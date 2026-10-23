"""MS-DOC 2.6.3 row-local columns and 2.9.336 parent-style toggle probes."""
import pytest

from legacy_office_parser import Limits, LimitExceededError
from test_doc import parse, sprm, u16
from test_doc_conditional_rows import FALLBACK, RAGGED, source
from test_doc_conditional_styles import cnf, table_style
from test_doc_styles import style, stylesheet
from test_doc_table_styles import vanish


@pytest.mark.parametrize('condition,look,hidden', [
    (4, 0x680, {'A', 'B'}), (8, 0x700, {'A', 'D'}),
    (512, 0x6A0, {'A'}), (256, 0x720, {'A'}),
    (2048, 0x6C0, {'B'}), (1024, 0x740, {'D'}),
    (16, 0x200, {'A', 'B', 'D'}), (32, 0x200, {'C'}),
])
@pytest.mark.parametrize('rtl', [False, True])
def test_ragged_columns_use_row_source_order_not_output_slots(monkeypatch, condition, look, hidden, rtl):
    result = parse(monkeypatch, source(RAGGED, chpx=cnf(condition, 1), look=look,
                                       tapx=sprm(0x3489, 1),
                                       row_extra=lambda r: sprm(0x560B, u16(int(rtl)))))
    for value in 'ABCD':
        assert (value in result.text) == (value not in hidden)
    assert not any(FALLBACK in w for w in result.warnings)


@pytest.mark.parametrize('condition,look,hidden', [
    (4, 0x680, {'A'}), (8, 0x700, set()),
    (512, 0x6A0, {'A'}), (256, 0x720, set()),
    (16, 0x200, {'A', 'C'}), (32, 0x200, set()),
])
def test_horizontal_origin_keeps_source_column_across_band_and_right_edge(monkeypatch, condition, look, hidden):
    rows = [(['A', '', 'C', ''], [0, 10, 100, 110, 300], [2, 1, 3, 1])]
    result = parse(monkeypatch, source(rows, chpx=cnf(condition, 1), look=look,
                                       tapx=sprm(0x3489, 1)))
    for value in 'AC':
        assert (value in result.text) == (value not in hidden)
    assert [c.col_span for c in result.blocks[0].rows[0] if not c.covered] == [2, 2]
    assert not any(FALLBACK in w for w in result.warnings)


@pytest.mark.parametrize('size,hidden', [(1, {'C'}), (2, {'B'}), (3, {'B', 'C'})])
def test_horizontal_band_count_includes_covered_source_cells(monkeypatch, size, hidden):
    rows = [(['A', '', 'B', 'C'], [0, 20, 40, 60, 80], [2, 1, 0, 0])]
    result = parse(monkeypatch, source(rows, chpx=cnf(16, 1), look=0x280,
                                       tapx=sprm(0x3489, size)))
    for value in 'ABC':
        assert (value in result.text) == (value not in hidden)
    assert not any(FALLBACK in w for w in result.warnings)


@pytest.mark.parametrize('flags', [[2, 0], [3, 0], [96, 0], [98, 0]])
def test_singleton_merge_restart_does_not_require_a_continuation(monkeypatch, flags):
    result = parse(monkeypatch, source([(['A', 'B'], [0, 100, 200], flags)],
                                       look=0x680, chpx=cnf(4, 1)))
    assert 'A' not in result.text and 'B' in result.text
    assert not any(FALLBACK in w for w in result.warnings)


@pytest.mark.parametrize('base_hidden', [0, 1])
@pytest.mark.parametrize('operand', [128, 129])
@pytest.mark.parametrize('parent_rule', [False, True])
def test_relative_toggle_uses_parent_context_including_its_conditions(monkeypatch, base_hidden, operand, parent_rule):
    data = source(RAGGED, look=0x680)
    parent = vanish(base_hidden) + (cnf(4, 1 - base_hidden) if parent_rule else b'')
    stylesheet(data, [style(0)] + [b'\0\0'] * 15 + [
        table_style(16, 17, cnf(4, operand)), table_style(17, chpx=parent)])
    result = parse(monkeypatch, data)
    parent_value = 1 - base_hidden if parent_rule else base_hidden
    hidden = bool(parent_value) ^ (operand == 129)
    for value in 'AB':
        assert (value in result.text) == (not hidden)
    for value in 'CD':
        assert (value in result.text) == (not base_hidden)
    assert not any(FALLBACK in w for w in result.warnings)


def test_relative_toggles_do_not_rebase_on_sibling_conditions_or_local_literals(monkeypatch):
    # Parent first-column hide is the common base. Child row invert shows A,
    # even after a child column show; duplicate local invert remains show.
    data = source(RAGGED, look=0x6A0)
    stylesheet(data, [style(0)] + [b'\0\0'] * 15 + [
        table_style(16, 17, cnf(4, 0) + cnf(1, 1) + cnf(1, 129) + cnf(1, 129)),
        table_style(17, chpx=cnf(4, 1))])
    result = parse(monkeypatch, data)
    assert all(value in result.text for value in 'ABCD')
    assert not any(FALLBACK in w for w in result.warnings)


@pytest.mark.parametrize('override', ['paragraph', 'direct'])
def test_relative_hide_still_yields_to_later_visibility_override(monkeypatch, override):
    data = source(RAGGED, chpx=cnf(1, 129),
                  para_chpx=vanish(0) if override == 'paragraph' else b'')
    if override == 'direct':
        from test_doc_fidelity import add_chpx
        add_chpx(data, [1024, 1025, 1034], [vanish(0), None])
    result = parse(monkeypatch, data)
    assert 'A' in result.text
    assert not any(FALLBACK in w for w in result.warnings)


