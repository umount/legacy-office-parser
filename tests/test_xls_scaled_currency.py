"""Independent BIFF display expectations for the deliberately bounded extension."""
import struct
import sys
from dataclasses import replace
from decimal import ROUND_DOWN, localcontext

import pytest

from legacy_office_parser._xls_formats import render_number
from legacy_office_parser.errors import LimitExceededError
from legacy_office_parser.limits import Limits
from legacy_office_parser.xls import _parse_workbook
from test_xls_formats import parse_number, workbook


CASES = [
    ('[$$-409]#,##0.00', -1234.5, '-$1,234.50'),
    ('[$€-407]#,##0.00', -1234.5, '-€1,234.50'),
    ('[$USD-409]0.00', 0, 'USD0.00'),
    ('0.00[$€-407]', -12.5, '-12.50€'),
    ('[$USD-409]0.00;([$USD-409]0.00)', -12.5, '(USD12.50)'),
    ('0.0,,"M"', 1234567, '1.2M'),
    ('0.0,,"M"', 9999999, '10.0M'),
    ('0.0,,"M";[Red](0.0,,"M")', -1234567, '(1.2M)'),
    ('#,##0,,', 1234567890, '1,235'),
    ('0,', 1500, '2'),
    ('0,,', -500000, '-1'),
    ('0.00,"k"', 1235, '1.24k'),
    ('0.0##', 1, '1.0'), ('0.0##', 1.2, '1.2'),
    ('0.0##', 1.2345, '1.235'), ('0.0##', 1.2005, '1.201'),
    ('0.00##', 1.2, '1.20'), ('0.0##', 9.9999, '10.0'),
    ('0.0##', -0.0001, '0.0'), ('0.0##', -0.0, '0.0'),
    ('[$USD-409]#,##0.0##,"k"', 1234567, 'USD1,234.567k'),
    ('0.0##[$$-409]', 1.2, '1.2$'),
    ('[>=1000][$$-409]0.0,"k";0.00', 1234, '$1.2k'),
    ('[>=1000]0.0,"k";0.00', 999, '999.00'),
    ('0.0,;[Red](0.0,);"zero"', 0, 'zero'),
    ('0.0,;[Red](0.0,);"zero"', -1, '(0.0)'),
    ('0.0##"00"', 1, '1.000'),
    ('0.0##","', 1, '1.0,'),
]


@pytest.mark.parametrize('kind', ['number', 'formula'])
@pytest.mark.parametrize('code,value,expected', CASES)
def test_exact_biff_formats_preserve_raw_values(code, value, expected, kind):
    data = workbook(value, 164, code, kind)
    # Actual FORMAT payload is the requested string; no Office export or
    # normalization can rewrite it before the parser sees these bytes.
    encoded = code.encode('utf-16le')
    payload = struct.pack('<HHB', 164, len(encoded) // 2, 1) + encoded
    assert struct.pack('<HH', 0x41e, len(payload)) + payload in data
    doc = _parse_workbook(data, Limits())
    cell, = doc.sheets[0].cells
    assert struct.pack('<d', cell.value) == struct.pack('<d', value)
    assert (cell.text, cell.value_type) == (expected, 'number')
    assert cell.is_formula == (kind == 'formula') and cell.formula is None
    assert len(doc.warnings) == int(kind == 'formula')


@pytest.mark.parametrize('kind', ['rk', 'mulrk'])
def test_scaled_integer_records(kind):
    cell = parse_number(-12345, 164, '[$$-409]0.0,', kind).sheets[0].cells[0]
    assert type(cell.value) is int and cell.value == -12345
    assert cell.text == '-$12.3'


@pytest.mark.parametrize('code', [
    '[$-777]0.00', '[$-F800]0.00', '[$-F400]0.00',
    '[$-2000409]0.00', '[$-10409]0.00', '[$-0]0.00', '[$]0.00',
    '[$USD]0.00', '[$€-GGG]0.00', '[$$-40]0.00', '[$USD-040Z]0',
    '[$USD-409]yyyy', '[$USD-409]General',
    '[$USD-409]0[$$-409]', '[$$-409][$€-407]0',
    '0;0;[$$-ZZZ]', '[$USD-409', '[DBNum1]0.0',
    '0,,.0', '0.0,"x",', '0%,', '0E+00,',
    '0.0#E+00', '0.0#"x"#',
    '0.' + '0' * 15 + '#', '0.0' + '#' * 15,
    '0.0,,"unfinished', '0.0,,\\', '0.0,,"x"0',
    '0;0;0;[$$-409]@', '0.0;[$-777]0',
])
def test_unsupported_or_malformed_retains_raw_and_warns(code):
    assert render_number(.125, code) is None
    doc = parse_number(.125, 164, code)
    cell, = doc.sheets[0].cells
    assert (cell.value, cell.text, cell.value_type) == (.125, '0.125', 'number')
    assert sum('Unsupported or ambiguous' in w for w in doc.warnings) == 1


@pytest.mark.parametrize('code,expected', [
    ('[>=0][$$-409]0.0;0.0', '1234.0'), ('[<0]0.0,;0.0', '1.2'),
    ('[<0]General;[$$-409]0.0', '1234'), ('[>0]0.0;[=0]0.0;"negative"', 'negative')])
def test_negative_conditionals_render_selected_section(code, expected):
    assert render_number(-1234, code) == expected


@pytest.mark.parametrize('code,value,expected', CASES)
def test_exact_text_budget(code, value, expected):
    budget = len(code) + 1 + len(expected)
    data = workbook(value, 164, code)
    assert _parse_workbook(data, replace(Limits(), max_text_chars=budget)).sheets[0].cells[0].text == expected
    with pytest.raises(LimitExceededError):
        _parse_workbook(data, replace(Limits(), max_text_chars=budget - 1))


def test_format_and_precision_bounds():
    assert render_number(1, '0' + ',' * 63) == '0'
    assert render_number(1, '0' + ',' * 64) is None
    assert render_number(1, '0.0' + '#' * 14) == '1.0'
    assert render_number(1, '0.0' + '#' * 15) is None


def test_hostile_decimal_context_is_unchanged():
    with localcontext() as ctx:
        ctx.prec, ctx.rounding, ctx.Emin, ctx.Emax = 2, ROUND_DOWN, -2, 2
        ctx.clamp = 1
        for signal in ctx.traps:
            ctx.traps[signal] = True
        ctx.clear_flags()
        for code, value, expected in CASES:
            assert render_number(value, code) == expected
        assert render_number(5e-324, '0.0##,,,') == '0.0'
        result = render_number(sys.float_info.max, '[$$-409]#,##0.0##############,')
        assert result.startswith('$179,769,313') and result.endswith('.0')
        assert len(result) < 450
        assert not any(ctx.flags.values())
