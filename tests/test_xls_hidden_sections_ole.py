"""Authored same-XLS oracle; exact short FORMAT strings patched after export."""
import csv
import hashlib
import os
from pathlib import Path
import struct
from zipfile import ZipFile
import xml.etree.ElementTree as ET

import olefile
import pytest

from legacy_office_parser import parse_xls
from test_xls_conditions import generate_probe
from test_xls_hidden_sections import CASES as NUMERIC_CASES
from test_xls_scaled_currency_ole import convert, format_records, workbook_stream, CSV_FORMAT

FIXTURE = Path(__file__).parent / 'fixtures/xls_hidden_sections/preserved.xls'
CASES = [(code, value, expected) for code, outputs in NUMERIC_CASES if len(code) >= 3
         for value, expected in zip((12, -12, 0), outputs)]
CASES += [(';;;', 'retained', ''), ('0;0;0;', 'retained', ''),
          (';;;@', 'retained', 'retained'), ('0;;0', 'retained', 'retained')]


def verify_file(path):
    data = workbook_stream(path)
    formats = {idx: code for idx, _, _, _, code in format_records(data)}
    xfs, rows = [], {}
    pos = 0
    while pos + 4 <= len(data):
        tag, size = struct.unpack_from('<HH', data, pos)
        start = pos + 4
        if tag == 0xe0:
            xfs.append(struct.unpack_from('<H', data, start + 2)[0])
        elif tag in (0x203, 0x27e, 0xfd):
            row, col, xf = struct.unpack_from('<HHH', data, start)
            assert col == 0 and row not in rows
            rows[row] = xf
        elif tag == 0xbd:
            row, first = struct.unpack_from('<HH', data, start)
            last, = struct.unpack_from('<H', data, start + size - 2)
            assert first == last == 0 and row not in rows
            rows[row] = struct.unpack_from('<H', data, start + 4)[0]
        pos += 4 + size
    assert len(rows) == len(CASES)
    for row, (code, _, _) in enumerate(CASES):
        assert formats[xfs[rows[row]]] == code
        assert len(code) <= 64
    doc = parse_xls(path)
    assert not doc.warnings
    cells = doc.sheets[0].cells
    assert len(cells) == len(CASES)
    for cell, (_, value, expected) in zip(cells, CASES, strict=True):
        assert cell.value == value and cell.text == expected
        assert cell.value_type == ('string' if isinstance(value, str) else 'number')
        assert not cell.is_formula
    serialized = doc.to_dict()['sheets'][0]['cells']
    assert [cell['text'] for cell in serialized] == [case[2] for case in CASES]
    assert [cell['value'] for cell in serialized] == [case[1] for case in CASES]
    return [cell.text for cell in cells]


def verify_csv(path, destination):
    before = path.read_bytes()
    convert(path, CSV_FORMAT, destination)
    assert path.read_bytes() == before
    with (destination / (path.stem + '.csv')).open(encoding='utf-8') as stream:
        rows = list(csv.reader(stream))
    # One empty field is emitted as an empty CSV line by Calc.
    rows = [row if row else [''] for row in rows]
    assert rows == [[expected] for _, _, expected in CASES]
    assert verify_file(path) == [row[0] for row in rows]


def generate_preserved(destination):
    destination.mkdir(parents=True, exist_ok=True)
    # Every exact target has a harmless unique quoted Unicode seed of the same
    # length. No empty-literal padding alters an empty section's semantics.
    seeds = [('0' + chr(92) + chr(0x391 + i)) if len(code) == 3 else
             '"' + chr(0x391 + i) * (len(code) - 2) + '"'
             for i, (code, _, _) in enumerate(CASES)]
    source = destination / 'preserved.xlsx'
    generate_probe(source, [(seed, value if not isinstance(value, str) else 1)
                            for seed, (_, value, _) in zip(seeds, CASES)])
    with ZipFile(source) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    sheet = ET.fromstring(files['xl/worksheets/sheet1.xml'])
    for cell, (_, value, _) in zip(sheet.iter(f'{{{ns}}}c'), CASES):
        if isinstance(value, str):
            cell.remove(cell.find(f'{{{ns}}}v'))
            cell.set('t', 'inlineStr')
            ET.SubElement(ET.SubElement(cell, f'{{{ns}}}is'), f'{{{ns}}}t').text = value
    files['xl/worksheets/sheet1.xml'] = ET.tostring(sheet)
    with ZipFile(source, 'w') as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    convert(source, 'xls:MS Excel 97', destination)
    path = destination / 'preserved.xls'
    original = workbook_stream(path)
    patched = bytearray(original)
    mapping = dict(zip(seeds, [case[0] for case in CASES]))
    seen = set()
    for _, start, end, encoding, code in format_records(original):
        if code in mapping:
            replacement = mapping[code].encode(encoding)
            assert len(replacement) == end - start
            patched[start:end] = replacement
            seen.add(code)
    assert seen == set(seeds), (seen, set(seeds) - seen)
    with olefile.OleFileIO(path, write_mode=True) as compound:
        compound.write_stream('Workbook', bytes(patched))
    assert workbook_stream(path) == bytes(patched)
    verify_file(path)
    verify_csv(path, destination)
    return path


def test_persisted_exact_formats_and_public_api():
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == '3add5107121667889ec7d2614ae6ca1857fd21e22f2069c7dc30b2f6fa0819cb'
    verify_file(FIXTURE)


@pytest.mark.skipif(os.environ.get('OFFICE_CORPUS_LIBREOFFICE') != '1',
                    reason='opt-in exact FORMAT export/patch/CSV oracle')
def test_regenerated_and_persisted_oracles(tmp_path):
    generate_preserved(tmp_path / 'generated')
    destination = tmp_path / 'persisted'
    destination.mkdir()
    verify_csv(FIXTURE, destination)
