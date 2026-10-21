"""Original annotation records with independent expected ownership and failures."""
import struct

import pytest

from legacy_office_parser._doc_comments import decode_comments
from legacy_office_parser import InvalidDocumentError, LimitExceededError, Limits
from legacy_office_parser.models import Paragraph, Table
from test_doc import IN, ROW, definition, fixture, mutate, parse, sprm, u16, u32
from test_doc_fidelity import add_chpx, append_table_part
from test_doc_styles import style, stylesheet


SPECIAL = sprm(0x0855, 1)


def reference(cps, owners=None, tags=None, initials=None):
    owners = owners if owners is not None else [0] * len(cps)
    tags = tags if tags is not None else [0xffffffff] * len(cps)
    initials = initials if initials is not None else ['AF'] * len(cps)
    records = []
    for owner, tag, initial in zip(owners, tags, initials):
        raw = initial.encode('utf-16le')
        records.append(u16(len(raw) // 2) + raw.ljust(18, b'\0') + u16(owner)
                       + b'\0' * 4 + u32(tag))
    return b''.join(map(u32, [*cps, 0xffffffff])) + b''.join(records)


def authors(*names):
    return b''.join(u16(len(n.encode('utf-16le')) // 2) + n.encode('utf-16le') for n in names)


def bookmarks(main_count, starts=(0,), ends=(1,), tags=(41,), indexes=None):
    indexes = list(range(len(starts))) if indexes is None else indexes
    return {
        37: u16(0xffff) + u16(len(tags)) + u16(10)
        + b''.join(u16(0) + u16(0x100) + u32(tag) + u32(0xffffffff) for tag in tags),
        42: b''.join(map(u32, [*starts, main_count + 1]))
        + b''.join(u16(index) + u16(0) for index in indexes),
        43: b''.join(map(u32, [*ends, main_count + 1])),
    }


def base_parts():
    return {4: reference([0, 2], owners=[0, 1]),
            5: b''.join(map(u32, [0, 3, 6, 0xffffffff])),
            36: authors('Ada', 'Ben')}


def decoded(parts=None, main='\x05X\x05\r', story='\x05a\r\x05b\r\r', **kwargs):
    return decode_comments(base_parts() if parts is None else parts,
                           main.encode('utf-16le'), story.encode('utf-16le'),
                           kwargs.pop('limits', Limits()), **kwargs)


def build(main='\x05\r', bodies=('\x05Body\r',), *, cps=None, props=None, tags=None):
    # All source positions are UTF-16 units, including the astral variants.
    main_raw = main.encode('utf-16le')
    body = ''.join(bodies) + '\r'
    raw = main_raw + body.encode('utf-16le')
    if props is None:
        props = [b''] * sum(u in (7, 13) for u in struct.unpack('<' + 'H' * (len(raw) // 2), raw))
    data = fixture([(raw, False)], counts=[len(main_raw) // 2, 0, 0, len(body.encode('utf-16le')) // 2, 0, 0, 0], props=props)
    stylesheet(data, [style(0)])
    if cps is None:
        cps = [i for i, u in enumerate(struct.unpack('<' + 'H' * (len(main_raw) // 2), main_raw)) if u == 5]
    ends = [0]
    for text in bodies:
        ends.append(ends[-1] + len(text.encode('utf-16le')) // 2)
    for index, part in {4: reference(cps, tags=tags),
                        5: b''.join(map(u32, [*ends, 0xffffffff])),
                        36: authors('Ada')}.items():
        append_table_part(data, index, part)
    add_chpx(data, [1024, 1024 + len(raw)], [SPECIAL])
    return data


def test_ordinal_pairing_ignores_sentinels_and_does_not_deduplicate():
    result = decoded(story='\x05a\r\x05a\r\r')
    assert [(s.ordinal, s.source_cp, s.body_start, s.body_end, s.author, s.initials)
            for s in result] == [(1, 0, 0, 3, 'Ada', 'AF'), (2, 2, 3, 6, 'Ben', 'AF')]
    assert [(s.selection_start, s.selection_end) for s in result] == [(0, 0), (2, 2)]


def test_tag_join_and_nonidentity_limit_indexes():
    parts = base_parts()
    parts[4] = reference([0, 2], tags=[70, 41])
    parts.update(bookmarks(4, starts=(0, 1), ends=(2, 3), tags=(41, 70), indexes=(1, 0)))
    assert [(s.selection_start, s.selection_end) for s in decoded(parts)] == [(1, 2), (0, 3)]


def test_overlapping_bookmarks_allow_duplicate_endpoints():
    parts = base_parts()
    parts[4] = reference([0, 2], tags=[41, 70])
    parts.update(bookmarks(4, starts=(0, 0), ends=(3, 3), tags=(41, 70)))
    assert [(s.selection_start, s.selection_end) for s in decoded(parts)] == [(0, 3)] * 2


@pytest.mark.parametrize('missing', [4, 5])
def test_missing_ownership_omits_story(missing):
    parts = base_parts()
    del parts[missing]
    with pytest.warns(UserWarning, match='ownership PLC is absent'):
        assert decoded(parts) == []


@pytest.mark.parametrize('missing', [37, 42, 43])
def test_missing_range_metadata_keeps_proven_body(missing):
    parts = base_parts()
    parts[4] = reference([0, 2], tags=[41, 41])
    parts.update(bookmarks(4))
    del parts[missing]
    with pytest.warns(UserWarning, match='selection bookmark is unresolved'):
        result = decoded(parts)
    assert [s.author for s in result] == ['Ada', 'Ada']
    assert all(s.selection_start is None and s.selection_end is None for s in result)


def test_missing_authors_does_not_invent_name_from_initials():
    parts = base_parts()
    del parts[36]
    with pytest.warns(UserWarning, match='authors are absent'):
        result = decoded(parts)
    assert result[0].author is None and result[0].initials == 'AF'


@pytest.mark.parametrize('key,value', [
    (4, b'x'), (4, reference([0, 0])), (4, reference([0, 4])),
    (4, reference([0, 1])), (4, reference([0, 2], owners=[0, 2])),
    (4, reference([0])), (5, b'x'), (5, b''.join(map(u32, [0, 0, 6, 99]))),
    (5, b''.join(map(u32, [0, 3, 5, 99]))),
    (36, b'\x01'), (36, u16(56) + b'A\0' * 56), (36, authors('Ada', 'Ada')),
    (36, u16(1) + b'\0\xd8'),
    (37, b'x'), (37, u16(0) + u16(0) + u16(10)),
    (42, b'x'), (43, b'x'), (112, b'x'), (112, b'\0' * 18),
])
def test_present_malformed_records_rejected(key, value):
    parts = base_parts()
    parts[key] = value
    with pytest.raises(InvalidDocumentError):
        decoded(parts)


@pytest.mark.parametrize('story', ['xa\r\x05b\r\r', '\x05ax\x05b\r\r'])
def test_body_marker_and_terminator_required(story):
    with pytest.raises(InvalidDocumentError, match=r'initial U\+0005 and final CR'):
        decoded(story=story)


@pytest.mark.parametrize('change', ['duplicate_tag', 'fcol', 'duplicate_ibkl', 'bad_ibkl',
                                    'reverse', 'out_of_bounds', 'count', 'bad_class', 'string'])
def test_malformed_bookmarks(change):
    parts = base_parts()
    parts.update(bookmarks(4, starts=(0, 1), ends=(2, 3), tags=(41, 70)))
    if change == 'duplicate_tag':
        parts[37] = parts[37][:22] + u32(41) + parts[37][26:]
    elif change in ('fcol', 'duplicate_ibkl', 'bad_ibkl'):
        raw = bytearray(parts[42])
        raw[18:20] = u16(0x8000) if change == 'fcol' else raw[18:20]
        raw[16:18] = u16(0 if change == 'duplicate_ibkl' else 2) if change != 'fcol' else raw[16:18]
        parts[42] = raw
    elif change == 'reverse':
        parts[43] = u32(0) + u32(0) + u32(5)
    elif change == 'out_of_bounds':
        parts[42] = u32(5) + parts[42][4:]
    elif change == 'count':
        parts[43] = u32(1) + u32(5)
    elif change == 'bad_class':
        parts[37] = parts[37][:8] + u16(0) + parts[37][10:]
    else:
        parts[37] = parts[37][:6] + u16(1) + parts[37][8:]
    with pytest.raises(InvalidDocumentError):
        decoded(parts)


def extra(depth=0, parent=0, flags=0):
    return b'\0' * 6 + struct.pack('<IiI', depth, parent, flags)


@pytest.mark.parametrize('last', [extra(1, -1), extra(0, 0, 2)])
def test_reply_or_ink_warns_without_reordering(last):
    parts = base_parts() | {112: extra() + last}
    with pytest.warns(UserWarning, match='replies or ink'):
        assert [s.ordinal for s in decoded(parts)] == [1, 2]


@pytest.mark.parametrize('last', [extra(1, 1), extra(2, -1), extra(0, -1), extra(1, 0)])
def test_bad_extra_parent_and_depth(last):
    with pytest.raises(InvalidDocumentError, match='reply'):
        decoded(base_parts() | {112: extra() + last})


def test_extra_depth_limit():
    with pytest.raises(LimitExceededError, match='depth'):
        decoded(base_parts() | {112: extra() + extra(2, -1)}, limits=Limits(max_depth=1))


def test_unassigned_prefix_is_not_an_extra_comment():
    parts = base_parts()
    parts[5] = b''.join(map(u32, [5, 8, 11, 0xffffffff]))
    with pytest.warns(UserWarning, match='unassigned prefix'):
        result = decoded(parts, story='STALE\x05a\r\x05b\r\r')
    assert [(s.body_start, s.body_end) for s in result] == [(5, 8), (8, 11)]


@pytest.mark.parametrize('limits', [Limits(max_records=2), Limits(max_stream_bytes=10), Limits(max_text_chars=5)])
def test_decoder_limits(limits):
    with pytest.raises(LimitExceededError):
        decoded(limits=limits)


def test_aggregate_record_callback_cannot_be_bypassed():
    calls = []

    def charge(n):
        calls.append(n)
        if sum(calls) > 12:
            raise LimitExceededError('aggregate')

    with pytest.raises(LimitExceededError, match='aggregate'):
        decoded(record=charge)


def test_runtime_original_body_author_and_main_anchor(monkeypatch):
    result = parse(monkeypatch, build())
    c = result.comments[0]
    assert (c.author, c.initials, c.ordinal, c.source_cp, c.anchor_path, c.visibility) == (
        'Ada', 'AF', 1, 0, ['blocks', 0], [])
    assert (c.selection_start, c.selection_end) == (0, 0)
    assert result.comment_text == 'Body'
    assert result.story_blocks['comment_text'] == [Paragraph('Body')]
    assert (c.body.block_start, c.body.block_end) == (0, 1)
    assert result.text == 'Body'


@pytest.mark.parametrize('operation,flag', [(0x083C, 'hidden'), (0x0800, 'deleted'), (0x0802, 'field_hidden')])
def test_reference_visibility_does_not_hide_body_or_shift_ordinals(monkeypatch, operation, flag):
    d = build('\x05X\x05\r', ('\x05First\r', '\x05Second\r'))
    add_chpx(d, [1024, 1026, 1024 + 2 * (4 + 7 + 8 + 1)], [SPECIAL + sprm(operation, 1), SPECIAL])
    result = parse(monkeypatch, d)
    assert [c.ordinal for c in result.comments] == [1, 2]
    assert result.comments[0].visibility == [flag]
    assert result.comments[1].visibility == []
    assert result.comment_text == 'First\nSecond'


def test_body_visibility_is_independent(monkeypatch):
    d = build()
    add_chpx(d, [1024, 1028, 1042, 1044], [SPECIAL, SPECIAL + sprm(0x083C, 1), SPECIAL])
    result = parse(monkeypatch, d)
    assert result.comments[0].visibility == []
    assert result.comment_text == ''
    assert result.story_blocks['comment_text'] == [Paragraph('')]


@pytest.mark.parametrize('where', ['reference', 'body'])
@pytest.mark.parametrize('unknown', [False, True])
def test_marker_false_rejected_unknown_omitted_with_original_ordinals(monkeypatch, where, unknown):
    d = build('\x05X\x05\r', ('\x05A\r', '\x05B\r'))
    # Missing stylesheet makes style-relative CFSpec unresolved; explicit false is invalid.
    if unknown:
        append_table_part(d, 1, b'')
    cp = 0 if where == 'reference' else 4
    fcs = [1024, 1024 + cp * 2, 1024 + (cp + 1) * 2, 1046]
    groups = [SPECIAL, sprm(0x0855, 128 if unknown else 0), SPECIAL]
    if cp == 0:
        del fcs[0]
        del groups[0]
    add_chpx(d, fcs, groups)
    if not unknown:
        with pytest.raises(InvalidDocumentError, match='CFSpec=false'):
            parse(monkeypatch, d)
    else:
        result = parse(monkeypatch, d)
        assert [c.ordinal for c in result.comments] == [2]
        assert result.comment_text == 'B'
        assert (result.comments[0].body.block_start, result.comments[0].body.block_end) == (0, 1)
        assert any('unproven body is omitted' in w for w in result.warnings)


def test_unknown_chpx_or_final_papx_omits_body(monkeypatch):
    for index in (12, 13):
        d = build()
        append_table_part(d, index, b'')
        result = parse(monkeypatch, d)
        assert result.comments == [] and result.comment_text == ''


def test_final_body_paragraph_must_be_outside_table(monkeypatch):
    with pytest.raises(InvalidDocumentError, match='final paragraph is inside a table'):
        parse(monkeypatch, build(props=[b'', IN, b'']))


def test_fields_keep_stored_results_and_reference_instruction_flag(monkeypatch):
    d = build('\x13\x05\x14Main\x15\r', ('\x05\x13COMMAND\x14Stored\x15\r',))
    result = parse(monkeypatch, d)
    assert result.comments[0].visibility == ['field_instruction']
    assert result.comment_text == 'Stored'
    assert result.text == 'Main\n\nStored'


def test_each_body_finishes_its_field_state(monkeypatch):
    result = parse(monkeypatch, build('\x05X\x05\r', ('\x05\x13SECRET\r', '\x05Visible\r')))
    assert result.comment_text == '\nVisible'
    assert [c.ordinal for c in result.comments] == [1, 2]


def test_comment_body_table_and_next_body_do_not_coalesce(monkeypatch):
    bodies = ('\x05\rCell\7\7Tail\r', '\x05Next\r')
    rp = ROW + definition([0])
    result = parse(monkeypatch, build('\x05X\x05\r', bodies,
                                     props=[b'', b'', IN, rp, b'', b'', b'']))
    blocks = result.story_blocks['comment_text']
    assert isinstance(blocks[1], Table) and blocks[1].rows[0][0].text == 'Cell'
    assert blocks[2:] == [Paragraph('Tail'), Paragraph('Next')]
    assert [(c.body.block_start, c.body.block_end) for c in result.comments] == [(0, 3), (3, 4)]


def test_nested_cell_reference_path(monkeypatch):
    from test_doc_nested import cell, paragraph, row

    parts = [paragraph(1, 'Outer'), cell(2, 'Inner\x05'), row(2), cell(1, 'Tail'), row(1)]
    main = ''.join(t for t, _ in parts)
    result = parse(monkeypatch, build(main, props=[p for _, p in parts] + [b'', b'']))
    assert result.comments[0].anchor_path == ['blocks', 0, 'rows', 0, 0, 'blocks', 1, 'rows', 0, 0]


@pytest.mark.parametrize('boundary', ['position', 'direction', 'frame'])
def test_reference_paths_follow_final_table_partition(monkeypatch, boundary):
    change = {'position': sprm(0x940E, u16(100)), 'direction': sprm(0x560B, u16(1)), 'frame': b''}[boundary]
    frame = sprm(0x841A, u16(100)) if boundary == 'frame' else b''
    rp = ROW + definition([0])
    main = 'First\7\7Second\x05\7\7'
    result = parse(monkeypatch, build(main, props=[IN, rp, IN + frame, rp + change, b'', b'']))
    assert result.comments[0].anchor_path == ['blocks', 1, 'rows', 0, 0]


@pytest.mark.parametrize('main,start,end,expected', [
    ('😀Text\x05\r', 2, 6, (2, 6)),
    ('First\rSecond\x05\r', 0, 12, (0, 12)),
    ('A\x13CMD\x14X\x15B\x05\r', 0, 1, (None, None)),
    ('😀Text\x05\r', 1, 6, (None, None)),
])
def test_narrow_selection_bounds(monkeypatch, main, start, end, expected):
    d = build(main, tags=[41])
    for index, data in bookmarks(len(main.encode('utf-16le')) // 2, starts=(start,), ends=(end,)).items():
        append_table_part(d, index, data)
    result = parse(monkeypatch, d)
    c = result.comments[0]
    assert (c.selection_start, c.selection_end) == expected
    assert c.anchor_path is not None


def test_prefix_and_unreferenced_stream_bytes_never_become_comments(monkeypatch):
    d = build()
    d['1Table'] += b'STALE-COMMENT-UNREFERENCED'
    result = parse(monkeypatch, d)
    assert result.comment_text == 'Body'
    assert 'STALE' not in result.text


@pytest.mark.parametrize('missing', [4, 5])
def test_ownership_absence_does_not_revive_stored_story(monkeypatch, missing):
    d = build()
    append_table_part(d, missing, b'')
    result = parse(monkeypatch, d)
    assert result.comments == [] and 'Body' not in result.text


def test_old_fib_does_not_interpret_extra_bytes_as_new_metadata(monkeypatch):
    d = build()
    # Word97 FIB has only 93 pairs; later bytes are not a 2002 metadata array.
    mutate(d, 'WordDocument', 154 + 112 * 8, b'\xff' * 8)
    assert parse(monkeypatch, d).comment_text == 'Body'


def test_unused_author_metadata_counts_before_unicode_decode():
    # 11 source units + 6 author units + 4 initials = 21; unused malformed
    # Unicode must hit its source budget BEFORE decoding the offending string.
    parts = base_parts()
    parts[36] = authors('Ada', 'Ben') + u16(5) + b'\0\xd8' * 5
    with pytest.raises(LimitExceededError, match='source metadata'):
        decoded(parts, limits=Limits(max_text_chars=21))


def test_initials_count_cumulatively_across_records():
    # 11 story + 6 author + 2 + 2 initials = 21 source units.
    assert len(decoded(limits=Limits(max_text_chars=21))) == 2
    with pytest.raises(LimitExceededError, match='source metadata'):
        decoded(limits=Limits(max_text_chars=20))


def test_comment_source_metadata_includes_other_declared_stories():
    with pytest.raises(LimitExceededError, match='source metadata'):
        decoded(limits=Limits(max_text_chars=21), source_text_count=12)


def test_source_metadata_not_recharged_as_repeated_output_authors():
    # Source strings count once per XST, plus each initials buffer. Repeated
    # published authors are charged separately by _Doc and public API output.
    parts = base_parts() | {4: reference([0, 2]), 36: authors('Ada')}
    assert len(decoded(parts, limits=Limits(max_text_chars=18))) == 2


def test_reference_path_tracks_omitted_grid_position(monkeypatch):
    main = '\x05\7\7L\7R\7\7'
    result = parse(monkeypatch, build(main, props=[
        IN, ROW + definition([0], [100, 200]), IN, IN,
        ROW + definition([0, 0], [0, 100, 200]), b'', b'']))
    assert result.blocks[0].rows[0][0].omitted
    assert result.comments[0].anchor_path == ['blocks', 0, 'rows', 0, 1]


def test_covered_source_cell_anchor_is_not_moved_to_merge_origin(monkeypatch):
    main = 'Origin\7Covered\x05\7\7'
    result = parse(monkeypatch, build(main, props=[IN, IN, ROW + definition([2, 1]), b'', b'']))
    assert result.blocks[0].rows[0][1].covered
    assert result.comments[0].anchor_path == ['blocks', 0, 'rows', 0, 1]


@pytest.mark.parametrize('uncertain', [False, True])
def test_conditional_table_visibility_flags_propagate_to_comments(monkeypatch, uncertain):
    from test_doc_conditional_styles import cnf, table_style
    from test_doc_table_styles import tistd

    main = 'Cell\x05\7\7'
    rp = ROW + definition([0]) + tistd(16) + struct.pack('<HhH', 0x740A, -1, 0x620)
    d = build(main, props=[IN, rp, b'', b''])
    stylesheet(d, [style(0)] + [b'\0\0'] * 15 + [table_style(
        chpx=cnf(1, 1), papx=sprm(0x841A, u16(100)) if uncertain else b'')])
    result = parse(monkeypatch, d)
    assert result.comments[0].visibility == (['unknown'] if uncertain else ['hidden'])
    assert result.comments[0].anchor_path == ['blocks', 0, 'rows', 0, 0]
    assert result.comment_text == 'Body'


def test_notes_and_comments_share_final_container_without_cross_pairing(monkeypatch):
    from test_doc_notes import reference_plc, text_plc

    main, foot, comment = '\x02\x05\r', '\x02Foot\r\r', '\x05Comment\r\r'
    text = main + foot + comment
    d = fixture([(text, True)], counts=[len(main), len(foot), 0, len(comment), 0, 0, 0],
                props=[b''] * 5)
    stylesheet(d, [style(0)])
    add_chpx(d, [1024, 1024 + len(text)], [SPECIAL])
    for index, data in {
        2: reference_plc([0]), 3: text_plc([0, len(foot) - 1]),
        4: reference([1]), 5: text_plc([0, len(comment) - 1]), 36: authors('Ada'),
    }.items():
        append_table_part(d, index, data)
    result = parse(monkeypatch, d)
    assert result.notes[0].source_cp == 0
    assert result.comments[0].source_cp == 1
    assert result.notes[0].anchor_path == result.comments[0].anchor_path == ['blocks', 0]
    assert result.footnotes == 'Foot\n' and result.comment_text == 'Comment'
    assert result.text.count('Comment') == result.text.count('Foot') == 1


def test_comment_and_note_path_budget_charged_before_publication():
    from legacy_office_parser.models import Document, Note, NoteBodyRange, Comment, CommentBodyRange
    from legacy_office_parser.doc import _Budget, _Doc

    target = Paragraph('shared')
    note = Note('footnote', 1, NoteBodyRange('footnotes', 0, 1), source_cp=0)
    comment = Comment(1, CommentBodyRange('comment_text', 0, 1), source_cp=1)
    parser = object.__new__(_Doc)
    parser.document = Document('doc', blocks=[target], notes=[note], comments=[comment])
    parser.note_targets = {0: target, 1: target}
    parser.budget = _Budget(Limits(max_records=3))
    with pytest.raises(LimitExceededError, match='record limit'):
        parser._resolve_note_paths()
    assert note.anchor_path is None and comment.anchor_path is None


def test_runtime_cumulative_unused_metadata_is_bounded(monkeypatch):
    d = build()
    append_table_part(d, 36, authors('Ada', 'Unused-author'))
    # Ten source units, three used author units, thirteen unused units, two initials.
    with pytest.raises(LimitExceededError, match='source metadata'):
        parse(monkeypatch, d, Limits(max_text_chars=25))


def test_runtime_repeated_author_output_is_bounded(monkeypatch):
    main = '\x05\x05\x05\x05\r'
    d = build(main, ('\x05A\r',) * 4)
    append_table_part(d, 36, authors('X' * 30))
    # Source = 18 CP + 30 owner + 8 initials = 56; retained four authors alone
    # cost 120, so output must independently fail despite source fitting.
    with pytest.raises(LimitExceededError, match='output text'):
        parse(monkeypatch, d, Limits(max_text_chars=60))


def test_comment_aggregate_work_limit_before_cleaning(monkeypatch):
    from legacy_office_parser.doc import _Doc

    original = _Doc.clean
    observed = []

    def clean(self, *args, **kwargs):
        observed.append(self.budget.records)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(_Doc, 'clean', clean)
    parse(monkeypatch, build())
    required = observed[0]
    observed.clear()
    with pytest.raises(LimitExceededError, match='record'):
        parse(monkeypatch, build(), Limits(max_records=required - 1))
    assert observed == []


def test_initials_unused_storage_is_not_decoded_and_length_is_bounded():
    parts = base_parts()
    raw = bytearray(parts[4])
    # First ATRD begins after 3 CPs; only two initials units are live.
    raw[12 + 6:12 + 20] = b'\0\xd8' * 7
    parts[4] = raw
    assert decoded(parts)[0].initials == 'AF'
    raw[12:14] = u16(10)
    with pytest.raises(InvalidDocumentError, match='initials length'):
        decoded(parts)


def test_missing_ownership_does_not_hide_present_malformed_owner_data():
    parts = base_parts() | {36: b'\x01'}
    del parts[4]
    with pytest.raises(InvalidDocumentError, match='author length'):
        decoded(parts)


def test_many_markers_never_search_the_growing_anchor_list(monkeypatch):
    from legacy_office_parser.doc import _Doc

    class NoMembershipList(list):
        def __contains__(self, value):
            raise AssertionError('linear membership scan on accumulated paragraph anchors')

    def store(self, value):
        self._test_anchor_list = NoMembershipList(value)

    monkeypatch.setattr(_Doc, 'paragraph_anchors', property(
        lambda self: self._test_anchor_list, store), raising=False)
    n = 128
    result = parse(monkeypatch, build('\x05' * n + '\r', ('\x05A\r',) * n))
    assert len(result.comments) == n
    assert [c.source_cp for c in result.comments] == list(range(n))
    assert all(c.anchor_path == ['blocks', 0] for c in result.comments)
