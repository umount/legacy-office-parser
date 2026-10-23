"""Source DOP/SEPX settings exposed by the actual DOC reader, without layout."""
from pathlib import Path
import struct

import pytest

from legacy_office_parser import Limits, normalize_text
from legacy_office_parser._validation import _validate_result
from legacy_office_parser.errors import InvalidDocumentError, LimitExceededError
from test_doc import mutate, parse, sprm, u16, u32
from test_doc_auxiliary_stories import header_fixture, put


def source_settings(streams, groups, facing=False):
    # Each section has independently stored properties; None is missing SEPX.
    count = len(groups)
    entries = []
    for group in groups:
        offset = 0xffffffff if group is None else len(streams['WordDocument'])
        if group is not None:
            streams['WordDocument'] += u16(len(group)) + group
        entries.append(b'\0\0' + u32(offset) + b'\0' * 6)
    mutate(streams, 'WordDocument', 64, u32(len(streams['WordDocument'])))
    put(streams, 6, b''.join(u32(n) for n in [*range(count), count + 2]) + b''.join(entries))
    if facing is not None:
        put(streams, 31, bytes([int(facing)]) + bytes(83))
    return streams


def headers(document):
    return [a for a in document.auxiliary_stories if a.kind in ('header', 'footer')]


def test_default_slots_and_disabled_stored_variants_are_serialized(monkeypatch):
    streams = source_settings(header_fixture([''] * 6 + [
        'EVEN H\r\r', 'DEFAULT H\r\r', 'EVEN F\r\r', 'DEFAULT F\r\r',
        'FIRST H\r\r', 'FIRST F\r\r']), [b''])
    d = _validate_result(parse(monkeypatch, streams), Limits())
    slots = headers(d)
    assert [(a.variant, a.selection_role, a.active) for a in slots] == [
        ('even', 'even', False), ('odd', 'default', True),
        ('even', 'even', False), ('odd', 'default', True),
        ('first', 'first', False), ('first', 'first', False)]
    assert all(a.different_first_page is False and a.different_even_odd is False for a in slots)
    # Inactive source text is retained, not mistaken for a rendered-page result.
    assert 'FIRST H' in d.headers_footers and 'EVEN F' in d.headers_footers
    serialized = d.to_dict()['auxiliary_stories']
    assert serialized[7]['selection_role'] == 'default'
    assert serialized[10]['active'] is False
    assert normalize_text(d).auxiliary_stories == d.auxiliary_stories
    assert all(a.active is None and a.selection_role is None for a in d.auxiliary_stories[:6])


def test_section_settings_do_not_inherit_but_source_bodies_do(monkeypatch):
    slots = [''] * 24
    slots[6:12] = ['EH\r\r', 'OH\r\r', 'EF\r\r', 'OF\r\r', 'FH\r\r', 'FF\r\r']
    slots[16] = '\r\r'  # Explicit blank first header in section 2.
    streams = source_settings(header_fixture(slots, sections=3), [
        sprm(0x300A, 1), b'', sprm(0x300A, 1)], facing=True)
    d = _validate_result(parse(monkeypatch, streams), Limits())
    items = {a.ordinal: a for a in headers(d)}
    assert [items[i].different_first_page for i in (11, 17, 23)] == [True, False, True]
    assert [items[i].active for i in (11, 17, 23)] == [True, False, True]
    assert items[23].inherited_from == 17  # The disabled but stored blank survives.
    assert items[17].source_end - items[17].source_start == 1
    assert items[24].inherited_from == 12  # Transitive first-footer inheritance.
    assert items[19].inherited_from == 7 and items[19].active is True
    assert items[20].selection_role == 'odd' and items[20].inherited_from == 8
    assert d.headers_footers.count('FH') == 1


def test_enabled_absent_first_and_even_are_blank_not_default_fallback(monkeypatch):
    slots = [''] * 12
    slots[7], slots[9] = 'DEFAULT H\r\r', 'DEFAULT F\r\r'
    streams = source_settings(header_fixture(slots), [sprm(0x300A, 1)], facing=True)
    d = parse(monkeypatch, streams)
    for a in headers(d):
        assert a.active is True
        if a.variant in ('even', 'first'):
            assert a.source_start == a.source_end
            assert a.inherited_from is None


def test_unknown_settings_are_not_false_or_default(monkeypatch):
    streams = source_settings(header_fixture([''] * 7 + ['H\r\r'] + [''] * 4),
                              [None], facing=None)
    d = parse(monkeypatch, streams)
    even, odd, _, _, first, _ = headers(d)
    assert even.active is None and first.active is None
    assert odd.active is True and odd.selection_role is None
    assert all(a.different_first_page is None and a.different_even_odd is None
               for a in headers(d))
    assert d.headers_footers.strip() == 'H'
    serialized = d.to_dict()['auxiliary_stories'][7]
    assert 'selection_role' not in serialized
    assert 'different_first_page' not in serialized
    assert 'different_even_odd' not in serialized
    assert serialized['active'] is True


