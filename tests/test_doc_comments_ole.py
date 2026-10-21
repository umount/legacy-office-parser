"""Real CFB comments compared with an independent raw/XML fixture reader."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from legacy_office_parser import parse_doc
from legacy_office_parser.models import Paragraph

ROOT = Path(__file__).parent / 'fixtures/doc_comments'


def evidence(root):
    spec = importlib.util.spec_from_file_location('comment_fixture_probe', ROOT / 'inspect_fixture.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = root
    return module.inspect()


def compare(root):
    raw = evidence(root)
    result = parse_doc(root / 'authored.doc')
    assert raw['source_xml'] == raw['lo_readback_xml']
    assert len(raw['comments']) == len(result.comments) == 3
    assert [c.author for c in result.comments] == ['Ada Fixture', 'Ben Fixture', 'Ada Fixture']
    assert [c.initials for c in result.comments] == ['', '', '']
    assert [c.visibility for c in result.comments] == [[], [], []]
    assert [c.anchor_path for c in result.comments] == [
        ['blocks', 0], ['blocks', 1], ['blocks', 2, 'rows', 0, 0]]
    for ordinal, (comment, source, xml) in enumerate(
            zip(result.comments, raw['comments'], raw['lo_readback_xml']), 1):
        assert comment.ordinal == ordinal
        assert comment.source_cp == source['source_cp']
        assert source['source_unit'] == 5
        assert comment.author == raw['owners'][source['owner_index']] == xml['author']
        blocks = result.story_blocks['comment_text'][comment.body.block_start:comment.body.block_end]
        assert all(isinstance(b, Paragraph) for b in blocks)
        expected = source['body'][1:-1].split('\r')
        assert source['body'].startswith('\x05') and source['body'].endswith('\r')
        assert [b.text for b in blocks] == expected == xml['paragraphs']
        if source['tag'] == 0xffffffff:
            assert comment.selection_start == comment.selection_end == comment.source_cp
            assert xml['range_chars'] is None
        else:
            # Fixture ranges contain ten BMP letters, with an emoji only BEFORE
            # the first range; never treat source CP as a Python text offset.
            main = raw['main'].encode('utf-16le')
            selected = main[comment.selection_start * 2:comment.selection_end * 2].decode('utf-16le')
            assert selected == ('RangeAlpha' if ordinal == 1 else 'RangeGamma')
            assert len(selected) == xml['range_chars'] == 10
    assert result.comment_text == 'Shared comment.\nShared comment.\nCell comment: Ελληνικά.\nSecond paragraph.'
    assert result.text.count('Shared comment.') == 2
    assert result.text.count('Second paragraph.') == 1
    assert result.to_dict()['comments'][2]['body'] == {
        'story': 'comment_text', 'block_start': 2, 'block_end': 4}
    return raw, result


def test_saved_cfb_and_independent_readback():
    raw, result = compare(ROOT)
    assert json.loads(json.dumps(raw)) == json.loads((ROOT / 'evidence.json').read_text())
    assert [c.source_cp for c in result.comments] == [20, 38, 61]
    assert [(c.selection_start, c.selection_end) for c in result.comments] == [(10, 20), (38, 38), (51, 61)]
    assert [p['direct_chpx_hex'] for p in raw['marker_chpx']] == [['550801']] * 6
    assert 'Comment story text is omitted' not in '\n'.join(result.warnings)


@pytest.mark.skipif(os.environ.get('OFFICE_CORPUS_LIBREOFFICE') != '1',
                    reason='opt-in isolated LibreOffice conversion')
def test_live_libreoffice_readback(tmp_path):
    office = shutil.which('libreoffice')
    if office is None:
        pytest.skip('LibreOffice unavailable')
    shutil.copyfile(ROOT / 'authored.fodt', tmp_path / 'authored.fodt')
    readback = tmp_path / 'readback'
    readback.mkdir()
    profile = '-env:UserInstallation=' + (tmp_path / 'profile').as_uri()
    for source, output, format_name in (
        (tmp_path / 'authored.fodt', tmp_path, 'doc:MS Word 97'),
        (tmp_path / 'authored.doc', readback, 'fodt'),
    ):
        subprocess.run([office, profile, '--headless', '--convert-to', format_name,
                        '--outdir', str(output), str(source)], check=True, timeout=60,
                       capture_output=True, text=True)
    compare(tmp_path)
