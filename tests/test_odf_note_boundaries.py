"""Original synthetic ODT note bodies, occurrence ranges, repeats, and limits."""
import json

import pytest

from legacy_office_parser import Limits, LimitExceededError, Paragraph, Table, parse_odt
from legacy_office_parser._validation import _validate_result
from legacy_office_parser.odf import parse_odf_bytes
from test_odf import package
from test_odf_notes import note
from test_odf_stories import frame, master, styles, table


def p(text=''):
    return '<text:p>' + text + '</text:p>'


def read(data, limits=None):
    return parse_odf_bytes(data, limits or Limits())


def bodies(doc):
    return [doc.story_blocks[n.body.story][n.body.block_start:n.body.block_end] for n in doc.notes]


def assert_metadata(doc):
    previous = {}
    for n in doc.notes:
        assert n.source_cp is n.anchor_path is None
        assert n.reference_kind == 'unknown' and n.visibility == ['unknown']
        assert n.body.story == n.kind + 's'
        ordinal, end = previous.get(n.kind, (0, 0))
        assert n.ordinal == ordinal + 1
        assert n.body.block_start == end
        assert n.body.block_end > end
        previous[n.kind] = n.ordinal, n.body.block_end
    for kind, (_, end) in previous.items():
        assert end == len(doc.story_blocks[kind + 's'])
    _validate_result(doc, Limits())


@pytest.mark.parametrize('reader', [parse_odt, read])
def test_plain_notes_exact_ranges_order_and_unknown_reference_metadata(reader):
    data = package(p('Before' + note(p('F1') + p('') + p('F2'), citation='custom-secret') +
                     ' after' + note(p('E1'), 'endnote', 'ix')) +
                   p(note(p('F3'), citation='77')))
    doc = reader(data)
    assert [(n.kind, n.ordinal, n.body.block_start, n.body.block_end) for n in doc.notes] == [
        ('footnote', 1, 0, 3), ('endnote', 1, 0, 1), ('footnote', 2, 3, 4)]
    assert [[b.text for b in blocks] for blocks in bodies(doc)] == [['F1', '', 'F2'], ['E1'], ['F3']]
    assert doc.footnotes == 'F1\n\nF2\n\nF3' and doc.endnotes == 'E1'
    assert doc.text == 'Before after\n\nF1\n\nF2\n\nF3\n\nE1'
    encoded = doc.to_dict()['notes'][0]
    assert encoded == {'kind': 'footnote', 'ordinal': 1,
                       'body': {'story': 'footnotes', 'block_start': 0, 'block_end': 3},
                       'source_cp': None, 'anchor_path': None,
                       'reference_kind': 'unknown', 'visibility': ['unknown']}
    assert 'custom-secret' not in json.dumps(doc.to_dict())
    assert_metadata(doc)


@pytest.mark.parametrize('kind', ['footnote', 'endnote'])
@pytest.mark.parametrize('body', ['', p(), p('secret<text:hidden-paragraph text:is-hidden="true"/>'),
                                 '<office:annotation>' + p('secret') + '</office:annotation>'])
def test_empty_and_fully_omitted_body_owns_nonempty_range(kind, body):
    doc = parse_odt(package(p('host' + note(body, kind) + note(p('next'), kind))))
    assert [(n.body.block_start, n.body.block_end) for n in doc.notes] == [(0, 1), (1, 2)]
    assert isinstance(bodies(doc)[0][0], Paragraph) and bodies(doc)[0][0].text == ''
    assert getattr(doc, kind + 's') == 'next'
    assert doc.text == 'host\n\nnext'
    assert_metadata(doc)


def test_nested_table_and_detached_frame_do_not_share_note_body_range():
    body = p('before') + table(p('cell') + table(p('inner'))) + frame(p('box')) + p('after')
    doc = parse_odt(package(p(note(body) + note(p('end'), 'endnote'))))
    first, second = bodies(doc)
    assert [type(b) for b in first] == [Paragraph, Table, Paragraph]
    assert first[1].rows[0][0].blocks[1].rows[0][0].text == 'inner'
    assert second[0].text == 'end'
    assert doc.textboxes == 'box'
    assert doc.footnotes == 'before\n\ncell\ninner\n\nafter'
    assert_metadata(doc)


