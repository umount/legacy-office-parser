"""Numeric policy regressions; literal expectations, no generated oracle outputs.

Normative syntax: MS-XLS 2.4.126, referring to ISO 29500 18.8.31:
https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-xls/300280fd-e4fe-4675-a924-4d383af48d3b
Placeholder/scale/alignment semantics:
https://support.microsoft.com/en-us/excel/review-guidelines-for-customizing-a-number-format
Nearest fraction and conditional-sign compatibility (not normative Excel ties):
https://help.libreoffice.org/latest/en-US/text/shared/01/05020301.html
https://github.com/LibreOffice/core/blob/master/include/svl/zformat.hxx

Focused Calc UNO and preserved-source XLS probes corroborate the compatible
cases below. Explicit policy differences: retain '.' with optional integral
results; fixed fractions use decimal half-up, not Calc's downward ties; nearest
fractions resolve actual stored binary64 neighbors, not fuzzy comparisons.
"""
import math
import os
import struct
import sys
from decimal import localcontext

import pytest

from legacy_office_parser import Limits, parse_xls
from legacy_office_parser._xls_formats import (
    _numeric_parts, _split_sections, render_number, text_affixes, text_literal,
)
from legacy_office_parser.errors import LimitExceededError
from legacy_office_parser.number_locale import NumberLocale
from test_xls import ole_workbook
from test_xls_formats import workbook


# Compatible cases are also checked independently by the opt-in Calc oracle.
CALC_CASES = [
    ('# ?/?', .456, ' 4/9'), ('# ??/??', 123.456, '123 31/68'),
    ('# ???/???', math.pi, '3  16/113'), ('# ?/?', .99, '1    '),
    ('# ?/?', -.001, '0    '), ('# ?/?;(# ?/?)', -.456, '( 4/9)'),
    ('"part: "# ??/??"!"', .456, 'part:  31/68!'),
    ('0.0#%', .1, '10.0%'), ('0.#0', 1.2, '1.20'),
    ('???.???', 1.2, '  1.2  '), ('0.??', 0, '0.  '),
    ('_(0.00_)', 1.2, ' 1.20 '), ('*x0.0', 1.2, '1.2'),
    ('[<0](0.0);0.00', -2, '(2.0)'),
    ('[<0]0.0;[<1]0.00;0.000', -2, '-2.0'),
    ('[<0]0.0;[>0]0.00;0.000', -2, '2.0'),
    ('[>10]0.0;[<-10]0.00;0.000', -2, '2.000'),
    ('[>0]0.0;0.00', 0, '0.0'),
    ('0;0;0;_(@_)', 'raw', ' raw '),
    ('0.###,;0.###,;0;"label "@', 'raw', 'label raw'),
    ('[>10]0;[<-10]0;0;[Red]"."@","', 'raw', '.raw,'),
]


@pytest.mark.parametrize('code,value,expected', [c for c in CALC_CASES if not isinstance(c[1], str)])
def test_composable_numeric_cores(code, value, expected):
    assert render_number(value, code) == expected
    doc = parse_xls(ole_workbook(workbook(value, 164, code)))
    cell, = doc.sheets[0].cells
    assert cell.text == expected
    assert struct.pack('<d', cell.value) == struct.pack('<d', value)
    assert not doc.warnings


@pytest.mark.parametrize('value,code,expected', [
    (0, '0.##', '0.'), (1, '0.##', '1.'), (9.999, '0.##', '10.'),
    (-.004, '0.##', '0.'), (1000, '[$$-409]0.##,%', '$100.%'),
    (1250, '[$$-409]0.##,%', '$125.%'),
    (1234567, '[$USD-409]0.0#,,%', 'USD123.46%'),
    (.0625, '0/8', '1/8'), (-.0625, '0/8', '-1/8'),
    (.9375, '0 0/8', '1 0/8'), (1.0625, '0 0/8', '1 1/8'),
    (.75, '# ?/?', ' 3/4'),
])
def test_explicit_rounding_and_decimal_point_policy(value, code, expected):
    assert render_number(value, code) == expected


