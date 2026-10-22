"""Source-CP selection proofs: ordinary paragraphs and explicit same-cell spans."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from legacy_office_parser import InvalidDocumentError, LimitExceededError, Limits, parse_doc
from legacy_office_parser._doc_comments import SourceComment
from legacy_office_parser.doc import _Budget, _Doc, _Props
from legacy_office_parser.models import Document
from test_doc import IN, ROW, definition, mutate, parse, sprm
from test_doc_comments import SPECIAL, bookmarks, build
from test_doc_fidelity import add_chpx, append_table_part
from test_doc_nested import cell, paragraph, row

ROOT = Path(__file__).parent / 'fixtures/doc_comment_selections'


def ranged(main, begin, end, *, props=None):
    data = build(main, props=props, tags=[41])
    for index, value in bookmarks(len(main.encode('utf-16le')) // 2,
                                   starts=(begin,), ends=(end,)).items():
        append_table_part(data, index, value)
    return data


def selection(result):
    assert len(result.comments) == 1
    return result.comments[0].selection_start, result.comments[0].selection_end


def evidence(root):
    spec = importlib.util.spec_from_file_location('selection_fixture', ROOT / 'inspect_fixture.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.inspect(root)


def compare_fixture(root):
    raw = evidence(root)
    result = parse_doc(root / 'authored.doc')
    expected = ['Alpha\r\rBeta 🚀', 'Gamma\rDelta']
    assert raw['source_xml'] == raw['lo_readback_xml']
    assert [c['selection'] for c in raw['comments']] == expected
    assert [c['selection'] for c in raw['lo_readback_xml']] == expected
    assert [(c.selection_start, c.selection_end) for c in result.comments] == [
        tuple(c['selection_cps']) for c in raw['comments']]
    assert [c.source_cp for c in result.comments] == [c['source_cp'] for c in raw['comments']]
    assert [c.author for c in result.comments] == ['Ada Range', 'Ben Range']
    assert [c.anchor_path for c in result.comments] == [['blocks', 2], ['blocks', 5]]
    assert [(c.body.block_start, c.body.block_end) for c in result.comments] == [(0, 1), (1, 2)]
    assert result.comment_text == 'Across empty paragraph.\nAcross ordinary paragraphs.'
    assert result.text.count('Across empty paragraph.') == 1
    assert result.text.count('Across ordinary paragraphs.') == 1
    assert not any('selection validity' in w for w in result.warnings)
    return raw, result


def test_real_cfb_literal_cross_paragraph_selections():
    raw, result = compare_fixture(ROOT)
    assert json.loads(json.dumps(raw)) == json.loads((ROOT / 'evidence.json').read_text())
    assert raw['story_counts'] == [69, 0, 0, 55, 0, 0, 0]
    assert [c.source_cp for c in result.comments] == [22, 61]
    assert [(c.selection_start, c.selection_end) for c in result.comments] == [(8, 22), (50, 61)]


@pytest.mark.skipif(os.environ.get('OFFICE_CORPUS_LIBREOFFICE') != '1', reason='opt-in LibreOffice')
def test_live_cross_paragraph_fixture(tmp_path):
    office = shutil.which('libreoffice')
    if office is None:
        pytest.skip('LibreOffice unavailable')
    shutil.copyfile(ROOT / 'authored.fodt', tmp_path / 'authored.fodt')
    (tmp_path / 'readback').mkdir()
    profile = '-env:UserInstallation=' + (tmp_path / 'profile').as_uri()
    for source, dest, kind in ((tmp_path / 'authored.fodt', tmp_path, 'doc:MS Word 97'),
                               (tmp_path / 'authored.doc', tmp_path / 'readback', 'fodt')):
        subprocess.run([office, profile, '--headless', '--convert-to', kind, '--outdir', str(dest), str(source)],
                       check=True, timeout=60, capture_output=True)
    compare_fixture(tmp_path)


@pytest.mark.parametrize('main,begin,end', [
    ('First\rSecond\x05\r', 0, 12),
    ('First\rMiddle\rThird\x05\r', 2, 16),
    ('First\r\rThird\x05\r', 0, 12),
    ('A\rB\x05\r', 0, 1),  # before CR
    ('A\rB\x05\r', 0, 2),  # after CR
    ('A\rB\x05\r', 1, 3),  # starts on CR
    ('A\rB\x05\r', 2, 3),  # starts after CR
    ('A\rB\x05\r', 0, 5),  # includes final ordinary CR
    ('\r\rB\x05\r', 0, 3),
    ('😀A\rB🚀\x05\r', 2, 7),
])
def test_ordinary_endpoint_and_empty_paragraph_cases(monkeypatch, main, begin, end):
    result = parse(monkeypatch, ranged(main, begin, end))
    assert selection(result) == (begin, end)
    assert result.comment_text == 'Body'


@pytest.mark.parametrize('begin,end', [(1, 7), (2, 6)])
def test_surrogate_splits_never_published(monkeypatch, begin, end):
    result = parse(monkeypatch, ranged('😀A\rB🚀\x05\r', begin, end))
    assert selection(result) == (None, None)
    assert result.comment_text == 'Body'


def test_hidden_selected_text_does_not_shift_source_cps(monkeypatch):
    main = 'Hidden\rVisible\x05\r'
    d = ranged(main, 0, 14)
    add_chpx(d, [1024, 1036, 1024 + 2 * (len(main) + 7 + 1)],
             [SPECIAL + sprm(0x083C, 1), SPECIAL])
    result = parse(monkeypatch, d)
    assert selection(result) == (0, 14)
    assert result.comments[0].source_cp == 14
    assert 'Hidden' not in result.text and result.comment_text == 'Body'


def test_unknown_middle_paragraph_coverage_blocks_entire_range(monkeypatch):
    original = _Doc._comment_paragraph_known

    def known(self, cp):
        return cp != 3 and original(self, cp)

    monkeypatch.setattr(_Doc, '_comment_paragraph_known', known)
    result = parse(monkeypatch, ranged('A\rB\rC\x05\r', 0, 5))
    assert selection(result) == (None, None)
    assert result.comments[0].anchor_path == ['blocks', 2]


@pytest.mark.parametrize('main', ['A\r\x13CMD\x14B\x15\x05\r', '\x13CMD\x14A\x15\rB\x05\r'])
def test_field_crossings_remain_conservative(monkeypatch, main):
    result = parse(monkeypatch, ranged(main, 0, main.index('\x05')))
    assert selection(result) == (None, None)
    assert result.comment_text == 'Body'


def test_section_crossing_is_not_an_ordinary_paragraph_crossing(monkeypatch):
    from test_doc_sections import with_sections

    d = ranged('A\rB\x05\r', 0, 3)
    mutate(d, 'WordDocument', 1026, b'\x0c\0')
    d = with_sections(d, [0, 2, 5])
    result = parse(monkeypatch, d)
    assert selection(result) == (None, None)


def test_same_cell_multiple_paragraphs_are_proven(monkeypatch):
    main = 'A\rB\rC\x05\7\7'
    result = parse(monkeypatch, ranged(main, 0, 5, props=[IN, IN, IN, ROW + definition([0]), b'', b'']))
    assert selection(result) == (0, 5)
    assert result.comments[0].anchor_path == ['blocks', 0, 'rows', 0, 0]


@pytest.mark.parametrize('end', [3, 4])
def test_different_cells_and_cell_delimiters_remain_unproven(monkeypatch, end):
    main = 'A\7B\x05\7\7'
    result = parse(monkeypatch, ranged(main, 0, end, props=[IN, IN, ROW + definition([0, 0]), b'', b'']))
    assert selection(result) == (None, None)
    assert result.comments[0].anchor_path == ['blocks', 0, 'rows', 0, 1]


def test_cell_terminator_is_not_an_ordinary_cr(monkeypatch):
    parts = [paragraph(2, 'A'), cell(2, 'B\x05'), row(2), cell(1, 'Outer'), row(1)]
    main = ''.join(t for t, _ in parts)
    d = ranged(main, 0, 5, props=[p for _, p in parts] + [b'', b''])
    result = parse(monkeypatch, d)
    assert selection(result) == (None, None)  # CP 4 is the inner cell CR.


def test_nested_same_cell_span_uses_explicit_depth(monkeypatch):
    parts = [paragraph(2, 'A'), cell(2, 'B\x05'), row(2), cell(1, 'Outer'), row(1)]
    main = ''.join(t for t, _ in parts)
    result = parse(monkeypatch, ranged(main, 0, 3, props=[p for _, p in parts] + [b'', b'']))
    assert selection(result) == (0, 3)
    assert result.comments[0].anchor_path == ['blocks', 0, 'rows', 0, 0, 'blocks', 0, 'rows', 0, 0]


def test_crossing_nested_table_never_uses_equal_outer_depth_as_proof(monkeypatch):
    parts = [paragraph(1, 'Before'), cell(2, 'Inner'), row(2), cell(1, 'After\x05'), row(1)]
    main = ''.join(t for t, _ in parts)
    result = parse(monkeypatch, ranged(main, 0, main.index('\x05'), props=[p for _, p in parts] + [b'', b'']))
    assert selection(result) == (None, None)


def test_complete_source_rows_bridge_omitted_output_grid_positions(monkeypatch):
    main = 'Before\rX\7\7L\7R\7\7After\x05\r'
    props = [b'', IN, ROW + definition([0], [100, 200]), IN, IN,
             ROW + definition([0, 0], [0, 100, 200]), b'', b'', b'']
    result = parse(monkeypatch, ranged(main, 0, main.index('\x05'), props=props))
    assert result.blocks[1].rows[0][0].omitted
    # Both source rows are complete; output padding is not a source cell.
    assert selection(result) == (0, 20)
    assert result.comments[0].anchor_path == ['blocks', 2]


def test_overlaps_and_permuted_ibkl_keep_source_ownership(monkeypatch):
    main = 'First\rSecond\x05\rThird\x05\r'
    d = build(main, ('\x05One\r', '\x05Two\r'), tags=[70, 41])
    for index, value in bookmarks(len(main), starts=(0, 2), ends=(12, 19), tags=(41, 70), indexes=(1, 0)).items():
        append_table_part(d, index, value)
    result = parse(monkeypatch, d)
    assert [(c.selection_start, c.selection_end) for c in result.comments] == [(2, 12), (0, 19)]
    assert [c.source_cp for c in result.comments] == [12, 19]
    assert result.comment_text == 'One\nTwo'


@pytest.mark.parametrize('begin,end', [(4, 1), (0, 99)])
def test_invalid_bookmark_bounds_still_raise(monkeypatch, begin, end):
    with pytest.raises(InvalidDocumentError, match='bookmark'):
        parse(monkeypatch, ranged('A\rB\x05\r', begin, end))


def test_nested_depth_limit_still_precedes_selection_proof(monkeypatch):
    parts = [paragraph(2, 'A'), cell(2, 'B\x05'), row(2), cell(1, 'Outer'), row(1)]
    main = ''.join(t for t, _ in parts)
    with pytest.raises(LimitExceededError, match='depth'):
        parse(monkeypatch, ranged(main, 0, 3, props=[p for _, p in parts] + [b'', b'']), Limits(max_depth=1))


class CountedParagraphs(list):
    accesses = 0

    def __iter__(self):
        for item in super().__iter__():
            self.accesses += 1
            yield item

    def __getitem__(self, index):
        if isinstance(index, slice):
            raise AssertionError('range validation must not allocate paragraph slices')
        self.accesses += 1
        return super().__getitem__(index)


def algorithm_case(n, records):
    parser = object.__new__(_Doc)
    parser.budget = _Budget(Limits(max_records=records))
    parser.text = ('A\r' * n).encode('utf-16le')
    parser.section_ends = set()
    parser.document = Document('doc')
    parser._comment_paragraph_known = lambda cp: True
    parser.comment_selections = {}
    parser.comment_ranges = [SourceComment(i + 1, i, 0, 3, 'A', '', 0, n * 2 - 1) for i in range(n)]
    paragraphs = CountedParagraphs([i * 2, i * 2 + 1, 13, i * 2 + 1, _Props(), False, True]
                                  for i in range(n))
    return parser, paragraphs


def test_overlapping_long_ranges_do_not_rescan_selected_paragraphs():
    parser, paragraphs = algorithm_case(256, 10000)
    parser._comment_selection_ranges(paragraphs)
    assert len(parser.comment_selections) == 256
    assert paragraphs.accesses <= 3 * 256
    assert parser.budget.records == 4 * 256 + 1


def test_prefix_index_budget_is_charged_before_reading_or_allocating():
    parser, paragraphs = algorithm_case(256, 4 * 256)
    with pytest.raises(LimitExceededError, match='record'):
        parser._comment_selection_ranges(paragraphs)
    assert paragraphs.accesses == 0
    assert parser.comment_selections == {}


def test_equal_depth_without_closing_cell_mark_is_not_proof(monkeypatch):
    main = 'A\rB\x05\r\7'
    result = parse(monkeypatch, ranged(main, 0, 3,
        props=[IN, IN, ROW + definition([0]), b'', b'']))
    assert selection(result) == (None, None)
    assert result.comment_text == 'Body'


def test_missing_cell_terminator_coverage_is_not_proof(monkeypatch):
    original = _Doc._comment_paragraph_known

    def known(self, cp):
        return cp != 8 and original(self, cp)

    monkeypatch.setattr(_Doc, '_comment_paragraph_known', known)
    main = 'A\rB\x05\rEnd\7\7'
    result = parse(monkeypatch, ranged(main, 0, 3,
        props=[IN, IN, IN, ROW + definition([0]), b'', b'']))
    assert selection(result) == (None, None)
    assert result.comment_text == 'Body'
