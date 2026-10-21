#!/usr/bin/env python3
"""Bounded Linux benchmarks of original synthetic documents (no corpus input)."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import resource
import signal
import subprocess
import sys
import tempfile
import time
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tools')]
FORMATS = ('odt', 'rtf', 'ods', 'odp', 'doc', 'xls', 'ppt')
# Fixed, moderate workloads, not an unbounded stress/load generator.
PROFILES = {
    'small': dict(paragraphs=20, table_rows=10, sheet_rows=20, slides=5),
    'large': dict(paragraphs=3000, table_rows=300, sheet_rows=1500, slides=120),
}


def item(kind, number):
    return (f'{kind}{number:06d} Original synthetic benchmark record with ordinary '
            'words for reproducible extraction and complete content verification.')


def expected(profile):
    n = PROFILES[profile]
    return {
        'paragraphs': [item('Paragraph', i) for i in range(n['paragraphs'])],
        'rows': [[item('Table', r * 6 + c) for c in range(6)]
                 for r in range(n['table_rows'])],
        'sheets': [[[f'S{s}R{r:04d}C{c} synthetic value' for c in range(1, 9)]
                    for r in range(1, n['sheet_rows'] + 1)] for s in range(2)],
        'slides': [[item('Slide', s * 8 + p) for p in range(8)]
                   for s in range(n['slides'])],
    }


def generate(directory, profile):
    from generate_fixtures import write_odf, p, cell, row
    e = expected(profile)
    document = ''.join(p(t) for t in e['paragraphs'])
    document += ('<table:table table:name="Benchmark">'
                 '<table:table-column table:number-columns-repeated="6"/>'
                 + ''.join(row([cell(t) for t in r]) for r in e['rows']) + '</table:table>')
    odt = directory / 'ordinary.odt'
    write_odf(odt, 'text', document)
    # Select the master only on the first body paragraph. Applying it to every
    # paragraph (including cells) makes LibreOffice insert section boundaries.
    with ZipFile(odt) as archive:
        entries = [(info, archive.read(info.filename)) for info in archive.infolist()]
    with ZipFile(odt, 'w') as archive:
        for info, data in entries:
            if info.filename == 'content.xml':
                data = data.replace(b'<office:body>',
                    b'<office:automatic-styles><style:style style:name="Body" '
                    b'style:family="paragraph" style:master-page-name="Default"/>'
                    b'</office:automatic-styles><office:body>')
                data = data.replace(b'<text:p>', b'<text:p text:style-name="Body">', 1)
            archive.writestr(info, data)
    rtf = ['{\\rtf1\\ansi\n']
    rtf.extend(t + '\\par\n' for t in e['paragraphs'])
    for values in e['rows']:
        rtf.append('\\trowd' + ''.join(f'\\cellx{(c+1)*1500}' for c in range(6)) + '\n')
        rtf.extend('\\pard\\intbl ' + t + '\\cell\n' for t in values)
        rtf.append('\\row\n')
    rtf.append('\\pard\n}')
    (directory / 'ordinary.rtf').write_text(''.join(rtf), encoding='ascii')
    sheets = ''.join(
        f'<table:table table:name="Sheet{s}">'
        '<table:table-column table:number-columns-repeated="8"/>'
        + ''.join(row([cell(t) for t in r]) for r in values) + '</table:table>'
        for s, values in enumerate(e['sheets']))
    write_odf(directory / 'ordinary.ods', 'spreadsheet', sheets)
    slides = ''.join(
        f'<draw:page draw:name="Slide{s}" draw:master-page-name="Default">'
        '<draw:frame svg:x="1cm" svg:y="1cm" svg:width="25cm" svg:height="18cm">'
        '<draw:text-box>' + ''.join(p(t) for t in values)
        + '</draw:text-box></draw:frame></draw:page>' for s, values in enumerate(e['slides']))
    write_odf(directory / 'ordinary.odp', 'presentation', slides)


def normalize(text):
    return ' '.join(text.split())


def validate(document, profile):
    """Compare every authored item, order, dimensions and coordinate, not sentinels."""
    from legacy_office_parser.models import Paragraph, Table
    e = expected(profile)
    errors = []
    counts = dict(paragraphs=0, tables=0, table_rows=0, table_cells=0,
                  sheets=len(document.sheets), sheet_cells=0, slides=len(document.slides))
    paragraphs = [b.text for b in document.blocks if isinstance(b, Paragraph) and b.text.strip()]
    tables = [b for b in document.blocks if isinstance(b, Table)]
    counts.update(paragraphs=len(paragraphs), tables=len(tables),
                  table_rows=sum(len(t.rows) for t in tables),
                  table_cells=sum(len(r) for t in tables for r in t.rows),
                  sheet_cells=sum(len(s.cells) for s in document.sheets))
    if document.format in ('doc', 'odt', 'rtf'):
        if list(map(normalize, paragraphs)) != e['paragraphs']:
            errors.append('paragraph_content_or_count')
        actual = [[[normalize(c.text) for c in r] for r in t.rows] for t in tables]
        if actual != [e['rows']]:
            errors.append('table_content_or_dimensions')
        # Validate the public projection too, including block order and extra stories.
        wanted = ' '.join(e['paragraphs'] + [t for r in e['rows'] for t in r])
        if normalize(document.text) != wanted:
            errors.append('text_projection')
    elif document.format in ('ods', 'xls'):
        actual = [(s.name, [(c.row, c.column, normalize(c.text), c.value_type)
                            for c in sorted(s.cells, key=lambda c: (c.row, c.column))])
                  for s in document.sheets]
        wanted = [(f'Sheet{s}', [(r, c, t, 'string') for r, row in enumerate(values, 1)
                                 for c, t in enumerate(row, 1)])
                  for s, values in enumerate(e['sheets'])]
        if actual != wanted:
            errors.append('sheet_content_coordinates_or_count')
    else:
        actual = [normalize(' '.join((s.title, s.text, s.notes))) for s in document.slides]
        if actual != [' '.join(values) for values in e['slides']]:
            errors.append('slide_content_order_or_count')
    if document.warnings:
        errors.append('parser_warnings')
    counts['text_chars'] = len(document.text)
    counts['warnings'] = len(document.warnings)
    return counts, errors


def limits(memory_mib, cpu_seconds):
    resource.setrlimit(resource.RLIMIT_AS, (memory_mib * 1024**2,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds,) * 2)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def peak_rss_kib():
    # Linux ru_maxrss can retain the parent's pre-exec high-water mark. VmHWM
    # belongs to this exec's address space, excluding the generator's memory.
    for line in Path('/proc/self/status').read_text().splitlines():
        if line.startswith('VmHWM:'):
            return int(line.split()[1])
    raise RuntimeError('Linux VmHWM unavailable')


def failure_details(exc):
    from legacy_office_parser import LimitExceededError
    result = {'error_type': type(exc).__name__}
    # Only fixed known messages become report codes; arbitrary exception text stays private.
    if isinstance(exc, LimitExceededError) and str(exc) == 'DOC record limit exceeded':
        result['limit_code'] = 'doc_record_budget'
    return result


def source_fingerprint():
    digest = hashlib.sha256()
    for path in sorted((ROOT / 'src' / 'legacy_office_parser').glob('*.py')):
        digest.update(path.name.encode() + b'\0' + path.read_bytes() + b'\0')
    return digest.hexdigest()


def worker(path, profile):
    limits(384, 30)
    from legacy_office_parser import parse
    started = time.perf_counter()
    try:
        document = parse(path)
    except Exception as exc:
        return dict(status='parse_error', **failure_details(exc),
                    parse_seconds=time.perf_counter() - started,
                    peak_rss_kib=peak_rss_kib())
    elapsed = time.perf_counter() - started
    rss = peak_rss_kib()
    counts, errors = validate(document, profile)
    return dict(status='ok' if not errors else 'validation_failed', parse_seconds=elapsed,
                peak_rss_kib=rss, counts=counts, validation_errors=errors)


def bounded(command, timeout):
    """Reap the child and kill its private group on every exit, including interruption."""
    started = time.perf_counter()
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, start_new_session=True)
    try:
        try:
            stdout, _ = proc.communicate(timeout=timeout)
            status = 'ok' if proc.returncode == 0 else 'child_failed'
        except subprocess.TimeoutExpired:
            status, stdout = 'timeout', ''
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.communicate()
    return dict(status=status, returncode=proc.returncode, stdout=stdout,
                subprocess_seconds=time.perf_counter() - started)


def convert_child(lo, source, destination, fmt):
    limits(1024, 60)
    with tempfile.TemporaryDirectory(prefix='lo-profile-', dir=destination) as profile:
        command = [lo, '-env:UserInstallation=' + Path(profile).as_uri(), '--headless',
                   '--nologo', '--nodefault', '--nofirststartwizard', '--convert-to', fmt,
                   '--outdir', str(destination), str(source)]
        # Inherit this wrapper's private process group so the parent kills all descendants.
        result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                env={**os.environ, 'SAL_USE_VCLPLUGIN': 'svp',
                                     'GSETTINGS_BACKEND': 'memory', 'DCONF_PROFILE': '/dev/null'})
        print(json.dumps({'converter_returncode': result.returncode}))
        return result.returncode


def benchmark(profile, repeats=1, libreoffice=None, timeout=45):
    from legacy_office_parser import Limits, __version__
    source_before = source_fingerprint()
    results = []
    with tempfile.TemporaryDirectory(prefix='lop-performance-') as temp:
        directory = Path(temp)
        generate(directory, profile)
        conversions = {}
        for source, target, filter_name in [('odt', 'doc', 'MS Word 97'),
                                             ('ods', 'xls', 'MS Excel 97'),
                                             ('odp', 'ppt', 'MS PowerPoint 97')]:
            if libreoffice:
                run = bounded([sys.executable, __file__, '--convert-child', libreoffice,
                               str(directory / f'ordinary.{source}'), str(directory),
                               f'{target}:{filter_name}'], 90)
                conversions[target] = {k: v for k, v in run.items() if k != 'stdout'}
                try:
                    conversions[target].update(json.loads(run['stdout']))
                except ValueError:
                    pass
        for fmt in FORMATS:
            path = directory / f'ordinary.{fmt}'
            if not path.exists():
                results.append(dict(format=fmt, status='conversion_failed' if libreoffice else 'skipped',
                                    reason=conversions.get(fmt, 'developer_converter_not_requested'),
                                    input_bytes=None, parse_seconds=None, peak_rss_kib=None))
                continue
            data = path.read_bytes()
            expanded_bytes = None
            if fmt in ('odt', 'ods', 'odp'):
                with ZipFile(path) as archive:
                    expanded_bytes = sum(info.file_size for info in archive.infolist())
            if len(data) > 5 * 1024**2:
                results.append(dict(format=fmt, status='input_too_large', input_bytes=len(data)))
                continue
            for repeat in range(repeats):
                run = bounded([sys.executable, __file__, '--worker', str(path), profile], timeout)
                result = dict(format=fmt, repeat=repeat + 1, input_bytes=len(data),
                              sha256=hashlib.sha256(data).hexdigest(),
                              odf_uncompressed_bytes=expanded_bytes, parse_seconds=None,
                              peak_rss_kib=None, counts=None,
                              subprocess_seconds=run['subprocess_seconds'])
                if run['status'] == 'ok':
                    try:
                        result.update(json.loads(run['stdout']))
                    except (ValueError, TypeError):
                        result.update(status='invalid_worker_output')
                else:
                    result.update(status=run['status'], returncode=run['returncode'])
                results.append(result)
    return dict(schema_version=1, profile=profile, workload=PROFILES[profile],
                project_version=__version__,
                runtime_version=__version__, parser_defaults=asdict(Limits()),
                source_sha256_before=source_before, source_sha256_after=source_fingerprint(),
                rss_source='Linux /proc/self/status VmHWM sampled immediately after parse',
                python=platform.python_version(), platform=platform.platform(),
                bounds=dict(parse_address_space_mib=384, parse_cpu_seconds=30,
                            parse_wall_seconds=timeout, converter_address_space_mib=1024,
                            converter_cpu_seconds=60, converter_wall_seconds=90), results=results)


def main():
    if len(sys.argv) == 4 and sys.argv[1] == '--worker':
        print(json.dumps(worker(Path(sys.argv[2]), sys.argv[3])))
        return 0
    if len(sys.argv) == 6 and sys.argv[1] == '--convert-child':
        return convert_child(sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4]), sys.argv[5])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=PROFILES, default='large')
    parser.add_argument('--repeats', type=int, choices=range(1, 4), default=1)
    parser.add_argument('--libreoffice', help='optional developer converter executable')
    parser.add_argument('--timeout', type=float, default=45)
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or not 0 < args.timeout <= 60:
        parser.error('--timeout must be finite and in (0, 60]')
    if sys.platform != 'linux':
        parser.error('RSS units and resource bounds currently require Linux')
    report = benchmark(args.profile, args.repeats, args.libreoffice, args.timeout)
    print(json.dumps(report, indent=2))
    return int(any(r['status'] not in ('ok', 'skipped') for r in report['results']))


if __name__ == '__main__':
    raise SystemExit(main())
