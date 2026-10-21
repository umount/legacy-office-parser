"""Original synthetic packages: no external/private document fixtures."""
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED

import pytest

from legacy_office_parser.errors import (EncryptedDocumentError, InvalidDocumentError,
                                        LimitExceededError, UnsupportedFormatError)
from legacy_office_parser.limits import Limits
from legacy_office_parser.models import Paragraph, Table
from legacy_office_parser.odf import parse_odf_bytes


# Independently specified namespace URIs, not imported from the parser.
NS = {
    'office': 'urn:oasis:names:tc:opendocument:xmlns:office:1.0',
    'text': 'urn:oasis:names:tc:opendocument:xmlns:text:1.0',
    'table': 'urn:oasis:names:tc:opendocument:xmlns:table:1.0',
    'draw': 'urn:oasis:names:tc:opendocument:xmlns:drawing:1.0',
    'presentation': 'urn:oasis:names:tc:opendocument:xmlns:presentation:1.0',
    'manifest': 'urn:oasis:names:tc:opendocument:xmlns:manifest:1.0',
    'style': 'urn:oasis:names:tc:opendocument:xmlns:style:1.0',
}


def package(body='', fmt='odt', *, extra=None, content=None, manifest=None):
    mime = 'application/vnd.oasis.opendocument.' + {
        'odt': 'text', 'ods': 'spreadsheet', 'odp': 'presentation'}[fmt]
    namespaces = ' '.join(f'xmlns:{p}="{uri}"' for p, uri in NS.items())
    kind = {'odt': 'text', 'ods': 'spreadsheet', 'odp': 'presentation'}[fmt]
    if content is None:
        content = (f'<office:document-content {namespaces}><office:body><office:{kind}>'
                   f'{body}</office:{kind}></office:body></office:document-content>')
    if manifest is None:
        manifest = (f'<manifest:manifest xmlns:manifest="{NS["manifest"]}">'
                    f'<manifest:file-entry manifest:full-path="/" manifest:media-type="{mime}"/>'
                    '</manifest:manifest>')
    out = BytesIO()
    with ZipFile(out, 'w', ZIP_DEFLATED) as z:
        z.writestr('mimetype', mime)
        z.writestr('content.xml', content)
        z.writestr('META-INF/manifest.xml', manifest)
        for name, value in (extra or {}).items():
            z.writestr(name, value)
    return out.getvalue()


def parse(body='', fmt='odt', limits=None, **kwargs):
    return parse_odf_bytes(package(body, fmt, **kwargs), limits or Limits())


def test_odt_order_whitespace_and_metadata():
    doc = parse('<text:h>Heading</text:h><text:p> Alpha <text:span>  beta</text:span>'
                '<text:s text:c="3"/>X<text:tab/>Y<text:line-break/>Z '
                '<office:annotation><text:p>SECRET</text:p></office:annotation>end</text:p>'
                '<table:table><table:table-row><table:table-cell><text:p>cell</text:p>'
                '</table:table-cell></table:table-row></table:table>'
                '<text:section><text:p>last</text:p></text:section>',
                extra={'meta.xml': '<secret>METADATA</secret>'})
    assert [type(b) for b in doc.blocks] == [Paragraph, Paragraph, Table, Paragraph]
    assert doc.blocks[1].text == 'Alpha beta   X\tY\nZ end'
    assert doc.text.count('cell') == 1
    assert 'SECRET' not in doc.text and 'METADATA' not in doc.text
    assert doc.blocks[-1].text == 'last'


def test_odt_repeats_and_covered_cells():
    doc = parse('<table:table><table:table-row table:number-rows-repeated="2">'
                '<table:table-cell table:number-columns-spanned="2"><text:p>A</text:p>'
                '</table:table-cell><table:covered-table-cell><text:p>hidden</text:p>'
                '</table:covered-table-cell><table:table-cell table:number-columns-repeated="2">'
                '<text:p>B</text:p></table:table-cell></table:table-row></table:table>')
    rows = doc.blocks[0].rows
    assert len(rows) == 2 and len(rows[0]) == 4
    assert rows[0][0].col_span == 2
    assert rows[0][1].covered and rows[0][1].text == ''
    assert rows[0][2].text == rows[1][3].text == 'B'
    assert rows[0][0] is not rows[1][0]


