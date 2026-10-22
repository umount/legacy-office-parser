"""Public JSON keeps raw text even when its displayed label replaces it."""
import json

import pytest

from legacy_office_parser import parse, parse_xls
from legacy_office_parser.cli import main
from test_xls import ole_workbook
from test_xls_hidden_sections import string_workbook


@pytest.mark.parametrize('kind', ['label', 'formula'])
@pytest.mark.parametrize('mask,display', [('0;0;0;"label"', 'label'), ('0;0;0;""', '')])
def test_literal_display_retains_source_value(tmp_path, capsys, kind, mask, display):
    source = tmp_path / 'literal.xls'
    source.write_bytes(ole_workbook(string_workbook(mask, kind)))
    doc = parse(source)
    assert doc.to_dict() == parse_xls(source).to_dict()
    cell = doc.sheets[0].cells[0]
    assert (cell.value, cell.text, cell.value_type, cell.is_formula) == (
        'retained', display, 'string', kind == 'formula')
    assert doc.text == ('S\nA1\tlabel' if display else 'S')
    assert main([str(source), '--json']) == 0
    result = json.loads(capsys.readouterr().out)['sheets'][0]['cells'][0]
    assert result['value'] == 'retained'
    assert result['text'] == display
    assert result['is_formula'] == (kind == 'formula')
