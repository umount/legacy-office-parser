"""Conditional formats: synthetic BIFF plus independent, opt-in Calc oracle.

Primary grammar: MS-XLS 2.4.126 Format (NFPartCond / NFPartCondNum).
https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-xls/300280fd-e4fe-4675-a924-4d383af48d3b
https://help.libreoffice.org/latest/en-US/text/shared/01/05020301.html
"""
from pathlib import Path
from xml.sax.saxutils import quoteattr
from zipfile import ZipFile

import csv
from dataclasses import replace
from decimal import ROUND_DOWN, localcontext
import os
import struct
import sys

import pytest

from legacy_office_parser import parse_xls
from legacy_office_parser._xls_formats import render_number
from legacy_office_parser.errors import LimitExceededError
from legacy_office_parser.limits import Limits
from legacy_office_parser.xls import _parse_workbook
from test_xls_formats import parse_number, workbook


def generate_probe(destination, cases):
    """Use only the original fixture's package skeleton; author masks and values."""
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    source = Path(__file__).parent / 'fixtures/xls_sections/sign_sections.xlsx'
    with ZipFile(source) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    import xml.etree.ElementTree as ET
    styles = ET.fromstring(files['xl/styles.xml'])
    formats = styles.find(f'{{{ns}}}numFmts')
    formats.clear()
    formats.set('count', str(len(cases)))
    xfs = styles.find(f'{{{ns}}}cellXfs')
    xfs.clear()
    xfs.set('count', str(len(cases)))
    rows = []
    for i, (code, value) in enumerate(cases):
        ET.SubElement(formats, f'{{{ns}}}numFmt', numFmtId=str(164+i), formatCode=code)
        ET.SubElement(xfs, f'{{{ns}}}xf', numFmtId=str(164+i), fontId='0', fillId='0',
                      borderId='0', xfId='0', applyNumberFormat='1')
        rows.append(f'<row r="{i+1}"><c r="A{i+1}" s="{i}"><v>{value}</v></c></row>')
    files['xl/styles.xml'] = ET.tostring(styles)
    files['xl/worksheets/sheet1.xml'] = (
        f'<worksheet xmlns={quoteattr(ns)}><sheetData>{"".join(rows)}</sheetData></worksheet>'
    ).encode()
    with ZipFile(destination, 'w') as archive:
        for name, data in files.items():
            archive.writestr(name, data)



# Observed Calc output, NOT a normative Excel sign oracle. Negative conditional
# values intentionally fall back even when this finite probe has a display. Avoid rounding ties: the parser's documented decimal policy is tested
# separately, not inferred from a spreadsheet engine's binary rounding.
CALC_OBSERVATIONS = [
    ('[<10]0.0;0.00', -2, '-2.0'),
    ('[<=10]0.0;0.00', 10, '10.0'),
    ('[>10]0.0;0.00', 10, '10.00'),
    ('[>=10]0.0;0.00', 10, '10.0'),
    ('[=10]0.0;0.00', 10, '10.0'),
    ('[<>10]0.0;0.00', 10, '10.00'),
    ('[<>0]0.0;0.00', -2, '-2.0'),
    ('[=-2]0.0;0.00', -2, '-2.0'),
    ('[<-10]0.0;0.00', -20, '-20.0'),
    ('[<0]0.0;0.00', -2, '2.0'),
    ('[<=0]0.0;0.00', -2, '2.0'),
    ('[<0](0.0);0.00', -2, '(2.0)'),
    ('[<0]"N"0.0;0.00', -2, 'N2.0'),
    ('[>10]0.0;0.00', -2, '2.00'),
    ('[>10]0.0;[<-10]0.00;0.000', -20, '20.00'),
    ('[>10]0.0;[<-10]0.00;0.000', -2, '2.000'),
    ('[>10]0.0;[<-10]0.00;0.000', 2, '2.000'),
    ('[>10]0.0;[<-10]0.00;0.000', 20, '20.0'),
    ('[>10]0.0;[<-10]0.00;"other"', -2, 'other'),
    ('[>=-10]0.0;[<10]0.00;0.000', -2, '-2.0'),
    ('[>=-10]0.0;[<10]0.00;0.000', -20, '20.00'),
    ('[<10]0.0;[>0]0.00;0.000', 2, '2.0'),  # First match wins.
    ('[<10]0.0;[>0]0.00;0.000', 20, '20.00'),
    ('[>0]0.0;[<0]0.00;0.000', 0, '0.000'),
    ('[<0]0.0;[>0]0.00;0.000;@', 0, '0.000'),
    ('[Red][<0]0.0;0.00', -2, '2.0'),
    ('[<0][Red]0.0;0.00', -2, '2.0'),
    ('[<0]0.0E+00;0.00E+00', -2, '2.0E+00'),
    ('[<0]0.0%;0.00%', -.25, '25.0%'),
    ('[<1.25]0.0;0.00', 1.25, '1.25'),
    ('[<1E+2]0.0;0.00', 100, '100.00'),
    ('[<1E-2]0.000;0.00', .005, '0.005'),
    ('[<0]General;General', -2, '2'),
    ('[>10]0;General', -2, '2'),
]