def test_real_authored_doc_settings_are_read_from_source():
    from legacy_office_parser import parse as public_parse
    d = public_parse(Path(__file__).parent / 'fixtures/doc_headings/authored.doc')
    even, odd, _, _, first, _ = headers(d)
    assert odd.selection_role == 'default' and odd.active is True
    assert even.active is False and first.active is False
    assert first.different_first_page is False


def test_unrelated_operands_and_last_title_setting_do_not_guess_pagination(monkeypatch):
    # Includes a continuous break and page-number restart. Neither determines
    # whether a section occupies a physical first/even page.
    group = (sprm(0x300A, 1) + sprm(0x3009, 0) + sprm(0x3011, 1) +
             sprm(0x501C, u16(2)) + sprm(0xD202, b'\3\x0a\x30\1') + sprm(0x300A, 0))
    streams = source_settings(header_fixture([''] * 7 + ['H\r\r'] + [''] * 4), [group])
    d = parse(monkeypatch, streams)
    assert headers(d)[4].active is False
    assert headers(d)[1].selection_role == 'default'


@pytest.mark.parametrize('group', [b'\x0a\x30', sprm(0x300A, 2),
    sprm(0x300A, 1) + b'\0', b'\x02\xd2\x05x'])
def test_malformed_sepx_preserves_text_and_only_loses_affected_settings(monkeypatch, group):
    slots = [''] * 18
    slots[7] = 'RETAINED\r\r'
    streams = source_settings(header_fixture(slots, sections=2), [group, b''], facing=True)
    d = _validate_result(parse(monkeypatch, streams), Limits())
    assert d.headers_footers.strip() == 'RETAINED'
    assert headers(d)[4].active is None
    assert headers(d)[0].active is True
    assert headers(d)[10].active is False
    assert [w.code for w in d.diagnostics].count('doc_header_settings_unresolved') == 1


@pytest.mark.parametrize('damage', ['sepx_offset', 'sepx_length', 'dop_short', 'dop_offset'])
def test_optional_setting_bounds_retain_text(monkeypatch, damage):
    streams = source_settings(header_fixture([''] * 7 + ['H\r\r'] + [''] * 4), [b''])
    word = bytearray(streams['WordDocument'])
    fc, _ = struct.unpack_from('<II', word, 154 + 6 * 8)
    table = bytearray(streams['1Table'])
    if damage == 'sepx_offset':
        struct.pack_into('<I', table, fc + 8 + 2, len(word) + 1)
    elif damage == 'sepx_length':
        offset = struct.unpack_from('<I', table, fc + 8 + 2)[0]
        struct.pack_into('<h', word, offset, -1)
    elif damage == 'dop_offset':
        struct.pack_into('<II', word, 154 + 31 * 8, len(table) + 1, 84)
    streams['WordDocument'], streams['1Table'] = bytes(word), bytes(table)
    if damage == 'dop_short':
        put(streams, 31, b'\1')
    d = _validate_result(parse(monkeypatch, streams), Limits())
    assert d.headers_footers.strip() == 'H'
    if damage.startswith('sepx'):
        assert headers(d)[4].active is None
        assert headers(d)[0].active is False
    else:
        assert headers(d)[0].active is None
        assert headers(d)[1].selection_role is None
        assert headers(d)[4].active is False
    assert 'doc_header_settings_unresolved' in [w.code for w in d.diagnostics]


def test_sepx_traversal_charges_existing_aggregate_budget(monkeypatch):
    simple = source_settings(header_fixture([''] * 12), [b''])
    parse(monkeypatch, simple, Limits(max_records=150))
    streams = source_settings(header_fixture([''] * 12), [sprm(0x300A, 0) * 60])
    with pytest.raises(LimitExceededError, match='record limit'):
        parse(monkeypatch, streams, Limits(max_records=150))


@pytest.mark.parametrize('changes', [
    {'active': 1}, {'different_first_page': 0}, {'different_even_odd': 'yes'},
    {'selection_role': 'first'}, {'active': False},
])
def test_invalid_header_applicability_rejected(monkeypatch, changes):
    streams = source_settings(header_fixture([''] * 12), [b''])
    d = parse(monkeypatch, streams)
    item = headers(d)[1]
    for name, value in changes.items():
        setattr(item, name, value)
    with pytest.raises(InvalidDocumentError):
        _validate_result(d, Limits())


def test_selection_metadata_cannot_disagree_with_section_or_attach_to_separator(monkeypatch):
    streams = source_settings(header_fixture([''] * 12), [b''])
    d = parse(monkeypatch, streams)
    headers(d)[1].different_first_page = True
    with pytest.raises(InvalidDocumentError, match='section settings'):
        _validate_result(d, Limits())
    d = parse(monkeypatch, streams)
    d.auxiliary_stories[0].active = True
    with pytest.raises(InvalidDocumentError, match='non-header'):
        _validate_result(d, Limits())