def test_ods_sparse_repeats_types_and_formulas():
    doc = parse('<table:table table:name="Data"><table:table-row table:number-rows-repeated="1000">'
                '<table:table-cell table:number-columns-repeated="100"/></table:table-row>'
                '<table:table-row table:number-rows-repeated="2">'
                '<table:table-cell table:number-columns-repeated="2"/>'
                '<table:table-cell office:value-type="float" office:value="42" table:formula="of:=6*7"/>'
                '<table:table-cell office:value-type="boolean" office:boolean-value="false"/>'
                '<table:table-cell office:value-type="date" office:date-value="2026-10-21"/>'
                '<table:table-cell office:value-type="time" office:time-value="PT2H"/>'
                '<table:table-cell office:value-type="string" office:string-value="cached">'
                '<text:p>display</text:p></table:table-cell></table:table-row></table:table>', 'ods')
    s = doc.sheets[0]
    assert (s.name, s.rows, s.columns, len(s.cells)) == ('Data', 1002, 100, 10)
    assert s.cells[0].address == 'C1001'
    assert s.cells[0].value == 42 and isinstance(s.cells[0].value, int)
    assert s.cells[0].formula == 'of:=6*7' and s.cells[0].is_formula
    assert s.cells[1].value is False
    assert s.cells[2].value_type == 'date'
    assert s.cells[3].value == 'PT2H'
    assert s.cells[4].value == 'cached' and s.cells[4].text == 'display'
    assert s.cells[5].address == 'C1002'


def test_ods_merges_and_hidden_style():
    styles = (f'<office:document-styles xmlns:office="{NS["office"]}" '
              f'xmlns:style="{NS["style"]}" xmlns:table="{NS["table"]}">'
              '<office:styles><style:style style:name="hidden" style:family="table">'
              '<style:table-properties table:display="false"/></style:style></office:styles>'
              '</office:document-styles>')
    doc = parse('<table:table table:name="s" table:style-name="hidden">'
                '<table:table-header-rows><table:table-row><table:table-cell '
                'table:number-columns-spanned="2" table:number-rows-spanned="2">'
                '<text:p>merged</text:p></table:table-cell><table:covered-table-cell/>'
                '<table:table-cell office:value-type="percentage" office:value="0.25"/>'
                '</table:table-row></table:table-header-rows></table:table>', 'ods',
                extra={'styles.xml': styles})
    s = doc.sheets[0]
    assert s.hidden and s.cells[1].address == 'C1'
    m = s.merges[0]
    assert (m.start_row, m.start_column, m.end_row, m.end_column) == (1, 1, 2, 2)
    assert s.rows == 2


def test_odp_blank_slides_title_body_notes():
    doc = parse('<draw:page draw:name="internal-name"><draw:frame presentation:class="title">'
                '<draw:text-box><text:p>Title</text:p></draw:text-box></draw:frame>'
                '<draw:g><draw:frame><draw:text-box><text:p>Body</text:p></draw:text-box>'
                '</draw:frame></draw:g><presentation:notes><draw:page-thumbnail/>'
                '<draw:frame presentation:class="notes"><draw:text-box><text:p>Note</text:p>'
                '</draw:text-box></draw:frame></presentation:notes></draw:page>'
                '<draw:page presentation:visibility="hidden"/>', 'odp')
    assert len(doc.slides) == 2
    first, blank = doc.slides
    assert (first.title, first.text, first.notes) == ('Title', 'Body', 'Note')
    assert blank.hidden and blank.number == 2 and blank.text == ''
    assert doc.text == 'Title\nBody\nNote\n\n'
    assert 'internal-name' not in doc.text


