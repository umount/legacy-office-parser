"""Source Plcfld closure only; stored text and comment ownership stay intact."""
import struct

import pytest

from legacy_office_parser import Limits, LimitExceededError
from legacy_office_parser._doc_fields import field_selection_index
from legacy_office_parser.doc import _Budget
from test_doc import IN, ROW, definition, parse, sprm
from test_doc_comment_selections import ranged, selection
from test_doc_fidelity import append_table_part, add_chpx


def delimiters(text):
    raw = text.encode('utf-16le')
    return [(i // 2, struct.unpack_from('<H', raw, i)[0])
            for i in range(0, len(raw), 2)
            if struct.unpack_from('<H', raw, i)[0] in (19, 20, 21)]


def plc(text):
    ds = delimiters(text)
    return (struct.pack('<' + 'I' * (len(ds) + 1),
                        *(cp for cp, _ in ds), len(text.encode('utf-16le')) // 2 + 1)
            + b''.join(bytes((kind, 0)) for _, kind in ds))


@pytest.mark.parametrize('begin,end,accepted', [
    (0, 1, True),       # Same paragraph before the field.
    (1, 9, True),       # Complete field, including all three delimiters.
    (0, 10, True),      # Complete field and ordinary surrounding text.
    (1, 8, False),      # Missing end delimiter.
    (2, 9, False),      # Missing begin delimiter.
    (7, 8, True),       # Stored result only; contains no delimiter.
    (6, 8, False),      # Separator without the rest of its field.
])
def test_verified_field_selection_and_unchanged_visibility(monkeypatch, begin, end, accepted):
    main = 'P\x13CODE\x14R\x15Q\x05\r'
    data = ranged(main, begin, end)
    append_table_part(data, 16, plc(main))
    doc = parse(monkeypatch, data)
    assert selection(doc) == ((begin, end) if accepted else (None, None))
    assert doc.comment_text == 'Body'
    assert 'CODE' not in doc.text and 'PRQ' in doc.text
    assert doc.comments[0].source_cp == 10
    assert doc.comments[0].visibility == []


@pytest.mark.parametrize('metadata', [b'', b'bad', 'wrong-cp'])
def test_unverified_fields_only_block_ranges_touching_delimiters(monkeypatch, metadata):
    main = 'P\x13CODE\x14R\x15Q\x05\r'
    raw = plc(main) if metadata == 'wrong-cp' else metadata
    if metadata == 'wrong-cp':
        raw = struct.pack('<I', 0) + raw[4:]
    for begin, end, accepted in [(0, 1, True), (9, 10, True), (1, 9, False)]:
        data = ranged(main, begin, end)
        if raw:
            append_table_part(data, 16, raw)
        doc = parse(monkeypatch, data)
        assert selection(doc) == ((begin, end) if accepted else (None, None))
        assert doc.comment_text == 'Body'


def test_table_fallback_requires_field_closure(monkeypatch):
    main = '\x13C\x14R\x15\7\7Q\x05\r'
    props = [IN, ROW + definition([0]), b'', b'', b'']
    for begin, end, accepted in [(0, 7, True), (0, 3, False), (3, 4, True)]:
        data = ranged(main, begin, end, props=props)
        append_table_part(data, 16, plc(main))
        doc = parse(monkeypatch, data)
        assert selection(doc) == ((begin, end) if accepted else (None, None))
        assert doc.comment_text == 'Body'


def test_nested_fields_use_each_delimiters_owner_and_reusable_index():
    main = '\x13O\x14A\x13I\x14B\x15C\x15'
    ds = delimiters(main)
    index = field_selection_index(ds, plc(main), len(main), Limits(), special=lambda cp: True)
    ds.clear()
    for _ in range(100):
        assert index.contains(0, 11) and index.contains(4, 9)
        assert index.contains(3, 10)  # Whole inner field, no outer delimiter.
        assert not index.contains(2, 10)  # Outer separator requires outer closure.
        assert not index.contains(4, 8)


@pytest.mark.parametrize('main', ['\x13A\x14B\x14C\x15', '\x13A', 'A\x15'])
def test_malformed_field_nesting_remains_unproven(main):
    index = field_selection_index(delimiters(main), plc(main), len(main), Limits(), special=lambda cp: True)
    assert not index.contains(0, len(main))
    at = main.index('A')
    assert index.contains(at, at + 1)


def test_field_index_limits_precharge_and_nesting():
    main = '\x13A\x13B\x15\x15'
    ds = delimiters(main)
    with pytest.raises(LimitExceededError, match='depth'):
        field_selection_index(ds, plc(main), len(main), Limits(max_depth=1), special=lambda cp: True)
    class Unreadable(list):
        def __iter__(self):
            pytest.fail('must charge before traversal')
    with pytest.raises(LimitExceededError, match='record'):
        field_selection_index(Unreadable(ds), b'', len(main), Limits(max_records=32))
    budget = _Budget(Limits(max_records=33))
    budget.record(1)
    with pytest.raises(LimitExceededError, match='record'):
        field_selection_index(ds, plc(main), len(main), budget.limits, record=budget.record)


def test_fld_reserved_bits_ignored_and_sentinel_order_checked(monkeypatch):
    main = 'P\x13CODE\x14R\x15Q\x05\r'
    raw = bytearray(plc(main))
    n = len(delimiters(main))
    for i in range(n):
        raw[4 * (n + 1) + 2 * i] |= 0xe0
    data = ranged(main, 1, 9)
    append_table_part(data, 16, raw)
    assert selection(parse(monkeypatch, data)) == (1, 9)
    struct.pack_into('<I', raw, 4 * n, 8)  # Equal to the last real delimiter CP.
    data = ranged(main, 1, 9)
    append_table_part(data, 16, raw)
    assert selection(parse(monkeypatch, data)) == (None, None)


@pytest.mark.parametrize('operand', [0, 128])
def test_field_markers_require_proven_cfspec(monkeypatch, operand):
    main = 'P\x13CODE\x14R\x15Q\x05\r'
    data = ranged(main, 1, 9)
    append_table_part(data, 16, plc(main))
    # Only the begin marker has false/style-relative CFSpec; comment marker and
    # body properties retain their existing known-special visibility.
    add_chpx(data, [1024, 1026, 1028, 1024 + 2 * (len(main) + 8)],
             [sprm(0x0855, 1), sprm(0x0855, operand), sprm(0x0855, 1)])
    doc = parse(monkeypatch, data)
    assert selection(doc) == (None, None)
    assert doc.comment_text == 'Body' and doc.comments[0].visibility == []


def test_field_without_separator_preserves_utf16_cps(monkeypatch):
    main = '😀\x13DATE\x15Q\x05\r'
    data = ranged(main, 2, 8)
    append_table_part(data, 16, plc(main))
    doc = parse(monkeypatch, data)
    assert selection(doc) == (2, 8)
    assert doc.comments[0].source_cp == 9
    assert 'DATE' not in doc.text and '😀Q' in doc.text
    assert doc.comment_text == 'Body'
