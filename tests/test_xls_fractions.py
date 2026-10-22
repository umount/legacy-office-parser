"""Original synthetic BIFF fraction masks, literal expectations, optional Calc oracle."""
import json
import math
import os
import struct
from decimal import Inexact, localcontext

import pytest

from legacy_office_parser import Limits, parse, parse_xls
from legacy_office_parser._xls_formats import render_number, text_affixes, text_literal
from legacy_office_parser.errors import InvalidDocumentError, LimitExceededError
from legacy_office_parser.xls import _parse_workbook
from test_xls import ole_workbook
from test_xls_formats import workbook


# Authored independently of the renderer; fixed FORMAT bytes are checked again
# after XLS export in the opt-in oracle. No expected values are parser-generated.
CASES = [
    ('0/8', 0, '0/8'),
    ('0/8', -0.0, '0/8'),
    ('0/8', .01, '0/8'),
    ('0/8', -.01, '0/8'),
    ('0/8', .125, '1/8'),
    ('0/8', .5, '4/8'),
    ('0/8', 1, '8/8'),
    ('0/8', 1.5, '12/8'),
    ('0/8', -1.5, '-12/8'),
    ('0/8', .999, '8/8'),
    ('0/8', 2.999, '24/8'),
    ('00/16', 0, '00/16'),
    ('00/16', .0625, '01/16'),
    ('00/16', .5, '08/16'),
    ('00/16', -.5, '-08/16'),
    ('00/16', 1.5, '24/16'),
    ('000/100', .01, '001/100'),
    ('000/100', .1875, '019/100'),
    ('000/100', .6875, '069/100'),
    ('000/100', -.9375, '-094/100'),
    ('0 0/8', 0, '0 0/8'),
    ('0 0/8', .125, '0 1/8'),
    ('0 0/8', .5, '0 4/8'),
    ('0 0/8', 1, '1 0/8'),
    ('0 0/8', 1.5, '1 4/8'),
    ('0 0/8', -.5, '-0 4/8'),
    ('0 0/8', -1.5, '-1 4/8'),
    ('0 0/8', .999, '1 0/8'),
    ('0 0/8', 2.999, '3 0/8'),
    ('0 00/16', .5, '0 08/16'),
    ('0 000/100', -.9375, '-0 094/100'),
    ('0/1', 2.2, '2/1'),
    ('0 0/1', 2.2, '2 0/1'),
    ('0/3', .1875, '1/3'),
    ('0/3', -.9375, '-3/3'),
    ('0/999', .25, '250/999'),
    ('0/999', 1000000, '999000000/999'),
    ('0 000/999', 1000000, '1000000 000/999'),
    ('"part: "0/8"!"', -.5, '-part: 4/8!'),
    ('0/8;[Red](0/8)', -.5, '(4/8)'),
    ('0 0/8;[Red](0 0/8);"zero"', -1.5, '(1 4/8)'),
    ('0 0/8;[Red](0 0/8);"zero"', 0, 'zero'),
    ('0/8;0/8;;@', 0, ''),
    ('0/8;0/8;0/8;@', 1.5, '12/8'),
]


@pytest.mark.parametrize('code,value,expected', CASES)
@pytest.mark.parametrize('kind', ['number', 'formula'])
def test_fraction_display_preserves_stored_value_and_formula_cache(code, value, expected, kind):
    data = ole_workbook(workbook(value, 164, code, kind))
    doc = parse_xls(data)
    cell, = doc.sheets[0].cells
    assert render_number(value, code) == expected
    assert struct.pack('<d', cell.value) == struct.pack('<d', value)
    assert cell.text == expected and cell.value_type == 'number'
    assert cell.is_formula == (kind == 'formula') and cell.formula is None
    assert not any('Unsupported or ambiguous' in w for w in doc.warnings)
    assert len(doc.warnings) == (1 if kind == 'formula' else 0)
    assert json.loads(json.dumps(doc.to_dict()))['sheets'][0]['cells'][0]['text'] == expected


@pytest.mark.parametrize('kind', ['rk', 'mulrk'])
def test_integer_records_and_auto_dispatch(kind):
    data = ole_workbook(workbook(-3, 164, '0 00/16', kind))
    doc = parse(data)
    assert doc.to_dict() == parse_xls(data).to_dict()
    cell = doc.sheets[0].cells[0]
    assert type(cell.value) is int and cell.value == -3
    assert cell.text == '-3 00/16' and not cell.is_formula
    assert not doc.warnings


