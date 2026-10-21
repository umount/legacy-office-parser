"""Public projections retain Unicode WordArt without exposing fallback copies."""
import json

from legacy_office_parser import parse, parse_rtf
from legacy_office_parser.cli import main


def test_unicode_wordart_public_api_and_cli(tmp_path, capsys):
    source = tmp_path / 'unicode.rtf'
    source.write_bytes(
        br'{\rtf1\ansi Before\par{\shp{\*\shpinst'
        br'{\sp{\sn shapeType}{\sv 136}}'
        br'{\sp{\sn fGtext}{\sv 1}}'
        br'{\sp{\sn fGtextOK}{\sv 1}}'
        br'{\sp{\sn gtextUNICODE}{\sv \u1046? \u-10179?\u-8704?}}'
        br'}{\shprslt Suppressed duplicate}}After\par}')
    expected = 'Ж 😀'
    generic = parse(source)
    specific = parse_rtf(source)
    assert generic.to_dict() == specific.to_dict()
    assert generic.textboxes == expected
    assert generic.text.count(expected) == 1
    assert 'Suppressed duplicate' not in generic.text
    assert main([str(source), '--json']) == 0
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert result['textboxes'] == expected
    assert expected in output.out
    assert main([str(source)]) == 0
    assert capsys.readouterr().out == generic.text + '\n'
