"""Public dispatch is content based, including deliberately misleading filenames."""
from io import BytesIO
import json
import zipfile

import pytest

from legacy_office_parser import parse, parse_odt, Limits, LimitExceededError, ParseError
from legacy_office_parser.cli import main


def package(kind):
    family = {'odt': 'text', 'ods': 'spreadsheet', 'odp': 'presentation'}[kind]
    contents = {
        'odt': '<text:p>A</text:p>',
        'ods': '<table:table table:name="S"><table:table-row><table:table-cell '
               'office:value-type="string"><text:p>A</text:p></table:table-cell>'
               '</table:table-row></table:table>',
        'odp': '<draw:page draw:name="S"><draw:frame><draw:text-box><text:p>A</text:p>'
               '</draw:text-box></draw:frame></draw:page>',
    }[kind]
    xml = ('<office:document-content '
           'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
           'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
           'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
           'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0">'
           f'<office:body><office:{family}>{contents}</office:{family}></office:body>'
           '</office:document-content>')
    result = BytesIO()
    with zipfile.ZipFile(result, 'w') as archive:
        archive.writestr('mimetype', 'application/vnd.oasis.opendocument.' + family)
        archive.writestr('content.xml', xml)
        archive.writestr('META-INF/manifest.xml',
                        '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"/>')
    return result.getvalue()


@pytest.mark.parametrize('kind', ['rtf', 'odt', 'ods', 'odp'])
def test_public_api_and_cli_detect_content_in_doc_named_file(tmp_path, capsys, kind):
    data = b'{\\rtf1\\ansi A\\par}' if kind == 'rtf' else package(kind)
    path = tmp_path / 'misleading.doc'
    path.write_bytes(data)
    doc = parse(path)
    assert doc.format == kind
    assert 'A' in doc.text
    assert main([str(path), '--json']) == 0
    assert json.loads(capsys.readouterr().out)['format'] == kind
    assert main([str(path), '--format', kind, '--json']) == 0
    assert json.loads(capsys.readouterr().out)['format'] == kind


def test_explicit_odt_does_not_accept_spreadsheet():
    with pytest.raises(ParseError):
        parse_odt(package('ods'))


@pytest.mark.parametrize('data', [b'{\\rtf1 hello}', package('odt')])
def test_shared_input_limit_applies_before_format_parsing(data):
    with pytest.raises(LimitExceededError):
        parse(data, limits=Limits(max_file_bytes=4))
