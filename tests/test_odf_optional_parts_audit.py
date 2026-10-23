"""Original optional-part audit fixtures; no external or private documents."""
from io import BytesIO
from zipfile import ZipFile, ZIP_STORED

import pytest

from legacy_office_parser import Limits, parse
from legacy_office_parser.errors import InvalidDocumentError, LimitExceededError
from test_odf import NS

DECL = ' '.join(f'xmlns:{key}="{value}"' for key, value in NS.items())


def xml_root(name, body=''):
    return f'<office:{name} {DECL} office:version="1.3">{body}</office:{name}>'


def package(fmt='odt', body=None, extras=None, content=True):
    kind, suffix = {'odt': ('text', 'text'), 'ods': ('spreadsheet', 'spreadsheet'),
                    'odp': ('presentation', 'presentation')}[fmt]
    mime = 'application/vnd.oasis.opendocument.' + suffix
    if body is None:
        body = {'odt': '<text:p>Main</text:p>',
                'ods': '<table:table table:name="S"><table:table-row><table:table-cell '
                       'office:value-type="string"><text:p>Main</text:p></table:table-cell>'
                       '</table:table-row></table:table>',
                'odp': '<draw:page><draw:frame><draw:text-box><text:p>Main</text:p>'
                       '</draw:text-box></draw:frame></draw:page>'}[fmt]
    parts = dict(extras or {})
    if content:
        parts['content.xml'] = xml_root('document-content',
            f'<office:body><office:{kind}>{body}</office:{kind}></office:body>')
    entries = ''.join(f'<manifest:file-entry manifest:full-path="{name}" '
                      'manifest:media-type="text/xml"/>' for name in parts)
    manifest = (f'<manifest:manifest xmlns:manifest="{NS["manifest"]}" manifest:version="1.3">'
                f'<manifest:file-entry manifest:full-path="/" manifest:media-type="{mime}"/>'
                + entries + '</manifest:manifest>')
    stream = BytesIO()
    with ZipFile(stream, 'w', ZIP_STORED) as archive:
        archive.writestr('mimetype', mime)
        archive.writestr('META-INF/manifest.xml', manifest)
        for name, value in parts.items():
            archive.writestr(name, value)
    return stream.getvalue()


@pytest.mark.parametrize('fmt', ['odt', 'ods', 'odp'])
@pytest.mark.parametrize('containers', [None, '', '<office:styles/>', '<office:automatic-styles/>',
                                      '<office:master-styles/>', '<office:font-face-decls/>',
                                      '<office:styles/><office:automatic-styles/><office:master-styles/>'])
def test_missing_or_empty_style_structures_preserve_main(fmt, containers):
    extras = {} if containers is None else {'styles.xml': xml_root('document-styles', containers)}
    assert 'Main' in parse(package(fmt, extras=extras)).text


@pytest.mark.parametrize('fmt', ['odt', 'ods', 'odp'])
def test_optional_metadata_and_settings_are_not_opened(monkeypatch, fmt):
    extras = {'meta.xml': xml_root('document-meta', '<office:meta/>'),
              'settings.xml': xml_root('document-settings', '<office:settings/>')}
    opened = []
    original = ZipFile.open

    def observe(self, name, *args, **kwargs):
        opened.append(name)
        return original(self, name, *args, **kwargs)

    monkeypatch.setattr(ZipFile, 'open', observe)
    assert 'Main' in parse(package(fmt, extras=extras)).text
    assert 'meta.xml' not in opened and 'settings.xml' not in opened


@pytest.mark.parametrize('fmt', ['odt', 'ods', 'odp'])
def test_empty_main_collection_is_not_missing_body(fmt):
    assert parse(package(fmt, body='')).text == ''


@pytest.mark.parametrize('header', ['', '<style:header/>', '<style:footer/>',
                                    '<style:header><text:p/></style:header><style:footer/>'])
def test_empty_master_auxiliary_stories_do_not_refuse_main(header):
    styles = xml_root('document-styles', '<office:master-styles><style:master-page '
                      'style:name="M">' + header + '</style:master-page></office:master-styles>')
    doc = parse(package(extras={'styles.xml': styles}))
    assert doc.text == 'Main' and doc.headers_footers == ''


@pytest.mark.parametrize('kind', ['footnote', 'endnote'])
def test_empty_note_preserves_body_ownership_without_text(kind):
    body = ('<text:p>Main<text:note text:note-class="'+kind+'"><text:note-citation/>'
            '<text:note-body><text:p/></text:note-body></text:note></text:p>')
    doc = parse(package(body=body))
    assert doc.text == 'Main' and len(doc.notes) == 1
    assert doc.notes[0].body.block_end - doc.notes[0].body.block_start == 1


@pytest.mark.parametrize('fmt', ['ods', 'odp'])
def test_missing_visibility_reference_retains_main(fmt):
    raw = package(fmt)
    # Rebuild content without changing its required body or the package inventory.
    with ZipFile(BytesIO(raw)) as archive:
        content = archive.read('content.xml').decode()
    token = '<table:table ' if fmt == 'ods' else '<draw:page>'
    replacement = '<table:table table:style-name="Absent" ' if fmt == 'ods' else '<draw:page draw:style-name="Absent">'
    doc = parse(package(fmt, content=False, extras={'content.xml': content.replace(token, replacement, 1)}))
    assert 'Main' in doc.text
    assert (doc.sheets or doc.slides)[0].hidden is False
    assert any(d.code == 'odf_sheet_slide_visibility_style_unresolved' for d in doc.diagnostics)


@pytest.mark.parametrize('bad', [b'', b' ', b'<office:document-styles',
                                b'<!DOCTYPE x [<!ENTITY a "x">]><x/>'])
def test_present_corrupt_styles_are_not_treated_as_absent(bad):
    with pytest.raises(InvalidDocumentError):
        parse(package(extras={'styles.xml': bad}))


@pytest.mark.parametrize('bad', [None, b'', xml_root('document-content'),
                                xml_root('document-content', '<office:body/>'),
                                xml_root('document-content', '<office:body><office:spreadsheet/></office:body>')])
def test_missing_or_corrupt_main_is_not_rescued_by_optional_styles(bad):
    extras = {'styles.xml': xml_root('document-styles')}
    if bad is not None:
        extras['content.xml'] = bad
    with pytest.raises(InvalidDocumentError):
        parse(package(content=False, extras=extras))


def test_optional_parts_still_obey_source_and_archive_budgets():
    styles = xml_root('document-styles', '<office:styles>'+'<style:style style:name="S" '
                      'style:family="paragraph"/>'*30+'</office:styles>')
    with pytest.raises(LimitExceededError, match='node limit'):
        parse(package(extras={'styles.xml': styles}), limits=Limits(max_records=20))
    with pytest.raises(LimitExceededError, match='member size'):
        parse(package(extras={'meta.xml': 'x'*10000}), limits=Limits(max_stream_bytes=5000))
