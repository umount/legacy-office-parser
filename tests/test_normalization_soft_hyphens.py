"""Synthetic soft-hyphen inputs; raw source and metadata remain unchanged."""
import pytest

from legacy_office_parser import Document, Limits, Paragraph, normalize_text, parse_odt, parse_rtf
from legacy_office_parser.errors import LimitExceededError
from legacy_office_parser.models import (
    Cell, Comment, CommentBodyRange, Note, NoteBodyRange, Sheet, Slide,
    SlideComment, SpreadsheetCell, Table,
)
from test_doc import fixture, parse as parse_doc_streams
from test_odf import package


@pytest.mark.parametrize('compressed', [True, False])
def test_doc_optional_hyphen_maps_to_shy_before_explicit_normalization(monkeypatch, compressed):
    raw = parse_doc_streams(monkeypatch, fixture([('co\x1foperate\r', compressed)]))
    assert raw.text == 'co\u00adoperate'
    before = raw.to_dict()
    assert normalize_text(raw).text == 'cooperate'
    assert normalize_text(raw, drop_soft_hyphens=False).text == raw.text
    assert raw.to_dict() == before


@pytest.mark.parametrize('payload', [br'{\rtf1 co\-operate}', br'{\rtf1 co\u173?operate}'])
def test_rtf_raw_and_normalized_soft_hyphen(payload):
    raw = parse_rtf(payload)
    assert raw.text == 'co\u00adoperate'
    before = raw.to_dict()
    assert normalize_text(raw).text == 'cooperate'
    assert normalize_text(raw, drop_soft_hyphens=False).to_dict() == before
    assert raw.to_dict() == before


def test_odt_literal_soft_hyphen():
    raw = parse_odt(package('<text:p>co\u00adoperate</text:p>'))
    assert raw.text == 'co\u00adoperate'
    before = raw.to_dict()
    assert normalize_text(raw).text == 'cooperate'
    assert normalize_text(raw, drop_soft_hyphens=False).to_dict() == before
    assert raw.to_dict() == before


@pytest.mark.parametrize('value', [None, 0, 1, '', 'true', [], {}, object()])
def test_flag_requires_actual_bool(value):
    with pytest.raises(TypeError, match='drop_soft_hyphens must be bool'):
        normalize_text(Document('rtf'), drop_soft_hyphens=value)


def test_no_general_format_character_or_word_boundary_deletion():
    retained = 'ไทย\u200bภาษา\u200c\u200d\u200e\u200f\u2060\ufeff-\u2010\u2011'
    raw = Document('rtf', blocks=[Paragraph('co\u00adoperate' + retained)])
    assert normalize_text(raw).text == 'cooperate' + retained
    assert normalize_text(raw, drop_soft_hyphens=False).text == raw.text


def test_all_word_projections_and_source_positions():
    text = 'co\u00adoperate'
    cell = Cell(text, blocks=[Paragraph(text, 2)])
    stories = {name: [Paragraph(text)] for name in (
        'footnotes', 'endnotes', 'headers_footers', 'textboxes', 'comment_text')}
    doc = Document('doc', blocks=[Paragraph(text, 1), Table([[cell]])],
                   story_blocks=stories, **{name: text for name in stories})
    doc.notes = [Note('footnote', 1, NoteBodyRange('footnotes', 0, 1), source_cp=3,
                      anchor_path=['blocks', 0], reference_kind='automatic'),
                 Note('endnote', 1, NoteBodyRange('endnotes', 0, 1), source_cp=12)]
    doc.comments = [Comment(1, CommentBodyRange('comment_text', 0, 1),
                            author=text, initials=text, source_cp=8,
                            selection_start=2, selection_end=9, anchor_path=['blocks', 0])]
    before = doc.to_dict()
    clean = normalize_text(doc)
    assert clean.blocks[0].text == clean.blocks[1].rows[0][0].text == 'cooperate'
    assert clean.blocks[0].heading_level == 1
    assert clean.blocks[1].rows[0][0].blocks[0].text == 'cooperate'
    assert clean.blocks[1].rows[0][0].blocks[0].heading_level == 2
    for name in stories:
        assert getattr(clean, name) == clean.story_blocks[name][0].text == 'cooperate'
    assert clean.notes == doc.notes
    assert clean.comments == doc.comments
    assert doc.to_dict() == before
    assert normalize_text(doc, drop_soft_hyphens=False).to_dict() == before
    assert normalize_text(clean).to_dict() == clean.to_dict()
    assert sum('Display text normalized' in w for w in clean.warnings) == 1


