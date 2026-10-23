"""General projection boundaries, not an oracle for Excel's width-dependent UI."""
import os
import struct

import pytest

from legacy_office_parser import Limits, parse_xls
from legacy_office_parser._xls_formats import render_number
from legacy_office_parser.errors import LimitExceededError
from test_xls import ole_workbook
from test_xls_formats import workbook


# Literal extraction expectations. Fractions and large numbers remain raw text.
CASES = [
    (99999999999.0, '99999999999'),
    (100000000000.0, '100000000000.0'),
    (-100000000000.0, '-100000000000.0'),
    (99999999999.99998, '99999999999.99998'),
    (100000000000.00002, '100000000000.00002'),
    (1.0000000000000002, '1.0000000000000002'),
    (0.9999999999999999, '0.9999999999999999'),
    (-1.0000000000000002, '-1.0000000000000002'),
    (0.0001, '0.0001'), (0.00001, '1e-05'),
    (0.000000001, '1e-09'), (1e16, '1e+16'),
    (5e-324, '5e-324'), (1.7976931348623157e308, '1.7976931348623157e+308'),
]


@pytest.mark.parametrize('value,expected', CASES)
@pytest.mark.parametrize('kind', ['number', 'formula'])
@pytest.mark.parametrize('fmt,code', [(0, None), (164, 'General')])
def test_general_projection_is_not_width_or_precision_inference(value, expected, kind, fmt, code):
    doc = parse_xls(ole_workbook(workbook(value, fmt, code, kind)))
    cell, = doc.sheets[0].cells
    assert cell.text == expected == render_number(value, 'General')
    assert struct.pack('<d', cell.value) == struct.pack('<d', value)
    assert cell.value_type == 'number' and cell.is_formula == (kind == 'formula')
    assert cell.formula is None
    assert doc.to_dict()['sheets'][0]['cells'][0]['text'] == expected
    # General raw projection currently succeeds without unsupported-format warning.
    assert len(doc.warnings) == (kind == 'formula')


SCIENTIFIC_CASES = [
    ('0.00E+00', 12345678901.0, '1.23E+10'),
    ('0.00E+00', 12200000.0, '1.22E+07'),
    ('0.00E+00', 100000000000.0, '1.00E+11'),
]


@pytest.mark.parametrize('code,value,expected', SCIENTIFIC_CASES)
def test_explicit_scientific_mask_uses_its_specified_decimal_places(code, value, expected):
    cell, = parse_xls(ole_workbook(workbook(value, 164, code))).sheets[0].cells
    assert cell.text == expected and cell.value == value
    assert render_number(value, 'General') != expected


def test_raw_projection_budget_is_charged_without_precision_shortening():
    data = ole_workbook(workbook(1.0000000000000002, 0))
    # One sheet-name character plus eighteen raw numeric characters.
    assert parse_xls(data, limits=Limits(max_text_chars=19)).sheets[0].cells[0].text == (
        '1.0000000000000002')
    with pytest.raises(LimitExceededError):
        parse_xls(data, limits=Limits(max_text_chars=18))


@pytest.mark.skipif(os.environ.get('XLS_GENERAL_BOUNDARIES_LO') != '1',
                    reason='opt-in preserved-source explicit scientific oracle')
def test_explicit_scientific_preserved_source_oracle(tmp_path):
    from _xls_format_oracle import generate_preserved
    generate_preserved(tmp_path, SCIENTIFIC_CASES)
