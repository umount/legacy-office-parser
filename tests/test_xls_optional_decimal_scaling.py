"""Literal synthetic expectations for optional decimals scaled before rounding."""
import math
import os
import struct
import sys
from decimal import Inexact, Overflow, ROUND_DOWN, Rounded, Underflow, localcontext

import pytest

from legacy_office_parser import Limits, parse_xls
from legacy_office_parser._xls_formats import render_number
from legacy_office_parser.errors import LimitExceededError
from test_xls import ole_workbook
from test_xls_formats import workbook


CASES = [
    ('0.##%', .12345, '12.35%'), ('0.##%', -.12345, '-12.35%'),
    ('0.##%', .125, '12.5%'), ('0.#%', .01234, '1.2%'),
    ('#,##0.##%', 12.34567, '1,234.57%'),
    ('0.###############%', .00125, '0.125%'),
    ('0.##%;(0.##%)', -.125, '(12.5%)'),
    ('[Red]0.##%', .125, '12.5%'),
    ('0.##%;0.##%;"zero"', 0, 'zero'),
    ('0.##%;0.##%;;@', 0, ''),
    ('"rate "0.##%" net"', .125, 'rate 12.5% net'),
    ('0.##,', 1234.5, '1.23'), ('0.##,', -1234.5, '-1.23'),
    ('0.##,', 1250, '1.25'), ('0.##,', 1230, '1.23'),
    ('#,##0.##,', 1234567, '1,234.57'),
    ('0.###,,"M"', 1234000, '1.234M'),
    ('0.###,,,"B"', 1234000000, '1.234B'),
    ('0.##,;(0.##,)', -1250, '(1.25)'),
    ('0.##,"%"', 1250, '1.25%'),
    ('0.##\\%', .125, '0.13%'),
    ('[>=1]0.##,;0.##%', .125, '12.5%'),
    ('[>=1]0.##,;0.##%', 1250, '1.25'),
]


@pytest.mark.parametrize('code,value,expected', CASES)
@pytest.mark.parametrize('kind', ['number', 'formula'])
def test_public_scaled_display_preserves_raw_value(code, value, expected, kind):
    doc = parse_xls(ole_workbook(workbook(value, 164, code, kind)))
    cell, = doc.sheets[0].cells
    assert cell.text == render_number(value, code) == expected
    assert struct.pack('<d', cell.value) == struct.pack('<d', value)
    assert cell.value_type == 'number'
    assert cell.is_formula == (kind == 'formula') and cell.formula is None
    assert len(doc.warnings) == (kind == 'formula')
    assert doc.to_dict()['sheets'][0]['cells'][0]['text'] == expected


@pytest.mark.parametrize('code,value,expected', [
    ('0.##%', 0, '0.%'), ('0.##%', -0.0, '0.%'), ('0.##%', .01, '1.%'),
    ('0.##%', .099999, '10.%'), ('0.##%', -.099999, '-10.%'),
    ('0.##%', .000001, '0.%'), ('0.##,', 1000, '1.'),
    ('0.##,', 9999.9, '10.'), ('0.##,', -9999.9, '-10.'),
    ('0.##,,', 1000000, '1.'), ('0.##,,', 5e-324, '0.')])
def test_integral_after_scaling_preserves_raw_bits(code, value, expected):
    doc = parse_xls(ole_workbook(workbook(value, 164, code)))
    cell, = doc.sheets[0].cells
    assert render_number(value, code) == cell.text == expected
    assert struct.pack('<d', cell.value) == struct.pack('<d', value)
    assert not doc.warnings


@pytest.mark.parametrize('kind', ['rk', 'mulrk'])
def test_integer_storage_preserved_on_scaled_success(kind):
    cell, = parse_xls(ole_workbook(workbook(1250, 164, '0.##,', kind))).sheets[0].cells
    assert type(cell.value) is int and cell.value == 1250
    assert cell.text == '1.25'


