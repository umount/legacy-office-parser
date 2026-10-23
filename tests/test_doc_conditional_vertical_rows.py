"""Original binary probes for same-column vertical row-condition ownership."""
import pytest

from legacy_office_parser import Limits, LimitExceededError
from legacy_office_parser.models import Cell, Table
from test_doc import sprm, u16, parse
from test_doc_conditional_rows import FALLBACK, source
from test_doc_conditional_styles import cnf


def rows(origin='A', count=3):
    return [([origin if r == 0 else '', str(r)], [0, 100, 200],
             [96 if r == 0 else 32, 0]) for r in range(count)]


@pytest.mark.parametrize('condition,look,expected', [
    (1, 0x620, ['', '', '1', '2']),
    (2, 0x640, ['A', '0', '1', '']),
    (1, 0x600, ['A', '0', '1', '2']),
])
def test_origin_row_owns_content_not_last_row_of_span(monkeypatch, condition, look, expected):
    result = parse(monkeypatch, source(rows(), chpx=cnf(condition, 1), look=look))
    assert result.blocks == [Table([
        [Cell(expected[0], row_span=3), Cell(expected[1])],
        [Cell(covered=True), Cell(expected[2])],
        [Cell(covered=True), Cell(expected[3])]])]
    assert not any(FALLBACK in w for w in result.warnings)


