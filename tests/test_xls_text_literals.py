"""Literal-only fourth sections: retained raw data, bounded replacement display."""
from dataclasses import replace
import json

import pytest

from legacy_office_parser import parse, parse_xls
from legacy_office_parser.cli import main
from legacy_office_parser._xls_formats import render_number, text_literal
from legacy_office_parser.errors import LimitExceededError
from legacy_office_parser.limits import Limits
from legacy_office_parser.xls import _parse_workbook
from test_xls import ole_workbook
from test_xls_text_sections_review import source

CASES = [
    ('0;0;0;"redacted"', 'redacted'),
    (r'0;0;0;\x\y', 'xy'),
    (';;;"a;b"', 'a;b'),
    ('0;0;0;"@"', '@'),
    (r'0;0;0;\@', '@'),
    ('0;0;0;""', ''),
    ('0;0;0;""""', ''),
    ('0;0;0;"Ω €"', 'Ω €'),
    (r'0;0;0;\"\\', '"\\'),
    ('0;0;0;"retained"', 'retained'),
]


@pytest.mark.parametrize('kind', ['label', 'formula', 'sst'])
@pytest.mark.parametrize('raw', ['retained', '', 'Ж😀;@"\\'])
@pytest.mark.parametrize('code,expected', CASES)
def test_literal_display_and_exact_budgets(code, expected, raw, kind):
    repeats = 3 if kind == 'sst' else 1
    data = source(code, raw, kind, repeats)
    # Source SST string, each retained raw occurrence, distinct display, mask,
    # and sheet name. Decoder charges UTF16 units; SST uses charge decoded chars.
    budget = len(code) + 1 + len(raw.encode('utf-16le')) // 2
    if kind == 'sst':
        budget += repeats * len(raw)
    budget += repeats * (len(expected) if expected != raw else 0)
    doc = _parse_workbook(data, replace(Limits(), max_text_chars=budget))
    for cell in doc.sheets[0].cells:
        assert (cell.value, cell.text, cell.value_type, cell.is_formula) == (
            raw, expected, 'string', kind == 'formula')
    with pytest.raises(LimitExceededError):
        _parse_workbook(data, replace(Limits(), max_text_chars=budget - 1))


@pytest.mark.parametrize('code', ['0;0;0;bare',
    '0;0;0;"unfinished', '0;0;0;\\', '0;0;0;"x";0',
    'yyyy;0;0;"x"', '0;[$-777]0;0;"x"', '0;[Orange]0;0;"x"',
     '0;0;[=0]0;"x"', '0;0;0;@', '0;0;0;"x"@'])
def test_no_guessing(code):
    assert text_literal(code) is None


@pytest.mark.parametrize('kind', ['label', 'formula', 'sst'])
def test_public_api_and_cli(tmp_path, capsys, kind):
    path = tmp_path / 'literal.xls'
    path.write_bytes(ole_workbook(source('0;0;0;"redacted"', 'secret', kind)))
    doc = parse(path)
    assert doc.to_dict() == parse_xls(path).to_dict()
    cell = doc.sheets[0].cells[0]
    assert cell.value == 'secret' and cell.text == 'redacted'
    assert cell.is_formula == (kind == 'formula')
    assert doc.text == 'S\nA1\tredacted'
    assert main([str(path), '--json']) == 0
    cell_json = json.loads(capsys.readouterr().out)['sheets'][0]['cells'][0]
    assert cell_json['value'] == 'secret' and cell_json['text'] == 'redacted'


def test_length_numeric_routing_and_fraction_deferral():
    code = '0;0;0;"' + 'x' * 56 + '"'
    assert len(code) == 64 and text_literal(code) == 'x' * 56
    assert text_literal(code + '""') is None
    for value, expected in ((12.5, '13'), (-12.5, '13'), (0, '0')):
        assert render_number(value, '0;0;0;"literal"') == expected
    for value in (-1.25, -.125, -0.0, 0.0, .125, 1, 1e30):
        assert render_number(value, '# ?/4') is None
    assert render_number(-12, '[>0]0;0;0;"literal"') == '12'


@pytest.mark.parametrize('kind', ['number', 'formula'])
@pytest.mark.parametrize('code', ['0;0;0;"@"', r'0;0;0;\@'])
@pytest.mark.parametrize('value,expected', [(12.5, '13'), (-12.5, '13'), (0.0, '0')])
def test_former_numeric_rejections_now_render(code, value, expected, kind):
    from test_xls_formats import parse_number
    doc = parse_number(value, 164, code, kind)
    cell = doc.sheets[0].cells[0]
    assert (cell.value, cell.text, cell.is_formula) == (value, expected, kind == 'formula')
    assert not any('format' in warning.lower() for warning in doc.warnings)


def test_former_empty_fourth_rejection_now_hides_strings():
    code = '0;;0;""'
    assert [render_number(value, code) for value in (-12, 0, 12)] == ['', '0', '12']
    assert text_literal(code) == ''
    assert _parse_workbook(source(code, 'raw', 'label'), Limits()).sheets[0].cells[0].text == ''


@pytest.mark.parametrize('branch', ['yyyy', '[Red]', '""', '[$-777]0', '0x'])
@pytest.mark.parametrize('position', range(3))
def test_unused_bad_numeric_branch_does_not_replace_text(branch, position):
    sections = ['0', '0', '0']
    sections[position] = branch
    code = ';'.join(sections) + ';"replacement"'
    assert text_literal(code) is None
    doc = _parse_workbook(source(code, 'original', 'sst'), Limits())
    assert doc.sheets[0].cells[0].text == 'original'
    assert all(render_number(value, code) is None for value in (-1, 0, 1))


@pytest.mark.parametrize('value,is_error,expected', [(1, 0, 'TRUE'), (7, 1, '#DIV/0!')])
def test_boolean_and_error_not_replaced(value, is_error, expected):
    import struct
    from test_xls_formats import workbook, record
    data = workbook(1, 164, '0;0;0;"replacement"')
    coords = struct.pack('<HHH', 0, 0, 0)
    numeric = record(0x203, coords + struct.pack('<d', 1))
    special = record(0x205, coords + bytes((value, is_error)))
    doc = _parse_workbook(data.replace(numeric, special), Limits())
    assert doc.sheets[0].cells[0].text == expected
