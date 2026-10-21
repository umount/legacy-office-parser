"""Synthetic omission comparisons; no fixtures, conversion, or private documents."""
from collections import Counter
import json

import pytest

from legacy_office_parser.models import Cell, Document, Table
from test_document_reference import compare, reference, tc, tr, tbl


@pytest.mark.parametrize('before,after,grid', [(1, 0, 2), (0, 1, 2), (1, 1, 3),
                                              (0, 0, 3), (1, 0, 3)])
def test_docx_edge_omissions_and_partial_rows(before, after, grid):
    props = f'<w:gridBefore w:val="{before}"/><w:gridAfter w:val="{after}"/>'
    row = [Cell(omitted=True) for _ in range(grid)]
    row[before] = Cell('value')
    doc = Document('doc', blocks=[Table([row])])
    xml = tbl(tr(tc('value'), props), grid)
    result = compare(doc, xml)
    assert result['complete'] is True and result['equal'] is True
    check = result['body']['table_checks'][0]
    assert check['dimensions_equal'] is True
    assert check['model_cells'] == check['reference_cells'] == 1
    assert check['reference_omitted_cells'] == grid - 1
    assert result['body']['model_total_cells'] == result['body']['reference_total_cells'] == 1

    for col, cell in enumerate(row):
        if not cell.omitted:
            continue
        for replacement in (Cell(), Cell(covered=True)):
            row[col] = replacement
            check = compare(doc, xml)['body']['table_checks'][0]
            assert check['equal'] is False and check['dimensions_equal'] is True
            mismatch, = check['cell_mismatches']
            assert (mismatch['row'], mismatch['column']) == (1, col + 1)
            assert mismatch['model_present'] is True
            assert mismatch['reference_present'] is False
        row[col] = cell


@pytest.mark.parametrize('covered', [False, True])
def test_omitted_cannot_match_present_empty_or_covered(covered):
    props = '<w:gridSpan w:val="2"/>' if covered else ''
    xml = tbl(tr(tc('anchor', props) + ('' if covered else tc())), 2)
    doc = Document('doc', blocks=[Table([[Cell('anchor', col_span=2 if covered else 1),
                                        Cell(omitted=True)]])])
    result = compare(doc, xml)
    assert result['equal'] is False
    mismatch, = result['body']['table_checks'][0]['cell_mismatches']
    assert mismatch['column'] == 2
    assert mismatch['model_present'] is False and mismatch['reference_present'] is True


@pytest.mark.parametrize('width', [1, 2, 4])
def test_row_width_mismatch_is_never_tolerated(width):
    row = [Cell('value')] + [Cell(omitted=True) for _ in range(width - 1)]
    result = compare(Document('doc', blocks=[Table([row])]), tbl(tr(tc('value')), 3))
    check = result['body']['table_checks'][0]
    assert result['equal'] is False and check['dimensions_equal'] is False
    assert check['cell_mismatches'] == []


def test_interior_omission_retains_indices_and_presence_distinctions():
    # DOCX gridBefore/gridAfter cannot express an interior gap. Exercise the
    # sparse reference representation directly without inventing DOCX semantics.
    expected = reference._ReferenceTable([{0: Cell('left'), 2: Cell('right')}], [3], True)
    row = [Cell('left'), Cell(omitted=True), Cell('right')]
    model = Table([row])
    assert reference._table_check(model, expected, 1)['equal'] is True
    for replacement in (Cell(), Cell(covered=True)):
        row[1] = replacement
        check = reference._table_check(model, expected, 1)
        mismatch, = check['cell_mismatches']
        assert mismatch['column'] == 2 and mismatch['reference_present'] is False
        assert check['equal'] is False
    row[:] = [Cell('left'), Cell('right'), Cell(omitted=True)]
    check = reference._table_check(model, expected, 1)
    assert [m['column'] for m in check['cell_mismatches']] == [2, 3]


