"""Original two-paragraph section/table fixture; run with --convert for DOC."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'tools'))
from generate_doc_nested_fixture import p, table

DEST = Path(__file__).resolve().parent
section = ('<w:sectPr><w:type w:val="nextPage"/>'
           '<w:pgSz w:w="12240" w:h="15840"/>'
           '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/>'
           '</w:sectPr>')
second = p('Second paragraph').replace('<w:p>', '<w:p><w:pPr>' + section + '</w:pPr>', 1)
body = p('First paragraph') + second + table([[p('Left'), p('Right')]], [3600, 3600]) + p('After table') + section.replace('w:top="1440"', 'w:top="1800"')
files = {
    '[Content_Types].xml': ('<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '</Types>'),
    '_rels/.rels': ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        '</Relationships>'),
    'word/document.xml': ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                          '<w:body>' + body + '</w:body></w:document>'),
}
source = DEST / 'clean_section_before_table.docx'
with ZipFile(source, 'w') as archive:
    for name, content in files.items():
        entry = ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
        entry.compress_type = ZIP_DEFLATED
        archive.writestr(entry, content.encode())
if '--convert' in sys.argv:
    with tempfile.TemporaryDirectory(prefix='doc-sections-lo-') as profile:
        subprocess.run(['/usr/bin/libreoffice', '-env:UserInstallation=' + Path(profile).as_uri(),
                        '--headless', '--convert-to', 'doc:MS Word 97', '--outdir', str(DEST), str(source)],
                       env={**os.environ, 'SAL_USE_VCLPLUGIN': 'svp'}, check=True, timeout=60)
    assert source.with_suffix('.doc').is_file()
