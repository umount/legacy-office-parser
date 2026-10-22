"""Real ODT auxiliary tables with expectations authored independently of parser."""
from pathlib import Path

from legacy_office_parser import parse_odt
from legacy_office_parser.models import Cell, Note, NoteBodyRange, Paragraph, Table


def test_real_odt_auxiliary_tables():
    source = Path(__file__).parent / 'fixtures/odf_story_tables/auxiliary_tables.odt'
    doc = parse_odt(source)
    assert doc.blocks == [Paragraph('Body')]
    assert doc.story_blocks == {
        'headers_footers': [Paragraph('Before'), Table([[Cell('A'), Cell('B')]]),
                            Paragraph('After')],
        'textboxes': [Table([[Cell('C'), Cell('D')]])],
        # One note: frame-only paragraph followed by two source empty paragraphs.
        'footnotes': [Paragraph(''), Paragraph(''), Paragraph('')],
    }
    assert doc.notes == [Note('footnote', 1, NoteBodyRange('footnotes', 0, 3))]
    assert doc.headers_footers == 'Before\n\nA\tB\n\nAfter'
    assert doc.textboxes == 'C\tD' and not doc.footnotes
    assert doc.text == 'Body\n\nBefore\n\nA\tB\n\nAfter\n\nC\tD'
