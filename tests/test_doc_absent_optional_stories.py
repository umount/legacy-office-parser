"""Absent optional DOC stories with zero-entry service tables."""
import struct

import pytest

from legacy_office_parser import InvalidDocumentError, LimitExceededError, Limits
from legacy_office_parser._doc_notes import decode_note_ranges
from legacy_office_parser._doc_comments import decode_comments
from test_doc import fixture, parse
from test_doc_auxiliary_stories import put


def decode(kind, refs, texts, *, limits=None, record=None, warn=None, extra=None):
    opts = {'record': record, 'warn': warn or (lambda message: None)}
    if kind == 'note':
        return decode_note_ranges(refs, texts, 2, b'', limits or Limits(), **opts)
    return decode_comments({4: refs, 5: texts, **(extra or {})}, b'B\0\r\0', b'',
                           limits or Limits(), **opts)


@pytest.mark.parametrize('kind', ['note', 'comment'])
@pytest.mark.parametrize('refs', [b'', bytes(4), b'\xff' * 4])
@pytest.mark.parametrize('terminal', [0, 1, 0x7fffffff, 0xffffffff])
def test_zero_entry_tables_have_no_source_relationships(kind, refs, terminal):
    warnings, charges = [], []
    assert decode(kind, refs, struct.pack('<II', 0, terminal),
                  warn=warnings.append, record=charges.append) == []
    assert sum(charges) == 2 + bool(refs)
    assert [w.code for w in warnings] == [f'doc_empty_{kind}_plc_ignored']


@pytest.mark.parametrize('kind', ['note', 'comment'])
@pytest.mark.parametrize('texts', [b'x', bytes(4), bytes(9), bytes(12), struct.pack('<II', 1, 0)])
def test_invalid_or_claimed_nonempty_body_is_not_absence(kind, texts):
    with pytest.raises(InvalidDocumentError):
        decode(kind, b'', texts)


@pytest.mark.parametrize('kind', ['note', 'comment'])
def test_empty_tables_keep_limits_before_recovery(kind):
    for limits in (Limits(max_records=2), Limits(max_stream_bytes=7)):
        with pytest.raises(LimitExceededError):
            decode(kind, bytes(4), bytes(8), limits=limits)
    def exhausted(count):
        raise LimitExceededError('aggregate exhausted')
    with pytest.raises(LimitExceededError, match='aggregate exhausted'):
        decode(kind, bytes(4), bytes(8), record=exhausted)


def test_empty_comments_do_not_hide_broken_author_metadata():
    with pytest.raises(InvalidDocumentError, match='author length'):
        decode('comment', bytes(4), bytes(8), extra={36: b'x'})


@pytest.mark.parametrize('pairs,code', [((2, 3), 'note'), ((46, 47), 'note'), ((4, 5), 'comment')])
def test_main_content_survives_absent_optional_story(monkeypatch, pairs, code):
    streams = fixture([('Main text\r', True)], props=[b''])
    put(streams, pairs[0], bytes(4))
    put(streams, pairs[1], bytes(8))
    doc = parse(monkeypatch, streams)
    assert doc.text == 'Main text'
    assert doc.footnotes == doc.endnotes == doc.comment_text == ''
    assert not doc.notes and not doc.comments
    assert [d.code for d in doc.diagnostics] == [f'doc_empty_{code}_plc_ignored']
