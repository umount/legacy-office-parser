"""Ordinary main-story selections across explicit PLCSED-backed section marks."""
import struct

import pytest

from legacy_office_parser import InvalidDocumentError, LimitExceededError, Limits, normalize_text
from legacy_office_parser.doc import _Doc
from test_doc import IN, ROW, definition, mutate, parse
from test_doc_comment_selections import ranged, selection, algorithm_case
from test_doc_sections import with_sections


def streams(main, begin, end, sections, *, props=None):
    # Original UTF-16 transport: preserve the synthetic FKP's source offsets
    # while replacing intended CR placeholders with section FF characters.
    result = ranged(main.replace('\f', '\r'), begin, end, props=props)
    mutate(result, 'WordDocument', 1024, main.encode('utf-16le'))
    return with_sections(result, sections) if sections is not None else result


def raw_part(data, index):
    start, size = struct.unpack_from('<II', data['WordDocument'], 154 + 8 * index)
    return data['1Table'][start:start + size]


@pytest.mark.parametrize('begin,end', [(0, 1), (0, 2), (0, 3), (1, 2),
                                      (1, 3), (2, 3), (0, 5)])
def test_literal_raw_section_and_bookmark_endpoints(monkeypatch, begin, end):
    data = streams('A\fB\x05\r', begin, end, [0, 2, 5])
    # PLCSED and bookmark CPs are read directly, not through the selection proof.
    assert struct.unpack_from('<III', raw_part(data, 6)) == (0, 2, 5)
    start, sentinel, ibkl, bkc = struct.unpack('<IIHH', raw_part(data, 42))
    limit = struct.unpack_from('<I', raw_part(data, 43), 4 * ibkl)[0]
    assert (start, limit, sentinel, bkc) == (begin, end, 6, 0)
    d = parse(monkeypatch, data)
    assert selection(d) == (begin, end)
    c = d.comments[0]
    assert c.source_cp == 3 and c.anchor_path == ['blocks', 1]
    assert d.comment_text == 'Body' and d.text == 'A\n\nB\n\nBody'
    assert d.to_dict()['comments'][0]['selection_start'] == begin
    assert not any('selection validity' in w for w in d.warnings)
    assert normalize_text(d).comments == d.comments


@pytest.mark.parametrize('begin,end,want', [
    (0, 10, (0, 10)), (2, 10, (2, 10)), (3, 4, (3, 4)),
    (4, 9, (4, 9)), (8, 10, (8, 10)), (0, 12, (0, 12)),
    (1, 10, (None, None)), (0, 7, (None, None)),
])
def test_multiple_sections_empty_paragraph_and_utf16_endpoints(monkeypatch, begin, end, want):
    # Emoji=0..2, A=2, FF=3, CR=4, B=5, rocket=6..8, FF=8, C=9, ref=10, CR=11.
    main = '😀A\f\rB🚀\fC\x05\r'
    d = parse(monkeypatch, streams(main, begin, end, [0, 4, 9, 12]))
    assert selection(d) == want
    assert d.comments[0].source_cp == 10
    assert d.comments[0].anchor_path == ['blocks', 3]
    assert d.comment_text == 'Body'


@pytest.mark.parametrize('sections', [None, [0, 5]])
def test_unproven_ff_is_not_promoted_to_a_section_boundary(monkeypatch, sections):
    d = parse(monkeypatch, streams('A\fB\x05\r', 0, 3, sections))
    assert selection(d) == (None, None)
    assert d.comment_text == 'Body'


@pytest.mark.parametrize('sections', [[0, 3, 5], [0, 2, 2, 5], [0, 2, 4], [0, 6, 7]])
def test_malformed_section_evidence_raises(monkeypatch, sections):
    with pytest.raises(InvalidDocumentError, match='section'):
        parse(monkeypatch, streams('A\fB\x05\r', 0, 3, sections))


@pytest.mark.parametrize('missing_cp', [1, 4])
def test_unknown_boundary_or_following_paragraph_refuses(monkeypatch, missing_cp):
    original = _Doc._comment_paragraph_known
    monkeypatch.setattr(_Doc, '_comment_paragraph_known',
                        lambda self, cp: cp != missing_cp and original(self, cp))
    d = parse(monkeypatch, streams('A\fB\x05\r', 0, 3, [0, 2, 5]))
    assert selection(d) == (None, None)
    assert d.comment_text == 'Body'


