"""Independent synthetic expectations; optional development-only LO comparison.

Run the external oracle explicitly with RTF_FIDELITY_LO=1. Normal tests need no
LibreOffice, network, downloaded documents or runtime parser dependency.
"""
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest

from legacy_office_parser.errors import InvalidDocumentError, LimitExceededError
from legacy_office_parser.limits import Limits
from legacy_office_parser.models import Cell, Paragraph, Table
from legacy_office_parser.rtf import parse_rtf_bytes


HORIZONTAL = (r'\trowd\clmgf\cellx2000\clmrg\cellx4000\cellx6000'
              r'\intbl Anchor\cell\cell Tail\cell\row')
VERTICAL = (r'\trowd\clvmgf\cellx2000\cellx4000\intbl Anchor\cell Top\cell\row'
            r'\trowd\clvmrg\cellx2000\cellx4000\intbl\cell Bottom\cell\row')
COMBINED = (r'\trowd\clmgf\clvmgf\cellx2000\clmrg\clvmgf\cellx4000\cellx6000'
            r'\intbl Anchor\cell\cell Top\cell\row'
            r'\trowd\clmgf\clvmrg\cellx2000\clmrg\clvmrg\cellx4000\cellx6000'
            r'\intbl\cell\cell Bottom\cell\row')
MERGE_TEXT = (r'\trowd\clmgf\cellx2000\clmrg\cellx4000'
              r'\intbl Anchor\cell Continuation\cell\row')
PLAIN = (r'Before\par\trowd\cellx2000\cellx4000\intbl Alpha\cell Beta\cell\row'
         r'\trowd\cellx2000\cellx4000\intbl Gamma\cell Delta\cell\row\pard After')
LATE = r'\intbl Alpha\cell Beta\cell\trowd\cellx2000\cellx4000\row\pard After'
SHAPE = (r'Before{\shp{\*\shpinst{\sp{\sn shapeType}{\sv 202}}}'
         r'{\shptxt ShapeText\par}}After')

SHAPE_STORY = (r'Before{\shp\shpleft0\shptop0\shpright4000\shpbottom2000'
               r'{\*\shpinst{\sp{\sn shapeType}{\sv 202}}'
               r'{\shptxt CanonicalText\par Second \u945?\par}}'
               r'{\shprslt{\do{\dptxbx{\dptxbxtext CanonicalText\par Second \u945?}}}}'
               r'}After')


def rtf(body):
    return ('{\\rtf1\\ansi ' + body + '}').encode('ascii')


def parse(body, **limits):
    return parse_rtf_bytes(rtf(body), Limits(**limits))


def test_horizontal_keeps_coordinates_and_surrounding_paragraphs():
    d = parse(r'Before\par' + HORIZONTAL + r'\pard After')
    assert d.blocks == [Paragraph('Before'), Table(rows=[[
        Cell('Anchor', col_span=2), Cell(covered=True), Cell('Tail')
    ]]), Paragraph('After')]
    assert not d.warnings


def test_vertical_and_combined_spans():
    assert parse(VERTICAL).blocks == [Table(rows=[
        [Cell('Anchor', row_span=2), Cell('Top')],
        [Cell(covered=True), Cell('Bottom')],
    ])]
    d = parse(COMBINED)
    assert d.blocks == [Table(rows=[
        [Cell('Anchor', row_span=2, col_span=2), Cell(covered=True), Cell('Top')],
        [Cell(covered=True), Cell(covered=True), Cell('Bottom')],
    ])]
    assert not d.warnings


def test_horizontal_continuation_text_is_not_dropped_or_duplicated():
    d = parse(MERGE_TEXT)
    assert d.blocks == [Table(rows=[[
        Cell('Anchor\nContinuation', col_span=2), Cell(covered=True)
    ]])]
    assert d.text.count('Continuation') == 1
    assert not d.warnings


def test_multiple_cell_paragraphs_unicode_and_field_result_survive_merge():
    d = parse(r'\trowd\clmgf\cellx100\clmrg\cellx200\intbl '
              r'\u945?\par First\cell '
              r'{\field{\*\fldinst ignored}{\fldrslt Visible}}\cell\row')
    assert d.blocks[0].rows[0] == [Cell('α\nFirst\nVisible', col_span=2), Cell(covered=True)]


def test_repeated_definitions_replace_merge_properties_before_row_ends():
    body = (r'\trowd\cellx100\cellx200\intbl A\cell B\cell'
            r'\trowd\clmgf\cellx100\clmrg\cellx200\row')
    assert parse(body).blocks[0].rows == [[Cell('A\nB', col_span=2), Cell(covered=True)]]
    reverse = (r'\trowd\clmgf\cellx100\clmrg\cellx200\intbl A\cell B\cell'
               r'\trowd\cellx100\cellx200\row')
    assert parse(reverse).blocks[0].rows == [[Cell('A'), Cell('B')]]


