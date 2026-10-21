"""Independently authored OOXML examples; no XLS parser/fixture helpers reused."""
import importlib.util
import io
import json
from pathlib import Path
import sys
from zipfile import ZipFile

import pytest

from legacy_office_parser import CellRange, Document, Sheet, SpreadsheetCell

_spec = importlib.util.spec_from_file_location(
    '_spreadsheet_reference', Path(__file__).parents[1] / 'tools/_spreadsheet_reference.py')
_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _module
_spec.loader.exec_module(_module)
compare_spreadsheets = _module.compare_spreadsheets

N = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
P = 'http://schemas.openxmlformats.org/package/2006/relationships'


def reference(cells='', *, epoch='0', styles=None, strings=None, merges='', sheets=None):
    # Intentionally nonstandard filenames and reverse physical/relationship order.
    sheets = sheets or [('First', 'visible', cells, merges)]
    stream = io.BytesIO()
    with ZipFile(stream, 'w') as z:
        z.writestr('_rels/.rels', f'<Relationships xmlns="{P}"><Relationship Id="root" '
                   f'Type="{R}/officeDocument" Target="book/main.xml"/></Relationships>')
        entries, rels = [], []
        for i, (name, state, content, merged) in reversed(list(enumerate(sheets))):
            path = f'tab{20-i}.xml'
            z.writestr('grid/' + path, f'<worksheet xmlns="{N}"><sheetData><row r="1">'
                       f'{content}</row></sheetData><mergeCells>{merged}</mergeCells></worksheet>')
            entries.insert(0, f'<sheet name="{name}" sheetId="{i+9}" state="{state}" '
                           f'r:id="key{i}"/>')
            rels.append(f'<Relationship Id="key{i}" Type="{R}/worksheet" '
                        f'Target="../grid/{path}"/>')
        z.writestr('book/main.xml', f'<workbook xmlns="{N}" xmlns:r="{R}">'
                   f'<workbookPr date1904="{epoch}"/><sheets>{"".join(entries)}</sheets></workbook>')
        if styles is not None:
            z.writestr('assets/styles.xml', f'<styleSheet xmlns="{N}">{styles}</styleSheet>')
            rels.append(f'<Relationship Id="styles" Type="{R}/styles" Target="/assets/styles.xml"/>')
        if strings is not None:
            z.writestr('assets/strings.xml', f'<sst xmlns="{N}">{strings}</sst>')
            rels.append(f'<Relationship Id="strings" Type="{R}/sharedStrings" '
                        'Target="../assets/strings.xml"/>')
        z.writestr('book/_rels/main.xml.rels',
                   f'<Relationships xmlns="{P}">{"".join(rels)}</Relationships>')
    stream.seek(0)
    return ZipFile(stream)


def cell(row, col, value, kind='number', formula=False):
    return SpreadsheetCell(row, col, value, kind, text='irrelevant display',
                           formula='private formula' if formula else None, is_formula=formula)


def compare(cells, archive, **kwargs):
    with archive:
        return compare_spreadsheets(Document(format='xls', sheets=[Sheet('First', cells, **kwargs)]),
                                    archive)


def test_equal_counts_do_not_hide_wrong_value_or_coordinate():
    xml = '<c r="A1"><v>12</v></c><c r="C8"><v>3</v></c>'
    result = compare([cell(1, 1, 13), cell(8, 4, 3)], reference(xml))
    assert result['cells'] == result['reference_cells'] == 2
    assert result['equal'] is False
    assert result['counts'] == {'extra_cell': 1, 'missing_cell': 1, 'value': 1}
    assert result['issues'][0]['coordinate'] == [1, 1]


def test_workbook_order_names_relationships_and_hidden():
    refs = [('Private one', 'veryHidden', '<c r="A1"><v>1</v></c>', ''),
            ('Private two', 'visible', '<c r="A1"><v>2</v></c>', '')]
    doc = Document('xls', sheets=[Sheet('Private one', [cell(1, 1, 1)], hidden=True),
                                  Sheet('Private two', [cell(1, 1, 2)])])
    with reference(sheets=refs) as z:
        assert compare_spreadsheets(doc, z)['equal'] is True
        doc.sheets.reverse()
        report = compare_spreadsheets(doc, z)
        assert report['counts'] == {'hidden': 2, 'sheet_name_or_order': 2, 'value': 2}
        assert 'Private' not in json.dumps(report)


