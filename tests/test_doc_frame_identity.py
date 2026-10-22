"""Literal synthetic oracles for MS-DOC 2.4.3 first-cell paragraph frames."""
import pytest

from legacy_office_parser.errors import InvalidDocumentError, LimitExceededError
from legacy_office_parser.limits import Limits
from legacy_office_parser.models import Cell, Paragraph, Table
from test_doc import IN, ROW, definition, parse, sprm, u16
from test_doc_external_tables import external, ref
from test_doc_nested import cell, paragraph, row, streams
from test_doc_styles import pap_style, style, stylesheet
from test_doc_table_properties import table_fixture


# Every property named in 2.4.3, with independent operands and defaults.
FRAMES = [
    (0x261B, b'\x50', b'\xf0'), (0x8418, u16(101), u16(0)),
    (0x8419, u16(201), u16(0)), (0x841A, u16(400), u16(0)),
    (0x442B, u16(0x8000 | 200), u16(0)), (0x442C, u16(17), u16(0)),
    (0x2423, b'\2', b'\0'), (0x842F, u16(50), u16(0)),
    (0x842E, u16(60), u16(0)), (0x2430, b'\1', b'\0'),
    (0x2462, b'\1', b'\0'), (0x443A, u16(3), u16(0)),
]
POSITION = [
    sprm(0x360D, 0), sprm(0x3465, 1), sprm(0x940E, u16(101)),
    sprm(0x940F, u16(201)), sprm(0x9410, u16(10)), sprm(0x9411, u16(20)),
    sprm(0x941E, u16(30)), sprm(0x941F, u16(40)),
]
WIDTH = sprm(0x841A, u16(400))
SPLIT = [Table([[Cell('A')]]), Table([[Cell('B')]])]
JOINED = [Table([[Cell('A')], [Cell('B')]])]

# Styles 1..9 are fixed heading indices even in these frame-focused fixtures.
SPLIT_HEADING_B = [Table([[Cell('A')]]), Table([[Cell('B', blocks=[Paragraph('B', 2)])]])]
JOINED_HEADING_B = [Table([[Cell('A')], [Cell('B', blocks=[Paragraph('B', 2)])]])]


def rows(first=b'', second=b'', row_props=b'', **kwargs):
    return table_fixture('A\7\7B\7\7', [
        IN + first, ROW + definition([0]) + row_props,
        IN + second, ROW + definition([0]) + row_props,
    ], **kwargs)


@pytest.mark.parametrize('op,value,default', FRAMES)
@pytest.mark.parametrize('reverse', [False, True])
def test_each_frame_property_splits_only_on_difference(monkeypatch, op, value, default, reverse):
    # Text flow requires a nondefault position/width/wrap/height in the frame.
    common = WIDTH if op == 0x443A else b''
    groups = [common, common + sprm(op, value)]
    if reverse:
        groups.reverse()
    assert parse(monkeypatch, rows(*groups)).blocks == SPLIT
    assert parse(monkeypatch, rows(common, common + sprm(op, default))).blocks == JOINED
    same = common + sprm(op, value)
    assert parse(monkeypatch, rows(same, same)).blocks == JOINED


@pytest.mark.parametrize('position', POSITION)
def test_each_nondefault_table_position_disables_frame_fallback(monkeypatch, position):
    assert parse(monkeypatch, rows(b'', WIDTH, position)).blocks == JOINED


def test_explicit_default_table_positions_still_allow_frame_boundary(monkeypatch):
    defaults = sprm(0x360D, 0xFF) + sprm(0x3465, 0)
    defaults += b''.join(sprm(op, u16(0)) for op in
                         (0x940E, 0x940F, 0x9410, 0x9411, 0x941E, 0x941F))
    assert parse(monkeypatch, rows(b'', WIDTH, defaults)).blocks == SPLIT


