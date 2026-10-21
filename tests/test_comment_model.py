"""Document comments share bodies without losing reference identity or budgets."""
from dataclasses import replace

import pytest

from legacy_office_parser import Comment, CommentBodyRange, Document, Limits, Paragraph
from legacy_office_parser.api import _validate_result
from legacy_office_parser.errors import InvalidDocumentError, LimitExceededError
from legacy_office_parser.models import Cell, Note, NoteBodyRange, Table


def document():
    return Document(format='doc', blocks=[Paragraph('anchor')],
                    story_blocks={'comment_text': [Paragraph('text')]}, comment_text='text',
                    comments=[Comment(1, CommentBodyRange('comment_text', 0, 1),
                                      author='Ada', initials='A', source_cp=2,
                                      selection_start=0, selection_end=2,
                                      anchor_path=['blocks', 0], visibility=[])])


def test_projection_and_public_exports():
    doc = _validate_result(document(), Limits())
    assert doc.text == 'anchor\n\ntext'
    data = doc.to_dict()
    comment = data['comments'][0]
    assert comment['body'] == {'story': 'comment_text', 'block_start': 0, 'block_end': 1}
    assert comment['author'] == 'Ada' and comment['source_cp'] == 2
    assert comment['anchor_path'] == ['blocks', 0]
    assert data['story_blocks']['comment_text'] == [{'text': 'text', 'kind': 'paragraph'}]
    assert 'comments' not in Document('doc').to_dict()
    assert 'comment_text' not in Document('doc').to_dict()


def test_empty_body_and_distinct_equal_comment_bodies():
    doc = document()
    doc.story_blocks['comment_text'] += [Paragraph('text'), Paragraph('')]
    doc.comment_text = 'text\n\ntext'
    doc.comments += [Comment(2, CommentBodyRange('comment_text', 1, 2), author='Ben', source_cp=3),
                     Comment(3, CommentBodyRange('comment_text', 2, 3), source_cp=4)]
    assert _validate_result(doc, Limits()).text == 'anchor\n\ntext\n\ntext'
    assert [c['ordinal'] for c in doc.to_dict()['comments']] == [1, 2, 3]


@pytest.mark.parametrize('field,value', [
    ('ordinal', 0), ('ordinal', True), ('ordinal', -1),
    ('author', 5), ('initials', []), ('source_cp', True), ('source_cp', -1),
    ('source_cp', 0x7FFFFFFF), ('selection_start', None), ('selection_end', None),
    ('selection_start', 3), ('selection_end', True), ('selection_end', 0x7FFFFFFF),
    ('anchor_path', []), ('anchor_path', ['blocks', True]), ('anchor_path', ['blocks', 1]),
    ('anchor_path', ['blocks', 0, 'blocks', 0]), ('anchor_path', ('blocks', 0)),
    ('visibility', ['hidden', 'hidden']), ('visibility', ['visible']),
    ('visibility', 'hidden'), ('body', CommentBodyRange('footnotes', 0, 1)),
    ('body', CommentBodyRange('comment_text', 1, 1)),
    ('body', CommentBodyRange('comment_text', True, 1)),
    ('body', CommentBodyRange('comment_text', 0, 2)),
])
def test_invalid_comment_metadata(field, value):
    doc = document()
    setattr(doc.comments[0], field, value)
    with pytest.raises(InvalidDocumentError):
        _validate_result(doc, Limits())


def test_source_required_for_anchor_and_selection():
    doc = document()
    doc.comments[0].source_cp = None
    with pytest.raises(InvalidDocumentError):
        _validate_result(doc, Limits())
    doc.comments[0].selection_start = doc.comments[0].selection_end = None
    with pytest.raises(InvalidDocumentError):
        _validate_result(doc, Limits())
    doc.comments[0].anchor_path = None
    assert _validate_result(doc, Limits()) is doc


@pytest.mark.parametrize('change', ['ordinal', 'cp', 'overlap'])
def test_order_and_body_ownership(change):
    doc = document()
    doc.story_blocks['comment_text'].append(Paragraph('second'))
    item = Comment(2, CommentBodyRange('comment_text', 1, 2), source_cp=3)
    if change == 'ordinal':
        item.ordinal = 1
    elif change == 'cp':
        item.source_cp = 2
    else:
        item.body.block_start = 0
    doc.comments.append(item)
    with pytest.raises(InvalidDocumentError):
        _validate_result(doc, Limits())


def test_nested_cell_path_and_omitted_cell_rejection():
    doc = document()
    cell = Cell('anchor')
    doc.blocks = [Table([[cell]])]
    doc.comments[0].anchor_path = ['blocks', 0, 'rows', 0, 0]
    assert _validate_result(doc, Limits()) is doc
    cell.text, cell.omitted = '', True
    with pytest.raises(InvalidDocumentError):
        _validate_result(doc, Limits())


def test_metadata_budget_combines_notes_and_comments():
    doc = document()
    doc.story_blocks['footnotes'] = [Paragraph('note')]
    doc.notes = [Note('footnote', 1, NoteBodyRange('footnotes', 0, 1), source_cp=1,
                      anchor_path=['blocks', 0])]
    assert _validate_result(doc, replace(Limits(), max_records=6)) is doc
    with pytest.raises(LimitExceededError):
        _validate_result(doc, replace(Limits(), max_records=5))
    # A later unlinked entry must still charge its record after a previous path.
    doc.notes = []
    doc.story_blocks['comment_text'].append(Paragraph(''))
    doc.comments.append(Comment(2, CommentBodyRange('comment_text', 1, 2)))
    with pytest.raises(LimitExceededError):
        _validate_result(doc, replace(Limits(), max_records=3))


def test_author_and_projection_text_budget():
    doc = document()
    # Main text + shared body + projection + author + initials.
    assert _validate_result(doc, replace(Limits(), max_text_chars=18)) is doc
    with pytest.raises(LimitExceededError):
        _validate_result(doc, replace(Limits(), max_text_chars=17))


def test_source_and_selection_limits():
    for field in ('source_cp', 'selection_end'):
        doc = document()
        setattr(doc.comments[0], field, 100)
        with pytest.raises(LimitExceededError):
            _validate_result(doc, replace(Limits(), max_text_chars=100))


def test_reject_wrong_document_and_comment_types():
    doc = document()
    doc.format = 'ppt'
    with pytest.raises(InvalidDocumentError):
        _validate_result(doc, Limits())
    doc = document()
    doc.comments = ['text']
    with pytest.raises(InvalidDocumentError):
        _validate_result(doc, Limits())
