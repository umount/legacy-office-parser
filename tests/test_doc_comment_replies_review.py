"""Independent public reply-tree and retained-ownership review cases."""
from dataclasses import replace
import struct

import pytest

from legacy_office_parser import InvalidDocumentError, LimitExceededError, Limits
from legacy_office_parser.api import _validate_result
from legacy_office_parser.models import Comment, CommentBodyRange, Document, Paragraph
from test_doc import parse
from test_doc_comments import build, decoded, base_parts


def document(relationships, ordinals=None):
    ordinals = ordinals or list(range(1, len(relationships) + 1))
    return Document('doc', comments=[
        Comment(ordinal, CommentBodyRange('comment_text', i, i + 1),
                reply_depth=depth, parent_ordinal=parent)
        for i, (ordinal, (depth, parent)) in enumerate(zip(ordinals, relationships))],
        story_blocks={'comment_text': [Paragraph('body') for _ in relationships]},
        comment_text='\n'.join('body' for _ in relationships))


@pytest.mark.parametrize('relationships', [
    [(0, None), (0, None), (1, 1)],
    [(0, None), (1, 1), (1, 1), (2, 2)],
])
def test_public_validator_rejects_return_to_closed_preorder_branch(relationships):
    with pytest.raises(InvalidDocumentError):
        _validate_result(document(relationships), Limits())


@pytest.mark.parametrize('relationships,ordinals', [
    ([(0, None), (1, 1), (2, 2), (1, 1), (0, None)], None),
    ([(0, None), (1, 2)], [2, 9]),
    ([(None, None), (0, None), (1, 2)], None),
    ([(0, None), (None, None), (1, 1)], None),
])
def test_public_valid_forest_and_source_ordinal_gaps(relationships, ordinals):
    doc = document(relationships, ordinals)
    _validate_result(doc, Limits())
    assert doc.text.count('body') == len(relationships)


def test_unknown_root_reply_json_states():
    doc = document([(None, None), (0, None), (1, 2)])
    values = doc.to_dict()['comments']
    assert 'reply_depth' not in values[0] and 'parent_ordinal' not in values[0]
    assert values[1]['reply_depth'] == 0 and values[1]['parent_ordinal'] is None
    assert values[2]['reply_depth'] == 1 and values[2]['parent_ordinal'] == 2


@pytest.mark.parametrize('depth,parent', [(None, 1), (True, None), (1, True),
                                         (0, 1), (1, 99), (-1, None)])
def test_public_invalid_relationship_states(depth, parent):
    with pytest.raises(InvalidDocumentError):
        _validate_result(document([(0, None), (depth, parent)]), Limits())


def test_source_extra_budget_precedes_decoding_malformed_tree():
    parts = base_parts()
    # Existing PLC/author charges total eleven; extras require two more.
    # Invalid depth must not be visited if the aggregate callback rejects extras.
    parts[112] = b'\0' * 6 + struct.pack('<IiI', 99, 0, 0) + b'\0' * 18
    charges = []

    def record(count):
        charges.append(count)
        if len(charges) == 4:
            raise LimitExceededError('independent budget guard')

    with pytest.raises(LimitExceededError, match='independent budget guard'):
        decoded(parts, record=record)


def test_omitted_parent_clears_descendants_without_renumbering(monkeypatch):
    import legacy_office_parser.doc as module
    original_decode = module.decode_comments
    original_props = module._Doc._character_props

    def decode(*args, **kwargs):
        sources = original_decode(*args, **kwargs)
        return [replace(source, reply_depth=d, parent_ordinal=p)
                for source, (d, p) in zip(sources, [(0, None), (1, 1), (2, 2), (0, None)])]

    def props(self, cp, *args, **kwargs):
        result = original_props(self, cp, *args, **kwargs)
        return {**result, 'special': None} if cp == 0 else result

    monkeypatch.setattr(module, 'decode_comments', decode)
    monkeypatch.setattr(module._Doc, '_character_props', props)
    doc = parse(monkeypatch, build('\x05\x05\x05\x05\r', ('\x05A\r', '\x05B\r', '\x05C\r', '\x05D\r')))
    assert [c.ordinal for c in doc.comments] == [2, 3, 4]
    assert [(c.reply_depth, c.parent_ordinal) for c in doc.comments] == [(None, None), (None, None), (0, None)]
    assert doc.comment_text == 'B\nC\nD'
    assert all(c.anchor_path == ['blocks', 0] for c in doc.comments)
    assert any('ancestry' in w for w in doc.warnings)
    _validate_result(doc, Limits())
