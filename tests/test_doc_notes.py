"""Independent authored DOCX, raw BIFF-like DOC PLC bytes, and bounded note model tests."""
from pathlib import Path
import os
import struct
import sys
import xml.etree.ElementTree as ET
from zipfile import ZipFile

import olefile
import pytest

from legacy_office_parser._doc_notes import decode_note_ranges
from legacy_office_parser.errors import InvalidDocumentError, LimitExceededError
from legacy_office_parser.limits import Limits

FIXTURE = Path(__file__).parent / 'fixtures/doc_notes'
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def reference_plc(cps, flags=None, sentinel=0xffffffff):
    if flags is None:
        flags = [1] * len(cps)
    return struct.pack('<' + 'I' * (len(cps) + 1), *cps, sentinel) + struct.pack('<' + 'H' * len(flags), *flags)


def text_plc(cps, sentinel=0xffffffff):
    return struct.pack('<' + 'I' * (len(cps) + 1), *cps, sentinel)


def raw_fixture():
    """Independent CLX walk: fixture-only, no production decoder imports.

    Return raw UTF-16 CP storage and the four PLCs. Do not normalize controls,
    strip labels or filter deleted references before ordinal pairing.
    """
    with olefile.OleFileIO(FIXTURE / 'authored.doc') as compound:
        word = compound.openstream('WordDocument').read()
        name = '1Table' if struct.unpack_from('<H', word, 10)[0] & 0x200 else '0Table'
        table = compound.openstream(name).read()
    counts = [struct.unpack_from('<I', word, 64 + i * 4)[0] for i in (3, 4, 5, 7, 8, 9, 10)]

    def part(index):
        at, size = struct.unpack_from('<II', word, 154 + index * 8)
        return table[at:at+size]

    clx = part(33)
    at = 0
    while clx[at] == 1:
        at += 3 + struct.unpack_from('<H', clx, at + 1)[0]
    assert clx[at] == 2
    size = struct.unpack_from('<I', clx, at + 1)[0]
    plc = clx[at+5:at+5+size]
    count = (size - 4) // 12
    cps = struct.unpack_from('<' + 'I' * (count + 1), plc)
    units = bytearray()
    for i in range(count):
        fc = struct.unpack_from('<I', plc, 4 * (count+1) + i*8 + 2)[0]
        width = 1 if fc & 0x40000000 else 2
        offset = (fc & 0x3fffffff) // (2 if width == 1 else 1)
        raw = word[offset:offset + (cps[i+1]-cps[i])*width]
        # The authored fixture uses only ASCII in compressed runs.
        if width == 1:
            assert all(c < 128 for c in raw)
            raw = raw.decode('ascii').encode('utf-16le')
        units.extend(raw)
    return counts, bytes(units), {i: part(i) for i in (2, 3, 46, 47)}


def xml_relationships(path, kind):
    """Resolve IDs independently; return context, body, custom, visibility flags."""
    with ZipFile(path) as archive:
        main = ET.fromstring(archive.read('word/document.xml'))
        notes = ET.fromstring(archive.read(f'word/{kind}s.xml'))
    bodies = {note.get(W+'id'): ''.join(note.itertext()) for note in notes
              if note.get(W+'type') is None}
    # itertext also includes no XML formatting whitespace in this fixture.
    parent = {child: node for node in main.iter() for child in node}
    result = []
    for ref in main.iter(W+kind+'Reference'):
        node = parent[ref]
        hidden = node.find('./'+W+'rPr/'+W+'vanish') is not None
        deleted = False
        while node.tag != W+'p':
            deleted |= node.tag == W+'del'
            node = parent[node]
        context = ''.join(node.itertext())
        result.append((context, bodies[ref.get(W+'id')],
                       ref.get(W+'customMarkFollows') == '1', hidden, deleted))
    return result


def test_two_ranges_pair_in_order_not_by_flag_value():
    result = decode_note_ranges(reference_plc([1, 3], [23, 0]), text_plc([0, 2, 4]),
                                5, 'a\rb\r\r'.encode('utf-16le'), Limits())
    assert [(n.ordinal, n.source_cp, n.reference_kind, n.body_start, n.body_end) for n in result] == [
        (1, 1, 'automatic', 0, 2), (2, 3, 'custom', 2, 4)]