def test_core_boundaries_and_explicit_locale_do_not_translate_literals():
    code = '"v1.2, "[$$-409]#,##0.0#".end,"'
    assert _numeric_parts(code) == ('v1.2, $', '#,##0.0#', '.end,')
    locale = NumberLocale(',', '\u00a0')
    assert render_number(-1234.5, code, display_locale=locale) == '-v1.2, $1\u00a0234,5.end,'
    assert render_number(-1234.5, code) == '-v1.2, $1,234.5.end,'
    assert render_number(1.25, 'General', display_locale=locale) == '1,25'
    assert render_number(1.25, '"v1.2,"', display_locale=locale) == 'v1.2,'
    assert render_number(.125, '"1.2,"0.0E+00".,"', display_locale=locale) == '1.2,1,3E-01.,'
    assert render_number(.5, '"1.2,"# ?/?', display_locale=locale) == '1.2, 1/2'
    assert text_affixes('0;0;0;"1.2,"@".,"') == ('1.2,', '.,')


def test_alignment_tokens_consume_semicolons_without_creating_sections():
    assert _split_sections('0_;') == ['0_;']
    assert render_number(1, '0_;') == '1 '
    assert _split_sections('0*;;0') == ['0*;', '0']
    assert render_number(1, '0*;;0') == '1'
    assert text_affixes('0;0;0;_(@_)') == (' ', ' ')
    assert text_literal('0;0;0;*x"literal"') == 'literal'
    assert text_affixes('[>10]0;[<-10]0;0;@') == ('', '')


def test_context_and_work_are_bounded_for_full_binary64_range():
    with localcontext() as ctx:
        ctx.prec, ctx.Emin, ctx.Emax, ctx.clamp = 1, -1, 1, 1
        for signal in ctx.traps:
            ctx.traps[signal] = True
        ctx.clear_flags()
        before = ctx.copy()
        assert render_number(5e-324, '# ?/?') == '0    '
        assert render_number(-5e-324, '0/8') == '0/8'
        for code in ('0.###############%', '#,##0.###############', '# ???/???', '0/999'):
            text = render_number(sys.float_info.max, code)
            assert text is not None and len(text) < 450
        assert not any(ctx.flags.values())
        assert (ctx.prec, ctx.Emin, ctx.Emax, ctx.clamp, ctx.traps) == (
            before.prec, before.Emin, before.Emax, before.clamp, before.traps)
    assert render_number(1, '0' * 65) is None
    assert render_number(.1, '# ????/????') is None
    assert render_number(1, '0.' + '#' * 16) is None


def test_added_alignment_characters_consume_display_budget():
    code, expected = '_(0.??_)', ' 1.  '
    # Leading alignment + number/point + two '?' blanks + trailing alignment.
    expected += ' '
    data = ole_workbook(workbook(1, 164, code))
    budget = len(code) + 1 + len(expected)
    assert parse_xls(data, limits=Limits(max_text_chars=budget)).sheets[0].cells[0].text == expected
    with pytest.raises(LimitExceededError):
        parse_xls(data, limits=Limits(max_text_chars=budget - 1))


@pytest.mark.skipif(os.environ.get('XLS_NUMERIC_COMPLETENESS_LO') != '1',
                    reason='opt-in preserved FORMAT LibreOffice oracle')
def test_focused_preserved_source_libreoffice_probe(tmp_path):
    from _xls_format_oracle import generate_preserved
    generate_preserved(tmp_path, CALC_CASES)


@pytest.mark.parametrize('code,expected', [
    ('0.00[$₽-419]', '12.50₽'), ('[$руб.-419]0.0', 'руб.12.5'),
    ('[$EUR-0407]0.00', 'EUR12.50'), ('[$-419]0.00', '12.50'),
    ('[$-409]0.00', '12.50'), ('[$-40C]0.00', '12.50'),
])
def test_currency_tokens_preserve_literals_without_inferring_locale(code, expected):
    assert render_number(12.5, code) == expected
    locale = NumberLocale(',', '.')
    # Literal decimal punctuation in a currency name must not be translated.
    assert render_number(12.5, '[$руб.-419]0.0', display_locale=locale) == 'руб.12,5'


@pytest.mark.parametrize('code', ['[$-F800]0', '[$-F400]0', '[$-2000409]0',
    '[$-10409]0', '[$-777]0', '[$-0]0', '[$₽-GGG]0', '[$₽-41]0',
    '[$₽-123456789]0', '[$-]0', '[$₽-419][$USD-409]0'])
def test_unknown_calendar_and_malformed_currency_tags_keep_fallback(code):
    assert render_number(1, code) is None
