"""Independent nested-RTF expectations; LO is only an opt-in external oracle."""
import os
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest

from legacy_office_parser.errors import InvalidDocumentError, LimitExceededError
from legacy_office_parser.limits import Limits
from legacy_office_parser.models import Cell, Paragraph, Table
from legacy_office_parser.rtf import parse_rtf_bytes

FIXTURES = Path(__file__).parent / 'fixtures' / 'rtf_nested'


def parse(body, **limits):
    return parse_rtf_bytes(('{\\rtf1 ' + body + '}').encode(), Limits(**limits))


def nested(text='N', props=r'\cellx100'):
    return (r'\pard\intbl\itap2 ' + text + r'\nestcell'
            r'{\*\nesttableprops\trowd' + props + r'\nestrow}')


def outer(body):
    return r'\trowd\cellx1000\intbl ' + body + r'\pard\intbl\itap1\cell\row'


def test_own_fixture_exact_hierarchy_projection_and_json():
    d = parse_rtf_bytes((FIXTURES / 'own_nested.rtf').read_bytes(), Limits())
    inner = Table([[Cell('InnerA'), Cell('InnerB')], [Cell('InnerC'), Cell('InnerD')]])
    projection = 'OuterBefore\nInnerA\tInnerB\nInnerC\tInnerD\nOuterAfter'
    assert d.blocks == [Paragraph('Before'), Table([[
        Cell(projection, blocks=[Paragraph('OuterBefore'), inner, Paragraph('OuterAfter')]),
        Cell('Sibling')]]), Paragraph('After')]
    assert not d.warnings
    assert d.text == 'Before\n\n' + projection + '\tSibling\n\nAfter'
    cells = d.to_dict()['blocks'][1]['rows'][0]
    assert 'blocks' in cells[0] and 'blocks' not in cells[1]
    assert 'blocks' not in cells[0]['blocks'][1]['rows'][0][0]


def test_three_levels_and_group_scoped_depth():
    body = outer(r'Before\par' + nested(
        r'Middle\par{\itap3 Deep\nestcell'
        r'{\*\nesttableprops\trowd\cellx50\nestrow}}Tail') +
        r'\pard\intbl After')
    d = parse(body)
    c = d.blocks[0].rows[0][0]
    assert c.text == 'Before\nMiddle\nDeep\nTail\nAfter'
    inner = c.blocks[1].rows[0][0]
    assert inner.blocks == [Paragraph('Middle'), Table([[Cell('Deep')]]), Paragraph('Tail')]
    assert not d.warnings


def test_nested_tables_in_two_cells_do_not_coalesce():
    d = parse(r'\trowd\cellx1000\cellx2000' + nested('A') +
              r'\pard\intbl\cell' + nested('B') + r'\pard\intbl\cell\row')
    cells = d.blocks[0].rows[0]
    assert [c.text for c in cells] == ['A', 'B']
    assert [c.blocks for c in cells] == [[Table([[Cell('A')]])], [Table([[Cell('B')]])]]


def test_two_nested_tables_separated_by_paragraph():
    d = parse(outer(nested('A') + r'\pard\intbl Between\par' + nested('B')))
    assert d.blocks[0].rows[0][0].blocks == [
        Table([[Cell('A')]]), Paragraph('Between'), Table([[Cell('B')]])]


def test_unicode_fields_empty_cells_and_fallback_are_not_duplicated():
    d = parse(outer(nested(r'\u945?{\field{\*\fldinst Ignore}{\fldrslt Link}}'
                           r'\nestcell', r'\cellx50\cellx100') +
                    r'{\nonesttables Duplicate}'))
    c = d.blocks[0].rows[0][0]
    assert c.text == 'αLink\t'
    assert c.blocks == [Table([[Cell('αLink'), Cell()]])]


def test_outer_repeated_properties_and_inner_merges_are_isolated():
    d = parse(outer(nested(r'A\nestcell B', r'\clmgf\cellx50\clmrg\cellx100') +
                    r'\trowd\cellx1000'))
    c = d.blocks[0].rows[0][0]
    assert c.text == 'A\nB\t'
    assert c.blocks == [Table([[Cell('A\nB', col_span=2), Cell(covered=True)]])]
    assert not d.warnings


def test_nested_merge_on_parent_is_conservatively_preserved():
    d = parse(r'\trowd\clmgf\cellx1000\clmrg\cellx2000' + nested('N') +
              r'\pard\intbl\cell Tail\cell\row')
    assert [c.text for c in d.blocks[0].rows[0]] == ['N', 'Tail']
    assert d.blocks[0].rows[0][0].blocks == [Table([[Cell('N')]])]
    assert any('Merged' in w for w in d.warnings)


