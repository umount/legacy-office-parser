"""Serialization and repeatability checks using only authored/synthetic inputs."""
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from enum import Enum
from io import BytesIO
import json
import multiprocessing
import os
import pickle
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

import pytest

from legacy_office_parser import (
    Cell, CellRange, Comment, CommentBodyRange, Document, InvalidDocumentError,
    Limits, Note, NoteBodyRange, Paragraph, Sheet, Slide, SlideComment,
    SpreadsheetCell, Table, parse, parse_odt, parse_rtf,
)
from legacy_office_parser._serialization import clone_model, model_to_dict
from legacy_office_parser.diagnostics import CodedWarning


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / 'fixtures'
AUTHORED = [
    ('doc', 'ordinary_table.doc'),
    ('xls', 'extended/typed_sparse.xls'),
    ('ppt', 'slides_notes.ppt'),
    ('rtf', 'extended/ordinary_table.rtf'),
    ('odt', 'extended/ordinary_table.odt'),
    ('ods', 'extended/typed_sparse.ods'),
    ('odp', 'extended/slides_notes.odp'),
]


def _legacy_dict(obj):
    """Frozen pre-change oracle, independent of the implementation under test."""
    def factory(items):
        result = dict(items)
        if result.get('kind') == 'paragraph' and result.get('heading_level') is None:
            result.pop('heading_level', None)
        if 'row_span' in result:
            if not result.get('blocks'):
                result.pop('blocks', None)
            if not result.get('omitted'):
                result.pop('omitted', None)
        if 'reply_depth' in result and result['reply_depth'] is None:
            result.pop('reply_depth')
            if result.get('parent_ordinal') is None:
                result.pop('parent_ordinal', None)
        if 'comments' in result and not result['comments']:
            result.pop('comments')
        if 'drawings' in result and not result['drawings']:
            result.pop('drawings')
        if 'format' in result:
            if not result.get('story_blocks'):
                result.pop('story_blocks', None)
            if not result.get('notes'):
                result.pop('notes', None)
            if not result.get('comment_text'):
                result.pop('comment_text', None)
        return result
    return asdict(obj, dict_factory=factory)


def _assert_public_legacy(doc, expected):
    actual = doc.to_dict()
    # Main owns the optional additive root diagnostics API. If exposed, verify
    # the complete extension explicitly; never drop it from reliability checks.
    if 'diagnostics' in actual:
        diagnostics, seen = [], set()
        for warning in doc.warnings:
            code = warning.code if isinstance(warning, CodedWarning) else 'unclassified_warning'
            pair = (code, str(warning))
            if pair not in seen:
                diagnostics.append({'code': code, 'message': str(warning)})
                seen.add(pair)
        expected = dict(expected)
        expected['diagnostics'] = diagnostics
    assert actual == expected
    assert _json(actual) == _json(expected)
    return actual


def _json(value):
    # Do not sort or normalize: order, warnings, omissions and whitespace matter.
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _mutable_ids(obj):
    pending, identities = [obj], set()
    while pending:
        value = pending.pop()
        if is_dataclass(value):
            children = [getattr(value, f.name) for f in fields(value)]
        elif isinstance(value, dict):
            children = value.values()
        elif isinstance(value, list):
            children = value
        else:
            continue
        assert id(value) not in identities, 'output occurrences unexpectedly share a mutable object'
        identities.add(id(value))
        pending.extend(children)
    return identities


