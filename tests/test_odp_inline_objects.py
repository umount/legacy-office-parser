"""Original inline text objects owned by ODP slides, never linked resources."""
import pytest

from legacy_office_parser import Limits, LimitExceededError, parse
from test_odf_inline_objects import embedded, p, table
from test_odp_frame_alternatives import box, data, frame


def test_inline_text_table_stays_with_owning_slide():
    body = embedded(p('Before') + table(p('Cell')) + p('After'))
    doc = parse(data(frame(body)))
    assert doc.slides[0].text == doc.text == 'Before\nCell\nAfter'
    assert doc.textboxes == '' and not doc.story_blocks
    assert any(d.code == 'odf_inline_text_object_projected_to_slide' for d in doc.diagnostics)


@pytest.mark.parametrize('body', ['', '<text:p/>',
    '<text:section text:display="none"><text:p>hidden</text:p></text:section>'])
def test_empty_selected_object_blocks_fallback(body):
    assert parse(data(frame(embedded(body) + box('fallback')))).text == ''


@pytest.mark.parametrize('first', [box('first'), embedded(p('first'))])
@pytest.mark.parametrize('last', [box('last'), embedded(p('last'))])
def test_source_order_selects_one_supported_representation(first, last):
    assert parse(data(frame(first + last))).text == 'first'


def test_independent_objects_keep_equal_text_and_nested_frames():
    obj = frame(embedded(p('same') + frame(embedded(p('nested')) + box('wrong'))))
    assert parse(data(obj + obj)).text == 'same\nnested\nsame\nnested'


@pytest.mark.parametrize('destination', ['body', 'title', 'notes'])
def test_embedded_presentation_attributes_cannot_change_host_destination(destination):
    content = frame(embedded(p('owned') +
        '<draw:frame presentation:class="title">' + box('inner') + '</draw:frame>' +
        '<presentation:notes>' + box('invalid') + '</presentation:notes>'))
    if destination == 'title':
        content = content.replace('<draw:frame ', '<draw:frame presentation:class="title" ', 1)
    elif destination == 'notes':
        content = '<presentation:notes>' + content + '</presentation:notes>'
    slide = parse(data(content)).slides[0]
    assert (slide.text, slide.title, slide.notes) == {
        'body': ('owned\ninner', '', ''), 'title': ('', 'owned\ninner', ''),
        'notes': ('', '', 'owned\ninner')}[destination]


@pytest.mark.parametrize('href', ['', '#id', 'Object 1/', 'file:///private', 'https://invalid.example/'])
def test_any_reference_keeps_object_unsupported(href):
    obj = embedded(p('never')).replace('<draw:object>',
        '<draw:object xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="' + href + '">')
    assert parse(data(frame(obj + box('fallback')))).text == 'fallback'


@pytest.mark.parametrize('obj', [
    embedded(p('never'), mime='application/vnd.oasis.opendocument.spreadsheet'),
    embedded(p('never')).replace('<office:body>', '<office:body/><office:body>'),
    embedded(p('never')).replace('office:document', 'office:document-content'),
    '<draw:object><office:text>' + p('never') + '</office:text></draw:object>',
])
def test_malformed_or_unsupported_document_does_not_scrape_text(obj):
    assert parse(data(frame(obj + box('fallback')))).text == 'fallback'


def test_embedded_styles_are_local_and_preludes_not_text():
    style = ('<office:automatic-styles><style:style style:name="Hidden" style:family="paragraph">'
             '<style:text-properties text:display="none"/></style:style></office:automatic-styles>')
    body = '<text:p text:style-name="Hidden">secret</text:p>' + p('public')
    obj = embedded(body, prelude=style + '<office:meta>' + p('metadata') + '</office:meta>')
    doc = parse(data(frame(obj) + frame(box('<text:span>outside</text:span>'))))
    assert doc.text == '\npublic\noutside'


def test_notes_and_inline_drawings_keep_explicit_existing_omission():
    # This increment does not introduce pooled footnotes or paragraph-anchored drawings in ODP.
    body = p('before<text:note text:note-class="footnote"><text:note-body>' +
             p('note omitted') + '</text:note-body></text:note>after')
    doc = parse(data(frame(embedded(body))))
    assert doc.text == 'beforeafter' and doc.footnotes == ''
    assert doc.warnings


def test_selected_object_uses_shared_cell_budget():
    obj = frame(embedded(table(p('cell'))))
    assert parse(data(obj + obj), limits=Limits(max_cells=2)).text == 'cell\ncell'
    with pytest.raises(LimitExceededError, match='cell limit'):
        parse(data(obj + obj), limits=Limits(max_cells=1))


def test_unselected_object_not_expanded_but_xml_is_bounded():
    obj = embedded(table(p('too many'), rows=1000))
    assert parse(data(frame(box('first') + obj)), limits=Limits(max_cells=1)).text == 'first'
    deep = embedded('<text:section>' * 30 + p('deep') + '</text:section>' * 30)
    with pytest.raises(LimitExceededError, match='depth limit'):
        parse(data(frame(box('first') + deep)), limits=Limits(max_depth=20))


def test_selected_object_exact_text_budget_includes_separator():
    obj = frame(embedded(p('A<text:s text:c="1000"/>B')))
    assert len(parse(data(obj + obj), limits=Limits(max_text_chars=2005)).text) == 2005
    with pytest.raises(LimitExceededError, match='rendered text limit'):
        parse(data(obj + obj), limits=Limits(max_text_chars=2004))


def test_selected_object_cached_display_and_unicode_are_literal():
    body = p('Ж 😀 <text:a xmlns:xlink="http://www.w3.org/1999/xlink" '
             'xlink:href="https://invalid.example/">label</text:a> '
             '<text:date>stored date</text:date>')
    doc = parse(data(frame(embedded(body))))
    assert doc.text == 'Ж 😀 label stored date'
    assert 'invalid.example' not in doc.text



def test_original_schema_valid_odp_and_matching_odt_control():
    from pathlib import Path
    from xml.etree import ElementTree as ET
    from zipfile import ZipFile
    root = Path(__file__).parent / 'fixtures' / 'odp_inline_objects'
    ns = {'o': 'urn:oasis:names:tc:opendocument:xmlns:office:1.0',
          'd': 'urn:oasis:names:tc:opendocument:xmlns:drawing:1.0',
          't': 'urn:oasis:names:tc:opendocument:xmlns:text:1.0'}
    with ZipFile(root / 'inline.odp') as z:
        xml = ET.fromstring(z.read('content.xml'))
    body = xml.find('o:body/o:presentation/d:page/d:frame/d:object/o:document/o:body/o:text', ns)
    assert body is not None
    assert [p.text for p in body.findall('.//t:p', ns)] == ['Object before', 'Object cell', 'Object after']
    doc = parse(root / 'inline.odp')
    assert len(doc.slides) == 1
    assert doc.slides[0].text == doc.text == 'Object before\nObject cell\nObject after'
    control = parse(root / 'inline.odt')
    assert control.textboxes == 'Object before\n\nObject cell\n\nObject after'
