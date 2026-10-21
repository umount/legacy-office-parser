"""Corpus comparison regressions using synthetic XML only."""
import importlib.util
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

import pytest

from legacy_office_parser.models import Document, Paragraph

_spec = importlib.util.spec_from_file_location(
    'check_corpus', Path(__file__).resolve().parents[1] / 'tools' / 'check_corpus.py')
corpus = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(corpus)


def xml(content):
    return ET.fromstring(
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006">'
        + content + '</w:document>')


def paragraph(text):
    return '<w:p><w:r><w:t>' + text + '</w:t></w:r></w:p>'


def tokens(text):
    return re.findall(r'\w+', text)


def test_runs_join_but_paragraphs_cells_and_breaks_separate():
    root = xml('<w:body><w:p><w:r><w:t>alpha</w:t></w:r>'
               '<w:hyperlink><w:r><w:t>bet</w:t><w:tab/><w:t>tabbed</w:t>'
               '<w:br/><w:t>line</w:t><w:cr/><w:t>end</w:t></w:r></w:hyperlink>'
               '</w:p><w:tbl><w:tr><w:tc>' + paragraph('left') + '</w:tc>'
               '<w:tc>' + paragraph('right') + '</w:tc></w:tr></w:tbl></w:body>')
    text, tables = corpus._docx_text(root)
    assert tokens(text) == ['alphabet', 'tabbed', 'line', 'end', 'left', 'right']
    assert tables == 1


@pytest.mark.parametrize('branches,expected', [
    ('<mc:Choice Requires="x">' + paragraph('chosen') + '</mc:Choice>'
     '<mc:Choice Requires="y">' + paragraph('second') + '</mc:Choice>'
     '<mc:Fallback><w:tbl>' + paragraph('fallback') + '</w:tbl></mc:Fallback>', ['chosen']),
    ('<mc:Fallback>' + paragraph('fallback') + '</mc:Fallback>', ['fallback']),
    ('<mc:Choice Requires="x"/><mc:Fallback>' + paragraph('fallback') + '</mc:Fallback>', []),
])
def test_one_alternate_content_branch(branches, expected):
    text, tables = corpus._docx_text(xml('<mc:AlternateContent>' + branches + '</mc:AlternateContent>'))
    assert tokens(text) == expected
    assert tables == 0


def test_nested_textbox_paragraphs_are_counted_once_and_do_not_split_anchor_word():
    box = '<w:txbxContent>' + paragraph('box words') + '</w:txbxContent>'
    root = xml('<w:p><w:r><w:t>pre</w:t><w:drawing><mc:AlternateContent>'
               '<mc:Choice Requires="x">' + box + '</mc:Choice>'
               '<mc:Fallback>' + box + '</mc:Fallback></mc:AlternateContent>'
               '</w:drawing><w:t>fix</w:t></w:r></w:p>')
    text, _ = corpus._docx_text(root)
    assert tokens(text) == ['prefix', 'box', 'words']


def test_special_hyphens_are_preserved():
    text, _ = corpus._docx_text(xml('<w:p><w:r><w:t>a</w:t><w:noBreakHyphen/>'
                                   '<w:t>b</w:t><w:softHyphen/><w:t>c</w:t></w:r></w:p>'))
    assert text.strip() == 'a\u2011b\u00adc'


def test_worker_compares_body_and_all_textboxes_only(tmp_path, monkeypatch):
    import legacy_office_parser
    doc = Document(format='doc', blocks=[Paragraph('alphabet')],
                   textboxes='mainbox headerbox footerbox', headers_footers='excluded',
                   footnotes='excludednote', endnotes='excludedend')
    monkeypatch.setattr(legacy_office_parser, 'parse', lambda source: doc)
    reference = tmp_path / 'synthetic.docx'
    with zipfile.ZipFile(reference, 'w') as z:
        z.writestr('word/document.xml', ET.tostring(xml(
            '<w:p><w:r><w:t>alpha</w:t><w:t>bet</w:t><w:drawing>'
            '<w:txbxContent>' + paragraph('mainbox') + '</w:txbxContent>'
            '</w:drawing></w:r></w:p>')))
        for kind in ('header', 'footer'):
            z.writestr('word/' + kind + '1.xml', ET.tostring(xml(
                paragraph('excluded reference header text') +
                '<w:p><w:r><w:drawing><w:txbxContent>' + paragraph(kind + 'box') +
                '</w:txbxContent></w:drawing></w:r></w:p>')))
        z.writestr('word/footnotes.xml', ET.tostring(xml(paragraph('excluded note'))))
    result = corpus._worker(tmp_path / 'unused.doc', reference)
    assert result['reference_words'] == 4
    assert result['reference_word_recall'] == 1
    assert result['reference_word_precision'] == 1
    assert result['reference_tables'] == 0


def test_spreadsheet_reference_does_not_claim_formatted_word_fidelity(tmp_path, monkeypatch):
    import legacy_office_parser
    from legacy_office_parser import Sheet, SpreadsheetCell
    monkeypatch.setattr(legacy_office_parser, 'parse', lambda source: Document(
        format='xls', sheets=[Sheet('S', cells=[SpreadsheetCell(1, 1, 0, 'number', '0')])]))
    reference = tmp_path / 'reference.xlsx'
    with zipfile.ZipFile(reference, 'w') as z:
        z.writestr('xl/worksheets/sheet1.xml',
                   '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   '<sheetData><row><c r="A1"><v>0</v></c><c r="B1" s="1"/>'
                   '</row></sheetData></worksheet>')
    result = corpus._worker(tmp_path / 'unused.xls', reference)
    assert result['reference_cells'] == result['cells'] == 1
    assert result['reference_sheets'] == result['sheets'] == 1
    assert 'reference_word_recall' not in result