@pytest.mark.parametrize('body,fmt,limits', [
    ('<text:p><text:s text:c="999999999999999999999999"/></text:p>', 'odt', Limits()),
    ('<text:p>123456</text:p>', 'odt', Limits(max_text_chars=5)),
    ('<text:p><text:span>X</text:span></text:p>', 'odt', Limits(max_depth=3)),
    ('<text:p>X</text:p>', 'odt', Limits(max_records=3)),
    ('<draw:page/><draw:page/>', 'odp', Limits(max_slides=1)),
    ('<table:table/><table:table/>', 'ods', Limits(max_sheets=1)),
    ('<table:table><table:table-row table:number-rows-repeated="1048577"/></table:table>', 'ods', Limits()),
    ('<table:table><table:table-row><table:table-cell table:number-columns-repeated="16385"/>'
     '</table:table-row></table:table>', 'ods', Limits()),
    ('<table:table><table:table-row table:number-rows-repeated="1000000">'
     '<table:table-cell><text:p>X</text:p></table:table-cell></table:table-row></table:table>', 'ods', Limits()),
    ('<table:table><table:table-row table:number-rows-repeated="1000000"/></table:table>', 'odt', Limits()),
    ('<table:table><table:table-row table:number-rows-repeated="2">'
     '<table:table-cell table:number-columns-repeated="3"><text:p>X</text:p></table:table-cell>'
     '</table:table-row></table:table>', 'odt', Limits(max_cells=5)),
])
def test_limits(body, fmt, limits):
    with pytest.raises(LimitExceededError):
        parse(body, fmt, limits)


@pytest.mark.parametrize('count', ['0', '-1', '1.5', 'NaN'])
def test_bad_repeat(count):
    with pytest.raises(InvalidDocumentError):
        parse(f'<text:p><text:s text:c="{count}"/></text:p>')


@pytest.mark.parametrize('encoding', ['utf-8', 'utf-16', 'utf-32'])
def test_dtd_rejected_before_parse(encoding):
    content = ('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY private SYSTEM "file:///etc/passwd">]>'
               '<x>&private;</x>').encode(encoding)
    with pytest.raises(InvalidDocumentError, match='DTD/entity'):
        parse(content=content)


def test_manifest_encryption():
    manifest = (f'<manifest:manifest xmlns:manifest="{NS["manifest"]}">'
                '<manifest:file-entry manifest:full-path="content.xml">'
                '<manifest:encryption-data/></manifest:file-entry></manifest:manifest>')
    with pytest.raises(EncryptedDocumentError):
        parse(manifest=manifest)


def test_mime_and_body_checks():
    with pytest.raises(InvalidDocumentError, match='expected format'):
        parse_odf_bytes(package(), Limits(), 'ods')
    with pytest.raises(InvalidDocumentError, match='MIME/body'):
        parse(content=f'<office:document-content xmlns:office="{NS["office"]}">'
              '<office:body><office:spreadsheet/></office:body></office:document-content>')
    with pytest.raises(InvalidDocumentError):
        parse(content='<broken>')
    with pytest.raises(InvalidDocumentError):
        parse_odf_bytes(b'not a zip', Limits())


def test_zip_limits():
    data = package(extra={'padding': ' ' * 1000})
    for limits in [Limits(max_archive_entries=3), Limits(max_stream_bytes=900),
                   Limits(max_uncompressed_bytes=1000), Limits(max_file_bytes=20)]:
        with pytest.raises(LimitExceededError):
            parse_odf_bytes(data, limits)


def test_manifest_mime_fallback_and_unknown_mime():
    data = package('<text:p>ok</text:p>')
    for mime, error in [(None, None), ('text/plain', InvalidDocumentError)]:
        out = BytesIO()
        with ZipFile(BytesIO(data)) as source, ZipFile(out, 'w') as target:
            for name in source.namelist():
                if name != 'mimetype':
                    target.writestr(name, source.read(name))
            if mime:
                target.writestr('mimetype', mime)
        if error:
            with pytest.raises(error):
                parse_odf_bytes(out.getvalue(), Limits())
        else:
            assert parse_odf_bytes(out.getvalue(), Limits()).text == 'ok'
    out = BytesIO()
    with ZipFile(out, 'w') as z:
        z.writestr('mimetype', 'text/plain')
    with pytest.raises(UnsupportedFormatError):
        parse_odf_bytes(out.getvalue(), Limits())


