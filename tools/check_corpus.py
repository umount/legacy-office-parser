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
import os
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile


_TARGETS = {'.doc': 'docx', '.rtf': 'docx', '.odt': 'docx', '.xls': 'xlsx',
            '.ods': 'xlsx', '.ppt': 'pptx', '.odp': 'pptx'}

_W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
_MC = '{http://schemas.openxmlformats.org/markup-compatibility/2006}'


def _selected_children(element):
    """Use one representation of AlternateContent, preferring its first Choice."""
    if element.tag == _MC + 'AlternateContent':
        branch = element.find(_MC + 'Choice')
        if branch is None:
            branch = element.find(_MC + 'Fallback')
        return () if branch is None else (branch,)
    return element


def _docx_text(root, *, textboxes_only=False):
    """Join inline runs; collect textbox stories independently of anchor paragraphs."""
    boxes = []
    tables = 0

    def visit(element):
        nonlocal tables
        if element.tag == _W + 't':
            return element.text or ''
        if element.tag in (_W + 'tab', _W + 'br', _W + 'cr'):
            return '\n'
        if element.tag == _W + 'noBreakHyphen':
            return '\u2011'
        if element.tag == _W + 'softHyphen':
            return '\u00ad'
        if element.tag == _W + 'tbl':
            tables += 1
        value = ''.join(visit(child) for child in _selected_children(element))
        if element.tag == _W + 'txbxContent':
            boxes.append(value)
            return ''
        if element.tag in (_W + 'p', _W + 'tc'):
            value += '\n'
        return value

    body = visit(root)
    return '\n'.join(([] if textboxes_only else [body]) + boxes), tables


def _docx_reference(archive):
    body, tables = _docx_text(ET.fromstring(archive.read('word/document.xml')))
    parts = [body]
    # The model pools main-story and header/footer textboxes in doc.textboxes.
    # Include those boxes, but exclude ordinary header/footer text on both sides.
    for name in sorted(archive.namelist()):
        if re.fullmatch(r'word/(?:header|footer)\d+\.xml', name):
            boxes, _ = _docx_text(ET.fromstring(archive.read(name)), textboxes_only=True)
            parts.append(boxes)
    return '\n'.join(parts), tables


def _worker(source: Path, reference: Path | None) -> dict:
    from legacy_office_parser import parse, ParseError, Paragraph
    start = time.perf_counter()
    try:
        doc = parse(source)
    except ParseError as exc:
        return {'status': 'parse_error', 'error': type(exc).__name__}
    body = '\n'.join(b.text if isinstance(b, Paragraph) else '\n'.join(
        '\t'.join(c.text for c in row) for row in b.rows) for b in doc.blocks)
    if doc.format in ('ppt', 'odp'):
        body = '\n'.join('\n'.join((s.title, s.text)) for s in doc.slides)
    else:
        body += '\n' + doc.textboxes
    result = {
        'status': 'warning' if doc.warnings else 'ok',
        'format': doc.format,
        'text_chars': len(doc.text),
        'tables': sum(b.kind == 'table' for b in doc.blocks),
        'slides': len(doc.slides),
        'sheets': len(doc.sheets),
        'cells': sum(len(sheet.cells) for sheet in doc.sheets),
        'warnings': doc.warnings,
        'parse_seconds': round(time.perf_counter() - start, 4),
        'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }
    if reference:
        with zipfile.ZipFile(reference) as z:
            if doc.format in ('doc', 'rtf', 'odt'):
                ref_text, result['reference_tables'] = _docx_reference(z)
            elif doc.format in ('xls', 'ods'):
                # Formatted numeric/date text cannot be compared against raw XLSX
                # values. Exact cell semantics are covered by authored fixtures.
                ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
                names = [n for n in z.namelist()
                         if re.fullmatch(r'xl/worksheets/sheet\d+\.xml', n)]
                result['reference_sheets'] = len(names)
                result['reference_cells'] = sum(
                    1 for n in names for cell in ET.fromstring(z.read(n)).iter(ns + 'c')
                    if any(cell.find(ns + tag) is not None for tag in ('v', 'is', 'f')))
                result['reference_scope'] = 'sheet and populated cell counts only'
                return result
            else:
                names = sorted((n for n in z.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml', n)),
                               key=lambda n: int(re.search(r'(\d+)\.xml$', n)[1]))
                ns = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
                ref_text = '\n'.join(''.join(t.text or '' for t in para.iter(ns + 't'))
                                     for n in names for para in ET.fromstring(z.read(n)).iter(ns + 'p'))
                result['reference_slides'] = len(names)
        def words(s):
            return Counter(re.findall(r'\w+', s.casefold()))
        got, expected = words(body), words(ref_text)
        common = sum((got & expected).values())
        result['reference_word_recall'] = round(common / sum(expected.values()), 6) if expected else None
        result['reference_word_precision'] = round(common / sum(got.values()), 6) if got else None
        result['reference_words'] = sum(expected.values())
        result['reference_nonspace_equal'] = (re.sub(r'\s+', '', body) ==
                                              re.sub(r'\s+', '', ref_text))
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
    sources = [args.directory] if args.directory.is_file() else sorted(args.directory.iterdir())
    for source in sources:
        if not source.is_file() or source.suffix.lower() not in _TARGETS:
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
                target = _TARGETS[source.suffix.lower()]
                command = ['libreoffice', '-env:UserInstallation=' + (temp / 'profile').as_uri(),
                           '--headless', '--convert-to', target, '--outdir', str(temp), str(copied)]
                started = time.perf_counter()
                try:
                    with subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                          start_new_session=True) as run:
                        try:
                            run.wait(timeout=args.timeout)
                        except subprocess.TimeoutExpired:
                            os.killpg(run.pid, signal.SIGKILL)
                            run.wait()
                            raise
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
    return int(not results or any(x['status'] not in ('ok', 'warning') or
                                 'reference_status' in x for x in results))

if __name__ == '__main__':
    raise SystemExit(main())
