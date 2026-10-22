"""End-to-end tests against authored content, never parser-generated goldens."""
from decimal import Decimal
import importlib
import json
from pathlib import Path
import struct
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

FIXTURES = Path(__file__).parent / 'fixtures' / 'extended'
CASES = [('ordinary_table', 'rtf'), ('ordinary_table', 'odt'),
         ('merged_table', 'odt'), ('slides_notes', 'odp'),
         ('typed_sparse', 'ods'), ('typed_sparse', 'xls')]


def expected_document(name, fmt):
    if fmt not in ('ods', 'xls'):
        return json.loads((FIXTURES / f'{name}.{fmt}.expected.json').read_text(encoding='utf-8'))
    sheets = json.loads((FIXTURES / 'typed_sparse.expected.json').read_text(encoding='utf-8'))['sheets']
    if fmt == 'xls':
        # BIFF tokens are retained as a formula flag, not decoded expressions.
        sheets[0]['cells'][7]['formula'] = None
    else:
        # ODF preserves office:value-type and explicitly represented grid size.
        # The authored blank ODS table contains one row and one empty cell.
        sheets[1]['rows'] = sheets[1]['columns'] = 1
        for cell in sheets[0]['cells']:
            if cell['value_type'] == 'number':
                cell['value_type'] = 'float'
    return dict(format=fmt, blocks=[], slides=[], sheets=sheets, footnotes='',
                endnotes='', headers_footers='', textboxes='', warnings=[])


def semantic_document(document):
    actual = document.to_dict()
    diagnostics = actual.pop('diagnostics', [])
    assert [d['message'] for d in diagnostics] == actual['warnings']
    assert all(d['code'] for d in diagnostics)
    assert all(isinstance(w, str) for w in actual.pop('warnings'))
    # Writer/RTF may carry empty layout paragraphs, but never discard table cells.
    actual['blocks'] = [b for b in actual['blocks'] if b['kind'] != 'paragraph' or b['text'] != '']
    for sheet in actual['sheets']:
        coords = [(c['row'], c['column']) for c in sheet['cells']]
        assert len(coords) == len(set(coords)), 'duplicate sparse coordinates'
        # XLS contains formatting-only BLANK records, including covered merge
        # coordinates. Validate their emptiness before excluding this metadata.
        cells = []
        for cell in sheet['cells']:
            if cell['value_type'] == 'empty':
                assert cell['value'] is None and cell['text'] == ''
                assert cell['formula'] is None and cell['is_formula'] is False
                continue
            if cell['value_type'] == 'boolean':
                assert type(cell['value']) is bool
            if cell['value_type'] in ('number', 'float'):
                assert type(cell['value']) in (int, float)
                # Decimal spelling differs (25 vs 25.0), not the displayed value.
                assert Decimal(cell['text']) == Decimal(str(cell['value']))
                cell['text'] = format(Decimal(cell['text']).normalize(), 'f')
            cells.append(cell)
        sheet['cells'] = sorted(cells, key=lambda c: (c['row'], c['column']))
    return actual


@pytest.mark.parametrize('name,fmt', CASES)
@pytest.mark.parametrize('entry', ['wrapper-path', 'wrapper-bytes', 'detect-bytes'])
def test_extended_public_parsers(name, fmt, entry):
    api = importlib.import_module('legacy_office_parser')
    path = FIXTURES / f'{name}.{fmt}'
    parse = api.parse if entry == 'detect-bytes' else getattr(api, f'parse_{fmt}')
    document = parse(path if entry == 'wrapper-path' else path.read_bytes())
    expected = expected_document(name, fmt)
    expected.pop('warnings')
    assert semantic_document(document) == expected
    if fmt in ('ods', 'xls'):
        assert 'Данные' in document.text and 'Пустой' in document.text
        assert 'F2\t25' in document.text
        assert [c.address for c in document.sheets[0].cells if c.is_formula] == ['F2']


@pytest.mark.parametrize('name,fmt', [case for case in CASES if case[1].startswith('od')])
def test_odf_fixture_package(name, fmt):
    kind = {'odt': 'text', 'ods': 'spreadsheet', 'odp': 'presentation'}[fmt]
    with ZipFile(FIXTURES / f'{name}.{fmt}') as archive:
        assert archive.testzip() is None
        assert archive.infolist()[0].filename == 'mimetype'
        assert archive.infolist()[0].compress_type == 0
        assert archive.read('mimetype').decode() == 'application/vnd.oasis.opendocument.' + kind
        ET.fromstring(archive.read('content.xml'))
        ET.fromstring(archive.read('META-INF/manifest.xml'))


def test_xls_is_actual_biff8_not_renamed_zip():
    import olefile
    path = FIXTURES / 'typed_sparse.xls'
    assert path.read_bytes()[:8] == bytes.fromhex('d0cf11e0a1b11ae1')
    with olefile.OleFileIO(path) as ole:
        stream = ole.openstream('Workbook').read()
    assert struct.unpack_from('<HHHH', stream) == (0x0809, 16, 0x0600, 5)
    # Independent record inspection: a numeric formula cache really is present.
    formulas = []
    pos = 0
    while pos + 4 <= len(stream):
        code, size = struct.unpack_from('<HH', stream, pos)
        record = stream[pos + 4:pos + 4 + size]
        if code == 6:
            formulas.append((struct.unpack_from('<HH', record), struct.unpack_from('<d', record, 6)[0]))
        pos += 4 + size
    assert ((1, 5), 25.0) in formulas


def test_authored_sources_preserved():
    assert (FIXTURES / 'typed_sparse.ods').read_bytes() == (FIXTURES / 'sources/typed_sparse.ods').read_bytes()
    for name in ('ordinary_table.odt', 'merged_table.odt'):
        assert (FIXTURES / name).read_bytes() == (FIXTURES.parent / 'sources' / name).read_bytes()
    source = FIXTURES / 'sources/slides_notes.pptx'
    assert source.read_bytes() == (FIXTURES.parent / 'sources/slides_notes.pptx').read_bytes()
    with ZipFile(source) as archive:
        ns = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main'}
        assert len(ET.fromstring(archive.read('ppt/presentation.xml')).findall('.//p:sldId', ns)) == 3
    with ZipFile(FIXTURES / 'typed_sparse.ods') as archive:
        xml = archive.read('content.xml').decode()
        assert 'table:formula="of:=[.B2]*2"' in xml
        assert 'office:value="25"' in xml
        assert 'office:date-value="2024-02-29"' in xml
    assert (FIXTURES / 'ordinary_table.rtf').read_bytes().startswith(b'{\\rtf1')