@pytest.mark.parametrize('code', [
    '# ?/?', '# ??/??', '0/0', '0/00', '0/08', '0/1000', '0/-8', '0/+8',
    '0/８', '0/8.0', '0 /8', '0/ 8', '0/8/2', '0  0/8', '00 0/8',
    '# ?/8', '?/8', '# 0/8', '0 ?/8', '0000/8', '0 0000/8', '0.0/8',
    '0/8%', '0/8,', '#,##0/8', '0/8E+00', '[$$-409]0/8', '[$-409]0/8',
    '[>0]0/8;0/8', '0/8;[<0]0/8', '[>0]0;0/8',
    '0/8;0/8;0/8;[Red]@', '0/8;0/8;0/8;@;@', '0/8;# ?/?',
    '0/8_ ', '0/8* ', '0/8"unfinished', '0/8\\', '0/8\n',
    '0/8' + '""' * 31, '0/' + '9' * 1000,
])
def test_unsupported_mask_is_raw_with_warning(code):
    assert render_number(.125, code) is None
    doc = parse_xls(ole_workbook(workbook(.125, 164, code)))
    cell = doc.sheets[0].cells[0]
    assert (cell.value, cell.value_type, cell.text) == (.125, 'number', '0.125')
    assert sum('Unsupported or ambiguous' in w for w in doc.warnings) == 1


@pytest.mark.parametrize('value', [.0625, .1875, .3125, .5625, .9375,
                                   -.0625, -.9375, 1000000.01, -1000000.01,
                                   1e12, 1.7976931348623157e308])
@pytest.mark.parametrize('code', ['0/8', '0 0/8'])
def test_ambiguous_midpoints_and_outside_magnitude_bound_fall_back(value, code):
    assert render_number(value, code) is None
    doc = parse_xls(ole_workbook(workbook(value, 164, code)))
    cell = doc.sheets[0].cells[0]
    assert cell.value == value and cell.text == str(value)
    assert any('Unsupported or ambiguous' in w for w in doc.warnings)


@pytest.mark.parametrize('value', [math.nextafter(.0625, 0), math.nextafter(.0625, 1)])
def test_neighboring_binary64_values_do_not_guess_midpoint_direction(value):
    assert render_number(value, '0/8') is None


def test_small_values_signed_zero_and_private_decimal_context():
    with localcontext() as ctx:
        ctx.prec = 2
        ctx.traps[Inexact] = True
        assert render_number(5e-324, '000/999') == '000/999'
        assert render_number(-5e-324, '0 000/999') == '0 000/999'
        assert render_number(1.375, '0 00/16') == '1 06/16'
        assert render_number(999999.25, '0/999') == '998999251/999'
        assert render_number(.0625, '0/8') is None


@pytest.mark.parametrize('value', [math.nan, math.inf, -math.inf])
def test_nonfinite_is_not_a_fraction(value):
    assert render_number(value, '0/8') is None
    with pytest.raises(InvalidDocumentError):
        parse_xls(ole_workbook(workbook(value, 164, '0/8')))


def test_complete_mask_validation_and_existing_text_section_helpers():
    assert render_number(.25, '0/8;# ?/?') is None
    assert render_number(.25, '"0/8"') is None
    assert render_number(2, '0"/8"') == '2/8'  # A literal label, not fraction scaling.
    assert text_affixes('0/8;0/8;0/8;"label: "@') == ('label: ', '')
    assert text_literal('0/8;0/8;0/8;"literal"') == 'literal'
    assert text_affixes('0/8;# ?/?;0/8;@') is None


@pytest.mark.parametrize('kind', ['number', 'formula'])
def test_fraction_display_expansion_is_budgeted(kind):
    data = workbook(1000000, 164, '0/999', kind)
    # Decoded FORMAT (5), sheet name (1), rendered number (13).
    assert _parse_workbook(data, Limits(max_text_chars=19)).sheets[0].cells[0].text == '999000000/999'
    with pytest.raises(LimitExceededError):
        _parse_workbook(data, Limits(max_text_chars=18))


@pytest.mark.skipif(os.environ.get('XLS_FRACTIONS_LO') != '1',
                    reason='opt-in independent LibreOffice fixed-FORMAT display oracle')
def test_preserved_xls_formats_match_libreoffice(tmp_path):
    from _xls_format_oracle import generate_preserved

    # Synthetic package skeleton, unique harmless seed masks, exact-length
    # FORMAT replacement, independent CSV display, and public parse_xls checks.
    # Conversion has a private profile, OS resource bounds and process timeout.
    generate_preserved(tmp_path, CASES)


def test_fraction_mask_length_boundary_and_literal_suffix():
    code = '0/8"' + 'x' * 59 + '"'
    assert len(code) == 64
    assert render_number(.5, code) == '4/8' + 'x' * 59
    assert render_number(.5, code[:-1] + 'x"') is None
