"""Authored legacy RTF syntax and literal expectations; no private documents."""
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest

from legacy_office_parser.errors import InvalidDocumentError, LimitExceededError
from legacy_office_parser.limits import Limits
from legacy_office_parser.models import Cell, Paragraph, Table
from legacy_office_parser.rtf import parse_rtf_bytes


GEOMETRY = r'\dpx0\dpy0\dpxsize3000\dpysize1500'


def textbox(text):
    return r'\dptxbx\dptxbxmar0{\dptxbxtext ' + text + '}' + GEOMETRY


def drawing(primitives):
    return r'{\*\do\dobxcolumn\dobypara\dodhgt0 ' + primitives + '}'


def rtf(body):
    return ('{\\rtf1\\ansi ' + body + '}').encode('ascii')


def parse(body, **limits):
    return parse_rtf_bytes(rtf(body), Limits(**limits))


STANDALONE = drawing(textbox(r'Legacy\par Second\par'))
GROUP = drawing(r'\dpgroup\dpcount2' + GEOMETRY + textbox('One') +
                textbox('Two') + r'\dpendgroup' + GEOMETRY)
CALLOUT = drawing(r'\dpcallout\dpcotright\dpcooffset0\dpcolength100' + GEOMETRY +
                  r'\dppolyline\dppolycount2\dpptx0\dppty0\dpptx100\dppty100' +
                  GEOMETRY + textbox('Callout'))


@pytest.mark.parametrize('source,expected', [
    (STANDALONE, 'Legacy\nSecond'), (GROUP, 'One\nTwo'), (CALLOUT, 'Callout'),
])
def test_authored_primitives(source, expected):
    result = parse('Before' + source + 'After')
    assert result.blocks == [Paragraph('BeforeAfter')]
    assert result.textboxes == expected
    assert result.story_blocks == {}
    assert result.warnings == ['Legacy drawing and layout omitted.']


def test_independent_identical_stories_are_not_deduplicated():
    source = drawing(textbox('Same'))
    assert parse(source + source).textboxes == 'Same\nSame'
    assert parse(drawing(textbox('Same') + textbox('Same'))).textboxes == 'Same\nSame'


def test_charset_unicode_fields_and_run_visibility():
    source = (r'{\fonttbl{\f0\fcharset204 Cyrillic;}}\f0' + drawing(textbox(
        r"\'cf\u945?\u-10179?\u-8704?"
        r'{\field{\*\fldinst SECRET}{\fldrslt Link}}'
        r'{\v Hidden}{\deleted Deleted}\par Next')))
    assert parse(source).textboxes == 'Пα😀Link\nNext'
    source = drawing(textbox(r"\ansicpg1251 \'cf{\ansicpg1252 \'e9}\'cf"))
    assert parse(source).textboxes == 'ПéП'


@pytest.mark.parametrize('visibility', [r'\v', r'\deleted'])
def test_inherited_visibility_is_not_reset(visibility):
    source = drawing(textbox('Hidden'))
    assert parse('{' + visibility + ' ' + source + '}Visible').text == 'Visible'
    reset = r'\v0\deleted0 Visible'
    assert parse('{' + visibility + ' ' + drawing(textbox(reset)) + '}').textboxes == 'Visible'


@pytest.mark.parametrize('ancestor', [
    r'\pict', r'\object', r'\objdata', r'\result', r'\background',
    r'\sp', r'\sn', r'\sv', r'\info', r'\*\unknown', r'\shprslt', r'\*\shprslt',
])
def test_skipped_ancestor_cannot_be_reopened(ancestor):
    assert parse('Before{' + ancestor + ' ' + STANDALONE + '}After').text == 'BeforeAfter'


@pytest.mark.parametrize('order', [False, True])
def test_modern_fallback_stays_skipped_in_either_order(order):
    primary = r'{\*\shpinst{\shptxt Primary}}'
    fallback = r'{\shprslt' + STANDALONE + '}'
    parts = [primary, fallback] if order else [fallback, primary]
    assert parse(r'{\shp' + ''.join(parts) + '}').textboxes == 'Primary'
    assert parse(r'{\shp' + fallback + '}').textboxes == 'Legacy\nSecond'