def test_frame_header_and_inline_object_notes_keep_source_ownership():
    embedded = ('<draw:frame><draw:object><office:document '
                'office:mimetype="application/vnd.oasis.opendocument.text">'
                '<office:body><office:text>' + p('embedded' + note(p('inner-note'))) +
                '</office:text></office:body></office:document></draw:object></draw:frame>')
    # An embedded text document can contain its own note while inside a host
    # note. That does not permit ordinary nested notes in the host document.
    outer = note(p('outer' + embedded + note(p('unsupported-nested'))))
    data = package(p(outer) + frame(p('frame' + note(p('frame-note'), 'endnote'))),
                   extra={'styles.xml': styles(master('<style:header>' +
                       p('header' + note(p('header-note'))) + '</style:header>'))})
    doc = parse_odt(data)
    assert [(n.kind, n.ordinal) for n in doc.notes] == [
        ('footnote', 1), ('footnote', 2), ('endnote', 1), ('footnote', 3)]
    assert [blocks[0].text for blocks in bodies(doc)] == ['outer', 'inner-note', 'frame-note', 'header-note']
    assert 'unsupported-nested' not in doc.text
    assert_metadata(doc)


@pytest.mark.parametrize('rows,columns', [(1, 3), (3, 1), (2, 3)])
def test_repeats_keep_cross_kind_encounter_order_distinct_ranges_and_trees(rows, columns):
    mixed = note(p('F1') + p('F2')) + note(p('E'), 'endnote') + note('')
    doc = parse_odt(package(table(p(mixed), rows=rows, columns=columns)))
    copies = rows * columns
    assert [n.kind for n in doc.notes] == ['footnote', 'endnote', 'footnote'] * copies
    assert [[b.text for b in body] for body in bodies(doc)] == [['F1', 'F2'], ['E'], ['']] * copies
    assert doc.footnotes == '\n\n'.join(['F1', 'F2'] * copies)
    assert doc.endnotes == '\n\n'.join(['E'] * copies)
    assert len({id(n.body) for n in doc.notes}) == len(doc.notes)
    assert len({id(n.visibility) for n in doc.notes}) == len(doc.notes)
    assert len({id(block) for body in bodies(doc) for block in body}) == copies * 4
    assert_metadata(doc)
    bodies(doc)[0][0].text = 'mutated'
    doc.notes[0].visibility.append('hidden')
    assert bodies(doc)[3][0].text == 'F1' and doc.notes[3].visibility == ['unknown']


def test_mixed_cells_and_nested_repeats_keep_row_major_note_order():
    inner = table(p(note(p('inner'), 'endnote') + note(p('foot'))), rows=2, columns=2)
    row = ('<table:table><table:table-row table:number-rows-repeated="2">'
           '<table:table-cell>' + p(note(p('first'))) + inner + '</table:table-cell>'
           '<table:table-cell table:number-columns-repeated="2">' + p(note(p('last'), 'endnote')) +
           '</table:table-cell></table:table-row></table:table>')
    doc = parse_odt(package(row))
    assert [body[0].text for body in bodies(doc)] == (['first'] + ['inner', 'foot'] * 4 + ['last'] * 2) * 2
    assert_metadata(doc)


@pytest.mark.parametrize('wrapper', [
    lambda b: '<text:section text:display="none">' + p(b) + '</text:section>',
    lambda b: p(b + '<text:hidden-paragraph text:is-hidden="true"/>'),
    lambda b: p('<text:span text:style-name="Hidden">' + b + '</text:span>'),
    lambda b: '<text:tracked-changes><text:changed-region text:id="x"><text:deletion>' + p(b) +
              '</text:deletion></text:changed-region></text:tracked-changes>',
    lambda b: '<office:annotation>' + p(b) + '</office:annotation>',
    lambda b: '<table:table><table:table-row><table:covered-table-cell>' + p(b) +
              '</table:covered-table-cell></table:table-row></table:table>',
])
def test_hidden_deleted_and_covered_sources_create_no_note_or_ordinal(wrapper):
    common = ('<style:style style:name="Hidden" style:family="text">'
              '<style:text-properties text:display="none"/></style:style>')
    data = package(wrapper(note(p('secret'))) + p('visible' + note(p('only'))),
                   extra={'styles.xml': styles('', common)})
    doc = parse_odt(data)
    assert len(doc.notes) == 1 and doc.notes[0].ordinal == 1
    assert doc.footnotes == 'only' and 'secret' not in json.dumps(doc.to_dict())
    assert_metadata(doc)


@pytest.mark.parametrize('body', ['<text:note text:note-class="footnote"/>',
                                 '<text:note text:note-class="footnote"><text:note-body/>'
                                 '<text:note-body/></text:note>', note(p('secret'), 'unknown')])
def test_malformed_note_does_not_allocate_identity(body):
    doc = parse_odt(package(p(body)))
    assert doc.notes == [] and doc.story_blocks == {} and doc.footnotes == ''
    assert doc.warnings