def test_three_row_vertical_chain_and_end():
    body = (r'\trowd\clvmgf\cellx100 A\cell\row'
            r'\trowd\clvmrg\cellx100\cell\row'
            r'\trowd\clvmrg\cellx100\cell\row'
            r'\trowd\cellx100 B\cell\row')
    assert parse(body).blocks[0].rows == [
        [Cell('A', row_span=3)], [Cell(covered=True)], [Cell(covered=True)], [Cell('B')]
    ]


@pytest.mark.parametrize('middle', [
    r'\trowd\cellx100 M\cell\row',
    r'\pard Middle\par',
    r'\trowd\clvmrg\cellx200\cell\row',  # changed right edge
    r'\trowd\trleft50\clvmrg\cellx100\cell\row',  # changed left edge
])
def test_vertical_chain_cannot_cross_interruption_or_changed_geometry(middle):
    d = parse(r'\trowd\clvmgf\cellx100 A\cell\row' + middle +
              r'\trowd\clvmrg\cellx100\cell\row')
    assert d.blocks[0].rows[0][0] == Cell('A')
    assert not d.blocks[-1].rows[-1][0].covered
    assert any('Vertical merge' in w for w in d.warnings)


def test_nonempty_vertical_continuation_is_preserved_and_breaks_chain():
    d = parse(r'\trowd\clvmgf\cellx100 A\cell\row'
              r'\trowd\clvmrg\cellx100 B\cell\row'
              r'\trowd\clvmrg\cellx100\cell\row')
    assert d.blocks[0].rows == [[Cell('A')], [Cell('B')], [Cell()]]
    assert any('nonempty' in w for w in d.warnings)


@pytest.mark.parametrize('definitions', [
    r'\clmrg\cellx100\cellx200',  # orphan continuation
    r'\clmgf\cellx200\clmrg\cellx100',  # non-monotonic grid
    r'\clmgf\cellx100\clmrg\cellx100',  # zero-width cell
    r'\clmgf\cellx100\clmrg\cellx',  # missing boundary
    r'\clmgf\clvmgf\cellx100\clmrg\cellx200',  # conflicting vertical flags
])
def test_ambiguous_definitions_keep_text_and_unmerged_coordinates(definitions):
    d = parse(r'\trowd' + definitions + r' A\cell B\cell\row')
    assert d.blocks[0].rows == [[Cell('A'), Cell('B')]]
    assert any('Merged' in w for w in d.warnings)


def test_recovery_and_nested_rows_do_not_guess_merges():
    d = parse(r'\trowd\clmgf\cellx100\clmrg\cellx200 A\cell\row')
    assert d.blocks[0].rows == [[Cell('A'), Cell()]]
    d = parse(r'\trowd\clmgf\cellx100\clmrg\cellx200 A\cell B\cell')
    assert d.blocks[0].rows == [[Cell('A'), Cell('B')]]
    d = parse(r'\trowd\clmgf\cellx100\clmrg\cellx200\itap2 A\cell B\cell\row')
    assert d.blocks[0].rows == [[Cell('A'), Cell('B')]]
    assert any('Nested' in w for w in d.warnings)


def test_merge_state_isolated_between_stories():
    d = parse(r'\trowd\clvmgf\cellx100 A\cell\row'
              r'{\header\trowd\clvmrg\cellx100 H\cell\row}'
              r'\trowd\clvmrg\cellx100\cell\row')
    assert d.blocks[0].rows == [[Cell('A', row_span=2)], [Cell(covered=True)]]
    assert d.headers_footers == 'H'
    assert parse('{\\header ' + MERGE_TEXT + '}').headers_footers == 'Anchor\nContinuation\t'


def test_merge_separators_and_definitions_obey_limits():
    assert parse(MERGE_TEXT, max_text_chars=19).blocks[0].rows[0][0].text == 'Anchor\nContinuation'
    with pytest.raises(LimitExceededError):
        parse(MERGE_TEXT, max_text_chars=18)
    with pytest.raises(LimitExceededError):
        parse(HORIZONTAL, max_cells=2)
    with pytest.raises(LimitExceededError):
        parse(r'\trowd\cellx100\cellx200 A\cell B\cell'
              r'\trowd\clmgf\cellx100\clmrg\cellx200\row', max_cells=3)


