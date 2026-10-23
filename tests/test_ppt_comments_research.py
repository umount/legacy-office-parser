"""Independent wire and LibreOffice oracles for active stored comments."""
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess

import olefile
import pytest

from legacy_office_parser import ppt
from legacy_office_parser.limits import Limits

FIXTURES = Path(__file__).parent / 'fixtures/ppt_comments'
EXPECTED = [
    {'slide': 1, 'body': ['Slide body 1'], 'comments': [
        {'author': 'Research Author', 'initials': 'RA', 'text': 'Budget excludes migration'},
        {'author': 'Review Author', 'initials': 'RA', 'text': 'Привет — проверить\nSecond comment line'},
    ]},
    {'slide': 2, 'body': ['Slide body 2'], 'comments': [
        {'author': 'Research Author', 'initials': 'RA', 'text': 'Slide body 2'},
    ]},
]
SHA = 'ca7b6d62b69dbd467116445113cbc966a1680b2ef7d282ccb840e48b35209aed'


def stored_active_comments(path):
    # Reuse only active persist/list resolution; inspect comment wire payloads
    # independently, without a production comment decoder or broad CString scan.
    with olefile.OleFileIO(path) as compound:
        data = compound.openstream('PowerPoint Document').read()
        current = compound.openstream('Current User').read()
    parser = ppt._Parser(data, Limits())
    root = parser.resolve(parser.directory(struct.unpack_from('<I', current, 16)[0]), 1000)
    lists = [r for r in parser.children(root) if r.type == 4080 and r.instance == 0]
    assert len(lists) == 1
    output = []
    for entry in parser.entries(lists[0]):
        comments = []
        slide = parser.resolve(entry.persist_id, 1006)
        for tags in parser.children(slide):
            if tags.type != 5000:
                continue
            assert tags.version == 15 and tags.instance == 0
            for tag in parser.children(tags):
                assert (tag.type, tag.version, tag.instance) == (5002, 15, 0)
                name, blob = list(parser.children(tag))
                assert (name.type, name.version, name.instance) == (4026, 0, 0)
                if data[name.start:name.end] != '___PPT10'.encode('utf-16le'):
                    continue
                assert (blob.type, blob.version, blob.instance) == (5003, 0, 0)
                for record in parser.children(blob):
                    if record.type != 12000:
                        continue
                    assert (record.version, record.instance) == (15, 0)
                    fields = {}
                    settings = []
                    for child in parser.children(record):
                        assert child.version == 0
                        if child.type == 4026:
                            assert child.instance in (0, 1, 2) and child.instance not in fields
                            length = child.end - child.start
                            assert length % 2 == 0 and length <= (64000 if child.instance == 1 else 104)
                            fields[child.instance] = data[child.start:child.end].decode('utf-16le')
                        else:
                            assert (child.type, child.instance, child.end - child.start) == (12001, 0, 28)
                            assert struct.unpack_from('<i', data, child.start)[0] >= 0
                            settings.append(child)
                    assert len(settings) == 1
                    comments.append(dict(author=fields[0], initials=fields[2], text=fields[1]))
        output.append(comments)
    return output


def test_complete_authored_fixture_contains_typed_active_comments():
    path = FIXTURES / 'comments.ppt'
    assert hashlib.sha256(path.read_bytes()).hexdigest() == SHA
    assert stored_active_comments(path) == [slide['comments'] for slide in EXPECTED]


def test_independent_uno_readback_distinguishes_body_and_comments():
    assert json.loads((FIXTURES / 'uno-readback.json').read_text()) == EXPECTED
    # Equality of content must not erase the distinct annotation on slide 2.
    assert EXPECTED[1]['comments'][0]['text'] == EXPECTED[1]['body'][0]


def test_comments_are_structured_separately_from_body_and_notes():
    document = ppt.parse_ppt_bytes((FIXTURES / 'comments.ppt').read_bytes(), Limits())
    assert [s.text for s in document.slides] == ['Slide body 1', 'Slide body 2']
    assert all(s.title == s.notes == '' for s in document.slides)
    assert 'Budget excludes migration' in document.text
    assert [[dict(text=c.text, author=c.author, initials=c.initials) for c in s.comments]
            for s in document.slides] == [s['comments'] for s in EXPECTED]
    assert document.text.endswith('Slide body 2\nSlide body 2')
    assert document.warnings == ['PPT active slide-number field is not evaluated; no generated value is extracted.']


@pytest.mark.skipif(os.environ.get('OFFICE_CORPUS_LIBREOFFICE') != '1',
                    reason='opt-in independent read-only UNO comment oracle')
def test_fresh_libreoffice_read_only_oracle(tmp_path):
    result = subprocess.run(['/usr/bin/python3', str(FIXTURES / 'generate.py'), str(tmp_path),
                             '--read', str((FIXTURES / 'comments.ppt').resolve())],
                            capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stderr
    assert json.loads((tmp_path / 'uno-readback.json').read_text()) == EXPECTED
    assert hashlib.sha256((FIXTURES / 'comments.ppt').read_bytes()).hexdigest() == SHA