@pytest.mark.parametrize('main', ['A\fB\x05\r\x13CODE\x15\r', 'A\fB\x13CODE\x14X\x15\x05\r'])
def test_fields_outside_section_selection_do_not_poison_it(monkeypatch, main):
    count = len(main.encode('utf-16le')) // 2
    d = parse(monkeypatch, streams(main, 0, 3, [0, 2, count]))
    assert selection(d) == (0, 3)
    assert d.comment_text == 'Body'


@pytest.mark.parametrize('main,sections,props,end', [
    ('P\fA\7\7Q\x05\r', [0, 2, 8], [b'', IN, ROW + definition([0]), b'', b'', b''], 6),
    ('A\7\7P\fQ\x05\r', [0, 5, 8], [IN, ROW + definition([0]), b'', b'', b'', b''], 6),
    ('A\fB\x05\7\7', [0, 2, 6], [IN, IN, ROW + definition([0]), b'', b''], 3),
])
def test_cross_section_tables_require_non_table_section_marks(monkeypatch, main, sections, props, end):
    d = parse(monkeypatch, streams(main, 0, end, sections, props=props))
    assert selection(d) == ((0, end) if end == 6 else (None, None))
    assert d.comment_text == 'Body'


def test_many_section_crossing_ranges_keep_existing_linear_index_budget():
    n = 256
    parser, paragraphs = algorithm_case(n, 4 * n + 1)
    parser.text = ('A\f' * (n - 1) + 'A\r').encode('utf-16le')
    parser.section_ends = set(range(1, n * 2 - 1, 2))
    for index, p in enumerate(paragraphs):
        if index == n - 1:
            break
        p[2] = 12
        p[5] = True  # Hidden source text does not shift the CP proof.
    paragraphs.accesses = 0
    parser._comment_selection_ranges(paragraphs)
    assert len(parser.comment_selections) == n
    assert set(parser.comment_selections.values()) == {(0, 511)}
    assert parser.budget.records == 4 * n + 1
    assert paragraphs.accesses <= 3 * n


def test_section_crossing_precharge_fails_before_paragraph_access():
    parser, paragraphs = algorithm_case(10, 40)
    parser.text = ('A\f' * 9 + 'A\r').encode('utf-16le')
    parser.section_ends = set(range(1, 19, 2))
    with pytest.raises(LimitExceededError, match='record'):
        parser._comment_selection_ranges(paragraphs)
    assert paragraphs.accesses == 0


def test_source_and_retained_text_limits_are_not_bypassed(monkeypatch):
    data = streams('A\fB\x05\r', 0, 3, [0, 2, 5])
    with pytest.raises(LimitExceededError):
        parse(monkeypatch, data, Limits(max_text_chars=4))


def test_original_cfb_keeps_cross_section_bookmark_despite_readback_loss():
    import importlib.util
    import json
    from pathlib import Path
    from legacy_office_parser import parse_doc

    root = Path(__file__).parent / 'fixtures/doc_comment_sections'
    spec = importlib.util.spec_from_file_location('section_raw_probe', root / 'inspect_fixture.py')
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    raw = probe.inspect()
    assert json.loads(json.dumps(raw)) == json.loads((root / 'evidence.json').read_text())
    assert raw['story_counts'] == [44, 0, 0, 24, 0, 0, 0]
    assert raw['section_cps'] == [0, 14, 29, 69]
    assert raw['comments'][0]['selection_cps'] == [8, 21]
    assert raw['comments'][0]['selection'] == 'Alpha\fBeta 🚀'
    assert raw['source_xml'][0]['selection'] == 'Alpha\rBeta 🚀'
    # Readback loses the annotation end, although the original DOC retains the
    # exact bookmark. Do not mistake converter loss for absent source evidence.
    assert raw['lo_readback_xml'][0]['selection'] is None
    assert raw['comments'][0]['tag'] == 0
    d = parse_doc(root / 'authored.doc')
    assert selection(d) == (8, 21)
    c = d.comments[0]
    assert c.source_cp == 21 and c.anchor_path == ['blocks', 1]
    assert c.author == 'Ada Section' and c.initials == ''
    assert c.body.block_start == 0 and c.body.block_end == 1
    assert d.comment_text == 'Review both sections.' and d.text.count(d.comment_text) == 1
    assert not d.warnings
    assert normalize_text(d).comments == d.comments