def test_duplicate_zip_member():
    out = BytesIO(package())
    with pytest.warns(UserWarning), ZipFile(out, 'a') as z:
        z.writestr('content.xml', '<replacement/>')
    with pytest.raises(InvalidDocumentError, match='Duplicate'):
        parse_odf_bytes(out.getvalue(), Limits())


def test_huge_empty_sheet_is_sparse():
    doc = parse('<table:table><table:table-row table:number-rows-repeated="1048576">'
                '<table:table-cell table:number-columns-repeated="16384"/>'
                '</table:table-row></table:table>', 'ods', Limits(max_cells=1))
    sheet = doc.sheets[0]
    assert not sheet.cells and sheet.rows == 1048576 and sheet.columns == 16384


def test_repeated_text_budget():
    with pytest.raises(LimitExceededError, match='expanded text'):
        parse('<table:table><table:table-row table:number-rows-repeated="20">'
              '<table:table-cell><text:p>' + 'A' * 100 + '</text:p></table:table-cell>'
              '</table:table-row></table:table>', 'ods', Limits(max_text_chars=1500))


def test_zip_encryption_flag():
    data = bytearray(package())
    # Original synthetic ZIP: set the encryption flag in both local/central headers.
    for signature, delta in [(b'PK\x03\x04', 6), (b'PK\x01\x02', 8)]:
        index = data.find(signature)
        assert index >= 0
        data[index + delta] |= 1
    with pytest.raises(EncryptedDocumentError):
        parse_odf_bytes(bytes(data), Limits())


def test_manifest_entities_and_style_depth_guard():
    with pytest.raises(InvalidDocumentError, match='DTD/entity'):
        parse(manifest='<!DOCTYPE x [<!ENTITY y "abc">]><x/>')
    with pytest.raises(LimitExceededError, match='depth'):
        parse(extra={'styles.xml': '<a>' * 40 + '</a>' * 40})


def test_raw_whitespace_across_spans_and_explicit_boundaries():
    d = parse('<text:p>  <text:span>A </text:span><text:span> B</text:span>  </text:p>'
              '<text:p><text:s text:c="2"/>X<text:s text:c="2"/></text:p>')
    assert [p.text for p in d.blocks] == ['A B', '  X  ']


def test_unknown_content_and_nested_table_not_scraped():
    d = parse('<text:p>visible<text:note><text:note-body><text:p>PRIVATE</text:p>'
              '</text:note-body></text:note>end</text:p>'
              '<text:tracked-changes><text:p>DELETED</text:p></text:tracked-changes>'
              '<table:table><table:table-row><table:table-cell><text:p>outer</text:p>'
              '<table:table><table:table-row><table:table-cell><text:p>NESTED</text:p>'
              '</table:table-cell></table:table-row></table:table>'
              '</table:table-cell></table:table-row></table:table>')
    assert d.text == 'visibleend\n\nouter'
    assert any('Unsupported' in w for w in d.warnings)


@pytest.mark.parametrize('attribute', ['office:value="NaN" office:value-type="float"',
                                       'office:boolean-value="yes" office:value-type="boolean"'])
def test_invalid_cached_values(attribute):
    with pytest.raises(InvalidDocumentError):
        parse('<table:table><table:table-row><table:table-cell ' + attribute + '/>'
              '</table:table-row></table:table>', 'ods')


def test_formula_without_cache_is_kept_and_not_executed():
    d = parse('<table:table><table:table-row><table:table-cell table:formula="of:=1+2"/>'
              '</table:table-row></table:table>', 'ods')
    c = d.sheets[0].cells[0]
    assert c.value is None and c.is_formula and c.formula == 'of:=1+2'
    assert c.text == ''