@pytest.mark.parametrize('container', ['shp', 'shpinst', 'shpgrp'])
def test_do_inside_modern_container_is_not_a_new_story(container):
    assert parse('{\\' + container + STANDALONE + '}').textboxes == ''


def test_only_explicit_legacy_destination_emits_text():
    decoys = (r'stray\par\trowd\cellx100\cell\row'
              r'{\sp{\sn Name}{\sv Property{\dptxbxtext Bad}}}'
              r'{\*\unknown{\dptxbxtext Bad}}'
              r'{\shptxt Bad}{\header Bad}{\footnote Bad}')
    result = parse('A' + drawing(decoys + textbox('Good') + 'trailer') + 'B')
    assert result.blocks == [Paragraph('AB')]
    assert result.textboxes == 'Good'
    assert not (result.headers_footers or result.footnotes)
    assert parse(r'A{\dptxbxtext Orphan}B').text == 'AB'
    assert parse(r'{\shp{\dptxbxtext Orphan}}').textboxes == ''


def test_binary_payload_is_opaque_in_container_and_story():
    payload = b'{\\dptxbxtext Fake}\\par'
    binary = b'\\bin' + str(len(payload)).encode() + b' ' + payload
    source = rtf('A' + drawing(textbox('Real')) + 'B')
    source = source.replace(b'\\dptxbx\\', binary + b'\\dptxbx\\', 1)
    source = source.replace(b'Real', b'R' + binary + b'eal')
    result = parse_rtf_bytes(source, Limits())
    assert result.blocks == [Paragraph('AB')]
    assert result.textboxes == 'Real'


def test_body_header_and_structured_story_tables_remain_isolated():
    table = r'\trowd\cellx100\cellx200\intbl X\cell Y\cell\row'
    result = parse(r'\trowd\cellx100 A' + drawing(textbox(table)) +
                   r'B\cell\row{\header H' + drawing(textbox('Box')) + 'T}')
    assert result.blocks == [Table([[Cell('AB')]])]
    assert result.headers_footers == 'HT'
    assert result.textboxes == 'X\tY\nBox'
    assert result.story_blocks['textboxes'] == [Table([[Cell('X'), Cell('Y')]]), Paragraph('Box')]


def test_surrogates_do_not_join_across_stories():
    result = parse(drawing(textbox(r'\u-10179?') + textbox(r'\u-8704?')))
    assert result.textboxes == '\ufffd\n\ufffd'


@pytest.mark.parametrize('bad', [r'\bin-1', r'\bin9999 x', r'\u65536', r'\uc-1'])
def test_malformed_story_operands_fail(bad):
    with pytest.raises(InvalidDocumentError):
        parse(drawing(textbox(bad)))


def test_malformed_binary_in_skipped_fallback_still_fails():
    with pytest.raises(InvalidDocumentError):
        parse(r'{\shprslt' + drawing(textbox(r'\bin9999 x')) + '}')


def test_bounds_and_separator_accounting():
    source = drawing(textbox('A') + textbox('B'))
    assert parse(source, max_text_chars=3).textboxes == 'A\nB'
    with pytest.raises(LimitExceededError):
        parse(source, max_text_chars=2)
    with pytest.raises(LimitExceededError):
        parse(STANDALONE, max_depth=2)
    with pytest.raises(LimitExceededError):
        parse(STANDALONE, max_records=2)
    with pytest.raises(LimitExceededError):
        parse(drawing(textbox(r'\trowd\cellx100\cellx200 A\cell B\cell\row')), max_cells=1)
    assert parse(drawing('NotText' * 1000 + textbox('OK')), max_text_chars=2).textboxes == 'OK'


