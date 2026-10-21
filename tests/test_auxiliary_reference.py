"""Benign independently constructed auxiliary stories; no source document data."""
import io
import json
from zipfile import ZipFile

import pytest

from legacy_office_parser.models import Document
from test_document_reference import W, p, reference, tbl, tc, tr

R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
P = 'http://schemas.openxmlformats.org/package/2006/relationships'


def oracle(doc, parts=(), body='', references=None, extra=None):
    refs, rels = [], []
    for i, (kind, content) in enumerate(parts, 1):
        refs.append(f'<w:{kind}Reference w:type="default" r:id="r{i}"/>')
        rels.append(f'<Relationship Id="r{i}" Type="{R}/{kind}" Target="{kind}{i}.xml"/>')
    if references is not None:
        refs = references
    stream = io.BytesIO()
    with ZipFile(stream, 'w') as archive:
        archive.writestr('word/document.xml', f'<w:document xmlns:w="{W}" xmlns:r="{R}">'
                         f'<w:body>{body}<w:sectPr>{"".join(refs)}</w:sectPr></w:body></w:document>')
        archive.writestr('word/_rels/document.xml.rels',
                         (extra or {}).get('word/_rels/document.xml.rels',
                         f'<Relationships xmlns="{P}">{"".join(rels)}</Relationships>'))
        for i, (kind, content) in enumerate(parts, 1):
            tag = 'hdr' if kind == 'header' else 'ftr'
            archive.writestr(f'word/{kind}{i}.xml',
                             f'<w:{tag} xmlns:w="{W}">{content}</w:{tag}>')
        for name, content in (extra or {}).items():
            if name != 'word/_rels/document.xml.rels':
                archive.writestr(name, content)
    with ZipFile(stream) as archive:
        return reference.compare_document(doc, archive)


def box(text):
    return '<w:p><w:r><w:pict><w:txbxContent>' + p(text) + \
           '</w:txbxContent></w:pict></w:r></w:p>'


@pytest.mark.parametrize('fmt', ['doc', 'rtf', 'odt'])
@pytest.mark.parametrize('kind', ['header', 'footer'])
def test_single_story_can_compare_order_but_never_identity_or_placement(fmt, kind):
    report = oracle(Document(fmt, headers_footers='alpha beta'), [(kind, p('alpha') + p('beta'))])
    check = report['headers_footers']
    assert report['equal'] is True and check['complete']
    assert check['text_equal'] and check['token_multiset_equal']
    assert check['pooled_text_only'] and check['tables_text_only']
    assert not check['placement_comparable'] and not check['anchors_comparable']
    assert not check['story_identity_comparable']
    reversed_report = oracle(Document(fmt, headers_footers='beta alpha'),
                             [(kind, p('alpha') + p('beta'))])
    assert reversed_report['equal'] is False
    assert reversed_report['headers_footers']['token_multiset_equal'] is True


@pytest.mark.parametrize('actual', ['alpha beta', 'beta alpha'])
def test_multiple_stories_do_not_imply_source_order_from_part_names(actual):
    report = oracle(Document('doc', headers_footers=actual),
                    [('header', p('alpha')), ('footer', p('beta'))])
    check = report['headers_footers']
    assert check['content_complete'] and check['token_multiset_equal']
    assert check['text_equal'] is None and check['equal'] is None
    assert not check['order_comparable'] and not check['complete']
    assert report['equal'] is None


def test_duplicate_tokens_are_not_deduplicated_or_treated_as_order_proof():
    report = oracle(Document('odt', headers_footers='same'),
                    [('header', p('same')), ('footer', p('same'))])
    assert report['headers_footers']['token_multiset_equal'] is False
    assert report['headers_footers']['equal'] is None


def test_empty_variants_do_not_destroy_recoverable_text_order():
    report = oracle(Document('rtf', headers_footers='one two'),
                    [('header', p('')), ('footer', p('one two'))])
    assert report['equal'] is True
    assert report['headers_footers']['reference_stories'] == 2


def test_shared_header_reference_is_read_once_not_once_per_section():
    report = oracle(Document('doc', headers_footers='one'), [('header', p('one'))],
                    references=['<w:headerReference r:id="r1"/>'] * 2)
    assert report['equal'] is True
    assert report['headers_footers']['reference_stories'] == 1


def test_unreferenced_or_missing_parts_are_incomplete():
    for refs in ([], ['<w:headerReference r:id="absent"/>']):
        report = oracle(Document('doc', headers_footers='one'),
                        [('header', p('one'))], references=refs)
        assert not report['headers_footers']['content_complete']
        assert report['headers_footers']['equal'] is None


def test_nested_auxiliary_table_projection_checks_word_order_not_structure():
    content = p('before') + tbl(tr(tc(content=p('cell') + tbl(tr(tc('nested')))))) + p('after')
    report = oracle(Document('odt', headers_footers='before cell nested after'), [('header', content)])
    assert report['equal'] is True
    assert report['headers_footers']['tables_text_only']


def test_single_textbox_is_independently_comparable_even_when_body_geometry_is_not():
    report = oracle(Document('rtf', textboxes='box words'), body=box('box words'))
    assert report['textboxes']['equal'] is True
    assert report['textboxes']['content_complete']
    assert report['body']['equal'] is None  # Drawing/anchor handling stays conservative.
    assert report['equal'] is None
    assert not report['textboxes']['anchors_comparable']


