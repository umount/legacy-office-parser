"""Sign sections exercised through independently assembled BIFF records."""
import struct
from dataclasses import replace
from decimal import ROUND_DOWN, localcontext

import pytest

from legacy_office_parser._xls_formats import render_number, simple_date_format
from legacy_office_parser.errors import LimitExceededError
from legacy_office_parser.limits import Limits
from legacy_office_parser.xls import _parse_workbook
from test_xls_formats import parse_number, record, workbook


@pytest.mark.parametrize('kind', ['number', 'formula'])
@pytest.mark.parametrize('code,value,expected', [
    ('0.00;[Red]-0.00', -12.345, '-12.35'),
    ('0;0,', 12.5, '13'), ('0;0,', -12.5, '0'), ('0;0,', 0.0, '0'),
    ('0.00;(0.00);"zero"', -.001, '(0.00)'),
    ('0.00;(0.00);"zero"', 0, 'zero'),
    ('0.00;0.00;"zero";@', -12.5, '12.50'),
    (r'0.00;[RED]\(0.00\);"zero"', -.001, '(0.00)'),
    (r'0.00;[RED]\-0.00;"zero"', -12.5, '-12.50'),
    ('0;0;"""""!"', 0, '!'),
    ('0.00;[Red]-0.00', 12.345, '12.35'),
    ('0%;0%', -.125, '13%'),
    ('0%;0%', 0, '0%'),
    ('"USD "0;0', 12.5, 'USD 13'),
    ('[Red]0" kg"', 12.5, '13 kg'),
    ('[Red]0%', -.125, '-13%'),
    ('+0.0;(0.00)', -12.345, '(12.35)'),
    ('+0.0;(0.00)', 12.345, '+12.3'),
    ('0;0-', -12.5, '13-'),
    ('0;+0', -12.5, '+13'),
    ('0;"USD "-0.00', -12.5, 'USD -12.50'),
    ('0;("USD "0.00)', -12.5, '(USD 12.50)'),
    ('0;0', -12.5, '13'),  # Never invent a minus in section two.
    ('+0.00;(0.00);"zero";@', -0.0, 'zero'),
    ('+0.00;(0.00);"zero"', 0.0, 'zero'),
    ('+0.00;(0.00);"zero"', -.0001, '(0.00)'),
    ('+0.00;(0.00);"zero"', .0001, '+0.00'),
    ('0;-0;"zero"', -.5, '-1'),
    ('0;-0;"zero"', .5, '1'),
    ('0;-0;"zero"', -.49, '-0'),
    ('0.00%;-0.00%;"zero"', -.000001, '-0.00%'),
    ('0.00;-0.00', -0.0, '0.00'),
    ('0.00;-0.00', 0.0, '0.00'),
    ('0.0E+00;(0.0E-000);0', -1200, '(1.2E003)'),
    ('0.00E+00;-0.00E+00;0', -5e-324, '-5.00E-324'),
    ('0.0E+00;(0.0E+00);0', -9999, '(1.0E+04)'),
    ('0;0;[Blue]"none"', 0, 'none'),
    (r'0;0;\z\e\r\o', 0, 'zero'),
    ('0;0;""";""@"', 0, ';@'),
    ('0;0;0.00', -0.0, '0.00'),
    ('General;General;General;@', -12.5, '12.5'),
    ('General;General;General', -0.0, '-0.0'),
    ('General', -0.0, '-0.0'),
    ('General', -12.5, '-12.5'),
    ('[Red]General;[Blue]0', 12.5, '12.5'),
    ('"a;b"0;("c;d"0);"z;z";@', -12, '(c;d12)'),
    (r'\;0;\;0;"zero"', -12, ';12'),
    (r'\"0;(\"0);"zero"', -12, '("12)'),
    ('"\\"0;0;"zero"', 12, '\\12'),
    (r'\\0;0;"zero"', 12, '\\12'),
    ('0;"[>0];[$-409]"0;"yyyy"', -12, '[>0];[$-409]12'),
    ('0;0;"yyyy"', 0, 'yyyy'),
    ('-0', -12, '--12'),
    ('(0)', -12, '-(12)'),
    ('+0.0E+00-', 12, '+1.2E+01-'),
])
def test_sections_biff(code, value, expected, kind):
    doc = parse_number(value, 164, code, kind)
    cell = doc.sheets[0].cells[0]
    assert struct.pack('<d', cell.value) == struct.pack('<d', value)
    assert (cell.value_type, cell.text) == ('number', expected)
    assert expected in doc.text
    assert cell.is_formula == (kind == 'formula') and cell.formula is None
    assert len(doc.warnings) == (1 if kind == 'formula' else 0)
    assert not any('format' in w.lower() for w in doc.warnings)


