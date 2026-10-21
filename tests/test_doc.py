"""Synthetic DOC streams only: no personal corpus data or external converters."""
from contextlib import contextmanager
import struct

import pytest

from legacy_office_parser import doc
from legacy_office_parser.errors import (EncryptedDocumentError, InvalidDocumentError,
                                        LimitExceededError, UnsupportedFormatError)
from legacy_office_parser.limits import Limits
from legacy_office_parser.models import Paragraph, Table


def u16(v):
    return struct.pack('<H', v)


def u32(v):
    return struct.pack('<I', v)


def sprm(op, arg):
    return u16(op) + (bytes([arg]) if isinstance(arg, int) else arg)


IN = sprm(0x2416, 1)
ROW = IN + sprm(0x2417, 1)


def definition(flags, edges=None):
    edges = edges or list(range(0, 100 * (len(flags) + 1), 100))
    body = bytes([len(flags)]) + struct.pack('<' + 'h' * len(edges), *edges)
    body += b''.join(u16(flag) + b'\0' * 18 for flag in flags)
    return sprm(0xD608, u16(len(body) + 1) + body)


def fixture(pieces, *, counts=None, props=None, prcs=(), prms=None, one_table=True):
    """Real FIB/CLX/PAPX layouts, wrapped in monkeypatched OLE for unit tests."""
    # pieces are (text OR raw UTF16 bytes, compressed).
    word = bytearray(4096 + 512 * max(1, len(props or [])))
    word[:2] = u16(0xA5EC)
    word[2:4] = u16(0xC1)
    word[10:12] = u16(0x200 if one_table else 0)
    word[32:34] = u16(14)
    word[62:64] = u16(22)
    word[152:154] = u16(93)
    cps, pcds, cp_fc, unit_text = [0], [], [], b''
    offset = 1024
    for i, (text, compressed) in enumerate(pieces):
        raw = text if isinstance(text, bytes) else text.encode('latin1' if compressed else 'utf-16le')
        size = len(raw) if compressed else len(raw) // 2
        word[offset:offset + len(raw)] = raw
        pcds.append(b'\0\0' + u32((offset * 2 | 0x40000000) if compressed else offset) + u16((prms or [0] * len(pieces))[i]))
        cps.append(cps[-1] + size)
        cp_fc.extend(offset + j * (1 if compressed else 2) for j in range(size))
        unit_text += raw.decode('latin1').encode('utf-16le') if compressed else raw
        offset += len(raw) + 16
    assert offset < 4096
    counts = counts or [cps[-1], 0, 0, 0, 0, 0, 0]
    for n, i in zip(counts, (3, 4, 5, 7, 8, 9, 10)):
        word[64 + i * 4:68 + i * 4] = u32(n)
    plc = b''.join(map(u32, cps)) + b''.join(pcds)
    clx = b''.join(b'\1' + u16(len(p)) + p for p in prcs) + b'\2' + u32(len(plc)) + plc
    table = bytearray(clx)
    word[154 + 33 * 8:162 + 33 * 8] = u32(0) + u32(len(clx))
    if props is not None:
        ends = [i for i in range(cps[-1]) if unit_text[i * 2:i * 2 + 2] in (b'\r\0', b'\7\0')]
        assert len(ends) == len(props)
        fcs = [cp_fc[cp] for cp in ends]
        fcs.append(fcs[-1] + 2)
        for i, group in enumerate(props):
            page = memoryview(word)[4096 + i * 512:4096 + (i + 1) * 512]
            page[:8] = u32(fcs[i]) + u32(fcs[i + 1])
            page[511] = 1
            if group is not None:
                page[8] = 32
                payload = u16(0) + group
                if len(payload) % 2:
                    enc = bytes([(len(payload) + 1) // 2]) + payload
                else:
                    enc = bytes([0, len(payload) // 2]) + payload
                page[64:64 + len(enc)] = enc
        bins = b''.join(map(u32, fcs)) + b''.join(u32(8 + i) for i in range(len(props)))
        word[154 + 13 * 8:162 + 13 * 8] = u32(len(table)) + u32(len(bins))
        table.extend(bins)
    word[64:68] = u32(len(word))
    return {'WordDocument': bytes(word), '1Table' if one_table else '0Table': bytes(table)}


def parse(monkeypatch, streams, limits=Limits()):
    @contextmanager
    def opened(data, supplied):
        assert supplied is limits
        yield streams

    def read(ole, name, supplied, *, required=True):
        if name not in ole:
            if required:
                raise InvalidDocumentError('missing required stream')
            return b''
        if len(ole[name]) > supplied.max_stream_bytes:
            raise LimitExceededError('stream size limit exceeded')
        return ole[name]

    monkeypatch.setattr(doc, 'open_ole', opened)
    monkeypatch.setattr(doc, 'read_stream', read)
    return doc.parse_doc_bytes(b'fixture', limits)


def mutate(streams, stream, offset, value):
    changed = bytearray(streams[stream])
    changed[offset:offset + len(value)] = value
    streams[stream] = bytes(changed)
    return streams


def test_mixed_piece_encodings_and_story_boundaries(monkeypatch):
    body, foot, head, comment, end, box, hbox = 'ASCII Ω😀\r', 'note\r', 'header\r', 'private\r', 'end\r', 'box\r', 'hbox\r'
    parts = [body, foot, head, comment, end, box, hbox]
    lengths = [len(s.encode('utf-16le')) // 2 for s in parts]
    streams = fixture([('ASCII ', True), ('Ω😀\r' + ''.join(parts[1:]), False)], counts=lengths)
    out = parse(monkeypatch, streams)
    assert out.blocks == [Paragraph(body[:-1])]
    assert out.footnotes == 'note'
    assert out.headers_footers == 'header'
    assert out.endnotes == 'end'
    assert out.textboxes == 'box\nhbox'
    assert comment.strip() not in out.text


def test_compressed_is_spec_unicode_mapping_not_cp1252(monkeypatch):
    out = parse(monkeypatch, fixture([(b'\x80\x82\x8e\x9e\r', True)]))
    assert out.blocks[0].text == '\x80\u201a\x8e\x9e'


def test_surrogate_pair_can_cross_pieces(monkeypatch):
    out = parse(monkeypatch, fixture([(b'\x3d\xd8', False), (b'\x00\xde\r\0', False)]))
    assert out.blocks == [Paragraph('😀')]


def test_both_table_streams(monkeypatch):
    assert parse(monkeypatch, fixture([('hello\r', True)], one_table=False)).blocks == [Paragraph('hello')]


def test_tables_preserve_body_order_and_multi_paragraph_cells(monkeypatch):
    streams = fixture([('before\rfirst\rsecond\7right\7\7after\r', True)],
                      props=[b'', IN, IN, IN, ROW + definition([0, 0]), b''])
    out = parse(monkeypatch, streams)
    assert isinstance(out.blocks[0], Paragraph)
    assert out.blocks[0].text == 'before'
    table = out.blocks[1]
    assert isinstance(table, Table)
    assert [[c.text for c in row] for row in table.rows] == [['first\nsecond', 'right']]
    assert out.blocks[2] == Paragraph('after')


def test_control_marks_alone_do_not_invent_tables(monkeypatch):
    out = parse(monkeypatch, fixture([('a\7b\7', True)], props=[b'', b'']))
    assert out.blocks == [Paragraph('a'), Paragraph('b')]
    assert any('without table membership' in w for w in out.warnings)


def test_horizontal_and_vertical_merges(monkeypatch):
    streams = fixture([('a\7\7c\7\7\7\7d\7\7', True)],
                      props=[IN, IN, IN, ROW + definition([2 | 96, 1, 0]),
                             IN, IN, IN, ROW + definition([2 | 32, 1, 0])])
    table = parse(monkeypatch, streams).blocks[0]
    assert len(table.rows) == 2
    assert table.rows[0][0].col_span == 2
    assert table.rows[0][0].row_span == 2
    assert table.rows[0][1].covered
    assert table.rows[1][0].covered
    assert table.rows[1][1].covered
    assert table.rows[1][2].text == 'd'


def test_explicit_merge_sprms(monkeypatch):
    group = ROW + definition([0, 0]) + sprm(0x5624, b'\0\2') + sprm(0xD62B, b'\2\0\3')
    out = parse(monkeypatch, fixture([('a\7\7\7', True)], props=[IN, IN, group]))
    assert out.blocks[0].rows[0][0].col_span == 2


def test_nested_tables_keep_text_inside_outer_cell(monkeypatch):
    nested = IN + sprm(0x6649, u32(2)) + sprm(0x244B, 1)
    streams = fixture([('outer\rinner\rrest\7\7', True)], props=[IN, nested, IN, ROW + definition([0])])
    out = parse(monkeypatch, streams)
    assert out.blocks[0].rows[0][0].text == 'outer\ninner\nrest'
    assert any('without a row terminator' in w for w in out.warnings)
    assert out.blocks[0].rows[0][0].blocks[1].rows[0][0].text == 'inner'


def test_prc_piece_override_and_paragraph_final_piece(monkeypatch):
    streams = fixture([('cell', True), ('\7', False), ('\7', True)], props=[b'', ROW + definition([0])],
                      prcs=[IN], prms=[0, 1, 0])
    out = parse(monkeypatch, streams)
    assert out.blocks[0].rows[0][0].text == 'cell'


def test_huge_papx(monkeypatch):
    group = ROW + definition([0])
    streams = fixture([('cell\7\7', True)], props=[IN, sprm(0x6646, u32(0))])
    streams['Data'] = u16(len(group)) + group
    assert parse(monkeypatch, streams).blocks[0].rows[0][0].text == 'cell'


def test_huge_papx_cycle(monkeypatch):
    group = sprm(0x6646, u32(0)) + sprm(0x4600, u16(0))
    streams = fixture([('a\r', True)], props=[group])
    streams['Data'] = u16(len(group)) + group
    with pytest.raises(InvalidDocumentError, match='cyclic'):
        parse(monkeypatch, streams)


def test_field_results_nested_and_across_paragraphs(monkeypatch):
    out = parse(monkeypatch, fixture([('pre\x13CODE\rMORE\x14result \x13SUB\x14sub\x15\x15 post\r', True)]))
    assert out.blocks == [Paragraph('pre'), Paragraph('result sub post')]
    assert 'CODE' not in out.text


def test_missing_row_terminator_warns_and_retains(monkeypatch):
    out = parse(monkeypatch, fixture([('cell\7after\r', True)], props=[IN, b'']))
    assert out.blocks[0].rows[0][0].text == 'cell'
    assert out.blocks[1].text == 'after'
    assert any('without a row terminator' in w for w in out.warnings)


def test_unpaired_surrogate_warns(monkeypatch):
    out = parse(monkeypatch, fixture([(b'\x00\xd8\r\0', False)]))
    assert out.blocks[0].text == '\ufffd'
    assert any('Invalid UTF-16' in w for w in out.warnings)


@pytest.mark.parametrize('offset,value,error', [
    (0, u16(0xA5DC), UnsupportedFormatError),
    (0, u16(0), InvalidDocumentError),
    (2, u16(0x1234), UnsupportedFormatError),
    (10, u16(0x100), EncryptedDocumentError),
    (10, u16(0x8100), EncryptedDocumentError),
    (32, u16(13), InvalidDocumentError),
    (62, u16(21), InvalidDocumentError),
    (64, u32(0), InvalidDocumentError),
    (76, u32(0xFFFFFFFF), InvalidDocumentError),
    (152, u16(3), InvalidDocumentError),
    (154 + 33 * 8, u32(9999999), InvalidDocumentError),
    (158 + 33 * 8, u32(0), UnsupportedFormatError),
])
def test_bad_fib_structured_errors(monkeypatch, offset, value, error):
    with pytest.raises(error):
        parse(monkeypatch, mutate(fixture([('a\r', True)]), 'WordDocument', offset, value))


@pytest.mark.parametrize('offset,value', [(0, b'\0'), (1, u32(99999)), (5, u32(1)),
                                        (9, u32(0)), (15, u32(0x40000003)), (19, u16(1))])
def test_bad_clx_structured_errors(monkeypatch, offset, value):
    with pytest.raises(InvalidDocumentError):
        parse(monkeypatch, mutate(fixture([('a\r', True)]), '1Table', offset, value))


@pytest.mark.parametrize('limits', [Limits(max_text_chars=1), Limits(max_records=1), Limits(max_stream_bytes=100)])
def test_limits(monkeypatch, limits):
    with pytest.raises(LimitExceededError):
        parse(monkeypatch, fixture([('a\r', True)]), limits)


def test_cell_limit(monkeypatch):
    streams = fixture([('a\7b\7\7', True)], props=[IN, IN, ROW])
    with pytest.raises(LimitExceededError, match='cell'):
        parse(monkeypatch, streams, Limits(max_cells=1))


def test_table_depth_limit(monkeypatch):
    streams = fixture([('a\r', True)], props=[IN + sprm(0x6649, u32(3))])
    with pytest.raises(LimitExceededError, match='depth'):
        parse(monkeypatch, streams, Limits(max_depth=2))


def test_field_depth_limit(monkeypatch):
    with pytest.raises(LimitExceededError, match='field nesting'):
        parse(monkeypatch, fixture([('\x13\x13\x13\r', True)]), Limits(max_depth=2))


@pytest.mark.parametrize('offset,value', [(4096 + 511, b'\xff'), (4096 + 8, b'\x01'),
                                        (4096 + 64, b'\xff'), (4096 + 4, u32(0))])
def test_bad_fkp_structured_errors(monkeypatch, offset, value):
    streams = fixture([('a\r', True)], props=[IN])
    with pytest.raises(InvalidDocumentError):
        parse(monkeypatch, mutate(streams, 'WordDocument', offset, value))


def test_truncated_sprm(monkeypatch):
    with pytest.raises(InvalidDocumentError):
        parse(monkeypatch, fixture([('a\r', True)], props=[u16(0x6649)]))


def test_special_tab_operand_does_not_desync_table_sprms(monkeypatch):
    tabs = sprm(0xC615, b'\xff\1' + b'\0' * 4 + b'\1' + b'\0' * 3)
    out = parse(monkeypatch, fixture([('cell\7\7', True)], props=[tabs + IN, ROW]))
    assert out.blocks[0].rows[0][0].text == 'cell'


def test_explicit_grid_expands_wide_cells(monkeypatch):
    streams = fixture([('wide\7right\7\7a\7b\7c\7\7', True)],
                      props=[IN, IN, ROW + definition([0, 0], [0, 200, 300]),
                             IN, IN, IN, ROW + definition([0, 0, 0], [0, 100, 200, 300])])
    out = parse(monkeypatch, streams)
    row = out.blocks[0].rows[0]
    assert [c.text for c in row] == ['wide', '', 'right']
    assert row[0].col_span == 2
    assert row[1].covered


def test_grid_expansion_enforces_cell_limit_before_allocation(monkeypatch):
    streams = fixture([('wide\7right\7\7a\7b\7c\7\7', True)],
                      props=[IN, IN, ROW + definition([0, 0], [0, 200, 300]),
                             IN, IN, IN, ROW + definition([0, 0, 0], [0, 100, 200, 300])])
    with pytest.raises(LimitExceededError, match='cell'):
        parse(monkeypatch, streams, Limits(max_cells=5))


def test_huge_papx_ignores_remainder_of_original_group(monkeypatch):
    group = IN + sprm(0x6649, u32(1)) + sprm(0x2417, 0)
    streams = fixture([('a\7\7', True)], props=[sprm(0x6646, u32(0)) + sprm(0x2416, 0), ROW])
    streams['Data'] = u16(len(group)) + group
    out = parse(monkeypatch, streams)
    assert out.blocks[0].rows[0][0].text == 'a'


def test_huge_papx_depth_limit(monkeypatch):
    streams = fixture([('a\r', True)], props=[sprm(0x6646, u32(0))])
    padding = sprm(0x4600, u16(0))
    streams['Data'] = (u16(10) + sprm(0x6646, u32(12)) + padding
                       + u16(10) + sprm(0x6646, u32(24)) + padding
                       + u16(10) + IN + padding + sprm(0x2417, 0))
    with pytest.raises(LimitExceededError, match='depth'):
        parse(monkeypatch, streams, Limits(max_depth=2))


def test_logical_piece_order_is_not_physical_stream_order(monkeypatch):
    streams = fixture([('first\r', True), ('other\r', True)])
    table = bytearray(streams['1Table'])
    # CLX header (5) + CP array (12), then PCDs (8 each).
    table[19:23], table[27:31] = table[27:31], table[19:23]
    streams['1Table'] = bytes(table)
    assert parse(monkeypatch, streams).blocks == [Paragraph('other'), Paragraph('first')]


def test_auxiliary_table_structure_and_projection(monkeypatch):
    streams = fixture([('main\rnote\7\7', True)], counts=[5, 6, 0, 0, 0, 0, 0],
                      props=[b'', IN, ROW])
    out = parse(monkeypatch, streams)
    assert out.blocks == [Paragraph('main')]
    assert out.footnotes == 'note'
    assert out.story_blocks['footnotes'][0].rows[0][0].text == 'note'
    assert 'story_blocks' in out.to_dict()


def test_record_budget_is_enforced_during_sprm_iteration(monkeypatch):
    streams = fixture([('a\r', True)], props=[sprm(0x2405, 1) * 20])
    with pytest.raises(LimitExceededError, match='record'):
        parse(monkeypatch, streams, Limits(max_records=105))


def test_bin_page_outside_word_stream(monkeypatch):
    streams = fixture([('a\r', True)], props=[IN])
    table = bytearray(streams['1Table'])
    table[-4:] = u32(0x3FFFFF)
    streams['1Table'] = bytes(table)
    with pytest.raises(InvalidDocumentError):
        parse(monkeypatch, streams)


def test_extra_tc80_entries_are_ignored_per_spec(monkeypatch):
    body = b'\1' + struct.pack('<hh', 0, 100) + b'\0' * 40
    group = ROW + sprm(0xD608, u16(len(body) + 1) + body)
    out = parse(monkeypatch, fixture([('a\7\7', True)], props=[IN, group]))
    assert len(out.blocks[0].rows[0]) == 1


def test_zero_length_stories(monkeypatch):
    out = parse(monkeypatch, fixture([], counts=[0] * 7))
    assert out.blocks == []
    assert out.text == ''


def test_truncation_raises_only_structured_parse_errors(monkeypatch):
    from legacy_office_parser.errors import ParseError
    streams = fixture([('a\r', True)], props=[IN])
    for length in (0, 1, 11, 32, 64, 153, 512, 4097):
        truncated = {**streams, 'WordDocument': streams['WordDocument'][:length]}
        with pytest.raises(ParseError):
            parse(monkeypatch, truncated)


def test_mutated_structures_never_leak_low_level_exceptions(monkeypatch):
    import random
    from legacy_office_parser.errors import ParseError
    rng = random.Random(9703)
    base = fixture([('a\7b\7\7', True)], props=[IN, IN, ROW + definition([0, 0])])
    for _ in range(150):
        streams = dict(base)
        name = rng.choice(['WordDocument', '1Table'])
        data = bytearray(streams[name])
        ranges = [range(154 + 93 * 8), range(4096, len(data))] if name == 'WordDocument' else [range(len(data))]
        offset = rng.choice(rng.choice(ranges))
        data[offset] ^= rng.randint(1, 255)
        streams[name] = bytes(data)
        try:
            parse(monkeypatch, streams, Limits(max_text_chars=1000, max_records=2000))
        except ParseError:
            pass


def test_vertical_merge_matches_edges_across_different_physical_grids(monkeypatch):
    streams = fixture([('a\7\7\7\7\7', True)], props=[
        IN, IN, ROW + definition([98, 1], [0, 100, 200]),
        IN, ROW + definition([32], [0, 200]),
    ])
    table = parse(monkeypatch, streams).blocks[0]
    assert table.rows[0][0].row_span == 2
    assert table.rows[0][0].col_span == 2
    assert all(c.covered for c in table.rows[1])


@pytest.mark.parametrize('flag,expected', [(0x1000, False), (0x4000, True)])
def test_far_east_flag_is_distinct_from_required_ext_char(monkeypatch, flag, expected):
    streams = fixture([('text\r', True)])
    mutate(streams, 'WordDocument', 10, u16(0x200 | flag))
    result = parse(monkeypatch, streams)
    assert any('Far East' in w for w in result.warnings) is expected
