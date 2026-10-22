"""Original synthetic ODF templates: MIME-based detection and unchanged safeguards.

ODF 1.3 Part 3 document types and Appendix C pair OTT/OTS/OTP with the
text/spreadsheet/presentation bodies; extension is not a detection signal.
https://docs.oasis-open.org/office/OpenDocument/v1.3/os/part3-schema/OpenDocument-v1.3-os-part3-schema.html
"""
from io import BytesIO
import struct
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

import pytest

from legacy_office_parser import (
    parse, parse_odt, parse_ods, parse_odp, Limits, EncryptedDocumentError,
    InvalidDocumentError, LimitExceededError, UnsupportedFormatError,
)

CASES = [
    ('ott', 'text', 'odt', parse_odt),
    ('ots', 'spreadsheet', 'ods', parse_ods),
    ('otp', 'presentation', 'odp', parse_odp),
]
PREFIX = 'application/vnd.oasis.opendocument.'
OFFICE = 'urn:oasis:names:tc:opendocument:xmlns:office:1.0'
MANIFEST = 'urn:oasis:names:tc:opendocument:xmlns:manifest:1.0'
NAMESPACES = (f'xmlns:office="{OFFICE}" '
              'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
              'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
              'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"')
BODIES = {
    'text': '<text:h text:outline-level="2">Original template specimen</text:h>',
    'spreadsheet': '<table:table table:name="Template"><table:table-row>'
                   '<table:table-cell office:value-type="float" office:value="42">'
                   '<text:p>42</text:p></table:table-cell></table:table-row></table:table>',
    'presentation': '<draw:page draw:name="Template"><draw:frame><draw:text-box>'
                    '<text:p>Original template specimen</text:p>'
                    '</draw:text-box></draw:frame></draw:page>',
}


def source(kind, *, template=True):
    mime = PREFIX + kind + ('-template' if template else '')
    return {
        'mimetype': mime.encode('ascii'),
        'META-INF/manifest.xml': (
            f'<manifest:manifest xmlns:manifest="{MANIFEST}" manifest:version="1.3">'
            f'<manifest:file-entry manifest:full-path="/" manifest:media-type="{mime}"/>'
            '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>'
            '</manifest:manifest>').encode(),
        'content.xml': (
            f'<office:document-content {NAMESPACES} office:version="1.3"><office:body>'
            f'<office:{kind}>{BODIES[kind]}</office:{kind}>'
            '</office:body></office:document-content>').encode(),
    }


def package(parts):
    out = BytesIO()
    with ZipFile(out, 'w') as archive:
        for name, data in parts.items():
            info = ZipInfo(name, (2020, 1, 1, 0, 0, 0))
            # ODF's mimetype is the first, uncompressed member without extras.
            if name != 'mimetype':
                info.compress_type = ZIP_DEFLATED
            archive.writestr(info, data)
    return out.getvalue()


@pytest.mark.parametrize('extension,kind,fmt,reader', CASES)
def test_template_public_detection_and_explicit_reader(tmp_path, extension, kind, fmt, reader):
    data = package(source(kind))
    ordinary = parse(package(source(kind, template=False)))
    for name in ('sample.' + extension, 'misleading.doc', 'misleading.ods', 'no-extension'):
        path = tmp_path / name
        path.write_bytes(data)
        for input_value in (data, path, str(path)):
            for entry in (parse, reader):
                doc = entry(input_value)
                assert doc.format == fmt
                assert doc.to_dict() == ordinary.to_dict()
                assert doc.warnings == []
                if fmt == 'odt':
                    assert doc.blocks[0].text == 'Original template specimen'
                    assert doc.blocks[0].heading_level == 2
                elif fmt == 'ods':
                    assert doc.sheets[0].cells[0].value == 42
                    assert doc.sheets[0].cells[0].address == 'A1'
                else:
                    assert doc.slides[0].text == 'Original template specimen'
    for wrong in (r for _, _, _, r in CASES if r is not reader):
        with pytest.raises(InvalidDocumentError, match='expected format'):
            wrong(data)


