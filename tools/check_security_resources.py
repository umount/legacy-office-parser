#!/usr/bin/env python3
"""Bounded defensive resource regressions using original synthetic data only.

Linux child processes enforce 256 MiB address space, 8 CPU seconds and a 15s
wall timeout. This is sampling, not a security certification or leak proof.
"""
import gc
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import tracemalloc

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
CASES = ('zip_expansion', 'xml_depth', 'xml_declarations', 'ole_cycle',
         'rtf_depth', 'odf_repetition', 'repeated_parse')


def child(case):
    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024**2,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
    from legacy_office_parser import parse, Limits, ParseError
    from test_odf import package
    from test_ole_limits import directory_chain
    import struct
    if case == 'zip_expansion':
        data = package('<text:p>' + 'a' * 2_000_000 + '</text:p>')
        limits = Limits(max_uncompressed_bytes=100_000)
    elif case == 'xml_depth':
        data = package('<text:section>' * 1000 + '<text:p>x</text:p>' + '</text:section>' * 1000)
        limits = Limits(max_depth=32)
    elif case == 'xml_declarations':
        data = package(content='<!DOCTYPE x [<!ENTITY a "small">]><x>&a;</x>')
        limits = Limits()
    elif case == 'ole_cycle':
        data = bytearray(directory_chain(4))
        struct.pack_into('<I', data, 1024 + 3 * 128 + 76, 1)
        data = bytes(data)
        limits = Limits()
    elif case == 'rtf_depth':
        data = b'{\\rtf1 ' + b'{' * 1000 + b'x' + b'}' * 1001
        limits = Limits(max_depth=32)
    elif case == 'odf_repetition':
        data = package('<table:table><table:table-row table:number-rows-repeated="1000000000">'
                       '<table:table-cell><text:p>x</text:p></table:table-cell>'
                       '</table:table-row></table:table>')
        limits = Limits(max_cells=100)
    else:
        paths = ['ordinary_table.doc', 'slides_notes.ppt', 'extended/typed_sparse.xls',
                 'extended/ordinary_table.rtf', 'extended/ordinary_table.odt',
                 'extended/typed_sparse.ods', 'extended/slides_notes.odp']
        inputs = [(ROOT / 'tests/fixtures' / p).read_bytes() for p in paths]
        for data in inputs:
            parse(data)
        gc.collect()
        tracemalloc.start()
        samples = []
        for _ in range(4):
            for _ in range(5):
                for data in inputs:
                    parse(data)
            gc.collect()
            samples.append(tracemalloc.get_traced_memory()[0])
        growth = samples[-1] - samples[0]
        assert growth < 1024**2, ('retained Python allocation growth', growth)
        return {'case': case, 'parses': 140, 'retained_bytes': samples,
                'growth_bytes': growth, 'rss_peak_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    try:
        parse(data, limits=limits)
    except ParseError as exc:
        return {'case': case, 'bytes': len(data), 'result': type(exc).__name__,
                'rss_peak_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    raise AssertionError('expected bounded rejection: ' + case)


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--child':
        print(json.dumps(child(sys.argv[2])))
        return 0
    results = []
    for case in CASES:
        try:
            run = subprocess.run([sys.executable, __file__, '--child', case],
                                 capture_output=True, timeout=15,
                                 env={**os.environ, 'PYTHONPATH': os.pathsep.join(
                                     [str(ROOT / 'src'), os.environ.get('PYTHONPATH', '')])})
            if run.returncode:
                results.append({'case': case, 'failed': True, 'returncode': run.returncode,
                                'error': run.stderr.decode()[-1500:]})
            else:
                results.append(json.loads(run.stdout))
        except subprocess.TimeoutExpired:
            results.append({'case': case, 'failed': True, 'error': 'wall timeout'})
    print(json.dumps({'memory_limit_mib': 256, 'cpu_limit_s': 8, 'wall_limit_s': 15,
                      'results': results}, indent=2))
    return int(any(r.get('failed') for r in results))


if __name__ == '__main__':
    raise SystemExit(main())