def test_later_paragraph_other_cells_and_row_mark_do_not_split(monkeypatch):
    result = parse(monkeypatch, table_fixture('A\7X\7\7B\rC\7Y\7\7', [
        IN, IN, ROW + definition([0, 0]),
        IN, IN + WIDTH, IN + WIDTH, ROW + definition([0, 0]) + WIDTH,
    ]))
    assert result.blocks == [Table([[Cell('A'), Cell('X')], [Cell('B\nC'), Cell('Y')]])]


def test_first_empty_paragraph_counts_and_later_reset_cannot_hide_boundary(monkeypatch):
    result = parse(monkeypatch, table_fixture('A\7\7\rB\7\7', [
        IN, ROW + definition([0]), IN + WIDTH, IN, ROW + definition([0]),
    ]))
    assert result.blocks == [Table([[Cell('A')]]), Table([[Cell('\nB')]])]


def test_hidden_first_paragraph_still_has_frame_identity(monkeypatch):
    source = table_fixture('A\7\7Hidden\rB\7\7', [
        IN, ROW + definition([0]), IN, IN, ROW + definition([0]),
    ])
    stylesheet(source, [style(0), style(1, chpx=sprm(0x083C, 1), papx=WIDTH)])
    pap_style(source, 1, paragraph=2)
    assert parse(monkeypatch, source).blocks == [Table([[Cell('A')]]), Table([[Cell('\nB')]])]


def test_style_inheritance_and_direct_default_override(monkeypatch):
    records = [style(0), style(1, papx=WIDTH), style(2, base=1)]
    source = rows()
    stylesheet(source, records)
    pap_style(source, 2, paragraph=2)
    assert parse(monkeypatch, source).blocks == SPLIT_HEADING_B
    source = rows(b'', sprm(0x841A, u16(0)))
    stylesheet(source, records)
    pap_style(source, 2, paragraph=2)
    assert parse(monkeypatch, source).blocks == JOINED_HEADING_B


def test_child_style_override_and_distinct_styles_same_effect(monkeypatch):
    source = rows()
    stylesheet(source, [style(0), style(1, papx=WIDTH),
                        style(2, base=1, papx=sprm(0x841A, u16(0))), style(3)])
    pap_style(source, 2, paragraph=0)
    pap_style(source, 3, paragraph=2)
    assert parse(monkeypatch, source).blocks == [Table([
        [Cell('A', blocks=[Paragraph('A', 2)])],
        [Cell('B', blocks=[Paragraph('B', 3)])]])]


@pytest.mark.parametrize('before,after,split', [
    (WIDTH, b'', False), (b'', WIDTH, True),
    (WIDTH, sprm(0x841A, u16(0)), False),
])
def test_direct_pistd_resets_frame_then_later_direct_overrides(monkeypatch, before, after, split):
    source = rows(b'', before + sprm(0x4600, u16(0)) + after)
    assert parse(monkeypatch, source).blocks == (SPLIT if split else JOINED)


def test_direct_style_selection_uses_inherited_frame(monkeypatch):
    source = rows(b'', sprm(0x4600, u16(2)))
    stylesheet(source, [style(0), style(1, papx=WIDTH), style(2, base=1)])
    assert parse(monkeypatch, source).blocks == SPLIT_HEADING_B


def test_complex_piece_override_wins_after_styles_and_papx(monkeypatch):
    source = rows(b'', WIDTH, prcs=[sprm(0x841A, u16(0))], prms=[1])
    stylesheet(source, [style(0, papx=WIDTH)])
    assert parse(monkeypatch, source).blocks == JOINED


def test_nested_frames_split_locally_and_preserve_projection(monkeypatch):
    value, props = cell(2, 'B')
    source = streams(paragraph(1, 'Outer'), cell(2, 'A'), row(2),
                     (value, props + WIDTH), row(2), cell(1, 'Tail'), row(1))
    assert parse(monkeypatch, source).blocks == [Table([[Cell('Outer\nA\nB\nTail', blocks=[
        Paragraph('Outer'), Table([[Cell('A')]]), Table([[Cell('B')]]), Paragraph('Tail')])]])]


