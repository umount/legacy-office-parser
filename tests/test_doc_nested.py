"""Independent MS-DOC 2.4.3 nested-table regressions and original LO fixture.

Only the existing FIB/CLX/PAPX transport builder is reused. Expected hierarchies
are hand-authored; no production table helpers manufacture the oracle.
"""
from pathlib import Path

import pytest

from legacy_office_parser.doc import parse_doc_bytes
from legacy_office_parser.errors import InvalidDocumentError, LimitExceededError
from legacy_office_parser.limits import Limits
from legacy_office_parser.models import Cell, Paragraph, Table
from test_doc import IN, ROW, definition, fixture, parse, sprm, u32

FIXTURES = Path(__file__).parent / 'fixtures' / 'doc_nested'


def member(depth):
    return IN + sprm(0x6649, u32(depth))


def cell(depth, text=''):
    return (text + ('\7' if depth == 1 else '\r'),
            member(depth) + (sprm(0x244B, 1) if depth > 1 else b''))


def row(depth, flags=(0,), edges=None):
    return ('\7' if depth == 1 else '\r',
            (ROW if depth == 1 else member(depth) + sprm(0x244C, 1)) +
            definition(flags, edges))


def paragraph(depth, text):
    return text + '\r', member(depth) if depth else b''


def streams(*parts):
    return fixture([(''.join(text for text, _ in parts), False)],
                   props=[props for _, props in parts])


def test_two_levels_exact_order_and_projection(monkeypatch):
    result = parse(monkeypatch, streams(
        paragraph(0, 'Before'), paragraph(1, 'OuterBefore'),
        cell(2, 'A'), cell(2, 'B'), row(2, (0, 0)),
        cell(2, 'C'), cell(2, 'D'), row(2, (0, 0)),
        cell(1, 'OuterAfter'), cell(1, 'Sibling'), row(1, (0, 0)),
        paragraph(0, 'After')))
    inner = Table([[Cell('A'), Cell('B')], [Cell('C'), Cell('D')]])
    projection = 'OuterBefore\nA\tB\nC\tD\nOuterAfter'
    assert result.blocks == [Paragraph('Before'), Table([[
        Cell(projection, blocks=[Paragraph('OuterBefore'), inner, Paragraph('OuterAfter')]),
        Cell('Sibling')]]), Paragraph('After')]
    assert result.text == 'Before\n\n' + projection + '\tSibling\n\nAfter'
    assert not result.warnings
    encoded = result.to_dict()['blocks'][1]['rows'][0]
    assert 'blocks' in encoded[0] and 'blocks' not in encoded[1]


def test_three_levels_with_parent_text(monkeypatch):
    result = parse(monkeypatch, streams(
        paragraph(1, 'Top'), paragraph(2, 'Middle'), cell(3, 'Deep'), row(3),
        cell(2, 'MiddleTail'), row(2), cell(1, 'TopTail'), row(1)))
    middle = Cell('Middle\nDeep\nMiddleTail', blocks=[
        Paragraph('Middle'), Table([[Cell('Deep')]]), Paragraph('MiddleTail')])
    assert result.blocks == [Table([[Cell('Top\nMiddle\nDeep\nMiddleTail\nTopTail',
        blocks=[Paragraph('Top'), Table([[middle]]), Paragraph('TopTail')])]])]
    assert not result.warnings


@pytest.mark.parametrize('depth', [2, 3])
def test_table_first_enclosing_cells_materialize_all_levels(monkeypatch, depth):
    parts = [cell(depth, 'Leaf'), row(depth)]
    for level in range(depth - 1, 0, -1):
        parts += [cell(level, 'Tail' + str(level)), row(level)]
    result = parse(monkeypatch, streams(*parts))
    expected = Table([[Cell('Leaf')]])
    projection = 'Leaf'
    for level in range(depth - 1, 0, -1):
        projection += '\nTail' + str(level)
        expected = Table([[Cell(projection, blocks=[expected, Paragraph('Tail' + str(level))])]])
    assert result.blocks == [expected]
    assert not result.warnings


def test_table_first_in_adjacent_outer_cells_do_not_coalesce(monkeypatch):
    result = parse(monkeypatch, streams(
        cell(2, 'A'), row(2), cell(1, 'TailA'),
        cell(2, 'B'), row(2), cell(1, 'TailB'), row(1, (0, 0))))
    assert result.blocks == [Table([[
        Cell('A\nTailA', blocks=[Table([[Cell('A')]]), Paragraph('TailA')]),
        Cell('B\nTailB', blocks=[Table([[Cell('B')]]), Paragraph('TailB')])]])]
    assert not result.warnings


def test_sibling_nested_tables_separated_by_parent_paragraph(monkeypatch):
    result = parse(monkeypatch, streams(
        cell(2, 'A'), row(2), paragraph(1, 'Between'),
        cell(2, 'B'), row(2), cell(1, 'Tail'), row(1)))
    assert result.blocks[0].rows[0][0] == Cell('A\nBetween\nB\nTail', blocks=[
        Table([[Cell('A')]]), Paragraph('Between'), Table([[Cell('B')]]), Paragraph('Tail')])
    assert not result.warnings