def test_main_and_header_boxes_share_pool_without_invented_order():
    report = oracle(Document('doc', textboxes='second first'),
                    [('header', box('second'))], body=box('first'))
    assert report['textboxes']['reference_stories'] == 2
    assert report['textboxes']['token_multiset_equal'] is True
    assert report['textboxes']['equal'] is None


def test_alternate_representations_never_double_count_as_complete():
    body = '<mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006">' \
           '<mc:Choice Requires="w">' + box('same') + '</mc:Choice><mc:Fallback>' + \
           box('same') + '</mc:Fallback></mc:AlternateContent>'
    report = oracle(Document('doc', textboxes='same same'), body=body)
    assert report['textboxes']['equal'] is None
    assert report['textboxes']['token_multiset_equal'] is None


def test_unknown_auxiliary_xml_and_private_data_are_not_reported():
    secret = 'DO_NOT_REPORT_973'
    report = oracle(Document('odt', headers_footers=secret),
                    [('header', p(secret) + '<w:unknown-private/>')])
    assert report['headers_footers']['equal'] is None
    assert secret not in json.dumps(report)
    assert 'unknown-private' not in json.dumps(report)


def test_model_only_auxiliary_text_is_a_complete_difference():
    report = oracle(Document('doc', headers_footers='lost', textboxes='missing'))
    assert report['complete'] and report['equal'] is False
    assert report['headers_footers']['equal'] is False
    assert report['textboxes']['equal'] is False


def test_malformed_relationships_are_sanitized():
    report = oracle(Document('doc'), extra={'word/_rels/document.xml.rels': '<PRIVATE'})
    assert report == {'status': 'invalid_reference', 'complete': False, 'equal': None}


def test_note_textboxes_cannot_make_main_textbox_pool_falsely_complete():
    notes = f'<w:footnotes xmlns:w="{W}"><w:footnote w:id="1">' + box('note box') + \
            '</w:footnote></w:footnotes>'
    report = oracle(Document('doc'), extra={'word/footnotes.xml': notes})
    assert report['textboxes']['equal'] is None
    assert not report['textboxes']['content_complete']


@pytest.mark.parametrize('fmt', ['rtf', 'doc', 'odt'])
def test_optional_libreoffice_roundtrip_of_authored_fixture(tmp_path, fmt):
    """Opt in with AUXILIARY_REFERENCE_LO=1; no LO dependency for regular tests."""
    import os
    from pathlib import Path
    import shutil
    import subprocess

    if os.environ.get('AUXILIARY_REFERENCE_LO') != '1':
        pytest.skip('optional LibreOffice oracle')
    executable = shutil.which('libreoffice')
    if executable is None:
        pytest.skip('LibreOffice unavailable')
    from legacy_office_parser import api

    source = Path(__file__).parent / 'fixtures/auxiliary_reference/single-header.rtf'
    profile = (tmp_path / 'profile').as_uri()

    def convert(path, extension, output):
        output.mkdir(exist_ok=True)
        subprocess.run([executable, f'-env:UserInstallation={profile}', '--headless',
                        '--convert-to', extension, '--outdir', str(output), str(path)],
                       check=True, capture_output=True, timeout=60)
        result = output / (path.stem + '.' + extension)
        assert result.is_file()
        return result

    if fmt != 'rtf':
        source = convert(source, fmt, tmp_path / 'source')
    expected = convert(source, 'docx', tmp_path / 'reference')
    doc = getattr(api, 'parse_' + fmt)(source)
    authored = 'Reference header alpha Second header beta'.split()
    # Writer versions can emit separate first/even/default parts for one source
    # header. Verify every part's full authored content without declaring those
    # variants to have a recoverable cross-story order or identical identities.
    import xml.etree.ElementTree as ET
    with ZipFile(expected) as archive:
        report = reference.compare_document(doc, archive)
        nonempty_parts = []
        for name in archive.namelist():
            if name.startswith('word/header') and name.endswith('.xml'):
                root = ET.fromstring(archive.read(name))
                tokens = ' '.join(node.text or '' for node in root.iter('{' + W + '}t')).split()
                if tokens:
                    assert tokens == authored
                    nonempty_parts.append(tokens)
    assert nonempty_parts
    tokens = doc.headers_footers.split()
    assert tokens and len(tokens) % len(authored) == 0
    assert tokens == authored * (len(tokens) // len(authored))
    if fmt == 'rtf':
        assert tokens == authored  # The original source has exactly one header.
    check = report['headers_footers']
    assert check['content_complete']
    assert check['reference_nonempty_stories'] == len(nonempty_parts)
    assert report['body']['equal'] is True
    assert report['footnotes']['equal'] is True
    assert report['endnotes']['equal'] is True
    assert report['textboxes']['equal'] is True
    if len(nonempty_parts) == 1:
        # DOC can store separate identical header variants which a subsequent
        # DOCX export coalesces. A pooled string has no variant IDs: preserve
        # this multiplicity difference instead of teaching the oracle to dedupe.
        same_multiplicity = tokens == authored
        assert check['equal'] is same_multiplicity
        assert check['token_multiset_equal'] is same_multiplicity
        assert report['equal'] is same_multiplicity
    else:
        assert check['equal'] is None and not check['order_comparable']
        assert not check['complete'] and report['equal'] is None
