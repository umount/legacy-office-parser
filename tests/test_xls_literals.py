"""Explicit numeric affixes, tested through independent synthetic BIFF records."""
import math
import struct
import sys
from dataclasses import replace
from decimal import ROUND_DOWN, localcontext

import pytest

from legacy_office_parser._xls_formats import render_number, simple_date_format
from legacy_office_parser.errors import InvalidDocumentError, LimitExceededError
from legacy_office_parser.limits import Limits
from legacy_office_parser.xls import _parse_workbook
from test_xls_formats import parse_number, workbook


@pytest.mark.parametrize('kind', ['number', 'formula'])
@pytest.mark.parametrize('code,value,expected', [
    ('0.00" kg"', 12.5, '12.50 kg'),
    ('"USD "#,##0,', .125, 'USD 0'), ('0.0,,"M"', .125, '0.0M'),
    ('"USD "#,##0.00', 12345.5, 'USD 12,345.50'),
    ('"USD "#,##0.00', -12.5, '-USD 12.50'),
    ('"USD "0.00', -12.5, '-USD 12.50'),
    (r'0\%', 12.5, '13%'),
    ('0"days"', 12.5, '13days'),
    ('0"%"', .125, '0%'),
    ('0.00"%"', .125, '0.13%'),
    (r'0.00\%', .125, '0.13%'),
    ('0.00"USD"', .125, '0.13USD'),
    (r'0.00\d', .125, '0.13d'),
    ('0.00%" growth"', .125, '12.50% growth'),
    ('"%"0.00%', .125, '%12.50%'),
    (r'\%0.00%\%', -.125, '-%12.50%%'),
    ('"rate "0.00%"%"', -.125, '-rate 12.50%%'),
    ('"mass "0.00E+00" kg"', -12345, '-mass 1.23E+04 kg'),
    ('"mass "0.0e-000" kg"', .0012, 'mass 1.2e-003 kg'),
    ('0.00E+00"%"', .125, '1.25E-01%'),
    (r'0.00E+00\%', .125, '1.25E-01%'),
    (r'\U\S\D\ 0.00\ \k\g', -12.5, '-USD 12.50 kg'),
    ('"ID "0.00" units"', 12.5, 'ID 12.50 units'),
    ('""0.00" kg"', 12.5, '12.50 kg'),
    (r'""0.00\%', .125, '0.13%'),
    ('""0"days"', 12.5, '13days'),
    ('""0.00" руб."', 12.5, '12.50 руб.'),
    ('""""0.00""""', 12.5, '12.50'),
    ('"A""B"0"C""D"', 12, 'AB12CD'),
    (r'\"0\"', 12, '"12"'),
    (r'\\0\\', 12, '\\12\\'),
    ('"\\"0', 12, '\\12'),
    ('"[Red];[$-409]@_*%"0"yyyy"', 12, '[Red];[$-409]@_*%12yyyy'),
    (r'\;0\;', 12, ';12;'),
    ('"0.00E+00"0"#,##0%"', 12, '0.00E+0012#,##0%'),
    ('"USD "0.00', -0.0, 'USD 0.00'),
    ('"USD "0.00', -.0001, 'USD 0.00'),
    ('"rate "0.00%', -.000001, 'rate 0.00%'),
    ('"mass "0.00E+00', -0.0, 'mass 0.00E+00'),
    ('"-"0.00', -12.5, '--12.50'),
])
def test_literal_biff_display(code, value, expected, kind):
    doc = parse_number(value, 164, code, kind)
    cell = doc.sheets[0].cells[0]
    assert struct.pack('<d', cell.value) == struct.pack('<d', value)
    assert (cell.value_type, cell.text) == ('number', expected)
    assert expected in doc.text
    assert cell.is_formula == (kind == 'formula') and cell.formula is None
    assert not any('format' in warning.lower() for warning in doc.warnings)
    assert len(doc.warnings) == (1 if kind == 'formula' else 0)


@pytest.mark.parametrize('kind', ['rk', 'mulrk'])
@pytest.mark.parametrize('code,expected', [
    ('"USD "#,##0.00', '-USD 12,345.00'),
    (r'""0\%', '-12345%'),
    ('"n="0.00E+00" units"', '-n=1.23E+04 units'),
])
def test_literal_integer_records(code, expected, kind):
    doc = parse_number(-12345, 164, code, kind)
    cell = doc.sheets[0].cells[0]
    assert type(cell.value) is int and cell.value == -12345
    assert (cell.value_type, cell.text) == ('number', expected)
    assert not doc.warnings