def _rich_document():
    return Document(
        'doc',
        blocks=[Paragraph('plain'), Paragraph('', 9), Table([[
            Cell(), Cell(omitted=True), Cell('H', blocks=[Paragraph('H', 2)]),
            Cell('nested', blocks=[Table([[Cell('nested')]])]),
        ]])],
        slides=[Slide(1), Slide(2, comments=[SlideComment('C', 'A', 'I')])],
        sheets=[Sheet('empty'), Sheet('data', cells=[
            SpreadsheetCell(2, 3, 1.5, 'number', '1.5', 'source', True),
            SpreadsheetCell(3, 1, False, 'boolean', 'FALSE'),
            SpreadsheetCell(4, 2),
        ], merges=[CellRange(1, 1, 1, 2)], drawings=['drawing'])],
        story_blocks={'textboxes': [Paragraph('box', 1)],
                      'footnotes': [Paragraph('note')],
                      'comment_text': [Paragraph('comment')]},
        notes=[Note('footnote', 1, NoteBodyRange('footnotes', 0, 1), visibility=[])],
        comments=[Comment(1, CommentBodyRange('comment_text', 0, 1)),
                  Comment(2, CommentBodyRange('comment_text', 0, 1), reply_depth=0),
                  Comment(3, CommentBodyRange('comment_text', 0, 1),
                          reply_depth=1, parent_ordinal=2)],
        comment_text='comment', warnings=['one', 'two'],
    )


@pytest.mark.parametrize('doc', [Document('rtf'), _rich_document()])
def test_legacy_omissions_values_and_insertion_order(doc):
    actual, expected = model_to_dict(doc), _legacy_dict(doc)
    assert actual == expected
    assert _json(actual) == _json(expected)
    _assert_public_legacy(doc, expected)
    assert actual is not doc


def test_omissions_apply_only_to_dataclass_records_and_keep_invalid_values():
    # Serialization is not validation, and ordinary dicts must bypass the factory.
    @dataclass
    class Envelope:
        raw: dict
        comment: Comment
        paragraph: Paragraph
    source = Envelope({'kind': 'paragraph', 'heading_level': None, 'comments': []},
                      Comment(1, CommentBodyRange('comment_text', 0, 1), parent_ordinal=7),
                      Paragraph('invalid but serializable', False))
    result = model_to_dict(source)
    assert _json(result) == _json(_legacy_dict(source))
    assert result['raw'] == source.raw
    assert result['comment']['parent_ordinal'] == 7
    assert 'reply_depth' not in result['comment']
    assert result['paragraph']['heading_level'] is False


def test_clone_all_fields_without_defaults_omission_or_aliases():
    doc = _rich_document()
    result = clone_model(doc)
    assert result == doc
    assert type(result) is Document
    assert not (_mutable_ids(result) & _mutable_ids(doc))
    result.blocks[2].rows[0][2].blocks[0].text = 'changed'
    result.story_blocks['textboxes'].append(Paragraph('new'))
    result.warnings.append('new')
    assert doc.blocks[2].rows[0][2].blocks[0].text == 'H'
    assert len(doc.story_blocks['textboxes']) == 1
    assert doc.warnings == ['one', 'two']


@pytest.mark.parametrize('operation', [model_to_dict, clone_model])
def test_shared_acyclic_nodes_are_copied_per_occurrence(operation):
    leaf = Paragraph('leaf', 3)
    shared = [leaf]
    source = {'first': shared, 'second': shared, 'third': {'leaf': leaf}}
    result = operation(source)
    _mutable_ids(result)
    assert result['first'] is not result['second']
    assert result['first'][0] is not result['second'][0]
    if operation is clone_model:
        result['first'][0].text = 'changed'
        assert result['second'][0].text == leaf.text == 'leaf'
    else:
        result['first'][0]['text'] = 'changed'
        assert result['second'][0]['text'] == leaf.text == 'leaf'


@pytest.mark.parametrize('operation', [model_to_dict, clone_model])
@pytest.mark.parametrize('shape', ['list', 'dict', 'dataclass', 'mixed', 'omitted'])
def test_cycles_raise_controlled_error_without_source_text(operation, shape):
    if shape == 'list':
        source = []
        source.append(source)
    elif shape == 'dict':
        source = {}
        source['back'] = source
    else:
        source = Document('rtf', blocks=[Paragraph('PRIVATE-SENTINEL')])
        if shape == 'dataclass':
            source.blocks = source
        elif shape == 'mixed':
            source.blocks.append(Table([[Cell(blocks=[source])]]))
        else:
            # Still traversed even though a similarly named field is often omitted.
            source.comments.append(source.comments)
    with pytest.raises(InvalidDocumentError) as error:
        operation(source)
    assert 'PRIVATE-SENTINEL' not in str(error.value)


