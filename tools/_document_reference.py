"""Privacy-safe comparison of Document with a LibreOffice DOCX ZipFile.

Only the standard library and the existing extraction model are required. No
conversion is run here, and the caller retains ownership of the open ZipFile.
Report values are counts, 1-based coordinates, booleans, null, or fixed status
strings; keys are fixed. Incomplete comparisons have root equal=None.

Text equality collapses Unicode whitespace to one space and strips its edges.
It preserves case, punctuation, word order and inline run adjacency. Consecutive
body paragraphs may differ in newline placement; table/cell boundaries may not.

Unsupported XML is never silently flattened. Equality is gated by completeness.
Headers/footers are reference-only part scopes: the model's pooled string cannot
be mapped to section/first/even/default stories. Textboxes are likewise unpaired.
Notes compare pooled text in XML order, not note identity or anchor positions.
Note tables use row-major text with explicit cell/row separators, not structure.
Omitted grid coordinates are absent, not empty or covered cells; the dense model
cannot express interior omissions. Legacy hMerge is unsupported. Cell tables compare recursively in reading order.
This is a developer oracle for trusted converted files, not a hardened ZIP reader.
"""
from __future__ import annotations

from collections import Counter
import re
import xml.etree.ElementTree as ET
from zipfile import BadZipFile
import zlib

from legacy_office_parser.models import Cell, Paragraph, Table

_W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
_INLINE = {'p', 'r', 'hyperlink', 'smartTag', 'sdt', 'sdtContent', 'fldSimple'}
_METADATA = {'pPr', 'rPr', 'sdtPr', 'sdtEndPr', 'bookmarkStart', 'bookmarkEnd',
             'proofErr', 'permStart', 'permEnd', 'commentRangeStart', 'commentRangeEnd',
             'commentReference', 'footnoteReference', 'endnoteReference', 'footnoteRef',
             'endnoteRef', 'fldChar', 'instrText', 'lastRenderedPageBreak'}


class _InvalidReference(Exception):
    """Internal sentinel; never propagate reference data into the report."""


def _read_part(archive, path, root_tag):
    try:
        root = ET.fromstring(archive.read(path))
    except (ET.ParseError, LookupError, BadZipFile, OSError, EOFError, ValueError,
            RuntimeError, NotImplementedError, zlib.error):
        raise _InvalidReference from None
    if root.tag != _W + root_tag:
        raise _InvalidReference
    return root


def _note_text(element, unsupported):
    if element.tag == _W + 'tbl':
        rows, widths = _table(element, unsupported, nested=False)
        return '\n'.join('\t'.join(row[c].text if c in row else ''
                                    for c in range(width))
                         for row, width in zip(rows, widths))
    if element.tag in {_W + 'sdt', _W + 'sdtContent'}:
        return '\n'.join(_note_text(child, unsupported) for child in element)
    return _text(element, unsupported)


def _normal(text):
    return ' '.join(text.split())


def _metric(actual, expected):
    return {'model_chars': len(actual), 'reference_chars': len(expected),
            'text_equal': _normal(actual) == _normal(expected)}


def _text(element, unsupported):
    tag = element.tag.removeprefix(_W)
    if element.tag == _W + 't':
        return element.text or ''
    if tag in {'tab', 'br', 'cr'}:
        return '\n'
    if tag in {'noBreakHyphen', 'softHyphen'}:
        return '\u2011' if tag == 'noBreakHyphen' else '\u00ad'
    if tag in _METADATA:
        return ''
    if tag not in _INLINE:
        # Fixed keys only: XML names/attributes may themselves contain private data.
        key = ('nested_tables' if tag == 'tbl' else
               'textboxes' if tag in {'drawing', 'pict', 'txbxContent'} else 'xml_scopes')
        unsupported[key] += 1
        return ''
    value = ''.join(_text(child, unsupported) for child in element)
    return value + ('\n' if tag == 'p' else '')


def _number(parent, path, default, unsupported, minimum=0):
    node = parent.find(path)
    if node is None:
        return default
    try:
        value = int(node.get(_W + 'val', ''))
        if not minimum <= value <= 16384:
            raise ValueError
        return value
    except ValueError:
        unsupported['invalid_grid'] += 1
        return default


