"""Original synthetic MS-DOC row-only visibility and conservative proof failures."""
import struct

import pytest

from legacy_office_parser import Limits, LimitExceededError
from legacy_office_parser.models import Cell, Table
from test_doc import IN, ROW, definition, fixture, parse, sprm, u16
from test_doc_conditional_styles import cnf, table_style
from test_doc_styles import style, stylesheet
from test_doc_table_styles import tistd, vanish


FALLBACK = 'no proven stable rectangular'
RAGGED = [(['A'], [100, 200], [0]), (['B', 'C', 'D'], [0, 100, 200, 300], [0, 0, 0])]


def source(rows, *, chpx=None, look=0x620, tapx=b'', papx=b'',
           row_extra=None, cell_extra=b'', para_chpx=b''):
    text, props = '', []
    for r, (values, edges, flags) in enumerate(rows):
        for value in values:
            text += value + '\7'
            props.extend([IN + cell_extra] * (value.count('\r') + 1))
        text += '\7'
        props.append(ROW + definition(flags, edges) + tistd(16)
                     + struct.pack('<HhH', 0x740A, -1, look)
                     + (row_extra(r) if row_extra else b''))
    return stylesheet(fixture([(text, True)], props=props),
                      [style(0, chpx=para_chpx)] + [b'\0\0'] * 15
                      + [table_style(chpx=cnf(1, 1) if chpx is None else chpx,
                                     tapx=tapx, papx=papx)])


@pytest.mark.parametrize('condition,look,first,last', [
    (1, 0x620, '', ['B', 'C', 'D']),
    (2, 0x640, 'A', ['', '', '']),
    (1, 0x600, 'A', ['B', 'C', 'D']),
    (2, 0x600, 'A', ['B', 'C', 'D']),
])
def test_ragged_row_conditions_preserve_omitted_slots(monkeypatch, condition, look, first, last):
    result = parse(monkeypatch, source(RAGGED, chpx=cnf(condition, 1), look=look))
    assert result.blocks == [Table([
        [Cell(omitted=True), Cell(first), Cell(omitted=True)], [Cell(v) for v in last]])]
    assert not any(FALLBACK in w for w in result.warnings)


@pytest.mark.parametrize('origin', [2, 3])
@pytest.mark.parametrize('condition,look,expected', [(1, 0x620, ''), (2, 0x640, '')])
def test_horizontal_origin_and_empty_continuations(monkeypatch, origin, condition, look, expected):
    result = parse(monkeypatch, source([(['A', '', 'B'], [0, 100, 200, 300], [origin, 1, 0])],
                                       chpx=cnf(condition, 1), look=look))
    assert result.blocks == [Table([[Cell(expected, col_span=2), Cell(covered=True), Cell('')]])]
    assert not any(FALLBACK in w for w in result.warnings)


def test_row_priority_single_merged_row_and_no_invented_column_matches(monkeypatch):
    # All row/column options on, but only row conditions exist. First beats last.
    result = parse(monkeypatch, source([(['A', ''], [0, 100, 200], [2, 1])],
                                       chpx=cnf(2, 1) + cnf(1, 0), look=0x7E0))
    assert result.blocks == [Table([[Cell('A', col_span=2), Cell(covered=True)]])]
    assert not any(FALLBACK in w for w in result.warnings)


