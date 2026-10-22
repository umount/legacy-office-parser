"""Public API and independent reference for original external-table DOC."""
from io import BytesIO
import json
import struct
import os
from pathlib import Path
import subprocess
import sys

import olefile
import pytest

from legacy_office_parser import parse_doc
from legacy_office_parser.errors import InvalidDocumentError

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/doc_external/ordinary_external.doc'


def test_real_ole_external_table_matches_authored_expectation():
    expected = json.loads((ROOT / 'tests/fixtures/ordinary_table.expected.json').read_text())
    actual = parse_doc(FIXTURE).to_dict()
    diagnostics = actual.pop('diagnostics', [])
    assert [d['message'] for d in diagnostics] == actual['warnings']
    assert all(d['code'] for d in diagnostics)
    actual['blocks'] = [b for b in actual['blocks']
                        if b['kind'] != 'paragraph' or b['text']]
    # Width preferences are separate from the explicit geometry tested here.
    assert all('Preferred table widths' in w for w in actual.pop('warnings'))
    expected.pop('warnings')
    assert actual == expected


def test_fixture_exercises_external_insert_and_width_records():
    with olefile.OleFileIO(FIXTURE) as ole:
        data = ole.openstream('Data').read()
        word = ole.openstream('WordDocument').read()
    assert b'\x6b\x64' in word  # PTableProps
    assert b'\x21\x76\0\3\x68\1' in data  # TInsert(0, 3, 360)
    assert b'\x23\x76\0\1' in data  # TDxaCol for first column
    assert b'\x08\xd6' not in data  # no TDefTable in external groups


def test_external_fixture_generator_is_reproducible():
    sys.path.insert(0, str(ROOT / 'tools'))
    try:
        from generate_doc_external_fixture import generate
        assert generate() == FIXTURE.read_bytes()
    finally:
        sys.path.pop(0)


@pytest.mark.skipif(os.environ.get('OFFICE_CORPUS_LIBREOFFICE') != '1',
                    reason='opt-in LibreOffice oracle')
def test_external_table_libreoffice_reference():
    result = subprocess.run([sys.executable, str(ROOT / 'tools/check_corpus.py'),
                             str(FIXTURE), '--libreoffice', '--fail-on-difference'],
                            capture_output=True, text=True, timeout=70, cwd=ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    report, = json.loads(result.stdout)['files']
    assert report['reference_differences'] == []
    body = report['reference_document']['body']
    assert body['equal'] is True
    assert body['model_total_tables'] == body['reference_total_tables'] == 1
    assert body['model_total_cells'] == body['reference_total_cells'] == 9


@pytest.mark.parametrize('mutation', ['short_group', 'outside_stream', 'cycle'])
def test_real_ole_invalid_external_reference_does_not_use_inline_fallback(mutation):
    content = BytesIO(FIXTURE.read_bytes())
    with olefile.OleFileIO(content, write_mode=True) as ole:
        data = bytearray(ole.openstream('Data').read())
        if mutation == 'short_group':
            struct.pack_into('<H', data, 0, 1)
        elif mutation == 'outside_stream':
            struct.pack_into('<HI', data, 2, 0x646b, 0xffffffff)
        else:
            struct.pack_into('<HI', data, 2, 0x646b, 0)
        ole.write_stream('Data', bytes(data))
    with pytest.raises(InvalidDocumentError):
        parse_doc(content.getvalue())
