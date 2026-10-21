"""Public DOC results keep source coordinates distinct from normalized text."""
import json
from pathlib import Path

from legacy_office_parser import parse, parse_doc
from legacy_office_parser.cli import main

FIXTURE = Path(__file__).parent / 'fixtures/doc_comment_selections/authored.doc'


def test_cross_paragraph_comments_api_and_cli(capsys):
    doc = parse(FIXTURE)
    assert doc.to_dict() == parse_doc(FIXTURE).to_dict()
    assert [(c.selection_start, c.selection_end, c.source_cp) for c in doc.comments] == [
        (8, 22, 22), (50, 61, 61)]
    assert [c.author for c in doc.comments] == ['Ada Range', 'Ben Range']
    for body in ('Across empty paragraph.', 'Across ordinary paragraphs.'):
        assert doc.comment_text.count(body) == 1
        assert doc.text.count(body) == 1
    assert main([str(FIXTURE), '--json']) == 0
    output = json.loads(capsys.readouterr().out)
    assert [(c['selection_start'], c['selection_end']) for c in output['comments']] == [
        (8, 22), (50, 61)]
    assert all(c['anchor_path'] for c in output['comments'])
