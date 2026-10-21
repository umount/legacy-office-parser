#!/usr/bin/env python3
"""Generate an original, minimal DOCX and optionally convert it with LibreOffice.

No personal/external input. Run from any directory:
  .venv/bin/python tools/generate_doc_nested_fixture.py --convert
DOCX ZIP entries have fixed timestamps. DOC metadata can vary with LO version.
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

DEST = Path(__file__).resolve().parents[1] / 'tests' / 'fixtures' / 'doc_nested'


def p(text):
    return '<w:p><w:r><w:t>' + escape(text) + '</w:t></w:r></w:p>'


def table(rows, widths):
    properties = ('<w:tblPr><w:tblW w:w="%d" w:type="dxa"/>'
                  '<w:tblLayout w:type="fixed"/></w:tblPr>') % sum(widths)
    grid = '<w:tblGrid>' + ''.join('<w:gridCol w:w="%d"/>' % w for w in widths) + '</w:tblGrid>'
    return '<w:tbl>' + properties + grid + ''.join(
        '<w:tr>' + ''.join('<w:tc><w:tcPr><w:tcW w:w="%d" w:type="dxa"/></w:tcPr>%s</w:tc>' %
                          (width, content) for width, content in zip(widths, row)) + '</w:tr>'
        for row in rows) + '</w:tbl>'


def generate():
    deep = table([[p('DeepLeaf')]], [1800])
    middle = table([[p('InnerA'), deep + p('DeepTail')], [p('InnerC'), p('InnerD')]], [2400, 2400])
    sibling = table([[p('SiblingLeaf')]], [4800])
    outer = table([[middle + p('Between') + sibling + p('OuterTail'), p('OuterRight')]], [4800, 2400])
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body>' + p('Before') + outer + p('After') +
                '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
                '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/>'
                '</w:sectPr></w:body></w:document>')
    files = {
        '[Content_Types].xml': ('<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '</Types>'),
        '_rels/.rels': ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '</Relationships>'),
        'word/document.xml': document,
    }
    DEST.mkdir(parents=True, exist_ok=True)
    source = DEST / 'own_nested.docx'
    with ZipFile(source, 'w') as archive:
        for name, content in files.items():
            entry = ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            entry.compress_type = ZIP_DEFLATED
            archive.writestr(entry, content.encode())
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--convert', action='store_true')
    args = parser.parse_args()
    source = generate()
    if args.convert:
        with tempfile.TemporaryDirectory(prefix='doc-nested-lo-') as profile:
            subprocess.run(['/usr/bin/libreoffice', '-env:UserInstallation=' + Path(profile).as_uri(),
                '--headless', '--convert-to', 'doc:MS Word 97', '--outdir', str(DEST), str(source)],
                env={**os.environ, 'SAL_USE_VCLPLUGIN': 'svp'}, check=True, timeout=60)
        if not source.with_suffix('.doc').is_file():
            raise RuntimeError('LibreOffice did not create the DOC fixture')


if __name__ == '__main__':
    main()