def test_relative_inheritance_is_bounded_before_clean(monkeypatch):
    from legacy_office_parser.doc import _Doc
    original = _Doc.clean
    records = []

    def clean(self, *args, **kwargs):
        records.append(self.budget.records)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(_Doc, 'clean', clean)
    data = source(RAGGED, chpx=cnf(1, 129))
    parse(monkeypatch, data)
    threshold = records[0]
    records.clear()
    with pytest.raises(LimitExceededError, match='record'):
        parse(monkeypatch, data, Limits(max_records=threshold - 1))
    assert records == []


@pytest.mark.parametrize('edges', [[0, 0, 100], [0, 100, 100], [0, 0, 0]])
def test_zero_width_columns_still_have_source_positions(monkeypatch, edges):
    result = parse(monkeypatch, source([(['A', 'B'], edges, [0, 0])],
                                       look=0x680, chpx=cnf(4, 1)))
    assert 'A' not in result.text and 'B' in result.text
    assert not any(FALLBACK in w for w in result.warnings)



def test_decreasing_source_boundaries_are_malformed_not_an_unsupported_style(monkeypatch):
    from legacy_office_parser import InvalidDocumentError

    with pytest.raises(InvalidDocumentError, match='boundaries are decreasing'):
        parse(monkeypatch, source([(['A'], [100, 0], [0])]))


def nested_source(parts, outer=None, inner=None):
    from test_doc_nested import streams
    return stylesheet(streams(*parts), [style(0)] + [b'\0\0'] * 15 + [
        table_style(16, chpx=cnf(1, 1) if outer is None else outer),
        table_style(17, chpx=cnf(1, 1) if inner is None else inner)])


def selected_row(depth, index=16, flags=(0,), look=0x620):
    import struct
    from test_doc_nested import row
    from test_doc_table_styles import tistd
    text, props = row(depth, flags)
    return text, props + tistd(index) + struct.pack('<HhH', 0x740A, -1, look)


@pytest.mark.parametrize('depth', [2, 3, 4])
def test_implicit_parent_cells_track_nested_content_at_every_depth(monkeypatch, depth):
    from test_doc_nested import cell
    parts = [cell(depth, 'leaf'), selected_row(depth, 17)]
    for parent in range(depth - 1, 0, -1):
        parts += [cell(parent, 'tail' + str(parent)), selected_row(parent)]
    result = parse(monkeypatch, nested_source(parts, inner=cnf(1, 0)))
    assert 'leaf' in result.text
    assert 'tail' not in result.text
    assert not any(FALLBACK in w for w in result.warnings)


@pytest.mark.parametrize('vertical', [False, True])
@pytest.mark.parametrize('show', [False, True])
def test_nested_table_is_nonempty_merge_continuation_even_when_direct_mark_is_empty(
    monkeypatch, vertical, show
):
    from test_doc_nested import cell
    parts = [cell(1, 'origin')]
    if vertical:
        parts += [selected_row(1, flags=(96,))]
    parts += [cell(2, 'inner0'), selected_row(2, 17),
              cell(2, 'inner1'), selected_row(2, 17), cell(1)]
    parts += [selected_row(1, flags=(32,) if vertical else (2, 1))]
    outer = (vanish(1) if show else b'') + cnf(1, 0 if show else 1)
    result = parse(monkeypatch, nested_source(parts, outer=outer))
    # Parent fallback retains its unconditional value; child first-row hide
    # still runs independently, even in an unsupported parent continuation.
    assert ('origin' in result.text) == (not show)
    assert 'inner0' not in result.text and 'inner1' in result.text
    assert any(FALLBACK in w for w in result.warnings)


@pytest.mark.parametrize('vertical', [False, True])
def test_nested_merge_origin_is_supported_and_does_not_taint_empty_continuations(monkeypatch, vertical):
    from test_doc_nested import cell
    parts = [cell(2, 'inner'), selected_row(2, 17), cell(1, 'origin')]
    if vertical:
        parts += [selected_row(1, flags=(96,)), cell(1), selected_row(1, flags=(32,))]
    else:
        parts += [cell(1), selected_row(1, flags=(2, 1))]
    result = parse(monkeypatch, nested_source(parts, inner=cnf(1, 0)))
    assert 'inner' in result.text and 'origin' not in result.text
    assert not any(FALLBACK in w for w in result.warnings)


def test_sibling_nested_tables_keep_parent_columns_and_own_row_ordinals(monkeypatch):
    from test_doc_nested import cell, paragraph
    parts = [cell(2, 'left0'), selected_row(2, 17),
             paragraph(1, 'between'), cell(2, 'left1'), selected_row(2, 17),
             cell(1, 'left-tail'), cell(2, 'right0'), selected_row(2, 17),
             cell(2, 'right1'), selected_row(2, 17), cell(1, 'right-tail'),
             selected_row(1, flags=(0, 0), look=0x680)]
    result = parse(monkeypatch, nested_source(parts, outer=cnf(4, 1)))
    assert 'between' not in result.text and 'left-tail' not in result.text
    assert 'right-tail' in result.text and 'right1' in result.text
    assert all(value not in result.text for value in ('left0', 'left1', 'right0'))
    assert not any(FALLBACK in w for w in result.warnings)


def test_nested_content_without_parent_cell_mark_is_not_a_valid_parent_row(monkeypatch):
    from test_doc_nested import cell, paragraph
    parts = [paragraph(1, 'outer'), cell(2, 'inner'), selected_row(2, 17), selected_row(1)]
    result = parse(monkeypatch, nested_source(parts))
    assert 'outer' in result.text and 'inner' not in result.text
    assert any(FALLBACK in w for w in result.warnings)
