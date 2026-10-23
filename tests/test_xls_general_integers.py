"""General text display preserves typed values and never evaluates formula tokens."""
import math
import os

import pytest

from legacy_office_parser._xls_formats import render_number
from test_xls_formats import parse_number


@pytest.mark.parametrize('value,text', [(1.0, '1'), (0.0, '0'), (-0.0, '0'),
                                        (-1.0, '-1'), (99999999999.0, '99999999999'),
                                        (-99999999999.0, '-99999999999')])
@pytest.mark.parametrize('code', ['General', 'general', '[Red]General'])
def test_whole_numbers_without_fraction_or_width_inference(value, text, code):
    assert render_number(value, code) == text


@pytest.mark.parametrize('value', [1.25, 1.0000000000000002, -1.0000000000000002,
                                   1e-8, 5e-324, 1e11, -1e11, 1e100])
def test_other_general_values_keep_existing_projection(value):
    assert render_number(value, 'General') == str(value)


@pytest.mark.parametrize('kind', ['number', 'formula', 'rk', 'mulrk'])
@pytest.mark.parametrize('fmt,custom', [(0, None), (164, 'General')])
@pytest.mark.parametrize('value', [0, 1, -1, 123456])
def test_biff_numeric_paths_and_formula_cache_keep_value(kind, fmt, custom, value):
    doc = parse_number(value, fmt, custom, kind)
    cell = doc.sheets[0].cells[0]
    assert cell.text == str(value)
    assert cell.value == value and cell.value_type == 'number'
    if kind in ('number', 'formula'):
        assert type(cell.value) is float
    assert doc.text == 'S\nA1\t' + str(value)


def test_negative_zero_value_keeps_sign_while_display_is_zero():
    cell = parse_number(-0.0).sheets[0].cells[0]
    assert cell.text == '0'
    assert math.copysign(1, cell.value) == -1


def test_explicit_decimal_format_and_missing_format_are_not_general():
    assert parse_number(1.0, 164, '0.0').sheets[0].cells[0].text == '1.0'
    assert parse_number(1.0, missing_xf=True).sheets[0].cells[0].text == '1.0'
    assert parse_number(1.0, 164, 'unsupported').sheets[0].cells[0].text == '1.0'


def test_general_section_routing_includes_negative_conditions():
    assert render_number(1.0, '[>0]General;General') == '1'
    assert render_number(-1.0, '[>0]General;General') == '1'
    assert render_number(-1.0, 'General;General') == '1'
    assert render_number(0.0, 'General;General;General') == '0'


@pytest.mark.skipif(os.environ.get('XLS_GENERAL_LO') != '1', reason='opt-in Calc oracle')
def test_preserved_general_display_against_libreoffice(tmp_path):
    from _xls_format_oracle import generate_preserved
    generate_preserved(tmp_path, [
        ('General', 1.0, '1'), ('General', 0.0, '0'), ('General', -0.0, '0'),
        ('General', -1.0, '-1'), ('General', 123456.0, '123456'),
        ('General', 99999999999.0, '99999999999'),
        ('General', -99999999999.0, '-99999999999'),
        ('General', 1.25, '1.25'), ('0.0', 1.0, '1.0'),
    ])
