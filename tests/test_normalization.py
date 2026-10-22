"""Normalization is explicit and preserves source data and structural identity."""
import pytest

from legacy_office_parser import Document, Limits, Paragraph, parse_rtf
from legacy_office_parser.errors import LimitExceededError
from legacy_office_parser.models import Cell, Sheet, Slide, SlideComment, SpreadsheetCell, Table
from legacy_office_parser.normalization import normalize_text


def test_control_cleanup_is_explicit_and_does_not_mutate_source():
    doc = parse_rtf(b'{\\rtf1  A\x00\x0bB\\u13?C\x1bD\x7f  }')
    original = doc.to_dict()
    clean = normalize_text(doc)
    assert clean.text == ' A\nB\nCD  '
    assert doc.to_dict() == original
    assert clean is not doc and clean.blocks[0] is not doc.blocks[0]
    assert len(clean.warnings) == len(doc.warnings) + 1
    assert normalize_text(clean).to_dict() == clean.to_dict()


def test_nfc_is_optional_and_whitespace_is_preserved():
    doc = Document('rtf', blocks=[Paragraph('  e\u0301\t\r\nX\rY\vZ\fQ\x85R  ', 2)])
    assert normalize_text(doc).blocks[0].text.startswith('  e\u0301\t\n')
    clean = normalize_text(doc, unicode_form='NFC')
    assert clean.blocks[0].text == '  é\t\nX\nY\nZ\nQ\nR  '
    assert clean.blocks[0].heading_level == 2


def test_nested_blocks_and_projection_are_both_cleaned():
    p = Paragraph('A\x00B', 1)
    doc = Document('odt', blocks=[Table([[Cell('A\x00B', blocks=[p])]])],
                   footnotes='C\x1bD', story_blocks={'footnotes': [Paragraph('C\x1bD')]})
    clean = normalize_text(doc)
    assert clean.blocks[0].rows[0][0].text == 'AB'
    assert clean.blocks[0].rows[0][0].blocks[0].text == 'AB'
    assert clean.footnotes == clean.story_blocks['footnotes'][0].text == 'CD'
    assert clean.text == 'AB\n\nCD'


def test_spreadsheet_raw_values_and_formulas_stay_exact():
    cell = SpreadsheetCell(1, 1, 'raw\x00value', 'string', 'shown\x00value', 'of:=A1\r', True)
    doc = Document('ods', sheets=[Sheet('N\x00ame', cells=[cell], drawings=['D\x1braw'])])
    clean = normalize_text(doc)
    c = clean.sheets[0].cells[0]
    assert (c.value, c.formula) == (cell.value, cell.formula)
    assert c.text == 'shownvalue'
    assert clean.text == 'Name\nA1\tshownvalue\nDraw'
    assert doc.sheets[0].drawings == ['D\x1braw']


def test_slide_content_but_not_authorship_is_cleaned():
    doc = Document('ppt', slides=[Slide(1, 'T\x00', 'B\r', 'N\v', comments=[
        SlideComment('C\x1b', 'Author\x00', 'A')])])
    clean = normalize_text(doc)
    assert clean.slides[0].title == 'T'
    assert clean.slides[0].comments[0].text == 'C'
    assert clean.slides[0].comments[0].author == 'Author\x00'


def test_surrogates_replaced_but_bidi_and_nbsp_not_silently_removed():
    doc = Document('rtf', blocks=[Paragraph('\ud800\u200f\xa0')])
    assert normalize_text(doc).text == '\ufffd\u200f\xa0'


def test_limits_are_not_bypassed_by_removing_controls():
    with pytest.raises(LimitExceededError):
        normalize_text(Document('rtf', blocks=[Paragraph('\x00' * 10)]),
                       limits=Limits(max_text_chars=9))


def test_nfc_growth_is_budgeted():
    # U+0344 canonically decomposes even in NFC, increasing codepoint count.
    with pytest.raises(LimitExceededError):
        normalize_text(Document('rtf', blocks=[Paragraph('\u0344')]),
                       unicode_form='NFC', limits=Limits(max_text_chars=1))


@pytest.mark.parametrize('form', ['NFKC', 'NFD', '', False])
def test_invalid_normalization_options(form):
    with pytest.raises(ValueError):
        normalize_text(Document('rtf'), unicode_form=form)


def test_invalid_types():
    with pytest.raises(TypeError):
        normalize_text({})
    with pytest.raises(TypeError):
        normalize_text(Document('rtf'), limits=False)


def test_cli_normalization_is_opt_in(tmp_path, capsys):
    from legacy_office_parser.cli import main
    path = tmp_path / 'test.rtf'
    path.write_bytes(b'{\\rtf1 A\x00B}')
    assert main([str(path)]) == 0
    assert capsys.readouterr().out == 'A\x00B\n'
    assert main([str(path), '--normalize-text', '--strict']) == 3
    output = capsys.readouterr()
    assert output.out == 'AB\n' and 'normalized' in output.err


def test_structured_separator_is_not_absorbed_as_crlf():
    doc = parse_rtf(br"{\rtf1\trowd\cellx100\intbl\outlinelevel0 A\'0d\par B\cell\row}")
    clean = normalize_text(doc)
    cell = clean.blocks[0].rows[0][0]
    assert cell.text == 'A\n\nB'
    assert cell.text == '\n'.join(p.text for p in cell.blocks)
    assert normalize_text(clean).to_dict() == clean.to_dict()


def test_paragraph_subclass_is_normalized():
    class StyledParagraph(Paragraph):
        pass
    assert normalize_text(Document('rtf', blocks=[StyledParagraph('A\0B')])).text == 'AB'
