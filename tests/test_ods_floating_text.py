"""Public sheet drawings contract and passive ODS extraction budgets."""
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

from legacy_office_parser import Limits, LimitExceededError, parse_ods
from legacy_office_parser.api import _validate_result
from legacy_office_parser.models import Document, Sheet, SpreadsheetCell
from legacy_office_parser.odf import _Parser, parse_odf_bytes
from test_ods_floating_research import fixture, expected
from test_odf_inline_objects import p, embedded, PREVIEW
from test_odf_passive_research import package


def shape(body, kind='rect'):
    return f'<draw:{kind}>' + body + f'</draw:{kind}>'


def frame(body):
    return '<draw:frame>' + body + '</draw:frame>'


def box(body):
    return '<draw:text-box>' + body + '</draw:text-box>'


def sheet(drawings='', cells='', name='S'):
    return f'<table:table table:name="{name}"><table:shapes>' + drawings + '</table:shapes>' + cells + '</table:table>'


def repeated(rows=1, columns=1, text='cell'):
    return (f'<table:table-row table:number-rows-repeated="{rows}">'
            f'<table:table-cell table:number-columns-repeated="{columns}" office:value-type="string">' +
            p(text) + '</table:table-cell></table:table-row>')


def parse(body, limits=None):
    return parse_ods(package('spreadsheet', body), limits=limits or Limits())


def test_proven_fixture_public_contract():
    source = Path(__file__).parent / 'fixtures/ods_drawings/floating.ods'
    with ZipFile(source) as persisted, ZipFile(BytesIO(fixture())) as generated:
        assert {n: persisted.read(n) for n in persisted.namelist()} == {
            n: generated.read(n) for n in generated.namelist()}
    doc = parse_ods(source)
    oracle = expected()
    projected = []
    for item in doc.sheets:
        want = oracle[item.name]
        assert item.drawings == [d['text'] for d in want['drawings']]
        assert len(item.cells) == 1
        assert item.cells[0].address == 'A1'
        assert item.cells[0].text == item.cells[0].value == want['cell']
        assert (item.rows, item.columns, item.merges) == (1, 1, [])
        projected.append('\n'.join([item.name, 'A1\t' + want['cell']] + item.drawings))
    assert doc.text == '\n\n'.join(projected)
    assert doc.to_dict()['sheets'][0]['drawings'] == doc.sheets[0].drawings
    assert not doc.textboxes and not doc.story_blocks
    assert not doc.warnings


@pytest.mark.parametrize('fmt', ['ods', 'xls'])
def test_empty_field_serialization_and_legacy_text(fmt):
    doc = Document(fmt, sheets=[Sheet('S', [SpreadsheetCell(1, 1, text='cell')])])
    assert doc.text == 'S\nA1\tcell'
    assert 'drawings' not in doc.to_dict()['sheets'][0]
    doc.sheets[0].drawings = ['same', '', 'same']
    assert doc.text == 'S\nA1\tcell\nsame\nsame'


@pytest.mark.parametrize('kind', ['rect', 'ellipse', 'custom-shape', 'text-box'])
def test_allowed_text_and_ignored_metadata(kind):
    good = p('A<text:span>B</text:span><text:s text:c="2"/><text:tab/><text:line-break/>C')
    good += '<text:list><text:list-item>' + p('list') + '</text:list-item></text:list>'
    decoys = ('<svg:desc>' + p('desc') + '</svg:desc><draw:enhanced-geometry>' + p('geometry') +
              '</draw:enhanced-geometry><office:event-listeners>' + p('script') + '</office:event-listeners>' +
              '<text:section>' + p('section') + '</text:section>' + embedded(p('object')))
    drawing = frame(box(good + decoys)) if kind == 'text-box' else shape(good + decoys, kind)
    doc = parse(sheet(drawing))
    assert doc.sheets[0].drawings == ['AB  \t\nC\nlist']
    assert doc.sheets[0].cells == []


@pytest.mark.parametrize('first', [box(p('first')), box('')])
def test_frame_first_supported_even_empty(first):
    doc = parse(sheet(frame(PREVIEW + embedded(p('object')) + first + box(p('fallback')))))
    assert doc.sheets[0].drawings == (['first'] if 'first' in first else [])


def test_empty_whitespace_and_duplicate_drawings():
    doc = parse(sheet(shape('') + shape(p('')) + shape(p('<text:s/>')) + shape(p('x')) * 2))
    assert doc.sheets[0].drawings == [' ', 'x', 'x']
    assert doc.text == 'S\n \nx\nx'


def test_sheet_drawings_do_not_repeat_with_rows_or_columns():
    doc = parse(sheet(shape(p('drawing')), repeated(2, 3)))
    assert doc.sheets[0].drawings == ['drawing']
    assert len(doc.sheets[0].cells) == 6
    assert all(c.text == c.value == 'cell' for c in doc.sheets[0].cells)
    assert doc.text.count('drawing') == 1