# Independent 24-cell sign probe: the second predicate changes whether the
# first zero-threshold section consumes magnitude. Include the matrix in both
# synthetic BIFF checks and the external CSV round-trip oracle.
for first in ('<', '<='):
    for second in ('<', '<=', '>', '>=', '=', '<>'):
        for limit in (0, 1):
            unsigned = (first, second, limit) in {
                ('<', '>', 0), ('<', '>=', 0), ('<', '=', 0), ('<=', '>', 0),
            }
            CALC_OBSERVATIONS.append((f'[{first}0]0.0;[{second}{limit}]0.00;0.000',
                           -2, '2.0' if unsigned else '-2.0'))


@pytest.mark.parametrize('code,value,expected', CALC_OBSERVATIONS)
@pytest.mark.parametrize('kind', ['number', 'formula'])
def test_proven_conditions_biff(code, value, expected, kind):
    doc = parse_number(value, 164, code, kind)
    cell = doc.sheets[0].cells[0]
    if value < 0:
        expected = str(float(value))
    elif 'General' in code:
        expected = str(float(value))
    assert cell.text == expected and cell.value_type == 'number'
    assert struct.pack('<d', cell.value) == struct.pack('<d', value)
    assert cell.is_formula == (kind == 'formula') and cell.formula is None
    assert len(doc.warnings) == (kind == 'formula') + (value < 0)


@pytest.mark.parametrize('op,expected', [
    ('<', ['A1', 'B2', 'B3']), ('<=', ['A1', 'A2', 'B3']),
    ('>', ['B1', 'B2', 'A3']), ('>=', ['B1', 'A2', 'A3']),
    ('=', ['B1', 'A2', 'B3']), ('<>', ['A1', 'B2', 'A3']),
])
def test_comparison_boundaries(op, expected):
    code = f'[{op}2]"A"0;"B"0'
    assert [render_number(v, code) for v in (1, 2, 3)] == expected


@pytest.mark.parametrize('code', [
    '0;[>0]0', '[>0]0;0;0', '[<0]0;0;"zero"', '[>0]0',
    '[>0]0;[<0]0;[=0]0', '[>0]0;[<0]0;0;[Red]@',
    '[>0][<10]0;0', '[Red][<0][Blue]0;0', '[Red][Blue][<0]0;0',
    '[<0]0;[Orange]0', '[<0]0;[<1]0;yyyy',
    '[<0]0;[<1]0;0.#0', '[<0]0;[<1]0;0;"text"@',
    '[<0]0;', '[<0]0;;0', '[<0]0;"hidden"',
    '[<0]0;[<1]0;""', '[<0]0;[<1]0;0;@;0',
    '[<+1]0;0', '[<.1]0;0', '[<1.]0;0', '[<1e+2]0;0', '[<1E2]0;0',
    '[<1E+0000]0;0', '[<1E+309]0;0', '[<1E-325]0;0', '[<1E-324]0;0',
    '[<1E+999]0;0', '[<NaN]0;0', '[<Infinity]0;0', '[<1,2]0;0',
    '[< 1]0;0', '[ <1]0;0', '[==1]0;0', '[!=1]0;0', '[<١]0;0',
    '[<0]0;[<bad]0', '[<0]0;0[>1]', '[<0]0;[>1]0;"unterminated',
])
@pytest.mark.parametrize('value', [-2, 0, 2])
def test_all_sections_and_condition_grammar_validated(code, value):
    assert render_number(value, code) is None
    doc = parse_number(value, 164, code)
    cell = doc.sheets[0].cells[0]
    assert cell.value == value and cell.text == str(float(value))
    assert sum('Unsupported or ambiguous' in w for w in doc.warnings) == 1