@pytest.mark.parametrize('body', [r'\itap-1 X', r'\itap X', r'\nestcell', r'\nestrow',
                                   r'{\*\nesttableprops\trowd\nestrow}',
                                   r'\itap2 X', r'\trowd\cellx100\itap3 X'])
def test_malformed_depth_is_structured_error(body):
    with pytest.raises(InvalidDocumentError):
        parse(body)


def test_depth_limit_independent_of_brace_depth():
    with pytest.raises(LimitExceededError):
        parse(r'\trowd\cellx100\itap4 X', max_depth=3)


def test_all_nested_and_padding_cells_count_towards_budget():
    body = outer(nested('N', r'\cellx50\cellx100'))
    assert parse(body, max_cells=3).blocks[0].rows[0][0].text == 'N\t'
    with pytest.raises(LimitExceededError):
        parse(body, max_cells=2)


def test_projection_copy_and_separators_count_towards_budget():
    body = outer(nested('abc'))
    assert parse(body, max_text_chars=6).text == 'abc'
    with pytest.raises(LimitExceededError):
        parse(body, max_text_chars=5)
    body = outer(nested(r'A\nestcell B', r'\cellx50\cellx100'))
    assert parse(body, max_text_chars=5).text == 'A\tB'
    with pytest.raises(LimitExceededError):
        parse(body, max_text_chars=4)


def test_clashing_nested_properties_warn_and_retain_every_cell():
    body = outer(r'\itap2 A\nestcell B\nestcell'
                 r'{\*\nesttableprops\trowd\cellx50\cellx100'
                 r'\trowd\cellx200\nestrow}')
    d = parse(body)
    assert d.text == 'A\tB'
    assert any('Conflicting' in w for w in d.warnings)
    assert any('count differs' in w for w in d.warnings)


def test_incomplete_nested_row_recovers_with_warning_and_hierarchy():
    d = parse(outer(r'\itap2 Kept'))
    assert d.blocks[0].rows[0][0].blocks == [Table([[Cell('Kept')]])]
    assert any('Nested' in w for w in d.warnings)


def test_story_and_skipped_destinations_do_not_leak_depth_or_text():
    d = parse(outer(nested('Body')) + r'{\header ' + outer(nested('Header')) + '}'
              r'{\*\unknown\itap99 Bad\nestrow}')
    assert d.blocks[0].rows[0][0].text == 'Body'
    assert d.headers_footers == 'Header'
    assert 'Bad' not in d.text