def test_presentation_reference_joins_formatting_runs(tmp_path, monkeypatch):
    import legacy_office_parser
    from legacy_office_parser import Slide
    monkeypatch.setattr(legacy_office_parser, 'parse', lambda source: Document(
        format='odp', slides=[Slide(1, text='alphabet')]))
    reference = tmp_path / 'reference.pptx'
    with zipfile.ZipFile(reference, 'w') as z:
        z.writestr('ppt/presentation.xml',
                   '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                   '<p:sldIdLst><p:sldId id="256" r:id="r1"/></p:sldIdLst></p:presentation>')
        z.writestr('ppt/_rels/presentation.xml.rels',
                   '<Relationships><Relationship Id="r1" Type="x/slide" '
                   'Target="slides/slide1.xml"/></Relationships>')
        z.writestr('ppt/slides/slide1.xml',
                   '<a:p xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                   '<a:r><a:t>alpha</a:t></a:r><a:r><a:t>bet</a:t></a:r></a:p>')
    result = corpus._worker(tmp_path / 'unused.odp', reference)
    assert result['reference_word_recall'] == result['reference_word_precision'] == 1


def test_reference_collapsed_cell_boundaries_are_distinguished_from_lost_characters(tmp_path, monkeypatch):
    import legacy_office_parser
    from legacy_office_parser import Table, Cell
    monkeypatch.setattr(legacy_office_parser, 'parse', lambda source: Document(
        format='doc', blocks=[Table([[Cell('one'), Cell('two')], [Cell('three'), Cell('four')]])]))
    reference = tmp_path / 'reference.docx'
    with zipfile.ZipFile(reference, 'w') as z:
        z.writestr('word/document.xml', ET.tostring(xml(paragraph('onetwothreefour'))))
    result = corpus._worker(tmp_path / 'unused.doc', reference)
    assert result['reference_word_recall'] == 0
    assert result['reference_nonspace_equal'] is True
    assert result['tables'] == 1 and result['reference_tables'] == 0


def test_presentation_order_notes_and_visibility_are_compared(tmp_path, monkeypatch):
    import legacy_office_parser
    from legacy_office_parser import Slide
    doc = Document(format='ppt', slides=[Slide(1, text='second', notes='speaker', hidden=True),
                                         Slide(2, text='first')])
    monkeypatch.setattr(legacy_office_parser, 'parse', lambda source: doc)
    reference = tmp_path / 'reference.pptx'
    pns = 'http://schemas.openxmlformats.org/presentationml/2006/main'
    ans = 'http://schemas.openxmlformats.org/drawingml/2006/main'
    rns = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    with zipfile.ZipFile(reference, 'w') as z:
        z.writestr('ppt/presentation.xml',
                   f'<p:presentation xmlns:p="{pns}" xmlns:r="{rns}"><p:sldIdLst>'
                   '<p:sldId r:id="r2"/><p:sldId r:id="r1"/></p:sldIdLst></p:presentation>')
        z.writestr('ppt/_rels/presentation.xml.rels',
                   '<Relationships><Relationship Id="r1" Type="x/slide" Target="slides/slide1.xml"/>'
                   '<Relationship Id="r2" Type="x/slide" Target="slides/slide2.xml"/></Relationships>')
        for number, text in ((1, 'first'), (2, 'second')):
            z.writestr(f'ppt/slides/slide{number}.xml',
                       f'<p:sld xmlns:p="{pns}" xmlns:a="{ans}" show="{number == 1 and 1 or 0}">'
                       f'<a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:sld>')
        z.writestr('ppt/slides/_rels/slide2.xml.rels',
                   '<Relationships><Relationship Id="n" Type="x/notesSlide" '
                   'Target="../notesSlides/notesSlide9.xml"/></Relationships>')
        z.writestr('ppt/notesSlides/notesSlide9.xml',
                   f'<p:notes xmlns:p="{pns}" xmlns:a="{ans}">'
                   '<p:sp><p:nvSpPr><p:nvPr><p:ph type="body"/></p:nvPr></p:nvSpPr>'
                   '<a:p><a:r><a:t>speaker</a:t></a:r></a:p></p:sp>'
                   '<p:sp><p:nvSpPr><p:nvPr><p:ph type="sldNum"/></p:nvPr></p:nvSpPr>'
                   '<a:p><a:r><a:t>2</a:t></a:r></a:p></p:sp></p:notes>')
    result = corpus._worker(tmp_path / 'unused.ppt', reference)
    assert result['reference_presentation_equal'] is True
    doc.slides[0].notes = 'speaker!'
    result = corpus._worker(tmp_path / 'unused.ppt', reference)
    assert result['reference_slide_checks'][0]['notes_words_equal'] is True
    assert result['reference_presentation_equal'] is False
    doc.slides[0].notes = ''
    result = corpus._worker(tmp_path / 'unused.ppt', reference)
    assert result['reference_word_recall'] == 1
    assert result['reference_presentation_equal'] is False
    assert result['reference_slide_checks'][0]['notes_words_equal'] is False
    doc.slides.reverse()
    result = corpus._worker(tmp_path / 'unused.ppt', reference)
    assert result['reference_word_recall'] == 1
    assert result['reference_ordered_words_equal'] is False
