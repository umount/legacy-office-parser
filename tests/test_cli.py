import json
from pathlib import Path

from legacy_office_parser.cli import main

FIXTURES = Path(__file__).parent / 'fixtures'


def test_json_cli_preserves_blank_slide_and_notes(capsys):
    assert main([str(FIXTURES / 'slides_notes.ppt'), '--json']) == 0
    out = capsys.readouterr()
    doc = json.loads(out.out)
    assert [slide['number'] for slide in doc['slides']] == [1, 2, 3]
    assert doc['slides'][1]['text'] == ''
    assert not doc['slides'][0]['notes']
    assert doc['slides'][2]['notes']


def test_strict_cli_returns_result_and_nonzero_on_warning(capsys):
    assert main([str(FIXTURES / 'ordinary_table.doc'), '--strict', '--json']) == 3
    out = capsys.readouterr()
    assert json.loads(out.out)['format'] == 'doc'
    assert 'warning:' in out.err


def test_invalid_input_does_not_echo_content(tmp_path, capsys):
    path = tmp_path / 'invalid.doc'
    path.write_bytes(b'private document content')
    assert main([str(path)]) == 2
    out = capsys.readouterr()
    assert not out.out
    assert 'private document content' not in out.err


def test_cli_enforces_requested_file_limit(capsys):
    assert main([str(FIXTURES / 'ordinary_table.doc'), '--max-file-bytes', '8']) == 2
    out = capsys.readouterr()
    assert not out.out
    assert 'LimitExceededError' in out.err
