"""Public heading contract checked against the independently authored DOC."""
import importlib.util
import json
from pathlib import Path

import pytest

from legacy_office_parser import parse, parse_doc
from legacy_office_parser.cli import main
from legacy_office_parser.errors import InvalidDocumentError


FIXTURES = Path(__file__).parent / 'fixtures' / 'doc_headings'
SOURCE = FIXTURES / 'authored.doc'


def expected_levels():
    spec = importlib.util.spec_from_file_location('heading_fixture_oracle', FIXTURES / 'fixture.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.EXPECTED


def paragraphs(blocks):
    for block in blocks:
        if block['kind'] == 'paragraph':
            yield block
        else:
            for row in block['rows']:
                for cell in row:
                    yield from paragraphs(cell.get('blocks', []))


def assert_authored_levels(result):
    items = list(paragraphs(result['blocks']))
    for blocks in result.get('story_blocks', {}).values():
        items.extend(paragraphs(blocks))
    nonempty = [item for item in items if item['text']]
    assert len(nonempty) == len(expected_levels())
    assert {item['text']: item.get('heading_level') for item in nonempty} == expected_levels()
    assert all('heading_level' not in item for item in items
               if item.get('heading_level') is None)
    # A cell or header heading must remain owned by that container.
    main_texts = [p['text'] for p in result['blocks'] if p['kind'] == 'paragraph']
    assert 'Cell heading specimen' not in main_texts
    assert 'Header heading specimen' not in main_texts


def test_authored_heading_public_dispatch_and_source_forms():
    expected = parse_doc(SOURCE).to_dict()
    assert_authored_levels(expected)
    for source in (SOURCE, str(SOURCE), SOURCE.read_bytes()):
        assert parse(source).to_dict() == expected
        assert parse_doc(source).to_dict() == expected


@pytest.mark.parametrize('format_args', [[], ['--format', 'doc']])
def test_authored_heading_cli_json_and_unchanged_plain_text(capsys, format_args):
    doc = parse_doc(SOURCE)
    assert main([str(SOURCE), *format_args, '--json']) == 0
    output = capsys.readouterr()
    structured = json.loads(output.out)
    assert structured == doc.to_dict()
    assert_authored_levels(structured)
    # Literal authored reading order; the four trailing newlines also match
    # the pre-heading parser's projection of this same persisted binary.
    flat = '\n\n'.join(expected_levels()) + '\n\n\n\n'
    assert doc.text == flat
    assert main([str(SOURCE), *format_args]) == 0
    assert capsys.readouterr().out == flat + '\n'


def test_public_boundary_and_cli_reject_invalid_nested_heading(monkeypatch, capsys):
    import legacy_office_parser.doc as doc_reader

    poisoned = parse_doc(SOURCE)
    table = next(block for block in poisoned.blocks if block.kind == 'table')
    table.rows[0][0].blocks[0].heading_level = True
    monkeypatch.setattr(doc_reader, 'parse_doc_bytes', lambda *args: poisoned)
    for reader in (parse, parse_doc):
        with pytest.raises(InvalidDocumentError, match='invalid paragraph heading level'):
            reader(SOURCE)
    assert main([str(SOURCE), '--json']) == 2
    output = capsys.readouterr()
    assert output.out == ''
    assert 'InvalidDocumentError: invalid paragraph heading level' in output.err
    assert 'specimen' not in output.err