@pytest.mark.parametrize('size', [1, 2, 3])
@pytest.mark.parametrize('even', [False, True])
def test_row_bands_count_rows_not_cells_or_spans(monkeypatch, size, even):
    rows = [([str(r)] if r % 2 else [str(r), ''],
             [0, 200] if r % 2 else [0, 100, 200],
             [0] if r % 2 else [2, 1]) for r in range(7)]
    result = parse(monkeypatch, source(rows, look=0x400, chpx=cnf(128 if even else 64, 1),
                                       tapx=sprm(0x3488, size)))
    assert [row[0].text for row in result.blocks[0].rows] == [
        '' if (r // size) % 2 == int(even) else str(r) for r in range(7)]
    assert all(row[0].col_span == 2 and row[1].covered for row in result.blocks[0].rows)
    assert not any(FALLBACK in w for w in result.warnings)


def test_header_prefix_and_isolated_header_do_not_depend_on_grid(monkeypatch):
    rows = [([str(r)], [0, 100 + r], [0]) for r in range(5)]
    result = parse(monkeypatch, source(rows, look=0x420, chpx=cnf(64, 1),
                                       tapx=sprm(0x3488, 1),
                                       row_extra=lambda r: sprm(0x3404, int(r in (0, 1, 4)))))
    assert [row[0].text for row in result.blocks[0].rows] == ['0', '1', '', '3', '']
    assert not any(FALLBACK in w for w in result.warnings)


@pytest.mark.parametrize('look,tapx', [(0x600, sprm(0x3488, 1)), (0x400, b'')])
def test_disabled_or_absent_bands_do_not_hide(monkeypatch, look, tapx):
    result = parse(monkeypatch, source(RAGGED, chpx=cnf(64, 1), look=look, tapx=tapx))
    assert result.blocks[0].rows[0][1].text == 'A'
    assert [c.text for c in result.blocks[0].rows[1]] == ['B', 'C', 'D']
    assert not any(FALLBACK in w for w in result.warnings)


@pytest.mark.parametrize('condition', [4, 8, 16, 32, 256, 512, 1024, 2048])
@pytest.mark.parametrize('look', [0x620, 0x7E0])
def test_column_or_corner_conditions_keep_whole_partition_unknown(monkeypatch, condition, look):
    result = parse(monkeypatch, source(RAGGED, chpx=cnf(1, 1) + cnf(condition, 0), look=look))
    assert result.blocks[0].rows[0][1].text == 'A'
    assert any(FALLBACK in w for w in result.warnings)


@pytest.mark.parametrize('rows', [
    [(['A', 'B'], [0, 100, 200], [2, 1])],  # Nonempty horizontal continuation.
    [(['A', ''], [0, 100, 200], [0, 1])],  # Orphan continuation.
    [(['A', 'B'], [0, 100, 200], [2, 0])],  # Restart without continuation.
    [(['A'], [0, 100], [2])],
    [(['A'], [0, 100], [96]), ([''], [0, 100], [32])],  # Vertical ownership deferred.
    [(['A'], [0, 100], [64])],  # Reserved vertical flag.
    [(['A'], [0, 0], [0])],
    [(['A', 'B'], [0, 100], [0])],  # Definition/physical-cell mismatch.
    [(['A', ''], [0, 100], [2])],  # Short merge flags cannot prove an origin.
])
def test_unproven_ownership_or_grid_never_applies_row_hide(monkeypatch, rows):
    result = parse(monkeypatch, source(rows))
    assert 'A' in result.text
    assert any(FALLBACK in w for w in result.warnings)


@pytest.mark.parametrize('kwargs', [
    {'papx': sprm(0xC666, b'\2\1\0')},
    {'tapx': sprm(0xD66A, b'\2\1\0')},
    {'chpx': cnf(1, 128)}, {'chpx': cnf(1, 129)},
    {'row_extra': lambda r: sprm(0x560B, u16(2))},
])
def test_row_proof_does_not_bypass_existing_style_or_direction_exclusions(monkeypatch, kwargs):
    result = parse(monkeypatch, source(RAGGED, **kwargs))
    assert 'A' in result.text
    assert any(FALLBACK in w for w in result.warnings)


@pytest.mark.parametrize('override', ['paragraph', 'direct', 'inherited'])
def test_literal_show_overrides_and_inherited_conditions(monkeypatch, override):
    data = source(RAGGED, para_chpx=vanish(0) if override == 'paragraph' else b'')
    if override == 'direct':
        from test_doc_fidelity import add_chpx
        add_chpx(data, [1024, 1025, 1034], [vanish(0), None])
    elif override == 'inherited':
        stylesheet(data, [style(0)] + [b'\0\0'] * 15 +
                   [table_style(16, 17, cnf(1, 0)), table_style(17, chpx=cnf(1, 1))])
    result = parse(monkeypatch, data)
    assert result.blocks[0].rows[0][1].text == 'A'
    assert not any(FALLBACK in w for w in result.warnings)


@pytest.mark.parametrize('direction', [0x560B, 0x3466])
def test_logical_row_visibility_is_independent_of_rtl(monkeypatch, direction):
    result = parse(monkeypatch, source(RAGGED, row_extra=lambda r: sprm(direction, u16(1))))
    assert [c.text for c in result.blocks[0].rows[0]] == ['', '', '']
    assert [c.text for c in result.blocks[0].rows[1]] == ['B', 'C', 'D']
    assert not any(FALLBACK in w for w in result.warnings)


def test_multiple_paragraphs_in_merged_origin_share_row_context(monkeypatch):
    result = parse(monkeypatch, source([(['A\rB', ''], [0, 100, 200], [2, 1])]))
    assert result.blocks == [Table([[Cell('\n', col_span=2), Cell(covered=True)]])]
    assert not any(FALLBACK in w for w in result.warnings)


def test_conditional_work_is_cached_and_budgeted_before_clean(monkeypatch):
    from legacy_office_parser import _doc_conditions
    from legacy_office_parser.doc import _Doc
    original_toggle, original_clean = _doc_conditions.toggle, _Doc.clean
    toggles, before_clean = [], []

    def toggle(operand, parent):
        toggles.append((operand, parent))
        return original_toggle(operand, parent)

    def clean(self, *args, **kwargs):
        before_clean.append(self.budget.records)
        return original_clean(self, *args, **kwargs)

    monkeypatch.setattr(_doc_conditions, 'toggle', toggle)
    monkeypatch.setattr(_Doc, 'clean', clean)
    rows = [(['A' * 500, '', 'B' * 500], [0, 100, 200, 300], [2, 1, 0])]
    parse(monkeypatch, source(rows))
    assert toggles == [(1, False)]  # One context, independent of character/cell count.
    threshold = before_clean[0]
    before_clean.clear()
    with pytest.raises(LimitExceededError, match='record'):
        parse(monkeypatch, source(rows), Limits(max_records=threshold - 1))
    assert before_clean == []


@pytest.mark.parametrize('column_condition', [False, True])
def test_ragged_note_visibility_is_known_only_for_row_conditions(monkeypatch, column_condition):
    from test_doc_fidelity import add_chpx, append_table_part
    from test_doc_notes import reference_plc, text_plc

    main, body = '\x02\7\7B\7C\7\7', 'note\r\r'
    select = tistd(16) + struct.pack('<HhH', 0x740A, -1, 0x620)
    data = stylesheet(fixture([(main + body, True)], props=[
        IN, ROW + definition([0], [0, 200]) + select,
        IN, IN, ROW + definition([0, 0]) + select, b'', b''],
        counts=[len(main), len(body), 0, 0, 0, 0, 0]),
        [style(0)] + [b'\0\0'] * 15 +
        [table_style(chpx=cnf(1, 1) + (cnf(4, 0) if column_condition else b''))])
    add_chpx(data, [1024, 1024 + len(main + body)], [sprm(0x0855, 1)])
    append_table_part(data, 2, reference_plc([0]))
    append_table_part(data, 3, text_plc([0, len(body) - 1]))
    result = parse(monkeypatch, data)
    assert result.notes[0].visibility == (['unknown'] if column_condition else ['hidden'])
    assert result.footnotes == 'note\n'
    assert any(FALLBACK in w for w in result.warnings) == column_condition


@pytest.mark.parametrize('extra', [sprm(0x940E, u16(100)), sprm(0x560B, u16(1))])
def test_partition_boundary_restarts_first_row_on_merged_rows(monkeypatch, extra):
    rows = [([str(r), ''], [0, 100, 200], [2, 1]) for r in range(3)]
    result = parse(monkeypatch, source(rows, row_extra=lambda r: extra if r == 0 else b''))
    assert [[row[0].text for row in table.rows] for table in result.blocks] == [[''], ['', '2']]
    assert not any(FALLBACK in w for w in result.warnings)


def test_inherited_column_condition_cannot_be_missed(monkeypatch):
    data = source(RAGGED)
    stylesheet(data, [style(0)] + [b'\0\0'] * 15 +
               [table_style(16, 17, cnf(1, 1)), table_style(17, chpx=cnf(4, 0))])
    result = parse(monkeypatch, data)
    assert 'A' in result.text
    assert any(FALLBACK in w for w in result.warnings)


def test_conditional_show_cannot_override_unknown_ownership(monkeypatch):
    result = parse(monkeypatch, source(RAGGED, chpx=vanish(1) + cnf(1, 0) + cnf(4, 0)))
    assert all(cell.text == '' for row in result.blocks[0].rows for cell in row)
    assert any(FALLBACK in w for w in result.warnings)


def test_ragged_output_grid_still_charges_all_slots(monkeypatch):
    data = source(RAGGED)
    with pytest.raises(LimitExceededError, match='cell'):
        parse(monkeypatch, data, Limits(max_cells=5))
    result = parse(monkeypatch, data, Limits(max_cells=6))
    assert sum(len(row) for row in result.blocks[0].rows) == 6
