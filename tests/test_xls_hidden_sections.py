"""Empty sections retain typed data and consume the existing budgets."""
import struct
from dataclasses import replace
from decimal import localcontext

import pytest

from legacy_office_parser._xls_formats import render_number, hides_text
from legacy_office_parser.errors import LimitExceededError
from legacy_office_parser.limits import Limits
from legacy_office_parser.xls import _parse_workbook
from test_xls_formats import parse_number, workbook, record


CASES = [
    (';', ('', '', '')), (';;', ('', '', '')), (';;;', ('', '', '')),
    ('0;', ('12', '', '0')), (';0', ('', '12', '')),
    ('0;;0', ('12', '', '0')), ('0;0;', ('12', '12', '')),
    (';;0', ('', '', '0')), (';0;', ('', '12', '')),
    ('0;;', ('12', '', '')), ('0;0;0;', ('12', '12', '0')),
    (';;;@', ('', '', '')), ('0.00;', ('12.00', '', '0.00')),
]


@pytest.mark.parametrize('code,expected', CASES)
@pytest.mark.parametrize('kind', ['number', 'formula', 'rk', 'mulrk'])
def test_empty_numeric_sections(code, expected, kind):
    for value, text in zip((12, -12, 0), expected):
        doc = parse_number(value, 164, code, kind)
        cell = doc.sheets[0].cells[0]
        assert (cell.value, cell.text, cell.value_type) == (value, text, 'number')
        assert cell.is_formula == (kind == 'formula')
        assert not any('format' in w.lower() for w in doc.warnings)


@pytest.mark.parametrize('code', ['', ';;;;', '0;0;0;@;0', '[>0]0;', ';[<0]0',
    '0;;yyyy', '0;;[Red]', '0;;""', '0;;\\', '0;;"bad', '0;;[$-409]0',
    '0;;0;""', '[>0]0;0;', '0;[Orange]0;', '0' * 65 + ';;;'])
def test_unsupported_empty_combinations(code):
    assert not hides_text(code)
    for value in (-12, 0, 12):
        assert render_number(value, code) is None


def string_workbook(code, kind='label', text='retained'):
    data = workbook(1, 164, code)
    coords = struct.pack('<HHH', 0, 0, 0)
    number = record(0x203, coords + struct.pack('<d', 1))
    encoded = struct.pack('<HB', len(text), 0) + text.encode('ascii')
    if kind == 'formula':
        cell = record(6, coords + b'\x00\x00\x00\x00\x00\x00\xff\xff' + bytes(6) + b'\x01\x00\xff')
        cell += record(0x207, encoded)
    else:
        cell = record(0x204, coords + encoded)
    return data.replace(number, cell)


@pytest.mark.parametrize('kind', ['label', 'formula'])
@pytest.mark.parametrize('code,expected', [(';;;', ''), ('0;0;0;', ''),
    (';;;@', 'retained'), (';;', 'retained'), ('0;;0', 'retained'),
    ('yyyy;;;', 'retained'), ('[>0]0;0;0;', 'retained')])
def test_string_fourth_section(code, expected, kind):
    doc = _parse_workbook(string_workbook(code, kind), Limits())
    cell = doc.sheets[0].cells[0]
    assert (cell.value, cell.text, cell.value_type, cell.is_formula) == (
        'retained', expected, 'string', kind == 'formula')


@pytest.mark.parametrize('kind', ['label', 'formula'])
def test_hidden_string_budget(kind):
    data = string_workbook(';;;', kind)
    budget = 3 + 1 + len('retained')
    assert _parse_workbook(data, replace(Limits(), max_text_chars=budget)).sheets[0].cells[0].text == ''
    with pytest.raises(LimitExceededError):
        _parse_workbook(data, replace(Limits(), max_text_chars=budget - 1))


def test_hidden_numeric_budget_and_decimal_context():
    data = workbook(12, 164, ';;;')
    assert _parse_workbook(data, replace(Limits(), max_text_chars=4)).sheets[0].cells[0].text == ''
    with pytest.raises(LimitExceededError):
        _parse_workbook(data, replace(Limits(), max_text_chars=3))
    with localcontext() as ctx:
        ctx.prec = 1
        for signal in ctx.traps:
            ctx.traps[signal] = True
        ctx.clear_flags()
        for value in (-0.0, 0.0, -5e-324, 1e308):
            assert render_number(value, ';;;') == ''
        assert not any(ctx.flags.values())


@pytest.mark.parametrize('value,is_error,expected', [(1, 0, 'TRUE'), (0, 0, 'FALSE'),
                                                    (7, 1, '#DIV/0!')])
def test_boolean_and_error_cells_remain_outside_numeric_text_scope(value, is_error, expected):
    data = workbook(1, 164, ';;;')
    coords = struct.pack('<HHH', 0, 0, 0)
    numeric = record(0x203, coords + struct.pack('<d', 1))
    special = record(0x205, coords + bytes((value, is_error)))
    doc = _parse_workbook(data.replace(numeric, special), Limits())
    assert doc.sheets[0].cells[0].text == expected


def test_length_boundary_and_hidden_sst_occurrences():
    code = '"' + 'x' * 58 + '"0;;;'
    assert len(code) == 64 and render_number(-12, code) == ''
    assert render_number(-12, 'x' + code) is None
    # SST decoding charges the retained source once; each reference is charged
    # again, even though every display is hidden.
    data = workbook(1, 164, ';;;')
    coords = struct.pack('<HHH', 0, 0, 0)
    numeric = record(0x203, coords + struct.pack('<d', 1))
    text = b'retained'
    sst = record(0xfc, struct.pack('<IIHB', 2, 1, len(text), 0) + text)
    # Insert before BOUNDSHEET and correct its sheet offset.
    pos = 0
    while struct.unpack_from('<H', data, pos)[0] != 0x85:
        pos += 4 + struct.unpack_from('<H', data, pos + 2)[0]
    patched = bytearray(data)
    offset, = struct.unpack_from('<I', patched, pos + 4)
    struct.pack_into('<I', patched, pos + 4, offset + len(sst))
    data = bytes(patched[:pos]) + sst + bytes(patched[pos:])
    cells = record(0xfd, coords + bytes(4))
    cells += record(0xfd, struct.pack('<HHHI', 1, 0, 0, 0))
    data = data.replace(numeric, cells)
    budget = 4 + 3 * len(text)
    doc = _parse_workbook(data, replace(Limits(), max_text_chars=budget))
    assert [(c.value, c.text) for c in doc.sheets[0].cells] == [('retained', '')] * 2
    with pytest.raises(LimitExceededError):
        _parse_workbook(data, replace(Limits(), max_text_chars=budget - 1))


def test_former_optional_decimal_rejection_now_supported():
    for value, expected in ((.125, '0.1'), (-.125, ''), (0, '0')):
        assert parse_number(value, 164, '0.0;;0').sheets[0].cells[0].text == expected


@pytest.mark.parametrize('kind', ['number', 'formula'])
def test_former_literal_rejection_now_supported(kind):
    for value, expected in ((.125, '0 kg'), (-.125, ''), (0, '0 kg')):
        doc = parse_number(value, 164, '0" kg";', kind)
        assert doc.sheets[0].cells[0].text == expected
        assert not any('format' in warning.lower() for warning in doc.warnings)