def test_inner_merges_do_not_leak_to_outer_cells(monkeypatch):
    result = parse(monkeypatch, streams(
        cell(2, 'Anchor'), cell(2), cell(2, 'Right'), row(2, (98, 1, 0)),
        cell(2), cell(2), cell(2, 'Bottom'), row(2, (34, 1, 0)),
        cell(1, 'Tail'), cell(1, 'OuterRight'), row(1, (0, 0))))
    outer = result.blocks[0].rows[0]
    assert len(outer) == 2
    assert outer[0].row_span == outer[0].col_span == 1
    assert outer[1] == Cell('OuterRight')
    assert outer[0].blocks[0] == Table([
        [Cell('Anchor', row_span=2, col_span=2), Cell(covered=True), Cell('Right')],
        [Cell(col_span=2, covered=True), Cell(covered=True), Cell('Bottom')]])
    assert not result.warnings


def grid_streams():
    return streams(cell(2, 'Wide'), cell(2, 'Right'), row(2, (0, 0), [0, 200, 300]),
        cell(2, 'A'), cell(2, 'B'), cell(2, 'C'), row(2, (0, 0, 0), [0, 100, 200, 300]),
        cell(1, 'Tail'), row(1))


def test_inner_grid_expansion_precedes_parent_projection(monkeypatch):
    result = parse(monkeypatch, grid_streams(), Limits(max_cells=7))
    outer = result.blocks[0].rows[0][0]
    assert outer.blocks[0] == Table([
        [Cell('Wide', col_span=2), Cell(covered=True), Cell('Right')],
        [Cell('A'), Cell('B'), Cell('C')]])
    assert outer.text == 'Wide\t\tRight\nA\tB\tC\nTail'
    assert not result.warnings
    with pytest.raises(LimitExceededError, match='cell'):
        parse(monkeypatch, grid_streams(), Limits(max_cells=6))


@pytest.mark.parametrize('ending', ['body', 'eof', 'parent'])
def test_missing_inner_row_marker_recovers_without_lost_text(monkeypatch, ending):
    parts = [paragraph(1, 'Outer'), cell(2, 'Kept')]
    if ending == 'body':
        parts += [paragraph(0, 'After')]
    elif ending == 'parent':
        parts += [cell(1, 'Tail'), row(1)]
    result = parse(monkeypatch, streams(*parts))
    outer = result.blocks[0].rows[0][0]
    assert outer.blocks[:2] == [Paragraph('Outer'), Table([[Cell('Kept')]])]
    assert outer.text == 'Outer\nKept' + ('\nTail' if ending == 'parent' else '')
    assert result.blocks[1:] == ([Paragraph('After')] if ending == 'body' else [])
    assert any('without a row terminator' in w for w in result.warnings)


def test_missing_inner_cell_marker_retains_text_at_row_end(monkeypatch):
    result = parse(monkeypatch, streams(paragraph(2, 'Kept'), row(2), cell(1, 'Tail'), row(1)))
    assert result.blocks[0].rows[0][0].blocks == [Table([[Cell('Kept')]]), Paragraph('Tail')]
    assert any('Row terminator contains content' in w for w in result.warnings)


@pytest.mark.parametrize('marker', [0x244B, 0x244C])
@pytest.mark.parametrize('depth', [0, 1])
def test_inner_marker_without_valid_depth_is_structured_error(monkeypatch, marker, depth):
    with pytest.raises(InvalidDocumentError, match='depth'):
        parse(monkeypatch, streams(('X\r', member(depth) + sprm(marker, 1))))


def test_outer_markers_at_inner_depth_warn_and_preserve_boundaries(monkeypatch):
    result = parse(monkeypatch, streams(('First\7', member(2)),
        cell(2, 'Second'), row(2), cell(1, 'Tail'), row(1)))
    assert result.blocks[0].rows[0][0].blocks[0] == Table([[Cell('First\nSecond')]])
    assert any('Outer table markers' in w for w in result.warnings)


def test_depth_and_total_cell_budgets_include_implicit_parents(monkeypatch):
    data = streams(cell(3, 'Deep'), row(3), cell(2, 'Middle'), row(2), cell(1, 'Top'), row(1))
    assert parse(monkeypatch, data, Limits(max_depth=3, max_cells=3)).text == 'Deep\nMiddle\nTop'
    with pytest.raises(LimitExceededError, match='depth'):
        parse(monkeypatch, data, Limits(max_depth=2))
    with pytest.raises(LimitExceededError, match='cell'):
        parse(monkeypatch, data, Limits(max_cells=2))


