"""Original nested oracle cases; no private or third-party documents."""
from dataclasses import replace
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from legacy_office_parser import Limits, LimitExceededError, parse_odt
from legacy_office_parser.models import Cell, Document, Paragraph, Table
from test_document_reference import compare, p, tc, tr, tbl, reference

FIXTURES = Path(__file__).parent / 'fixtures' / 'odf_nested'


def nested_case():
    deep = Table([[Cell('deep')]])
    middle = Cell('inside deep tail', blocks=[Paragraph('inside'), deep, Paragraph('tail')])
    inner = Table([[middle, Cell('side')]])
    outer = Cell('before inside deep tail side after',
                 blocks=[Paragraph('before'), inner, Paragraph('after')])
    xml = tbl(tr(tc(content=p('before') + tbl(tr(
        tc(content=p('inside') + tbl(tr(tc('deep'))) + p('tail')) + tc('side'))) + p('after'))))
    return Document('odt', blocks=[Table([[outer]])]), xml


def test_recursive_paths_counts_and_equality():
    doc, xml = nested_case()
    result = compare(doc, xml)
    assert result['equal'] is True
    body = result['body']
    assert body['model_tables'] == body['reference_tables'] == 1
    assert body['model_total_tables'] == body['reference_total_tables'] == 3
    assert body['model_total_cells'] == body['reference_total_cells'] == 4
    child = body['table_checks'][0]['nested_table_checks'][0]
    assert child['path'] == [1, 1, 1, 1]
    assert child['nested_table_checks'][0]['path'] == [1, 1, 1, 1, 1, 1, 1]


@pytest.mark.parametrize('change', ['flatten', 'move', 'reshape', 'projection', 'deep', 'extra'])
def test_same_outer_projection_cannot_hide_structure_changes(change):
    doc, xml = nested_case()
    cell = doc.blocks[0].rows[0][0]
    if change == 'flatten':
        cell.blocks = []
    elif change == 'move':
        cell.blocks = [cell.blocks[1], cell.blocks[0], cell.blocks[2]]
    elif change == 'reshape':
        inner = cell.blocks[1]
        inner.rows = [[inner.rows[0][0]], [inner.rows[0][1]]]
    elif change == 'projection':
        cell.text = 'incomplete'
    elif change == 'deep':
        cell.blocks[1].rows[0][0].blocks[1].rows[0][0].text = 'different'
    else:
        cell.blocks.append(Table([]))
    result = compare(doc, xml)
    assert result['complete'] is True and result['equal'] is False


def test_nested_span_and_omitted_coordinate_are_not_flattened():
    inner = Table([[Cell('a', col_span=2), Cell(covered=True)]])
    doc = Document('odt', blocks=[Table([[Cell('a', blocks=[inner])]])])
    xml = tbl(tr(tc(content=tbl(tr(tc('a', '<w:gridSpan w:val="2"/>')), 2))))
    assert compare(doc, xml)['equal'] is True
    xml = tbl(tr(tc(content=tbl(tr(tc('a')), 2))))
    result = compare(doc, xml)
    assert result['equal'] is False
    child = result['body']['table_checks'][0]['nested_table_checks'][0]
    assert child['reference_omitted_cells'] == 1


def test_nested_vertical_merge():
    inner = Table([[Cell('a', row_span=2)], [Cell(covered=True)]])
    doc = Document('odt', blocks=[Table([[Cell('a', blocks=[inner])]])])
    nested = tbl(tr(tc('a', '<w:vMerge w:val="restart"/>')) + tr(tc('', '<w:vMerge/>')))
    assert compare(doc, tbl(tr(tc(content=nested))))['equal'] is True


def test_nested_unsupported_xml_gates_ancestors_and_has_no_text_leaks():
    doc, xml = nested_case()
    secret = 'PRIVATE_SENTINEL_928'
    xml = xml.replace(p('deep'), '<w:' + secret + '/>' + p(secret))
    result = compare(doc, xml)
    assert result['equal'] is None and result['body']['equal'] is None
    assert result['body']['table_checks'][0]['complete'] is False
    assert result['unsupported_scopes'] == {'xml_scopes': 1}
    assert secret not in json.dumps(result)


def test_unknown_model_blocks_in_unpaired_nested_table_are_inconclusive():
    doc = Document('odt', blocks=[Table([[Cell(blocks=[object()])]])])
    result = compare(doc, '')
    assert result['equal'] is None
    assert result['unsupported_scopes'] == {'model_blocks': 1}


def test_original_odt_fixture_and_all_nested_cell_budgets():
    data = (FIXTURES / 'own_nested.odt').read_bytes()
    doc = parse_odt(data, limits=replace(Limits(), max_cells=4))
    assert doc.blocks[1].rows[0][0].text.split() == [
        'before', 'inside', 'deep', 'tail', 'side', 'after']
    assert isinstance(doc.blocks[1].rows[0][0].blocks[1], Table)
    with pytest.raises(LimitExceededError):
        parse_odt(data, limits=replace(Limits(), max_cells=3))


def test_original_fixture_against_live_libreoffice_reference():
    """Checked-in reference is generated only from the adjacent original ODT."""
    doc = parse_odt((FIXTURES / 'own_nested.odt').read_bytes())
    with ZipFile(FIXTURES / 'own_nested.docx') as archive:
        result = reference.compare_document(doc, archive)
    assert result['equal'] is True, result
    assert result['body']['model_total_cells'] == 4