@pytest.mark.parametrize('operation', [model_to_dict, clone_model])
def test_deep_mixed_containers_do_not_use_python_recursion(operation):
    depth = 1800
    source = Paragraph('bottom', 4)
    for _ in range(depth):
        source = {'next': [source]}
    result = operation(source)
    for _ in range(depth):
        result = result['next'][0]
    assert (result.text if operation is clone_model else result['text']) == 'bottom'


def test_frozen_slots_init_false_and_enum_strings_clone_without_constructor():
    class Tag(str, Enum):
        PARAGRAPH = 'paragraph'

    @dataclass(frozen=True, slots=True)
    class Record:
        text: str
        tag: Tag = Tag.PARAGRAPH
        derived: list = field(default_factory=list, init=False)

        def __post_init__(self):
            self.derived.append('constructed')

    source = Record('value')
    source.derived.append('edited')
    copied = clone_model(source)
    assert copied == source and copied is not source
    assert copied.derived is not source.derived
    assert copied.derived == ['constructed', 'edited']
    assert copied.tag is Tag.PARAGRAPH
    assert _json(model_to_dict(source)) == _json(_legacy_dict(source))


@pytest.mark.parametrize('operation', [model_to_dict, clone_model])
@pytest.mark.parametrize('value', [(1, 2), {1, 2}, object(), {('tuple',): 'value'}])
def test_unsupported_types_are_explicit_not_deepcopied(operation, value):
    with pytest.raises(TypeError):
        operation(value)


def _parse_worker(data):
    # Module-level function is picklable under spawn, with no inherited parser.
    doc = parse(data)
    return doc.format, doc.to_dict(), model_to_dict(doc)


@pytest.mark.parametrize('fmt,relative', AUTHORED)
def test_seven_authored_formats_repeat_exact_dict(fmt, relative):
    data = (FIXTURES / relative).read_bytes()
    first = parse(data)
    expected = _legacy_dict(first)
    public_expected = _assert_public_legacy(first, expected)
    for _ in range(3):
        doc = parse(data)
        assert doc.format == fmt
        assert _assert_public_legacy(doc, expected) == public_expected
        assert _json(model_to_dict(doc)) == _json(expected)
    first.warnings.append('mutation must not leak')
    assert parse(data).to_dict() == public_expected


def test_seven_authored_formats_spawn_pool_matches_serial():
    inputs = [(FIXTURES / relative).read_bytes() for _, relative in AUTHORED]
    expected = [_parse_worker(data) for data in inputs]
    with ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context('spawn')) as pool:
        actual = list(pool.map(_parse_worker, inputs * 2, timeout=60))
    assert actual == expected * 2
    assert [_json(item) for item in actual] == [_json(item) for item in expected * 2]


def test_seven_authored_formats_hash_seed_fresh_interpreters():
    script = '''
import json, sys
from pathlib import Path
from legacy_office_parser import parse
values = [parse(Path(path).read_bytes()).to_dict() for path in sys.argv[1:]]
print(json.dumps(values, ensure_ascii=False, allow_nan=False))
'''
    paths = [str(FIXTURES / relative) for _, relative in AUTHORED]
    expected = _json([parse(Path(path).read_bytes()).to_dict() for path in paths]) + '\n'
    for seed in ('1', '22', '123'):
        env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONDONTWRITEBYTECODE='1',
                   PYTHONPATH=str(ROOT / 'src'))
        result = subprocess.run([sys.executable, '-c', script, *paths],
                                env=env, capture_output=True, text=True, encoding='utf-8',
                                timeout=30, check=True)
        assert result.stdout == expected


def _nested_rtf(depth):
    parts = [br'{\rtf1\trowd\cellx100\intbl ']
    for level in range(2, depth + 1):
        parts.append(fr'\itap{level} '.encode())
    parts.append(b'leaf')
    for level in range(depth, 1, -1):
        parts.append(fr'\itap{level}\nestcell{{\*\nesttableprops\trowd\cellx100\nestrow}}'.encode())
    parts.append(br'\itap1\cell\row}')
    return b''.join(parts)


