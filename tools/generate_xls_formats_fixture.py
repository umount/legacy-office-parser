#!/usr/bin/env python3
"""Original numeric-format ODS/XLS fixture; never derive expected values from a parser."""
import argparse
from pathlib import Path
import shutil
import tempfile
from xml.sax.saxutils import escape
from zipfile import ZipFile, ZipInfo, ZIP_STORED, ZIP_DEFLATED

from generate_extended_fixtures import NS, convert

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'tests/fixtures/xls_formats'


def write_ods(path):
    formats = [
        ('Pct', '<number:percentage-style style:name="Pct"><number:number '
         'number:decimal-places="2" number:min-integer-digits="1"/>'
         '<number:text>%</number:text></number:percentage-style>'),
        ('Fixed', '<number:number-style style:name="Fixed"><number:number '
         'number:decimal-places="2" number:min-integer-digits="1"/></number:number-style>'),
        ('Grouped', '<number:number-style style:name="Grouped"><number:number '
         'number:decimal-places="2" number:min-integer-digits="1" '
         'number:grouping="true"/></number:number-style>'),
        ('Scientific', '<number:number-style style:name="Scientific"><number:scientific-number '
         'number:decimal-places="2" number:min-integer-digits="1" '
         'number:min-exponent-digits="2"/></number:number-style>'),
    ]
    rows = [
        ('Percent', 'Pct', '0.125', '12.50%', ''),
        ('Negative percent', 'Pct', '-0.25', '-25.00%', ''),
        ('Decimal', 'Fixed', '12.5', '12.50', ''),
        ('Grouped', 'Grouped', '12345.5', '12,345.50', ''),
        ('Scientific', 'Scientific', '12345', '1.23E+04', ''),
        ('Cached formula', 'Pct', '0.25', '25.00%', 'of:=1/4'),
        ('Zero', 'Pct', '0', '0.00%', ''),
    ]
    styles = ''.join(xml for _, xml in formats)
    styles += ''.join(f'<style:style style:name="C{name}" style:family="table-cell" '
                      f'style:data-style-name="{name}"><style:text-properties '
                      'fo:language="en" fo:country="US"/></style:style>' for name, _ in formats)
    body = ''
    for label, style, value, text, formula in rows:
        attr = f' table:formula="{escape(formula)}"' if formula else ''
        body += ('<table:table-row><table:table-cell office:value-type="string">'
                 f'<text:p>{label}</text:p></table:table-cell>'
                 f'<table:table-cell table:style-name="C{style}" office:value-type="float" '
                 f'office:value="{value}"{attr}><text:p>{text}</text:p>'
                 '</table:table-cell></table:table-row>')
    content = (f'<office:document-content {NS} '
               'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
               f'office:version="1.2"><office:automatic-styles>{styles}</office:automatic-styles>'
               '<office:body><office:spreadsheet><table:table table:name="Numbers">'
               '<table:table-column table:number-columns-repeated="2"/>' + body +
               '</table:table></office:spreadsheet></office:body></office:document-content>')
    mime = 'application/vnd.oasis.opendocument.spreadsheet'
    manifest = ('<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0">'
                f'<manifest:file-entry manifest:full-path="/" manifest:media-type="{mime}"/>'
                '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>'
                '</manifest:manifest>')
    with ZipFile(path, 'w') as archive:
        for name, text in [('mimetype', mime), ('content.xml', content), ('META-INF/manifest.xml', manifest)]:
            info = ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_STORED if name == 'mimetype' else ZIP_DEFLATED
            archive.writestr(info, text.encode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--libreoffice', default='/usr/bin/libreoffice')
    args = parser.parse_args()
    DEST.mkdir(parents=True, exist_ok=True)
    source = DEST / 'numeric_formats.ods'
    write_ods(source)
    with tempfile.TemporaryDirectory(prefix='xls-formats-') as tmp:
        output = convert(args.libreoffice, source, Path(tmp), 'xls:MS Excel 97', 45)
        shutil.copyfile(output, DEST / output.name)


if __name__ == '__main__':
    main()