def test_nested_first_content_does_not_capture_child_frame_for_parent(monkeypatch):
    value, props = cell(2, 'N')
    source = streams(cell(1, 'A'), row(1), (value, props + WIDTH), row(2),
                     cell(1, 'B'), row(1))
    assert parse(monkeypatch, source).blocks == [Table([
        [Cell('A')], [Cell('N\nB', blocks=[Table([[Cell('N')]]), Paragraph('B')])]])]


def test_first_parent_paragraph_is_not_overwritten_by_nested_or_tail(monkeypatch):
    text, props = paragraph(1, 'First')
    source = streams(cell(1, 'A'), row(1), (text, props + WIDTH),
                     cell(2, 'N'), row(2), cell(1, 'Tail'), row(1))
    assert parse(monkeypatch, source).blocks == [Table([[Cell('A')]]), Table([[
        Cell('First\nN\nTail', blocks=[Paragraph('First'), Table([[Cell('N')]]),
                                        Paragraph('Tail')])]])]


def test_vertical_merge_state_cannot_cross_frame_boundary(monkeypatch):
    source = table_fixture('A\7\7\7\7', [
        IN, ROW + definition([96]), IN + WIDTH, ROW + definition([32]),
    ])
    result = parse(monkeypatch, source)
    assert result.blocks == [Table([[Cell('A')]]), Table([[Cell('')]])]
    assert any('Vertical merge without' in w for w in result.warnings)


def test_incomplete_row_does_not_invent_frame_boundary(monkeypatch):
    source = table_fixture('A\7\7B\7', [IN, ROW + definition([0]), IN + WIDTH])
    assert parse(monkeypatch, source).blocks == JOINED


def test_external_papx_and_fallback_frame_snapshot(monkeypatch):
    data, offsets = external(IN + WIDTH)
    # HugePapx is effective only at index 0, so remove leading IN for this paragraph.
    source = table_fixture('A\7\7B\7\7', [
        IN, ROW + definition([0]), ref(offsets[0], 0x6646), ROW + definition([0]),
    ])
    source['Data'] = data
    assert parse(monkeypatch, source).blocks == SPLIT
    source = rows(b'', ref(offsets[0]) + definition([0]))
    source['Data'] = data
    assert parse(monkeypatch, source).blocks == JOINED


@pytest.mark.parametrize('op,value,other', [
    (0x261B, 0x50, 0x5F), (0x442C, 17, 0xAB11), (0x443A, 3, 0xFFFB),
])
def test_ignored_bits_do_not_create_boundaries(monkeypatch, op, value, other):
    encode = (lambda v: bytes([v])) if op == 0x261B else u16
    assert parse(monkeypatch, rows(WIDTH + sprm(op, encode(value)),
                                  WIDTH + sprm(op, encode(other)))).blocks == JOINED


@pytest.mark.parametrize('op,value', [
    (0x8418, -31680), (0x8419, 31682), (0x841A, -1), (0x842E, 31681),
    (0x842F, -1), (0x442B, 0x8000), (0x442B, 31681),
    (0x442C, 3), (0x442C, 1), (0x442C, 89), (0x443A, 2),
    (0x2423, 6), (0x2430, 2), (0x2462, 2),
])
def test_bad_frame_operands_are_structured_errors(monkeypatch, op, value):
    operand = bytes([value]) if op in (0x2423, 0x2430, 0x2462) else u16(value & 65535)
    with pytest.raises(InvalidDocumentError, match='frame'):
        parse(monkeypatch, rows(b'', sprm(op, operand)))


def test_truncation_and_existing_limits(monkeypatch):
    with pytest.raises(InvalidDocumentError):
        parse(monkeypatch, rows(b'', sprm(0x8418, b'')))
    source = rows(b'', WIDTH)
    assert parse(monkeypatch, source, Limits(max_cells=2)).blocks == SPLIT
    with pytest.raises(LimitExceededError, match='cell'):
        parse(monkeypatch, source, Limits(max_cells=1))
    with pytest.raises(LimitExceededError, match='record'):
        parse(monkeypatch, source, Limits(max_records=1))


