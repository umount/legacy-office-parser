"""Research fixtures only; no production behavior changes or private documents."""
from io import BytesIO
import os
from pathlib import Path
import subprocess
from zipfile import ZipFile, ZIP_STORED

import pytest

from test_odf_inline_objects import DECL, NS, PREVIEW, embedded, p, table, _UNO_READER


def fixtures():
    shape_parts = []
    for kind in ('rect', 'ellipse', 'custom-shape'):
        shape_parts.append(f'<draw:{kind} draw:name="{kind}" text:anchor-type="as-char" '
                           'svg:width="4cm" svg:height="2cm">' + p(kind + ' paragraph') +
                           '<text:list><text:list-item>' + p(kind + ' list') +
                           f'</text:list-item></text:list></draw:{kind}>')
    shapes = p('Host before' + ''.join(shape_parts) + 'Host after')
    image = PREVIEW.replace('</draw:image>', p('Image attached paragraph') +
                            '<text:list><text:list-item>' + p('Image attached list') +
                            '</text:list-item></text:list></draw:image>')
    image = p('<draw:frame draw:name="AttachedImage" text:anchor-type="as-char" '
              'svg:width="4cm" svg:height="2cm">' + image +
              '<svg:desc>Metadata decoy</svg:desc></draw:frame>')
    obj = ('<draw:frame draw:name="InlineWriter" svg:x="1cm" svg:y="1cm" '
           'svg:width="8cm" svg:height="4cm">' + embedded(
               p('Object before') + table(p('Object cell')) + p('Object after')) + '</draw:frame>')
    return {
        'shapes.odt': ('text', shapes),
        'image.odt': ('text', image),
        'inline.ods': ('spreadsheet', '<table:table table:name="Sheet1"><table:shapes>' + obj +
                       '</table:shapes><table:table-column/><table:table-row>'
                       '<table:table-cell office:value-type="string">' + p('Host cell') +
                       '</table:table-cell></table:table-row></table:table>'),
        'inline.odp': ('presentation', '<draw:page draw:name="Page1" draw:master-page-name="Default">' + obj + '</draw:page>'),
    }


def package(kind, body):
    mime = 'application/vnd.oasis.opendocument.' + kind
    content = (f'<office:document-content {DECL} office:version="1.3"><office:body>'
               f'<office:{kind}>{body}</office:{kind}></office:body></office:document-content>')
    manifest = (f'<manifest:manifest xmlns:manifest="{NS["manifest"]}" manifest:version="1.3">'
                f'<manifest:file-entry manifest:full-path="/" manifest:media-type="{mime}"/>'
                '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>'
                '</manifest:manifest>')
    if kind == 'presentation':
        manifest = manifest.replace('</manifest:manifest>', '<manifest:file-entry '
                                    'manifest:full-path="styles.xml" manifest:media-type="text/xml"/>'
                                    '</manifest:manifest>')
    out = BytesIO()
    with ZipFile(out, 'w', ZIP_STORED) as z:
        z.writestr('mimetype', mime)
        z.writestr('content.xml', content)
        z.writestr('META-INF/manifest.xml', manifest)
        if kind == 'presentation':
            z.writestr('styles.xml', f'<office:document-styles {DECL} office:version="1.3">'
                       '<office:automatic-styles><style:page-layout style:name="PageLayout">'
                       '<style:page-layout-properties/></style:page-layout></office:automatic-styles>'
                       '<office:master-styles><style:master-page style:name="Default" '
                       'style:page-layout-name="PageLayout"/></office:master-styles></office:document-styles>')
    return out.getvalue()


def write_fixtures(root):
    root.mkdir(parents=True, exist_ok=True)
    for name, (kind, body) in fixtures().items():
        data = package(kind, body)
        (root / name).write_bytes(data)
        with ZipFile(BytesIO(data)) as z:
            (root / (name + '.xml')).write_bytes(z.read('content.xml'))


@pytest.mark.skipif(not os.environ.get('ODF13_SCHEMA'), reason='optional official schema')
@pytest.mark.parametrize('name', fixtures())
def test_research_fixture_schema(name, tmp_path):
    write_fixtures(tmp_path)
    subprocess.run(['xmllint', '--nonet', '--noout', '--relaxng', os.environ['ODF13_SCHEMA'],
                    str(tmp_path / (name + '.xml'))], check=True, capture_output=True)


# Reuse only isolated process setup and safe load properties, not parser results.
_READER_START = _UNO_READER.split('        output = []')[0]
_READER_END = _UNO_READER.split('        desktop.terminate()')[1]
READER = _READER_START + r'''
        output = {}
        for filename in ('shapes.odt', 'image.odt', 'inline.ods', 'inline.odp'):
            doc = desktop.loadComponentFromURL((root / filename).as_uri(), '_blank', 0,
                (prop('Hidden', True), prop('ReadOnly', True),
                 prop('MacroExecutionMode', NEVER_EXECUTE), prop('UpdateDocMode', NO_UPDATE)))
            if doc is None:
                raise RuntimeError('Fixture not loaded: ' + filename)
            page = (doc.Sheets.getByIndex(0).DrawPage if filename.endswith('.ods') else
                    doc.DrawPages.getByIndex(0) if filename.endswith('.odp') else doc.DrawPage)
            shapes = []
            for i in range(page.Count):
                shape = page.getByIndex(i)
                entry = {'type': shape.ShapeType}
                try:
                    entry['text'] = shape.String
                except Exception:
                    pass
                try:
                    model = shape.Model
                    entry['embedded_text'] = model.Text.String
                    entry['cell'] = model.TextTables.getByName('Inner').getCellByName('A1').String
                except Exception:
                    pass
                shapes.append(entry)
            output[filename] = {'shapes': shapes}
            if filename.endswith('.odt'):
                output[filename]['host'] = doc.Text.String
                output[filename]['text_frames'] = [doc.TextFrames.getByName(n).Text.String
                                                   for n in doc.TextFrames.ElementNames]
                output[filename]['graphics'] = list(doc.GraphicObjects.ElementNames)
            doc.close(True)
        print(json.dumps(output, indent=2))
        desktop.terminate()
''' + _READER_END


if __name__ == '__main__':
    import sys
    root = Path(sys.argv[1]).resolve()
    write_fixtures(root)
    (root / 'reader.py').write_text(READER)


def test_research_packages_are_self_contained():
    for kind, body in fixtures().values():
        with ZipFile(BytesIO(package(kind, body))) as z:
            assert z.read('mimetype').decode().endswith(kind)
            xml = z.read('content.xml')
            assert b'xlink:href=' not in xml
            assert b'office:scripts' not in xml
            assert b'office:event-listeners' not in xml


@pytest.mark.skipif(os.environ.get('ODF_PASSIVE_RESEARCH_LO') != '1',
                    reason='optional independent LibreOffice reader')
def test_independent_reader_confirms_shape_labels(tmp_path):
    import json
    write_fixtures(tmp_path)
    script = tmp_path / 'reader.py'
    script.write_text(READER)
    result = subprocess.run(['/usr/bin/python3', str(script), str(tmp_path)],
                            check=True, capture_output=True, text=True, timeout=45)
    data = json.loads(result.stdout)
    assert [shape['text'] for shape in data['shapes.odt']['shapes']] == [
        f'{kind} paragraph\n{kind} list' for kind in ('rect', 'ellipse', 'custom-shape')]
    assert data['shapes.odt']['host'] == 'Host beforeHost after'
