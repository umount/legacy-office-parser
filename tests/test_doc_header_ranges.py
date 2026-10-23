"""Literal source-slot expectations, independent of the production DOC reader."""
from pathlib import Path
import struct

import olefile
import pytest

from legacy_office_parser._doc_headers import decode_header_ranges, decode_section_count
from legacy_office_parser.errors import InvalidDocumentError, LimitExceededError
from legacy_office_parser.limits import Limits


def plc(cps, final=0xffffffff):
    return struct.pack('<' + 'I' * (len(cps) + 1), *cps, final)


def sed(cps):
    return struct.pack('<' + 'I' * len(cps), *cps) + bytes(12 * (len(cps) - 1))


def specimen():
    # Six separators, then all six section slots, then an empty second section.
    texts = ['a\r', 'b\r', 'c\r', 'd\r', 'e\r', 'f\r',
             'EVEN H\r\r', 'ODD H\r\r', 'EVEN F\r\r', 'ODD F\r\r', 'FIRST H\r\r', 'FIRST F\r\r'] + [''] * 6
    cps = [0]
    for text in texts:
        cps.append(cps[-1] + len(text))
    return plc(cps), (''.join(texts) + '\r').encode('utf-16le')


def test_literal_identities_ranges_empty_slots_and_guards():
    raw, story = specimen()
    records = decode_header_ranges(raw, story, Limits(), 2)
    assert [(r.kind, r.variant, r.section) for r in records[:6]] == [
        ('footnote_separator', 'separator', None),
        ('footnote_separator', 'continuation_separator', None),
        ('footnote_separator', 'continuation_notice', None),
        ('endnote_separator', 'separator', None),
        ('endnote_separator', 'continuation_separator', None),
        ('endnote_separator', 'continuation_notice', None)]
    assert [(r.kind, r.variant, r.section) for r in records[6:12]] == [
        ('header', 'even', 1), ('header', 'odd', 1), ('footer', 'even', 1),
        ('footer', 'odd', 1), ('header', 'first', 1), ('footer', 'first', 1)]
    assert [(r.start, r.end) for r in records[:8]] == [
        (0, 1), (2, 3), (4, 5), (6, 7), (8, 9), (10, 11), (12, 19), (20, 26)]
    assert [r.ordinal for r in records] == list(range(1, 19))
    assert all(r.start == r.end and r.section == 2 for r in records[12:])
    assert story[records[6].start * 2:records[6].end * 2].decode('utf-16le') == 'EVEN H\r'
    assert not hasattr(records[12], 'inherited_from')  # Caller resolves inheritance.


@pytest.mark.parametrize('final', [0, 1, 0x7fffffff, 0xffffffff])
def test_undefined_final_cp_is_ignored(final):
    raw, story = specimen()
    assert len(decode_header_ranges(raw[:-4] + struct.pack('<I', final), story, Limits(), 2)) == 18


def test_utf16_cps_and_guard_only_separator():
    story = '\r😀\r\r\r'.encode('utf-16le')
    cps = [0, 1, 1, 1, 1, 1, 1, 5, 5, 5, 5, 5, 5]
    records = decode_header_ranges(memoryview(plc(cps)), memoryview(story), Limits(), 1)
    assert (records[0].start, records[0].end) == (0, 0)
    assert (records[6].start, records[6].end) == (1, 4)
    assert story[2:8].decode('utf-16le') == '😀\r'


@pytest.mark.parametrize('section_count', [None, 2])
def test_missing_plc_returns_coded_fallback(section_count):
    warnings = []
    assert decode_header_ranges(b'', b'x\0', Limits(), section_count, warn=warnings.append) is None
    assert [w.code for w in warnings] == ['doc_header_plc_missing']
    assert decode_header_ranges(b'', b'', Limits(), section_count, warn=warnings.append) == []
    assert len(warnings) == 1


def test_missing_section_count_validates_then_warns():
    raw, story = specimen()
    warnings = []
    assert decode_header_ranges(raw, story, Limits(), warn=warnings.append) is None
    assert [w.code for w in warnings] == ['doc_header_section_count_missing']
    with pytest.raises(InvalidDocumentError):
        decode_header_ranges(raw, story.replace(b'\r\0', b'x\0'), Limits(), warn=warnings.append)
    assert len(warnings) == 1


@pytest.mark.parametrize('bad', [b'x', bytes(4), bytes(8), bytes(36),
    plc([1] * 13), plc([0] * 12 + [999]), plc([0, 2, 1] + [2] * 10),
    plc([0] * 12 + [0x80000000]), plc([0] * 13)])
