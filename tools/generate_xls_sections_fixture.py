#!/usr/bin/env python3
"""Original sign-section workbook; OOXML source supplies exact authored masks."""
from pathlib import Path
import shutil
import tempfile
from xml.sax.saxutils import escape, quoteattr
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

from generate_extended_fixtures import convert

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'tests/fixtures/xls_sections'
NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'


def generate_source(destination):
    formats = ['0.00;(0.00);"zero"', '0.00%;[Red]-0.00%;0.00%',
               '"USD "0.00;("USD "0.00);"none"',
               '0.00";ok";-0.00";bad";"zero;none"',
               '0.00;0.00;"zero";@']
    rows = [('Positive', 12.5, 0), ('Negative', -12.5, 0), ('Zero', 0, 0),
            ('Negative percent', -.25, 1), ('Negative currency', -12.5, 2),
            ('Quoted semicolon', -12.5, 3), ('Unsigned negative', -12.5, 4),
            ('Rounded negative', -.001, 0), ('Cached formula', -.25, 1)]
    styles = f'<styleSheet xmlns="{NS}"><numFmts count="{len(formats)}">'
    styles += ''.join(f'<numFmt numFmtId="{164+i}" formatCode={quoteattr(fmt)}/>'
                      for i, fmt in enumerate(formats))
    styles += ('</numFmts><fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
               '<fills count="2"><fill><patternFill patternType="none"/></fill>'
               '<fill><patternFill patternType="gray125"/></fill></fills>'
               '<borders count="1"><border/></borders>'
               '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
               f'<cellXfs count="{len(formats)+1}"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>')
    styles += ''.join(f'<xf numFmtId="{164+i}" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
                      for i in range(len(formats)))
    styles += '</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'
    sheet = f'<worksheet xmlns="{NS}"><sheetData>'
    for i, (label, value, fmt) in enumerate(rows, 1):
        formula = '<f>-1/4</f>' if label == 'Cached formula' else ''
        sheet += (f'<row r="{i}"><c r="A{i}" t="inlineStr"><is><t>{escape(label)}</t></is></c>'
                  f'<c r="B{i}" s="{fmt+1}">{formula}<v>{value}</v></c></row>')
    sheet += '</sheetData></worksheet>'
    types = 'http://schemas.openxmlformats.org/package/2006/content-types'
    rels = 'http://schemas.openxmlformats.org/package/2006/relationships'
    office = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    files = {
        '[Content_Types].xml': f'<Types xmlns="{types}"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        '_rels/.rels': f'<Relationships xmlns="{rels}"><Relationship Id="rId1" Type="{office}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        'xl/workbook.xml': f'<workbook xmlns="{NS}" xmlns:r="{office}"><sheets><sheet name="Sections" sheetId="1" r:id="rId1"/></sheets></workbook>',
        'xl/_rels/workbook.xml.rels': f'<Relationships xmlns="{rels}"><Relationship Id="rId1" Type="{office}/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="{office}/styles" Target="styles.xml"/></Relationships>',
        'xl/styles.xml': styles,
        'xl/worksheets/sheet1.xml': sheet,
    }
    with ZipFile(destination, 'w') as archive:
        for name, xml in files.items():
            info = ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, xml.encode())


if __name__ == '__main__':
    DEST.mkdir(parents=True, exist_ok=True)
    source = DEST / 'sign_sections.xlsx'
    generate_source(source)
    with tempfile.TemporaryDirectory(prefix='xls-sections-') as tmp:
        result = convert('/usr/bin/libreoffice', source, Path(tmp), 'xls:MS Excel 97', 45)
        shutil.copyfile(result, DEST / result.name)
