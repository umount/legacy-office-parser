#!/usr/bin/env python3
"""Private corpus check: only counts/hashes leave the worker, never document text.

LibreOffice is an optional development reference, not a package dependency.
Temporary copies and converted documents are removed after each invocation.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import resource
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile


def _worker(source: Path, reference: Path | None) -> dict:
    from legacy_office_parser import parse, ParseError, Paragraph
    start = time.perf_counter()
    try:
        doc = parse(source)
    except ParseError as exc:
        return {'status': 'parse_error', 'error': type(exc).__name__}
    body = '\n'.join(b.text if isinstance(b, Paragraph) else '\n'.join(
        '\t'.join(c.text for c in row) for row in b.rows) for b in doc.blocks)
    if doc.format == 'ppt':
        body = '\n'.join('\n'.join((s.title, s.text)) for s in doc.slides)
    result = {
        'status': 'warning' if doc.warnings else 'ok',
        'format': doc.format,
        'text_chars': len(doc.text),
        'tables': sum(b.kind == 'table' for b in doc.blocks),
        'slides': len(doc.slides),
        'warnings': doc.warnings,
        'parse_seconds': round(time.perf_counter() - start, 4),
        'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }
    if reference:
        with zipfile.ZipFile(reference) as z:
            if doc.format == 'doc':
                root = ET.fromstring(z.read('word/document.xml'))
                ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
                ref_text = ' '.join(t.text or '' for t in root.iter(ns + 't'))
                result['reference_tables'] = sum(1 for _ in root.iter(ns + 'tbl'))
            else:
                names = sorted((n for n in z.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml', n)),
                               key=lambda n: int(re.search(r'(\d+)\.xml$', n)[1]))
                ns = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
                ref_text = ' '.join(t.text or '' for n in names for t in ET.fromstring(z.read(n)).iter(ns + 't'))
                result['reference_slides'] = len(names)
        words = lambda s: Counter(re.findall(r'\w+', s.casefold()))
        got, expected = words(body), words(ref_text)
        common = sum((got & expected).values())
        result['reference_word_recall'] = round(common / sum(expected.values()), 6) if expected else None
        result['reference_word_precision'] = round(common / sum(got.values()), 6) if got else None
        result['reference_words'] = sum(expected.values())
        # Bag-of-words is a diagnostic only, not a claim of ordering/table fidelity.
    return result


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory', type=Path)
    p.add_argument('--libreoffice', action='store_true')
    p.add_argument('--timeout', type=int, default=60)
    p.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    p.add_argument('--reference', type=Path, help=argparse.SUPPRESS)
    args = p.parse_args()
    if args.worker:
        print(json.dumps(_worker(args.directory, args.reference), ensure_ascii=False))
        return 0
    results = []
    for source in sorted(args.directory.iterdir()):
        if not source.is_file() or source.suffix.lower() not in ('.doc', '.ppt'):
            continue
        # Hash the stream without materialising a second copy of large personal input.
        with source.open('rb') as stream:
            file_id = hashlib.file_digest(stream, 'sha256').hexdigest()[:12]
        entry = {'id': file_id, 'bytes': source.stat().st_size}
        with tempfile.TemporaryDirectory(prefix='legacy-office-check-') as td:
            temp = Path(td)
            reference = None
            if args.libreoffice:
                copied = temp / ('input' + source.suffix.lower())
                shutil.copyfile(source, copied)
                target = 'docx' if source.suffix.lower() == '.doc' else 'pptx'
                command = ['libreoffice', '-env:UserInstallation=' + (temp / 'profile').as_uri(),
                           '--headless', '--convert-to', target, '--outdir', str(temp), str(copied)]
                started = time.perf_counter()
                try:
                    run = subprocess.run(command, capture_output=True, timeout=args.timeout)
                    candidate = temp / ('input.' + target)
                    if run.returncode == 0 and candidate.exists():
                        reference = candidate
                    else:
                        entry['reference_status'] = 'conversion_failed'
                except subprocess.TimeoutExpired:
                    entry['reference_status'] = 'timeout'
                entry['reference_seconds'] = round(time.perf_counter() - started, 4)
            cmd = [sys.executable, str(Path(__file__).resolve()), str(source.resolve()), '--worker']
            if reference:
                cmd.extend(['--reference', str(reference)])
            try:
                run = subprocess.run(cmd, capture_output=True, text=True, timeout=args.timeout)
                if run.returncode:
                    entry.update(status='worker_failed', returncode=run.returncode)
                else:
                    entry.update(json.loads(run.stdout))
            except subprocess.TimeoutExpired:
                entry['status'] = 'timeout'
            results.append(entry)
    print(json.dumps({'files': results}, ensure_ascii=False, indent=2))
    return int(not results or any(x['status'] not in ('ok', 'warning') for x in results))

if __name__ == '__main__':
    raise SystemExit(main())
