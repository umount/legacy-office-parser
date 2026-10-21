"""Independent synthetic MS-DOC 2.4.3 row identity expectations.

Transport/SPRMs come from existing helpers; no production identity helpers
are used to derive expected tables. No private documents or converters.
"""
import struct

import pytest

from legacy_office_parser.errors import InvalidDocumentError, LimitExceededError
from legacy_office_parser.limits import Limits
from legacy_office_parser.models import Cell, Paragraph, Table
from test_doc import IN, ROW, definition, parse, sprm, u16, u32
from test_doc_external_tables import external, ref
from test_doc_nested import cell, row, streams
from test_doc_styles import style, stylesheet
from test_doc_table_properties import table_fixture


# One independently encoded change for every newly supported identity property.
CHANGES = [
    (0x7469, u32(0x12345678)), (0x360D, b'\x50'), (0x3465, b'\1'),
    (0x940E, u16(101)), (0x940F, u16(201)), (0x9410, u16(100)),
    (0x9411, u16(200)), (0x941E, u16(300)), (0x941F, u16(400)),
]


def two_rows(first=b'', second=b''):
    return table_fixture('A\7\7B\7\7', [
        IN, ROW + definition([0]) + first,
        IN, ROW + definition([0]) + second,
    ])


@pytest.mark.parametrize('op,arg', CHANGES)
@pytest.mark.parametrize('reverse', [False, True])
def test_each_identity_property_splits_adjacent_rows(monkeypatch, op, arg, reverse):
    groups = (b'', sprm(op, arg))
    result = parse(monkeypatch, two_rows(*(groups[::-1] if reverse else groups)))
    assert result.blocks == [Table([[Cell('A')]]), Table([[Cell('B')]])]


@pytest.mark.parametrize('op,arg', CHANGES)
def test_equal_identity_and_last_assignment_do_not_split(monkeypatch, op, arg):
    value = sprm(op, arg)
    # Earlier differences are not a boundary: compare effective row properties.
    reset = sprm(op, bytes(len(arg))) + value
    result = parse(monkeypatch, two_rows(value, reset))
    assert result.blocks == [Table([[Cell('A')], [Cell('B')]])]


@pytest.mark.parametrize('op,arg', CHANGES[1:])
def test_explicit_defaults_equal_absent_properties(monkeypatch, op, arg):
    default = b'\xf0' if op == 0x360D else bytes(len(arg))
    result = parse(monkeypatch, two_rows(b'', sprm(op, default)))
    assert result.blocks == [Table([[Cell('A')], [Cell('B')]])]


def test_position_padding_is_ignored(monkeypatch):
    result = parse(monkeypatch, two_rows(sprm(0x360D, 0x50), sprm(0x360D, 0x5F)))
    assert len(result.blocks) == 1


def table_style():
    # STD kind=3 has three UPXs: TAPX, PAPX, CHPX, all empty here.
    raw = u16(0xFFE) + u16(0xFFF3) + u16(3) + bytes(4)
    raw += u16(1) + 'T\0'.encode('utf-16le') + u16(0) * 3
    return u16(len(raw)) + raw


def test_real_table_style_ids_split_and_default_is_eleven(monkeypatch):
    records = [u16(0)] * 13 + [table_style(), table_style()]
    data = two_rows(sprm(0x563A, u16(13)), sprm(0x563A, u16(14)))
    result = parse(monkeypatch, stylesheet(data, records))
    assert result.blocks == [Table([[Cell('A')]]), Table([[Cell('B')]])]
    assert any('Table styles' in warning for warning in result.warnings)
    result = parse(monkeypatch, two_rows(b'', sprm(0x563A, u16(11))))
    assert len(result.blocks) == 1


@pytest.mark.parametrize('index', [0, 1, 2, 65535])
def test_invalid_style_references_are_default_not_boundaries(monkeypatch, index):
    data = two_rows(b'', sprm(0x563A, u16(index)))
    result = parse(monkeypatch, stylesheet(data, [style(0), u16(0), style(2, kind=2)]))
    assert result.blocks == [Table([[Cell('A')], [Cell('B')]])]


def test_nested_boundary_preserves_parent_and_projection(monkeypatch):
    text, props = row(2)
    data = streams(cell(2, 'A'), row(2), cell(2, 'B'),
                   (text, props + sprm(0x941E, u16(100))), cell(1, 'Tail'), row(1))
    result = parse(monkeypatch, data)
    assert result.blocks == [Table([[Cell('A\nB\nTail', blocks=[
        Table([[Cell('A')]]), Table([[Cell('B')]]), Paragraph('Tail')])]])]


