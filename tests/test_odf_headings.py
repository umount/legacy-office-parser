"""Original synthetic ODF heading packages; no external document fixtures."""
import json

import pytest

from legacy_office_parser import Limits, LimitExceededError, parse_odt
from legacy_office_parser.odf import parse_odf_bytes
from test_odf import package, parse
from test_odf_stories import frame, master, note, styles, table
from test_odf_story_blocks import document, KEYS

HEADING_WARNING = ('ODF heading level invalid or outside supported range 1-9; '
                   'text retained without heading metadata.')


def h(text='Heading', level='2'):
    attr = '' if level is None else f' text:outline-level="{level}"'
    return f'<text:h{attr}>{text}</text:h>'


def p(text='plain'):
    return f'<text:p>{text}</text:p>'


@pytest.mark.parametrize('level,expected', [
    (None, 1), *[(str(n), n) for n in range(1, 10)],
    ('+03', 3), (' 0009&#x9;', 9), ('0' * 5000 + '4', 4),
    ('', None), ('0', None), ('-1', None), ('10', None), ('99', None),
    ('9' * 5000, None), ('1.0', None), ('1e0', None), ('true', None),
    ('1 2', None), ('++1', None), ('١', None), ('\u00a01', None),
])
def test_heading_level_default_lexical_space_and_invalid_policy(level, expected):
    doc = parse(h('A<text:span>B</text:span><text:s/>C', level))
    assert doc.blocks[0].heading_level == expected
    assert doc.text == 'AB C'
    encoded = doc.to_dict()['blocks'][0]
    if expected is None:
        assert 'heading_level' not in encoded
        assert doc.warnings == [HEADING_WARNING]
    else:
        assert encoded['heading_level'] == expected
        assert doc.warnings == []


def test_styles_and_paragraph_attributes_do_not_infer_headings():
    common = ('<style:style style:name="Heading_20_1" style:family="paragraph" '
              'style:default-outline-level="4"/>')
    doc = parse('<text:p text:style-name="Heading_20_1" text:outline-level="3">A</text:p>'
                '<text:h text:style-name="Heading_20_1">B</text:h>' + h('', '9'),
                extra={'styles.xml': styles('', common)})
    assert [b.heading_level for b in doc.blocks] == [None, 1, 9]
    assert doc.blocks[-1].text == ''


def test_cell_wrappers_nested_tables_and_repeats_keep_independent_headings():
    body = ('<text:section><text:list><text:list-item>' + h('outer', '3') +
            '</text:list-item></text:list></text:section>' + table(h('inner', '9')) + p())
    doc = parse(table(body, rows=2, columns=2))
    for row in doc.blocks[0].rows:
        for cell in row:
            assert cell.text == 'outer\ninner\nplain'
            assert cell.blocks[0].heading_level == 3
            assert cell.blocks[1].rows[0][0].blocks[0].heading_level == 9
            assert cell.blocks[2].heading_level is None
    first, second = doc.blocks[0].rows[0]
    first.blocks[0].heading_level = 1
    first.blocks[1].rows[0][0].blocks[0].heading_level = 2
    assert second.blocks[0].heading_level == 3
    assert second.blocks[1].rows[0][0].blocks[0].heading_level == 9


@pytest.mark.parametrize('key', KEYS)
def test_heading_only_stories_opt_in_entire_pool_including_empty_blocks(key):
    doc = parse_odt(document(key, [p('before'), h('', '1') + h('title', '4'), p('after')]))
    blocks = doc.story_blocks[key]
    assert [b.heading_level for b in blocks] == [None, 1, 4, None]
    assert [b.text for b in blocks] == ['before', '', 'title', 'after']
    assert getattr(doc, key) == doc.text == 'before\n\ntitle\n\nafter'
    assert doc.to_dict()['story_blocks'][key][2]['heading_level'] == 4


@pytest.mark.parametrize('key', KEYS)
def test_nested_heading_cells_in_stories(key):
    doc = parse_odt(document(key, [table(h('outer') + table(h('inner', '7')))]))
    cell = doc.story_blocks[key][0].rows[0][0]
    assert cell.blocks[0].heading_level == 2
    assert cell.blocks[1].rows[0][0].blocks[0].heading_level == 7
    assert getattr(doc, key) == 'outer\ninner'


@pytest.mark.parametrize('wrap,key', [(frame, 'textboxes'),
                                      (note, 'footnotes'),
                                      (lambda b: note(b, 'endnote'), 'endnotes')])
def test_heading_only_detached_stories_survive_repeated_cells(wrap, key):
    doc = parse(table(p(wrap(h('title', '5'))), rows=2, columns=3))
    blocks = doc.story_blocks[key]
    assert len(blocks) == 6
    assert [b.heading_level for b in blocks] == [5] * 6
    assert getattr(doc, key) == '\n\n'.join(['title'] * 6)
    blocks[0].heading_level = 1
    assert blocks[1].heading_level == 5


def test_hidden_covered_and_unsupported_headings_do_not_opt_in():
    hidden = '<text:section text:display="none">' + h() + '</text:section>'
    doc = parse(table(p() + hidden) + frame(p() + hidden) +
                '<table:table><table:table-row><table:covered-table-cell>' + h() +
                '</table:covered-table-cell></table:table-row></table:table>' +
                '<office:annotation>' + h() + '</office:annotation>')
    assert doc.blocks[0].rows[0][0].blocks == []
    assert doc.blocks[1].rows[0][0].blocks == []
    assert doc.story_blocks == {}
    assert 'heading_level' not in json.dumps(doc.to_dict())


