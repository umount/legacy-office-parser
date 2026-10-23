"""Ordinary fourth-section affixes preserve raw strings and bound expansion."""
from dataclasses import replace
import struct

import pytest

from legacy_office_parser._xls_formats import render_number, text_affixes
from legacy_office_parser.errors import LimitExceededError
from legacy_office_parser.limits import Limits
from legacy_office_parser.xls import _parse_workbook
from test_xls_formats import workbook, record
from test_xls_hidden_sections import string_workbook

CASES = [
    ('0;0;0;"Name: "@', 'Name: retained'),
    ('0;0;0;@" kg"', 'retained kg'),
    ('0;0;0;"["@"]"', '[retained]'),
    (r'0;0;0;\[@\]', '[retained]'),
    (';;;"a;"@";b"', 'a;retained;b'),
    ('0;0;0;"@"@"@"', '@retained@'),
    (r'0;0;0;\@@\@', '@retained@'),
    ('0;0;0;""@""', 'retained'),
    ('0;0;0;"Ω "@" €"', 'Ω retained €'),
]


@pytest.mark.parametrize('code,expected', CASES)
@pytest.mark.parametrize('kind', ['label', 'formula'])
def test_string_affixes(code, expected, kind):
    doc = _parse_workbook(string_workbook(code, kind), Limits())
    cell = doc.sheets[0].cells[0]
    assert (cell.value, cell.text, cell.value_type, cell.is_formula) == (
        'retained', expected, 'string', kind == 'formula')
    assert doc.to_dict()['sheets'][0]['cells'][0]['text'] == expected
    assert expected in doc.text
    budget = len(code) + 1 + len('retained') + (len(expected) if expected != 'retained' else 0)
    _parse_workbook(string_workbook(code, kind), replace(Limits(), max_text_chars=budget))
    with pytest.raises(LimitExceededError):
        _parse_workbook(string_workbook(code, kind), replace(Limits(), max_text_chars=budget - 1))


@pytest.mark.parametrize('code', ['0;0;0;@@',
    '0;0;0;@x',
    '0;0;0;@\\', '0;0;0;"bad@', '0;0;0;@;0', '0;yyyy;0;"x"@',
    '0;[$-777]0;0;"x"@',  '0;0;0;"'+'x'*64+'"@'])
def test_unsupported_text_retains_raw(code):
    assert text_affixes(code) is None
    doc = _parse_workbook(string_workbook(code), Limits())
    assert doc.sheets[0].cells[0].text == 'retained'


def test_numeric_routing_and_negative_conditions_unchanged():
    for value, expected in ((12, '12'), (-12, '12'), (0, '0')):
        assert render_number(value, '0;0;0;"text"@') == expected
    assert render_number(-12, '[>0]0;0;0;"text"@') == '12'


def test_repeat_sst_expansion_budget():
    code = '0;0;0;"["@"]"'
    data = workbook(1, 164, code)
    coords = struct.pack('<HHH', 0, 0, 0)
    numeric = record(0x203, coords + struct.pack('<d', 1))
    raw = b'retained'
    sst = record(0xfc, struct.pack('<IIHB', 2, 1, len(raw), 0) + raw)
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
    budget = len(code) + 1 + len(raw) + 2 * (2 * len(raw) + 2)
    doc = _parse_workbook(data, replace(Limits(), max_text_chars=budget))
    assert [(c.value, c.text) for c in doc.sheets[0].cells] == [('retained', '[retained]')] * 2
    with pytest.raises(LimitExceededError):
        _parse_workbook(data, replace(Limits(), max_text_chars=budget - 1))


def test_maximum_format_length():
    code = '0;0;0;"' + 'x' * 55 + '"@'
    assert len(code) == 64
    assert text_affixes(code) == ('x' * 55, '')
    assert text_affixes(code + '""') is None


@pytest.mark.parametrize('kind', ['label', 'formula'])
def test_empty_stored_string(kind):
    code = '0;0;0;"["@"]"'
    data = string_workbook(code, kind, text='')
    doc = _parse_workbook(data, replace(Limits(), max_text_chars=len(code) + 3))
    cell = doc.sheets[0].cells[0]
    assert (cell.value, cell.text) == ('', '[]')
    with pytest.raises(LimitExceededError):
        _parse_workbook(data, replace(Limits(), max_text_chars=len(code) + 2))


@pytest.mark.parametrize('value,is_error,expected', [(1, 0, 'TRUE'), (7, 1, '#DIV/0!')])
def test_boolean_and_error_ignore_text_affixes(value, is_error, expected):
    data = workbook(1, 164, '0;0;0;"["@"]"')
    coords = struct.pack('<HHH', 0, 0, 0)
    numeric = record(0x203, coords + struct.pack('<d', 1))
    special = record(0x205, coords + bytes((value, is_error)))
    doc = _parse_workbook(data.replace(numeric, special), Limits())
    assert doc.sheets[0].cells[0].text == expected
