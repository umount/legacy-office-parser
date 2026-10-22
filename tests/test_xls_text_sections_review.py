"""Independent fourth-section review: literal oracles and retained-size limits."""
import struct

import pytest

from legacy_office_parser import Limits, LimitExceededError
from legacy_office_parser.api import _validate_result
from legacy_office_parser._xls_formats import render_number, text_affixes
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
@pytest.mark.parametrize('raw', ['', 'plain', 'Ж😀;@"\\'])
@pytest.mark.parametrize('section,prefix,suffix', [
    ('@', '', ''), ('""@""', '', ''),
    ('"["@"]"', '[', ']'), (r'\[@\]', '[', ']'),
    ('"@;"@";@"', '@;', ';@'), (r'\;\@@\@\;', ';@', '@;'),
    (r'\"@\"', '"', '"'), (r'\\@\\', '\\', '\\'),
    ('"pre""fix"@"suf""fix"', 'prefix', 'suffix'),
    ('"Ω😀"@" Ж"', 'Ω😀', ' Ж'),
])
def test_literal_oracles_and_raw_retention(kind, raw, section, prefix, suffix):
    code = '0;0;0;' + section
    assert text_affixes(code) == (prefix, suffix)
    doc = _parse_workbook(source(code, raw, kind), Limits())
    item, = doc.sheets[0].cells
    assert (item.value, item.text, item.value_type, item.is_formula) == (
        raw, prefix + raw + suffix, 'string', kind == 'formula')
    assert doc.to_dict()['sheets'][0]['cells'][0]['value'] == raw
    _validate_result(doc, Limits())


@pytest.mark.parametrize('branch', ['yyyy', '[Red]', '""', '[$-409]0', '0x', '0.##'])
@pytest.mark.parametrize('position', range(3))
def test_unused_bad_numeric_branch_cannot_enable_text_expansion(branch, position):
    sections = ['0', '0', '0']
    sections[position] = branch
    code = ';'.join(sections) + ';"prefix"@'
    assert text_affixes(code) is None
    assert all(render_number(value, code) is None for value in (-1, 0, 1))
    assert _parse_workbook(source(code, 'raw', 'sst'), Limits()).sheets[0].cells[0].text == 'raw'


@pytest.mark.parametrize('section', ['@@', '@x', 'x@', '[Red]@',
                                   '@\\', '"unfinished@', '@;@', '_x@', '*x@'])
def test_invalid_fourth_section_never_changes_strings_or_validates_numbers(section):
    code = '0;0;0;' + section
    assert text_affixes(code) is None
    assert render_number(12, code) is None
    assert _parse_workbook(source(code, 'raw', 'label'), Limits()).sheets[0].cells[0].text == 'raw'


@pytest.mark.parametrize('kind', ['label', 'formula', 'sst'])
@pytest.mark.parametrize('section,display', [('@', 'raw'), ('""@""', 'raw'),
                                           ('"["@"]"', '[raw]'), ('', '')])
def test_full_retained_display_budget_and_no_publication_on_failure(monkeypatch, kind, section, display):
    import legacy_office_parser.xls as xls
    code, raw = '0;0;0;' + section, 'raw'
    repeats = 3 if kind == 'sst' else 1
    data = source(code, raw, kind, repeats)
    # FORMAT + sheet name + SST source (when applicable) + each retained value
    # + each different display. Identical displays and hidden text add no copy.
    per_cell = len(raw) + (len(display) if display != raw else 0)
    budget = len(code) + 1 + repeats * per_cell + (len(raw) if kind == 'sst' else 0)
    doc = _parse_workbook(data, Limits(max_text_chars=budget))
    assert [c.text for c in doc.sheets[0].cells] == [display] * repeats
    public_budget = 1 + repeats * per_cell
    _validate_result(doc, Limits(max_text_chars=public_budget))
    with pytest.raises(LimitExceededError):
        _validate_result(doc, Limits(max_text_chars=public_budget - 1))
    published = []
    original = xls.SpreadsheetCell

    def observe(*args, **kwargs):
        published.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(xls, 'SpreadsheetCell', observe)
    with pytest.raises(LimitExceededError):
        _parse_workbook(data, Limits(max_text_chars=budget - 1))
    assert len(published) < repeats


def test_exact_format_limit_and_numeric_branch_independence():
    code = '0;0;0;"' + 'x' * 55 + '"@'
    assert len(code) == 64
    assert text_affixes(code) == ('x' * 55, '')
    assert text_affixes(code + ' ') is None
    for value, expected in ((12, '12'), (-12, '12'), (0, '0')):
        assert render_number(value, code) == expected