def test_namespace_prefixes_are_not_significant():
    data = package('<text:p>hello</text:p>')
    out = BytesIO()
    with ZipFile(BytesIO(data)) as source, ZipFile(out, 'w') as target:
        for name in source.namelist():
            payload = source.read(name)
            if name == 'content.xml':
                payload = payload.replace(b'xmlns:text=', b'xmlns:t=').replace(b'<text:', b'<t:').replace(b'</text:', b'</t:')
            target.writestr(name, payload)
    assert parse_odf_bytes(out.getvalue(), Limits()).text == 'hello'


def test_xml_limits_interrupt_before_later_malformed_input():
    content = ('<a>' * 100 + 'not valid XML').encode()
    with pytest.raises(LimitExceededError, match='depth'):
        parse(content=content, limits=Limits(max_depth=8))
    with pytest.raises(LimitExceededError, match='node'):
        parse(content=b'<a>' + b'<b/>' * 100 + b'<broken', limits=Limits(max_records=10))


def test_last_grid_coordinate_after_empty_runs():
    d = parse('<table:table><table:table-row table:number-rows-repeated="1048575"/>'
              '<table:table-row><table:table-cell table:number-columns-repeated="16383"/>'
              '<table:table-cell office:value-type="float" office:value="1"/>'
              '</table:table-row></table:table>', 'ods', Limits(max_cells=1))
    assert len(d.sheets[0].cells) == 1
    assert d.sheets[0].cells[0].address == 'XFD1048576'


def test_joins_cannot_exceed_rendered_text_limit():
    with pytest.raises(LimitExceededError, match='rendered text'):
        parse('<draw:page/>' * 300, 'odp', Limits(max_text_chars=500))


def test_explicit_larger_limits_are_honored():
    d = parse('<table:table/>' * 257, 'ods', Limits(max_sheets=257))
    assert len(d.sheets) == 257
    d = parse('<table:table><table:table-row table:number-rows-repeated="1048577">'
              '<table:table-cell table:number-columns-repeated="16385"/>'
              '</table:table-row></table:table>', 'ods',
              Limits(max_rows=1048577, max_columns=16385))
    assert (d.sheets[0].rows, d.sheets[0].columns) == (1048577, 16385)
    d = parse('<table:table><table:table-row table:number-rows-repeated="100001">'
              '<table:table-cell office:value-type="float" office:value="1"/>'
              '</table:table-row></table:table>', 'ods', Limits(max_cells=100001))
    assert len(d.sheets[0].cells) == 100001


def test_unsupported_zip_compression_error():
    data = bytearray(package())
    for signature, delta in [(b'PK\x03\x04', 8), (b'PK\x01\x02', 10)]:
        offset = 0
        while (index := data.find(signature, offset)) >= 0:
            data[index + delta:index + delta + 2] = (99).to_bytes(2, 'little')
            offset = index + 4
    with pytest.raises(UnsupportedFormatError, match='compression'):
        parse_odf_bytes(bytes(data), Limits())


def test_cached_inline_fields_retained_without_metadata_or_deleted_text():
    d = parse('<text:p>Page <text:page-number>3</text:page-number> of '
              '<text:page-count>8</text:page-count>; <text:date>21 Oct</text:date> '
              '<text:time>12:30</text:time> <text:sequence>7</text:sequence> '
              '<text:title>Shown title</text:title>'
              '<office:annotation><text:p>PRIVATE</text:p></office:annotation>'
              '<text:tracked-changes><text:deletion><text:p>DELETED</text:p>'
              '</text:deletion></text:tracked-changes></text:p>',
              extra={'meta.xml': '<title>SECRET metadata</title>'})
    assert d.text == 'Page 3 of 8; 21 Oct 12:30 7 Shown title'


def test_supported_simple_text_and_cached_fields_do_not_warn():
    d = parse('<text:h>Heading</text:h><text:p>page <text:page-number>2</text:page-number></text:p>')
    assert d.text == 'Heading\n\npage 2'
    assert d.warnings == []


def test_hidden_fields_do_not_leak_stored_value():
    d = parse('<text:p>A<text:variable-set text:display="none">SECRET</text:variable-set>'
              '<text:hidden-text text:is-hidden="true">PRIVATE</text:hidden-text>B</text:p>')
    assert d.text == 'AB'
