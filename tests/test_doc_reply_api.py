"""Public extraction preserves explicit reply links without repeating bodies."""
import json
from pathlib import Path

from legacy_office_parser import parse, parse_doc
from legacy_office_parser.cli import main

FIXTURE = Path(__file__).parent / 'fixtures/doc_comment_replies/authored.doc'


def test_reply_links_public_api_and_cli(capsys):
    doc = parse(FIXTURE)
    assert doc.to_dict() == parse_doc(FIXTURE).to_dict()
    expected = [(1, 0, None), (2, 1, 1), (3, 2, 2)]
    assert [(c.ordinal, c.reply_depth, c.parent_ordinal) for c in doc.comments] == expected
    assert doc.comment_text.count('Shared comment.') == 2
    assert doc.text.count('Shared comment.') == 2
    assert doc.text.count('Second paragraph.') == 1
    assert main([str(FIXTURE), '--json']) == 0
    result = json.loads(capsys.readouterr().out)
    assert [(c['ordinal'], c['reply_depth'], c['parent_ordinal'])
            for c in result['comments']] == expected
