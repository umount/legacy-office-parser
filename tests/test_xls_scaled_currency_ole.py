"""Preserved BIFF FORMAT oracle: patch only after exporting harmless seed masks."""
import csv
import hashlib
import os
from pathlib import Path
import struct
import sys

import olefile
import pytest

from legacy_office_parser import parse_xls
from test_xls_conditions import generate_probe

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/xls_scaled_currency/preserved.xls'
CSV_FORMAT = 'csv:Text - txt - csv (StarCalc):44,34,76,1,,0,false,true,true,false,false'
# Literal independent expectations, never calculated with the tested renderer.
CASES = [
    ('[$$-409]#,##0.00', -1234.5, '-$1,234.50'),
    ('[$€-407]#,##0.00', -1234.5, '-€1,234.50'),
    ('[$USD-409]0.00', 0, 'USD0.00'),
    ('0.00[$€-407]', -12.5, '-12.50€'),
    ('[$USD-409]0.00;([$USD-409]0.00)', -12.5, '(USD12.50)'),
    ('0.00[$$-409]', 12.5, '12.50$'),
    ('0.00[$USD-409]', 12.5, '12.50USD'),
    ('0.0,,"M"', 1234567, '1.2M'),
    ('0.0,,"M"', -1234567, '-1.2M'),
    ('0.0,,"M"', 9999999, '10.0M'),
    ('0.0,,"M";[Red](0.0,,"M")', -1234567, '(1.2M)'),
    ('#,##0,,', 1234567890, '1,235'),
    ('0.00,"k"', 1235, '1.24k'),
    ('0.0##', 1, '1.0'),
    ('0.0##', 1.2, '1.2'),
    ('0.0##', 1.2345, '1.235'),
    ('0.00##', 1.2, '1.20'),
    ('0.0##', 9.9999, '10.0'),
    ('[$USD-409]#,##0.0##,"k"', 1234567, 'USD1,234.567k'),
]


def masks():
    # Distinct <=49-character masks; empty literals keep record sizes stable.
    return [code + '""' * ((48 + len(code) % 2 - len(code)) // 2)
            for code, _, _ in CASES]


def workbook_stream(path):
    with olefile.OleFileIO(path) as compound:
        return compound.openstream('Workbook').read()


def format_records(data):
    pos = 0
    while pos + 4 <= len(data):
        tag, size = struct.unpack_from('<HH', data, pos)
        assert pos + 4 + size <= len(data)
        if tag == 0x41e:
            idx, count, flags = struct.unpack_from('<HHB', data, pos + 4)
            assert flags in (0, 1)
            encoding, width = ('utf-16le', 2) if flags else ('latin1', 1)
            start, end = pos + 9, pos + 9 + count * width
            assert end <= pos + 4 + size
            yield idx, start, end, encoding, data[start:end].decode(encoding)
        pos += 4 + size


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
        elif tag in (0x203, 0x27e):
            row, col, xf = struct.unpack_from('<HHH', data, start)
            assert col == 0 and row not in rows
            rows[row] = xf
        elif tag == 0xbd:
            row, first = struct.unpack_from('<HH', data, start)
            last, = struct.unpack_from('<H', data, start + size - 2)
            assert first == last == 0 and row not in rows
            rows[row] = struct.unpack_from('<H', data, start + 4)[0]
        pos += 4 + size
    expected_masks = masks()
    assert len(rows) == len(CASES)
    for row, expected in enumerate(expected_masks):
        assert len(expected) <= 64
        assert formats[xfs[rows[row]]] == expected
    parsed = parse_xls(path)
    assert parsed.warnings == []
    assert len(parsed.sheets) == 1
    for cell, (_, value, expected) in zip(parsed.sheets[0].cells, CASES, strict=True):
        assert struct.pack('<d', cell.value) == struct.pack('<d', value)
        assert (cell.value_type, cell.text, cell.is_formula) == ('number', expected, False)
    return [cell.text for cell in parsed.sheets[0].cells]


def convert(path, fmt, destination):
    sys.path.insert(0, str(ROOT / 'tools'))
    try:
        from check_performance import bounded
        result = bounded([sys.executable, str(ROOT / 'tools/check_performance.py'),
                          '--convert-child', '/usr/bin/libreoffice', str(path),
                          str(destination), fmt], 45)
        assert result['status'] == 'ok', result
    finally:
        sys.path.pop(0)


def generate_preserved(destination):
    """Reproducible authored inputs; LO container metadata may vary between runs."""
    destination.mkdir(parents=True, exist_ok=True)
    target_masks = masks()
    seeds = ['0.00"Ω' + str(i).zfill(2) + 'X' * (len(target) - 9) + '"'
             for i, target in enumerate(target_masks)]
    assert all(len(seed) == len(target) for seed, target in zip(seeds, target_masks))
    source = destination / 'preserved.xlsx'
    generate_probe(source, [(seed, case[1]) for seed, case in zip(seeds, CASES)])
    convert(source, 'xls:MS Excel 97', destination)
    path = destination / 'preserved.xls'
    original = workbook_stream(path)
    patched = bytearray(original)
    mapping = dict(zip(seeds, target_masks))
    seen = set()
    for _, start, end, encoding, code in format_records(original):
        if code in mapping:
            assert code not in seen
            replacement = mapping[code].encode(encoding)
            assert len(replacement) == end - start
            patched[start:end] = replacement
            seen.add(code)
    assert seen == set(seeds)
    with olefile.OleFileIO(path, write_mode=True) as compound:
        compound.write_stream('Workbook', bytes(patched))
    assert workbook_stream(path) == bytes(patched)
    verify_file(path)
    verify_csv(path, destination)
    return path


def verify_csv(path, destination):
    before = path.read_bytes()
    convert(path, CSV_FORMAT, destination)
    assert path.read_bytes() == before  # The oracle must not resave the input.
    with (destination / (path.stem + '.csv')).open(encoding='utf-8') as stream:
        rows = list(csv.reader(stream))
    assert rows == [[expected] for _, _, expected in CASES]
    assert verify_file(path) == [row[0] for row in rows]


def test_persisted_actual_formats_and_end_to_end_display():
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == '462a619c11d90e0dad081127e1c252e02f21345e999c97089cac2c25f79ad2f2'
    verify_file(FIXTURE)


@pytest.mark.skipif(os.environ.get('OFFICE_CORPUS_LIBREOFFICE') != '1',
                    reason='opt-in preserved FORMAT export/patch/CSV oracle')
def test_regenerated_and_persisted_files_against_libreoffice(tmp_path):
    generate_preserved(tmp_path / 'generated')
    destination = tmp_path / 'persisted'
    destination.mkdir()
    verify_csv(FIXTURE, destination)