class _ReferenceTable:
    def __init__(self, rows, widths, complete):
        self.rows = rows
        self.widths = widths
        self.complete = complete


def _projection(table):
    return '\n'.join('\t'.join(row[c].text if c in row else ''
                               for c in range(width))
                     for row, width in zip(table.rows, table.widths))


def _table(root, unsupported, nested=True):
    rows = []
    widths = []
    active = {}
    grid = root.find(_W + 'tblGrid')
    grid_width = len(grid.findall(_W + 'gridCol')) if grid is not None else 0
    for child in root:
        if child.tag not in {_W + 'tblPr', _W + 'tblGrid', _W + 'tr'}:
            unsupported['xml_scopes'] += 1
    for tr in root.findall(_W + 'tr'):
        col = _number(tr, f'{_W}trPr/{_W}gridBefore', 0, unsupported)
        after = _number(tr, f'{_W}trPr/{_W}gridAfter', 0, unsupported)
        cells = {}
        current = {}
        for tc in tr:
            if tc.tag == _W + 'trPr':
                continue
            if tc.tag != _W + 'tc':
                unsupported['xml_scopes'] += 1
                continue
            span = _number(tc, f'{_W}tcPr/{_W}gridSpan', 1, unsupported, 1)
            if tc.find(f'{_W}tcPr/{_W}hMerge') is not None:
                unsupported['horizontal_merge'] += 1
            pieces, blocks = [], []
            for item in tc:
                if item.tag == _W + 'tcPr':
                    continue
                if item.tag == _W + 'tbl' and nested:
                    local = Counter()
                    child_rows, child_widths = _table(item, local)
                    child = _ReferenceTable(child_rows, child_widths, not local)
                    unsupported.update(local)
                    blocks.append(child)
                    pieces.append(_projection(child))
                else:
                    value = _text(item, unsupported)
                    blocks.append(Paragraph(value))
                    pieces.append(value)
            value = '\n'.join(pieces)
            merge = tc.find(f'{_W}tcPr/{_W}vMerge')
            mode = merge.get(_W + 'val', 'continue') if merge is not None else ''
            key = (col, span)
            cell = Cell(value, col_span=span, blocks=blocks)
            if mode == 'continue':
                cell.covered = True
                cell.col_span = 1  # Spans belong to anchors, not covered coordinates.
                if key in active:
                    anchor = active[key]
                    anchor.row_span += 1
                    current[key] = anchor
                else:
                    unsupported['orphan_vertical_merge'] += 1
            elif mode == 'restart':
                current[key] = cell
            elif mode:
                unsupported['invalid_grid'] += 1
            cells[col] = cell
            for offset in range(1, span):
                cells[col + offset] = Cell(covered=True)
            col += span
        width = col + after
        if grid_width and width > grid_width:
            unsupported['invalid_grid'] += 1
        # A short row has absent trailing cells, never invented empty cells.
        widths.append(max(width, grid_width))
        rows.append(cells)
        active = current  # A missing continuation terminates a vertical merge.
    return rows, widths


def _segments(blocks):
    segments, tables = [''], []
    for block in blocks:
        if isinstance(block, (Table, _ReferenceTable)):
            tables.append(block)
            segments.append('')
        elif isinstance(block, Paragraph):
            segments[-1] += '\n' + block.text
    return segments, tables


