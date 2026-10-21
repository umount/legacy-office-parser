"""Malformed XML encoding declarations use the public error contract."""
import pytest

from legacy_office_parser import parse, InvalidDocumentError
from legacy_office_parser.cli import main
from test_odf import package


@pytest.mark.parametrize('member', ['content', 'manifest', 'styles'])
def test_unknown_xml_encoding_is_a_structured_error(member, tmp_path, capsys):
    xml = b'<?xml version="1.0" encoding="unknown-private-encoding"?><root/>'
    kwargs = {'content': xml} if member == 'content' else (
        {'manifest': xml} if member == 'manifest' else {'extra': {'styles.xml': xml}})
    data = package('<text:p>ok</text:p>', **kwargs)
    with pytest.raises(InvalidDocumentError) as exc:
        parse(data)
    assert 'unknown-private-encoding' not in str(exc.value)
    path = tmp_path / 'invalid.odt'
    path.write_bytes(data)
    assert main([str(path)]) == 2
    output = capsys.readouterr()
    assert not output.out
    assert 'InvalidDocumentError' in output.err
    assert 'Traceback' not in output.err
    assert 'unknown-private-encoding' not in output.err