@pytest.mark.parametrize('code,value', [
    ('[>10]0;[<-10]0', 0), ('[>10]0;[<-10]0', 2),
    ('[>10]General', -2), ('[>0]0.0;0.00', 0),
])
def test_unmatched_or_ambiguous_uses_warning_fallback(code, value):
    assert render_number(value, code) is None
    doc = parse_number(value, 164, code, 'formula')
    assert doc.sheets[0].cells[0].text == str(float(value))
    assert len(doc.warnings) == 2


@pytest.mark.parametrize('kind', ['rk', 'mulrk'])
def test_raw_integer_records(kind):
    cell = parse_number(-20, 164, '[<-10]0.00;0', kind).sheets[0].cells[0]
    assert type(cell.value) is int and cell.value == -20
    assert cell.text == '-20'


def test_routing_precedes_rounding_and_percent_scaling():
    assert render_number(-.001, '[<0]0.00;0.0') is None
    assert render_number(.001, '[=0]0.0;0.00') == '0.00'
    assert render_number(.25, '[<1]0%;0.00') == '25%'
    assert render_number(-2, '0;0') == '2'
    assert render_number(-2, '[<10]0;0') is None
    for value in (0.0, -0.0):
        assert render_number(value, '[<0]0.0;[>0]0.00;"zero"') == 'zero'
        cell = parse_number(value, 164, '[<0]0.0;0.00').sheets[0].cells[0]
        assert struct.pack('<d', cell.value) == struct.pack('<d', value)


def test_literals_are_not_conditions():
    assert render_number(-2, '"[<0]"0;0') == '2'
    assert render_number(2, '[<10]"[>0];"0;0') == '[>0];2'
    assert render_number(2, r'[<10]\[0\];0') == '[2]'


def test_private_decimal_context_extremes_and_exact_thresholds():
    with localcontext() as ctx:
        ctx.prec, ctx.rounding, ctx.Emin, ctx.Emax = 2, ROUND_DOWN, -2, 2
        for signal in ctx.traps:
            ctx.traps[signal] = True
        ctx.clear_flags()
        assert render_number(1.235, '[<2]0.00;0') == '1.24'
        assert render_number(.1, '[=0.1]0.00;0') == '0.10'
        assert render_number(5e-324, '[=5E-324]0.00E+00;0') == '5.00E-324'
        assert render_number(-5e-324, '[<-1E-323]0;0.00E+00') is None
        text = render_number(sys.float_info.max, '[<=1.7976931348623157E+308]0.000000000000000%;0')
        assert text.endswith('.000000000000000%') and len(text) < 450
        assert render_number(-sys.float_info.max, '[<0]0.0E+00;0') is None
        assert not any(ctx.flags.values())


@pytest.mark.parametrize('value', [float('inf'), -float('inf'), float('nan')])
def test_nonfinite_conditional_input(value):
    assert render_number(value, '[<0]0;0') is None


def test_length_and_text_budget():
    code = '[<2]"' + 'x' * 55 + '"0;0'
    assert len(code) == 64
    expected = 'x' * 55 + '1'
    assert render_number(1, code) == expected
    assert render_number(1, code.replace('x', 'xx', 1)) is None
    data = workbook(1, 164, code)
    budget = len(code) + 1 + len(expected)
    assert _parse_workbook(data, replace(Limits(), max_text_chars=budget)).sheets[0].cells[0].text == expected
    with pytest.raises(LimitExceededError):
        _parse_workbook(data, replace(Limits(), max_text_chars=budget-1))


@pytest.mark.skipif(os.environ.get('OFFICE_CORPUS_LIBREOFFICE') != '1',
                    reason='opt-in independent LibreOffice XLS/CSV oracle')
