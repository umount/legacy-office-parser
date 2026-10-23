"""Literal source/PLC expectations for ordinary text plus complete outer rows."""
import struct

import pytest

from legacy_office_parser import Limits, LimitExceededError
from legacy_office_parser._doc_comments import comment_selection_index
from legacy_office_parser.doc import _Budget
from test_doc import IN, ROW, definition, parse
from test_doc_comment_selections import ranged, selection
from test_doc_comment_complex_selections import source
from test_doc_nested import cell, paragraph, row


MAIN = 'Intro\rA\7B\7\7Outro\x05\r'
PROPS = [b'', IN, IN, ROW + definition([0, 0]), b'', b'', b'']


@pytest.mark.parametrize('begin,end,literal', [
    (0, 16, 'Intro\rA\7B\7\7Outro'),
    (0, 11, 'Intro\rA\7B\7\7'), (6, 16, 'A\7B\7\7Outro'),
    (2, 13, 'tro\rA\7B\7\7Ou'), (5, 12, '\rA\7B\7\7O'),
    (0, 18, MAIN), (6, 11, 'A\7B\7\7'),
])
def test_literal_transport_and_raw_bookmark_endpoints(monkeypatch, begin, end, literal):
    streams = ranged(MAIN, begin, end, props=PROPS)
    # Read the original FIB pairs and FBKF.ibkl, independently of runtime decode.
    def part(index):
        offset, size = struct.unpack_from('<II', streams['WordDocument'], 154 + 8 * index)
        return streams['1Table'][offset:offset + size]
    starts, ends = part(42), part(43)
    raw_begin, sentinel, ibkl, bkc = struct.unpack('<IIHH', starts)
    raw_end = struct.unpack_from('<I', ends, ibkl * 4)[0]
    assert (raw_begin, raw_end, sentinel, ibkl, bkc) == (begin, end, 19, 0, 0)
    assert MAIN.encode('utf-16le')[begin*2:end*2].decode('utf-16le') == literal
    d = parse(monkeypatch, streams)
    assert selection(d) == (begin, end)
    assert d.comments[0].source_cp == 16
    assert d.comments[0].anchor_path == ['blocks', 2]
    assert d.comment_text == 'Body' and d.text.count('Body') == 1
    assert not any('selection validity' in w for w in d.warnings)
    assert d.to_dict()['comments'][0]['selection_end'] == end


@pytest.mark.parametrize('begin,end', [(0, 7), (0, 8), (0, 9), (0, 10),
                                      (7, 16), (8, 16), (9, 16), (10, 16)])
def test_partial_row_limits_are_validated_without_widening(monkeypatch, begin, end):
    d = parse(monkeypatch, ranged(MAIN, begin, end, props=PROPS))
    assert selection(d) == ((begin, end) if end in (7, 8) else (None, None))
    assert d.comment_text == 'Body'


def mixed(text, paragraphs, **kwargs):
    return comment_selection_index(text, paragraphs, kwargs.pop('sections', set()),
        kwargs.pop('known', lambda cp: True), kwargs.pop('limits', Limits()),
        **kwargs)


@pytest.mark.parametrize('fault', ['unknown-before', 'unknown-after', 'unsafe-before',
    'unsafe-after', 'section-before', 'section-after', 'field-outside', 'unclosed',
    'wrong-grid', 'unknown-cell', 'bad-mark', 'gap'])