@pytest.mark.parametrize('flag,marker', [(1, '\x02'), (0, '*'), (0, '**')])
def test_leading_body_markers_are_preserved_not_inferred_or_stripped(flag, marker):
    body = marker + ' Body\r'
    raw = (body + '\r').encode('utf-16le')
    end = len(body.encode('utf-16le')) // 2
    notes = decode_note_ranges(reference_plc([0], [flag]), text_plc([0, end]),
                               1, raw, Limits())
    assert len(notes) == 1
    note = notes[0]
    assert note.reference_kind == ('automatic' if flag else 'custom')
    assert (note.body_start, note.body_end) == (0, end)
    assert raw[note.body_start * 2:note.body_end * 2].decode('utf-16le') == body


def test_astral_bodies_use_utf16_boundaries_without_losing_characters():
    bodies = ['\x02 A😀\r', '* 🚀B\r']
    raw = (''.join(bodies) + '\r').encode('utf-16le')
    # Each astral character occupies two UTF-16 units.
    notes = decode_note_ranges(reference_plc([0, 2], [1, 0]), text_plc([0, 6, 12]),
                               3, raw, Limits())
    assert [(n.body_start, n.body_end) for n in notes] == [(0, 6), (6, 12)]
    assert [raw[n.body_start * 2:n.body_end * 2].decode('utf-16le') for n in notes] == bodies


def test_body_boundary_cannot_split_a_surrogate_pair():
    raw = 'A😀\rB\r\r'.encode('utf-16le')
    # CP 2 splits the surrogate pair, so the first range necessarily lacks CR.
    with pytest.raises(InvalidDocumentError, match='final paragraph mark'):
        decode_note_ranges(reference_plc([0, 1]), text_plc([0, 2, 6]),
                           2, raw, Limits())


