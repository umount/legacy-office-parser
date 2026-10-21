"""Independent synthetic WordDocument/1Table/Data streams; no corpus inputs.

Only the OLE transport is substituted. FIB, CLX, PLC, PAPX, references,
paragraph routing, merging and grid normalization run through the public parser.
"""
from contextlib import contextmanager
import struct

import pytest

from legacy_office_parser import doc
from legacy_office_parser.errors import InvalidDocumentError, LimitExceededError
from legacy_office_parser.limits import Limits


def p(op, arg):
    return struct.pack('<H', op) + arg


def ref(offset, op=0x646B):
    return p(op, struct.pack('<I', offset))


def insert(first, count, width):
    return p(0x7621, struct.pack('<BBh', first, count, width))


def resize(first, stop, width):
    return p(0x7623, struct.pack('<BBh', first, stop, width))


def delete(first, stop):
    return p(0x5622, bytes([first, stop]))


def merge(first, stop):
    return p(0x5624, bytes([first, stop]))


def vm(cell, value):
    return p(0xD62B, bytes([2, cell, value]))


def definition(edges, flags=None):
    n = len(edges) - 1
    body = bytes([n]) + struct.pack('<' + 'h' * len(edges), *edges)
    body += b''.join(struct.pack('<H', f) + bytes(18) for f in (flags or [0] * n))
    return p(0xD608, struct.pack('<H', len(body) + 1) + body)


IN = p(0x2416, b'\1')
ROW = IN + p(0x2417, b'\1')
NOOP = p(0x6467, bytes(4))


def external(*groups):
    """Offsets are returned, never borrowed from another test fixture."""
    data, offsets = bytearray(), []
    for group in groups:
        # PRSID is an irrelevant, complete Prl, not invented padding bytes.
        while len(group) < 10:
            group += NOOP
        offsets.append(len(data))
        data += struct.pack('<H', len(group)) + group
    return bytes(data), offsets