def test_unsafe_atom_breaks_mixed_proof(fault):
    text, ps = source(('P', 0, 'para'), ('A', 1, 'cell'), ('', 1, 'row'), ('Q', 0, 'para'))
    kwargs = {}
    if fault == 'unknown-before':
        kwargs['known'] = lambda cp: cp != 1
    elif fault == 'unknown-after':
        kwargs['known'] = lambda cp: cp != 6
    elif fault in ('unsafe-before', 'unsafe-after'):
        raw = bytearray(text)
        raw[0 if fault.endswith('before') else 10:2 if fault.endswith('before') else 12] = b'\x01\0'
        text = bytes(raw)
    elif fault == 'section-before':
        kwargs['sections'] = {1}
    elif fault == 'section-after':
        kwargs['sections'] = {6}
    elif fault == 'field-outside':
        text, ps = source(('P', 0, 'para'), ('A', 1, 'cell'), ('', 1, 'row'), ('Q\x13', 0, 'para'))
    elif fault == 'unclosed':
        text, ps = source(('P', 0, 'para'), ('A', 1, 'para'), ('', 1, 'row'), ('Q', 0, 'para'))
    elif fault == 'wrong-grid':
        ps[2][4].edges = [100, 0]
    elif fault == 'unknown-cell':
        ps[1] = (*ps[1][:-1], False)
    elif fault == 'bad-mark':
        text = text[:8] + b'\r\0' + text[10:]
    elif fault == 'gap':
        ps[1] = (3, *ps[1][1:])
    assert not mixed(text, ps, **kwargs).contains(0, len(text)//2)


def test_two_complete_tables_separated_by_ordinary_text():
    text, ps = source(('A', 1, 'cell'), ('', 1, 'row'), ('P', 0, 'para'),
                      ('B', 1, 'cell'), ('', 1, 'row'), ('Q', 0, 'para'))
    index = mixed(text, ps)
    assert index.contains(0, 10)
    assert index.contains(0, 8)
    assert not index.contains(1, 10)
    assert not index.contains(0, 7)


def test_nested_rows_must_close_before_ordinary_suffix(monkeypatch):
    parts = [paragraph(0, 'Before'), paragraph(1, 'P'), cell(2, 'A'), row(2, (0,)),
             cell(1, 'Q'), row(1, (0,)), paragraph(0, 'After\x05')]
    main = ''.join(t for t, _ in parts)
    end = main.index('\x05')
    d = parse(monkeypatch, ranged(main, 0, end, props=[p for _, p in parts] + [b'', b'']))
    assert selection(d) == (0, end)


@pytest.mark.parametrize('begin,end,want', [(0, 8, True), (1, 8, False), (0, 7, False)])
def test_surrogate_boundaries_are_source_utf16(begin, end, want):
    text, ps = source(('😀', 0, 'para'), ('A', 1, 'cell'), ('', 1, 'row'), ('🚀', 0, 'para'))
    assert mixed(text, ps).contains(begin, end) is want


def test_metadata_precharge_and_no_query_rescanning():
    text, ps = source(('P', 0, 'para'), ('A', 1, 'cell'), ('', 1, 'row'), ('Q', 0, 'para'))
    charges = []
    index = mixed(text, ps, record=charges.append, limits=Limits(max_records=49))
    assert charges == [49]
    ps.clear()  # Queries must not revisit source paragraph records.
    for _ in range(1000):
        assert index.contains(0, 7)
        assert index.contains(2, 6)
    class Unreadable:
        def __len__(self):
            return 4
        def __iter__(self):
            pytest.fail('must fail before traversal')
    with pytest.raises(LimitExceededError):
        mixed(text, Unreadable(), limits=Limits(max_records=48))
    budget = _Budget(Limits(max_records=50))
    budget.record(10)
    with pytest.raises(LimitExceededError):
        mixed(text, Unreadable(), limits=budget.limits, record=budget.record)


def test_original_doc_readback_records_converter_range_loss():
    import importlib.util
    import json
    from pathlib import Path
    from legacy_office_parser import parse_doc

    root = Path(__file__).parent / 'fixtures/doc_comment_mixed'
    spec = importlib.util.spec_from_file_location('mixed_probe', root / 'inspect_fixture.py')
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    observed = probe.inspect()
    assert json.loads(json.dumps(observed)) == json.loads((root / 'evidence.json').read_text())
    assert observed['source_xml'][0]['selection'] == 'Intro\rA\rB\rOutro 🚀'
    assert observed['lo_readback_xml'][0]['selection'] is None
    assert observed['comments'][0]['tag'] == 0xffffffff
    assert all(observed['raw_parts_hex'][str(i)] == '' for i in (37, 42, 43))
    d = parse_doc(root / 'authored.doc')
    # The converter dropped the range before this parser saw the DOC. Never
    # reconstruct it from the authored XML, visible text, or reference anchor.
    assert selection(d) == (27, 27)
    assert d.comments[0].anchor_path == ['blocks', 2]
    assert d.comment_text == 'Review paragraph and table together.'