def _nested_odt(depth):
    opening = '<table:table><table:table-row><table:table-cell>'
    closing = '</table:table-cell></table:table-row></table:table>'
    content = ('<office:document-content '
               'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
               'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
               'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
               '<office:body><office:text>' + opening * depth +
               '<text:p>leaf</text:p>' + closing * depth +
               '</office:text></office:body></office:document-content>')
    result = BytesIO()
    with ZipFile(result, 'w') as archive:
        archive.writestr('mimetype', 'application/vnd.oasis.opendocument.text')
        archive.writestr('content.xml', content)
    return result.getvalue()


@pytest.mark.parametrize('reader,data,depth', [
    (parse_rtf, _nested_rtf(350), 350),
    (parse_odt, _nested_odt(80), 80),
], ids=['rtf-350-tables', 'odt-80-tables'])
def test_accepted_deep_documents_serialize_and_clone(reader, data, depth):
    doc = reader(data, limits=Limits(max_depth=400))
    assert doc.text == 'leaf'
    # Serialization must not depend on recursive asdict. Parse first, then lower
    # only for copying; the ODF reader's own XML hard depth cap remains respected.
    previous = sys.getrecursionlimit()
    try:
        sys.setrecursionlimit(200)
        independent = model_to_dict(doc)
        copied = clone_model(doc)
        result = doc.to_dict()
    finally:
        sys.setrecursionlimit(previous)
    for tree in (result, independent):
        block = tree['blocks'][0]
        for index in range(depth):
            cell = block['rows'][0][0]
            assert cell['text'] == 'leaf'
            if index + 1 < depth:
                block = cell['blocks'][0]
    block = copied.blocks[0]
    for index in range(depth):
        cell = block.rows[0][0]
        if index + 1 < depth:
            block = cell.blocks[0]
    assert cell.text == 'leaf'
    assert not (_mutable_ids(copied) & _mutable_ids(doc))


def test_coded_warning_is_preserved_as_immutable_scalar_and_pickles():
    warning = CodedWarning('authored_warning', 'original message')
    source = Document('rtf', warnings=[warning])
    cloned = clone_model(source)
    assert cloned.warnings is not source.warnings
    assert cloned.warnings[0] is warning
    assert cloned.warnings[0].code == 'authored_warning'
    assert model_to_dict(source)['warnings'][0] is warning
    assert _json(model_to_dict(source)) == _json(_legacy_dict(source))
    restored = pickle.loads(pickle.dumps(cloned))
    assert isinstance(restored.warnings[0], CodedWarning)
    assert restored.warnings[0].code == 'authored_warning'
    assert str(restored.warnings[0]) == 'original message'
    with pytest.raises(AttributeError):
        restored.warnings[0].code = 'changed'


def _clone_worker(doc):
    return clone_model(doc)


def test_coded_warning_and_model_clone_survive_spawn_pool():
    source = Document('rtf', blocks=[Paragraph('body')],
                      warnings=[CodedWarning('authored_warning', 'message')])
    with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context('spawn')) as pool:
        result = pool.submit(_clone_worker, source).result(timeout=30)
    assert result == source
    assert isinstance(result.warnings[0], CodedWarning)
    assert result.warnings[0].code == 'authored_warning'
    assert result.warnings[0] is not source.warnings[0]
    result.blocks[0].text = 'changed'
    assert source.blocks[0].text == 'body'


@pytest.mark.parametrize('operation', [model_to_dict, clone_model])
def test_deep_dataclass_models_without_recursion(operation):
    node = Paragraph('bottom', 2)
    for _ in range(1200):
        node = Table([[Cell('bottom', blocks=[node])]])
    result = operation(Document('rtf', blocks=[node]))
    current = result.blocks[0] if operation is clone_model else result['blocks'][0]
    for _ in range(1200):
        if operation is clone_model:
            current = current.rows[0][0].blocks[0]
        else:
            current = current['rows'][0][0]['blocks'][0]
    assert (current.text if operation is clone_model else current['text']) == 'bottom'