def test_retained_projection_budget_counts_every_level_and_paragraph(monkeypatch):
    # 100 leaf characters + middle (100+1+1) projection + retained M (1)
    # + outer (102+1+1) projection + retained O (1) = 308 retained chars.
    # Source CP count (108) is below this; the boundary tests retained storage.
    data = streams(cell(3, 'x' * 100), row(3), cell(2, 'M'), row(2), cell(1, 'O'), row(1))
    assert parse(monkeypatch, data, Limits(max_text_chars=308)).text == 'x' * 100 + '\nM\nO'
    with pytest.raises(LimitExceededError, match='text'):
        parse(monkeypatch, data, Limits(max_text_chars=307))


def test_original_libreoffice_doc_exact_hierarchy():
    result = parse_doc_bytes((FIXTURES / 'own_nested.doc').read_bytes(), Limits())
    deep = Table([[Cell('DeepLeaf')]])
    middle = Table([[Cell('InnerA'), Cell('DeepLeaf\nDeepTail', blocks=[deep, Paragraph('DeepTail')])],
                    [Cell('InnerC'), Cell('InnerD')]])
    first = Cell('InnerA\tDeepLeaf\nDeepTail\nInnerC\tInnerD\nBetween\nSiblingLeaf\nOuterTail',
                 blocks=[middle, Paragraph('Between'), Table([[Cell('SiblingLeaf')]]), Paragraph('OuterTail')])
    assert result.blocks == [Paragraph('Before'), Table([[first, Cell('OuterRight')]]), Paragraph('After')]
    assert not result.warnings


def test_empty_inner_cells_keep_coordinates_and_count_towards_budget(monkeypatch):
    data = streams(cell(2), cell(2, 'Right'), row(2, (0, 0)), cell(1, 'Tail'), row(1))
    result = parse(monkeypatch, data, Limits(max_cells=3))
    assert result.blocks[0].rows[0][0] == Cell('\tRight\nTail', blocks=[
        Table([[Cell(), Cell('Right')]]), Paragraph('Tail')])
    assert not result.warnings
    with pytest.raises(LimitExceededError, match='cell'):
        parse(monkeypatch, data, Limits(max_cells=2))


def test_cleared_inner_flags_do_not_end_cell_or_row(monkeypatch):
    cleared = member(2) + sprm(0x244B, 0) + sprm(0x244C, 0)
    result = parse(monkeypatch, streams(('First\r', cleared), cell(2, 'Second'), row(2),
                                       cell(1, 'Tail'), row(1)))
    assert result.blocks[0].rows[0][0].blocks == [
        Table([[Cell('First\nSecond')]]), Paragraph('Tail')]
    assert not result.warnings


def test_sibling_tables_share_total_cell_budget(monkeypatch):
    data = streams(cell(2, 'A'), row(2), paragraph(1, 'Between'),
                   cell(2, 'B'), row(2), cell(1, 'Tail'), row(1))
    assert parse(monkeypatch, data, Limits(max_cells=3)).text == 'A\nBetween\nB\nTail'
    with pytest.raises(LimitExceededError, match='cell'):
        parse(monkeypatch, data, Limits(max_cells=2))


def test_projection_budget_includes_inner_tabs_and_parent_newline(monkeypatch):
    # Leaf storage 200 + parent projection (100+tab+100+newline+T) 203
    # + retained parent paragraph T (1) = 404. Source CP count is only 206.
    data = streams(cell(2, 'a' * 100), cell(2, 'b' * 100), row(2, (0, 0)),
                   cell(1, 'T'), row(1))
    assert parse(monkeypatch, data, Limits(max_text_chars=404)).text == 'a' * 100 + '\t' + 'b' * 100 + '\nT'
    with pytest.raises(LimitExceededError, match='text'):
        parse(monkeypatch, data, Limits(max_text_chars=403))


def test_original_docx_source_has_table_first_three_level_structure():
    # Validate the independently authored source as well as the converted DOC.
    import xml.etree.ElementTree as ET
    from zipfile import ZipFile

    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    with ZipFile(FIXTURES / 'own_nested.docx') as archive:
        root = ET.fromstring(archive.read('word/document.xml'))
    body = root.find('w:body', ns)
    assert len(root.findall('.//w:tbl', ns)) == 4
    outer = body.find('w:tbl', ns)
    first = outer.find('w:tr/w:tc', ns)
    assert [child.tag.rsplit('}', 1)[-1] for child in first] == ['tcPr', 'tbl', 'p', 'tbl', 'p']
    middle = first.find('w:tbl', ns)
    deep_cell = middle.findall('w:tr/w:tc', ns)[1]
    assert deep_cell.find('w:tbl/w:tr/w:tc/w:p/w:r/w:t', ns).text == 'DeepLeaf'
    assert [node.text for node in root.findall('.//w:t', ns)] == [
        'Before', 'InnerA', 'DeepLeaf', 'DeepTail', 'InnerC', 'InnerD',
        'Between', 'SiblingLeaf', 'OuterTail', 'OuterRight', 'After']
