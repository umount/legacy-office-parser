"""DOC row offsets and exact grids: absence is not a blank or merged cell."""
from dataclasses import replace

import pytest

from legacy_office_parser.errors import LimitExceededError
from legacy_office_parser.limits import Limits
from legacy_office_parser.models import Cell, Document, Paragraph, Table, _clone_cell
from test_doc import IN, ROW, definition, fixture, parse, sprm, u32


def source(rows):
    parts, props = [], []
    for texts, edges, flags in rows:
        parts.extend(t + '\7' for t in texts)
        props.extend(IN for _ in texts)
        parts.append('\7')
        props.append(ROW + definition(flags, edges))
    return fixture([(''.join(parts), False)], props=props)


def test_leading_trailing_absence_keeps_source_empty_cell(monkeypatch):
    result = parse(monkeypatch, source([
        (['Middle'], [100, 200], [0]),
        (['Left', '', 'Right'], [0, 100, 200, 300], [0, 0, 0]),
    ]))
    assert result.blocks == [Table([
        [Cell(omitted=True), Cell('Middle'), Cell(omitted=True)],
        [Cell('Left'), Cell(), Cell('Right')],
    ])]
    assert result.text == '\tMiddle\t\nLeft\t\tRight'
    assert not result.warnings


def test_internal_spans_survive_different_outer_boundaries(monkeypatch):
    result = parse(monkeypatch, source([
        (['Wide'], [100, 300], [0]),
        (['A', 'B', 'C', 'D'], [0, 100, 200, 300, 400], [0, 0, 0, 0]),
    ]))
    assert result.blocks[0].rows == [
        [Cell(omitted=True), Cell('Wide', col_span=2), Cell(covered=True), Cell(omitted=True)],
        [Cell('A'), Cell('B'), Cell('C'), Cell('D')],
    ]
    assert not result.warnings


def test_exact_edges_do_not_snap_small_intervals(monkeypatch):
    result = parse(monkeypatch, source([
        (['Short'], [-10, 100], [0]),
        (['Long'], [-10, 101], [0]),
    ]))
    assert result.blocks[0].rows == [
        [Cell('Short'), Cell(omitted=True)],
        [Cell('Long', col_span=2), Cell(covered=True)],
    ]


def test_vertical_merge_uses_physical_intervals_before_padding(monkeypatch):
    result = parse(monkeypatch, source([
        (['Wide'], [100, 300], [96]),
        (['Left', '', '', 'Right'], [0, 100, 200, 300, 400], [0, 34, 1, 0]),
    ]))
    assert result.blocks[0].rows == [
        [Cell(omitted=True), Cell('Wide', row_span=2, col_span=2),
         Cell(covered=True), Cell(omitted=True)],
        [Cell('Left'), Cell(col_span=2, covered=True), Cell(covered=True), Cell('Right')],
    ]
    assert not result.warnings


def test_padding_does_not_invent_vertical_merge_between_distinct_intervals(monkeypatch):
    result = parse(monkeypatch, source([
        (['Top'], [0, 100], [96]),
        (['Bottom'], [100, 200], [32]),
    ]))
    assert result.blocks[0].rows == [
        [Cell('Top'), Cell(omitted=True)], [Cell(omitted=True), Cell('Bottom')]]
    assert any('Vertical merge' in w for w in result.warnings)


@pytest.mark.parametrize('bad_edges', [[0, 0, 200], [0, 200]])
def test_incomplete_or_zero_grid_is_not_padded(monkeypatch, bad_edges):
    result = parse(monkeypatch, source([
        (['A', 'B'], bad_edges, [0] * (len(bad_edges) - 1)),
        (['C'], [100, 200], [0]),
    ]))
    assert all(not c.omitted for r in result.blocks[0].rows for c in r)
    assert any('cannot be normalized' in w for w in result.warnings)


def test_output_slots_charged_before_expansion(monkeypatch):
    streams = source([(['A'], [100, 200], [0]),
                      (['B', 'C', 'D'], [0, 100, 200, 300], [0, 0, 0])])
    with pytest.raises(LimitExceededError, match='cell'):
        parse(monkeypatch, streams, replace(Limits(), max_cells=5))
    assert len(parse(monkeypatch, streams, replace(Limits(), max_cells=6)).blocks[0].rows[0]) == 3


def test_sparse_disjoint_rows_do_not_allocate_quadratic_grid_before_budget(monkeypatch):
    rows = [([str(i)], [i * 100, (i + 1) * 100], [0]) for i in range(30)]
    with pytest.raises(LimitExceededError, match='cell'):
        parse(monkeypatch, source(rows), replace(Limits(), max_cells=100))


def test_model_json_compatibility_and_clone_absence():
    simple = Cell('Text')
    missing = Cell(omitted=True)
    doc = Document(format='doc', blocks=[Table([[missing, simple, Cell(covered=True)]])])
    encoded = doc.to_dict()['blocks'][0]['rows'][0]
    assert encoded[0] == dict(text='', row_span=1, col_span=1, covered=False, omitted=True)
    assert 'omitted' not in encoded[1] and 'omitted' not in encoded[2]
    nested = Cell('Nested', blocks=[Paragraph('Before'), Table([[missing, simple]])])
    copied = _clone_cell(nested)
    assert copied == nested
    assert copied.blocks[1].rows[0][0] is not missing
    assert _clone_cell(missing).omitted


def test_nested_table_padding_is_preserved_in_parent_projection(monkeypatch):
    member = IN + sprm(0x6649, u32(2))
    inner_cell = member + sprm(0x244B, 1)
    inner_row = member + sprm(0x244C, 1)
    text = 'Middle\r\rLeft\rRight\r\rTail\7\7'
    props = [inner_cell, inner_row + definition([0], [100, 200]),
             inner_cell, inner_cell, inner_row + definition([0, 0], [0, 100, 200]),
             IN, ROW + definition([0])]
    result = parse(monkeypatch, fixture([(text, False)], props=props))
    outer = result.blocks[0].rows[0][0]
    assert outer.text == '\tMiddle\nLeft\tRight\nTail'
    assert outer.blocks[0].rows[0] == [Cell(omitted=True), Cell('Middle')]


@pytest.mark.parametrize('changes', [dict(text='hidden'), dict(covered=True),
    dict(row_span=2), dict(col_span=2), dict(blocks=[Paragraph('hidden')])])
def test_public_result_validation_rejects_invalid_omissions(changes):
    from legacy_office_parser.api import _validate_result
    from legacy_office_parser.errors import InvalidDocumentError
    doc = Document(format='doc', blocks=[Table([[Cell(omitted=True, **changes)]])])
    with pytest.raises(InvalidDocumentError, match='omitted'):
        _validate_result(doc, Limits())


def test_real_ole_row_offset():
    from pathlib import Path
    from legacy_office_parser import parse
    doc = parse(Path(__file__).parent / 'fixtures/doc_offsets/offset_rows.doc')
    rows = next(b.rows for b in doc.blocks if isinstance(b, Table))
    assert rows == [
        [Cell(omitted=True), Cell('Key'), Cell('Value'), Cell('Примечание')],
        [Cell('alpha beta', col_span=2), Cell(covered=True), Cell(), Cell('два слова')],
        [Cell('', col_span=2), Cell(covered=True), Cell('42'), Cell('English and русский')],
    ]


def test_offset_fixture_is_reproducible():
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / 'tools'))
    try:
        from generate_doc_offset_fixture import generate
        assert generate() == (root / 'tests/fixtures/doc_offsets/offset_rows.doc').read_bytes()
    finally:
        sys.path.pop(0)