@pytest.mark.parametrize('kind', ['number', 'formula'])
@pytest.mark.parametrize('code', [
    '"kg"', '"0.00%"', r'\0', '""',
    '"unterminated', '0"unterminated', '"USD "0"',
    '\\', '0\\', '"USD "0\\',
    '0"x"0', '0""0', '0."x"00', '0"x".00', r'0\.00',
    '#,"x"##0', '0.00"x"E+00', '0E+"x"00', '0E+0""0',
    '0"%"%', r'0\%%', '"USD "0"x"0',
    '0" kg";', '[>0]"USD "0',
    '[$-409]0" kg"', '_("USD "0_)', '* "USD "0',
    '$0.00', 'USD 0.00', '0.00 kg', ' "USD "0', '0" kg" ',
    '"USD "$0',
    '"USD "General', 'General" kg"', '"USD "0.##',
    '"USD "0.0000000000000000', '0E+0000" kg"', '0.00E+00%" kg"',
    '"USD "yyyy-mm-dd', 'yyyy"days"mm', '0"days"yyyy',
])
def test_literal_rejections_keep_raw_and_warn(code, kind):
    assert render_number(.125, code) is None
    doc = parse_number(.125, 164, code, kind)
    cell = doc.sheets[0].cells[0]
    assert (cell.value, cell.value_type, cell.text) == (.125, 'number', '0.125')
    assert sum('Unsupported or ambiguous' in w for w in doc.warnings) == 1


@pytest.mark.parametrize('code', ['"' + 'x' * 61 + '"0', '0"' + 'x' * 61 + '"',
                                  r'\x' * 30 + '"x"0'])
def test_original_format_length_bound(code):
    assert len(code) == 64
    assert render_number(1, code) is not None
    doc = parse_number(1, 164, code)
    assert not doc.warnings
    for oversized in (code + '""', '"' + 'x' * 62 + '"0', '""' * 32 + '0'):
        assert len(oversized) > 64
        assert render_number(1, oversized) is None
        doc = parse_number(1, 164, oversized)
        assert doc.sheets[0].cells[0].text == '1.0'
        assert any('Unsupported or ambiguous' in w for w in doc.warnings)


@pytest.mark.parametrize('kind', ['number', 'formula'])
def test_literal_output_budget(kind):
    code = '"USD "0.00" kg"'
    data = workbook(-12.5, 164, code, kind)
    expected = '-USD 12.50 kg'
    budget = len(code) + 1 + len(expected)  # FORMAT string, sheet name, display.
    doc = _parse_workbook(data, replace(Limits(), max_text_chars=budget))
    assert doc.sheets[0].cells[0].text == expected
    with pytest.raises(LimitExceededError):
        _parse_workbook(data, replace(Limits(), max_text_chars=budget - 1))


def test_literals_private_decimal_context_and_extremes():
    cases = [
        (1.235, '"USD "0.00', 'USD 1.24'),
        (.125, '0.00"%"', '0.13%'),
        (.125, '"rate "0.00%', 'rate 12.50%'),
        (-5e-324, '"n="0.00E+00', '-n=5.00E-324'),
        (sys.float_info.max, '0.00E+00" kg"', '1.80E+308 kg'),
    ]
    with localcontext() as ctx:
        ctx.prec, ctx.rounding, ctx.Emin, ctx.Emax = 2, ROUND_DOWN, -2, 2
        ctx.clamp = 1
        for signal in ctx.traps:
            ctx.traps[signal] = True
        ctx.clear_flags()
        for value, code, expected in cases:
            assert render_number(value, code) == expected
        text = render_number(sys.float_info.max, '"n="#,##0.000000000000000%" units"')
        assert text.startswith('n=17,976,931')
        assert text.endswith('.000000000000000% units') and len(text) < 514
        assert not any(ctx.flags.values())


@pytest.mark.parametrize('value', [math.nan, math.inf, -math.inf])
def test_nonfinite_literal_values(value):
    assert render_number(value, '"USD "0.00') is None
    with pytest.raises(InvalidDocumentError):
        parse_number(value, 164, '"USD "0.00')


@pytest.mark.parametrize('code,value,expected', [
    ('yyyy-mm-dd', 61, '1900-03-01'),
    ('yyyy"-"mm"-"dd', 45351, '2024-02-29'),
    (r'yyyy\-mm\-dd', 45351, '2024-02-29'),
    (r'hh\:mm', .5, '12:00:00'),
])
def test_date_recognition_unchanged(code, value, expected):
    assert render_number(value, code) is None
    assert simple_date_format(code)
    cell = parse_number(value, 164, code).sheets[0].cells[0]
    assert (cell.value, cell.value_type, cell.text) == (expected, 'date', expected)
