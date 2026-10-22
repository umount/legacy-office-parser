"""Public API and CLI behavior for the original terminal-NUL regression."""
import json

from legacy_office_parser import parse, parse_rtf
from legacy_office_parser.cli import main

SOURCE = br'{\rtf1 Original}' + b'\0'
WARNING = 'A single terminal NUL after the RTF root was ignored.'


def test_terminal_nul_public_dispatch_and_warning():
    for reader in (parse, parse_rtf):
        result = reader(SOURCE)
        assert result.text == 'Original'
        assert result.warnings == [WARNING]


def test_terminal_nul_cli_remains_visible_in_strict_mode(tmp_path, capsys):
    path = tmp_path / 'original.rtf'
    path.write_bytes(SOURCE)
    assert main([str(path), '--json']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['warnings'] == [WARNING]
    assert result['blocks'] == [{'kind': 'paragraph', 'text': 'Original'}]
    assert main([str(path), '--json', '--strict']) == 3
    assert json.loads(capsys.readouterr().out) == result
