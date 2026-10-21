"""Authored inline ODF documents; optional schema and independent Writer checks.

No binary/private fixture, office runtime dependency, or external object lookup.
"""
from io import BytesIO
import json
import os
import subprocess
from zipfile import ZipFile, ZIP_STORED

import pytest

from legacy_office_parser import Limits, LimitExceededError, Paragraph, Table, parse_odt
from legacy_office_parser.odf import parse_odf_bytes
from test_odf import NS as BASE_NS, package as other_package
from test_odf_stories import master, note, styles

NS = {**BASE_NS, 'svg': 'urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0',
      'xlink': 'http://www.w3.org/1999/xlink'}
DECL = ' '.join(f'xmlns:{prefix}="{uri}"' for prefix, uri in NS.items())


def p(value=''):
    return '<text:p>' + value + '</text:p>'


def table(body, rows=1, columns=1):
    return ('<table:table table:name="Inner"><table:table-column/>'
            f'<table:table-row table:number-rows-repeated="{rows}">'
            f'<table:table-cell office:value-type="string" table:number-columns-repeated="{columns}">'
            + body + '</table:table-cell></table:table-row></table:table>')


def box(body):
    return '<draw:text-box>' + body + '</draw:text-box>'


def frame(body):
    return ('<draw:frame xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0" '
            'draw:name="InlineObject" text:anchor-type="as-char" '
            'svg:width="12cm" svg:height="4cm">' + body + '</draw:frame>')


def embedded(body, prelude='', mime='application/vnd.oasis.opendocument.text'):
    return ('<draw:object><office:document office:version="1.3" '
            f'office:mimetype="{mime}">' + prelude + '<office:body><office:text>' + body +
            '</office:text></office:body></office:document></draw:object>')


def package(body, extra=None):
    content = (f'<office:document-content {DECL} office:version="1.3">'
               '<office:body><office:text>' + body + '</office:text></office:body></office:document-content>')
    manifest = (f'<manifest:manifest xmlns:manifest="{NS["manifest"]}" manifest:version="1.3">'
                '<manifest:file-entry manifest:full-path="/" '
                'manifest:media-type="application/vnd.oasis.opendocument.text"/>'
                '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>'
                '</manifest:manifest>')
    out = BytesIO()
    with ZipFile(out, 'w', ZIP_STORED) as z:
        z.writestr('mimetype', 'application/vnd.oasis.opendocument.text')
        z.writestr('content.xml', content)
        z.writestr('META-INF/manifest.xml', manifest)
        for name, value in (extra or {}).items():
            z.writestr(name, value)
    return out.getvalue()


# Authored one-pixel RGB PNG (25/75/a5 hex), with standard CRCs and no metadata.
PREVIEW = ('<draw:image><office:binary-data>'
           'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNQLV0KAAICAUC01TwxAAAAAElFTkSuQmCC'
           '</office:binary-data></draw:image>')


def reader_fixture(preview=False):
    body = p('Embedded before / Привет') + table(p('Embedded cell')) + p('Embedded after')
    return package(p('Host before' + frame(embedded(body) + (PREVIEW if preview else '')) + 'Host after'))


def test_authored_reader_fixture_text_and_structure():
    for preview in (False, True):
        doc = parse_odt(reader_fixture(preview))
        assert [b.text for b in doc.blocks] == ['Host beforeHost after']
        assert doc.textboxes == 'Embedded before / Привет\n\nEmbedded cell\n\nEmbedded after'
        blocks = doc.story_blocks['textboxes']
        assert [type(b) for b in blocks] == [Paragraph, Table, Paragraph]
        assert blocks[1].rows[0][0].text == 'Embedded cell'
        assert doc.text.count('Embedded cell') == 1
        assert any('inline text objects pooled' in w for w in doc.warnings)
        assert doc.to_dict()['story_blocks']['textboxes'][1]['kind'] == 'table'


@pytest.mark.parametrize('contents,expected', [
    (embedded(p('first')) + box(p('fallback')), 'first'),
    (box(p('first')) + embedded(p('fallback')), 'first'),
    (embedded(p('first')) + embedded(p('fallback')), 'first'),
    (box(p('first')) + box(p('fallback')), 'first'),
    (PREVIEW + embedded(p('body')) + PREVIEW, 'body'),
    (embedded('') + box(p('fallback')), ''),
    (box('') + embedded(p('fallback')), ''),
])
def test_first_supported_frame_representation_even_when_empty(contents, expected):
    doc = parse_odt(package(p(frame(contents))))
    assert doc.textboxes == doc.text == expected
    assert doc.story_blocks == {}