def test_style_cycle_depth_and_invalid_parent_are_bounded(monkeypatch):
    cases = [([style(0, base=1), style(1, base=0)], Limits(), InvalidDocumentError, 'cyclic'),
             ([style(0, base=1), style(1)], Limits(max_depth=1), LimitExceededError, 'depth'),
             ([style(0, base=1)], Limits(), InvalidDocumentError, 'range')]
    for records, limits, error, message in cases:
        source = rows()
        stylesheet(source, records)
        with pytest.raises(error, match=message):
            parse(monkeypatch, source, limits)


@pytest.mark.parametrize('isprm,op,value', [(0x1D, 0x261B, 0xF0),
                                         (0x25, 0x2423, 0), (0x32, 0x2430, 0)])
def test_compact_piece_frame_override(monkeypatch, isprm, op, value):
    changed = 0x50 if op == 0x261B else 1
    source = rows(b'', sprm(op, changed), prms=[(value << 8) | (isprm << 1)])
    assert parse(monkeypatch, source).blocks == JOINED
    assert not parse(monkeypatch, source).warnings


@pytest.mark.parametrize('op,value,default', FRAMES)
def test_all_frame_properties_inherit_and_directly_reset(monkeypatch, op, value, default):
    common = WIDTH if op == 0x443A else b''
    source = rows(common, common)
    stylesheet(source, [style(0), style(1, papx=sprm(op, value)), style(2, base=1)])
    pap_style(source, 2, paragraph=2)
    assert parse(monkeypatch, source).blocks == SPLIT_HEADING_B
    source = rows(common, common + sprm(op, default))
    stylesheet(source, [style(0), style(1, papx=sprm(op, value)), style(2, base=1)])
    pap_style(source, 2, paragraph=2)
    assert parse(monkeypatch, source).blocks == JOINED_HEADING_B


def test_unknown_first_frame_does_not_invent_boundary(monkeypatch):
    source = table_fixture('\7B\7\7', [ROW, IN + WIDTH, ROW + definition([0])])
    assert parse(monkeypatch, source).blocks == [Table([[Cell('')], [Cell('B')]])]


def test_frame_split_closes_only_previous_grid(monkeypatch):
    source = table_fixture('Wide\7\7A\7B\7\7C\7\7', [
        IN, ROW + definition([0], [0, 200]),
        IN, IN, ROW + definition([0, 0], [0, 100, 200]),
        IN + WIDTH, ROW + definition([0], [0, 200]),
    ])
    assert parse(monkeypatch, source).blocks == [
        Table([[Cell('Wide', col_span=2), Cell(covered=True)], [Cell('A'), Cell('B')]]),
        Table([[Cell('C')]]),
    ]
    with pytest.raises(LimitExceededError, match='cell'):
        parse(monkeypatch, source, Limits(max_cells=4))


def test_nested_style_inheritance_uses_first_paragraph_only(monkeypatch):
    source = streams(cell(2, 'A'), row(2), paragraph(2, 'B'), cell(2, 'C'), row(2),
                     cell(1, 'Tail'), row(1))
    stylesheet(source, [style(0), style(1, papx=WIDTH), style(2, base=1)])
    pap_style(source, 2, paragraph=2)
    assert parse(monkeypatch, source).blocks == [Table([[Cell('A\nB\nC\nTail', blocks=[
        Table([[Cell('A')]]),
        Table([[Cell('B\nC', blocks=[Paragraph('B', 2), Paragraph('C')])]]),
        Paragraph('Tail')])]])]


def test_malformed_style_frame_is_structured_error(monkeypatch):
    source = rows()
    stylesheet(source, [style(0, papx=sprm(0x842E, u16(65535)))])
    with pytest.raises(InvalidDocumentError, match='frame'):
        parse(monkeypatch, source)