def test_nested_omissions_counts_include_covered_and_preserve_paths():
    inner = Table([[Cell(omitted=True), Cell('value', col_span=2), Cell(covered=True),
                    Cell(omitted=True)]])
    doc = Document('doc', blocks=[Table([[Cell('value', blocks=[inner])]])])
    xml = tbl(tr(tc(content=tbl(tr(tc('value', '<w:gridSpan w:val="2"/>'),
                                  '<w:gridBefore w:val="1"/><w:gridAfter w:val="1"/>'), 4))))
    result = compare(doc, xml)
    assert result['equal'] is True
    body = result['body']
    assert body['model_total_tables'] == body['reference_total_tables'] == 2
    assert body['model_total_cells'] == body['reference_total_cells'] == 3
    child, = body['table_checks'][0]['nested_table_checks']
    assert child['model_cells'] == child['reference_cells'] == 2
    assert child['reference_omitted_cells'] == 2
    inner.rows[0][0] = Cell()
    result = compare(doc, xml)
    assert result['equal'] is False
    child, = result['body']['table_checks'][0]['nested_table_checks']
    mismatch, = child['cell_mismatches']
    assert mismatch['path'] == [1, 1, 1, 1, 1, 1]


def test_multiple_partial_rows_keep_row_indices_and_counts():
    model = Table([[Cell('a'), Cell(omitted=True)],
                   [Cell(omitted=True), Cell('b')],
                   [Cell(omitted=True), Cell(omitted=True)]])
    xml = tbl(tr(tc('a')) + tr(tc('b'), '<w:gridBefore w:val="1"/>') +
              tr('', '<w:gridAfter w:val="2"/>'), 2)
    result = compare(Document('doc', blocks=[model]), xml)
    assert result['equal'] is True
    check = result['body']['table_checks'][0]
    assert check['model_rows'] == check['reference_rows'] == 3
    assert check['model_cells'] == check['reference_cells'] == 2
    assert check['reference_omitted_cells'] == 4
    model.rows[1][1].text = 'changed'
    check = compare(Document('doc', blocks=[model]), xml)['body']['table_checks'][0]
    mismatch, = check['cell_mismatches']
    assert (mismatch['row'], mismatch['column']) == (2, 2)
    assert mismatch['text_equal'] is False


def test_counts_do_not_traverse_absent_slots():
    absent = Cell(omitted=True)
    absent.blocks = [Table([[Cell('unreachable')]])]
    unsupported = Counter()
    assert reference._model_counts([Table([[absent, Cell(covered=True), Cell()]])],
                                   unsupported) == (1, 2)
    assert unsupported == {'invalid_model_omitted': 1}


@pytest.mark.parametrize('field,value', [
    ('text', 'FORGED_PRIVATE_TEXT'), ('text', ' '), ('covered', True),
    ('row_span', 2), ('col_span', 2), ('row_span', 0), ('col_span', 0),
    ('blocks', [Table([[Cell('FORGED_PRIVATE_NESTED')]])]),
])
@pytest.mark.parametrize('placement', ['body', 'nested', 'unpaired'])
def test_forged_omitted_cells_make_comparison_inconclusive(field, value, placement):
    omitted = Cell(omitted=True)
    # Forge after construction, including when public model validation is added.
    setattr(omitted, field, value)
    table = Table([[Cell('value'), omitted]])
    xml = tbl(tr(tc('value')), 2)
    if placement == 'nested':
        table = Table([[Cell('value', blocks=[table])]])
        xml = tbl(tr(tc(content=xml)))
    elif placement == 'unpaired':
        xml = ''
    result = compare(Document('doc', blocks=[table]), xml)
    assert result['status'] == 'inconclusive'
    assert result['complete'] is False and result['equal'] is None
    assert result['unsupported_scopes'] == {'invalid_model_omitted': 1}
    assert result['body']['complete'] is False and result['body']['equal'] is None
    if placement != 'unpaired':
        check, = result['body']['table_checks']
        assert check['complete'] is False and check['equal'] is None
        if placement == 'nested':
            child, = check['nested_table_checks']
            assert child['complete'] is False and child['equal'] is None
    assert 'FORGED_PRIVATE' not in json.dumps(result)


def test_invalid_omitted_counter_counts_cells_not_violations():
    first, second = Cell(omitted=True), Cell(omitted=True)
    first.text, first.covered, first.col_span = 'forged', True, 2
    second.row_span = 2
    result = compare(Document('doc', blocks=[Table([[first, second]])]), tbl(tr(''), 2))
    assert result['unsupported_scopes'] == {'invalid_model_omitted': 2}
    assert result['equal'] is None