def test_equal_objects_in_separate_frames_are_not_value_deduplicated():
    obj = frame(embedded(p('same')))
    doc = parse_odt(package(p('A' + obj + 'B' + obj + 'C')))
    assert doc.blocks[0].text == 'ABC'
    assert doc.textboxes == 'same\n\nsame'
    assert doc.text.count('same') == 2


def test_repeated_empty_objects_obey_record_budget_before_detached_clone(monkeypatch):
    import legacy_office_parser.odf as odf

    body = embedded(p('') * 200 + '<table:table/>')
    data = package(table(p(frame(body)), columns=1000))
    original = odf._clone_cell

    def checked(cell):
        if cell.blocks and not cell.text:
            pytest.fail('expanded empty objects must be rejected before detached copying')
        return original(cell)

    monkeypatch.setattr(odf, '_clone_cell', checked)
    with pytest.raises(LimitExceededError, match='expanded story record'):
        parse_odt(data)


def test_unselected_alternative_is_not_expanded_or_traversed():
    poison = embedded(table(p('<text:s text:c="100000000"/>'), columns=1000000))
    doc = parse_odt(package(p(frame(box(p('selected')) + poison))), limits=Limits(max_cells=1))
    assert doc.text == 'selected'


@pytest.mark.parametrize('bad', [
    '<draw:object/>',
    '<draw:object><office:text>' + p('OMIT') + '</office:text></draw:object>',
    embedded(p('OMIT')).replace('office:document', 'office:document-content'),
    embedded(p('OMIT'), mime='application/vnd.oasis.opendocument.spreadsheet'),
    embedded(p('OMIT'), mime='application/vnd.oasis.opendocument.text-template'),
    embedded(p('OMIT')).replace(' office:mimetype="application/vnd.oasis.opendocument.text"', ''),
    embedded(p('OMIT')).replace('<office:body>', '<office:body/><office:body>'),
    embedded(p('OMIT')).replace('</office:body>', '<office:text/></office:body>'),
    embedded(p('OMIT')).replace('office:text', 'office:spreadsheet'),
    embedded(p('OMIT')).replace('</draw:object>', '<office:document/></draw:object>'),
    '<draw:object-ole><office:binary-data>AAAA</office:binary-data></draw:object-ole>',
])
def test_unsupported_or_ambiguous_body_is_not_scraped(bad):
    doc = parse_odt(package(p(frame(bad + box(p('fallback'))))))
    assert doc.text == 'fallback'
    assert any('Unsupported' in w for w in doc.warnings)


@pytest.mark.parametrize('href', ['', '#fragment', './Object 1/', 'file:///never-open', 'https://invalid.example/object'])
def test_href_even_with_inline_body_is_not_followed(href, monkeypatch):
    opened = []
    original_open = ZipFile.open

    def tracked(self, name, *args, **kwargs):
        opened.append(name)
        return original_open(self, name, *args, **kwargs)

    obj = embedded(p('OMIT')).replace('<draw:object>', f'<draw:object xlink:href="{href}">')
    data = package(p(frame(obj + box(p('fallback')))), extra={'Object 1/content.xml': 'not XML'})
    monkeypatch.setattr(ZipFile, 'open', tracked)
    assert parse_odt(data).text == 'fallback'
    assert set(opened) == {'mimetype', 'META-INF/manifest.xml', 'content.xml'}


def test_object_requires_direct_frame_placement():
    obj = embedded(p('OMIT'))
    assert parse_odt(package(obj + p(obj) + '<draw:g>' + obj + '</draw:g>')).text == ''


@pytest.mark.parametrize('wrapper', [
    '<office:annotation>{}</office:annotation>',
    '<text:tracked-changes>{}</text:tracked-changes>',
    '<text:section text:display="none">{}</text:section>',
    '<text:hidden-text text:is-hidden="true">{}</text:hidden-text>',
])
def test_invisible_or_unsupported_ancestors_do_not_expose_objects(wrapper):
    xml = frame(embedded(p('OMIT')))
    assert parse_odt(package(p('visible' + wrapper.format(xml)))).text == 'visible'