@pytest.mark.parametrize('value,kind', [('raw\u00advalue', 'string'), (42, 'number'),
                                      (True, 'boolean'), (None, 'empty')])
def test_sheet_display_only_not_typed_values_or_formulas(value, kind):
    raw = Document('ods', sheets=[Sheet('Na\u00adme', cells=[
        SpreadsheetCell(1, 1, value, kind, 'dis\u00adplay', 'of:="x\u00ady"', True)],
        drawings=['dra\u00adwing'])])
    before = raw.to_dict()
    clean = normalize_text(raw)
    sheet = clean.sheets[0]
    assert sheet.name == 'Name' and sheet.drawings == ['drawing']
    assert sheet.cells[0].text == 'display'
    assert sheet.cells[0].value == value and type(sheet.cells[0].value) is type(value)
    assert sheet.cells[0].formula == 'of:="x\u00ady"'
    assert clean.text == 'Name\nA1\tdisplay\ndrawing'
    assert raw.to_dict() == before


def test_slide_fields_and_comments_not_authorship():
    text = 'co\u00adoperate'
    raw = Document('ppt', slides=[Slide(1, text, text, text, True,
                                       comments=[SlideComment(text, text, text)])])
    before = raw.to_dict()
    clean = normalize_text(raw)
    slide = clean.slides[0]
    assert (slide.title, slide.text, slide.notes) == ('cooperate',) * 3
    assert slide.hidden is True
    assert slide.comments[0].text == 'cooperate'
    assert slide.comments[0].author == slide.comments[0].initials == text
    assert raw.to_dict() == before


def test_empty_atom_retains_story_block_ranges_and_separators():
    raw = Document('odt', footnotes='\u00ad\n\nnext',
                   story_blocks={'footnotes': [Paragraph('\u00ad'), Paragraph('next')]},
                   notes=[Note('footnote', 1, NoteBodyRange('footnotes', 0, 2))])
    clean = normalize_text(raw)
    assert clean.footnotes == '\n\nnext'
    assert [p.text for p in clean.story_blocks['footnotes']] == ['', 'next']
    assert clean.notes == raw.notes
    assert normalize_text(clean).to_dict() == clean.to_dict()


def test_pre_normalization_budget_cannot_be_bypassed():
    raw = Document('rtf', blocks=[Paragraph('\u00ad' * 10)])
    with pytest.raises(LimitExceededError):
        normalize_text(raw, limits=Limits(max_text_chars=9))
    assert normalize_text(raw, limits=Limits(max_text_chars=10)).text == ''


def test_false_preserves_shy_but_other_cleanup_and_nfc_still_apply():
    raw = Document('rtf', blocks=[Paragraph('e\u0301\u00ad\x00\r\n')])
    assert normalize_text(raw, drop_soft_hyphens=False, unicode_form='NFC').text == 'é\u00ad\n'
    assert normalize_text(raw, unicode_form='NFC').text == 'é\n'


@pytest.mark.parametrize('option', ['--normalize-text', '--nfc'])
def test_cli_normalization_uses_default_soft_hyphen_removal(tmp_path, capsys, option):
    from legacy_office_parser.cli import main
    path = tmp_path / 'synthetic.rtf'
    path.write_bytes(br'{\rtf1 co\-operate\u8203?word}')
    assert main([str(path)]) == 0
    assert capsys.readouterr().out == 'co\u00adoperate\u200bword\n'
    assert main([str(path), option, '--strict']) == 3
    output = capsys.readouterr()
    assert output.out == 'cooperate\u200bword\n'
    assert output.err.count('Display text normalized') == 1