@pytest.mark.parametrize('references', [b'', reference_plc([]), reference_plc([0])])
def test_zero_body_plc_emits_no_invented_note(references):
    messages = []
    charged = []
    assert decode_note_ranges(references, text_plc([0]), 1, b'\r\0', Limits(),
                              warn=messages.append, record=charged.append) == []
    expected_charge = 2 + ((len(references) - 4) // 6 + 1 if references else 0)
    assert charged == [expected_charge]
    assert len(messages) == (1 if references == reference_plc([0]) else 0)
    if messages:
        assert 'no corresponding bodies' in messages[0]


def test_zero_body_plc_cannot_claim_an_absent_reserved_cp():
    with pytest.raises(InvalidDocumentError, match='CP order or range'):
        decode_note_ranges(reference_plc([]), text_plc([0]), 0, b'', Limits())


@pytest.mark.parametrize('ref_sentinel', [0, 1, 0x7fffffff, 0xffffffff])
@pytest.mark.parametrize('txt_sentinel', [0, 1, 0x7fffffff, 0xffffffff])
def test_unused_sentinels_are_not_ranges(ref_sentinel, txt_sentinel):
    notes = decode_note_ranges(reference_plc([1], sentinel=ref_sentinel),
                               text_plc([0, 2], sentinel=txt_sentinel),
                               3, b'a\0\r\0\r\0', Limits())
    assert len(notes) == 1 and notes[0].body_end == 2


def test_missing_text_preserves_legacy_story():
    messages = []
    assert decode_note_ranges(b'', b'', 1, b'a\0', Limits(), warn=messages.append) is None
    assert len(messages) == 1
    assert decode_note_ranges(b'', b'', 0, b'', Limits()) == []


@pytest.mark.parametrize('references', [b'', reference_plc([]), reference_plc([1, 2])])
def test_absent_or_count_mismatched_references_never_guess(references):
    messages = []
    notes = decode_note_ranges(references, text_plc([0, 2]), 4, b'a\0\r\0\r\0',
                               Limits(), warn=messages.append)
    assert notes[0].source_cp is None and notes[0].reference_kind == 'unknown'
    assert notes[0].body_start == 0 and notes[0].body_end == 2
    assert len(messages) == 1


def test_unassigned_prefix_preserves_whole_story():
    messages = []
    assert decode_note_ranges(reference_plc([1]), text_plc([1, 3]), 2,
                               'xa\r\r'.encode('utf-16le'), Limits(), warn=messages.append) is None
    assert 'prefix' in messages[0]


@pytest.mark.parametrize('refs,texts,story', [
    (b'x', text_plc([0, 2]), 'a\r\r'),
    (reference_plc([1]), b'x', 'a\r\r'),
    (reference_plc([1]), struct.pack('<I', 0), 'a\r\r'),
    (reference_plc([1, 1]), text_plc([0, 2]), 'a\r\r'),
    (reference_plc([2, 1]), text_plc([0, 2]), 'a\r\r'),
    (reference_plc([4]), text_plc([0, 2]), 'a\r\r'),
    (reference_plc([0x80000000]), text_plc([0, 2]), 'a\r\r'),
    (reference_plc([1]), text_plc([0, 0]), 'a\r\r'),
    (reference_plc([1]), text_plc([0, 3]), 'a\r\r'),
    (reference_plc([1]), text_plc([0, 1]), 'a\r\r'),
    (reference_plc([1]), text_plc([0, 2]), 'ax\r'),
    (reference_plc([1]), text_plc([0, 0x80000000]), 'a\r\r'),
    (reference_plc([1]), text_plc([0, 1]), ''),
])
def test_malformed_present_plcs_fail(refs, texts, story):
    with pytest.raises(InvalidDocumentError):
        decode_note_ranges(refs, texts, 4, story.encode('utf-16le'), Limits())


def test_malformed_ref_is_not_hidden_by_absent_text():
    with pytest.raises(InvalidDocumentError):
        decode_note_ranges(reference_plc([5]), b'', 2, b'', Limits())


def test_source_and_record_budgets_before_allocation():
    args = (reference_plc([1]), text_plc([0, 2]), 3, b'a\0\r\0\r\0')
    for limits in (Limits(max_records=4), Limits(max_text_chars=5), Limits(max_stream_bytes=5)):
        with pytest.raises(LimitExceededError):
            decode_note_ranges(*args, limits)
    charged = []
    decode_note_ranges(*args, Limits(max_records=5), record=charged.append)
    assert charged == [5]

    def exhausted(count):
        raise LimitExceededError('aggregate')
    with pytest.raises(LimitExceededError, match='aggregate'):
        decode_note_ranges(*args, Limits(), record=exhausted)


def test_fixture_source_reproducible(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
    try:
        from generate_doc_notes_fixture import generate_source
        generate_source(tmp_path / 'source.docx')
    finally:
        sys.path.pop(0)
    assert (tmp_path / 'source.docx').read_bytes() == (FIXTURE / 'authored.docx').read_bytes()


def test_raw_plc_pairing_matches_authored_order_and_survives_roundtrip():
    counts, units, plcs = raw_fixture()
    expected = {
        'footnote': ([14, 36, 48, 60, 99, 115], [1, 0, 2, 3, 4, 5],
                     [0, 15, 31, 46, 80, 105, 131, 132],
                     ['Shared note.', '** Custom body.', 'Shared note.', 'Note table.',
                      'Hidden reference body.', 'Deleted reference body.']),
        'endnote': ([73, 84], [1, 2], [0, 17, 34, 35], ['End cell body.', 'End main body.']),
    }
    for kind, index, ref_index, text_index in [('footnote', 1, 2, 3), ('endnote', 4, 46, 47)]:
        ref_cps, flags, body_cps, labels = expected[kind]
        ref_data, txt_data = plcs[ref_index], plcs[text_index]
        n = (len(ref_data) - 4) // 6
        assert list(struct.unpack_from('<'+'I'*n, ref_data)) == ref_cps
        assert list(struct.unpack_from('<'+'H'*n, ref_data, (n+1)*4)) == flags
        assert list(struct.unpack('<'+'I'*(len(txt_data)//4), txt_data)) == body_cps
        base = sum(counts[:index])
        story = units[base*2:(base+counts[index])*2]
        decoded = decode_note_ranges(ref_data, txt_data, counts[0], story, Limits())
        source = xml_relationships(FIXTURE/'authored.docx', kind)
        roundtrip = xml_relationships(FIXTURE/'roundtrip.docx', kind)
        assert len(decoded) == len(source) == len(roundtrip)
        for i, note in enumerate(decoded):
            assert note.source_cp == ref_cps[i]
            assert note.reference_kind == ('custom' if flags[i] == 0 else 'automatic')
            char = units[note.source_cp*2:note.source_cp*2+2].decode('utf-16le')
            assert char == ('*' if flags[i] == 0 else '\x02')
            raw_body = story[note.body_start*2:note.body_end*2].decode('utf-16le')
            assert labels[i] in raw_body and raw_body.endswith('\r')
            assert source[i][0] == roundtrip[i][0]
            assert source[i][2:] == roundtrip[i][2:]
            assert labels[i].lstrip('* ') in roundtrip[i][1]
    # Emoji consumes two CP units; Python string index is deliberately different.
    main = units[:counts[0]*2].decode('utf-16le')
    assert main.index('\x02') == 13 and expected['footnote'][0][0] == 14


def test_lo_export_losses_are_evidence_not_expectations_for_the_parser():
    source = xml_relationships(FIXTURE/'unordered.docx', 'endnote')
    exported = xml_relationships(FIXTURE/'unordered-roundtrip.docx', 'endnote')
    assert [r[0] for r in source] == [r[0] for r in exported]
    assert [r[1] for r in source] == [' End cell body.', ' End main body.']
    assert [r[1] for r in exported] == [' End main body.', ' End cell body.']
    original = xml_relationships(FIXTURE/'authored.docx', 'footnote')
    converted = xml_relationships(FIXTURE/'roundtrip.docx', 'footnote')
    assert original[1][1] == '* Custom body.' and converted[1][1] == '** Custom body.'
    assert 'NoteTableCell' in original[3][1] and 'NoteTableCell' not in converted[3][1]


def resolve(doc, path):
    result = doc
    for step in path:
        result = getattr(result, step) if isinstance(step, str) else result[step]
    return result


def test_live_binary_fixture_exposes_body_ranges_and_structural_anchor_paths():
    from legacy_office_parser import parse_doc
    from legacy_office_parser.models import Cell, Paragraph
    doc = parse_doc(FIXTURE/'authored.doc')
    assert len(doc.notes) == 8
    expected = [
        (14, ['blocks', 0], 'MainAstral😀A  after.', []),
        (36, ['blocks', 1], 'CustomAnchor *', []),
        (48, ['blocks', 2, 'rows', 0, 0], 'OuterCell ', []),
        (60, ['blocks', 2, 'rows', 0, 1, 'blocks', 0, 'rows', 0, 0], 'InnerCell ', []),
        (99, ['blocks', 4], 'HiddenAnchor ', ['hidden']),
        (115, ['blocks', 5], 'DeletedAnchor ', ['deleted']),
        (73, ['blocks', 2, 'rows', 0, 1, 'blocks', 1], 'OuterTail ', []),
        (84, ['blocks', 3], 'EndMain ', []),
    ]
    for note, (cp, path, text, visibility) in zip(doc.notes, expected, strict=True):
        assert note.source_cp == cp and note.anchor_path == path
        target = resolve(doc, path)
        assert isinstance(target, (Paragraph, Cell)) and target.text == text
        assert note.visibility == visibility
        body = doc.story_blocks[note.body.story][note.body.block_start:note.body.block_end]
        assert body
    assert [n.ordinal for n in doc.notes] == [1, 2, 3, 4, 5, 6, 1, 2]
    assert doc.to_dict()['notes'][0]['body'] == {'story': 'footnotes', 'block_start': 0, 'block_end': 1}
    assert doc.text.count('Shared note.') == 2  # Two actual notes, not another copy in notes.
    assert '** Custom body.' in doc.footnotes  # Never guess which marker to strip.


def synthetic_note(monkeypatch, main='a\x02\r', story='note\r\r', *, automatic=True,
                   group=b'\x55\x08\x01', cp=1, texts=None, props=None):
    from test_doc import fixture, parse
    from test_doc_fidelity import add_chpx, append_table_part
    streams = fixture([(main + story, True)], counts=[len(main), len(story), 0, 0, 0, 0, 0], props=props)
    append_table_part(streams, 2, reference_plc([cp], [1 if automatic else 0]))
    append_table_part(streams, 3, text_plc([0, len(story)-1]) if texts is None else texts)
    if group is not None:
        add_chpx(streams, [1024, 1024+len(main+story)], [group])
    return parse(monkeypatch, streams)


def test_authored_story_projection_matches_legacy_whole_story_scan(monkeypatch):
    from legacy_office_parser import Paragraph, parse_doc
    from legacy_office_parser.doc import _Doc
    current = parse_doc(FIXTURE / 'authored.doc')
    # The pre-notes path scans each complete auxiliary story, including its
    # reserved final CP. Disable only note splitting/association as an oracle.
    monkeypatch.setattr(_Doc, '_prepare_notes', lambda self: setattr(self, 'note_ranges', {}))
    baseline = parse_doc(FIXTURE / 'authored.doc')
    assert current.footnotes == baseline.footnotes
    assert current.endnotes == baseline.endnotes
    assert current.text == baseline.text
    assert current.endnotes.endswith('\n')
    for story in ('footnotes', 'endnotes'):
        last = max(n.body.block_end for n in current.notes if n.body.story == story)
        assert current.story_blocks[story][last:] == [Paragraph('')]


@pytest.mark.parametrize('record_limit', [1, 1000])
def test_anchor_resolver_bounds_memory_for_deep_wide_tree(record_limit):
    import tracemalloc
    from legacy_office_parser import Cell, Document, Note, NoteBodyRange, Paragraph, Table
    from legacy_office_parser.doc import _Budget, _Doc
    target = Paragraph('target')
    cells = [Cell(blocks=[Paragraph('')]) for _ in range(39999)]
    cells.append(Cell(blocks=[target]))
    tree = Table(rows=[cells])
    for _ in range(30):
        tree = Table(rows=[[Cell(blocks=[tree])]])
    note = Note('footnote', 1, NoteBodyRange('footnotes', 0, 1), source_cp=0)
    parser = object.__new__(_Doc)
    parser.document = Document('doc', blocks=[tree], notes=[note])
    parser.note_targets = {0: target}
    parser.budget = _Budget(Limits(max_records=record_limit))
    tracemalloc.start()
    try:
        if record_limit == 1:
            with pytest.raises(LimitExceededError, match='record limit'):
                parser._resolve_note_paths()
            assert note.anchor_path is None
        else:
            parser._resolve_note_paths()
            assert resolve(parser.document, note.anchor_path) is target
            assert parser.budget.records == len(note.anchor_path)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    # Tree allocation is excluded. The previous eager sibling/path stack
    # allocated tens of MiB here before checking the publication budget.
    assert peak < 1024 * 1024


def test_shared_anchor_paths_are_charged_before_any_copy_is_published():
    from legacy_office_parser import Document, Note, NoteBodyRange, Paragraph
    from legacy_office_parser.doc import _Budget, _Doc
    target = Paragraph('two references')
    notes = [Note('footnote', i + 1, NoteBodyRange('footnotes', i, i + 1), source_cp=i)
             for i in range(2)]
    parser = object.__new__(_Doc)
    parser.document = Document('doc', blocks=[target], notes=notes)
    parser.note_targets = {0: target, 1: target}
    parser.budget = _Budget(Limits(max_records=3))
    with pytest.raises(LimitExceededError, match='record limit'):
        parser._resolve_note_paths()
    assert all(note.anchor_path is None for note in notes)


@pytest.mark.parametrize('group,flag', [(b'\x3c\x08\x01', 'hidden'),
                                        (b'\x00\x08\x01', 'deleted'),
                                        (b'\x02\x08\x01', 'field_hidden')])
def test_suppressed_reference_still_has_the_correct_container(monkeypatch, group, flag):
    doc = synthetic_note(monkeypatch, group=b'\x55\x08\x01'+group)
    assert doc.notes[0].anchor_path == ['blocks', 0]
    assert flag in doc.notes[0].visibility
    assert 'unknown' in doc.notes[0].visibility  # Synthetic fixture has no stylesheet.
    assert doc.blocks[0].text == ''


def test_reference_in_field_instruction_is_not_called_visible(monkeypatch):
    doc = synthetic_note(monkeypatch, main='\x13x\x02\x14result\x15\r', cp=2)
    assert doc.blocks[0].text == 'result'
    assert 'field_instruction' in doc.notes[0].visibility
    assert doc.notes[0].anchor_path == ['blocks', 0]


def test_missing_special_property_keeps_body_but_not_guessed_anchor(monkeypatch):
    doc = synthetic_note(monkeypatch, group=None)
    assert doc.notes[0].source_cp == 1 and doc.notes[0].anchor_path is None
    assert 'unknown' in doc.notes[0].visibility and doc.footnotes == 'note\n'


def test_wrong_automatic_reference_character_fails(monkeypatch):
    with pytest.raises(InvalidDocumentError, match=r'U\+0002'):
        synthetic_note(monkeypatch, main='ax\r')


def test_note_boundary_resets_fields_and_tables(monkeypatch):
    from test_doc import IN, ROW, definition, fixture, parse
    from test_doc_fidelity import append_table_part
    main = '*a*b\r'
    first = '\x13ignored\r'
    second = 'left\7right\7\7\r'
    third = 'next\7\7\r'
    story = first + second + third + '\r'
    props = [b'', b'', IN, IN, ROW+definition([0, 0]), b'', IN, ROW+definition([0]), b'', b'']
    streams = fixture([(main+story, True)], counts=[len(main), len(story), 0, 0, 0, 0, 0], props=props)
    # Three bodies, two refs: ALL bodies remain explicitly unlinked.
    append_table_part(streams, 2, reference_plc([0, 2], [0, 0]))
    append_table_part(streams, 3, text_plc([0, len(first), len(first+second), len(story)-1]))
    doc = parse(monkeypatch, streams)
    assert len(doc.notes) == 3 and all(n.source_cp is None for n in doc.notes)
    assert all(n.anchor_path is None and n.reference_kind == 'unknown' for n in doc.notes)
    assert 'left\tright' in doc.footnotes and 'next' in doc.footnotes
    assert doc.notes[1].body.block_end <= doc.notes[2].body.block_start


def test_anchor_path_is_computed_after_omitted_grid_positions(monkeypatch):
    from test_doc import IN, ROW, definition
    main = '*\7\7L\7R\7\7'
    props = [IN, ROW+definition([0], [100, 200]), IN, IN,
             ROW+definition([0, 0], [0, 100, 200]), b'', b'']
    doc = synthetic_note(monkeypatch, main, 'N\r\r', automatic=False, cp=0, props=props)
    assert doc.notes[0].anchor_path == ['blocks', 0, 'rows', 0, 1]
    assert doc.blocks[0].rows[0][0].omitted
    assert resolve(doc, doc.notes[0].anchor_path).text == '*'


def test_model_serialization_and_budget_do_not_duplicate_body():
    from legacy_office_parser import Document, Note, NoteBodyRange, Paragraph
    from legacy_office_parser.api import _validate_result
    doc = Document('doc', blocks=[Paragraph('A')], footnotes='B',
                   story_blocks={'footnotes': [Paragraph('B')]},
                   notes=[Note('footnote', 1, NoteBodyRange('footnotes', 0, 1),
                               source_cp=0, reference_kind='custom', anchor_path=['blocks', 0], visibility=[])])
    assert _validate_result(doc, Limits(max_text_chars=3)) is doc
    with pytest.raises(LimitExceededError):
        _validate_result(doc, Limits(max_text_chars=2))
    assert 'notes' not in Document('doc').to_dict()
    assert len(doc.to_dict()['notes']) == 1
    with pytest.raises(LimitExceededError):
        _validate_result(doc, Limits(max_records=2))


@pytest.mark.parametrize('changes', [
    {'ordinal': 0}, {'source_cp': -1}, {'source_cp': True}, {'reference_kind': 'label'},
    {'anchor_path': []}, {'anchor_path': ['blocks', -1]}, {'anchor_path': ['blocks', True]},
    {'anchor_path': ['blocks', 0, 'text']}, {'anchor_path': ['blocks', 1]},
    {'visibility': ['visible']}, {'visibility': ['hidden', 'hidden']},
])
def test_public_api_validates_note_metadata(changes):
    from legacy_office_parser import Document, Note, NoteBodyRange, Paragraph
    from legacy_office_parser.api import _validate_result
    note = Note('footnote', 1, NoteBodyRange('footnotes', 0, 1), source_cp=0,
                reference_kind='custom', anchor_path=['blocks', 0], visibility=[])
    for name, value in changes.items():
        setattr(note, name, value)
    doc = Document('doc', blocks=[Paragraph('a')], story_blocks={'footnotes': [Paragraph('b')]}, notes=[note])
    with pytest.raises(InvalidDocumentError):
        _validate_result(doc, Limits())


def test_public_api_rejects_overlapping_body_ranges():
    from legacy_office_parser import Document, Note, NoteBodyRange, Paragraph
    from legacy_office_parser.api import _validate_result
    doc = Document('doc', story_blocks={'footnotes': [Paragraph('b')]}, notes=[
        Note('footnote', 1, NoteBodyRange('footnotes', 0, 1)),
        Note('footnote', 2, NoteBodyRange('footnotes', 0, 1))])
    with pytest.raises(InvalidDocumentError, match='overlapping'):
        _validate_result(doc, Limits())


def test_frame_split_keeps_note_anchor_with_its_actual_row(monkeypatch):
    from test_doc import IN, ROW, definition, sprm
    # A positioned first cell splits two tables. References belong to the
    # second table after row/frame identity has been applied, not table zero.
    main = 'A\7\7*\7\7'
    position = sprm(0x8418, struct.pack('<h', 120))
    props = [IN+position, ROW+definition([0]), IN, ROW+definition([0]), b'', b'']
    doc = synthetic_note(monkeypatch, main, 'N\r\r', automatic=False, cp=3, props=props)
    assert doc.notes[0].anchor_path == ['blocks', 1, 'rows', 0, 0]
    assert resolve(doc, doc.notes[0].anchor_path).text == '*'


def test_empty_note_body_and_missing_plc_keep_distinct_contracts(monkeypatch):
    from test_doc import fixture, parse
    empty = synthetic_note(monkeypatch, story='\r\r')
    assert len(empty.notes) == 1
    assert empty.notes[0].body.block_end == 1
    assert empty.footnotes == '\n'
    legacy = parse(monkeypatch, fixture([('main\rnote\r', True)], counts=[5, 5, 0, 0, 0, 0, 0]))
    assert legacy.footnotes == 'note' and legacy.notes == []
    assert 'notes' not in legacy.to_dict() and 'story_blocks' not in legacy.to_dict()
    assert any('PLC is absent' in warning for warning in legacy.warnings)


def test_fixture_unordered_source_reproducible(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
    try:
        from generate_doc_notes_fixture import generate_source
        generate_source(tmp_path / 'source.docx', unordered=True)
    finally:
        sys.path.pop(0)
    assert (tmp_path / 'source.docx').read_bytes() == (FIXTURE/'unordered.docx').read_bytes()


# Keep converters strictly outside runtime. This test consumes only authored
# numeric/text XML and uses the generator's bounded, private-profile subprocess.
@pytest.mark.skipif(os.environ.get('OFFICE_CORPUS_LIBREOFFICE') != '1',
                    reason='opt-in independent authored note round trip')
def test_independent_live_note_roundtrip(tmp_path):
    from legacy_office_parser import parse_doc
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
    try:
        from generate_doc_notes_fixture import generate_source, convert_roundtrip
        generate_source(tmp_path/'authored.docx')
        convert_roundtrip(tmp_path)
    finally:
        sys.path.pop(0)
    doc = parse_doc(tmp_path/'authored.doc')
    saved = parse_doc(FIXTURE/'authored.doc')
    assert doc.notes == saved.notes
    assert doc.footnotes == saved.footnotes and doc.endnotes == saved.endnotes
    for kind in ('footnote', 'endnote'):
        assert xml_relationships(tmp_path/'roundtrip.docx', kind) == xml_relationships(FIXTURE/'roundtrip.docx', kind)
