#!/usr/bin/env python3
"""Author deterministic note relationships; optional isolated DOC round trip.

No parser imports, macros, external links, personal input, or runtime dependency.
The arbitrary OOXML IDs and repeated bodies deliberately prohibit text matching.
"""
import argparse
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
from xml.sax.saxutils import escape
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'tests/fixtures/doc_notes'
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'


def run(text):
    return '<w:r><w:t xml:space="preserve">' + escape(text) + '</w:t></w:r>'


def paragraph(content):
    return '<w:p>' + content + '</w:p>'


def reference(kind, ident, *, custom=False, hidden=False, deleted=False):
    mark = f'<w:{kind}Reference w:id="{ident}"' + (' w:customMarkFollows="1"' if custom else '') + '/>'
    body = '<w:r>' + ('<w:rPr><w:vanish/></w:rPr>' if hidden else '') + mark
    body += ('<w:t>*</w:t>' if custom else '') + '</w:r>'
    return ('<w:del w:id="9" w:author="Fixture" w:date="2026-01-01T00:00:00Z">'
            + body + '</w:del>') if deleted else body


def table(cells):
    width = 7200 // len(cells)
    return ('<w:tbl><w:tblPr><w:tblW w:w="7200" w:type="dxa"/>'
            '<w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid>'
            + f'<w:gridCol w:w="{width}"/>' * len(cells) + '</w:tblGrid><w:tr>'
            + ''.join(f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/></w:tcPr>'
                      + cell + '</w:tc>' for cell in cells) + '</w:tr></w:tbl>')


def generate_source(destination, *, unordered=False):
    # ID order intentionally differs from numbering and is not contiguous.
    body = paragraph(run('MainAstral😀A ') + reference('footnote', 11) + run(' after.'))
    body += paragraph(run('CustomAnchor ') + reference('footnote', 29, custom=True))
    nested = table([paragraph(run('InnerCell ') + reference('footnote', 57))])
    body += table([paragraph(run('OuterCell ') + reference('footnote', 41)),
                   nested + paragraph(run('OuterTail ') + reference('endnote', 93 if unordered else 17))])
    body += paragraph(run('EndMain ') + reference('endnote', 17 if unordered else 93))
    body += paragraph(run('HiddenAnchor ') + reference('footnote', 68, hidden=True))
    body += paragraph(run('DeletedAnchor ') + reference('footnote', 79, deleted=True))
    body += ('<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
             '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/>'
             '</w:sectPr>')
    documents = {'word/document.xml': f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'}
    for kind, notes in (
        ('footnote', [(11, 'Shared note.'), (29, 'Custom body.'), (41, 'Shared note.'),
                      (57, 'Note table.'), (68, 'Hidden reference body.'), (79, 'Deleted reference body.')]),
        ('endnote', ([(17, 'End main body.'), (93, 'End cell body.')] if unordered else
                     [(17, 'End cell body.'), (93, 'End main body.')])),
    ):
        parts = []
        for ident, text in notes:
            marker = run('*') if kind == 'footnote' and ident == 29 else f'<w:r><w:{kind}Ref/></w:r>'
            content = paragraph(marker + run(' ' + text))
            if kind == 'footnote' and ident == 57:
                content += table([paragraph(run('NoteTableCell'))]) + paragraph(run('NoteTail'))
            parts.append(f'<w:{kind} w:id="{ident}">{content}</w:{kind}>')
        documents[f'word/{kind}s.xml'] = f'<w:{kind}s xmlns:w="{W}">' + ''.join(parts) + f'</w:{kind}s>'
    types = 'http://schemas.openxmlformats.org/package/2006/content-types'
    rel = 'http://schemas.openxmlformats.org/package/2006/relationships'
    files = {
        '[Content_Types].xml': f'<Types xmlns="{types}"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '<Override PartName="/word/footnotes.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"/>'
            '<Override PartName="/word/endnotes.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.endnotes+xml"/></Types>',
        '_rels/.rels': f'<Relationships xmlns="{rel}"><Relationship Id="r1" Type="{R}/officeDocument" Target="word/document.xml"/></Relationships>',
        'word/_rels/document.xml.rels': f'<Relationships xmlns="{rel}"><Relationship Id="r1" Type="{R}/footnotes" Target="footnotes.xml"/>'
            f'<Relationship Id="r2" Type="{R}/endnotes" Target="endnotes.xml"/></Relationships>',
        **documents,
    }
    with ZipFile(destination, 'w') as archive:
        for name, text in files.items():
            info = ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, text.encode())


def convert_roundtrip(destination, source_name='authored', roundtrip_name='roundtrip'):
    from check_performance import bounded
    source = destination / (source_name + '.docx')
    for path, fmt, result_name in ((source, 'doc:MS Word 97', source_name + '.doc'),
                                  (destination / (source_name + '.doc'), 'docx:Office Open XML Text', roundtrip_name + '.docx')):
        with TemporaryDirectory(prefix='notes-convert-', dir=destination) as tmp:
            result = bounded([sys.executable, str(ROOT / 'tools/check_performance.py'),
                              '--convert-child', '/usr/bin/libreoffice', str(path.resolve()),
                              tmp, fmt], 45)
            if result['status'] != 'ok':
                raise RuntimeError(result)
            generated = Path(tmp) / (path.stem + '.' + fmt.split(':')[0])
            shutil.copyfile(generated, destination / result_name)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--convert', action='store_true')
    args = parser.parse_args()
    DEST.mkdir(parents=True, exist_ok=True)
    generate_source(DEST / 'authored.docx')
    generate_source(DEST / 'unordered.docx', unordered=True)
    if args.convert:
        convert_roundtrip(DEST)
        convert_roundtrip(DEST, 'unordered', 'unordered-roundtrip')