@pytest.mark.parametrize('reader', [parse_odt, read])
@pytest.mark.parametrize('copies', [1, 2, 6])
def test_plain_body_and_legacy_text_both_count_at_exact_budget(reader, copies):
    data = package(table(p(note(p('<text:s text:c="1000"/>'))), columns=copies))
    ceiling = 2000 * copies + 2 * (copies - 1)
    doc = reader(data, limits=Limits(max_text_chars=ceiling))
    assert len(doc.notes) == copies
    assert_metadata(doc)
    with pytest.raises(LimitExceededError):
        reader(data, limits=Limits(max_text_chars=ceiling - 1))


def test_repeat_text_is_rejected_before_any_detached_clone(monkeypatch):
    import legacy_office_parser.odf as odf

    def no_clone(cell):
        pytest.fail('over-budget note text must fail before cloning')

    monkeypatch.setattr(odf, '_clone_cell', no_clone)
    data = package(table(p(note(p('<text:s text:c="1000"/>'))), columns=2))
    with pytest.raises(LimitExceededError, match='retained story text'):
        parse_odt(data, limits=Limits(max_text_chars=4001))


def test_repeat_metadata_is_preflighted_before_any_clone(monkeypatch):
    import legacy_office_parser.odf as odf

    def no_clone(cell):
        pytest.fail('note metadata must be bounded before repeated tree allocation')

    monkeypatch.setattr(odf, '_clone_cell', no_clone)
    # Each copy needs a note record, a story occurrence, and its empty body
    # paragraph. Without the note record, 40 copies fit this record ceiling.
    data = package(table(p(note('')), columns=40))
    with pytest.raises(LimitExceededError, match='expanded story record'):
        parse_odt(data, limits=Limits(max_records=100))


def test_original_metadata_and_empty_sentinel_record_boundaries():
    from xml.etree import ElementTree as ET
    from legacy_office_parser._odf_package import Budget
    from legacy_office_parser.models import Document
    from legacy_office_parser.odf import _Parser
    from test_odf import NS

    xml = '<text:p xmlns:text="' + NS['text'] + '">' + note('') + '</text:p>'
    root = ET.fromstring(xml)
    for maximum in (1, 2):
        budget = Budget(Limits(max_records=maximum))
        parser = _Parser(Document('odt'), budget, ())
        if maximum == 1:
            with pytest.raises(LimitExceededError, match='empty note body record'):
                parser.inline(root)
        else:
            parser.inline(root)
            assert budget.nodes == 2 and parser.note_order == [('footnote', 0)]


@pytest.mark.parametrize('fmt', ['ods', 'odp'])
def test_non_odt_does_not_create_note_metadata(fmt):
    body = table(p(note(p('note body'))))
    if fmt == 'odp':
        body = '<draw:page>' + body + '</draw:page>'
    doc = read(package(body, fmt))
    assert doc.notes == [] and doc.story_blocks == {}
    assert ('note body' in doc.text) is (fmt == 'odp')


def test_embedded_same_kind_notes_repeated_with_parent_ranges_are_disjoint():
    embedded = ('<draw:frame><draw:object><office:document '
                'office:mimetype="application/vnd.oasis.opendocument.text">'
                '<office:body><office:text>' + p(note(p('inner'))) +
                '</office:text></office:body></office:document></draw:object></draw:frame>')
    doc = parse_odt(package(table(p(note(p('outer' + embedded))), rows=2, columns=2)))
    assert [body[0].text for body in bodies(doc)] == ['outer', 'inner'] * 4
    assert doc.footnotes == '\n\n'.join(['outer', 'inner'] * 4)
    assert [(n.body.block_start, n.body.block_end) for n in doc.notes] == [(i, i + 1) for i in range(8)]
    assert_metadata(doc)


def test_note_record_limit_is_checked_before_reserving_occurrence():
    from xml.etree import ElementTree as ET
    from legacy_office_parser._odf_package import Budget
    from legacy_office_parser.models import Document
    from legacy_office_parser.odf import _Parser
    from test_odf import NS

    root = ET.fromstring('<text:p xmlns:text="' + NS['text'] + '">' + note(p('body')) + '</text:p>')
    budget = Budget(Limits(max_records=1))
    budget.nodes = 1
    parser = _Parser(Document('odt'), budget, ())
    with pytest.raises(LimitExceededError, match='note metadata record'):
        parser.inline(root)
    assert parser.note_order == [] and parser.notes['footnote'] == []