def test_nested_object_note_scope_and_host_note_guard_are_restored():
    obj = frame(embedded(p('Object' + note(p('Independent foot')))))
    host = note(p('Host note' + obj + note(p('OMIT nested host note'))))
    doc = parse_odt(package(p('Main' + host)))
    assert doc.footnotes == 'Host note\n\nIndependent foot'
    assert doc.textboxes == 'Object'
    assert 'OMIT' not in doc.text


def test_embedded_preludes_masters_and_host_master_selection_stay_separate():
    prelude = ('<office:meta>' + p('OMIT meta') + '</office:meta>'
               '<office:scripts>' + p('OMIT script') + '</office:scripts>'
               '<office:master-styles><style:master-page style:name="Embedded">'
               '<style:header>' + p('OMIT embedded header') + '</style:header>'
               '</style:master-page></office:master-styles>')
    host_styles = styles(master('<style:header>' + p('Host header') + '</style:header>') +
                         master('<style:header>' + p('OMIT unused') + '</style:header>', 'Unused'))
    obj = embedded('<text:p text:style-name="EmbeddedOnly">Object body</text:p>', prelude)
    doc = parse_odt(package(p('Main' + frame(obj)), extra={'styles.xml': host_styles}))
    assert doc.textboxes == 'Object body'
    assert doc.headers_footers == 'Host header'
    assert 'OMIT' not in doc.text


def test_selected_host_header_and_cell_objects_use_existing_story_routing():
    header = '<style:header>' + p('Header' + frame(embedded(table(p('header object'))))) + '</style:header>'
    doc = parse_odt(package(table(p('Cell' + frame(embedded(p('cell object'))))),
                            extra={'styles.xml': styles(master(header))}))
    assert doc.blocks[0].rows[0][0].text == 'Cell'
    assert doc.headers_footers == 'Header'
    assert doc.textboxes == 'cell object\n\nheader object'
    assert [type(b) for b in doc.story_blocks['textboxes']] == [Paragraph, Table]


def test_nested_objects_keep_encounter_order_and_empty_table_semantics():
    body = p('outer before' + frame(embedded(table(p('inner'))))) + p('outer after')
    doc = parse_odt(package(p(frame(embedded(body)) + frame(embedded('<table:table/>')))))
    assert doc.textboxes == 'outer before\n\nouter after\n\ninner'
    blocks = doc.story_blocks['textboxes']
    assert [type(b) for b in blocks] == [Paragraph, Paragraph, Table, Table]
    assert blocks[-1].rows == []


def test_repeated_object_trees_are_independent_and_budgeted_before_detached_copy(monkeypatch):
    import legacy_office_parser.odf as odf

    body = embedded(table(table(p('<text:s text:c="1000"/>')), rows=2))
    data = package(table(p(frame(body)), columns=2))
    copied = []
    original_clone = odf._clone_cell

    def tracked(cell):
        if cell.blocks and not cell.text:
            copied.append(cell)
        return original_clone(cell)

    monkeypatch.setattr(odf, '_clone_cell', tracked)
    with pytest.raises(LimitExceededError):
        parse_odt(data, limits=Limits(max_text_chars=12003))
    assert copied == []
    doc = parse_odt(data, limits=Limits(max_text_chars=12004, max_cells=10))
    assert len(copied) == 1
    assert len(doc.textboxes) == 4004
    left, right = doc.story_blocks['textboxes']
    left.rows[0][0].blocks[0].rows[0][0].text = 'changed'
    assert right.rows[0][0].blocks[0].rows[0][0].text == ' ' * 1000
    with pytest.raises(LimitExceededError):
        parse_odt(data, limits=Limits(max_cells=9))


def test_inline_object_shares_xml_depth_record_and_text_budgets():
    xml = p('body')
    for _ in range(8):
        xml = p(frame(embedded(xml)))
    with pytest.raises(LimitExceededError, match='XML depth'):
        parse_odt(package(xml), limits=Limits(max_depth=20))
    with pytest.raises(LimitExceededError, match='XML node'):
        parse_odt(package(xml), limits=Limits(max_records=30))
    data = package(p(frame(embedded(table(p('<text:s text:c="1000"/>'))))))
    assert len(parse_odt(data, limits=Limits(max_text_chars=2000)).textboxes) == 1000
    with pytest.raises(LimitExceededError):
        parse_odt(data, limits=Limits(max_text_chars=1999))


