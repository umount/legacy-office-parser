"""Independent synthetic BIFF streams for the bounded numeric rendering contract."""
import math
import struct
import sys
from dataclasses import replace
from decimal import Inexact, localcontext

import pytest

from legacy_office_parser._xls_formats import render_number
from legacy_office_parser.errors import InvalidDocumentError, LimitExceededError
from legacy_office_parser.limits import Limits
from legacy_office_parser.xls import _parse_workbook


def record(code, data=b''):
    return struct.pack('<HH', code, len(data)) + data


def workbook(value, fmt=0, custom=None, kind='number', missing_xf=False):
    def bof(kind):
        return record(0x809, struct.pack('<HHHHII', 0x600, kind, 0, 0, 0, 0))
    head = bof(5)
    if not missing_xf:
        head += record(0xe0, struct.pack('<HH', 0, fmt) + bytes(16))
    if custom is not None:
        encoded = custom.encode('utf-16le')
        head += record(0x41e, struct.pack('<HHB', fmt, len(encoded) // 2, 1) + encoded)
    coords = struct.pack('<HHH', 0, 0, 0)
    if kind == 'formula':
        # Opaque token bytes are intentionally not an executable expression.
        body = record(6, coords + struct.pack('<d', value) + bytes(6) + b'\x01\x00\xff')
    elif kind in ('rk', 'mulrk'):
        rk = struct.pack('<I', ((int(value) << 2) | 2) & 0xffffffff)
        body = record(0x27e, coords + rk) if kind == 'rk' else record(0xbd, coords + rk + bytes(2))
    else:
        body = record(0x203, coords + struct.pack('<d', value))
    # BOUNDSHEET = four-byte header, eight-byte metadata, one-byte name.
    bound = record(0x85, struct.pack('<IBBBB', len(head) + 13 + 4, 0, 0, 1, 0) + b'S')
    return head + bound + record(10) + bof(0x10) + body + record(10)


def parse_number(value, fmt=0, custom=None, kind='number', **kwargs):
    return _parse_workbook(workbook(value, fmt, custom, kind, **kwargs), Limits())


@pytest.mark.parametrize('kind', ['number', 'formula'])
@pytest.mark.parametrize('fmt,custom,value,expected', [
    (0, None, 12.5, '12.5'), (164, 'General', 12.5, '12.5'),
    (164, 'general', 12.5, '12.5'),
    (164, '0,,', .125, '0'), (164, '#,##0,', .125, '0'),
    (164, '0.0,,"M"', .125, '0.0M'),
    (1, None, 12.5, '13'), (2, None, -12.345, '-12.35'),
    (3, None, 12345.5, '12,346'), (4, None, 12345.5, '12,345.50'),
    (9, None, .125, '13%'), (10, None, -.25, '-25.00%'),
    (11, None, 12345, '1.23E+04'),
    (165, '0.00%', .125, '12.50%'), (165, '0.00%', .25, '25.00%'),
    (165, '0.00%', 0, '0.00%'), (166, '0.00', 12.5, '12.50'),
    (167, '#,##0.00', 12345.5, '12,345.50'),
    (168, '0.00E+00', 12345, '1.23E+04'),
    (164, '0.000', 1.2345, '1.235'), (164, '#,##0.0%', 12.345, '1,234.5%'),
    (164, '0.00E+00', .0012345, '1.23E-03'),
    (164, '0.00E+00', 9999, '1.00E+04'),
    (164, '0.0e-000', 1200, '1.2e003'),
    (164, '0E-0', .01, '1E-2'),
    (164, '0.00E+00', 0, '0.00E+00'),
    (164, '0.00E+00', -0.0, '0.00E+00'),
    (164, '0.00%', -0.000001, '0.00%'),
    (164, '0.00E+00', -1200, '-1.20E+03'),
])
def test_numeric_and_cached_formula_rendering(fmt, custom, value, expected, kind):
    doc = parse_number(value, fmt, custom, kind)
    cell = doc.sheets[0].cells[0]
    assert struct.pack('<d', cell.value) == struct.pack('<d', value)
    assert cell.value_type == 'number' and cell.text == expected
    assert expected in doc.text
    assert cell.is_formula == (kind == 'formula') and cell.formula is None
    assert not any('format' in warning.lower() for warning in doc.warnings)
    assert len(doc.warnings) == (1 if kind == 'formula' else 0)


@pytest.mark.parametrize('kind', ['number', 'formula'])
@pytest.mark.parametrize('custom', [
    '"0.00%"',
    '[$-409]0.00%', '[$-409]yyyy-mm-dd', '[>0]0%',
    '0_%,', '0*%', '0.00yyyy', '0%yyyy',
    '0.00"unfinished', '0.00\\', '[h]:mm', 'yyyy-mm-dd;0%',
    '0,00', '#.##0,00', '0.##', '# ???/???', '##0.0E+0', '0%%', '%0', '@',
    '0.0000000000000000', '0E+0000', '', '0.' + '0' * 1000,
    'm' * 63 + 'x', 'yyyyyyyy-mm-dd', '0\n', '0.00E+00%',
    r'yyyy\%mm', 'yyyy"%"mm', 'yyyy"days"mm', r'yyyy\dmm',
    'yyyy"0"mm', r'yyyy\0mm', 'yyyy"-mm', 'yyyy' + chr(92),
])
def test_unsupported_is_raw_with_explicit_warning(custom, kind):
    doc = parse_number(.125, 164, custom, kind)
    cell = doc.sheets[0].cells[0]
    assert (cell.value, cell.value_type, cell.text) == (.125, 'number', '0.125')
    assert sum('Unsupported or ambiguous' in w for w in doc.warnings) == 1


@pytest.mark.parametrize('fmt', [5, 23, 27, 37, 46, 48, 49, 50, 163, 164, 999])
def test_unhandled_or_missing_format(fmt):
    doc = parse_number(.125, fmt)
    assert doc.sheets[0].cells[0].text == '0.125'
    assert any('Unsupported or ambiguous' in w for w in doc.warnings)


def test_missing_xf_is_raw():
    doc = parse_number(.125, missing_xf=True)
    assert doc.sheets[0].cells[0].text == '0.125'
    assert any('Missing XF' in w for w in doc.warnings)


@pytest.mark.parametrize('kind', ['rk', 'mulrk'])
def test_integer_records_keep_integer_raw_type(kind):
    cell = parse_number(-12345, 4, kind=kind).sheets[0].cells[0]
    assert type(cell.value) is int and cell.value == -12345
    assert cell.value_type == 'number' and cell.text == '-12,345.00'


@pytest.mark.parametrize('kind', ['number', 'formula'])
@pytest.mark.parametrize('fmt,custom,value,expected', [
    (14, None, 61, '1900-03-01'), (164, 'yyyy-mm-dd', 61, '1900-03-01'),
    (164, 'hh:mm AM/PM', .5, '12:00:00'),
    (164, r'yyyy\-mm\-dd', 45351, '2024-02-29'),
    (164, 'yyyy"-"mm"-"dd', 45351, '2024-02-29'),
    (164, r'hh\:mm', .5, '12:00:00'),
])
def test_dates_remain_in_existing_date_path(fmt, custom, value, expected, kind):
    cell = parse_number(value, fmt, custom, kind).sheets[0].cells[0]
    assert (cell.value, cell.value_type, cell.text) == (expected, 'date', expected)


@pytest.mark.parametrize('kind', ['number', 'formula'])
@pytest.mark.parametrize('value', [math.nan, math.inf, -math.inf])
def test_nonfinite_rejected(value, kind):
    with pytest.raises(InvalidDocumentError):
        parse_number(value, 10, kind=kind)


def test_binary64_extremes_and_decimal_context():
    assert render_number(5e-324, '0.00E+00') == '5.00E-324'
    assert render_number(sys.float_info.max, '0.00E+00') == '1.80E+308'
    text = render_number(sys.float_info.max, '#,##0.000000000000000%')
    assert text.endswith('.000000000000000%') and len(text) < 450
    with localcontext() as ctx:
        ctx.prec = 2
        ctx.traps[Inexact] = True
        assert render_number(1.235, '0.00') == '1.24'
        assert render_number(.125, '0.00%') == '12.50%'
    assert render_number(1, '0.' + '0' * 15) == '1.000000000000000'


@pytest.mark.parametrize('kind', ['number', 'formula'])
def test_rendered_text_is_budgeted(kind):
    data = workbook(.125, 10, kind=kind)
    # One character sheet name plus six characters of rendered text.
    assert _parse_workbook(data, replace(Limits(), max_text_chars=7)).sheets[0].cells[0].text == '12.50%'
    with pytest.raises(LimitExceededError):
        _parse_workbook(data, replace(Limits(), max_text_chars=6))
