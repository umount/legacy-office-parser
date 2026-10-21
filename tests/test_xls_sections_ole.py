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
FIXTURES = ROOT / 'tests/fixtures/xls_sections'
EXPECTED = [
    ('Positive', 12.5, '12.50', False),
    ('Negative', -12.5, '(12.50)', False),
    ('Zero', 0, 'zero', False),
    ('Negative percent', -.25, '-25.00%', False),
    ('Negative currency', -12.5, '(USD 12.50)', False),
    ('Quoted semicolon', -12.5, '-12.50;bad', False),
    ('Unsigned negative', -12.5, '12.50', False),
    ('Rounded negative', -.001, '(0.00)', False),
    ('Cached formula', -.25, '-25.00%', True),
]


def test_original_xls_numeric_meaning_and_raw_values():
    document = parse_xls(FIXTURES / 'sign_sections.xls')
    assert document.warnings == [
        'Formula expressions are not decoded or executed; cached results may be stale.']
    sheet, = document.sheets
    assert sheet.name == 'Sections'
    assert len(sheet.cells) == 18
    for row, (label, value, rendered, formula) in enumerate(EXPECTED, 1):
        cells = {c.column: c for c in sheet.cells if c.row == row}
        assert cells[1].text == label
        assert (cells[2].value, cells[2].value_type, cells[2].text,
                cells[2].is_formula) == (value, 'number', rendered, formula)
        assert rendered in document.text


def test_original_source_contains_authored_values_and_masks():
    import xml.etree.ElementTree as ET
    ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with ZipFile(FIXTURES / 'sign_sections.xlsx') as z:
        sheet = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
        styles = ET.fromstring(z.read('xl/styles.xml'))
    rows = sheet.findall('.//s:row', ns)
    assert [float(r.find('s:c[@s]/s:v', ns).text) for r in rows] == [v for _, v, _, _ in EXPECTED]
    assert [r.find('s:c/s:is/s:t', ns).text for r in rows] == [label for label, _, _, _ in EXPECTED]
    assert styles.find('s:numFmts/s:numFmt', ns).get('formatCode') == '0.00;(0.00);"zero"'


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
                str(FIXTURES / 'sign_sections.xls'), tmp,
                'csv:Text - txt - csv (StarCalc):44,34,76,1,,0,false,true,true,false,false'], 45)
            assert result['status'] == 'ok', result
            rows = list(csv.reader(StringIO((Path(tmp) / 'sign_sections.csv').read_text())))
    finally:
        sys.path.pop(0)
    assert rows == [[label, display] for label, _, display, _ in EXPECTED]
    parsed = parse_xls(FIXTURES / 'sign_sections.xls')
    assert [c.text for c in parsed.sheets[0].cells if c.column == 2] == [r[1] for r in rows]


def test_cli_json_keeps_raw_value_and_formatted_text():
    import json
    result = subprocess.run([sys.executable, '-m', 'legacy_office_parser',
                             str(FIXTURES / 'sign_sections.xls'), '--json'],
                            capture_output=True, text=True, timeout=15, cwd=ROOT,
                            env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')})
    assert result.returncode == 0, result.stderr
    cells = json.loads(result.stdout)['sheets'][0]['cells']
    cell = next(c for c in cells if c['row'] == 1 and c['column'] == 2)
    assert cell['value'] == 12.5 and cell['text'] == '12.50'


def test_authored_xlsx_is_reproducible(tmp_path):
    sys.path.insert(0, str(ROOT / 'tools'))
    try:
        from generate_xls_sections_fixture import generate_source
        destination = tmp_path / 'source.xlsx'
        generate_source(destination)
        assert destination.read_bytes() == (FIXTURES / 'sign_sections.xlsx').read_bytes()
    finally:
        sys.path.pop(0)
