"""Independent, hand-authored expectations for original binary Office fixtures."""
from dataclasses import is_dataclass
import importlib
import json
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET

import pytest

FIXTURES = Path(__file__).parent / 'fixtures'
CASES = [('ordinary_table', 'doc', 'odt'), ('merged_table', 'doc', 'odt'),
         ('slides_notes', 'ppt', 'pptx')]


@pytest.mark.parametrize('name,extension,source_extension', CASES)
def test_fixture_is_binary_ole_with_original_source(name, extension, source_extension):
    assert (FIXTURES / f'{name}.{extension}').read_bytes()[:8] == bytes.fromhex('d0cf11e0a1b11ae1')
    with ZipFile(FIXTURES / 'sources' / f'{name}.{source_extension}') as source:
        assert source.testzip() is None
        if source_extension == 'pptx':
            ET.fromstring(source.read('ppt/presentation.xml'))
        else:
            ET.fromstring(source.read('content.xml'))
            assert source.read('mimetype').startswith(b'application/vnd.oasis.opendocument.')
    expected = json.loads((FIXTURES / f'{name}.expected.json').read_text(encoding='utf-8'))
    assert expected['format'] == extension


@pytest.mark.parametrize('name,extension,source_extension', CASES)
def test_public_parser_matches_original_fixture(name, extension, source_extension):
    # Resolve at test execution so missing public exports fail tests, not collection.
    # Do not xfail incomplete implementations or derive expectations from parser output.
    api = importlib.import_module('legacy_office_parser')
    parse = getattr(api, f'parse_{extension}')
    result = parse(FIXTURES / f'{name}.{extension}')
    assert is_dataclass(result)
    expected = json.loads((FIXTURES / f'{name}.expected.json').read_text(encoding='utf-8'))
    actual = result.to_dict()
    diagnostics = actual.pop('diagnostics', [])
    assert [d['message'] for d in diagnostics] == actual['warnings']
    assert all(d['code'] for d in diagnostics)
    # Empty layout paragraphs added by Writer carry no semantic content. Retain all
    # table cells and slides: filtering those would hide the target regressions.
    actual['blocks'] = [block for block in actual['blocks']
                        if block['kind'] != 'paragraph' or block['text'] != '']
    # Diagnostics can evolve independently of extraction. LibreOffice emits
    # extension records that may legitimately trigger an unsupported-content warning.
    assert all(isinstance(warning, str) for warning in actual.pop('warnings'))
    expected.pop('warnings')
    assert actual == expected