def test_two_sheets_preserve_owner_and_source_order():
    doc = parse(sheet(shape(p('B')) + shape(p('A')), name='first') + sheet(shape(p('B')), name='second'))
    assert doc.text == 'first\nB\nA\n\nsecond\nB'


def test_drawing_aggregate_and_visible_separators_exact_budget():
    data = package('spreadsheet', sheet(shape(p('<text:s text:c="1000"/>')) * 2))
    for entry in (parse_ods, lambda data, limits: parse_odf_bytes(data, limits)):
        doc = entry(data, limits=Limits(max_text_chars=2003))
        assert len(doc.text) == 2003
        with pytest.raises(LimitExceededError):
            entry(data, limits=Limits(max_text_chars=2002))


def test_repeated_cells_projection_preflight_before_allocation(monkeypatch):
    import legacy_office_parser.odf as odf
    data = package('spreadsheet', sheet(shape(p('drawing')), repeated(1000, 1, 'x')))
    # Allocation text cost ~2000; addresses and separators exceed 6000.
    def unexpected(*args, **kwargs):
        pytest.fail('repeated cells allocated before rendered size preflight')
    monkeypatch.setattr(odf, 'SpreadsheetCell', unexpected)
    with pytest.raises(LimitExceededError, match='rendered text'):
        parse_ods(data, limits=Limits(max_text_chars=4000))


def test_public_drawing_records_and_projection_budgets():
    doc = Document('ods', sheets=[Sheet('S', drawings=['x']), Sheet('T', drawings=['y'])])
    with pytest.raises(LimitExceededError, match='record'):
        _validate_result(doc, Limits(max_records=1))
    assert len(doc.text) == 8
    _validate_result(doc, Limits(max_text_chars=8))
    with pytest.raises(LimitExceededError, match='rendered'):
        _validate_result(doc, Limits(max_text_chars=7))
    with pytest.raises(LimitExceededError, match='size'):
        _validate_result(doc, Limits(max_text_chars=3))


def test_coordinate_band_preflight_matches_actual_addresses():
    for row, rows, col, cols in [(9, 3, 25, 4), (98, 4, 701, 4), (999, 2, 16383, 2)]:
        expected_size = sum(len(SpreadsheetCell(r, c).address)
                            for r in range(row, row + rows) for c in range(col, col + cols))
        assert _Parser.cell_address_size(row, rows, col, cols) == expected_size


def test_private_collector_records_accumulate_across_sheets():
    from xml.etree import ElementTree as ET
    from legacy_office_parser._odf_package import Budget
    from test_odf_inline_objects import DECL
    parser = _Parser(Document('ods'), Budget(Limits(max_records=1)), ())
    source = ET.fromstring(f'<table:shapes {DECL}>' + shape(p('label')) + '</table:shapes>')
    first, second = Sheet('one'), Sheet('two')
    parser.sheet_drawings(source, first)
    with pytest.raises(LimitExceededError, match='drawing record'):
        parser.sheet_drawings(source, second)
    assert first.drawings == ['label']
    assert second.drawings == []


def test_drawing_characters_are_shared_across_sheets():
    body = sheet(shape(p('<text:s text:c="1000"/>')), name='A')
    body += sheet(shape(p('<text:s text:c="1000"/>')), name='B')
    doc = parse(body, Limits(max_text_chars=2006))
    assert len(doc.text) == 2006
    with pytest.raises(LimitExceededError):
        parse(body, Limits(max_text_chars=2005))


def test_expanded_drawing_paragraph_limit():
    with pytest.raises(LimitExceededError):
        parse(sheet(shape(p('<text:s text:c="100000"/>'))), Limits(max_text_chars=2000))


def test_cell_hosted_drawing_behavior_is_unchanged():
    row = '<table:table-row><table:table-cell>' + frame(box(p('cell-hosted'))) + '</table:table-cell></table:table-row>'
    doc = parse(sheet(shape(p('floating')), row))
    assert doc.sheets[0].cells[0].text == 'cell-hosted'
    assert doc.sheets[0].drawings == ['floating']


def test_unproven_drawing_containers_and_table_content_are_not_scraped():
    unsupported = '<draw:g>' + shape(p('group')) + '</draw:g>'
    unsupported += '<draw:a>' + shape(p('link')) + '</draw:a>'
    unsupported += frame(box('<table:table><table:table-row><table:table-cell>' + p('table') +
                             '</table:table-cell></table:table-row></table:table>'))
    doc = parse(sheet(unsupported + shape(p('allowed'))))
    assert doc.sheets[0].drawings == ['allowed']