def test_independent_libreoffice_probe(tmp_path):
    # No main fixture edits, macros, external links, or formula execution. These
    # generated workbooks contain numeric literals only. Use existing bounded
    # process-group conversion with a fresh private LibreOffice profile.
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / 'tools'))
    try:
        from check_performance import bounded
        source = tmp_path / 'conditions.xlsx'
        generate_probe(source, [(code, value) for code, value, _ in CALC_OBSERVATIONS])

        def convert(path, fmt):
            result = bounded([sys.executable, str(root / 'tools/check_performance.py'),
                              '--convert-child', '/usr/bin/libreoffice', str(path),
                              str(tmp_path), fmt], 45)
            assert result['status'] == 'ok', result

        csv_format = 'csv:Text - txt - csv (StarCalc):44,34,76,1,,0,false,true,true,false,false'
        convert(source, csv_format)
        expected = [[text] for _, _, text in CALC_OBSERVATIONS]
        with (tmp_path / 'conditions.csv').open() as stream:
            assert list(csv.reader(stream)) == expected
        convert(source, 'xls:MS Excel 97')
        xls = tmp_path / 'conditions.xls'
        (tmp_path / 'conditions.csv').unlink()
        convert(xls, csv_format)
        with (tmp_path / 'conditions.csv').open() as stream:
            assert list(csv.reader(stream)) == expected
        parsed = parse_xls(xls)
        assert len(parsed.warnings) == 1
        assert 'Unsupported or ambiguous' in parsed.warnings[0]
        for cell, (code, value, display) in zip(parsed.sheets[0].cells, CALC_OBSERVATIONS, strict=True):
            assert cell.value == value and cell.value_type == 'number'
            assert cell.text == (str(cell.value) if value < 0 or 'General' in code else display)
    finally:
        sys.path.pop(0)


@pytest.mark.parametrize('kind', ['number', 'formula'])
@pytest.mark.parametrize('value,expected', [(12.5, '13'), (-12.5, '-12.5'), (0.0, '0')])
def test_previously_rejected_mask_now_supported(value, expected, kind):
    # Only nonnegative cases replace historical rejections now; negative
    # conditional display is explicitly incomplete and must continue to warn.
    doc = parse_number(value, 164, '[<=0]0;0', kind)
    assert doc.sheets[0].cells[0].text == expected
    assert doc.sheets[0].cells[0].value == value
    assert len(doc.warnings) == (kind == 'formula') + (value < 0)


def test_single_general_condition_and_matching_two_condition_format():
    assert render_number(2, '[>1]General') == '2'
    assert render_number(-2, '[<-1]General') is None
    assert render_number(-2, '[<0]General') is None
    assert render_number(-20, '[>10]0.0;[<-10]0.00') is None
    assert render_number(20, '[>10]0.0;[<-10]0.00') == '20.0'


@pytest.mark.parametrize('value', [-sys.float_info.max, -1.0, -5e-324])
def test_negative_conditional_guard_has_no_sign_whitelist(value):
    # Exercise the rejected class beyond the finite Calc observation matrix.
    # Every choice of first/second operator and threshold must take raw fallback.
    for first in ('<', '<=', '>', '>=', '=', '<>'):
        for second in ('<', '<=', '>', '>=', '=', '<>'):
            for limit in (-1, 0, 1):
                for fallback in ('0.00', 'General', '"other"'):
                    code = f'[{first}{limit}]0;[{second}{limit}]0;{fallback}'
                    assert render_number(value, code) is None


@pytest.mark.parametrize('kind', ['number', 'formula', 'rk', 'mulrk'])
def test_overprecise_threshold_preserved_in_biff(kind):
    code = '[=1.00000000000000001]0;0.00""'
    data = workbook(1, 164, code, kind)
    # This is the exact authored FORMAT, not a normalized XLSX/Calc export.
    assert code.encode('utf-16le') in data
    doc = _parse_workbook(data, Limits())
    cell = doc.sheets[0].cells[0]
    assert cell.value == 1 and cell.value_type == 'number'
    assert cell.text == str(cell.value)
    assert sum('Unsupported or ambiguous' in w for w in doc.warnings) == 1
    assert len(doc.warnings) == 1 + (kind == 'formula')


