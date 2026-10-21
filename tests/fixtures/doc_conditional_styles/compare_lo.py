"""Developer-only: /usr/bin/python3 compare_lo.py; connect to isolated LO :20172.

Start LO with a fresh UserInstallation and --headless
--accept='socket,host=localhost,port=20172;urp;StarOffice.ComponentContext'.
Never interpret raw DOCX text as visible text. PDF export is the print oracle.
"""
from pathlib import Path
import hashlib
import json
import subprocess
import tempfile
import uno

ROOT = Path(__file__).resolve().parent

def prop(name, value):
    p = uno.createUnoStruct('com.sun.star.beans.PropertyValue')
    p.Name, p.Value = name, value
    return p

local = uno.getComponentContext()
resolver = local.ServiceManager.createInstanceWithContext('com.sun.star.bridge.UnoUrlResolver', local)
ctx = resolver.resolve('uno:socket,host=localhost,port=20172;urp;StarOffice.ComponentContext')
desktop = ctx.ServiceManager.createInstanceWithContext('com.sun.star.frame.Desktop', ctx)
report = {'version': subprocess.check_output(['libreoffice', '--version'], text=True).strip(), 'files': {}}
with tempfile.TemporaryDirectory(prefix='doc-style-visible-') as temp:
    for mode in ('disabled', 'header', 'corner'):
        path = ROOT / (mode + '.doc')
        doc = desktop.loadComponentFromURL(path.as_uri(), '_blank', 0, (
            prop('Hidden', True), prop('ReadOnly', True), prop('MacroExecutionMode', uno.getConstantByName('com.sun.star.document.MacroExecMode.NEVER_EXECUTE')),
            prop('UpdateDocMode', 0)))
        try:
            settings = doc.createInstance('com.sun.star.text.DocumentSettings')
            settings.setPropertyValue('PrintHiddenText', False)
            settings.setPropertyValue('PrintTextPlaceholder', False)
            view = doc.CurrentController.ViewSettings
            view.setPropertyValue('ShowHiddenCharacters', False)
            view.setPropertyValue('ShowHiddenParagraphs', False)
            rows = []
            for name in doc.TextTables.ElementNames:
                table = doc.TextTables.getByName(name)
                rows.append({cell: table.getCellByName(cell).String for cell in table.CellNames})
            pdf = Path(temp) / (mode + '.pdf')
            doc.storeToURL(pdf.as_uri(), (prop('FilterName', 'writer_pdf_Export'),))
            visible = subprocess.check_output(['pdftotext', '-layout', str(pdf), '-'], text=True)
            report['files'][mode] = {
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'stored_table_text': rows, 'pdf_visible_text': visible,
                'PrintHiddenText': settings.getPropertyValue('PrintHiddenText'),
                'ShowHiddenCharacters': view.getPropertyValue('ShowHiddenCharacters'),
                'ShowHiddenParagraphs': view.getPropertyValue('ShowHiddenParagraphs'),
            }
        finally:
            doc.close(True)
(ROOT / 'lo-comparison.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(report, ensure_ascii=False, indent=2))