def test_strings_booleans_errors_and_numeric_types():
    xml = ('<c r="A1" t="s"><v>0</v></c>'
           '<c r="B1" t="inlineStr"><is><r><t>in</t></r><r><t>line</t></r></is></c>'
           '<c r="C1" t="b"><v>1</v></c><c r="D1" t="e"><v>#DIV/0!</v></c>'
           '<c r="E1"><v>1.25E+2</v></c><c r="F1" t="inlineStr"><is><t/></is></c>')
    strings = '<si><r><t>shared </t></r><rPh><t>ignore</t></rPh><r><t>text</t></r></si>'
    cells = [cell(1, 1, 'shared text', 'string'), cell(1, 2, 'inline', 'string'),
             cell(1, 3, True, 'boolean'), cell(1, 4, '#DIV/0!', 'error'),
             cell(1, 5, 125, 'currency'), cell(1, 6, '', 'string')]
    assert compare(cells, reference(xml, strings=strings))['equal'] is True
    cells[2] = cell(1, 3, 1)
    assert compare(cells, reference(xml, strings=strings))['counts'] == {'type': 1}


def test_formula_caches_only_and_empty_string_vs_missing_cache():
    xml = ('<c r="A1"><f>SECRET()</f><v>5</v></c>'
           '<c r="B1" t="str"><f t="shared" si="0"/><v/></c>'
           '<c r="C1" t="b"><f>SECRET()</f><v>0</v></c>'
           '<c r="D1" t="e"><f>SECRET()</f><v>#N/A</v></c>')
    cells = [cell(1, 1, 5, formula=True), cell(1, 2, '', 'string', True),
             cell(1, 3, False, 'boolean', True), cell(1, 4, '#N/A', 'error', True)]
    assert compare(cells, reference(xml))['equal'] is True
    cells[0].is_formula = False
    assert compare(cells, reference(xml))['counts'] == {'formula_flag': 1}
    report = compare([cell(1, 1, 0, formula=True)], reference('<c r="A1"><f>SECRET()</f></c>'))
    assert report['status'] == 'ambiguous' and report['equal'] is None
    assert report['counts'] == {'missing_formula_cache': 1}
    assert 'SECRET' not in json.dumps(report)


@pytest.mark.parametrize('epoch,serial,expected', [
    ('0', '1', '1900-01-01'), ('0', '59', '1900-02-28'),
    ('0', '61', '1900-03-01'), ('true', '0', '1904-01-01'),
    ('1', '1.5', '1904-01-02T12:00:00'),
])
def test_calendar_dates(epoch, serial, expected):
    styles = '<cellXfs><xf numFmtId="14"/></cellXfs>'
    report = compare([cell(1, 1, expected, 'date')],
                     reference(f'<c r="A1"><v>{serial}</v></c>', epoch=epoch, styles=styles))
    assert report['equal'] is True


def test_custom_date_clock_and_iso_date():
    styles = ('<numFmts><numFmt numFmtId="165" formatCode="yyyy-mm-dd"/></numFmts>'
              '<cellXfs><xf numFmtId="165"/><xf numFmtId="21"/></cellXfs>')
    xml = ('<c r="A1"><v>61</v></c><c r="B1" s="1"><v>0.5</v></c>'
           '<c r="C1" t="d"><v>2024-03-04T00:00:00</v></c>')
    report = compare([cell(1, 1, '1900-03-01', 'date'), cell(1, 2, '12:00:00', 'date'),
                      cell(1, 3, '2024-03-04', 'date')], reference(xml, styles=styles))
    assert report['equal'] is True


@pytest.mark.parametrize('fmt,serial,reason', [
    (14, '60', 'ambiguous_date'), (14, '-1', 'ambiguous_date'),
    (14, '999999999', 'ambiguous_date'), (46, '2', 'unsupported_number_format'),
    (27, '2', 'unsupported_number_format'), (164, '2', 'unsupported_number_format'),
])
def test_uncertain_formats_never_equal(fmt, serial, reason):
    report = compare([cell(1, 1, float(serial))], reference(
        f'<c r="A1"><v>{serial}</v></c>', styles=f'<cellXfs><xf numFmtId="{fmt}"/></cellXfs>'))
    assert report['equal'] is None
    assert report['counts'] == {reason: 1}


