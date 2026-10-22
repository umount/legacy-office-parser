"""Original synthetic XLS optional-decimal probes with literal display oracles."""
import json
import math
import os
import struct
import sys
from decimal import Inexact, Overflow, ROUND_DOWN, Rounded, Underflow, localcontext

import pytest

from legacy_office_parser import Limits, parse, parse_xls
from legacy_office_parser._xls_formats import render_number
from legacy_office_parser.errors import InvalidDocumentError, LimitExceededError
from test_xls import ole_workbook
from test_xls_formats import workbook


# Literal expectations, also used by the independent preserved-FORMAT Calc oracle.
CASES = [
    ('0.#', .12, '0.1'), ('0.#', -.12, '-0.1'),
    ('0.##', .125, '0.13'), ('0.##', -.125, '-0.13'),
    ('0.##', 1.2, '1.2'), ('0.##', -1.2, '-1.2'),
    ('0.##', 1.236, '1.24'), ('0.##', -1.236, '-1.24'),
    ('0.###', 1.201, '1.201'), ('0.###', 1.2301, '1.23'),
    ('0.####', 9.9994, '9.9994'), ('0.#####', .00012, '0.00012'),
    ('0.######', 123456.123456, '123456.123456'),
    ('0.###############', .125, '0.125'),
    ('#,##0.#', 1234.56, '1,234.6'), ('#,##0.##', 1234.5, '1,234.5'),
    ('#,##0.##', -1234.5, '-1,234.5'), ('#,##0.###', 1234567.125, '1,234,567.125'),
    ('"mass "0.##" kg"', 1.236, 'mass 1.24 kg'),
    ('"mass "0.##" kg"', -1.236, '-mass 1.24 kg'),
    ('0.##"%"', .125, '0.13%'), ('0.##\\#', .125, '0.13#'),
    ('[Red]0.##', 1.25, '1.25'),
    ('0.##;(0.##)', -1.25, '(1.25)'),
    ('0.##;[Red](0.##);"zero"', -1.25, '(1.25)'),
    ('0.##;[Red](0.##);"zero"', 0, 'zero'),
    ('0.##;0.##;;@', 1.25, '1.25'),
    ('0.##;0.##;;@', 0, ''),
]


@pytest.mark.parametrize('code,value,expected', CASES)
@pytest.mark.parametrize('kind', ['number', 'formula'])
def test_public_display_preserves_value_and_formula_cache(code, value, expected, kind):
    data = ole_workbook(workbook(value, 164, code, kind))
    doc = parse_xls(data)
    cell, = doc.sheets[0].cells
    assert cell.text == render_number(value, code) == expected
    assert struct.pack('<d', cell.value) == struct.pack('<d', value)
    assert cell.value_type == 'number'
    assert cell.is_formula == (kind == 'formula') and cell.formula is None
    assert not any('Unsupported or ambiguous' in w for w in doc.warnings)
    assert len(doc.warnings) == (kind == 'formula')
    assert json.loads(json.dumps(doc.to_dict()))['sheets'][0]['cells'][0]['text'] == expected
    assert parse(data).to_dict() == doc.to_dict()


@pytest.mark.parametrize('value', [0, -0.0, 1, -1, .004, -.004, 9.999, -9.999,
                                   999.999, sys.float_info.max, 5e-324])
@pytest.mark.parametrize('kind', ['number', 'formula'])
def test_integral_rounded_results_keep_raw_text_and_warning(value, kind):
    code = '#,##0.##'
    doc = parse_xls(ole_workbook(workbook(value, 164, code, kind)))
    cell, = doc.sheets[0].cells
    assert render_number(value, code) is None
    assert cell.text == str(value if isinstance(value, float) else float(value))
    assert struct.pack('<d', cell.value) == struct.pack('<d', value)
    assert cell.value_type == 'number' and cell.is_formula == (kind == 'formula')
    assert sum('Unsupported or ambiguous' in w for w in doc.warnings) == 1


@pytest.mark.parametrize('kind', ['rk', 'mulrk'])
def test_integer_records_keep_integer_type_on_integral_fallback(kind):
    doc = parse_xls(ole_workbook(workbook(-3, 164, '0.##', kind)))
    cell, = doc.sheets[0].cells
    assert type(cell.value) is int and cell.value == -3
    assert cell.text == '-3' and cell.value_type == 'number'
    assert sum('Unsupported or ambiguous' in w for w in doc.warnings) == 1


@pytest.mark.parametrize('code', [
    '0.#0', '0.0#0', '0.##0', '0.????????', '#.##', '00.##', '.##', '0.',
    '0.################', '0.##%', '0.##,', '0.##,,"M"',
    '0.##E+00', '[$$-409]0.##', '0.##[$USD-409]', '[$-409]0.##', '[$-419]0.##',
    '0.##"a"#', '0.##x', '0.##"unfinished', '0.##\\',
])
def test_new_subset_does_not_enable_other_grammars(code):
    doc = parse_xls(ole_workbook(workbook(1.25, 164, code)))
    assert doc.sheets[0].cells[0].text == '1.25'
    assert render_number(1.25, code) is None
    assert sum('Unsupported or ambiguous' in w for w in doc.warnings) == 1


