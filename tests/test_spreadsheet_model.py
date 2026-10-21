import pytest
from legacy_office_parser import Document, Sheet, SpreadsheetCell, CellRange, Limits, LimitExceededError
from legacy_office_parser.api import _validate_result


def test_sparse_text_does_not_materialize_empty_grid():
    doc = Document(format='xls', sheets=[Sheet('Data', cells=[
        SpreadsheetCell(1048576, 16384, text='end'),
        SpreadsheetCell(1, 1, text='start'),
    ])])
    assert doc.text == 'Data\nA1\tstart\nXFD1048576\tend'
    assert doc.to_dict()['sheets'][0]['cells'][0]['row'] == 1048576


def test_formula_and_merge_are_kept_in_json():
    doc = Document(format='ods', sheets=[Sheet('Data', cells=[
        SpreadsheetCell(2, 3, value=3.0, value_type='number', text='3',
                        formula='of:=1+2', is_formula=True)],
        merges=[CellRange(2, 3, 3, 4)])])
    cell = doc.to_dict()['sheets'][0]['cells'][0]
    assert cell['value'] == 3.0 and cell['is_formula']
    assert doc.to_dict()['sheets'][0]['merges'][0]['end_column'] == 4


def test_aggregate_cells_across_sheets_are_bounded():
    doc = Document(format='xls', sheets=[Sheet(str(i), cells=[SpreadsheetCell(1, 1)]) for i in range(2)])
    with pytest.raises(LimitExceededError):
        _validate_result(doc, Limits(max_cells=1))


def test_formula_text_counts_towards_output_budget():
    doc = Document(format='ods', sheets=[Sheet('S', cells=[
        SpreadsheetCell(1, 1, formula='of:=' + '1+' * 100, is_formula=True)])])
    with pytest.raises(LimitExceededError):
        _validate_result(doc, Limits(max_text_chars=100))
