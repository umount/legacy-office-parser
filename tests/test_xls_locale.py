"""Numeric locale affects display cores, never stored values or authored literals."""
import json

import pytest

from legacy_office_parser import Limits, NumberLocale, parse, parse_xls
from legacy_office_parser.cli import main
from legacy_office_parser.errors import LimitExceededError
from test_xls import ole_workbook
from test_xls_formats import workbook


def data(value=1227483, code='#,##0.00', kind='number'):
    return ole_workbook(workbook(value, 164, code, kind))


@pytest.mark.parametrize('locale,expected', [
    (None, '1,227,483.00'), ('en-US', '1,227,483.00'),
    ('ru-RU', '1\u00a0227\u00a0483,00'), ('de-DE', '1.227.483,00'),
    ('fr-FR', '1\u202f227\u202f483,00'),
    (NumberLocale('.', "'"), "1'227'483.00"),
])
def test_locale_public_api_and_detection(locale, expected):
    result = parse(data(), display_locale=locale)
    cell, = result.sheets[0].cells
    assert cell.value == 1227483 and cell.value_type == 'number'
    assert cell.text == expected and expected in result.text
    assert not result.warnings
    assert parse_xls(data(), display_locale=locale).to_dict() == result.to_dict()


def test_locale_keeps_literals_formula_cache_and_general():
    doc = parse_xls(data(1234.5, '"v1.0, "#,##0.00" kg."', 'formula'),
                    display_locale='ru-RU')
    cell, = doc.sheets[0].cells
    assert (cell.value, cell.text, cell.is_formula) == (1234.5, 'v1.0, 1\u00a0234,50 kg.', True)
    assert len(doc.warnings) == 1  # Cached formula warning remains.
    assert parse_xls(data(.5, 'General'), display_locale='de-DE').sheets[0].cells[0].text == '0,5'
    assert parse_xls(data(61, 'yyyy-mm-dd'), display_locale='ru-RU').sheets[0].cells[0].text == '1900-03-01'
    assert parse_xls(data(1.5, '0.00yyyy'), display_locale='ru-RU').sheets[0].cells[0].text == '1.5'


def test_locale_is_per_call_and_subject_to_text_budget():
    source = data(1234.5, '"v1.0 "#,##0.00')
    localized = parse_xls(source, display_locale='ru-RU').to_dict()
    parse_xls(source, display_locale='de-DE')
    assert parse_xls(source, display_locale='ru-RU').to_dict() == localized
    with pytest.raises(LimitExceededError):
        parse_xls(source, display_locale='ru-RU', limits=Limits(max_text_chars=10))
    assert parse(b'{\\rtf1 Plain}', display_locale='ru-RU').text == 'Plain'


def test_locale_cli_and_invalid_options(tmp_path, capsys):
    path = tmp_path / 'numbers.xls'
    path.write_bytes(data())
    assert main([str(path), '--json', '--display-locale', 'ru-RU']) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)['sheets'][0]['cells'][0]['text'] == '1\u00a0227\u00a0483,00'
    assert main([str(path), '--display-locale', 'unknown']) == 2
    assert 'invalid options' in capsys.readouterr().err
    for decimal, grouping in [('.', '.'), (' ', ','), ('..', ','), ('0', ','), ('.', '\n')]:
        with pytest.raises(ValueError):
            NumberLocale(decimal, grouping)
    with pytest.raises(TypeError):
        parse_xls(data(), display_locale=123)