@pytest.mark.parametrize('key', KEYS)
def test_invalid_headings_do_not_expand_legacy_story_contract(key):
    doc = parse_odt(document(key, [h('title', '10')]))
    assert getattr(doc, key) == 'title'
    assert doc.story_blocks == {}
    assert doc.warnings.count(HEADING_WARNING) == 1


@pytest.mark.parametrize('level', ['', '0', '-1', '10', '+00010', 'source-secret',
                                 '9' * 5000],
                         ids=['empty', 'zero', 'negative', 'ten', 'padded', 'invalid', 'huge'])
@pytest.mark.parametrize('structured', [False, True])
def test_invalid_cell_headings_warn_without_exposing_source(level, structured):
    body = h('retained-secret', level)
    if structured:
        body = h('valid') + body
    doc = parse(table('<text:section>' + body + '</text:section>', rows=2, columns=3))
    assert doc.warnings == [HEADING_WARNING]
    for row in doc.blocks[0].rows:
        for cell in row:
            assert 'retained-secret' in cell.text
            if structured:
                assert cell.blocks[-1].heading_level is None
            else:
                assert cell.blocks == []


def test_heading_warning_deduplicates_across_body_cells_and_stories():
    bad = h('content-secret', 'source-secret')
    doc = parse(h('body', '10') + table(bad + p(frame(bad) + note(bad) +
                note(bad, 'endnote')), rows=2, columns=3),
                extra={'styles.xml': styles(master('<style:header>' + bad + '</style:header>'))})
    assert doc.warnings.count(HEADING_WARNING) == 1
    assert 'source-secret' not in '\n'.join(doc.warnings)
    assert 'content-secret' not in '\n'.join(doc.warnings)
    for key in KEYS:
        assert 'content-secret' in getattr(doc, key)


def test_omitted_headings_and_paragraph_attributes_do_not_warn():
    bad = h('omitted-secret', 'source-secret')
    doc = parse('<text:p text:outline-level="source-secret">plain</text:p>' +
                '<text:section text:display="none">' + bad + '</text:section>' +
                '<table:table><table:table-row><table:covered-table-cell>' + bad +
                '</table:covered-table-cell></table:table-row></table:table>' +
                '<office:annotation>' + bad + '</office:annotation>')
    assert HEADING_WARNING not in doc.warnings
    assert 'source-secret' not in '\n'.join(doc.warnings)


@pytest.mark.parametrize('fmt', ['ods', 'odp'])
def test_non_odt_invalid_heading_does_not_warn(fmt):
    body = table(h('cell', '10'))
    if fmt == 'odp':
        body = '<draw:page>' + body + '</draw:page>'
    assert HEADING_WARNING not in parse(body, fmt).warnings


@pytest.mark.parametrize('reader', [parse_odt, lambda data, limits: parse_odf_bytes(data, limits)])
@pytest.mark.parametrize('location,ceiling', [('cell', 4000), ('story', 2000),
                                            ('repeated-story', 12010)])
def test_retained_heading_text_budgets(reader, location, ceiling):
    heading = h('<text:s text:c="1000"/>')
    if location == 'cell':
        data = package(table(heading, rows=2))  # Two projections plus two blocks.
    elif location == 'story':
        data = package(frame(heading))  # Legacy string plus heading block.
    else:
        data = package(table(p(frame(heading)), rows=2, columns=3))
    doc = reader(data, limits=Limits(max_text_chars=ceiling))
    assert 'heading_level' in json.dumps(doc.to_dict())
    with pytest.raises(LimitExceededError):
        reader(data, limits=Limits(max_text_chars=ceiling - 1))


@pytest.mark.parametrize('fmt', ['ods', 'odp'])
def test_other_odf_formats_keep_string_contract_without_heading_metadata(fmt):
    body = table(h('cell', '4'))
    if fmt == 'odp':
        body = '<draw:page>' + frame(h('slide', '3')) + body + '</draw:page>'
    doc = parse(body, fmt)
    assert doc.blocks == [] and doc.story_blocks == {}
    assert 'heading_level' not in json.dumps(doc.to_dict())
    assert 'cell' in doc.text
    if fmt == 'odp':
        assert doc.slides[0].text == 'slide\ncell'


def test_inline_object_heading_is_retained_as_textbox_story():
    body = ('<draw:frame><draw:object><office:document '
            'office:mimetype="application/vnd.oasis.opendocument.text">'
            '<office:body><office:text>' + h('embedded', '6') +
            '</office:text></office:body></office:document></draw:object></draw:frame>')
    doc = parse(body)
    assert doc.textboxes == 'embedded'
    assert doc.story_blocks['textboxes'][0].heading_level == 6


def test_unused_master_heading_does_not_leak():
    doc = parse(p(), extra={'styles.xml': styles(
        master('<style:header>' + p('used') + '</style:header>') +
        master('<style:header>' + h('unused') + '</style:header>', 'Other'))})
    assert doc.headers_footers == 'used'
    assert doc.story_blocks == {}


def test_heading_after_nested_table_still_validates_retained_cell_text():
    data = package(table('<table:table/>' + h('<text:s text:c="1000"/>'), rows=2))
    # Each repeated cell retains a 1001-character projection and a heading block.
    doc = parse_odf_bytes(data, Limits(max_text_chars=4002))
    assert doc.blocks[0].rows[1][0].blocks[1].heading_level == 2
    with pytest.raises(LimitExceededError):
        parse_odf_bytes(data, Limits(max_text_chars=4001))
