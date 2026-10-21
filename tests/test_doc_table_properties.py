"""Synthetic regressions for effective table properties and row boundaries."""
import struct

import pytest

from legacy_office_parser.errors import InvalidDocumentError, LimitExceededError
from legacy_office_parser.limits import Limits
from legacy_office_parser.models import Table
from test_doc import IN, ROW, definition, fixture, mutate, parse, sprm, u16, u32


def table_fixture(text, props, **kwargs):
    streams = fixture([(text, True)], props=props, **kwargs)
    # Use paragraph-start FCs and an exclusive final FC, including compressed text.
    fcs = [1024] + [1025 + i for i, ch in enumerate(text) if ch in '\r\7']
    at = struct.unpack_from('<I', streams['WordDocument'], 154 + 13 * 8)[0]
    mutate(streams, '1Table', at, b''.join(map(u32, fcs)))
    for i in range(len(props)):
        mutate(streams, 'WordDocument', 4096 + i * 512,
               u32(fcs[i]) + u32(fcs[i + 1]))
    return streams


def delta(value):
    return sprm(0x664A, struct.pack('<i', value))


@pytest.mark.parametrize('depth', [
    sprm(0x6649, u32(2)) + delta(-1),
    delta(1),
    delta(2) + delta(-2) + delta(1),
])
def test_effective_top_level_depth(monkeypatch, depth):
    out = parse(monkeypatch, table_fixture('A\7\7', [
        IN + depth, ROW + definition([0]) + depth,
    ]))
    assert len(out.blocks) == 1
    assert isinstance(out.blocks[0], Table)
    assert out.blocks[0].rows[0][0].text == 'A'
    assert not out.warnings


def test_prc_delta_adjusts_papx_depth(monkeypatch):
    base = sprm(0x6649, u32(2))
    out = parse(monkeypatch, table_fixture('A\7\7', [
        IN + base, ROW + definition([0]) + base,
    ], prcs=[delta(-1)], prms=[1]))
    assert out.blocks[0].rows[0][0].text == 'A'
    assert not out.warnings


@pytest.mark.parametrize('group,error', [
    (delta(-1), InvalidDocumentError),
    (sprm(0x6649, u32(1)) + delta(-2), InvalidDocumentError),
    (sprm(0x6649, u32(0xFFFFFFFF)), InvalidDocumentError),
    (delta(3), LimitExceededError),
    (sprm(0x6649, u32(2)) + delta(1), LimitExceededError),
])
def test_effective_depth_validation(monkeypatch, group, error):
    with pytest.raises(error, match='depth'):
        parse(monkeypatch, table_fixture('A\r', [IN + group]), Limits(max_depth=2))


@pytest.mark.parametrize('flag', [0x244B, 0x244C])
def test_prc_clears_nested_flag(monkeypatch, flag):
    base = IN + sprm(0x6649, u32(2)) + sprm(flag, 1)
    override = sprm(0x6649, u32(1)) + sprm(0x244B, 0) + sprm(0x244C, 0)
    out = parse(monkeypatch, table_fixture('A\7\7', [
        base, ROW + definition([0]),
    ], prcs=[override], prms=[1]))
    assert len(out.blocks) == 1
    assert out.blocks[0].rows[0][0].text == 'A'
    assert not out.warnings


@pytest.mark.parametrize('cleared,retained', [(0x244B, 0x244C), (0x244C, 0x244B)])
def test_clearing_one_inner_flag_preserves_the_other(monkeypatch, cleared, retained):
    group = (IN + sprm(0x6649, u32(2)) + sprm(retained, 1)
             + sprm(cleared, 1) + sprm(cleared, 0))
    out = parse(monkeypatch, table_fixture('A\r', [group]))
    assert out.blocks[0].text == 'A'
    assert any('Nested tables' in warning for warning in out.warnings)


@pytest.mark.parametrize('opcode', [0x560B, 0x5664])
@pytest.mark.parametrize('first,second', [(0, 1), (1, 0)])
def test_direction_change_splits_before_attaching_pending_row(monkeypatch, opcode,
                                                            first, second):
    out = parse(monkeypatch, table_fixture('A\7\7B\rC\7D\7\7', [
        IN, ROW + definition([0]) + sprm(opcode, u16(first)),
        IN, IN, IN, ROW + definition([0, 0]) + sprm(opcode, u16(second)),
    ]))
    assert len(out.blocks) == 2
    assert [[c.text for c in r] for r in out.blocks[0].rows] == [['A']]
    assert [[c.text for c in r] for r in out.blocks[1].rows] == [['B\nC', 'D']]
    assert not out.warnings


def test_effective_direction_is_or_of_independent_latest_values(monkeypatch):
    directions = [
        sprm(0x560B, u16(1)),
        sprm(0x560B, u16(1)) + sprm(0x5664, u16(1)) + sprm(0x560B, u16(0)),
        sprm(0x5664, u16(1)) + sprm(0x5664, u16(0)),
    ]
    props = []
    for direction in directions:
        props.extend([IN, ROW + definition([0]) + direction])
    out = parse(monkeypatch, table_fixture('A\7\7B\7\7C\7\7', props))
    assert [len(table.rows) for table in out.blocks] == [2, 1]
    assert not out.warnings


def test_direction_split_resets_vertical_merge_state(monkeypatch):
    out = parse(monkeypatch, table_fixture('A\7\7\7\7', [
        IN, ROW + definition([96]),
        IN, ROW + definition([32]) + sprm(0x560B, u16(1)),
    ]))
    assert len(out.blocks) == 2
    assert out.blocks[0].rows[0][0].row_span == 1
    assert not out.blocks[1].rows[0][0].covered
    assert any('Vertical merge without' in warning for warning in out.warnings)


def test_split_normalizes_only_the_previous_table(monkeypatch):
    out = parse(monkeypatch, table_fixture('wide\7\7A\7B\7\7C\7\7', [
        IN, ROW + definition([0], [0, 200]),
        IN, IN, ROW + definition([0, 0], [0, 100, 200]),
        IN, ROW + definition([0], [0, 200]) + sprm(0x560B, u16(1)),
    ]))
    assert len(out.blocks) == 2
    assert out.blocks[0].rows[0][0].col_span == 2
    assert out.blocks[0].rows[0][1].covered
    assert len(out.blocks[1].rows[0]) == 1
    assert out.blocks[1].rows[0][0].text == 'C'
    assert out.blocks[1].rows[0][0].col_span == 1
    assert not out.warnings


def test_incomplete_row_does_not_invent_direction_boundary(monkeypatch):
    out = parse(monkeypatch, table_fixture('A\7\7B\7', [
        IN, ROW + definition([0]) + sprm(0x560B, u16(1)), IN,
    ]))
    assert len(out.blocks) == 1
    assert [[c.text for c in r] for r in out.blocks[0].rows] == [['A'], ['B']]
    assert any('without a row terminator' in warning for warning in out.warnings)


def test_incremental_column_width_warns_without_desynchronizing(monkeypatch):
    width = sprm(0x7623, b'\0\1' + struct.pack('<h', 200))
    out = parse(monkeypatch, table_fixture('A\7\7', [
        IN, IN + definition([0]) + width + sprm(0x2417, 1),
    ]))
    assert out.blocks[0].rows[0][0].text == 'A'
    assert any('incremental table geometry' in warning for warning in out.warnings)
