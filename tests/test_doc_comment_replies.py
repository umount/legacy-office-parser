"""Explicit source reply metadata, independent CFB evidence, and public limits."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess

import olefile
import pytest

from legacy_office_parser import (
    Comment, CommentBodyRange, Document, InvalidDocumentError, LimitExceededError,
    Limits, Paragraph, parse_doc,
)
from legacy_office_parser.api import _validate_result
from test_doc_comments import base_parts, decoded, extra
from test_doc import parse

ROOT = Path(__file__).parent / 'fixtures/doc_comment_replies'
spec = importlib.util.spec_from_file_location('reply_fixture', ROOT / 'fixture.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def tree(values):
    return b''.join(extra(depth, parent) for depth, parent in values)


def streams():
    with olefile.OleFileIO(ROOT / 'authored.doc') as compound:
        return {'/'.join(name): compound.openstream(name).read() for name in compound.listdir()}


def replace_extra(data, raw):
    word = bytearray(data['WordDocument'])
    offset, size = probe.location(word)
    assert len(raw) == size
    table = bytearray(data['1Table'])
    table[offset:offset + size] = raw
    data['1Table'] = bytes(table)


def test_raw_metadata_absent_root_and_reply():
    assert [(s.reply_depth, s.parent_ordinal) for s in decoded()] == [(None, None)] * 2
    result = decoded(base_parts() | {112: tree([(0, 0), (1, -1)])})
    assert [(s.reply_depth, s.parent_ordinal) for s in result] == [(0, None), (1, 1)]


@pytest.mark.parametrize('values', [
    [(1, -1), (0, 0)], [(0, 0), (1, 1)], [(0, 0), (1, 0)],
    [(0, 0), (0, -1)], [(0, 0), (2, -1)], [(0, 0), (1, -2)],
])
def test_bad_tree(values):
    with pytest.raises(InvalidDocumentError, match='reply'):
        decoded(base_parts() | {112: tree(values)})


def test_preorder_cannot_reopen_closed_parent(monkeypatch):
    data = streams()
    replace_extra(data, tree([(0, 0), (0, 0), (1, -2)]))
    with pytest.raises(InvalidDocumentError, match='preorder'):
        parse(monkeypatch, data)


@pytest.mark.parametrize('values,expected', [
    ([(0, 0), (1, -1), (1, -2)], [(0, None), (1, 1), (1, 1)]),
    ([(0, 0), (0, 0), (1, -1)], [(0, None), (0, None), (1, 2)]),
])
def test_siblings_and_multiple_roots(monkeypatch, values, expected):
    data = streams()
    replace_extra(data, tree(values))
    assert [(c.reply_depth, c.parent_ordinal) for c in parse(monkeypatch, data).comments] == expected


@pytest.mark.parametrize('omitted,expected', [
    (1, [(2, None, None), (3, None, None)]),
    (2, [(1, 0, None), (3, None, None)]),
])
def test_omitted_ancestor_clears_branch_without_dropping_bodies(monkeypatch, omitted, expected):
    from legacy_office_parser.doc import _Doc
    prepare = _Doc._prepare_comments

    def unknown(self):
        prepare(self)
        self.comment_structure_known[omitted] = False

    monkeypatch.setattr(_Doc, '_prepare_comments', unknown)
    result = parse_doc(ROOT / 'authored.doc')
    assert [(c.ordinal, c.reply_depth, c.parent_ordinal) for c in result.comments] == expected
    assert result.comment_text == 'Shared comment.\nCell comment: Ελληνικά.\nSecond paragraph.'
    assert any('ancestry is unavailable' in w for w in result.warnings)
    for c in result.to_dict()['comments']:
        if c['ordinal'] == 3:
            assert 'reply_depth' not in c and 'parent_ordinal' not in c


def test_absent_metadata_omits_both_json_keys(monkeypatch):
    expected = parse_doc(ROOT / 'authored.doc').comment_text
    data = streams()
    word = bytearray(data['WordDocument'])
    at = 32
    at += 2 + 2 * struct.unpack_from('<H', word, at)[0]
    at += 2 + 4 * struct.unpack_from('<H', word, at)[0]
    struct.pack_into('<II', word, at + 2 + 112 * 8, 0, 0)
    data['WordDocument'] = bytes(word)
    result = parse(monkeypatch, data)
    assert all('reply_depth' not in c and 'parent_ordinal' not in c
               for c in result.to_dict()['comments'])
    assert result.comment_text == expected


def test_fixture_is_deterministic_and_raw_oracle_is_independent(tmp_path):
    target = tmp_path / 'authored.doc'
    probe.generate(target)
    assert target.read_bytes() == (ROOT / 'authored.doc').read_bytes()
    saved = json.loads((ROOT / 'evidence.json').read_text())
    assert probe.inspect(target) == saved['source']
    assert probe.inspect(ROOT / 'readback/authored.doc') == saved['libreoffice_readback']
    result = parse_doc(target)
    assert [(c.reply_depth, c.parent_ordinal) for c in result.comments] == [(0, None), (1, 1), (2, 2)]
    assert [(c.source_cp, c.selection_start, c.selection_end) for c in result.comments] == [
        (20, 10, 20), (38, 38, 38), (61, 51, 61)]
    original = parse_doc(probe.SOURCE)
    assert result.text == original.text
    assert result.comment_text == original.comment_text
    assert result.to_dict()['comments'][0]['reply_depth'] == 0
    assert result.to_dict()['comments'][0]['parent_ordinal'] is None
    assert result.text.count('Shared comment.') == 2
    assert result.text.count('Second paragraph.') == 1


def test_saved_libreoffice_loses_relationships_but_preserves_bodies():
    result = parse_doc(ROOT / 'readback/authored.doc')
    assert [(c.reply_depth, c.parent_ordinal) for c in result.comments] == [(0, None)] * 3
    assert result.comment_text == parse_doc(ROOT / 'authored.doc').comment_text


@pytest.mark.skipif(os.environ.get('OFFICE_CORPUS_LIBREOFFICE') != '1', reason='opt-in LibreOffice oracle')
def test_live_libreoffice_reply_loss(tmp_path):
    office = shutil.which('libreoffice')
    if office is None:
        pytest.skip('LibreOffice unavailable')
    subprocess.run([office, '-env:UserInstallation=' + (tmp_path / 'profile').as_uri(),
                    '--headless', '--convert-to', 'doc:MS Word 97', '--outdir', str(tmp_path),
                    str(ROOT / 'authored.doc')], check=True, timeout=60, capture_output=True)
    assert [r['depth'] for r in probe.inspect(tmp_path / 'authored.doc')] == [0, 0, 0]
    assert parse_doc(tmp_path / 'authored.doc').comment_text == parse_doc(ROOT / 'authored.doc').comment_text


def model(values):
    return Document('doc', story_blocks={'comment_text': [Paragraph('Body') for _ in values]},
                    comments=[Comment(i + 1, CommentBodyRange('comment_text', i, i + 1),
                                      reply_depth=d, parent_ordinal=p)
                              for i, (d, p) in enumerate(values)])


@pytest.mark.parametrize('values', [
    [(None, 1)], [(0, 1)], [(True, None)], [(-1, None)], [('1', None)],
    [(1, None)], [(0, None), (1, True)], [(0, None), (1, 0)],
    [(0, None), (1, 2)], [(0, None), (1, 3)], [(None, None), (1, 1)],
    [(0, None), (2, 1)], [(0, None), (1, '1')],
])
def test_api_invalid_relationship(values):
    with pytest.raises(InvalidDocumentError):
        _validate_result(model(values), Limits())


def test_api_valid_depth_and_ordinal_gaps():
    doc = model([(0, None), (1, 1), (2, 2)])
    doc.comments[1].ordinal = 4
    doc.comments[2].ordinal = 7
    doc.comments[2].parent_ordinal = 4
    assert _validate_result(doc, Limits()) is doc


def test_reply_limits():
    with pytest.raises(LimitExceededError, match='reply depth'):
        _validate_result(model([(0, None), (1, 1), (2, 2)]), Limits(max_depth=1))
    with pytest.raises(LimitExceededError, match='reply depth'):
        decoded(base_parts() | {112: tree([(0, 0), (2, -1)])}, limits=Limits(max_depth=1))
    with pytest.raises(LimitExceededError, match='record'):
        _validate_result(model([(0, None)] * 4), Limits(max_records=3))
    with pytest.raises(LimitExceededError, match='record'):
        decoded(base_parts() | {112: tree([(0, 0), (1, -1)])}, limits=Limits(max_records=1))


def test_api_rejects_closed_ancestor():
    with pytest.raises(InvalidDocumentError, match='reply parent'):
        _validate_result(model([(0, None), (0, None), (1, 1)]), Limits())


def test_api_unknown_entry_does_not_invent_branch_closure():
    doc = model([(0, None), (None, None), (1, 1)])
    assert _validate_result(doc, Limits()) is doc


def test_api_unknown_entry_is_not_a_parent():
    with pytest.raises(InvalidDocumentError, match='reply parent'):
        _validate_result(model([(0, None), (None, None), (1, 2)]), Limits())


def test_runtime_unknown_grandchild_then_known_sibling(monkeypatch):
    from legacy_office_parser import doc as runtime
    from test_doc_comments import build

    original_decode = runtime.decode_comments
    original_prepare = runtime._Doc._prepare_comments
    # Supply real extra-record bytes to the existing Word97 synthetic transport;
    # the production decoder, ownership checks, and body publisher still run.
    def decode(parts, *args, **kwargs):
        return original_decode(parts | {112: tree([(0, 0), (1, -1), (2, -1), (1, -3)])},
                               *args, **kwargs)

    def prepare(self):
        original_prepare(self)
        self.comment_structure_known[2] = False

    monkeypatch.setattr(runtime, 'decode_comments', decode)
    monkeypatch.setattr(runtime._Doc, '_prepare_comments', prepare)
    data = build('\x05A\x05B\x05C\x05\r', ('\x05Root\r', '\x05Omitted\r',
                                               '\x05Grandchild\r', '\x05Sibling\r'))
    result = parse(monkeypatch, data)
    assert [(c.ordinal, c.reply_depth, c.parent_ordinal) for c in result.comments] == [
        (1, 0, None), (3, None, None), (4, 1, 1)]
    assert result.comment_text == 'Root\nGrandchild\nSibling'
    assert _validate_result(result, Limits()) is result