def streams(rows, groups, data=b'', prc=b''):
    text = ''.join(''.join(cell + '\7' for cell in row) + '\7' for row in rows)
    raw = text.encode('utf-16le')
    starts = [2048] + [2048 + 2 * (i + 1) for i, ch in enumerate(text) if ch == '\7']
    props = []
    for row, group in zip(rows, groups):
        props.extend([IN] * len(row) + [ROW + group])
    assert len(starts) == len(props) + 1
    word = bytearray(8192 + 512 * len(props))
    def w16(at, value):
        struct.pack_into('<H', word, at, value)
    def w32(at, value):
        struct.pack_into('<I', word, at, value)
    w16(0, 0xA5EC)
    w16(2, 0xC1)
    w16(10, 0x200)
    w16(32, 14)
    w16(62, 22)
    w16(152, 93)
    w32(64, len(word))
    w32(76, len(text))
    assert 2048 + len(raw) < 8192
    word[2048:2048 + len(raw)] = raw
    plc = struct.pack('<IIHIH', 0, len(text), 0, 2048, 1 if prc else 0)
    clx = (b'\1' + struct.pack('<H', len(prc)) + prc if prc else b'')
    clx += b'\2' + struct.pack('<I', len(plc)) + plc
    bins = struct.pack('<' + 'I' * len(starts), *starts)
    bins += struct.pack('<' + 'I' * len(props), *range(16, 16 + len(props)))
    w32(154 + 33 * 8, 0)
    w32(158 + 33 * 8, len(clx))
    w32(154 + 13 * 8, len(clx))
    w32(158 + 13 * 8, len(bins))
    for i, group in enumerate(props):
        at = 8192 + i * 512
        w32(at, starts[i])
        w32(at + 4, starts[i + 1])
        word[at + 8] = 32
        word[at + 511] = 1
        payload = bytes(2) + group
        payload += bytes(len(payload) % 2)
        assert len(payload) < 440
        word[at + 64:at + 66] = bytes([0, len(payload) // 2])
        word[at + 66:at + 66 + len(payload)] = payload
    return {'WordDocument': bytes(word), '1Table': clx + bins, 'Data': data}


def parse(monkeypatch, source, limits=Limits()):
    @contextmanager
    def opened(raw, supplied):
        assert supplied is limits
        yield source
    def read(ole, name, supplied, **kwargs):
        if name not in ole:
            raise InvalidDocumentError('missing stream')
        if len(ole[name]) > supplied.max_stream_bytes:
            raise LimitExceededError('stream limit')
        return ole[name]
    monkeypatch.setattr(doc, 'open_ole', opened)
    monkeypatch.setattr(doc, 'read_stream', read)
    return doc.parse_doc_bytes(b'synthetic', limits)


def effective(monkeypatch, group):
    source = streams([['a']], [group])
    parse(monkeypatch, source)
    reader = doc._Doc(source, Limits())
    return reader.properties(2)


def test_external_grid_and_merge_end_to_end(monkeypatch):
    a = insert(0, 2, 100) + resize(0, 1, 200) + vm(0, 3)
    b = insert(0, 3, 100) + merge(0, 2) + vm(0, 1)
    data, offsets = external(a, b)
    out = parse(monkeypatch, streams([['wide', 'r'], ['', '', 's']],
                [ref(i) + definition([0, 999]) for i in offsets], data))
    rows = out.blocks[0].rows
    assert [[c.text for c in row] for row in rows] == [['wide', '', 'r'], ['', '', 's']]
    assert (rows[0][0].col_span, rows[0][0].row_span) == (2, 2)
    assert rows[0][1].covered and rows[1][0].covered and rows[1][1].covered
    assert not out.warnings


@pytest.mark.parametrize('at,expected', [(0, [-40, 10, 110, 310]),
                                       (1, [-40, 60, 110, 310]),
                                       (2, [-40, 60, 260, 310])])
def test_insert_at_start_middle_end(monkeypatch, at, expected):
    props = effective(monkeypatch, definition([-40, 60, 260], [96, 0]) + insert(at, 1, 50))
    assert props.edges == expected
    assert props.flags == [96, 0][:at] + [0] + [96, 0][at:]


def test_sequential_mutation_preserves_cell_merge_flags(monkeypatch):
    group = (definition([0, 100, 200, 300]) + merge(1, 3) + vm(1, 3)
             + insert(0, 1, 50) + delete(1, 2) + resize(1, 3, 75))
    props = effective(monkeypatch, group)
    assert props.edges == [0, 50, 125, 200]
    assert props.flags == [0, 98, 1]
    out = parse(monkeypatch, streams([['x', 'anchor', '']], [group]))
    assert out.blocks[0].rows[0][1].col_span == 2
    assert out.blocks[0].rows[0][2].covered


def test_redefinition_overrides_prior_merges(monkeypatch):
    props = effective(monkeypatch, insert(0, 2, 100) + merge(0, 2) + vm(0, 3)
                      + definition([10, 50, 90]))
    assert props.flags == [0, 0]
    assert props.edges == [10, 50, 90]


def test_split_and_vertical_clear_are_sequential(monkeypatch):
    props = effective(monkeypatch, definition([0, 10, 20], [98, 1])
                      + p(0x5625, b'\0\2') + vm(0, 0))
    assert props.flags == [0, 0]


@pytest.mark.parametrize('ops', [
    p(0x9601, struct.pack('<h', 100)) + p(0x9602, struct.pack('<h', 20)) + insert(0, 1, 100),
    insert(0, 1, 100) + p(0x9602, struct.pack('<h', 20)) + p(0x9601, struct.pack('<h', 100)),
    p(0x9601, struct.pack('<h', 100)) + insert(0, 1, 100) + p(0x9602, struct.pack('<h', 20)),
])
def test_origin_and_gap_before_or_after_insert(monkeypatch, ops):
    assert effective(monkeypatch, ops).edges == [80, 180]


def test_definition_coordinates_not_offset_twice(monkeypatch):
    assert effective(monkeypatch, p(0x9601, struct.pack('<h', 100))
                     + definition([80, 180])).edges == [80, 180]


def test_origin_prevents_false_vertical_match(monkeypatch):
    groups = [insert(0, 1, 100) + vm(0, 3),
              p(0x9601, struct.pack('<h', 20)) + insert(0, 1, 100) + vm(0, 1)]
    out = parse(monkeypatch, streams([['a'], ['']], groups))
    assert out.blocks[0].rows[0][0].row_span == 1
    assert not out.blocks[0].rows[1][0].covered
    assert any('Vertical merge' in w for w in out.warnings)


def test_mixed_chain_skips_each_tail(monkeypatch):
    # All three targets are >=10 bytes, first HugePapx is first in its array.
    end = insert(0, 2, 80) + resize(0, 1, 120)
    # Each intermediate target is 14 bytes plus its 2-byte length.
    data, _ = external(ref(16, 0x6646) + NOOP + b'\xff\xff',
                       ref(32) + NOOP + b'\xff\xff', end)
    out = parse(monkeypatch, streams([['a', 'b']], [ref(0) + b'\xff\xff'], data))
    assert [c.text for c in out.blocks[0].rows[0]] == ['a', 'b']
    assert not out.warnings


def test_nonfirst_huge_papx_ignored_without_reading_data(monkeypatch):
    # ROW precedes HugePapx, so even this invalid pointer must be ignored.
    out = parse(monkeypatch, streams([['a']], [ref(0xffffffff, 0x6646) + definition([0, 10])]))
    assert not out.warnings


def test_unsupported_external_geometry_retains_inline_fallback(monkeypatch):
    data, _ = external(p(0x563A, b'\1\0') + NOOP)
    out = parse(monkeypatch, streams([['a', '']],
                [ref(0) + definition([0, 100, 200], [2, 1])], data))
    assert out.blocks[0].rows[0][0].col_span == 2
    assert any('inline fallback' in w for w in out.warnings)
    assert any('Table styles' in w for w in out.warnings)


def test_external_style_warning_kept_with_supported_geometry(monkeypatch):
    data, _ = external(p(0x563A, b'\1\0') + insert(0, 1, 50))
    out = parse(monkeypatch, streams([['a']], [ref(0) + definition([0, 999])], data))
    assert any('Table styles' in w for w in out.warnings)
    assert not any('fallback' in w for w in out.warnings)


@pytest.mark.parametrize('op', [0x6646, 0x646B])
@pytest.mark.parametrize('size', [0, 9, 0x3fa3, 0x8000, 0xffff])
def test_invalid_external_length(monkeypatch, op, size):
    # PTableProps forwards to an array whose first element is the tested ref.
    data = struct.pack('<H', 12) + ref(14, op) + NOOP + struct.pack('<H', size)
    with pytest.raises(InvalidDocumentError, match='PrcData length'):
        parse(monkeypatch, streams([['a']], [ref(0)], data))


@pytest.mark.parametrize('data,offset', [(b'', 0), (b'\0', 0), (b'\x0a\0abc', 0), (b'', 0xffffffff)])
def test_external_bounds(monkeypatch, data, offset):
    with pytest.raises(InvalidDocumentError):
        parse(monkeypatch, streams([['a']], [ref(offset)], data))


def test_missing_data(monkeypatch):
    source = streams([['a']], [ref(0)])
    del source['Data']
    with pytest.raises(InvalidDocumentError, match='missing stream'):
        parse(monkeypatch, source)


@pytest.mark.parametrize('second', [0x646B, 0x6646])
def test_mixed_and_same_opcode_cycles(monkeypatch, second):
    data, _ = external(ref(14) + NOOP, ref(0, second) + NOOP)
    with pytest.raises(InvalidDocumentError, match='cyclic'):
        parse(monkeypatch, streams([['a']], [ref(0)], data))


def test_depth_limit_and_exact_boundary(monkeypatch):
    data, _ = external(ref(14) + NOOP, insert(0, 1, 100) + NOOP)
    source = streams([['a']], [ref(0)], data)
    with pytest.raises(LimitExceededError, match='depth'):
        parse(monkeypatch, source, Limits(max_depth=1))
    assert not parse(monkeypatch, source, Limits(max_depth=2)).warnings


def test_external_records_share_document_budget(monkeypatch):
    data, _ = external(NOOP * 200 + insert(0, 1, 100))
    with pytest.raises(LimitExceededError, match='record'):
        parse(monkeypatch, streams([['a']], [ref(0)], data), Limits(max_records=150))


@pytest.mark.parametrize('group', [
    insert(1, 1, 1), insert(0, 0, 1), insert(0, 64, 1), insert(0, 1, -1),
    insert(0, 1, 31681), insert(0, 2, 16000),
    insert(0, 1, 100) + delete(0, 1),
    insert(0, 1, 100) + delete(1, 1),
    insert(0, 2, 100) + delete(1, 3),
    insert(0, 2, 100) + resize(1, 0, 10),
    insert(0, 2, 100) + resize(0, 3, 10),
    insert(0, 1, 100) + resize(0, 1, -1),
    insert(0, 1, 100) + resize(0, 1, 31681),
    p(0x9602, struct.pack('<h', -1)),
])
def test_invalid_geometry_operands(monkeypatch, group):
    with pytest.raises(InvalidDocumentError):
        parse(monkeypatch, streams([['a']], [group]))


def test_zero_width_and_empty_ranges_are_legal(monkeypatch):
    props = effective(monkeypatch, insert(0, 2, 0) + delete(0, 0)
                      + resize(1, 1, 100) + merge(0, 0))
    assert props.edges == [0, 0, 0]
    assert props.flags == [0, 0]


def test_maximum_cell_count_and_insertion_width(monkeypatch):
    assert len(effective(monkeypatch, insert(0, 63, 0)).flags) == 63
    assert effective(monkeypatch, insert(0, 1, 31680)).edges == [0, 31680]


def test_prc_override_is_applied_after_external_properties(monkeypatch):
    data, _ = external(insert(0, 2, 100) + merge(0, 2))
    source = streams([['a', '']], [ref(0)], data, p(0x5625, b'\0\2'))
    out = parse(monkeypatch, source)
    assert out.blocks[0].rows[0][0].col_span == 1
    assert not out.blocks[0].rows[0][1].covered


def test_fallback_continuation_does_not_make_huge_papx_first(monkeypatch):
    data, _ = external(NOOP * 2)
    out = parse(monkeypatch, streams([['a']],
                [ref(0) + ref(0xffffffff, 0x6646) + definition([0, 10])], data))
    assert out.blocks[0].rows[0][0].text == 'a'


def test_reused_declined_target_is_not_a_cycle(monkeypatch):
    data, _ = external(NOOP * 2)
    out = parse(monkeypatch, streams([['a']],
                [ref(0) + ref(0) + definition([0, 10])], data))
    assert out.blocks[0].rows[0][0].text == 'a'


def test_nested_fallback_is_used_before_outer_fallback(monkeypatch):
    inner = ref(0) + definition([0, 50, 100], [2, 1])
    data, offsets = external(NOOP * 2, inner)
    out = parse(monkeypatch, streams([['a', '']],
                [ref(offsets[1]) + definition([0, 100])], data))
    assert out.blocks[0].rows[0][0].col_span == 2
    assert not any('disagree' in w for w in out.warnings)


def test_external_requires_whole_prls_not_papx_padding(monkeypatch):
    group = insert(0, 1, 10) + NOOP + b'\0'
    with pytest.raises(InvalidDocumentError):
        parse(monkeypatch, streams([['a']], [ref(0)], struct.pack('<H', len(group)) + group))


def test_deletion_and_width_use_remaining_widths(monkeypatch):
    group = definition([-20, 30, 130, 330, 630], [0, 96, 2, 1])
    props = effective(monkeypatch, group + delete(0, 2) + resize(1, 2, 10))
    assert props.edges == [-20, 180, 190]
    assert props.flags == [2, 1]


def test_insertion_in_merged_range_does_not_copy_merge_to_new_cell(monkeypatch):
    out = parse(monkeypatch, streams([['a', 'new', '']],
                [definition([0, 100, 200], [2, 1]) + insert(1, 1, 100)]))
    row = out.blocks[0].rows[0]
    assert row[0].col_span == 1
    assert not any(c.covered for c in row)
    assert any('Orphan horizontal' in w for w in out.warnings)


def test_delete_merge_anchor_does_not_invent_replacement_anchor(monkeypatch):
    out = parse(monkeypatch, streams([['', 'normal']],
                [definition([0, 100, 200, 300], [2, 1, 0]) + delete(0, 1)]))
    assert not any(c.covered for c in out.blocks[0].rows[0])
    assert any('Orphan horizontal' in w for w in out.warnings)


def test_vertical_merge_index_moves_with_insert_delete(monkeypatch):
    first = insert(0, 2, 100) + vm(1, 3) + insert(0, 1, 100) + delete(1, 2)
    second = insert(0, 2, 100) + vm(1, 1)
    out = parse(monkeypatch, streams([['a', 'anchor'], ['b', '']], [first, second]))
    assert out.blocks[0].rows[0][1].row_span == 2
    assert out.blocks[0].rows[1][1].covered


@pytest.mark.parametrize('op', [0x7621, 0x5622, 0x7623, 0xD62B])
def test_truncated_operands_are_structured_errors(monkeypatch, op):
    group = NOOP * 2 + p(op, b'\x02')
    with pytest.raises(InvalidDocumentError):
        parse(monkeypatch, streams([['a']], [ref(0)], struct.pack('<H', len(group)) + group))