def test_malformed_present_plc_never_falls_back(bad):
    with pytest.raises(InvalidDocumentError):
        decode_header_ranges(bad, b'\r\0' * 3, Limits())


@pytest.mark.parametrize('count', [0, 1, 3, -1, True, 1.5])
def test_section_mismatch_or_invalid_count(count):
    raw, story = specimen()
    with pytest.raises(InvalidDocumentError):
        decode_header_ranges(raw, story, Limits(), count)


@pytest.mark.parametrize('text', ['x', '\r', 'x\r', '\rx'])
def test_header_requires_content_paragraph_and_guard(text):
    cps = [0] * 7 + [len(text)] * 6
    with pytest.raises(InvalidDocumentError):
        decode_header_ranges(plc(cps), (text + '\r').encode('utf-16le'), Limits(), 1)


def test_odd_byte_count_and_zero_story_with_present_plc_rejected():
    raw, _ = specimen()
    for story in (b'x', b''):
        with pytest.raises(InvalidDocumentError):
            decode_header_ranges(raw, story, Limits(), 2)


@pytest.mark.parametrize('limits', [Limits(max_records=19), Limits(max_stream_bytes=79), Limits(max_text_chars=3)])
def test_bounds_before_allocation(limits):
    raw, story = specimen()
    with pytest.raises(LimitExceededError):
        decode_header_ranges(raw, story, limits, 2)


@pytest.mark.parametrize('missing_plc', [False, True])
def test_decoded_story_uses_cp_limit_not_stream_byte_limit(missing_plc):
    # ASCII compressed source expands to twice as many bytes in UTF-16.
    source = 'A' * 60 + '\r\r\r'
    story = source.encode('utf-16le')
    raw = b'' if missing_plc else plc([0] * 7 + [62] * 6)
    assert len(raw) <= len(source.encode('ascii')) == 63 < len(story)
    limits = Limits(max_stream_bytes=63, max_text_chars=63)
    warnings = []
    records = decode_header_ranges(raw, story, limits, 1, warn=warnings.append)
    if missing_plc:
        assert records is None
        assert [w.code for w in warnings] == ['doc_header_plc_missing']
    else:
        assert len(records) == 12
        assert (records[6].start, records[6].end) == (0, 61)
        assert story[:122].decode('utf-16le') == 'A' * 60 + '\r'
        assert warnings == []
    with pytest.raises(LimitExceededError):
        decode_header_ranges(raw, story, Limits(max_stream_bytes=63, max_text_chars=62), 1)


def test_aggregate_callback_including_sentinels():
    raw, story = specimen()
    charges = []
    decode_header_ranges(raw, story, Limits(), 2, record=charges.append)
    decode_section_count(sed([0, 10, 20]), 20, Limits(), record=charges.append)
    assert charges == [20, 5]

    def exhausted(count):
        raise LimitExceededError('aggregate exhausted')

    with pytest.raises(LimitExceededError, match='aggregate exhausted'):
        decode_header_ranges(raw, story, Limits(), 2, record=exhausted)


@pytest.mark.parametrize('cps,main,expected', [([0, 10], 10, 1), ([0, 10, 30], 20, 2), ([0], 0, 0)])
def test_section_count_structure(cps, main, expected):
    assert decode_section_count(sed(cps), main, Limits()) == expected
    assert decode_section_count(b'', main, Limits()) is None


@pytest.mark.parametrize('raw,main', [(b'x', 1), (sed([0]), 1), (sed([1, 10]), 10),
    (sed([0, 0]), 0), (sed([0, 10, 9]), 10), (sed([0, 10, 20]), 10),
    (sed([0, 9]), 10), (sed([0, 0x80000000]), 10)])
def test_invalid_section_plc(raw, main):
    with pytest.raises(InvalidDocumentError):
        decode_section_count(raw, main, Limits())


@pytest.mark.parametrize('limits', [Limits(max_records=2), Limits(max_stream_bytes=19), Limits(max_text_chars=2)])
def test_section_bounds(limits):
    with pytest.raises(LimitExceededError):
        decode_section_count(sed([0, 10]), 10, limits)


