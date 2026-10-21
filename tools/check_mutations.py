#!/usr/bin/env python3
"""Deterministic mutation smoke check of original public fixtures, never private input.

This is bounded sampling, not an exhaustive fuzzer or a proof of safety. Run it
under an external process timeout when changing parsers. Unexpected inputs are
saved under ignored tmp/mutation-regressions for minimization into unit tests.
"""
from __future__ import annotations

import argparse
import json
import hashlib
from pathlib import Path
import random
import time

from legacy_office_parser import Limits, ParseError, parse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=int, default=20261021)
    parser.add_argument('--cases-per-format', type=int, default=60)
    parser.add_argument('--all-fixtures', action='store_true',
                        help='Sample every supported-format document under public tests/fixtures')
    args = parser.parse_args()
    if not 1 <= args.cases_per_format <= 10000:
        parser.error('--cases-per-format must be between 1 and 10000')
    root = Path(__file__).resolve().parents[1]
    base = root / 'tests' / 'fixtures'
    paths = [base / 'ordinary_table.doc', base / 'slides_notes.ppt'] + [
        base / 'extended' / name for name in (
            'ordinary_table.rtf', 'ordinary_table.odt', 'typed_sparse.xls',
            'typed_sparse.ods', 'slides_notes.odp')]
    if args.all_fixtures:
        supported = {'.doc', '.ppt', '.rtf', '.odt', '.xls', '.ods', '.odp'}
        paths = sorted(path for path in base.rglob('*')
                       if path.is_file() and path.suffix.lower() in supported)
    rng = random.Random(args.seed)
    counts, failures, fixtures = {}, [], []
    start = time.monotonic()
    limits = Limits(max_text_chars=100000, max_records=50000, max_cells=10000)
    for path in paths:
        original = path.read_bytes()
        counter = counts.setdefault(path.suffix, {'ok': 0, 'parse_error': 0})
        fixture = path.relative_to(base).as_posix()
        fixture_id = hashlib.sha256(fixture.encode()).hexdigest()[:12]
        fixtures.append(fixture)
        for number in range(args.cases_per_format):
            data = bytearray(original)
            if number % 4 == 0:
                data = data[:rng.randrange(len(data))]
            else:
                for _ in range(rng.randint(1, 8)):
                    at = rng.randrange(len(data))
                    data[at] ^= rng.randrange(1, 256)
            try:
                parse(bytes(data), limits=limits)
                counter['ok'] += 1
            except ParseError:
                counter['parse_error'] += 1
            except Exception as exc:
                output = root / 'tmp' / 'mutation-regressions'
                output.mkdir(parents=True, exist_ok=True)
                (output / f'{args.seed}-{fixture_id}-{number}{path.suffix}').write_bytes(data)
                failures.append({'format': path.suffix, 'fixture': fixture, 'case': number,
                                 'exception': type(exc).__name__})
    print(json.dumps({'seed': args.seed, 'cases': len(paths) * args.cases_per_format,
                      'counts': counts, 'fixtures': fixtures, 'unexpected': failures,
                      'seconds': round(time.monotonic() - start, 2)}, indent=2))
    return int(bool(failures))


if __name__ == '__main__':
    raise SystemExit(main())
