"""Source-owned auxiliary ranges from original synthetic DOC streams."""
from dataclasses import asdict

import pytest

from legacy_office_parser import Limits, Paragraph, normalize_text
from legacy_office_parser._validation import _validate_result
from test_doc import fixture, mutate, parse, u32
from test_doc_textboxes import plc


def put(streams, pair, data):
    offset = len(streams['1Table'])
    streams['1Table'] += data
    mutate(streams, 'WordDocument', 154 + pair * 8, u32(offset) + u32(len(data)))


def textbox_fixture():
    main = 'Body\r'
    # The middle reusable record must not renumber the last live textbox.
    boxes = 'One\r\rTwo\rReserved\r'
    head_boxes = 'Header box\rSpare\r'
    streams = fixture([(main + boxes + head_boxes, True)],
                      counts=[len(main), 0, 0, 0, 0, len(boxes), len(head_boxes)])
    put(streams, 56, plc([0, 4, 5, 9, len(boxes)], [0, 1, 0, 0]))
    put(streams, 58, plc([0, 11, len(head_boxes)], [0, 0]))
    return streams


def test_textboxes_keep_source_subdocument_and_plc_ordinal(monkeypatch):
    d = _validate_result(parse(monkeypatch, textbox_fixture()), Limits())
    assert d.textboxes == 'One\nTwo\nHeader box'
    assert d.story_blocks['textboxes'] == [Paragraph('One'), Paragraph('Two'), Paragraph('Header box')]
    assert [(a.source, a.ordinal, a.block_start, a.block_end, a.source_start, a.source_end)
            for a in d.auxiliary_stories] == [
        ('main_textbox', 1, 0, 1, 0, 4), ('main_textbox', 3, 1, 2, 5, 9),
        ('header_textbox', 1, 2, 3, 0, 11)]
    assert all(a.kind == 'textbox' and a.section is None and a.variant is None
               and a.inherited_from is None for a in d.auxiliary_stories)
    assert d.to_dict()['auxiliary_stories'] == [asdict(a) for a in d.auxiliary_stories]
    assert normalize_text(d).auxiliary_stories == d.auxiliary_stories
    assert d.text.count('One') == 1 and 'Reserved' not in d.text and 'Spare' not in d.text


def test_absent_textbox_plc_does_not_invent_identity(monkeypatch):
    d = parse(monkeypatch, fixture([('B\rBox\r', True)], counts=[2, 0, 0, 0, 0, 4, 0]))
    assert d.textboxes == 'Box'
    assert not d.auxiliary_stories
    assert 'auxiliary_stories' not in d.to_dict()


@pytest.mark.parametrize('source_index,pair', [(5, 56), (6, 58)])
def test_non_bmp_source_offsets_are_utf16_units(monkeypatch, source_index, pair):
    body, text = 'B\r', '😀\rOLD\r'
    counts = [2, 0, 0, 0, 0, 0, 0]
    counts[source_index] = 7
    streams = fixture([(body + text, False)], counts=counts)
    put(streams, pair, plc([0, 3, 7], [0, 0]))
    d = parse(monkeypatch, streams)
    a, = d.auxiliary_stories
    assert (a.source_start, a.source_end) == (0, 3)
    assert d.textboxes == '😀'


def header_fixture(slots, *, sections=1, final=0xffffffff):
    main = '\x0c' * (sections - 1) + 'B\r'
    header = ''.join(slots) + '\r'
    streams = fixture([(main + header, True)],
                      counts=[len(main), 0, len(header), 0, 0, 0, 0])
    cps = [0]
    for slot in slots:
        cps.append(cps[-1] + len(slot))
    put(streams, 11, b''.join(u32(n) for n in [*cps, final]))
    # Each explicit section break begins the following section.
    put(streams, 6, b''.join(u32(n) for n in [*range(sections), len(main)]) + b'\0' * (12 * sections))
    return streams