@pytest.mark.parametrize('code', [
    '0.##%,', '0.##%%',
    '[$-777]0.##%',
    '0.##%;0.##%;0;0.##%',
    '0.################%', '0.################,',
])
def test_unsupported_masks_including_unused_sections(code):
    doc = parse_xls(ole_workbook(workbook(.125, 164, code)))
    assert render_number(.125, code) is None
    assert doc.sheets[0].cells[0].text == '0.125'
    assert sum('Unsupported or ambiguous' in w for w in doc.warnings) == 1


@pytest.mark.parametrize('code,value,expected', [
    ('[>=0]0.##%;0.##%', -.125, '12.5%'), ('[>=0]0.##,;0.##,', -1250, '1.25')])
def test_negative_condition_uses_magnitude(code, value, expected):
    assert render_number(value, code) == expected


def test_rounding_before_trimming_and_integral_display():
    assert render_number(1.25, '0.##,') == '0.'  # scale then round, not vice versa
    assert render_number(.00005, '0.##%') == '0.01%'
    assert render_number(-.00005, '0.##%') == '-0.01%'
    assert render_number(math.nextafter(.00005, 0), '0.##%') == '0.%'
    assert render_number(math.nextafter(.00005, 1), '0.##%') == '0.01%'
    assert render_number(5, '0.##,') == '0.01'
    assert render_number(math.nextafter(5, 0), '0.##,') == '0.'
    assert render_number(math.nextafter(5, 6), '0.##,') == '0.01'


def test_context_and_resource_bounds():
    with localcontext() as ctx:
        ctx.prec, ctx.Emax, ctx.Emin, ctx.rounding = 1, 1, -1, ROUND_DOWN
        for signal in (Inexact, Rounded, Overflow, Underflow):
            ctx.traps[signal] = True
        ctx.clear_flags()
        before = (dict(ctx.flags), dict(ctx.traps), ctx.prec, ctx.Emax, ctx.Emin, ctx.rounding)
        for code, value, expected in CASES:
            assert render_number(value, code) == expected
        assert render_number(sys.float_info.max, '0.###############%').endswith('.%')
        assert before == (dict(ctx.flags), dict(ctx.traps), ctx.prec, ctx.Emax, ctx.Emin, ctx.rounding)
    mask = '0.##%"' + 'x' * 57 + '"'
    assert len(mask) == 64 and render_number(.125, mask) == '12.5%' + 'x' * 57
    assert render_number(.125, mask[:-1] + 'x"') is None
    assert render_number(1, '0.#' + ',' * 61) == '0.'
    assert render_number(1, '0.#' + ',' * 100000) is None
    data = ole_workbook(workbook(.125, 164, '0.##%'))
    # Five FORMAT characters, one sheet-name character, five display characters.
    assert parse_xls(data, limits=Limits(max_text_chars=11)).sheets[0].cells[0].text == '12.5%'
    with pytest.raises(LimitExceededError):
        parse_xls(data, limits=Limits(max_text_chars=10))


@pytest.mark.skipif(os.environ.get('XLS_OPTIONAL_SCALING_LO') != '1',
                    reason='opt-in independent preserved-source XLS/Calc oracle')
def test_literal_preserved_source_oracle(tmp_path):
    from _xls_format_oracle import generate_preserved
    generate_preserved(tmp_path, CASES)


@pytest.mark.parametrize('fourth,expected', [('', ''), ('"prefix "@', 'prefix retained'),
                                             ('"literal"', 'literal'), ('@', 'retained')])
def test_numeric_core_support_composes_with_string_helpers(fourth, expected):
    from test_xls_hidden_sections import string_workbook
    code = '0.###,;0.###,;0;' + fourth
    doc = parse_xls(ole_workbook(string_workbook(code)))
    assert doc.sheets[0].cells[0].value == 'retained'
    assert doc.sheets[0].cells[0].text == expected


@pytest.mark.parametrize('fourth,expected', [
    ('', ''), ('"prefix "@', 'prefix retained'), ('"literal"', 'literal'),
])
def test_preexisting_mandatory_scaling_string_helpers_still_work(fourth, expected):
    from test_xls_hidden_sections import string_workbook

    code = '0.000,;0.000,;0;' + fourth
    cell, = parse_xls(ole_workbook(string_workbook(code))).sheets[0].cells
    assert (cell.value, cell.text) == ('retained', expected)
