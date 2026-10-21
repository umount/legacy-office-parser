"""Independent synthetic DOCX oracle tests; no LibreOffice or private fixtures."""
import importlib.util
import io
import json
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZipFile

import pytest

from legacy_office_parser.models import Cell, Document, Paragraph, Table

_spec = importlib.util.spec_from_file_location(
    'document_reference', Path(__file__).resolve().parents[1] / 'tools/_document_reference.py')
reference = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reference)

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'


def p(text):
    return '<w:p><w:r><w:t>' + escape(text) + '</w:t></w:r></w:p>'


def tc(text='', props='', content=None):
    return '<w:tc><w:tcPr>' + props + '</w:tcPr>' + (
        p(text) if content is None else content) + '</w:tc>'


def tr(content, props=''):
    return '<w:tr><w:trPr>' + props + '</w:trPr>' + content + '</w:tr>'


def tbl(rows, width=0):
    return '<w:tbl><w:tblGrid>' + '<w:gridCol/>' * width + '</w:tblGrid>' + rows + '</w:tbl>'


def compare(doc, body, **parts):
    stream = io.BytesIO()
    with ZipFile(stream, 'w') as archive:
        archive.writestr('word/document.xml',
                         f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>')
        for name, (tag, content) in parts.items():
            archive.writestr('word/' + name + '.xml',
                             f'<w:{tag} xmlns:w="{W}">{content}</w:{tag}>')
    with ZipFile(stream) as archive:
        result = reference.compare_document(doc, archive)
        assert archive.fp is not None  # Caller owns its lifetime.
    return result


@pytest.mark.parametrize('fmt', ['doc', 'rtf', 'odt'])
def test_equal_body_and_table_for_all_document_formats(fmt):
    doc = Document(fmt, blocks=[Paragraph('Intro'), Table([[Cell('one'), Cell('two')]]),
                               Paragraph('End')])
    report = compare(doc, p('Intro') + tbl(tr(tc('one') + tc('two')), 2) + p('End'))
    assert report['equal'] and report['complete']
    assert report['body']['table_checks'][0]['equal']


@pytest.mark.parametrize('actual', ['beta alpha', 'Alpha beta', 'alpha beta!', 'alphabeta'])
def test_equal_counts_or_bagwords_do_not_prove_text_equality(actual):
    result = compare(Document('doc', blocks=[Paragraph(actual)]), p('alpha beta'))
    assert not result['equal']
    assert not result['body']['text_equal']


def test_runs_join_and_whitespace_is_the_only_normalization():
    xml = '<w:p><w:r><w:t>alpha</w:t></w:r><w:hyperlink><w:r><w:t>bet</w:t>' \
          '<w:tab/><w:t>one</w:t><w:br/><w:t>two</w:t><w:cr/><w:t>three</w:t>' \
          '<w:noBreakHyphen/><w:t>x</w:t><w:softHyphen/><w:t>y</w:t>' \
          '</w:r></w:hyperlink></w:p>'
    doc = Document('rtf', blocks=[Paragraph('alphabet one\n two three\u2011x\u00ady')])
    assert compare(doc, xml)['equal']
    doc.blocks = [Paragraph('alpha bet one two three\u2011x\u00ady')]
    assert not compare(doc, xml)['equal']
    assert compare(Document('doc', blocks=[Paragraph('one two')]), p('one') + p('two'))['equal']


def test_cell_paragraph_boundaries_are_not_deleted():
    xml = tbl(tr(tc(content=p('one') + p('two'))))
    assert compare(Document('doc', blocks=[Table([[Cell('one\ntwo')]])]), xml)['equal']
    assert not compare(Document('doc', blocks=[Table([[Cell('onetwo')]])]), xml)['equal']


def test_table_order_and_cell_coordinates_with_same_counts():
    xml = tbl(tr(tc('a') + tc('b'))) + tbl(tr(tc('c') + tc('d')))
    doc = Document('doc', blocks=[Table([[Cell('c'), Cell('d')]]),
                                 Table([[Cell('a'), Cell('b')]])])
    result = compare(doc, xml)
    assert result['body']['table_count_equal']
    assert not result['equal']
    assert all(not t['equal'] for t in result['body']['table_checks'])
    doc.blocks = [Table([[Cell('b'), Cell('a')]]), Table([[Cell('c'), Cell('d')]])]
    assert not compare(doc, xml)['body']['table_checks'][0]['equal']


def test_table_placement_and_count_are_checked():
    doc = Document('doc', blocks=[Table([[Cell('a')]]), Paragraph('end')])
    assert not compare(doc, p('end') + tbl(tr(tc('a'))))['equal']
    assert not compare(doc, tbl(tr(tc('a'))) + tbl(tr(tc('extra'))))['equal']
    assert not compare(Document('doc'), tbl(''))['equal']


def test_horizontal_and_vertical_spans_and_covered_coordinates():
    xml = tbl(tr(tc('anchor', '<w:gridSpan w:val="2"/><w:vMerge w:val="restart"/>') + tc('x')) +
              tr(tc('', '<w:gridSpan w:val="2"/><w:vMerge/>') + tc('y')) +
              tr(tc('', '<w:gridSpan w:val="2"/><w:vMerge w:val="continue"/>') + tc('z')), 3)
    doc = Document('odt', blocks=[Table([
        [Cell('anchor', row_span=3, col_span=2), Cell(covered=True), Cell('x')],
        [Cell(covered=True), Cell(covered=True), Cell('y')],
        [Cell(covered=True), Cell(covered=True), Cell('z')]])])
    assert compare(doc, xml)['equal']
    doc.blocks[0].rows[0][0].row_span = 2
    result = compare(doc, xml)
    assert not result['equal']
    assert result['body']['table_checks'][0]['cell_mismatches'][0]['row_span_equal'] is False
    doc.blocks[0].rows[0][0].row_span = 3
    doc.blocks[0].rows[0][0].col_span = 1
    assert not compare(doc, xml)['equal']


def test_vertical_continuation_text_is_retained_at_its_coordinate():
    xml = tbl(tr(tc('a', '<w:vMerge w:val="restart"/>')) + tr(tc('b', '<w:vMerge/>')))
    doc = Document('doc', blocks=[Table([[Cell('a', row_span=2)], [Cell('b', covered=True)]])])
    assert compare(doc, xml)['equal']
    doc.blocks[0].rows[1][0].text = ''
    assert not compare(doc, xml)['equal']


def test_grid_before_after_do_not_shift_or_invent_cells():
    xml = tbl(tr(tc('middle'), '<w:gridBefore w:val="1"/><w:gridAfter w:val="1"/>'), 3)
    doc = Document('doc', blocks=[Table([[Cell(), Cell('middle'), Cell()]])])
    result = compare(doc, xml)
    table = result['body']['table_checks'][0]
    assert table['dimensions_equal']
    assert table['reference_cells'] == 1 and table['reference_omitted_cells'] == 2
    assert [c['column'] for c in table['cell_mismatches']] == [1, 3]
    assert all(not c['reference_present'] for c in table['cell_mismatches'])
    # Even an empty physical tc is different from an absent coordinate.
    assert not result['equal']
    shifted = compare(Document('doc', blocks=[Table([[Cell('middle')]])]), xml)
    assert len(shifted['body']['table_checks'][0]['cell_mismatches']) == 2


def test_short_rows_and_missing_rows_not_padded_with_empty_cells():
    result = compare(Document('doc', blocks=[Table([[Cell('a'), Cell()]])]), tbl(tr(tc('a')), 2))
    assert result['body']['table_checks'][0]['reference_omitted_cells'] == 1
    assert not result['equal']
    assert not compare(Document('doc', blocks=[Table([])]), tbl(tr('')))['equal']


@pytest.mark.parametrize('rows', [
    tr(tc('', '<w:vMerge/>')),
    tr(tc('', '<w:vMerge w:val="restart"/>')) + tr('') + tr(tc('', '<w:vMerge/>')),
    tr(tc('', '<w:gridSpan w:val="2"/><w:vMerge w:val="restart"/>')) +
    tr(tc('', '<w:vMerge/>')),
])
def test_orphan_or_changed_interval_vertical_merge_is_unsupported(rows):
    result = compare(Document('doc'), tbl(rows))
    assert result['unsupported_scopes']['orphan_vertical_merge'] == 1
    assert not result['complete']


def test_nested_table_is_not_flattened_into_outer_cell_or_body_tables():
    result = compare(Document('doc', blocks=[Table([[Cell('outer')]])]),
                     tbl(tr(tc(content=p('outer') + tbl(tr(tc('nested secret')))))))
    assert result['body']['reference_tables'] == 1
    assert result['unsupported_scopes'] == {}
    assert result['body']['table_checks'][0]['complete']
    assert not result['body']['table_checks'][0]['equal']
    assert not result['body']['equal'] and result['complete']


def test_notes_are_separate_and_separators_are_excluded():
    parts = {
        'footnotes': ('footnotes', '<w:footnote w:type="separator" w:id="-1">' + p('separator secret') +
                      '</w:footnote><w:footnote w:type="continuationSeparator" w:id="0">' + p('separator zero') +
                      '</w:footnote><w:footnote w:id="1">' + p('foot') + '</w:footnote>'),
        'endnotes': ('endnotes', '<w:endnote w:id="3">' + p('end') + '</w:endnote>')}
    doc = Document('doc', blocks=[Paragraph('body')], footnotes='foot', endnotes='end')
    result = compare(doc, p('body'), **parts)
    assert result['equal']
    assert result['footnotes']['reference_notes'] == 1
    doc.footnotes = 'wrong'
    result = compare(doc, p('body'), **parts)
    assert result['body']['equal'] and result['endnotes']['equal']
    assert not result['footnotes']['equal'] and not result['equal']
    assert not compare(Document('doc', footnotes='lost'), '')['footnotes']['equal']


def test_note_order_and_table_text():
    xml = '<w:footnote w:id="2">' + p('two') + '</w:footnote>' \
          '<w:footnote w:id="1">' + p('one') + '</w:footnote>'
    result = compare(Document('doc', footnotes='one two'), '', footnotes=('footnotes', xml))
    assert not result['footnotes']['equal']
    xml = '<w:footnote w:id="1">' + tbl(tr(tc('hidden'))) + '</w:footnote>'
    result = compare(Document('doc', footnotes='hidden'), '', footnotes=('footnotes', xml))
    assert result['footnotes']['complete'] and result['equal']
    assert result['footnotes']['tables_text_only']


def test_headers_are_explicit_unpaired_part_scopes_not_body_or_note_text():
    result = compare(Document('doc', blocks=[Paragraph('body')], headers_footers='pooled'),
                     p('body'), header9=('hdr', p('header private')),
                     footer1=('ftr', p('footer private')))
    assert result['body']['equal'] and result['footnotes']['equal']
    assert not result['complete'] and not result['equal']
    assert len(result['headers_footers']['reference_parts']) == 2
    assert not result['headers_footers']['comparable']


@pytest.mark.parametrize('xml,key', [
    ('<w:sdt><w:sdtContent>' + tbl(tr(tc('hidden'))) + '</w:sdtContent></w:sdt>', 'nested_tables'),
    (p('ok') + '<w:altChunk/>', 'xml_scopes'),
    ('<w:p><w:r><w:drawing><w:txbxContent>' + p('box') +
     '</w:txbxContent></w:drawing></w:r></w:p>', 'textboxes'),
    (tbl(tr(tc('', '<w:hMerge/>'))), 'horizontal_merge'),
    (tbl(tr(tc('', '<w:gridSpan w:val="-4"/>'))), 'invalid_grid'),
])
def test_unsupported_scopes_never_claim_full_equality(xml, key):
    result = compare(Document('doc'), xml)
    assert result['unsupported_scopes'][key]
    assert not result['complete'] and not result['equal']


def test_report_contains_only_numeric_boolean_values_and_fixed_keys():
    secret = 'PRIVATE_CONTENT_735!'
    result = compare(Document('doc', blocks=[Paragraph(secret), Table([[Cell(secret)]])],
                              footnotes=secret, textboxes=secret, warnings=[secret]),
                     p('other') + tbl(tr(tc('different'))), header7=('hdr', p(secret)))
    assert secret not in json.dumps(result)

    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == 'status':
                    assert child in {'ok', 'inconclusive', 'invalid_reference'}
                else:
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
        else:
            assert value is None or type(value) in (int, bool)
    walk(result)


def test_paragraphs_inside_content_controls_keep_text_boundaries():
    xml = '<w:sdt><w:sdtContent>' + p('one') + p('two') + '</w:sdtContent></w:sdt>'
    assert compare(Document('doc', blocks=[Paragraph('one two')]), xml)['equal']
    assert not compare(Document('doc', blocks=[Paragraph('onetwo')]), xml)['equal']


def test_inline_content_control_does_not_add_word_boundaries():
    xml = '<w:p><w:r><w:t>pre</w:t></w:r><w:sdt><w:sdtContent>' \
          '<w:r><w:t>fix</w:t></w:r></w:sdtContent></w:sdt></w:p>'
    assert compare(Document('doc', blocks=[Paragraph('prefix')]), xml)['equal']


def test_empty_document_is_complete_and_equal():
    result = compare(Document('doc'), '')
    assert result['equal'] and result['complete']


@pytest.mark.parametrize('known_difference', [False, True])
def test_incomplete_root_equality_is_unknown_even_with_known_differences(known_difference):
    doc = Document('doc', blocks=[Paragraph('different' if known_difference else 'same')],
                   textboxes='unpaired')
    result = compare(doc, p('same'), header1=('hdr', p('unpaired')))
    assert result['equal'] is None
    assert result['complete'] is False
    assert result['status'] == 'inconclusive'
    assert result['body']['equal'] is (not known_difference)


def test_complete_difference_is_false_not_unknown():
    result = compare(Document('doc', blocks=[Paragraph('wrong')]), p('right'))
    assert result['equal'] is False and result['complete'] is True
    assert result['status'] == 'ok'


@pytest.mark.parametrize('part,content', [
    ('word/document.xml', None),
    ('word/document.xml', '<private-broken-xml'),
    ('word/document.xml', '<?xml version="1.0" encoding="PRIVATE-unknown"?><root/>'),
    ('word/document.xml', f'<w:document xmlns:w="{W}">' + p('no body') + '</w:document>'),
    ('word/document.xml', f'<w:document xmlns:w="{W}"><w:body/><w:body/></w:document>'),
    ('word/document.xml', f'<w:wrong xmlns:w="{W}"><w:body/></w:wrong>'),
    ('word/footnotes.xml', '<private-broken-note'),
    ('word/endnotes.xml', '<wrong-root/>'),
    ('word/header1.xml', '<private-broken-header'),
    ('word/footer1.xml', '<wrong-root/>'),
])
def test_malformed_reference_is_sanitized_inconclusive(part, content):
    stream = io.BytesIO()
    with ZipFile(stream, 'w') as archive:
        if part != 'word/document.xml':
            archive.writestr('word/document.xml',
                             f'<w:document xmlns:w="{W}"><w:body/></w:document>')
        if content is not None:
            archive.writestr(part, content)
    with ZipFile(stream) as archive:
        result = reference.compare_document(Document('doc'), archive)
    assert result == {'status': 'invalid_reference', 'complete': False, 'equal': None}
    assert 'private' not in json.dumps(result)


@pytest.mark.parametrize('error', [
    reference.BadZipFile('PRIVATE crc error'), OSError('PRIVATE path'),
    EOFError('PRIVATE'), RuntimeError('PRIVATE encrypted part'),
    NotImplementedError('PRIVATE compression'), reference.zlib.error('PRIVATE compressed data'),
])
def test_archive_read_errors_are_sanitized(error):
    class BrokenArchive:
        def read(self, name):
            raise error
    assert reference.compare_document(Document('doc'), BrokenArchive()) == {
        'status': 'invalid_reference', 'complete': False, 'equal': None}


@pytest.mark.parametrize('kind', ['footnotes', 'endnotes'])
@pytest.mark.parametrize('type_attribute', ['', ' w:type="normal"'])
def test_normal_note_zero_is_not_a_separator(kind, type_attribute):
    tag = kind[:-1]
    xml = f'<w:{tag} w:id="0"{type_attribute}>' + p('real note zero') + f'</w:{tag}>'
    doc = Document('odt', **{kind: 'real note zero'})
    result = compare(doc, '', **{kind: (kind, xml)})
    assert result['equal'] is True and result[kind]['reference_notes'] == 1
    setattr(doc, kind, '')
    assert compare(doc, '', **{kind: (kind, xml)})['equal'] is False


@pytest.mark.parametrize('note_type', ['separator', 'continuationSeparator', 'continuationNotice'])
@pytest.mark.parametrize('kind', ['footnotes', 'endnotes'])
def test_special_note_is_excluded_by_type_not_id(note_type, kind):
    tag = kind[:-1]
    xml = f'<w:{tag} w:id="42" w:type="{note_type}">' + p('special') + f'</w:{tag}>'
    result = compare(Document('doc'), '', **{kind: (kind, xml)})
    assert result['equal'] is True and result[kind]['reference_notes'] == 0


@pytest.mark.parametrize('kind', ['footnotes', 'endnotes'])
def test_note_table_text_preserves_order_and_boundaries(kind):
    tag = kind[:-1]
    table = tbl(tr(tc(content=p('one') + p('two')) + tc('three')) +
                tr(tc('four', '<w:gridSpan w:val="2"/>')), 2)
    xml = f'<w:{tag} w:id="1">' + p('before') + table + p('after') + f'</w:{tag}>'
    doc = Document('odt', **{kind: 'before\n\none\ntwo\tthree\nfour\t\n\nafter'})
    result = compare(doc, '', **{kind: (kind, xml)})
    assert result['equal'] is True and result[kind]['complete']
    assert result[kind]['tables_text_only'] is True
    for wrong in ('before onetwo three four after', 'before one two four three after'):
        setattr(doc, kind, wrong)
        result = compare(doc, '', **{kind: (kind, xml)})
        assert result['equal'] is False and result['body']['equal'] is True


def test_nested_note_table_remains_explicitly_unsupported():
    xml = '<w:footnote w:id="1">' + tbl(tr(tc(content=tbl(tr(tc('nested')))))) + '</w:footnote>'
    result = compare(Document('odt'), '', footnotes=('footnotes', xml))
    assert result['equal'] is None
    assert result['footnotes']['equal'] is None
    assert result['unsupported_scopes']['footnotes_nested_tables'] == 1