def test_headers_keep_sections_variants_and_inheritance_without_copying(monkeypatch):
    slots = [''] * 18
    slots[7] = 'Shared\r\r'     # First section odd header.
    slots[9] = 'Footer\r\r'     # First section odd footer.
    slots[17] = '\r\r'         # Explicit empty second-section first footer.
    streams = header_fixture(slots, sections=2)
    d = _validate_result(parse(monkeypatch, streams), Limits())
    assert len(d.auxiliary_stories) == 18
    items = {a.ordinal: a for a in d.auxiliary_stories}
    assert (items[8].kind, items[8].variant, items[8].section) == ('header', 'odd', 1)
    assert items[14].inherited_from == 8
    assert items[16].inherited_from == 10
    assert items[18].inherited_from is None
    assert items[18].source_end - items[18].source_start == 1
    assert d.story_blocks['headers_footers'][items[18].block_start:items[18].block_end] == [Paragraph('')]
    assert all(a.source == 'header' for a in items.values())
    assert d.headers_footers.count('Shared') == 1
    # Existing pooled text remains exactly the same without ownership metadata.
    mutate(streams, 'WordDocument', 154 + 11 * 8, b'\0' * 8)
    fallback = parse(monkeypatch, streams)
    assert d.headers_footers == fallback.headers_footers
    assert d.text == fallback.text
    assert not fallback.auxiliary_stories


def test_separator_guard_is_not_part_of_body_and_final_plc_cp_is_ignored(monkeypatch):
    slots = [''] * 12
    slots[0], slots[3], slots[7] = 'Foot\r', 'End\r', 'Header\r\r'
    d = _validate_result(parse(monkeypatch, header_fixture(slots)), Limits())
    a, b = d.auxiliary_stories[0], d.auxiliary_stories[3]
    assert (a.kind, a.variant, a.section, a.source_start, a.source_end) == ('footnote_separator', 'separator', None, 0, 4)
    assert (b.kind, b.source_start, b.source_end) == ('endnote_separator', 5, 8)
    assert d.story_blocks['headers_footers'][a.block_start:a.block_end] == [Paragraph('Foot')]
    assert d.story_blocks['headers_footers'][b.block_start:b.block_end] == [Paragraph('End')]
    assert 'doc_a_doc_story_has_no_final_paragraph_mark_trailing' not in [x.code for x in d.diagnostics]


def test_no_section_evidence_means_no_guessed_header_identity(monkeypatch):
    slots = [''] * 12
    slots[7] = 'Header\r\r'
    streams = header_fixture(slots)
    mutate(streams, 'WordDocument', 154 + 6 * 8, b'\0' * 8)
    d = parse(monkeypatch, streams)
    assert 'Header' in d.headers_footers
    assert not d.auxiliary_stories
    assert 'doc_header_section_count_missing' in [x.code for x in d.diagnostics]


def test_real_authored_header_has_proven_odd_variant():
    from pathlib import Path
    from legacy_office_parser import parse as public_parse
    d = public_parse(Path(__file__).parent / 'fixtures/doc_headings/authored.doc')
    headings = [a for a in d.auxiliary_stories if a.kind == 'header' and a.source_start != a.source_end]
    assert [(a.variant, a.ordinal) for a in headings] == [('odd', 8), ('first', 11)]
    assert d.story_blocks['headers_footers'][headings[1].block_start:headings[1].block_end] == [Paragraph('')]
    a = headings[0]
    assert (a.section, a.variant, a.ordinal) == (1, 'odd', 8)
    assert d.story_blocks[a.story][a.block_start:a.block_end] == [Paragraph('Header heading specimen', 2)]


def test_header_plc_with_absent_header_subdocument_is_rejected(monkeypatch):
    from legacy_office_parser import InvalidDocumentError
    streams = fixture([('Body\r', True)])
    put(streams, 11, b'\0' * 56)
    with pytest.raises(InvalidDocumentError):
        parse(monkeypatch, streams)


def test_field_state_does_not_leak_between_header_variants(monkeypatch):
    slots = [''] * 12
    slots[6] = '\x13INSTRUCTION\r\r'
    slots[7] = 'VISIBLE\r\r'
    d = parse(monkeypatch, header_fixture(slots))
    even, odd = d.auxiliary_stories[6:8]
    assert d.story_blocks['headers_footers'][even.block_start:even.block_end] == [Paragraph('')]
    assert d.story_blocks['headers_footers'][odd.block_start:odd.block_end] == [Paragraph('VISIBLE')]
    assert 'INSTRUCTION' not in d.text