def _table_check(model, reference, number, path=None):
    expected, widths, complete = reference.rows, reference.widths, reference.complete
    path = [number] if path is None else path
    nested_checks = []
    actual = [{i: c for i, c in enumerate(row)} for row in model.rows]
    mismatches = []
    for r in range(max(len(actual), len(expected))):
        left = actual[r] if r < len(actual) else {}
        right = expected[r] if r < len(expected) else {}
        for col in sorted(left.keys() | right.keys()):
            a, b = left.get(col), right.get(col)
            present = a is not None and b is not None
            check = {'row': r + 1, 'column': col + 1,
                     'model_present': a is not None, 'reference_present': b is not None,
                     'text_equal': present and _normal(a.text) == _normal(b.text),
                     'covered_equal': present and a.covered == b.covered,
                     'col_span_equal': present and a.col_span == b.col_span,
                     'row_span_equal': present and a.row_span == b.row_span}
            if present:
                # Empty blocks mean a simple cell, never inferred nested structure.
                a_segments, a_tables = _segments(a.blocks or [Paragraph(a.text)])
                b_segments, b_tables = _segments(b.blocks or [Paragraph(b.text)])
                children = [_table_check(x, y, i + 1, path + [r + 1, col + 1, i + 1])
                            for i, (x, y) in enumerate(zip(a_tables, b_tables))]
                nested_checks.extend(children)
                check['blocks_equal'] = (
                    len(a_tables) == len(b_tables) and
                    list(map(_normal, a_segments)) == list(map(_normal, b_segments)) and
                    all(child['equal'] is True for child in children))
            else:
                check['blocks_equal'] = False
            check['path'] = path + [r + 1, col + 1]
            if not all(check[k] for k in ('text_equal', 'covered_equal', 'blocks_equal',
                                          'col_span_equal', 'row_span_equal')):
                mismatches.append(check)
    dimensions = len(actual) == len(expected) and [len(r) for r in model.rows] == widths
    return {'number': number, 'path': path, 'nested_table_checks': nested_checks,
            'model_rows': len(actual), 'reference_rows': len(expected),
            'model_cells': sum(map(len, actual)), 'reference_cells': sum(map(len, expected)),
            'reference_omitted_cells': sum(widths) - sum(map(len, expected)),
            'dimensions_equal': dimensions, 'cell_mismatches': mismatches,
            'complete': complete, 'equal': (dimensions and not mismatches) if complete else None}


def _body(root, unsupported):
    # Segments between tables preserve table placement without insisting on the
    # same number of paragraph elements after LibreOffice reflows line breaks.
    segments, tables = [''], []
    for child in root:
        if child.tag == _W + 'tbl':
            local = Counter()
            rows, widths = _table(child, local)
            tables.append(_ReferenceTable(rows, widths, not local))
            unsupported.update(local)
            segments.append('')
        elif child.tag == _W + 'sectPr':
            continue
        else:
            segments[-1] += '\n' + _text(child, unsupported)
    return segments, tables


def _model_counts(blocks, unsupported):
    tables = cells = 0
    pending = list(blocks)
    while pending:
        block = pending.pop()
        if isinstance(block, Table):
            tables += 1
            for row in block.rows:
                for cell in row:
                    cells += 1
                    pending.extend(cell.blocks)
        elif not isinstance(block, Paragraph):
            unsupported['model_blocks'] += 1
    return tables, cells


def _reference_counts(tables):
    count = cells = 0
    pending = list(tables)
    while pending:
        table = pending.pop()
        count += 1
        for row in table.rows:
            for cell in row.values():
                cells += 1
                pending.extend(b for b in cell.blocks if isinstance(b, _ReferenceTable))
    return count, cells


