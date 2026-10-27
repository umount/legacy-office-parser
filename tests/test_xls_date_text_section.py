"""Date masks followed by a text section keep the normalized XLS date contract.

MS-XLS 2.4.126 permits NFAnyNoText ; NFAny, including a trailing NFText.
Expectations are literal; no source date display or locale names are synthesized.
"""
from dataclasses import replace

import pytest

from legacy_office_parser import parse, parse_xls
from legacy_office_parser._xls_dates import DateResult, interpret_date
from legacy_office_parser.errors import LimitExceededError
from legacy_office_parser.limits import Limits
from legacy_office_parser.xls import _parse_workbook
from test_xls import ole_workbook
from test_xls_formats import parse_number, workbook
from test_xls_hidden_sections import string_workbook


@pytest.mark.parametrize('code,value,mode,expected', [
    ('DD.MM.YYYY;@', 45366.0, 0, ('2024-03-15', 'date', '2024-03-15')),
    ('[$-419]d mmmm yyyy;@', 45366.0, 0, ('2024-03-15', 'date', '2024-03-15')),
    ('[$-0419]dd.mm.yy;@', 0.0, 1, ('1904-01-01', 'date', '1904-01-01')),
    ('dd/mm/yyyy;@', -0.0, 0, ('1899-12-31', 'date', '1899-12-31')),
    ('[$-419]dd.mm.yyyy h:mm;@', 45366.5, 0,
     ('2024-03-15T12:00:00', 'date', '2024-03-15T12:00:00')),
    ('hh:mm:ss.000;@', 60.5, 0, ('12:00:00', 'date', '12:00:00')),
    ('[h]:mm:ss;@', 1.5, 0, (1.5, 'number', '36:00:00')),
    ('yyyy-mm-dd";@";[Red]"label;"@', 61.0, 0,
     ('1900-03-01', 'date', '1900-03-01')),
    (r'yyyy-mm-dd\;;\@@";"', 61.0, 0, ('1900-03-01', 'date', '1900-03-01')),
])
def test_date_with_trailing_text_section(code, value, mode, expected):
    assert interpret_date(value, code, mode) == DateResult('ok', expected)


@pytest.mark.parametrize('code', [
    'dd.mm.yyyy;0', 'dd.mm.yyyy;hh:mm', 'dd.mm.yyyy;',
    'dd.mm.yyyy;"@"', r'dd.mm.yyyy;\@', 'dd.mm.yyyy;_@',
    'dd.mm.yyyy;@@', 'dd.mm.yyyy;@0', 'dd.mm.yyyy;@\\',
    'dd.mm.yyyy;"unfinished@', 'dd.mm.yyyy;[>0]@',
    'dd.mm.yyyy;@;@', 'dd.mm.yyyy;;;@',
    '[>=0]dd.mm.yyyy;@', '[$-F800]dd.mm.yyyy;@', '[$-FC19]dd.mm.yyyy;@',
    'yyyyyyyy;@', '"yyyy";@', ';@', '0;@',
])
def test_unsupported_sections_keep_raw_values_and_diagnostics(code):
    doc = parse_number(45366.0, 164, code)
    cell = doc.sheets[0].cells[0]
    assert (cell.value, cell.value_type, cell.text) == (45366.0, 'number', '45366.0')
    assert [d.code for d in doc.diagnostics] == [
        'xls_unsupported_or_ambiguous_date_number_format_raw_numeric_value']


@pytest.mark.parametrize('value,code,warning', [
    (60.5, 'dd.mm.yyyy;@', 'xls_unrepresentable_excel_date_including_serial_60_raw_numeric_value'),
    (-1.0, 'dd.mm.yyyy;@', 'xls_unrepresentable_excel_date_including_serial_60_raw_numeric_value'),
    (-1.0, '[h]:mm;@', 'xls_unrepresentable_excel_date_including_serial_60_raw_numeric_value'),
    (2958466.0, 'dd.mm.yyyy;@', 'xls_excel_date_outside_supported_range_raw_numeric_value_retained'),
])
def test_date_fallback_diagnostics_survive_text_section(value, code, warning):
    doc = parse_number(value, 164, code)
    cell = doc.sheets[0].cells[0]
    assert (cell.value, cell.value_type, cell.text) == (value, 'number', str(value))
    assert [d.code for d in doc.diagnostics] == [warning]


def test_format_limit_includes_the_text_section():
    code = 'yyyy-mm-dd;"' + 'x' * 50 + '"@'
    assert len(code) == 64
    assert interpret_date(45366.0, code, 0).result == ('2024-03-15', 'date', '2024-03-15')
    assert interpret_date(45366.0, code + ' ', 0).status == 'unsupported'


@pytest.mark.parametrize('kind,code', [
    ('number', 'DD.MM.YYYY;@'), ('formula', '[$-419]DD.MM.YYYY;@'),
    ('rk', 'DD.MM.YYYY;@'), ('mulrk', '[$-419]DD.MM.YYYY;@'),
])
def test_public_xls_date_with_text_section(tmp_path, kind, code):
    source = tmp_path / 'date.xls'
    source.write_bytes(ole_workbook(workbook(45366, 164, code, kind)))
    doc = parse_xls(source)
    assert doc.to_dict() == parse(source).to_dict()
    cell = doc.sheets[0].cells[0]
    assert (cell.value, cell.value_type, cell.text) == ('2024-03-15', 'date', '2024-03-15')
    assert cell.is_formula == (kind == 'formula') and cell.formula is None
    assert doc.text == 'S\nA1\t2024-03-15'
    assert doc.warnings == ([
        'Formula expressions are not decoded or executed; cached results may be stale.'
    ] if kind == 'formula' else [])
    serialized = doc.to_dict()['sheets'][0]['cells'][0]
    assert serialized['value'] == serialized['text'] == '2024-03-15'
    assert serialized['value_type'] == 'date'


def test_normalized_date_text_is_budgeted():
    code = 'dd.mm.yyyy;@'
    data = workbook(45366.0, 164, code)
    budget = len(code) + 1 + len('2024-03-15')
    doc = _parse_workbook(data, replace(Limits(), max_text_chars=budget))
    assert doc.sheets[0].cells[0].text == '2024-03-15'
    with pytest.raises(LimitExceededError):
        _parse_workbook(data, replace(Limits(), max_text_chars=budget - 1))


def test_text_in_date_formatted_cell_is_retained():
    doc = _parse_workbook(string_workbook('[$-419]dd.mm.yyyy;@'), Limits())
    cell = doc.sheets[0].cells[0]
    assert (cell.value, cell.value_type, cell.text) == ('retained', 'string', 'retained')
