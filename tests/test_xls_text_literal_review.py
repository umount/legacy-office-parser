"""Independent literal-only fourth-section value and resource regressions."""
import struct
from decimal import localcontext

import pytest

from legacy_office_parser import Limits, LimitExceededError
from legacy_office_parser.api import _validate_result
from legacy_office_parser._xls_formats import render_number, text_affixes, text_literal
from legacy_office_parser.xls import _parse_workbook
from test_xls import book, cell, formula, rec, special, string


def source(code, raw, kind, repeats=1):
    globals_ = rec(0xE0, struct.pack('<HH', 0, 164) + bytes(16))
    globals_ += rec(0x41E, struct.pack('<H', 164) + string(code))
    if kind == 'sst':
        globals_ += rec(0xFC, struct.pack('<II', repeats, 1) + string(raw))
        body = b''.join(cell(0xFD, row, 0, bytes(4)) for row in range(repeats))
    elif kind == 'formula':
        body = formula(special(0)) + rec(0x207, string(raw))
    else:
        body = cell(0x204, payload=string(raw))
    return book([('S', 0, body)], globals_)


@pytest.mark.parametrize('kind', ['label', 'formula', 'sst'])
@pytest.mark.parametrize('raw', ['', 'retained', 'Ж😀;@"\\'])
@pytest.mark.parametrize('section,expected', [
    ('"fixed"', 'fixed'), ('""', ''), ('""""', ''),
    ('"@;"', '@;'), (r'\@\;', '@;'),
    (r'\"\\', '"\\'), ('"a""b"', 'ab'),
    ('"Ω😀"', 'Ω😀'), ('"=SUM(A1)"', '=SUM(A1)'),
])
def test_literal_replaces_only_display(kind, raw, section, expected):
    code = '0;0;0;' + section
    assert text_literal(code) == expected
    assert text_affixes(code) is None
    doc = _parse_workbook(source(code, raw, kind), Limits())
    item, = doc.sheets[0].cells
    assert (item.value, item.text, item.value_type, item.is_formula) == (
        raw, expected, 'string', kind == 'formula')
    encoded = doc.to_dict()['sheets'][0]['cells'][0]
    assert (encoded['value'], encoded['text']) == (raw, expected)
    _validate_result(doc, Limits())


@pytest.mark.parametrize('kind', ['label', 'formula', 'sst'])
@pytest.mark.parametrize('raw,section,display', [
    ('retained', '"retained"', 'retained'),
    ('', '""', ''), ('retained', '""', ''),
    ('retained', '"x"', 'x'), ('x', '"long replacement"', 'long replacement'),
])
def test_full_source_and_distinct_display_budget(monkeypatch, kind, raw, section, display):
    import legacy_office_parser.xls as xls
    code = '0;0;0;' + section
    repeats = 3 if kind == 'sst' else 1
    data = source(code, raw, kind, repeats)
    per_cell = len(raw) + (len(display) if display != raw else 0)
    budget = len(code) + 1 + repeats * per_cell + (len(raw) if kind == 'sst' else 0)
    doc = _parse_workbook(data, Limits(max_text_chars=budget))
    assert [c.text for c in doc.sheets[0].cells] == [display] * repeats
    if raw == display:
        assert all(c.text is c.value for c in doc.sheets[0].cells)
    _validate_result(doc, Limits(max_text_chars=1 + repeats * per_cell))
    published = []
    original = xls.SpreadsheetCell

    def observe(*args, **kwargs):
        published.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(xls, 'SpreadsheetCell', observe)
    with pytest.raises(LimitExceededError):
        _parse_workbook(data, Limits(max_text_chars=budget - 1))
    assert len(published) < repeats


@pytest.mark.parametrize('branch', ['yyyy', '[Red]', '""', '0x',  '[$-777]0'])
@pytest.mark.parametrize('position', range(3))
def test_literal_does_not_legitimize_bad_unused_numeric_branch(branch, position):
    sections = ['0', '0', '0']
    sections[position] = branch
    code = ';'.join(sections) + ';"replacement"'
    assert text_literal(code) is None
    assert all(render_number(v, code) is None for v in (-1, 0, 1))
    assert _parse_workbook(source(code, 'raw', 'label'), Limits()).sheets[0].cells[0].text == 'raw'


@pytest.mark.parametrize('section,expected', [('"literal"', 'literal'), ('""', ''),
                                            (r'\@', '@'), (r'\;', ';')])
def test_conditional_mask_with_literal_fourth(section, expected):
    code = '[>0]0;[<0]0;0;' + section
    assert text_literal(code) == expected
    assert _parse_workbook(source(code, 'raw', 'formula'), Limits()).sheets[0].cells[0].text == expected


@pytest.mark.parametrize('section', ['literal',    '"unterminated',
                                   '"x"\\', '"x";"y"', '"x"0', '[$-409]"x"'])
def test_bad_literal_section_keeps_raw(section):
    code = '0;0;0;' + section
    assert text_literal(code) is None
    assert render_number(1, code) is None
    assert _parse_workbook(source(code, 'raw', 'sst'), Limits()).sheets[0].cells[0].text == 'raw'


def test_placeholder_grammar_stays_distinct_and_length_is_bounded():
    assert text_literal('0;0;0;"x"@') is None
    assert text_affixes('0;0;0;"x"@') == ('x', '')
    code = '0;0;0;"' + 'x' * 56 + '"'
    assert len(code) == 64 and text_literal(code) == 'x' * 56
    assert text_literal(code + ' ') is None


def test_numeric_values_signs_and_hostile_decimal_context_are_unaffected():
    code = '0.0;0.0;0.0;"replacement"'
    with localcontext() as context:
        context.prec = 1
        for signal in context.traps:
            context.traps[signal] = True
        context.clear_flags()
        assert text_literal(code) == 'replacement'
        for value, expected in ((1.25, '1.3'), (-1.25, '1.3'), (0.0, '0.0'), (-0.0, '0.0')):
            assert render_number(value, code) == expected
        assert not any(context.flags.values())
