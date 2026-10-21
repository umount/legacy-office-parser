"""Original synthetic performance tooling; no LibreOffice required by unit tests."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

import pytest

from legacy_office_parser import parse

_spec = importlib.util.spec_from_file_location(
    'check_performance', Path(__file__).resolve().parents[1] / 'tools/check_performance.py')
perf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(perf)


@pytest.mark.parametrize('fmt', ['odt', 'rtf', 'ods', 'odp'])
def test_generated_content_and_deterministic_bytes(tmp_path, fmt):
    perf.generate(tmp_path, 'small')
    path = tmp_path / f'ordinary.{fmt}'
    first = path.read_bytes()
    doc = parse(path)
    counts, errors = perf.validate(doc, 'small')
    assert errors == []
    assert counts['text_chars'] > 1000
    perf.generate(tmp_path, 'small')
    assert path.read_bytes() == first
    if fmt in ('odt', 'rtf'):
        doc.blocks[0].text = 'lost content'
    elif fmt == 'ods':
        doc.sheets[0].cells[0].row += 1
    else:
        doc.slides.pop()
    assert perf.validate(doc, 'small')[1]


def test_table_loss_and_reorder_detected(tmp_path):
    perf.generate(tmp_path, 'small')
    doc = parse(tmp_path / 'ordinary.odt')
    doc.blocks[-1].rows[-1].pop()
    assert 'table_content_or_dimensions' in perf.validate(doc, 'small')[1]
    doc = parse(tmp_path / 'ordinary.odt')
    doc.blocks[0], doc.blocks[1] = doc.blocks[1], doc.blocks[0]
    assert 'paragraph_content_or_count' in perf.validate(doc, 'small')[1]


def test_worker_metrics(tmp_path):
    perf.generate(tmp_path, 'small')
    run = perf.bounded([sys.executable, perf.__file__, '--worker',
                        str(tmp_path / 'ordinary.ods'), 'small'], 10)
    assert run['status'] == 'ok'
    report = json.loads(run['stdout'])
    assert report['status'] == 'ok'
    assert 0 < report['parse_seconds'] < run['subprocess_seconds']
    assert report['peak_rss_kib'] > 0
    assert report['counts']['sheet_cells'] == 320


def test_parse_failure_is_privacy_safe(tmp_path):
    path = tmp_path / 'invalid.rtf'
    path.write_bytes(b'PRIVATE fake input')
    run = perf.bounded([sys.executable, perf.__file__, '--worker', str(path), 'small'], 10)
    report = json.loads(run['stdout'])
    assert report['status'] == 'parse_error'
    assert 'PRIVATE' not in run['stdout']
    assert str(path) not in run['stdout']


def test_timeout_kills_descendants(tmp_path):
    pidfile = tmp_path / 'pid'
    script = ('import subprocess,sys,time; '
              'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"]); '
              'open(sys.argv[1],"w").write(str(p.pid)); time.sleep(30)')
    run = perf.bounded([sys.executable, '-c', script, str(pidfile)], 0.5)
    assert run['status'] == 'timeout'
    assert run['subprocess_seconds'] < 5
    pid = int(pidfile.read_text())
    # A dead descendant may briefly remain a zombie until the host init reaps it.
    for _ in range(100):
        stat = Path(f'/proc/{pid}/stat')
        try:
            state = stat.read_text().split()[2]
        except FileNotFoundError:
            break  # init may reap the child at any point during observation.
        if state == 'Z':
            break
        time.sleep(0.01)
    else:
        os.kill(pid, 9)
        pytest.fail('descendant survived timeout')


def test_failed_child_and_missing_converter_are_not_success():
    assert perf.bounded([sys.executable, '-c', 'raise SystemExit(7)'], 5)['status'] == 'child_failed'
    report = perf.benchmark('small', libreoffice='/nonexistent/performance-lo')
    assert [r['status'] for r in report['results'][-3:]] == ['conversion_failed'] * 3


def test_no_converter_explicitly_skips_binary_formats():
    report = perf.benchmark('small')
    assert [r['status'] for r in report['results'][:4]] == ['ok'] * 4
    assert [r['status'] for r in report['results'][4:]] == ['skipped'] * 3


@pytest.mark.parametrize('value', ['0', '-1', 'nan', 'inf', '61'])
def test_invalid_timeout_rejected(value):
    run = perf.bounded([sys.executable, perf.__file__, '--timeout', value], 5)
    assert run['returncode'] == 2


def test_record_budget_has_safe_code_without_exposing_arbitrary_messages():
    from legacy_office_parser import LimitExceededError
    assert perf.failure_details(LimitExceededError('DOC record limit exceeded')) == {
        'error_type': 'LimitExceededError', 'limit_code': 'doc_record_budget'}
    assert perf.failure_details(LimitExceededError('private filename and text')) == {
        'error_type': 'LimitExceededError'}


def test_master_page_selected_only_by_first_body_paragraph(tmp_path):
    from zipfile import ZipFile
    import xml.etree.ElementTree as ET
    perf.generate(tmp_path, 'small')
    with ZipFile(tmp_path / 'ordinary.odt') as archive:
        root = ET.fromstring(archive.read('content.xml'))
    ns = {'text': 'urn:oasis:names:tc:opendocument:xmlns:text:1.0'}
    paragraphs = root.findall('.//text:p', ns)
    attr = '{' + ns['text'] + '}style-name'
    assert len(paragraphs) == 80
    assert paragraphs[0].attrib[attr] == 'Body'
    assert all(attr not in p.attrib for p in paragraphs[1:])
