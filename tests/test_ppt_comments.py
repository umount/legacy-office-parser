"""Active typed PPT10 comments, independent wire fixtures and public model checks."""
from dataclasses import replace
from struct import pack

import pytest

from legacy_office_parser import Document, Slide, SlideComment
from legacy_office_parser.api import _validate_result
from legacy_office_parser.errors import InvalidDocumentError, LimitExceededError
from legacy_office_parser.limits import Limits
from test_ppt import File, atom, container, document, note, persist, run, slide, text
from test_ppt_extensions import extension, metadata


def comment(value='Review', author='Author', initials='AU', index=0, extra=b''):
    strings = b''.join(atom(4026, v.encode('utf-16le'), instance=i)
                       for i, v in ((0, author), (1, value), (2, initials)) if v is not None)
    return container(12000, strings + atom(12001, pack('<i', index) + bytes(24)) + extra)


def fixture(payload, body='Body', notes=None):
    return File().edit({1: document(persist(2, 200) + text(body), persist(3, 300) if notes else b''),
                        2: slide(extension(payload), notes=300 if notes else 0),
                        **({3: note(200, notes)} if notes else {})})


def test_source_order_owning_slide_and_notes_projection(monkeypatch):
    f = fixture(comment('one') + comment('Body', index=1), notes='Speaker notes')
    result = run(monkeypatch, f)
    own, = result.slides
    assert (own.text, own.notes) == ('Body', 'Speaker notes')
    assert own.comments == [SlideComment('one', 'Author', 'AU'), SlideComment('Body', 'Author', 'AU')]
    assert result.text == 'Body\nSpeaker notes\none\nBody'
    assert result.warnings == []


@pytest.mark.parametrize('value,author,initials', [(None, None, None), ('', '', ''),
                                                ('Text', None, None), (None, 'Author', 'A')])
def test_optional_strings_remain_separate(monkeypatch, value, author, initials):
    doc = run(monkeypatch, fixture(comment(value, author, initials)))
    assert doc.slides[0].comments == [SlideComment(value or '', author or '', initials or '')]
    assert doc.text == 'Body' + ('\n' + value if value else '')


def test_unicode_and_linebreak_normalization(monkeypatch):
    doc = run(monkeypatch, fixture(comment('  Привет\t世界 😀\r\nnext  ')))
    assert doc.slides[0].comments[0].text == 'Привет\t世界 😀\nnext'


def test_live_references_only_and_no_cross_slide_dedup(monkeypatch):
    f = fixture(comment('old'))
    f.edit({1: document(persist(2, 200) + text('A') + persist(4, 400) + text('B')),
            2: slide(extension(comment('same'))), 4: slide(extension(comment('same'))),
            99: slide(extension(comment('unreferenced')))})
    f.put(slide(extension(comment('appended stale'))))
    doc = run(monkeypatch, f)
    assert [s.comments for s in doc.slides] == [[SlideComment('same', 'Author', 'AU')]] * 2
    assert doc.text == 'A\nsame\n\nB\nsame'


def test_unknown_siblings_warn_without_losing_known_comments(monkeypatch):
    doc = run(monkeypatch, fixture(comment('known') + atom(0x7777, b'opaque') + metadata()))
    assert doc.slides[0].comments[0].text == 'known'
    assert any('extension-only' in w for w in doc.warnings)


def test_metadata_siblings_do_not_warn(monkeypatch):
    assert run(monkeypatch, fixture(comment() + metadata())).warnings == []


@pytest.mark.parametrize('payload', [
    extension(comment(), name='___PPT9'), extension(comment(), name='___PPT12'),
    extension(container(0x7777, comment())),
])
def test_other_names_and_nested_unknown_content_not_scanned(monkeypatch, payload):
    f = File().edit({1: document(persist(2, 200)), 2: slide(payload)})
    doc = run(monkeypatch, f)
    assert doc.slides[0].comments == []
    assert doc.warnings


def test_notes_comments_not_promoted_to_slide(monkeypatch):
    f = fixture(comment('slide'), notes='notes')
    f.edit({3: container(1008, atom(1009, pack('<IHH', 200, 0, 0), 1) + extension(comment('notes-only')))})
    doc = run(monkeypatch, f)
    assert [c.text for c in doc.slides[0].comments] == ['slide']
    assert 'notes-only' not in doc.text and doc.warnings


@pytest.mark.parametrize('bad', [
    container(12000), container(12000, atom(4026, b'x\0', instance=1)),
    atom(12000, atom(12001, bytes(28))),
    container(12000, atom(12001, bytes(28)), instance=1),
    container(12000, atom(12001, bytes(27))),
    container(12000, atom(12001, bytes(29))),
    container(12000, atom(12001, bytes(28), version=1)),
    container(12000, atom(12001, bytes(28), instance=1)),
    comment(index=-1), comment(extra=atom(12001, bytes(28))),
    comment(extra=atom(4026, b'x\0', instance=1)),
    comment(extra=atom(4026, b'x\0', instance=3)),
    container(12000, atom(4026, b'x', instance=1) + atom(12001, bytes(28))),
    container(12000, atom(4026, b'\0\xd8', instance=1) + atom(12001, bytes(28))),
    container(12000, atom(4026, b'x\0', version=1, instance=1) + atom(12001, bytes(28))),
    comment('x' * 32001), comment(author='x' * 53), comment(initials='x' * 53),
    comment('a\0b'), comment(author='a\nb'),
])
def test_malformed_typed_comments_fail_closed(monkeypatch, bad):
    with pytest.raises(InvalidDocumentError):
        run(monkeypatch, fixture(bad))