@pytest.mark.parametrize('extension,kind,fmt,reader', CASES)
@pytest.mark.parametrize('manifest_kind', ['ordinary_same_family', 'other_template'])
def test_actual_mimes_must_match_before_family_normalization(
        extension, kind, fmt, reader, manifest_kind):
    parts = source(kind)
    root = PREFIX + (kind if manifest_kind == 'ordinary_same_family' else
                     ('spreadsheet-template' if kind == 'text' else 'text-template'))
    parts['META-INF/manifest.xml'] = parts['META-INF/manifest.xml'].replace(
        (PREFIX + kind + '-template').encode(), root.encode())
    for entry in (parse, reader):
        with pytest.raises(InvalidDocumentError, match='mimetype/manifest mismatch'):
            entry(package(parts))


@pytest.mark.parametrize('extension,kind,fmt,reader', CASES)
def test_manifest_fallback_and_missing_manifest_policy(extension, kind, fmt, reader):
    parts = source(kind)
    del parts['mimetype']
    assert reader(package(parts)).format == fmt
    assert parse(package(parts)).warnings == []
    parts = source(kind)
    del parts['META-INF/manifest.xml']
    doc = parse(package(parts))
    assert doc.format == fmt
    assert doc.warnings == [
        'ODF manifest missing; package encryption declarations could not be checked.']


@pytest.mark.parametrize('extension,kind,fmt,reader', CASES)
@pytest.mark.parametrize('damage', ['wrong_body', 'ambiguous_body', 'wrong_root',
                                    'bad_xml', 'missing_content', 'bad_manifest'])
def test_template_malformed_content_still_rejected(extension, kind, fmt, reader, damage):
    parts = source(kind)
    content = parts['content.xml']
    if damage == 'wrong_body':
        other = 'spreadsheet' if kind == 'text' else 'text'
        content = content.replace(('office:' + kind).encode(), ('office:' + other).encode())
    elif damage == 'ambiguous_body':
        content = content.replace(b'</office:body>', b'<office:text/></office:body>')
    elif damage == 'wrong_root':
        content = content.replace(b'office:document-content', b'office:document-styles')
    elif damage == 'bad_xml':
        content = b'<broken'
    elif damage == 'bad_manifest':
        parts['META-INF/manifest.xml'] = b'<wrong/>'
    parts['content.xml'] = content
    if damage == 'missing_content':
        del parts['content.xml']
    for entry in (parse, reader):
        with pytest.raises(InvalidDocumentError):
            entry(package(parts))


@pytest.mark.parametrize('extension,kind,fmt,reader', CASES)
@pytest.mark.parametrize('encryption', ['manifest', 'zip'])
def test_template_encryption_still_rejected(extension, kind, fmt, reader, encryption):
    parts = source(kind)
    if encryption == 'manifest':
        parts['META-INF/manifest.xml'] = parts['META-INF/manifest.xml'].replace(
            b'</manifest:manifest>', b'<manifest:file-entry manifest:full-path="secret">'
            b'<manifest:encryption-data/></manifest:file-entry></manifest:manifest>')
    data = bytearray(package(parts))
    if encryption == 'zip':
        central = data.index(b'PK\x01\x02')
        struct.pack_into('<H', data, central + 8, 1)
        struct.pack_into('<H', data, 6, 1)
    for entry in (parse, reader):
        with pytest.raises(EncryptedDocumentError):
            entry(bytes(data))


@pytest.mark.parametrize('extension,kind,fmt,reader', CASES)
@pytest.mark.parametrize('limit', ['max_file_bytes', 'max_stream_bytes', 'max_uncompressed_bytes',
                                  'max_archive_entries', 'max_records', 'max_depth', 'max_text_chars'])
def test_template_limits_still_enforced(extension, kind, fmt, reader, limit):
    data = package(source(kind))
    limits = Limits(**{limit: 1})
    for entry in (parse, reader):
        with pytest.raises(LimitExceededError):
            entry(data, limits=limits)


@pytest.mark.parametrize('mime', [PREFIX + 'graphics-template', PREFIX + 'text-template-extra',
                                PREFIX + 'text-template\n', 'application/octet-stream'])
def test_extension_cannot_enable_unknown_mime(tmp_path, mime):
    parts = source('text')
    parts['mimetype'] = mime.encode()
    del parts['META-INF/manifest.xml']
    path = tmp_path / 'pretending.ott'
    path.write_bytes(package(parts))
    with pytest.raises(UnsupportedFormatError, match='mimetype'):
        parse(path)