@pytest.mark.parametrize('color', [
    'Black', 'Blue', 'Cyan', 'Green', 'Magenta', 'Red', 'White', 'Yellow', 'rEd',
])
def test_standard_colors(color):
    assert render_number(-12, f'[{color}]0;[{color}](0)') == '(12)'


@pytest.mark.parametrize('kind', ['rk', 'mulrk'])
@pytest.mark.parametrize('value,expected', [(12345, '+12,345'), (-12345, '(12,345)'), (0, 'nil')])
def test_sections_integer_records(kind, value, expected):
    doc = parse_number(value, 164, '+#,##0;(#,##0);"nil";@', kind)
    cell = doc.sheets[0].cells[0]
    assert type(cell.value) is int and cell.value == value
    assert cell.text == expected and cell.value_type == 'number'
    assert not doc.warnings


@pytest.mark.parametrize('kind', ['number', 'formula'])
@pytest.mark.parametrize('value', [12.5, -12.5, 0.0])
@pytest.mark.parametrize('code', [
    '0;0;0;@;0',
    '0;0;0; @', '0;0;0;"@"', r'0;0;0;\@', '0;0;0;[Red]@',
    '0;0;0;"text"@', '0;@', '@;0', '0;0;@',
    '0;[Orange]0', '0;[Color3]0', '0;[Red][Blue]0', '0;0[Red]',
    '0;[>0]0', '0;0;[=0]0', '0;[$-409]0',
    '0;yyyy-mm-dd', 'yyyy-mm-dd;0', '0;0;yyyy-mm-dd',
    '0;"hidden"', '"hidden";0', '0;0;""', '0;0;""""',
    '0;0;-', '0;0;()', '0;0;[Red]', '0;0;"zero"-',
    '0;0;"unfinished', '0;0;\\', '0;0;"x"\\',
    '0;0;"x";"@', '0;0;0;@\\',
    '0;0+0', '0;0(0)', '0;0E+"x"00', '0;0.00E+00%',
    '0;0.0000000000000000', '0;0E+0000', '0;0.##',
    '0;General"x"', '0;-General', '0;_(0)', '0;*0',
])
def test_all_sections_validated_even_when_unused(code, value, kind):
    assert render_number(value, code) is None
    doc = parse_number(value, 164, code, kind)
    cell = doc.sheets[0].cells[0]
    assert (cell.value, cell.value_type, cell.text) == (value, 'number', str(value))
    assert sum('Unsupported or ambiguous' in w for w in doc.warnings) == 1


@pytest.mark.parametrize('kind', ['number', 'formula'])
def test_whole_format_and_display_limits(kind):
    code = '"' + 'x' * 55 + '"0;0;0;@'
    assert len(code) == 64
    assert render_number(1, code) == 'x' * 55 + '1'
    assert render_number(1, code + '0') is None
    assert render_number(1, code.replace('x', 'xx', 1)) is None
    expected = 'x' * 55 + '1'
    data = workbook(1, 164, code, kind)
    budget = len(code) + 1 + len(expected)
    doc = _parse_workbook(data, replace(Limits(), max_text_chars=budget))
    assert doc.sheets[0].cells[0].text == expected
    with pytest.raises(LimitExceededError):
        _parse_workbook(data, replace(Limits(), max_text_chars=budget - 1))


def test_section_rounding_uses_private_context():
    with localcontext() as ctx:
        ctx.prec, ctx.rounding = 2, ROUND_DOWN
        for signal in ctx.traps:
            ctx.traps[signal] = True
        ctx.clear_flags()
        assert render_number(-1.235, '0;(0.00);"zero"') == '(1.24)'
        assert render_number(-.0001, '0;-0.00;"zero"') == '-0.00'
        assert not any(ctx.flags.values())


@pytest.mark.parametrize('kind', ['number', 'formula', 'rk', 'mulrk'])
def test_dates_stay_on_existing_path(kind):
    doc = parse_number(61, 164, 'yyyy-mm-dd', kind)
    cell = doc.sheets[0].cells[0]
    assert (cell.value_type, cell.text) == ('date', '1900-03-01')
    assert simple_date_format('yyyy-mm-dd')
    assert not simple_date_format('yyyy-mm-dd;0')


def test_text_with_fourth_passthrough_is_untouched():
    code = '0;(0);"zero";@'
    data = workbook(1, 164, code)
    coords = struct.pack('<HHH', 0, 0, 0)
    numeric = record(0x203, coords + struct.pack('<d', 1))
    label = record(0x204, coords + struct.pack('<HB', 7, 0) + b'literal')
    doc = _parse_workbook(data.replace(numeric, label), Limits())
    cell = doc.sheets[0].cells[0]
    assert (cell.value, cell.text, cell.value_type) == ('literal', 'literal', 'string')
    assert not doc.warnings