def test_plain_and_late_defined_tables_preserve_all_text():
    assert parse(PLAIN).blocks == [Paragraph('Before'), Table(rows=[
        [Cell('Alpha'), Cell('Beta')], [Cell('Gamma'), Cell('Delta')]
    ]), Paragraph('After')]
    assert parse(LATE).blocks == [Table(rows=[[Cell('Alpha'), Cell('Beta')]]), Paragraph('After')]


def test_libreoffice_development_oracle(tmp_path):
    """Compare independent markers and physical spans, not whitespace rendering.

    LO collapses columns merged in every row, so H/combined cases also contain
    an ordinary grid row to make their colspans explicit in the exported ODF.
    """
    if os.environ.get('RTF_FIDELITY_LO') != '1':
        pytest.skip('opt-in development oracle: RTF_FIDELITY_LO=1')
    executable = shutil.which('libreoffice')
    if not executable:
        pytest.fail('RTF_FIDELITY_LO requested but libreoffice is unavailable')
    grid = r'\trowd\cellx2000\cellx4000\cellx6000\intbl X\cell Y\cell Z\cell\row'
    cases = {'horizontal': HORIZONTAL + grid, 'vertical': VERTICAL,
             'combined': COMBINED + grid, 'merge_text': MERGE_TEXT,
             'plain': PLAIN, 'late': LATE, 'shape': SHAPE, 'shape_story': SHAPE_STORY}
    for name, body in cases.items():
        (tmp_path / (name + '.rtf')).write_bytes(rtf(body))
    result = subprocess.run(
        [executable, '-env:UserInstallation=' + (tmp_path / 'profile').as_uri(),
         '--headless', '--convert-to', 'fodt', '--outdir', str(tmp_path),
         *[str(tmp_path / (name + '.rtf')) for name in cases]],
        env={**os.environ, 'SAL_USE_VCLPLUGIN': 'svp'},
        capture_output=True, text=True, timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    ns = {'t': 'urn:oasis:names:tc:opendocument:xmlns:table:1.0',
          'x': 'urn:oasis:names:tc:opendocument:xmlns:text:1.0'}
    expected = {'horizontal': ['Anchor', 'Tail', 'X', 'Y', 'Z'],
                'vertical': ['Anchor', 'Top', 'Bottom'],
                'combined': ['Anchor', 'Top', 'Bottom', 'X', 'Y', 'Z'],
                'merge_text': ['Anchor', 'Continuation'],
                'plain': ['Before', 'Alpha', 'Beta', 'Gamma', 'Delta', 'After'],
                'late': ['Alpha', 'Beta', 'After']}
    for name, body in cases.items():
        root = ET.parse(tmp_path / (name + '.fodt'))
        paragraphs = [''.join(e.itertext()) for e in root.findall('.//x:p', ns)]
        if name in {'shape', 'shape_story'}:
            # Count only textbox paragraphs: outer body itertext includes nested
            # drawing text too and would itself double-count the same XML nodes.
            box_ns = {'draw': 'urn:oasis:names:tc:opendocument:xmlns:drawing:1.0', **ns}
            boxes = [''.join(e.itertext()) for e in
                     root.findall('.//draw:text-box//x:p', box_ns)]
            wanted = ['ShapeText'] if name == 'shape' else ['CanonicalText', 'Second α']
            assert boxes == wanted
            document = parse(body)
            assert document.blocks == [Paragraph('BeforeAfter')]
            assert document.textboxes == '\n'.join(wanted)
            for text in wanted:
                assert document.text.count(text) == 1
            continue
        assert [p for p in paragraphs if p] == expected[name]
        document = parse(body)
        for marker in expected[name]:
            assert document.text.count(marker) == 1
        first = root.find('.//t:table-cell', ns)
        if name in {'horizontal', 'combined'}:
            assert first.get('{%s}number-columns-spanned' % ns['t']) == '2'
            assert document.blocks[0].rows[0][0].col_span == 2
        if name in {'vertical', 'combined'}:
            assert first.get('{%s}number-rows-spanned' % ns['t']) == '2'
            assert document.blocks[0].rows[0][0].row_span == 2


def shape_story(text):
    return r'{\shp{\*\shpinst{\sp{\sn shapeType}{\sv 202}}{\shptxt ' + text + '}}}'


def test_shape_text_restores_proven_loss_and_canonical_nested_story():
    assert parse(SHAPE).textboxes == 'ShapeText'
    d = parse(SHAPE_STORY)
    assert d.blocks == [Paragraph('BeforeAfter')]
    assert d.textboxes == 'CanonicalText\nSecond α'
    assert d.text.count('CanonicalText') == 1
    assert 'Shape drawing and layout omitted.' in d.warnings


def test_shape_containers_do_not_emit_properties_or_stray_controls():
    d = parse(r'A{\shp stray\par\trowd\cellx100\cell\row'
              r'{\*\shpinst stray{\sp{\sn Name}{\sv Value}}'
              r'{\shptxt Visible}trailer}}B')
    assert d.blocks == [Paragraph('AB')]
    assert d.textboxes == 'Visible'


@pytest.mark.parametrize('destination', [
    r'\pict', r'\object', r'\shprslt', r'\sp', r'\sn', r'\sv',
    r'\*\unknown', r'\background',
])
def test_shape_story_never_reopens_skipped_parent(destination):
    d = parse('A{' + destination + ' ' + shape_story('Excluded') + '}B')
    assert d.text == 'AB'
    assert d.textboxes == ''


def test_shape_fallback_before_or_after_primary_is_always_suppressed():
    fallback = r'{\shprslt Fallback{\shptxt Duplicate}{\fldrslt Extra}}'
    primary = r'{\*\shpinst{\shptxt Once}}'
    for body in [fallback + primary, primary + fallback]:
        assert parse(r'{\shp' + body + '}').text == 'Once'
    # A fallback-only drawing is not a supported text story.
    assert parse(r'A{\shp' + fallback + '}B').text == 'AB'


def test_grouped_and_linked_shape_stories_keep_input_order_without_deduping_text():
    d = parse(r'{\shpgrp' + shape_story('Same') + r'{\shpgrp' +
              shape_story('Same') + r'}{\shp\shplid2{\*\shpinst}}}')
    assert d.textboxes == 'Same\nSame'
    assert d.blocks == []


def test_shape_story_preserves_fields_unicode_and_hidden_text_policy():
    d = parse(shape_story(r"\ansicpg1251 \'cf\u945?\u-10179?\u-8704?"
                          r'{\field{\*\fldinst Omitted}{\fldrslt Link}}'
                          r'{\v Hidden}{\deleted Deleted}\par Next'))
    assert d.textboxes == 'Пα😀Link\nNext'
    assert parse(r'{\v ' + shape_story('Hidden') + '}Visible').text == 'Visible'
    assert parse(r'{\deleted ' + shape_story('Deleted') + '}Visible').text == 'Visible'


def test_shape_story_isolated_from_body_table_and_header():
    d = parse(r'\trowd\cellx100 A' + shape_story(HORIZONTAL) + r'B\cell\row'
              r'{\header H' + shape_story('HeaderBox') + 'T}')
    assert d.blocks == [Table(rows=[[Cell('AB')]])]
    assert d.headers_footers == 'HT'
    assert d.textboxes == 'Anchor\t\tTail\nHeaderBox'


def test_shape_binary_is_opaque_even_when_it_contains_fake_story_syntax():
    payload = b'{\\shptxt NotText}\\par\x00\xff'
    data = (b'{\\rtf1 A{\\shp{\\*\\shpinst\\bin' + str(len(payload)).encode() + b' ' +
            payload + b'{\\shptxt Real{\\pict\\bin' + str(len(payload)).encode() + b' ' +
            payload + b'}Text}}}B}')
    d = parse_rtf_bytes(data, Limits())
    assert d.blocks == [Paragraph('AB')]
    assert d.textboxes == 'RealText'


def test_shape_limits_charge_stories_and_separators_but_not_properties():
    assert parse(shape_story('abc'), max_text_chars=3).textboxes == 'abc'
    with pytest.raises(LimitExceededError):
        parse(shape_story('abcd'), max_text_chars=3)
    with pytest.raises(LimitExceededError):
        parse(shape_story('a') + shape_story('b'), max_text_chars=2)
    with pytest.raises(LimitExceededError):
        parse(shape_story(r'a\par b'), max_text_chars=2)
    with pytest.raises(LimitExceededError):
        parse(shape_story(HORIZONTAL), max_cells=2)
    assert parse(r'{\shp{\*\shpinst{\sp{\sv ' + 'x' * 5000 +
                 r'}}{\shptxt ok}}}', max_text_chars=2).textboxes == 'ok'


@pytest.mark.parametrize('limits', [{'max_depth': 3}, {'max_records': 8}])
def test_shape_traversal_obeys_structural_limits(limits):
    with pytest.raises(LimitExceededError):
        parse(shape_story('Text'), **limits)


def test_shape_skipping_does_not_accept_truncated_binary():
    with pytest.raises(InvalidDocumentError):
        parse(r'{\shp{\*\shpinst{\sp{\sv\bin100 x}}}}')


def test_shape_story_surrogates_cannot_join_across_story_boundary():
    d = parse(r'\uc0\u55357' + shape_story('Box') + r'\u56832')
    assert d.blocks == [Paragraph('\ufffd\ufffd')]
    assert d.textboxes == 'Box'
