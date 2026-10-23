"""Original exact-fraction expectations; the XLS oracle preserves source FORMAT."""
import json
import math
import os
import struct
from decimal import Inexact, localcontext

import pytest

from legacy_office_parser import Limits, parse, parse_xls
from legacy_office_parser._xls_formats import render_number
from legacy_office_parser.errors import InvalidDocumentError, LimitExceededError
from legacy_office_parser.xls import _parse_workbook
from test_xls import ole_workbook
from test_xls_formats import workbook


# Literal expectations, including every leading/trailing ASCII alignment space.
# No formatter output is used to generate either masks or expected displays.
CASES = [
    ('# ?/?', 0, '0    '),
    ('# ?/?', -0.0, '0    '),
    ('# ?/?', .125, ' 1/8'),
    ('# ?/?', 1 / 3, ' 1/3'),
    ('# ?/?', -1 / 3, '- 1/3'),
    ('# ?/?', 2 / 3, ' 2/3'),
    ('# ?/?', 1 / 7, ' 1/7'),
    ('# ?/?', 8 / 9, ' 8/9'),
    ('# ?/?', 4 / 3, '1 1/3'),
    ('# ?/?', .25, ' 1/4'),
    ('# ?/?', .5, ' 1/2'),
    ('# ?/?', -.5, '- 1/2'),
    ('# ?/?', .75, ' 3/4'),
    ('# ?/?', .2, ' 1/5'),
    ('# ?/?', .4, ' 2/5'),
    ('# ?/?', .6, ' 3/5'),
    ('# ?/?', .8, ' 4/5'),
    ('# ?/?', .875, ' 7/8'),
    ('# ?/?', 1, '1    '),
    ('# ?/?', -1, '-1    '),
    ('# ?/?', 1.5, '1 1/2'),
    ('# ?/?', -1.5, '-1 1/2'),
    ('# ?/?', 1000000, '1000000    '),
    ('# ?/?', 999999.25, '999999 1/4'),
    ('# ??/??', 0, '0      '),
    ('# ??/??', -0.0, '0      '),
    ('# ??/??', .1, '  1/10'),
    ('# ??/??', 1 / 3, '  1/3 '),
    ('# ??/??', -1 / 3, '-  1/3 '),
    ('# ??/??', 1 / 99, '  1/99'),
    ('# ??/??', 98 / 99, ' 98/99'),
    ('# ??/??', 1 / 18, '  1/18'),
    ('# ??/??', 17 / 18, ' 17/18'),
    ('# ??/??', .125, '  1/8 '),
    ('# ??/??', .1875, '  3/16'),
    ('# ??/??', .25, '  1/4 '),
    ('# ??/??', .5, '  1/2 '),
    ('# ??/??', -.5, '-  1/2 '),
    ('# ??/??', .75, '  3/4 '),
    ('# ??/??', .9, '  9/10'),
    ('# ??/??', .06, '  3/50'),
    ('# ??/??', .015625, '  1/64'),
    ('# ??/??', .0125, '  1/80'),
    ('# ??/??', .984375, ' 63/64'),
    ('# ??/??', 1, '1      '),
    ('# ??/??', -1, '-1      '),
    ('# ??/??', 1.5, '1  1/2 '),
    ('# ??/??', -1.5, '-1  1/2 '),
    ('# ??/??', 1000000, '1000000      '),
    ('# ??/??', 999999.25, '999999  1/4 '),
]


@pytest.mark.parametrize('code,value,expected', CASES)
def test_exact_fraction_literal_display(code, value, expected):
    assert render_number(value, code) == expected


@pytest.mark.parametrize('code,value,expected', [
    ('# ?/?', -0.0, '0    '), ('# ??/??', -0.0, '0      '),
    ('# ?/?', -1.5, '-1 1/2'), ('# ??/??', -1.5, '-1  1/2 '),
    ('# ?/?', 1 / 3, ' 1/3'), ('# ??/??', 1 / 99, '  1/99'),
    ('# ?/?', 1000000, '1000000    '), ('# ??/??', 1000000, '1000000      '),
])
@pytest.mark.parametrize('kind', ['number', 'formula'])
@pytest.mark.parametrize('builtin', [False, True])
def test_fraction_biff_transport_preserves_value_cache_and_spaces(code, value, expected, kind, builtin):
    fmt = (12 if code == '# ?/?' else 13) if builtin else 164
    doc = parse_xls(ole_workbook(workbook(value, fmt, None if builtin else code, kind)))
    cell, = doc.sheets[0].cells
    assert struct.pack('<d', cell.value) == struct.pack('<d', value)
    assert cell.text == expected and cell.value_type == 'number'
    assert cell.is_formula == (kind == 'formula') and cell.formula is None
    assert not any('Unsupported or ambiguous' in w for w in doc.warnings)
    assert len(doc.warnings) == (1 if kind == 'formula' else 0)
    assert json.loads(json.dumps(doc.to_dict()))['sheets'][0]['cells'][0]['text'] == expected


