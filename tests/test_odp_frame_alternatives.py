"""Original synthetic ODP frames; no renderer or external fixture required."""
from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from legacy_office_parser import Limits, LimitExceededError, parse
from test_odf import package


def box(text=''):
    return '<draw:text-box><text:p>' + text + '</text:p></draw:text-box>'


def frame(body, attrs=''):
    return f'<draw:frame {attrs}>' + body + '</draw:frame>'


def table(text=''):
    return ('<table:table><table:table-row><table:table-cell><text:p>' + text +
            '</text:p></table:table-cell></table:table-row></table:table>')


def data(body, attrs=''):
    return package(f'<draw:page {attrs}>' + body + '</draw:page>', 'odp')


@pytest.mark.parametrize('first', [box('first'), table('first')])
@pytest.mark.parametrize('second', [box('later'), table('later')])
def test_first_supported_alternative_only(first, second):
    doc = parse(data(frame(first + second)))
    assert doc.slides[0].text == doc.text == 'first'
    assert doc.textboxes == ''


@pytest.mark.parametrize('first', ['<draw:text-box/>', box(), '<table:table/>', table()])
def test_empty_supported_alternative_wins(first):
    doc = parse(data(frame(first + box('must not escape'))))
    assert doc.slides[0].text == doc.text == ''


@pytest.mark.parametrize('unsupported', [
    '<draw:image><text:p>image text</text:p></draw:image>',
    '<draw:object><office:document><office:body><office:text><text:p>embedded</text:p>'
    '</office:text></office:body></office:document></draw:object>',
    '<draw:object-ole/>', '<draw:plugin/>',
    '<draw:g>' + box('invalid frame child') + '</draw:g>',
])
def test_unsupported_first_does_not_own_text(unsupported):
    doc = parse(data(frame(unsupported + box('selected') + box('later'))))
    assert doc.slides[0].text == doc.text == 'selected'
    assert doc.warnings


def test_identical_independent_frames_remain_independent():
    content = frame(box('same') + box('same'))
    doc = parse(data(content + content))
    assert doc.slides[0].text == doc.text == 'same\nsame'


def test_title_and_notes_inherit_destination_without_leaking_alternatives():
    body = frame(box('title') + box('wrong title'), 'presentation:class="title"')
    body += frame(table('body') + box('wrong body'))
    body += '<presentation:notes>' + frame(box('notes') + box('wrong notes'),
                                          'presentation:class="title"') + '</presentation:notes>'
    slide = parse(data(body)).slides[0]
    assert (slide.title, slide.text, slide.notes) == ('title', 'body', 'notes')


@pytest.mark.parametrize('hidden', [
    '<text:p>secret<text:hidden-paragraph text:is-hidden="true"/></text:p>',
    '<text:section text:display="none"><text:p>secret</text:p></text:section>',
    '<text:tracked-changes><text:changed-region><text:deletion><text:p>secret</text:p>'
    '</text:deletion></text:changed-region></text:tracked-changes>',
])
def test_hidden_or_deleted_first_content_does_not_select_fallback(hidden):
    doc = parse(data(frame('<draw:text-box>' + hidden + '</draw:text-box>' + box('fallback'))))
    assert doc.text == ''
    assert doc.textboxes == doc.footnotes == doc.endnotes == ''


def test_hidden_slide_keeps_existing_hidden_metadata_contract():
    slide = parse(data(frame(box('selected') + box('fallback')),
                       'presentation:visibility="hidden"')).slides[0]
    assert slide.hidden is True
    assert slide.text == 'selected'


def test_nested_frames_select_locally_and_keep_surrounding_text():
    inner = frame(box('inner') + box('wrong inner'))
    outer = '<draw:text-box><text:p>before</text:p>' + inner + '<text:p>after</text:p></draw:text-box>'
    assert parse(data(frame(outer + box('wrong outer')))).text == 'before\ninner\nafter'


def test_unselected_alternative_not_expanded_or_cell_budgeted():
    huge = table('<text:s text:c="1000000"/>').replace(
        '<table:table-row>', '<table:table-row table:number-rows-repeated="1000000">')
    assert parse(data(frame(box('selected') + huge)),
                 limits=Limits(max_text_chars=2000, max_cells=1)).text == 'selected'


def test_selected_output_exact_budget_and_independent_frame_separator():
    # Source is much smaller than output; 2 * (A + 1000 spaces + B) + newline.
    body = frame(box('A<text:s text:c="1000"/>B') + box('ignored'))
    payload = data(body + body)
    assert len(parse(payload, limits=Limits(max_text_chars=2005)).text) == 2005
    with pytest.raises(LimitExceededError, match='ODF rendered text limit exceeded'):
        parse(payload, limits=Limits(max_text_chars=2004))
    with pytest.raises(LimitExceededError, match='ODF expanded text limit exceeded'):
        parse(payload, limits=Limits(max_text_chars=2003))


def test_selected_table_exact_cell_budget():
    payload = data(frame(table('one') + table('unused')) + frame(table('two')))
    assert parse(payload, limits=Limits(max_cells=2)).text == 'one\ntwo'
    with pytest.raises(LimitExceededError, match='ODF cell limit exceeded'):
        parse(payload, limits=Limits(max_cells=1))


def test_unselected_xml_still_charged_against_source_and_node_limits():
    payload = data(frame(box('selected') + box('x' * 3000)))
    with ZipFile(BytesIO(payload)) as archive:
        roots = [ET.fromstring(archive.read(n)) for n in ('content.xml', 'META-INF/manifest.xml')]
    # Count independently from the XML, including unselected content and attributes.
    nodes = sum(1 for root in roots for _ in root.iter())
    chars = sum(len(e.text or '') + len(e.tail or '') +
                sum(len(k) + len(v) for k, v in e.attrib.items())
                for root in roots for e in root.iter())
    assert parse(payload, limits=Limits(max_records=nodes, max_text_chars=chars)).text == 'selected'
    with pytest.raises(LimitExceededError, match='ODF XML node limit exceeded'):
        parse(payload, limits=Limits(max_records=nodes - 1))
    with pytest.raises(LimitExceededError, match='ODF XML text/attribute limit exceeded'):
        parse(payload, limits=Limits(max_text_chars=chars - 1))


def test_unselected_xml_still_obeys_depth_limit():
    payload = data(frame(box('selected') + box('<text:span>' * 20 + 'unused' + '</text:span>' * 20)))
    with pytest.raises(LimitExceededError, match='ODF XML depth limit exceeded'):
        parse(payload, limits=Limits(max_depth=15))


def test_unsupported_only_frame_does_not_scrape_descendants():
    body = '<draw:image>' + box('secret') + '</draw:image><draw:object-ole/>'
    doc = parse(data(frame(body)))
    assert doc.text == ''
    assert doc.warnings


def test_frame_metadata_before_text_is_not_a_content_representation():
    meta = ('<svg:title xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0">'
            'metadata</svg:title><draw:glue-point/>')
    assert parse(data(frame(meta + box('selected') + box('fallback')))).text == 'selected'


def test_hidden_section_around_frame_does_not_leak_alternatives():
    hidden = '<text:section text:display="none">' + frame(box('secret') + box('fallback')) + '</text:section>'
    assert parse(data(hidden + frame(box('visible')))).text == 'visible'


def test_selected_limit_failure_is_not_a_reason_to_try_fallback():
    selected = table('x').replace('<table:table-row>',
                                '<table:table-row table:number-rows-repeated="2">')
    with pytest.raises(LimitExceededError, match='ODF cell limit exceeded'):
        parse(data(frame(selected + box('fallback'))), limits=Limits(max_cells=1))
