"""Public extraction separates a formatted label from its stored string value."""
import json

import pytest

from legacy_office_parser import parse, parse_xls
from legacy_office_parser.cli import main
from test_xls import ole_workbook
from test_xls_hidden_sections import string_workbook


@pytest.mark.parametrize('kind', ['label', 'formula'])
def test_formatted_string_public_projection_and_cli(tmp_path, capsys, kind):
    source = tmp_path / 'text.xls'
    source.write_bytes(ole_workbook(string_workbook('0;0;0;"item: "@"!"', kind)))
    doc = parse(source)
    assert doc.to_dict() == parse_xls(source).to_dict()
    cell = doc.sheets[0].cells[0]
    assert cell.value == 'retained'
    assert cell.value_type == 'string'
    assert cell.text == 'item: retained!'
    assert cell.is_formula == (kind == 'formula')
    assert doc.text == 'S\nA1\titem: retained!'
    assert main([str(source), '--json']) == 0
    data = json.loads(capsys.readouterr().out)
    result = data['sheets'][0]['cells'][0]
    assert result['value'] == 'retained'
    assert result['text'] == 'item: retained!'
    assert result['is_formula'] == (kind == 'formula')