def test_exact_spec_string_maxima(monkeypatch):
    doc = run(monkeypatch, fixture(comment('x' * 32000, 'a' * 52, 'i' * 52)))
    assert len(doc.slides[0].comments[0].text) == 32000


def test_duplicate_ppt10_with_comments_fails(monkeypatch):
    f = File().edit({1: document(persist(2, 200)),
                     2: slide(extension(comment()) + extension(comment()))})
    with pytest.raises(InvalidDocumentError, match='duplicate PPT10'):
        run(monkeypatch, f)


def test_author_initials_and_text_share_decode_budget(monkeypatch):
    f = fixture(comment('xxx', 'aa', 'i'), body='')
    with pytest.raises(LimitExceededError, match='text limit'):
        run(monkeypatch, f, replace(Limits(), max_text_chars=5))
    assert run(monkeypatch, f, replace(Limits(), max_text_chars=6)).text == 'xxx'


def test_output_separators_checked_before_document_projection(monkeypatch):
    f = fixture(comment('a', '', '') + comment('b', '', ''), body='')
    with pytest.raises(LimitExceededError, match='output text'):
        run(monkeypatch, f, replace(Limits(), max_text_chars=2))
    assert run(monkeypatch, f, replace(Limits(), max_text_chars=3)).text == 'a\nb'


@pytest.mark.parametrize('limit,value', [('max_records', 25), ('max_depth', 5)])
def test_shared_traversal_budgets(monkeypatch, limit, value):
    with pytest.raises(LimitExceededError):
        run(monkeypatch, fixture(comment() * 20), replace(Limits(), **{limit: value}))


def test_public_model_compatibility_and_projection():
    first = Slide(1, 'Title', 'Body', 'Notes', True)
    second = Slide(2)
    first.comments.append(SlideComment('Body', 'Author', 'A'))
    doc = Document('ppt', slides=[first, second])
    assert second.comments == []
    assert doc.text == 'Title\nBody\nNotes\nBody\n\n'
    encoded = doc.to_dict()
    assert encoded['slides'][0]['comments'] == [{'text': 'Body', 'author': 'Author', 'initials': 'A'}]
    assert 'comments' not in encoded['slides'][1]
    assert 'story_blocks' not in encoded and 'notes' not in encoded


@pytest.mark.parametrize('comments,limit', [([SlideComment('x', 'long', 'A')], 5),
                                           ([SlideComment('a'), SlideComment('b')], 2)])
def test_api_defence_in_depth_text_and_projection(comments, limit):
    with pytest.raises(LimitExceededError):
        _validate_result(Document('ppt', slides=[Slide(1, comments=comments)]),
                         replace(Limits(), max_text_chars=limit))


def test_api_defence_in_depth_comment_count_and_types():
    with pytest.raises(LimitExceededError, match='comment record'):
        _validate_result(Document('ppt', slides=[Slide(1, comments=[SlideComment('')] * 3)]),
                         replace(Limits(), max_records=2))
    with pytest.raises(InvalidDocumentError, match='slide comment'):
        _validate_result(Document('ppt', slides=[Slide(1, comments=['bad'])]), Limits())


@pytest.mark.parametrize('role', ['value', 'author', 'initials'])
@pytest.mark.parametrize('codepoint', range(0x7f, 0xa0))
def test_comment_roles_reject_delete_and_c1_before_normalization(monkeypatch, role, codepoint):
    # Leading/trailing U+0085 would otherwise disappear in str.strip().
    value = chr(codepoint) + 'content' + chr(codepoint)
    with pytest.raises(InvalidDocumentError, match='invalid control in PPT comment string'):
        run(monkeypatch, fixture(comment(**{role: value})))


@pytest.mark.parametrize('role', ['value', 'author', 'initials'])
@pytest.mark.parametrize('codepoint', range(32))
def test_comment_roles_allow_only_text_tab_cr_lf(monkeypatch, role, codepoint):
    payload = 'a' + chr(codepoint) + 'b'
    f = fixture(comment(**{role: payload}))
    if role == 'value' and codepoint in (9, 10, 13):
        doc = run(monkeypatch, f)
        assert doc.slides[0].comments[0].text == ('a\tb' if codepoint == 9 else 'a\nb')
    else:
        with pytest.raises(InvalidDocumentError, match='invalid control in PPT comment string'):
            run(monkeypatch, f)


@pytest.mark.parametrize('role', ['value', 'author', 'initials'])
@pytest.mark.parametrize('char', ['~', '\u00a0', 'é', '世', '😀'])
def test_comment_roles_retain_printable_range_neighbors(monkeypatch, role, char):
    doc = run(monkeypatch, fixture(comment(**{role: 'a' + char + 'b'})))
    result = doc.slides[0].comments[0]
    assert getattr(result, 'text' if role == 'value' else role) == 'a' + char + 'b'