@pytest.mark.parametrize('size', [1, 2, 3])
@pytest.mark.parametrize('condition', [64, 128])
def test_bands_count_source_rows_not_origin_span(monkeypatch, size, condition):
    result = parse(monkeypatch, source(rows(count=7), chpx=cnf(condition, 1),
                                       look=0x400, tapx=sprm(0x3488, size)))
    grid = result.blocks[0].rows
    assert grid[0][0].text == ('' if condition == 64 else 'A')
    assert grid[0][0].row_span == 7
    assert [row[1].text for row in grid] == [
        '' if (r // size) % 2 == (condition == 128) else str(r) for r in range(7)]
    assert all(row[0].covered for row in grid[1:])
    assert not any(FALLBACK in w for w in result.warnings)


def test_headers_and_later_restart_are_separate_origins(monkeypatch):
    data = rows(count=4)
    data[2] = (['B', '2'], [0, 100, 200], [96, 0])
    result = parse(monkeypatch, source(data, chpx=cnf(64, 1), look=0x420,
                                       tapx=sprm(0x3488, 1),
                                       row_extra=lambda r: sprm(0x3404, int(r < 2))))
    grid = result.blocks[0].rows
    assert [row[1].text for row in grid] == ['0', '1', '', '3']
    assert grid[0][0] == Cell('A', row_span=2)
    assert grid[2][0] == Cell('', row_span=2)
    assert not any(FALLBACK in w for w in result.warnings)


@pytest.mark.parametrize('direction', [0x560B, 0x3466])
def test_equal_grid_ownership_in_either_direction(monkeypatch, direction):
    result = parse(monkeypatch, source(rows(), row_extra=lambda r: sprm(direction, u16(1))))
    assert result.blocks[0].rows[0][0].text == ''
    assert not any(FALLBACK in w for w in result.warnings)


def test_multiple_origin_paragraphs_and_paragraph_override(monkeypatch):
    from test_doc_table_styles import vanish
    result = parse(monkeypatch, source(rows('A\rB'), para_chpx=vanish(0)))
    assert result.blocks[0].rows[0][0].text == 'A\nB'
    assert result.blocks[0].rows[0][0].row_span == 3
    assert not any(FALLBACK in w for w in result.warnings)


@pytest.mark.parametrize('bad', [
    [(['A'], [0, 100], [32])],  # Orphan continuation.
    [(['A'], [0, 100], [96])],  # Restart without continuation.
    [(['A'], [0, 100], [64])],  # Reserved flag.
    [(['A'], [0, 100], [96]), (['B'], [0, 100], [32])],
    [(['A'], [0, 100], [96]), (['\r'], [0, 100], [32])],
    [(['A'], [0, 100], [96]), ([''], [100, 200], [32])],
    [(['A'], [0, 100], [96]), ([''], [0, 200], [32])],
    [(['A'], [0, 100], [96]), ([''], [0, 100], [0]), ([''], [0, 100], [32])],
    [(['A', ''], [0, 100, 200], [96, 0]), (['', ''], [0, 100, 200], [0, 32])],
    [(['A', ''], [0, 100, 200], [98, 1]), (['', ''], [0, 100, 200], [32, 0])],
])
def test_unproven_vertical_ownership_retains_unconditional_visibility(monkeypatch, bad):
    result = parse(monkeypatch, source(bad))
    assert 'A' in result.text
    assert any(FALLBACK in w for w in result.warnings)


@pytest.mark.parametrize('condition', [4, 8, 16, 32, 256, 512, 1024, 2048])
def test_column_and_corner_conditions_still_unknown_even_disabled(monkeypatch, condition):
    result = parse(monkeypatch, source(rows(), chpx=cnf(1, 1) + cnf(condition, 0)))
    assert 'A' in result.text
    assert any(FALLBACK in w for w in result.warnings)


def test_ownership_does_not_cross_table_partition(monkeypatch):
    result = parse(monkeypatch, source(rows(), row_extra=lambda r:
                                       sprm(0x940E, u16(100)) if r == 0 else b''))
    assert 'A' in result.text
    assert any(FALLBACK in w for w in result.warnings)


def test_proof_work_is_budgeted_before_clean(monkeypatch):
    from legacy_office_parser import _doc_conditions
    from legacy_office_parser.doc import _Doc
    original, original_clean = _doc_conditions.vertical_row_context, _Doc.clean
    start = []
    cleaned = []

    def proof(rows, budget):
        start.append(budget.records)
        return original(rows, budget)

    def clean(self, *args, **kwargs):
        cleaned.append(True)
        return original_clean(self, *args, **kwargs)

    monkeypatch.setattr(_doc_conditions, 'vertical_row_context', proof)
    monkeypatch.setattr(_Doc, 'clean', clean)
    parse(monkeypatch, source(rows()))
    threshold = start[0]
    cleaned.clear()
    # Six physical cells require six charged proof steps before visibility work.
    with pytest.raises(LimitExceededError, match='record'):
        parse(monkeypatch, source(rows()), Limits(max_records=threshold + 5))
    assert cleaned == []


def test_output_cells_remain_budgeted(monkeypatch):
    with pytest.raises(LimitExceededError, match='cell'):
        parse(monkeypatch, source(rows()), Limits(max_cells=5))
    assert len(parse(monkeypatch, source(rows()), Limits(max_cells=6)).blocks[0].rows) == 3


@pytest.mark.parametrize('ambiguous', [False, True])
def test_note_in_origin_visibility_known_only_with_proven_chain(monkeypatch, ambiguous):
    import struct
    from test_doc import IN, ROW, definition, fixture
    from test_doc_conditional_styles import table_style
    from test_doc_styles import style, stylesheet
    from test_doc_table_styles import tistd
    from test_doc_fidelity import add_chpx, append_table_part
    from test_doc_notes import reference_plc, text_plc

    main, body = '\x02\7\7\7\7', 'note\r\r'
    select = tistd(16) + struct.pack('<HhH', 0x740A, -1, 0x620)
    data = stylesheet(fixture([(main + body, True)], props=[
        IN, ROW + definition([96], [0, 100]) + select,
        IN, ROW + definition([32], [0, 200 if ambiguous else 100]) + select, b'', b''],
        counts=[len(main), len(body), 0, 0, 0, 0, 0]),
        [style(0)] + [b'\0\0'] * 15 + [table_style(chpx=cnf(1, 1))])
    add_chpx(data, [1024, 1024 + len(main + body)], [sprm(0x0855, 1)])
    append_table_part(data, 2, reference_plc([0]))
    append_table_part(data, 3, text_plc([0, len(body) - 1]))
    result = parse(monkeypatch, data)
    assert result.notes[0].visibility == (['unknown'] if ambiguous else ['hidden'])
    assert result.notes[0].source_cp == 0
    assert result.footnotes == 'note\n'
    assert any(FALLBACK in w for w in result.warnings) == ambiguous


def test_two_columns_have_independent_chain_lengths(monkeypatch):
    data = [(['A', 'B'], [0, 100, 200], [96, 96]),
            (['', ''], [0, 100, 200], [32, 32]),
            (['', 'C'], [0, 100, 200], [32, 0])]
    result = parse(monkeypatch, source(data, chpx=cnf(2, 1), look=0x640))
    assert result.blocks == [Table([
        [Cell('A', row_span=3), Cell('B', row_span=2)],
        [Cell(covered=True), Cell(covered=True)],
        [Cell(covered=True), Cell('')]])]
    assert not any(FALLBACK in w for w in result.warnings)


@pytest.mark.parametrize('inherited_column', [False, True])
def test_inheritance_and_direct_override_with_vertical_ownership(monkeypatch, inherited_column):
    from test_doc_fidelity import add_chpx
    from test_doc_conditional_styles import table_style
    from test_doc_styles import style, stylesheet
    from test_doc_table_styles import vanish

    data = source(rows())
    if inherited_column:
        stylesheet(data, [style(0)] + [b'\0\0'] * 15 + [
            table_style(16, 17, cnf(1, 1)), table_style(17, chpx=cnf(4, 0))])
    else:
        # Override only the first source character, leaving the adjacent cell hidden.
        add_chpx(data, [1024, 1025, 1037], [vanish(0), None])
    result = parse(monkeypatch, data)
    assert result.blocks[0].rows[0][0].text == 'A'
    assert result.blocks[0].rows[0][1].text == ('0' if inherited_column else '')
    assert any(FALLBACK in w for w in result.warnings) == inherited_column