def test_unsupported_custom_format_and_duration():
    styles = ('<numFmts><numFmt numFmtId="170" formatCode="[Red][h]:mm;0"/></numFmts>'
              '<cellXfs><xf numFmtId="170"/></cellXfs>')
    assert compare([cell(1, 1, 1)], reference('<c r="A1"><v>1</v></c>', styles=styles))[
        'status'] == 'unsupported'
    assert compare([cell(1, 1, 'PT12H', 'time')], reference('<c r="A1"><v>0.5</v></c>'))[
        'counts'] == {'unsupported_duration': 1}


def test_merges_sparse_blanks_and_ignored_dimensions():
    xml = '<c r="A1"/><c r="XFD1048576"><v>7</v></c>'
    cells = [cell(1048576, 16384, 7), cell(2, 3, None, 'empty')]
    merge = '<mergeCell ref="B2:D3"/>'
    assert compare(cells, reference(xml, merges=merge),
                   merges=[CellRange(2, 2, 3, 4)])['equal'] is True
    report = compare(cells, reference(xml, merges=merge), merges=[CellRange(2, 2, 3, 5)])
    assert report['counts'] == {'extra_merge': 1, 'missing_merge': 1}
    assert report['issues'][0]['coordinate'] == [2, 2, 3, 4]


@pytest.mark.parametrize('xml', [
    '<c r="SECRET"><v>1</v></c>', '<c r="A1"><v>PRIVATE</v></c>',
    '<c r="A1" t="s"><v>-1</v></c>', '<c r="A1" t="s"><v>100</v></c>',
    '<c r="A1" t="b"><v>PRIVATE</v></c>', '<c r="A1"/><c r="A1"/>',
])
def test_invalid_reference_diagnostics_are_sanitized(xml):
    report = compare([], reference(xml))
    assert report['status'] == 'invalid_reference' and report['equal'] is None
    assert 'PRIVATE' not in json.dumps(report) and 'SECRET' not in json.dumps(report)


def test_private_content_never_leaks_on_differences():
    report = compare([cell(1, 1, 'PRIVATE actual', 'string', True)], reference(
        '<c r="A1" t="str"><f>PRIVATE formula</f><v>PRIVATE reference</v></c>'))
    assert report['counts'] == {'value': 1}
    assert 'PRIVATE' not in json.dumps(report)


def test_missing_extra_sheets_and_duplicate_model_coordinate():
    with reference() as z:
        assert compare_spreadsheets(Document('ods'), z)['counts'] == {'missing_sheet': 1}
        doc = Document('ods', sheets=[Sheet('First'), Sheet('Extra')])
        assert compare_spreadsheets(doc, z)['counts'] == {'extra_sheet': 1}
    report = compare([cell(1, 1, 1), cell(1, 1, 1)], reference('<c r="A1"><v>1</v></c>'))
    assert report['counts'] == {'duplicate_coordinate': 1}


def test_ooxml_escape_and_literal_escape():
    report = compare([cell(1, 1, 'A_x0041_😀', 'string')], reference(
        '<c r="A1" t="inlineStr"><is><t>_x0041__x005F_x0041__xD83D__xDE00_</t></is></c>'))
    assert report['equal'] is True


@pytest.mark.parametrize('styles', [
    '<cellXfs><xf numFmtId="14" applyNumberFormat="false"/></cellXfs>',
    '<cellXfs><xf numFmtId="0" xfId="1"/></cellXfs>',
])
def test_unresolved_style_inheritance_is_not_equal(styles):
    report = compare([cell(1, 1, 1)], reference('<c r="A1"><v>1</v></c>', styles=styles))
    assert report['equal'] is None
    assert report['counts'] == {'unsupported_number_format': 1}


def test_submicrosecond_date_does_not_round_to_equal():
    report = compare([cell(1, 1, '1900-01-01', 'date')], reference(
        '<c r="A1"><v>1.00000000000001</v></c>',
        styles='<cellXfs><xf numFmtId="14"/></cellXfs>'))
    assert report['counts'] == {'ambiguous_date': 1}


def test_unknown_type_with_no_value_is_not_a_blank():
    report = compare([cell(1, 1, 1)], reference('<c r="A1" t="future"/>'))
    assert report['counts'] == {'unsupported_cell_type': 1}