@pytest.mark.parametrize('fmt', ['ods', 'odp'])
def test_other_formats_do_not_gain_inline_object_recursion(fmt):
    obj = embedded(p('OMIT'))
    body = table(frame(obj)) if fmt == 'ods' else '<draw:page>' + frame(obj) + '</draw:page>'
    # The simple object uses only the namespaces already in the shared helper.
    body = body.replace(' svg:width="12cm" svg:height="4cm"', '')
    assert 'OMIT' not in parse_odf_bytes(other_package(body, fmt), Limits()).text


@pytest.mark.skipif(not os.environ.get('ODF13_SCHEMA'), reason='optional official ODF 1.3 schema')
def test_authored_reader_fixtures_validate_against_official_schema(tmp_path):
    for preview in (False, True):
        with ZipFile(BytesIO(reader_fixture(preview))) as z:
            content = tmp_path / 'content.xml'
            content.write_bytes(z.read('content.xml'))
        subprocess.run(['xmllint', '--noout', '--nonet', '--relaxng', os.environ['ODF13_SCHEMA'],
                        str(content)], check=True, capture_output=True, timeout=15)


@pytest.mark.skipif(os.environ.get('ODF_INLINE_LO_ORACLE') != '1', reason='optional LibreOffice UNO reader')
def test_independent_libreoffice_reads_authored_inline_document(tmp_path):
    for preview in (False, True):
        (tmp_path / f'inline-{int(preview)}.odt').write_bytes(reader_fixture(preview))
    completed = subprocess.run(['/usr/bin/python3', '-c', _UNO_READER, str(tmp_path)],
                               check=True, capture_output=True, text=True, timeout=45)
    result = json.loads(completed.stdout)
    for document in result:
        assert document['host'] == 'Host beforeHost after'
        assert document['objects'] == [{
            'text': 'Embedded before / Привет\nEmbedded cell\nEmbedded after',
            'cells': {'A1': 'Embedded cell'},
        }]


_UNO_READER = r'''
import json, subprocess, sys, tempfile, time, uuid
from pathlib import Path
import uno
from com.sun.star.beans import PropertyValue
from com.sun.star.document.MacroExecMode import NEVER_EXECUTE
from com.sun.star.document.UpdateDocMode import NO_UPDATE

def prop(name, value):
    p = PropertyValue(); p.Name = name; p.Value = value; return p
root = Path(sys.argv[1])
pipe = 'inlineodf' + uuid.uuid4().hex
with tempfile.TemporaryDirectory(prefix='inline-odf-reader-') as profile:
    process = subprocess.Popen(['soffice', '-env:UserInstallation=' + Path(profile).as_uri(),
        '--headless', '--accept=pipe,name=' + pipe + ';urp;StarOffice.ComponentContext',
        '--norestore', '--nodefault', '--nofirststartwizard'], stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL)
    try:
        local = uno.getComponentContext()
        resolver = local.ServiceManager.createInstanceWithContext('com.sun.star.bridge.UnoUrlResolver', local)
        context = None
        for _ in range(100):
            try:
                context = resolver.resolve('uno:pipe,name=' + pipe + ';urp;StarOffice.ComponentContext')
                break
            except Exception:
                time.sleep(.1)
        if context is None:
            raise RuntimeError('Isolated LibreOffice did not start')
        desktop = context.ServiceManager.createInstanceWithContext('com.sun.star.frame.Desktop', context)
        output = []
        for filename in ('inline-0.odt', 'inline-1.odt'):
            doc = desktop.loadComponentFromURL((root / filename).as_uri(), '_blank', 0,
                (prop('Hidden', True), prop('ReadOnly', True),
                 prop('MacroExecutionMode', NEVER_EXECUTE), prop('UpdateDocMode', NO_UPDATE)))
            if doc is None:
                raise RuntimeError('Fixture was not loaded')
            objects = []
            for name in doc.EmbeddedObjects.ElementNames:
                model = doc.EmbeddedObjects.getByName(name).Model
                table = model.TextTables.getByName('Inner')
                objects.append({'text': model.Text.String,
                                'cells': {name: table.getCellByName(name).String for name in table.CellNames}})
            output.append({'host': doc.Text.String, 'objects': objects})
            doc.close(True)
        print(json.dumps(output))
        desktop.terminate()
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait()
'''