def test_new_identity_does_not_merge_with_previous_table(monkeypatch):
    result = parse(monkeypatch, table_fixture('A\7\7\7\7', [
        IN, ROW + definition([96]),
        IN, ROW + definition([32]) + sprm(0x7469, u32(7)),
    ]))
    assert result.blocks == [Table([[Cell('A')]]), Table([[Cell('')]])]
    assert any('Vertical merge without' in warning for warning in result.warnings)


def test_grid_and_multiline_pending_cells_are_preserved(monkeypatch):
    result = parse(monkeypatch, table_fixture('Wide\7\7A\7B\7\7C\rD\7\7', [
        IN, ROW + definition([0], [0, 200]),
        IN, IN, ROW + definition([0, 0], [0, 100, 200]),
        IN, IN, ROW + definition([0], [0, 200]) + sprm(0x9410, u16(100)),
    ]))
    assert result.blocks == [Table([
        [Cell('Wide', col_span=2), Cell(covered=True)], [Cell('A'), Cell('B')]
    ]), Table([[Cell('C\nD')]])]


def test_incomplete_row_retains_previous_identity(monkeypatch):
    result = parse(monkeypatch, table_fixture('A\7\7B\7', [
        IN, ROW + definition([0]) + sprm(0x7469, u32(7)), IN,
    ]))
    assert result.blocks == [Table([[Cell('A')], [Cell('B')]])]
    assert any('without a row terminator' in warning for warning in result.warnings)


def test_identity_only_on_cell_marks_is_not_a_row_boundary(monkeypatch):
    result = parse(monkeypatch, table_fixture('A\7\7B\7\7', [
        IN, ROW + definition([0]),
        IN + sprm(0x9410, u16(100)), ROW + definition([0]),
    ]))
    assert result.blocks == [Table([[Cell('A')], [Cell('B')]])]


@pytest.mark.parametrize('opcode', [0x646B, 0x6646])
def test_external_properties_carry_identity(monkeypatch, opcode):
    data, offsets = external(ROW + definition([0]) + sprm(0x7469, u32(9)))
    source = table_fixture('A\7\7B\7\7', [
        IN, ROW + definition([0]), IN, ref(offsets[0], opcode),
    ])
    source['Data'] = data
    assert parse(monkeypatch, source).blocks == [Table([[Cell('A')]]), Table([[Cell('B')]])]


def test_external_geometry_fallback_restores_identity(monkeypatch):
    data, offsets = external(sprm(0x7469, u32(9)))
    source = table_fixture('A\7\7B\7\7', [
        IN, ROW + definition([0]), IN, ROW + ref(offsets[0]) + definition([0]),
    ])
    source['Data'] = data
    assert parse(monkeypatch, source).blocks == [Table([[Cell('A')], [Cell('B')]])]


def test_piece_modifier_overrides_papx_identity(monkeypatch):
    # Rebuild with the existing helper's genuine CLX Prc/Prm transport.
    source = table_fixture('A\7\7B\7\7', [
        IN, ROW + definition([0]), IN, ROW + definition([0]) + sprm(0x9410, u16(100)),
    ], prcs=[sprm(0x9410, u16(200))], prms=[1])
    assert parse(monkeypatch, source).blocks == [Table([[Cell('A')], [Cell('B')]])]


@pytest.mark.parametrize('op,arg', [
    (0x3465, b'\2'), (0x940E, struct.pack('<h', -31680)),
    (0x940F, struct.pack('<h', 31682)), (0x9410, u16(65535)),
    (0x9411, u16(31681)), (0x941E, u16(65535)), (0x941F, u16(31681)),
])
def test_invalid_position_operands_fail_closed(monkeypatch, op, arg):
    with pytest.raises(InvalidDocumentError, match='operand'):
        parse(monkeypatch, two_rows(b'', sprm(op, arg)))


def test_truncated_identity_and_cell_budget(monkeypatch):
    with pytest.raises(InvalidDocumentError):
        parse(monkeypatch, two_rows(b'', sprm(0x7469, b'\1')))
    source = two_rows(b'', sprm(0x9410, u16(100)))
    assert len(parse(monkeypatch, source, Limits(max_cells=2)).blocks) == 2
    with pytest.raises(LimitExceededError, match='cell'):
        parse(monkeypatch, source, Limits(max_cells=1))
    with pytest.raises(LimitExceededError, match='record'):
        parse(monkeypatch, source, Limits(max_records=1))


@pytest.mark.parametrize('anchor,count', [(0xF0, 1), (0xFF, 1), (0x00, 2)])
def test_absent_anchor_means_unpositioned(monkeypatch, anchor, count):
    result = parse(monkeypatch, two_rows(b'', sprm(0x360D, anchor)))
    assert len(result.blocks) == count