@pytest.mark.parametrize('code', [
    '0.##;0.#0', '0.##;0.##;yyyy', '0.##;0.##;[$-419]0',
    '0.##;0.##;0;@x', '0.##;0.##;0;0.##',
    '[>=0]0.##;0.#0', '0.##;0.##;0;"unfinished',
])
def test_unknown_unselected_sections_still_force_fallback(code):
    doc = parse_xls(ole_workbook(workbook(1.25, 164, code)))
    assert render_number(1.25, code) is None
    assert doc.sheets[0].cells[0].text == '1.25'
    assert sum('Unsupported or ambiguous' in w for w in doc.warnings) == 1


@pytest.mark.parametrize('code,value,expected', [
    ('[>=1]0.##;0.00', 1.236, '1.24'),
    ('[>=1]0.##;0.00', .125, '0.13'),
    ('0.##;0.00;"zero"', -1, '1.00'),
    ('0.##;0.00;"zero"', 0, 'zero'),
])
def test_existing_section_routing_remains_before_rounding(code, value, expected):
    doc = parse_xls(ole_workbook(workbook(value, 164, code)))
    assert doc.sheets[0].cells[0].text == expected
    assert not any('Unsupported or ambiguous' in w for w in doc.warnings)


@pytest.mark.parametrize('value', [-1.25, 1, 9.999])
def test_conditional_negative_and_integral_cases_remain_unsupported(value):
    assert render_number(value, '[>=0]0.##;0.00') is None


def test_hostile_decimal_context_is_neither_used_nor_mutated():
    with localcontext() as ctx:
        ctx.prec, ctx.Emax, ctx.Emin, ctx.rounding = 1, 1, -1, ROUND_DOWN
        for signal in (Inexact, Rounded, Overflow, Underflow):
            ctx.traps[signal] = True
        ctx.clear_flags()
        before = (ctx.prec, ctx.Emax, ctx.Emin, ctx.rounding, dict(ctx.traps), dict(ctx.flags))
        doc = parse_xls(ole_workbook(workbook(1234.125, 164, '#,##0.###')))
        assert doc.sheets[0].cells[0].text == '1,234.125'
        assert render_number(9.999, '0.##') is None
        assert render_number(sys.float_info.max, '0.###############') is None
        assert before == (ctx.prec, ctx.Emax, ctx.Emin, ctx.rounding, dict(ctx.traps), dict(ctx.flags))


@pytest.mark.parametrize('kind', ['number', 'formula'])
def test_public_text_budget_exact_boundary(kind):
    data = ole_workbook(workbook(1234.5, 164, '#,##0.##', kind))
    # Decoded FORMAT 8 + sheet name 1 + displayed cell 7, independently counted.
    assert parse_xls(data, limits=Limits(max_text_chars=16)).sheets[0].cells[0].text == '1,234.5'
    with pytest.raises(LimitExceededError):
        parse_xls(data, limits=Limits(max_text_chars=15))


def test_mask_and_decimal_place_bounds():
    mask = '0.##"' + 'x' * 58 + '"'
    assert len(mask) == 64
    assert render_number(1.25, mask) == '1.25' + 'x' * 58
    assert render_number(1.25, mask[:-1] + 'x"') is None
    assert render_number(.000000000000001, '0.' + '#' * 15) == '0.000000000000001'
    assert render_number(.0000000000000001, '0.' + '#' * 15) is None
    assert render_number(.125, '0.' + '#' * 16) is None
    assert render_number(.125, '0.' + '#' * 100000) is None


@pytest.mark.parametrize('value', [math.inf, -math.inf, math.nan])
def test_nonfinite_values_still_rejected(value):
    with pytest.raises(InvalidDocumentError, match='non-finite'):
        parse_xls(ole_workbook(workbook(value, 164, '0.##')))


@pytest.mark.parametrize('code,value,expected', [
    ('0.0##', 1, '1.0'), ('0.0##', 9.9999, '10.0'),
    ('0.00', 0, '0.00'), ('0.00%', .125, '12.50%'),
    ('0.0,"k"', 1250, '1.3k'), ('[$$-409]0.0#', 1.25, '$1.25'),
    ('0.00E+00', 1, '1.00E+00'), ('0/8', .5, '4/8'),
])
def test_other_existing_cores_keep_their_behavior(code, value, expected):
    assert render_number(value, code) == expected


@pytest.mark.skipif(os.environ.get('XLS_OPTIONAL_DECIMALS_LO') != '1',
                    reason='opt-in independent preserved-source XLS/Calc oracle')
def test_preserved_source_formats_against_libreoffice(tmp_path):
    from _xls_format_oracle import generate_preserved
    generate_preserved(tmp_path, CASES)


@pytest.mark.parametrize('op,threshold', [('<', 2), ('<=', 1.25), ('>', 1),
                                        ('>=', 1.25), ('=', 1.25), ('<>', 2)])
def test_supported_nonnegative_conditions_use_unrounded_value(op, threshold):
    code = f'[{op}{threshold}]0.#;0.00'
    doc = parse_xls(ole_workbook(workbook(1.25, 164, code)))
    assert doc.sheets[0].cells[0].text == '1.3'
    assert not any('Unsupported or ambiguous' in w for w in doc.warnings)


@pytest.mark.parametrize('value,expected', [
    (math.nextafter(.005, 0), None), (.005, '0.01'),
    (math.nextafter(.005, 1), '0.01'),
    (math.nextafter(1, 0), None), (math.nextafter(1, 2), None),
    (1000000.125, '1000000.13'),
])
def test_rounding_boundary_and_large_fractional_value(value, expected):
    assert render_number(value, '0.##') == expected
