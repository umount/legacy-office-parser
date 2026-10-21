"""Original spreadsheet: raw values and authored display text are independent oracles."""
import csv
from io import StringIO
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from zipfile import ZipFile

import pytest

from legacy_office_parser import parse_xls

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests/fixtures/xls_literals'
EXPECTED = [
    ('Mass', 12.5, '12.50 kg', False),
    ('Negative mass', -12.5, '-12.50 kg', False),
    ('Currency', 12.5, 'USD 12.50', False),
    ('Negative currency', -12.5, '-USD 12.50', False),
    ('Literal percent', .125, '0.13%', False),
    ('Days', 3, '3days', False),
    ('Cyrillic', 42, '42.00 руб.', False),
    ('Both sides', 2, 'ID 2.00 units', False),
]


def test_original_xls_numeric_meaning_and_raw_values():
    document = parse_xls(FIXTURES / 'literal_formats.xls')
    assert document.warnings == []
    sheet, = document.sheets
    assert sheet.name == 'Numbers'
    assert len(sheet.cells) == 16
    for row, (label, value, rendered, formula) in enumerate(EXPECTED, 1):
        cells = {c.column: c for c in sheet.cells if c.row == row}
        assert cells[1].text == label
        assert (cells[2].value, cells[2].value_type, cells[2].text,
                cells[2].is_formula) == (value, 'number', rendered, formula)
        assert rendered in document.text


def test_original_source_contains_authored_display_values():
    import xml.etree.ElementTree as ET
    with ZipFile(FIXTURES / 'literal_formats.ods') as z:
        root = ET.fromstring(z.read('content.xml'))
    ns = {'text': 'urn:oasis:names:tc:opendocument:xmlns:text:1.0'}
    assert [p.text for p in root.findall('.//text:p', ns)] == [
        s for label, _, display, _ in EXPECTED for s in (label, display)]


@pytest.mark.skipif(os.environ.get('OFFICE_CORPUS_LIBREOFFICE') != '1',
                    reason='opt-in LibreOffice displayed-number oracle')
def test_xls_displayed_values_match_libreoffice_csv():
    # Separate profile, resource-bounded converter and entire process-group timeout.
    sys.path.insert(0, str(ROOT / 'tools'))
    try:
        from check_performance import bounded
        with tempfile.TemporaryDirectory(prefix='xls-number-reference-') as tmp:
            result = bounded([sys.executable, str(ROOT / 'tools/check_performance.py'),
                '--convert-child', '/usr/bin/libreoffice',
                str(FIXTURES / 'literal_formats.xls'), tmp,
                'csv:Text - txt - csv (StarCalc):44,34,76,1,,0,false,true,true,false,false'], 45)
            assert result['status'] == 'ok', result
            rows = list(csv.reader(StringIO((Path(tmp) / 'literal_formats.csv').read_text())))
    finally:
        sys.path.pop(0)
    assert rows == [[label, display] for label, _, display, _ in EXPECTED]
    parsed = parse_xls(FIXTURES / 'literal_formats.xls')
    assert [c.text for c in parsed.sheets[0].cells if c.column == 2] == [r[1] for r in rows]


def test_cli_json_keeps_raw_value_and_formatted_text():
    import json
    result = subprocess.run([sys.executable, '-m', 'legacy_office_parser',
                             str(FIXTURES / 'literal_formats.xls'), '--json'],
                            capture_output=True, text=True, timeout=15, cwd=ROOT,
                            env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')})
    assert result.returncode == 0, result.stderr
    cells = json.loads(result.stdout)['sheets'][0]['cells']
    cell = next(c for c in cells if c['row'] == 1 and c['column'] == 2)
    assert cell['value'] == 12.5 and cell['text'] == '12.50 kg'


def test_authored_ods_is_reproducible(tmp_path):
    sys.path.insert(0, str(ROOT / 'tools'))
    try:
        from generate_xls_literals_fixture import generate_source
        destination = tmp_path / 'source.ods'
        generate_source(destination)
        assert destination.read_bytes() == (FIXTURES / 'literal_formats.ods').read_bytes()
    finally:
        sys.path.pop(0)