def _compare_document(doc, zipfile) -> dict:
    """Compare DOC/RTF/ODT Document with an open DOCX ZipFile, without text leaks.

    ``body.equal`` covers ordered body text and tables only. ``equal`` additionally
    requires equal notes and no unsupported scopes anywhere. Inspect ``complete``
    before interpreting partial text metrics. No XML, filenames, hashes, model
    warnings, note IDs or exception messages are copied to the report.

    Table paths are [body_table, row, column, nested_table, ...], all 1-based;
    cell mismatch paths append row and column. Nested table ordinals are local
    to the containing cell. body total counts include every nested/covered cell;
    existing model_tables/reference_tables and per-table counts remain local.
    Consecutive cell paragraphs normalize like body paragraphs, while intervening
    tables and their row/cell boundaries must match recursively.
    """
    if doc.format not in {'doc', 'rtf', 'odt'}:
        raise ValueError('Unsupported document format')
    unsupported = Counter()
    root = _read_part(zipfile, 'word/document.xml', 'document')
    bodies = root.findall(_W + 'body')
    if len(bodies) != 1:
        raise _InvalidReference
    body = bodies[0]
    segments, tables = _body(body, unsupported)
    actual_segments, actual_tables = [''], []
    for block in doc.blocks:
        if isinstance(block, Table):
            actual_tables.append(block)
            actual_segments.append('')
        elif isinstance(block, Paragraph):
            actual_segments[-1] += '\n' + block.text
    model_count, model_cells = _model_counts(doc.blocks, unsupported)
    reference_count, reference_cells = _reference_counts(tables)
    checks = [_table_check(a, b, i + 1)
              for i, (a, b) in enumerate(zip(actual_tables, tables))]
    text_equal = (len(actual_segments) == len(segments) and
                  all(_normal(a) == _normal(b) for a, b in zip(actual_segments, segments)))
    body_complete = not unsupported
    report = {'body': {
        'model_tables': len(actual_tables), 'reference_tables': len(tables),
        'model_total_tables': model_count, 'reference_total_tables': reference_count,
        'model_total_cells': model_cells, 'reference_total_cells': reference_cells,
        'table_count_equal': len(actual_tables) == len(tables),
        'text_equal': text_equal, 'table_checks': checks, 'complete': body_complete,
        'equal': ((text_equal and len(actual_tables) == len(tables)
                   and all(c['equal'] for c in checks)) if body_complete else None)}}
    for kind in ('footnotes', 'endnotes'):
        local = Counter()
        path = f'word/{kind}.xml'
        pieces = []
        if path in zipfile.namelist():
            notes = _read_part(zipfile, path, kind)
            seen = set()
            for note in notes:
                if note.tag != _W + kind[:-1]:
                    local['xml_scopes'] += 1
                    continue
                note_id = note.get(_W + 'id')
                # ECMA-376: omitted w:type means normal. IDs do not classify notes.
                # https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.footnoteendnotetype.type
                note_type = note.get(_W + 'type', 'normal')
                if note_type in {'separator', 'continuationSeparator', 'continuationNotice'}:
                    continue
                if note_type != 'normal':
                    local['note_type'] += 1
                    continue
                if note_id is None or note_id in seen:
                    local['note_identity'] += 1
                seen.add(note_id)
                paragraphs = []
                for child in note:
                    paragraphs.append(_note_text(child, local))
                pieces.append('\n'.join(paragraphs))
        metric = _metric(getattr(doc, kind), '\n'.join(pieces))
        metric.update(reference_notes=len(pieces), complete=not local,
                      equal=metric['text_equal'] if not local else None,
                      tables_text_only=True)
        report[kind] = metric
        unsupported.update({kind + '_' + k: v for k, v in local.items()})
    # Part numbers below are report ordinals, not a claimed reading order.
    headers = []
    for name in sorted(zipfile.namelist()):
        if re.fullmatch(r'word/(header|footer)[^/]*\.xml', name):
            part = _read_part(zipfile, name,
                              'hdr' if name.startswith('word/header') else 'ftr')
            headers.append({'number': len(headers) + 1,
                            'header': part.tag == _W + 'hdr',
                            'reference_paragraphs': sum(1 for _ in part.iter(_W + 'p')),
                            'reference_tables': sum(1 for _ in part.iter(_W + 'tbl')),
                            'comparable': False})
    report['headers_footers'] = {'reference_parts': headers,
                                 'model_chars': len(doc.headers_footers), 'comparable': False}
    if headers or doc.headers_footers:
        unsupported['headers_footers'] += max(1, len(headers))
    if doc.textboxes:
        unsupported['model_textboxes'] += 1
    report['unsupported_scopes'] = dict(unsupported)
    report['whitespace_normalized'] = True
    report['complete'] = not unsupported
    report['equal'] = ((report['body']['equal'] and report['footnotes']['equal'] and
                        report['endnotes']['equal']) if report['complete'] else None)
    report['status'] = 'ok' if report['complete'] else 'inconclusive'
    return report


def compare_document(doc, zipfile) -> dict:
    """Return privacy-safe metrics for a Document and an already open DOCX ZipFile.

    Root ``equal`` is True/False only for complete comparisons, otherwise None.
    ``status`` is ok, inconclusive (unsupported scopes), or invalid_reference
    (unreadable/malformed required or present XML parts, including absent body).
    Invalid references return only status/complete/equal; do not assume body metrics
    exist. ZIP opening failures before this call remain the caller's responsibility.
    """
    try:
        return _compare_document(doc, zipfile)
    except _InvalidReference:
        return {'status': 'invalid_reference', 'complete': False, 'equal': None}
