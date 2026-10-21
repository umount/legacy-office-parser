"""Extraction must not dereference document-controlled resources or execute code.

Audit hooks run in a child because they cannot be removed from a Python process.
These are behavioral regression tests, not reproductions of native-code exploits.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_odf import package

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('resource', [
    'file:///etc/passwd', 'http://127.0.0.1:9/data',
    'vnd.sun.star.expand:${HOME}/private',
])
@pytest.mark.parametrize('kind', ['rtf', 'odt', 'ods', 'odp'])
def test_document_resources_are_inert(kind, resource):
    if kind == 'rtf':
        data = (rb'{\rtf1 before '
                rb'{\field{\*\fldinst INCLUDETEXT "file:///etc/passwd"}{\fldrslt cached}}'
                rb'{\field{\*\fldinst DDEAUTO cmd " /c echo injected"}{\fldrslt cached}}'
                rb'{\object\objemb{\*\objclass Package}{\*\objdata 01020304}}'
                rb'{\field{\*\fldinst HYPERLINK "http://127.0.0.1:9/secret"}'
                rb'{\fldrslt link}} after}')
    else:
        content = '''<office:document-content
          xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
          xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
          xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"
          xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
          xmlns:script="urn:oasis:names:tc:opendocument:xmlns:script:1.0"
          xmlns:xlink="http://www.w3.org/1999/xlink">
          <office:scripts><office:script script:language="Python">raise Exception()</office:script></office:scripts>
          <office:body><office:text><text:p>before
          <text:a xlink:href="file:///etc/passwd">link</text:a>
          <text:section-source xlink:href="http://127.0.0.1:9/secret"/>
          <draw:frame><draw:object xlink:href="../../outside"/></draw:frame>
          <draw:frame><draw:object-ole xlink:href="file:///etc/passwd"/></draw:frame>
          <draw:frame><draw:image xlink:href="http://127.0.0.1:9/image"/></draw:frame>
          after</text:p></office:text></office:body></office:document-content>'''
        if kind == 'ods':
            content = content.replace('<office:text>', '<office:spreadsheet><table:table><table:table-row><table:table-cell>')
            content = content.replace('</office:text>', '</table:table-cell></table:table-row></table:table></office:spreadsheet>')
            content = content.replace('<table:table>',
                '<table:table><table:table-source xlink:href="' + resource + '"/>', 1)
            content = content.replace('<table:table-cell>',
                '<table:table-cell table:formula="of:=WEBSERVICE(&quot;' + resource + '&quot;)">', 1)
        elif kind == 'odp':
            content = content.replace('<office:text>', '<office:presentation><draw:page><draw:frame><draw:text-box>')
            content = content.replace('</office:text>', '</draw:text-box></draw:frame></draw:page></office:presentation>')
        content = content.replace('file:///etc/passwd', resource)
        data = package(fmt=kind, content=content, extra={
            '../../outside': b'not extracted',
            'Scripts/python/payload.py': b'raise Exception("not executed")',
        })
    if kind == 'rtf':
        data = data.replace(b'file:///etc/passwd', resource.encode('ascii'))
    child = r'''
import json, sys
from pathlib import Path
from legacy_office_parser import parse
# Warm supported formats and lazy codec imports before installing the sentinel.
root = Path(sys.argv[1])
for name in ['ordinary_table.doc', 'slides_notes.ppt', 'extended/typed_sparse.xls',
             'extended/ordinary_table.rtf', 'extended/ordinary_table.odt',
             'extended/typed_sparse.ods', 'extended/slides_notes.odp']:
    parse((root / name).read_bytes())
data = sys.stdin.buffer.read()
forbidden = []
def audit(event, args):
    if (event == 'open' or event.startswith(('socket.', 'subprocess.', 'os.exec',
        'os.spawn', 'os.system', 'os.remove', 'os.rename', 'os.mkdir', 'ctypes.dlopen'))):
        forbidden.append(event)
        raise AssertionError('document triggered external effect: ' + event)
sys.addaudithook(audit)
doc = parse(data)
assert not forbidden, forbidden
assert 'before' in doc.text and 'after' in doc.text
assert 'root:' not in doc.text
print(json.dumps({'effects': forbidden, 'parsed': True}))
'''
    result = subprocess.run([sys.executable, '-c', child, str(ROOT / 'tests/fixtures')],
                            input=data, capture_output=True, timeout=15, cwd=ROOT,
                            env={**os.environ, 'PYTHONPATH': os.pathsep.join(
                                [str(ROOT / 'src'), os.environ.get('PYTHONPATH', '')])})
    assert result.returncode == 0, result.stderr.decode()
    assert json.loads(result.stdout) == {'effects': [], 'parsed': True}
