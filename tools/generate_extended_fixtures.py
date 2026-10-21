#!/usr/bin/env python3
"""Build original extended fixtures; never import a parser or write expectations.

Only stdlib and LibreOffice are needed. Existing authored ODT/PPTX sources
are copied unchanged. Conversion runs in a fresh profile and process group.
"""
import argparse
import os
import math
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'tests/fixtures/extended'
NS = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
      'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
      'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
      'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
      'xmlns:number="urn:oasis:names:tc:opendocument:xmlns:datastyle:1.0" '
      'xmlns:of="urn:oasis:names:tc:opendocument:xmlns:of:1.2"')


def write_ods(path):
    def cell(kind, value, text, extra=''):
        attr = {'float': 'value', 'boolean': 'boolean-value', 'date': 'date-value'}.get(kind)
        typed = f' office:{attr}="{value}"' if attr else ''
        return (f'<table:table-cell office:value-type="{kind}"{typed} {extra}>'
                f'<text:p>{escape(text)}</text:p></table:table-cell>')

    def row(cells):
        return '<table:table-row>' + ''.join(cells) + '</table:table-row>'

    empty = '<table:table-cell/>'
    body = ('<table:table table:name="Данные">'
            '<table:table-column table:number-columns-repeated="6"/>'
            + row([cell('string', '', 'Label / Метка'), cell('string', '', 'Значение'),
                   empty, cell('string', '', 'Sparse / Разрежено')])
            + row([cell('string', '', 'alpha beta'), cell('float', '12.5', '12.5'), empty,
                   cell('boolean', 'true', 'TRUE'),
                   cell('date', '2024-02-29', '2024-02-29', 'table:style-name="Date"'),
                   cell('float', '25', '25', 'table:formula="of:=[.B2]*2"')])
            + '<table:table-row table:number-rows-repeated="2"><table:table-cell '
              'table:number-columns-repeated="6"/></table:table-row>'
            + row([cell('string', '', 'Общий итог', 'table:number-columns-spanned="2"'),
                   '<table:covered-table-cell/>', empty, cell('float', '-7', '-7')])
            + row([empty, empty, cell('boolean', 'false', 'FALSE')])
            + '</table:table><table:table table:name="Пустой">'
              '<table:table-column/><table:table-row><table:table-cell/>'
              '</table:table-row></table:table>')
    styles = ('<office:automatic-styles><number:date-style style:name="ISODate">'
              '<number:year number:style="long"/><number:text>-</number:text>'
              '<number:month number:style="long"/><number:text>-</number:text>'
              '<number:day number:style="long"/></number:date-style>'
              '<style:style style:name="Date" style:family="table-cell" '
              'style:data-style-name="ISODate"/></office:automatic-styles>')
    content = (f'<?xml version="1.0" encoding="UTF-8"?><office:document-content {NS} '
               f'office:version="1.2">{styles}<office:body><office:spreadsheet>{body}'
               '</office:spreadsheet></office:body></office:document-content>')
    mime = 'application/vnd.oasis.opendocument.spreadsheet'
    manifest = ('<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" '
                'manifest:version="1.2">'
                f'<manifest:file-entry manifest:full-path="/" manifest:media-type="{mime}"/>'
                '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>'
                '</manifest:manifest>')
    with ZipFile(path, 'w') as archive:
        for name, data in [('mimetype', mime), ('content.xml', content), ('META-INF/manifest.xml', manifest)]:
            entry = ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            entry.compress_type = ZIP_STORED if name == 'mimetype' else ZIP_DEFLATED
            archive.writestr(entry, data.encode('utf-8'))


def write_rtf(path):
    def text(value):
        return ''.join('\\' + c if c in '\\{}' else c if ord(c) < 128
                       else f'\\u{ord(c) if ord(c) < 32768 else ord(c)-65536}?' for c in value)
    rows = [('Key', 'Value', 'Примечание'), ('alpha beta', '', 'два слова'),
            ('', '42', 'English and русский')]
    out = ['{\\rtf1\\ansi\\ansicpg1252\\uc1\n',
           text('Synthetic document / Синтетический документ') + '\\par\n']
    for values in rows:
        out.append('\\trowd\\cellx2400\\cellx4800\\cellx7200\n')
        out.extend('\\pard\\intbl ' + text(value) + '\\cell\n' for value in values)
        out.append('\\row\n')
    out.append('\\pard ' + text('After table / После таблицы') + '\\par\n}')
    path.write_text(''.join(out), encoding='ascii')


def convert(lo, source, work, fmt, timeout):
    # A separate profile per invocation prevents forwarding to any user's session.
    with tempfile.TemporaryDirectory(prefix='profile-', dir=work) as profile:
        command = [lo, '-env:UserInstallation=' + Path(profile).as_uri(), '--headless',
                   '--nologo', '--nodefault', '--nofirststartwizard', '--convert-to', fmt,
                   '--outdir', str(work), str(source)]
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, start_new_session=True,
                                env={**os.environ, 'SAL_USE_VCLPLUGIN': 'svp',
                                     'GSETTINGS_BACKEND': 'memory', 'DCONF_PROFILE': '/dev/null'})
        try:
            output, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
            raise RuntimeError(f'LibreOffice timed out: {source.name}') from None
        if proc.returncode:
            raise RuntimeError(f'LibreOffice failed: {output}')
        target = work / (source.stem + '.' + fmt.split(':')[0])
        if not target.is_file() or not target.stat().st_size:
            raise RuntimeError(f'LibreOffice produced no output: {output}')
        if target.suffix == '.xls':
            if target.read_bytes()[:8] != bytes.fromhex('d0cf11e0a1b11ae1'):
                raise RuntimeError('XLS export is not an OLE compound document')
        else:
            with ZipFile(target) as package:
                assert package.read('mimetype') == b'application/vnd.oasis.opendocument.presentation'
                assert package.testzip() is None
        print(output.strip())
        return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--libreoffice', default='libreoffice')
    parser.add_argument('--timeout', type=float, default=45)
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('--timeout must be positive')
    sources = DEST / 'sources'
    sources.mkdir(parents=True, exist_ok=True)
    for name in ('ordinary_table.odt', 'merged_table.odt'):
        shutil.copyfile(ROOT / 'tests/fixtures/sources' / name, DEST / name)
    shutil.copyfile(ROOT / 'tests/fixtures/sources/slides_notes.pptx', sources / 'slides_notes.pptx')
    write_rtf(DEST / 'ordinary_table.rtf')
    write_ods(sources / 'typed_sparse.ods')
    shutil.copyfile(sources / 'typed_sparse.ods', DEST / 'typed_sparse.ods')
    with tempfile.TemporaryDirectory(prefix='extended-office-') as temp:
        work = Path(temp)
        for source, fmt in [(sources / 'typed_sparse.ods', 'xls:MS Excel 97'),
                            (sources / 'slides_notes.pptx', 'odp:impress8')]:
            target = convert(args.libreoffice, source, work, fmt, args.timeout)
            shutil.copyfile(target, DEST / target.name)
    print('Hand-authored expectations were not modified.')


if __name__ == '__main__':
    main()