@pytest.mark.parametrize('apply', [' applyNumberFormat="0"', ' applyNumberFormat="false"', ''])
def test_same_parent_number_format_is_resolved_even_with_apply_false(apply):
    styles = ('<numFmts><numFmt numFmtId="164" formatCode="General"/></numFmts>'
              '<cellStyleXfs><xf numFmtId="164"/><xf numFmtId="14"/></cellStyleXfs>'
              f'<cellXfs><xf numFmtId="164" xfId="0"{apply}/>'
              f'<xf numFmtId="14" xfId="1"{apply}/></cellXfs>')
    report = compare([cell(1, 1, 3), cell(1, 2, '1900-03-01', 'date')], reference(
        '<c r="A1"><v>3</v></c><c r="B1" s="1"><v>61</v></c>', styles=styles))
    assert report['equal'] is True


def test_missing_local_format_inherits_parent():
    styles = ('<cellStyleXfs><xf numFmtId="0"/><xf numFmtId="14"/></cellStyleXfs>'
              '<cellXfs><xf xfId="1" applyNumberFormat="0"/></cellXfs>')
    assert compare([cell(1, 1, '1900-03-01', 'date')], reference(
        '<c r="A1"><v>61</v></c>', styles=styles))['equal'] is True


@pytest.mark.parametrize('apply', ['', ' applyNumberFormat="1"'])
def test_explicit_format_overrides_parent_in_lo_exports(apply):
    styles = ('<numFmts><numFmt numFmtId="164" formatCode="General"/>'
              '<numFmt numFmtId="165" formatCode="yyyy\\\\-mm\\\\-dd"/></numFmts>'
              '<cellStyleXfs><xf numFmtId="164"/></cellStyleXfs>'
              f'<cellXfs><xf xfId="0" numFmtId="165"{apply}/></cellXfs>')
    assert compare([cell(1, 1, '1900-03-01', 'date')], reference(
        '<c r="A1"><v>61</v></c>', styles=styles))['equal'] is True


def test_conflicting_explicit_false_format_stays_uncertain():
    styles = ('<cellStyleXfs><xf numFmtId="0"/></cellStyleXfs>'
              '<cellXfs><xf numFmtId="14" xfId="0" applyNumberFormat="0"/></cellXfs>')
    assert compare([cell(1, 1, 61)], reference(
        '<c r="A1"><v>61</v></c>', styles=styles))['equal'] is None


@pytest.mark.parametrize('value,raw,expected', [
    (0.1, '0.10000000000000001', 'equal'),
    (1.2345678901234567, '1.234567890123457', 'ambiguous'),
    (1.0000000000000002, '1', 'ambiguous'),
    (1.0000000000000002, '1.0000000000000002', 'equal'),
    (1.2345678901234567, '1.23456789012', 'different'),
    (9007199254740993, '9007199254740992', 'different'),
    (1, '1.00000000000000001', 'different'),
    (125.0, '1.25E2', 'equal'),
])
def test_numeric_domain_and_export_precision(value, raw, expected):
    result = compare([cell(1, 1, value)], reference(f'<c r="A1"><v>{raw}</v></c>'))
    assert result['status'] == expected
    if expected == 'ambiguous':
        assert result['equal'] is None
        assert result['counts'] == {'ambiguous_numeric_precision': 1}


@pytest.mark.parametrize('value,expression', [(True, 'TRUE()'), (False, 'FALSE()')])
def test_lo_boolean_formula_is_conversion_ambiguity(value, expression):
    result = compare([cell(1, 1, value, 'boolean')], reference(
        f'<c r="A1" t="b"><f>{expression}</f><v>{int(value)}</v></c>'))
    assert result['counts'] == {'conversion_boolean_formula': 1}
    assert result['compared_cells'] == 1
    assert result['status'] == 'ambiguous'
    assert result['equal'] is None


@pytest.mark.parametrize('expression,cache', [('TRUE()', '0'), ('NOT(FALSE())', '1')])
def test_boolean_formula_exception_does_not_hide_changed_cache_or_expression(expression, cache):
    result = compare([cell(1, 1, True, 'boolean')], reference(
        f'<c r="A1" t="b"><f>{expression}</f><v>{cache}</v></c>'))
    assert result['equal'] is False
    assert result['counts']['formula_flag'] == 1
    if cache == '0':
        assert result['counts']['value'] == 1


def test_exact_integer_rounded_by_lo_is_ambiguous_not_equal():
    result = compare([cell(1, 1, 9007199254740991)], reference(
        '<c r="A1"><v>9007199254740990</v></c>'))
    assert result['status'] == 'ambiguous'
    assert result['equal'] is None
    assert result['counts'] == {'ambiguous_numeric_precision': 1}
