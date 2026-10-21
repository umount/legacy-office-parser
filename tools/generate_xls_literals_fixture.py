#!/usr/bin/env python3
"""Authored numeric units: ODS source and independently converted XLS fixture."""
from pathlib import Path
import shutil
import tempfile
from xml.sax.saxutils import escape
from zipfile import ZipFile

from generate_xls_formats_fixture import write_ods
from generate_extended_fixtures import convert

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'tests/fixtures/xls_literals'


def generate_source(destination):
    # Reuse only package/namespace boilerplate, replacing all styles and rows.
    with tempfile.TemporaryDirectory() as tmp:
        original = Path(tmp) / 'base.ods'
        write_ods(original)
        with ZipFile(original) as archive:
            files = [(info, archive.read(info.filename)) for info in archive.infolist()]
    formats = [
        ('Mass', '', ' kg', 2), ('Currency', 'USD ', '', 2),
        ('PercentLiteral', '', '%', 2), ('Days', '', 'days', 0),
        ('Cyrillic', '', ' руб.', 2), ('EscapedText', 'ID ', ' units', 2),
    ]
    styles = ''
    for name, before, after, places in formats:
        styles += (f'<number:number-style style:name="{name}">'
                   f'<number:text>{escape(before)}</number:text>'
                   f'<number:number number:decimal-places="{places}" number:min-integer-digits="1"/>'
                   f'<number:text>{escape(after)}</number:text></number:number-style>'
                   f'<style:style style:name="C{name}" style:family="table-cell" '
                   f'style:data-style-name="{name}"><style:text-properties '
                   'fo:language="en" fo:country="US"/></style:style>')
    rows = [
        ('Mass', 'Mass', '12.5', '12.50 kg'),
        ('Negative mass', 'Mass', '-12.5', '-12.50 kg'),
        ('Currency', 'Currency', '12.5', 'USD 12.50'),
        ('Negative currency', 'Currency', '-12.5', '-USD 12.50'),
        ('Literal percent', 'PercentLiteral', '0.125', '0.13%'),
        ('Days', 'Days', '3', '3days'),
        ('Cyrillic', 'Cyrillic', '42', '42.00 руб.'),
        ('Both sides', 'EscapedText', '2', 'ID 2.00 units'),
    ]
    body = ''.join('<table:table-row><table:table-cell office:value-type="string">'
        f'<text:p>{label}</text:p></table:table-cell><table:table-cell '
        f'table:style-name="C{style}" office:value-type="float" office:value="{value}">'
        f'<text:p>{escape(display)}</text:p></table:table-cell></table:table-row>'
        for label, style, value, display in rows)
    with ZipFile(destination, 'w') as out:
        for info, content in files:
            if info.filename == 'content.xml':
                xml = content.decode()
                start = xml.index('<office:automatic-styles>') + len('<office:automatic-styles>')
                end = xml.index('</office:automatic-styles>')
                xml = xml[:start] + styles + xml[end:]
                start = xml.index('<table:table-row>')
                end = xml.index('</table:table>')
                xml = xml[:start] + body + xml[end:]
                content = xml.encode()
            out.writestr(info, content)


if __name__ == '__main__':
    DEST.mkdir(parents=True, exist_ok=True)
    source = DEST / 'literal_formats.ods'
    generate_source(source)
    with tempfile.TemporaryDirectory(prefix='xls-literals-') as tmp:
        result = convert('/usr/bin/libreoffice', source, Path(tmp), 'xls:MS Excel 97', 45)
        shutil.copyfile(result, DEST / result.name)