def test_libreoffice_own_fixture_hierarchy(tmp_path):
    if os.environ.get('RTF_NESTED_LO') != '1':
        pytest.skip('opt-in development oracle: RTF_NESTED_LO=1')
    executable = shutil.which('libreoffice')
    assert executable, 'LibreOffice required for requested oracle'
    result = subprocess.run([
        executable, '-env:UserInstallation=' + (tmp_path / 'profile').as_uri(),
        '--headless', '--convert-to', 'fodt', '--outdir', str(tmp_path),
        str(FIXTURES / 'own_nested.rtf')],
        env={**os.environ, 'SAL_USE_VCLPLUGIN': 'svp'},
        capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    root = ET.parse(tmp_path / 'own_nested.fodt')
    ns = {'t': 'urn:oasis:names:tc:opendocument:xmlns:table:1.0',
          'x': 'urn:oasis:names:tc:opendocument:xmlns:text:1.0'}
    tables = root.findall('.//t:table', ns)
    assert len(tables) == 2
    outer_cell = tables[0].find('t:table-row/t:table-cell', ns)
    assert outer_cell.find('t:table', ns) is tables[1]
    rows = tables[1].findall('t:table-row', ns)
    assert [[ ''.join(c.itertext()).strip() for c in r.findall('t:table-cell', ns)]
            for r in rows] == [['InnerA', 'InnerB'], ['InnerC', 'InnerD']]
    paragraphs = [''.join(e.itertext()) for e in root.findall('.//x:p', ns)]
    assert [p for p in paragraphs if p] == [
        'Before', 'OuterBefore', 'InnerA', 'InnerB', 'InnerC', 'InnerD',
        'OuterAfter', 'Sibling', 'After']


def test_line_breaks_are_not_mistaken_for_paragraph_terminators():
    d = parse(outer(r'Before\line' + nested('N') + r'\pard\intbl After\line'))
    c = d.blocks[0].rows[0][0]
    assert c.blocks == [Paragraph('Before\n'), Table([[Cell('N')]]), Paragraph('After\n')]
    assert c.text == 'Before\n\nN\nAfter\n'


def test_empty_nested_cell_is_valid_and_counted():
    d = parse(outer(nested('')))
    assert d.blocks[0].rows[0][0].blocks == [Table([[Cell()]])]
    assert not d.warnings
    with pytest.raises(LimitExceededError):
        parse(outer(nested('')), max_cells=1)


def test_public_output_separators_are_bounded_with_empty_nested_cells():
    body = outer(nested('')) + r'\pard A\par B'
    assert parse(body, max_text_chars=4).text == 'A\n\nB'
    with pytest.raises(LimitExceededError):
        parse(body, max_text_chars=3)


def test_conflicting_properties_cannot_be_hidden_by_third_repeat():
    d = parse(outer(r'\itap2 A\nestcell{\*\nesttableprops'
                    r'\trowd\cellx100\trowd\cellx200\trowd\cellx200\nestrow}'))
    assert d.text == 'A'
    assert any('Conflicting' in w for w in d.warnings)


def test_deep_tables_use_iterative_recovery_and_count_all_cells():
    depth = 1100
    body = r'\trowd\cellx100 A' + ''.join(r'\itap%d A' % i for i in range(2, depth + 1))
    d = parse(body, max_depth=depth)
    cell = d.blocks[0].rows[0][0]
    count = 1
    while cell.blocks:
        cell = cell.blocks[-1].rows[0][0]
        count += 1
    assert count == depth
    assert d.text.count('A') == depth
    with pytest.raises(LimitExceededError):
        parse(body, max_depth=depth, max_cells=depth - 1)


def test_libreoffice_exported_fixture_keeps_nested_markers_once():
    d = parse_rtf_bytes((FIXTURES / 'own_nested_lo.rtf').read_bytes(), Limits())
    cell = d.blocks[1].rows[0][0]
    assert cell.blocks == [Paragraph('OuterBefore'),
                          Table([[Cell('InnerA'), Cell('InnerB')],
                                 [Cell('InnerC'), Cell('InnerD')]]),
                          Paragraph('OuterAfter')]
    for marker in ['Before', 'InnerA', 'InnerB', 'InnerC', 'InnerD', 'Sibling']:
        # Before also occurs in OuterBefore, so compare tokenized projection.
        assert d.text.replace('\t', '\n').split('\n').count(marker) == 1
    # LO 7.4 emits an extra outer \\cell before \\row: retain the coordinate
    # and report it rather than silently dropping it to match the definition.
    assert d.blocks[1].rows[0][-1] == Cell()
    assert any('count differs' in w for w in d.warnings)


def test_empty_intermediate_parent_still_has_a_real_hierarchy():
    d = parse(outer(r'\itap2\itap3 Deep\nestcell'
                    r'{\*\nesttableprops\trowd\cellx50\nestrow}'
                    r'\itap2\nestcell{\*\nesttableprops\trowd\cellx100\nestrow}'))
    c = d.blocks[0].rows[0][0]
    assert c.text == 'Deep'
    assert c.blocks[0].rows[0][0].blocks == [Table([[Cell('Deep')]])]
    assert not d.warnings


@pytest.mark.parametrize('control', [r'\itap1', r'\pard', r'\cell', r'\row'])
def test_nested_properties_cannot_clobber_parent_with_wrong_depth(control):
    with pytest.raises(InvalidDocumentError):
        parse(outer(r'\itap2 A\nestcell{\*\nesttableprops' + control + '}'))


def test_surrogate_pairs_do_not_join_across_table_depth_change():
    d = parse(outer(r'\uc0\u55357' + nested(r'\u56832')))
    assert d.blocks[0].rows[0][0].text == '\ufffd\n\ufffd'
    assert any('surrogate' in w for w in d.warnings)


def test_outer_properties_can_also_follow_nested_content():
    d = parse(r'\intbl Before\par' + nested('N') +
              r'\pard\intbl After\cell\trowd\cellx1000\row')
    assert d.blocks == [Table([[Cell('Before\nN\nAfter', blocks=[
        Paragraph('Before'), Table([[Cell('N')]]), Paragraph('After')])]])]
    assert not d.warnings


def test_malformed_outer_terminator_keeps_recovered_child_instead_of_flattening():
    d = parse(r'\trowd\clmgf\cellx100\clmrg\cellx200\itap2 A\cell B\cell\row')
    assert d.blocks[0].rows == [[
        Cell('A', blocks=[Table([[Cell('A')]])]), Cell('B')]]
    assert d.text == 'A\tB'
    assert any('Nested' in w for w in d.warnings)
    assert any('Merged' in w for w in d.warnings)