@pytest.mark.parametrize('code,value,expected', [
    ('# ?/?', .456, ' 4/9'), ('# ?/?', .001, '0    '),
    ('# ?/?', -.001, '0    '), ('# ?/?', .99, '1    '),
    ('# ??/??', 123.456, '123 31/68'), ('# ??/??', .01, '  1/99'),
    ('# ?/?', 1000000.01, '1000000    '),
])
def test_approximations_preserve_raw_value(code, value, expected):
    doc = parse_xls(ole_workbook(workbook(value, 164, code)))
    cell, = doc.sheets[0].cells
    assert render_number(value, code) == cell.text == expected
    assert struct.pack('<d', cell.value) == struct.pack('<d', value)
    assert not doc.warnings


def test_midpoint_neighbors_choose_nearest_stored_rational():
    assert render_number(math.nextafter(1 / 18, 0), '# ?/?') == '0    '
    assert render_number(math.nextafter(1 / 18, 1), '# ?/?') == ' 1/9'
    assert render_number(math.nextafter(17 / 18, 0), '# ?/?') == ' 8/9'
    assert render_number(math.nextafter(17 / 18, 1), '# ?/?') == '1    '


@pytest.mark.parametrize('code', [   '?/?', '# #/#',
    '0 ?/?', '#  ?/?', '# ? /?',
                                '# ?/?' + '""' * 30, '# ' + '?' * 1000 + '/?'])
def test_other_placeholder_layouts_and_sections_remain_unsupported(code):
    assert render_number(.5, code) is None


def test_denominator_bounds_and_reduction_are_exact():
    assert render_number(.1, '# ?/?') == ' 1/9'
    assert render_number(.01, '# ??/??') == '  1/99'
    assert render_number(.02, '# ??/??') == '  1/50'
    assert render_number(.5, '# ??/??') == '  1/2 '
    assert render_number(math.nextafter(.5, 1), '# ??/??') == '  1/2 '


def test_private_decimal_context():
    with localcontext() as ctx:
        ctx.prec = 2
        ctx.traps[Inexact] = True
        assert render_number(999999.25, '# ??/??') == '999999  1/4 '
        assert render_number(-0.0, '# ?/?') == '0    '
        assert render_number(123.456, '# ??/??') == '123 31/68'


@pytest.mark.parametrize('value', [math.nan, math.inf, -math.inf])
def test_nonfinite_rejected(value):
    for code, fmt in [('# ?/?', 12), ('# ??/??', 13)]:
        assert render_number(value, code) is None
        with pytest.raises(InvalidDocumentError):
            parse_xls(ole_workbook(workbook(value, fmt)))


@pytest.mark.parametrize('kind', ['rk', 'mulrk'])
def test_integer_records_keep_integer_type_and_auto_dispatch(kind):
    data = ole_workbook(workbook(-3, 13, kind=kind))
    doc = parse(data)
    assert doc.to_dict() == parse_xls(data).to_dict()
    cell, = doc.sheets[0].cells
    assert type(cell.value) is int and cell.value == -3
    assert cell.text == '-3      ' and not doc.warnings


@pytest.mark.parametrize('builtin', [False, True])
def test_display_budget_includes_all_alignment_spaces(builtin):
    data = workbook(1000000, 13 if builtin else 164, None if builtin else '# ??/??')
    # Sheet name 1, output 13, plus custom FORMAT length 7 where present.
    size = 14 if builtin else 21
    assert _parse_workbook(data, Limits(max_text_chars=size)).sheets[0].cells[0].text == '1000000      '
    with pytest.raises(LimitExceededError):
        _parse_workbook(data, Limits(max_text_chars=size - 1))


@pytest.mark.skipif(os.environ.get('XLS_VARIABLE_FRACTIONS_LO') != '1',
                    reason='opt-in preserved-source LibreOffice display oracle')
def test_preserved_xls_formats_match_libreoffice(tmp_path):
    from _xls_format_oracle import generate_preserved

    generate_preserved(tmp_path, CASES)


@pytest.mark.parametrize('value,expected', [(1 / 3, '  1/3 '), (1 / 7, '  1/7 '),
                                        (1 / 99, '  1/99'), (98 / 99, ' 98/99')])
def test_adjacent_values_keep_nearest_rational(value, expected):
    for toward in (-math.inf, math.inf):
        assert render_number(math.nextafter(value, toward), '# ??/??') == expected


def test_single_digit_midpoints_use_actual_binary_value():
    assert render_number(1 / 18, '# ?/?') == '0    '
    assert render_number(17 / 18, '# ?/?') == ' 8/9'


def test_large_repeating_fraction_is_bounded_and_context_independent():
    with localcontext() as ctx:
        ctx.prec = 2
        ctx.traps[Inexact] = True
        assert render_number(2999998 / 3, '# ?/?') == '999999 1/3'