@pytest.mark.parametrize('threshold', [
    '1.00000000000000001', '0.10000000000000001', '9007199254740993',
    '-1.00000000000000001', '6E-324', '1.0000000000000001E-323',
    '4.9E-324', '1E-325', '1.7976931348623158E+308', '1E+309',
])
def test_ambiguous_thresholds_rejected_even_in_unused_sections(threshold):
    with localcontext() as ctx:
        ctx.prec, ctx.Emin, ctx.Emax = 2, -2, 2
        for signal in ctx.traps:
            ctx.traps[signal] = True
        ctx.clear_flags()
        assert render_number(1, f'[={threshold}]0;0.00') is None
        assert render_number(1, f'[>0]0;[={threshold}]0;0.00') is None
        assert not any(ctx.flags.values())


@pytest.mark.parametrize('threshold,value', [
    ('0.1', .1), ('0.1000', .1), ('1.00000000000000000', 1),
    ('5E-324', 5e-324), ('1E-323', 1e-323),
    ('2.2250738585072014E-308', sys.float_info.min),
    ('1.7976931348623157E+308', sys.float_info.max), ('-0.0', 0),
])
def test_canonical_binary64_thresholds_ignore_ambient_context(threshold, value):
    with localcontext() as ctx:
        ctx.prec, ctx.Emin, ctx.Emax = 2, -2, 2
        for signal in ctx.traps:
            ctx.traps[signal] = True
        ctx.clear_flags()
        assert render_number(value, f'[={threshold}]0.0E+00;0') == render_number(value, '0.0E+00')
        assert not any(ctx.flags.values())


@pytest.mark.skipif(os.environ.get('OFFICE_CORPUS_LIBREOFFICE') != '1',
                    reason='opt-in preserved-BIFF threshold oracle')
def test_libreoffice_overprecise_format_patched_after_export(tmp_path):
    import olefile
    target = '[=1.00000000000000001]0;0.00""'
    # Equal character count permits patching only the FORMAT string in place,
    # without changing BIFF record offsets, BOUNDSHEET, or the OLE allocation.
    seed = '0.00"' + 'x' * (len(target) - 6) + '"'
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / 'tools'))
    try:
        from check_performance import bounded
        source = tmp_path / 'precise.xlsx'
        generate_probe(source, [(seed, 1)])

        def convert(path, fmt):
            result = bounded([sys.executable, str(root / 'tools/check_performance.py'),
                              '--convert-child', '/usr/bin/libreoffice', str(path),
                              str(tmp_path), fmt], 45)
            assert result['status'] == 'ok', result

        convert(source, 'xls:MS Excel 97')
        xls = tmp_path / 'precise.xls'
        with olefile.OleFileIO(xls, write_mode=True) as compound:
            data = bytearray(compound.openstream('Workbook').read())
            pos, patched = 0, 0
            while pos + 4 <= len(data):
                tag, size = struct.unpack_from('<HH', data, pos)
                if tag == 0x41e:
                    _, count, flags = struct.unpack_from('<HHB', data, pos + 4)
                    assert flags in (0, 1)
                    width, encoding = (2, 'utf-16le') if flags else (1, 'latin1')
                    start = pos + 9
                    end = start + count * width
                    if data[start:end].decode(encoding) == seed:
                        assert len(target) == count
                        data[start:end] = target.encode(encoding)
                        patched += 1
                pos += 4 + size
            assert patched == 1
            compound.write_stream('Workbook', bytes(data))
        with olefile.OleFileIO(xls) as compound:
            assert compound.openstream('Workbook').read() == bytes(data)
        doc = parse_xls(xls)
        cell, = doc.sheets[0].cells
        assert cell.value == 1 and cell.text == str(cell.value)
        assert len(doc.warnings) == 1 and 'Unsupported or ambiguous' in doc.warnings[0]
        convert(xls, 'csv:Text - txt - csv (StarCalc):44,34,76,1,,0,false,true,true,false,false')
        with (tmp_path / 'precise.csv').open() as stream:
            assert list(csv.reader(stream)) == [['1']]
    finally:
        sys.path.pop(0)