def test_own_libreoffice_fixture(tmp_path):
    if os.environ.get('RTF_LEGACY_LO') != '1':
        pytest.skip('opt-in authored fixture oracle: RTF_LEGACY_LO=1')
    executable = shutil.which('libreoffice')
    assert executable, 'LibreOffice requested but unavailable'
    source = tmp_path / 'legacy.rtf'
    source.write_bytes(rtf('Before\\par' + STANDALONE + 'After\\par'))
    result = subprocess.run(
        [executable, '-env:UserInstallation=' + (tmp_path / 'profile').as_uri(),
         '--headless', '--convert-to', 'fodt', '--outdir', str(tmp_path), str(source)],
        env={**os.environ, 'SAL_USE_VCLPLUGIN': 'svp'},
        capture_output=True, text=True, timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    root = ET.parse(tmp_path / 'legacy.fodt')
    ns = {'draw': 'urn:oasis:names:tc:opendocument:xmlns:drawing:1.0',
          'text': 'urn:oasis:names:tc:opendocument:xmlns:text:1.0'}
    # Literal authored expectation, never generated by this parser.
    paragraphs = root.findall('.//draw:text-box//text:p', ns)
    assert [''.join(p.itertext()) for p in paragraphs] == ['Legacy', 'Second']
    assert parse(STANDALONE).textboxes == 'Legacy\nSecond'


@pytest.mark.parametrize('inside_text', [False, True])
@pytest.mark.parametrize('modern', [False, True])
@pytest.mark.parametrize('poison', [
    r'{\fonttbl{\f0\fcharset0 Injected;}}',
    r'{\fonttbl{\f1\cpg-1 Invalid;}}',
])
def test_drawing_font_table_cannot_change_global_fonts(inside_text, modern, poison):
    if modern:
        inner = r'{\shptxt ' + poison + r"\'cf}" if inside_text else poison
        drawing_source = r'{\shp{\*\shpinst ' + inner + '}}'
    else:
        inner = textbox(poison + r"\'cf") if inside_text else poison
        drawing_source = drawing(inner)
    result = parse(r'{\fonttbl{\f0\fcharset204 Cyrillic;}}\f0' +
                   r"\'cf" + drawing_source + r"\'cf")
    assert result.blocks == [Paragraph('ПП')]
    assert result.textboxes == ('П' if inside_text else '')


@pytest.mark.parametrize('source', [
    drawing(r'{\*\nesttableprops\trowd\cellx100 Bad\nestrow}'),
    r'{\shp{\*\nesttableprops\trowd\cellx100 Bad\nestrow}}',
])
def test_drawing_container_nested_properties_are_not_text_controls(source):
    result = parse('A' + source + 'B')
    assert result.blocks == [Paragraph('AB')]
    assert result.textboxes == ''


@pytest.mark.parametrize('destination', ['header', 'footer', 'footnote'])
@pytest.mark.parametrize('modern', [False, True])
def test_textbox_ancestry_blocks_secondary_story_injection(destination, modern):
    text = 'A{\\' + destination + ' Injected}B'
    source = (r'{\shp{\*\shpinst{\shptxt ' + text + '}}}' if modern
              else drawing(textbox(text)))
    result = parse(source)
    assert result.textboxes == 'AB'
    assert result.headers_footers == result.footnotes == result.endnotes == ''


@pytest.mark.parametrize('modern', [False, True])
def test_legacy_text_cannot_reopen_modern_shapes(modern):
    injected = r'{\shp{\*\shpinst{\shptxt Injected}}}' if modern else r'{\shptxt Injected}'
    result = parse(drawing(textbox('A' + injected + 'B')))
    assert result.textboxes == 'AB'


@pytest.mark.parametrize('primary', [
    r'{\shp{\*\shpinst{\shptxt A%sB}}}',
    r'{\shptxt A%sB}',
])
def test_modern_text_cannot_bypass_do_guard(primary):
    result = parse(primary % drawing(textbox('Injected')))
    assert result.textboxes == 'AB'
    assert result.blocks == []


def test_legacy_ancestry_restores_after_story_and_drawing_close():
    result = parse(drawing(textbox('One') + textbox('Two')) +
                   r'{\header Header}{\shp{\*\shpinst{\shptxt Modern}}}' +
                   drawing(textbox('Three')))
    assert result.textboxes == 'One\nTwo\nModern\nThree'
    assert result.headers_footers == 'Header'


def test_nested_table_properties_still_work_inside_legacy_text():
    text = (r'\trowd\cellx200\intbl Outer'
            r'\trowd\itap2\cellx100 Inner\nestcell'
            r'{\*\nesttableprops\trowd\itap2\cellx100\nestrow}'
            r'\itap1\cell\row')
    result = parse(drawing(textbox(text)))
    outer, = result.story_blocks['textboxes']
    assert isinstance(outer, Table)
    assert outer.rows[0][0].blocks == [Paragraph('Outer'), Table([[Cell('Inner')]])]
