"""Original compressed DOC streams: transport bytes differ from decoded CPs."""
import struct

import pytest

from legacy_office_parser import LimitExceededError, Limits
from test_doc import IN, ROW, definition, fixture, parse, u32
from test_doc_comments import SPECIAL, authors, bookmarks, reference
from test_doc_fidelity import add_chpx, append_table_part
from test_doc_styles import style, stylesheet


def compressed_comment(main_size, body_size):
    """Relocate a small synthetic fixture's single compressed piece after its FKPs."""
    main = 'A' * (main_size - 3) + '\x05\7\7'
    body = '\x05' + 'B' * (body_size - 3) + '\r\r'
    raw = (main + body).encode('ascii')
    props = [IN, ROW + definition([0]), b'', b'']
    streams = fixture([('\x05\7\7\x05\r\r', True)], props=props)
    word = bytearray(streams['WordDocument'])
    table = bytearray(streams['1Table'])
    offset = len(word)
    word.extend(raw)
    word.extend(b'\0' * (-len(word) % 512))
    word[64:68] = u32(len(word))
    word[76:80] = u32(len(main))
    word[92:96] = u32(len(body))
    # Single-piece CLX: CP terminator and compressed FC, then PAPX FC coverage.
    table[9:13] = u32(len(raw))
    table[15:19] = u32((offset * 2) | 0x40000000)
    marks = [offset + i for i, unit in enumerate(raw) if unit in (7, 13)]
    fcs = marks + [offset + len(raw)]
    bins = struct.unpack_from('<I', word, 154 + 13 * 8)[0]
    table[bins:bins + 4 * len(fcs)] = b''.join(map(u32, fcs))
    for i in range(len(props)):
        page = 4096 + i * 512
        word[page:page + 8] = u32(fcs[i]) + u32(fcs[i + 1])
    streams['WordDocument'], streams['1Table'] = bytes(word), bytes(table)
    stylesheet(streams, [style(0)])
    parts = {4: reference([len(main) - 3], tags=[41]),
             5: b''.join(map(u32, [0, len(body) - 1, 0xffffffff])),
             36: authors('Synthetic Author')}
    parts.update(bookmarks(len(main), starts=(0,), ends=(len(main),)))
    for index, part in parts.items():
        append_table_part(streams, index, part)
    add_chpx(streams, [offset, offset + len(raw)], [SPECIAL])
    return streams, main, body


@pytest.mark.parametrize('main_size,body_size', [(7000, 7000), (14000, 7)])
def test_decoded_stories_do_not_consume_transport_byte_limit(monkeypatch, main_size, body_size):
    streams, main, body = compressed_comment(main_size, body_size)
    transport_limit = max(map(len, streams.values()))
    assert len(main + body) * 2 > transport_limit
    if body_size == 7:
        assert len(main) * 2 > transport_limit
    else:
        assert max(len(main), len(body)) * 2 < transport_limit
    result = parse(monkeypatch, streams, Limits(max_stream_bytes=transport_limit))
    comment, = result.comments
    assert (comment.selection_start, comment.selection_end) == (0, len(main))
    assert comment.source_cp == len(main) - 3
    assert comment.anchor_path is not None
    assert result.comment_text == 'B' * (body_size - 3)
    assert not any('selection validity' in warning for warning in result.warnings)


def test_compressed_story_still_obeys_source_cp_limit(monkeypatch):
    streams, main, body = compressed_comment(14000, 7)
    with pytest.raises(LimitExceededError):
        parse(monkeypatch, streams, Limits(max_text_chars=len(main + body) - 1))


def test_compressed_transport_still_obeys_stream_byte_limit(monkeypatch):
    streams, _, _ = compressed_comment(14000, 7)
    with pytest.raises(LimitExceededError, match='stream size'):
        parse(monkeypatch, streams, Limits(max_stream_bytes=len(streams['WordDocument']) - 1))