def original_fixture():
    """Independent, fixture-only FIB/CLX inspection; no production DOC decoder."""
    path = Path(__file__).parent / 'fixtures/doc_headings/authored.doc'
    with olefile.OleFileIO(path) as compound:
        word = compound.openstream('WordDocument').read()
        table = compound.openstream('1Table' if struct.unpack_from('<H', word, 10)[0] & 0x200 else '0Table').read()
    counts = [struct.unpack_from('<I', word, 64 + i * 4)[0] for i in (3, 4, 5)]

    def part(index):
        start, size = struct.unpack_from('<II', word, 154 + 8 * index)
        return table[start:start + size]

    clx = part(33)
    at = 0
    while clx[at] == 1:
        at += 3 + struct.unpack_from('<H', clx, at + 1)[0]
    assert clx[at] == 2
    size = struct.unpack_from('<I', clx, at + 1)[0]
    pieces = clx[at + 5:at + 5 + size]
    n = (size - 4) // 12
    cps = struct.unpack_from('<' + 'I' * (n + 1), pieces)
    units = bytearray()
    for i in range(n):
        fc = struct.unpack_from('<I', pieces, 4 * (n + 1) + 8 * i + 2)[0]
        compressed = bool(fc & 0x40000000)
        offset = (fc & 0x3fffffff) // (2 if compressed else 1)
        raw = word[offset:offset + (cps[i + 1] - cps[i]) * (1 if compressed else 2)]
        if compressed:
            assert all(c < 128 for c in raw)
            raw = raw.decode('ascii').encode('utf-16le')
        units.extend(raw)
    start = counts[0] + counts[1]
    return counts, part(6), part(11), bytes(units[start * 2:(start + counts[2]) * 2])


def test_original_lo_doc_literal_readback():
    counts, sections, headers, story = original_fixture()
    assert counts == [203, 0, 28]
    assert struct.unpack('<14I', headers) == (0, 0, 0, 0, 0, 0, 0, 0, 25, 25, 25, 27, 27, 29)
    section_count = decode_section_count(sections, 203, Limits())
    assert section_count == 1
    records = decode_header_ranges(headers, story, Limits(), section_count)
    assert len(records) == 12
    assert [(r.ordinal, r.start, r.end, r.section, r.kind, r.variant)
            for r in records if r.start != r.end] == [
        (8, 0, 24, 1, 'header', 'odd'), (11, 25, 26, 1, 'header', 'first')]
    assert story[:48].decode('utf-16le') == 'Header heading specimen\r'
    assert story[50:52] == b'\r\0'
    assert [r.ordinal for r in records if r.start == r.end] == [1, 2, 3, 4, 5, 6, 7, 9, 10, 12]


@pytest.mark.parametrize('cp_count', [2, 8, 13, 14, 20])
@pytest.mark.parametrize('sections', [None, 0, 1, 2])
@pytest.mark.parametrize('final', [0, 0xffffffff])
def test_empty_story_degenerate_plc_retains_no_identities(cp_count, sections, final):
    raw = bytes(4 * (cp_count - 1)) + struct.pack('<I', final)
    warnings, charges = [], []
    assert decode_header_ranges(memoryview(raw), b'', Limits(), sections,
                                record=charges.append, warn=warnings.append) == []
    assert charges == [cp_count]
    assert [w.code for w in warnings] == ['doc_empty_header_plc_ignored']


@pytest.mark.parametrize('index', range(12))
def test_empty_story_nonzero_defined_cp_still_rejected(index):
    raw = bytearray(52)
    struct.pack_into('<I', raw, index * 4, 1)
    warnings = []
    with pytest.raises(InvalidDocumentError):
        decode_header_ranges(raw, b'', Limits(), 1, warn=warnings.append)
    assert warnings == []


@pytest.mark.parametrize('raw', [b'x', bytes(4), bytes(51), bytes(53)])
def test_empty_story_malformed_plc_size_still_rejected(raw):
    with pytest.raises(InvalidDocumentError):
        decode_header_ranges(raw, b'', Limits(), 1)


def test_empty_story_degenerate_plc_keeps_preflight_limits():
    warnings, charges = [], []
    for limits in (Limits(max_stream_bytes=51), Limits(max_records=12)):
        with pytest.raises(LimitExceededError):
            decode_header_ranges(bytes(52), b'', limits, 1, warn=warnings.append)
    def exhausted(count):
        charges.append(count)
        raise LimitExceededError('aggregate exhausted')
    with pytest.raises(LimitExceededError, match='aggregate exhausted'):
        decode_header_ranges(bytes(52), b'', Limits(), 1, record=exhausted, warn=warnings.append)
    assert charges == [13] and warnings == []
