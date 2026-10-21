"""Independent, stdlib-only ODT/ODS/ODP extraction (see docs/research-odf.md)."""
from __future__ import annotations

import math
import re

from ._odf_package import Budget, cap, q, read_package
from .errors import InvalidDocumentError, LimitExceededError
from .limits import Limits
from .models import Cell, CellRange, Document, Paragraph, Sheet, Slide, SpreadsheetCell, Table

PARAS = {q('text:p'), q('text:h')}
ROW_WRAPPERS = {q('table:table-header-rows'), q('table:table-rows'), q('table:table-row-group')}
BLOCK_WRAPPERS = {q('text:section'), q('text:list'), q('text:list-item'),
                  q('text:list-header'), q('text:numbered-paragraph'),
                  q('text:index-body'), q('text:table-of-content')}
INLINE = {q('text:span'), q('text:a'), q('text:meta'), q('text:meta-field'), q('text:ruby-base')}
# Stored display text only: never resolve variables, refresh dates, or run formulas.
CACHED_FIELDS = {q('text:' + name) for name in (
    'page-number', 'page-count', 'date', 'time', 'sequence', 'sequence-ref',
    'variable-set', 'variable-get', 'variable-input', 'user-field-get', 'user-field-input',
    'expression', 'text-input', 'conditional-text', 'hidden-text', 'hidden-paragraph',
    'author-name', 'author-initials', 'sender-firstname', 'sender-lastname',
    'sender-initials', 'sender-title', 'sender-position', 'sender-email',
    'sender-phone-private', 'sender-fax', 'sender-company', 'sender-phone-work',
    'sender-street', 'sender-city', 'sender-postal-code', 'sender-country',
    'sender-state-or-province', 'creation-author', 'creation-date', 'creation-time',
    'modification-date', 'modification-time', 'print-date', 'print-time',
    'printed-by', 'editing-cycles', 'editing-duration', 'description', 'title',
    'subject', 'keywords', 'initial-creator', 'creator', 'file-name', 'chapter',
    'template-name', 'sheet-name', 'character-count', 'word-count', 'paragraph-count',
    'table-count', 'image-count', 'object-count', 'bookmark-ref', 'reference-ref',
    'note-ref', 'database-display', 'database-name', 'database-row-number',
    'user-defined', 'bibliography-mark', 'page-variable-get')}

SKIP = {q('office:annotation'), q('office:annotation-end'), q('text:tracked-changes'),
        q('office:forms'), q('office:scripts'), q('draw:object'), q('draw:object-ole'),
        q('draw:image'), q('draw:page-thumbnail'), q('text:ruby-text')}


def positive(element, name, maximum):
    raw = element.get(q(name), '1')
    if not re.fullmatch(r'\+?[0-9]+', raw):
        raise InvalidDocumentError('Invalid ODF positive integer')
    digits = raw.lstrip('+0')
    if len(digits) > len(str(maximum)):
        raise LimitExceededError('ODF repeat/span limit exceeded')
    value = int(digits or '0')
    if value < 1:
        raise InvalidDocumentError('Invalid ODF zero repeat/span')
    if value > maximum:
        raise LimitExceededError('ODF repeat/span limit exceeded')
    return value


class _Parser:
    def __init__(self, doc, budget, roots):
        self.doc, self.budget = doc, budget
        self.limits = budget.limits
        self.max_rows = cap(self.limits, 'max_rows', 1_048_576)
        self.max_columns = cap(self.limits, 'max_columns', 16_384)
        self.styles = {}
        for root in roots:
            if root is not None:
                for e in root.iter(q('style:style')):
                    self.styles[(e.get(q('style:family')), e.get(q('style:name')))] = e

    def warn(self, text):
        if text not in self.doc.warnings:
            self.doc.warnings.append(text)

    def unsupported(self, e):
        if e.tag == q('text:note'):
            self.warn('ODF inline footnotes/endnotes are not extracted.')
            return
        # Element names are intentionally not echoed: extensions may contain secrets.
        if e.tag in {q('text:soft-page-break'), q('text:bookmark'), q('text:bookmark-start'),
                     q('text:bookmark-end'), q('text:change-start'), q('text:change-end')}:
            return
        self.warn('Unsupported ODF content omitted (annotations, revisions, objects, or extensions).')

    def inline(self, element):
        tokens = []
        count = 0

        def add(s, explicit=False):
            nonlocal count
            count += len(s)
            if count > cap(self.limits, 'max_text_chars', 10_000_000):
                raise LimitExceededError('ODF paragraph text limit exceeded')
            tokens.append((s, explicit))

        def walk(e):
            if e.text:
                add(e.text)
            for child in e:
                if child.tag in INLINE or child.tag in CACHED_FIELDS:
                    if child.get(q('text:display')) != 'none' and child.get(q('text:is-hidden')) not in {'true', '1'}:
                        walk(child)
                elif child.tag == q('text:ruby'):
                    for base in child:
                        if base.tag == q('text:ruby-base'):
                            walk(base)
                    self.warn('ODF ruby annotations omitted; base text retained.')
                elif child.tag == q('text:s'):
                    n = positive(child, 'text:c', cap(self.limits, 'max_text_chars', 10_000_000))
                    if count + n > cap(self.limits, 'max_text_chars', 10_000_000):
                        raise LimitExceededError('ODF expanded spaces limit exceeded')
                    add(' ' * n, True)
                elif child.tag in {q('text:tab'), q('text:line-break')}:
                    add('\t' if child.tag == q('text:tab') else '\n', True)
                else:
                    self.unsupported(child)
                if child.tail:
                    add(child.tail)
        walk(element)
        # Raw XML whitespace collapses across span boundaries; explicit ODF
        # whitespace survives, including leading/trailing text:s elements.
        parts, pending, started = [], False, False
        for value, explicit in tokens:
            if explicit:
                if pending and started:
                    parts.append(' ')
                parts.append(value)
                pending, started = False, True
            else:
                for token in re.findall(r'[^ \t\r\n]+|[ \t\r\n]+', value):
                    if token[0] in ' \t\r\n':
                        pending = True
                    else:
                        if pending and started:
                            parts.append(' ')
                        parts.append(token)
                        pending, started = False, True
        return ''.join(parts)

    def paragraphs(self, element):
        for child in element:
            if child.tag in PARAS:
                yield self.inline(child)
            elif child.tag in BLOCK_WRAPPERS or child.tag in {
                q('draw:frame'), q('draw:text-box'), q('draw:g'), q('draw:custom-shape'),
                q('draw:rect'), q('draw:ellipse'), q('draw:a'), q('presentation:notes')}:
                yield from self.paragraphs(child)
            else:
                self.unsupported(child)

    def cell_text(self, e):
        text = '\n'.join(self.paragraphs(e))
        if len(text) > cap(self.limits, 'max_text_chars', 10_000_000):
            raise LimitExceededError('ODF cell text limit exceeded')
        return text

    def rows(self, table):
        for child in table:
            if child.tag == q('table:table-row'):
                yield child
            elif child.tag in ROW_WRAPPERS:
                yield from self.rows(child)
            elif child.tag not in {q('table:table-column'), q('table:table-columns'),
                                    q('table:table-header-columns'), q('table:table-column-group')}:
                self.unsupported(child)

    def row_cells(self, row):
        column = 1
        for e in row:
            if e.tag not in {q('table:table-cell'), q('table:covered-table-cell')}:
                self.unsupported(e)
                continue
            repeat = positive(e, 'table:number-columns-repeated', self.max_columns)
            rs = positive(e, 'table:number-rows-spanned', self.max_rows)
            cs = positive(e, 'table:number-columns-spanned', self.max_columns)
            if column + repeat - 1 > self.max_columns or column + repeat + cs - 2 > self.max_columns:
                raise LimitExceededError('ODF column limit exceeded')
            yield e, column, repeat, rs, cs
            column += repeat

    def table(self, element):
        result = Table()
        row_index = 1
        for row in self.rows(element):
            repeat = positive(row, 'table:number-rows-repeated', self.max_rows)
            if row_index + repeat - 1 > self.max_rows:
                raise LimitExceededError('ODF row limit exceeded')
            specs = list(self.row_cells(row))
            width = sum(s[2] for s in specs)
            # Empty ODT rows still allocate a row object.
            self.budget.cell(max(width, 1) * repeat)
            template = []
            for e, column, cr, rs, cs in specs:
                if row_index + repeat + rs - 2 > self.max_rows:
                    raise LimitExceededError('ODF row span limit exceeded')
                covered = e.tag == q('table:covered-table-cell')
                value = '' if covered else self.cell_text(e)
                self.budget.text(len(value) * cr * repeat)
                template.extend(Cell(value, rs, cs, covered) for _ in range(cr))
            for _ in range(repeat):
                result.rows.append([Cell(c.text, c.row_span, c.col_span, c.covered) for c in template])
            row_index += repeat
        return result

    def blocks(self, parent):
        for e in parent:
            if e.tag in PARAS:
                value = self.inline(e)
                self.budget.text(len(value))
                self.doc.blocks.append(Paragraph(value))
            elif e.tag == q('table:table'):
                self.doc.blocks.append(self.table(e))
            elif e.tag in BLOCK_WRAPPERS:
                self.blocks(e)
            else:
                self.unsupported(e)

    def hidden(self, e, family, property_tag, attribute):
        name = e.get(q('table:style-name') if family == 'table' else q('draw:style-name'))
        visited = set()
        while name and name not in visited:
            visited.add(name)
            style = self.styles.get((family, name))
            if style is None:
                break
            prop = style.find(q(property_tag))
            if prop is not None and q(attribute) in prop.attrib:
                return prop.get(q(attribute)) in {'false', '0', 'hidden'}
            name = style.get(q('style:parent-style-name'))
        return False

    def value(self, e, text):
        kind = e.get(q('office:value-type'), 'string' if text else 'empty')
        formula = e.get(q('table:formula'))
        value = None
        if kind in {'float', 'percentage', 'currency'}:
            raw = e.get(q('office:value'))
            if raw is not None:
                try:
                    value = float(raw)
                    if not math.isfinite(value):
                        raise ValueError
                    if re.fullmatch(r'[+-]?[0-9]{1,100}', raw):
                        value = int(raw)
                except ValueError as exc:
                    raise InvalidDocumentError('Invalid ODF numeric value') from exc
        elif kind == 'boolean':
            raw = e.get(q('office:boolean-value'))
            if raw is not None:
                if raw not in {'true', 'false', '1', '0'}:
                    raise InvalidDocumentError('Invalid ODF boolean value')
                value = raw in {'true', '1'}
        elif kind in {'date', 'time'}:
            value = e.get(q('office:date-value' if kind == 'date' else 'office:time-value'))
        elif kind == 'string':
            value = e.get(q('office:string-value'), text)
        elif kind != 'empty':
            self.warn('Unsupported ODF spreadsheet value type; display text retained.')
        if formula is not None:
            self.warn('ODF formulas are not evaluated; only cached values and formula text are retained.')
        if kind != 'empty' and value is None:
            self.warn('ODF cell has no supported cached value; display text retained.')
        if not text and value is not None:
            text = ('true' if value else 'false') if isinstance(value, bool) else str(value)
        return value, kind, text, formula

    def sheets(self, body):
        for e in body:
            if e.tag != q('table:table'):
                self.unsupported(e)
                continue
            if len(self.doc.sheets) >= cap(self.limits, 'max_sheets', 256):
                raise LimitExceededError('ODF sheet limit exceeded')
            sheet = Sheet(e.get(q('table:name'), ''))
            self.budget.text(len(sheet.name))
            sheet.hidden = self.hidden(e, 'table', 'style:table-properties', 'table:display')
            self.doc.sheets.append(sheet)
            row_index = 1
            for row in self.rows(e):
                rr = positive(row, 'table:number-rows-repeated', self.max_rows)
                if row_index + rr - 1 > self.max_rows:
                    raise LimitExceededError('ODF row limit exceeded')
                for cell, column, cr, rs, cs in self.row_cells(row):
                    if row_index + rr + rs - 2 > self.max_rows:
                        raise LimitExceededError('ODF row span limit exceeded')
                    sheet.columns = max(sheet.columns, column + cr + cs - 2)
                    sheet.rows = max(sheet.rows, row_index + rr + rs - 2)
                    if cell.tag == q('table:covered-table-cell'):
                        continue
                    value, kind, text, formula = self.value(cell, self.cell_text(cell))
                    merged = rs > 1 or cs > 1
                    if value is None and not text and formula is None and not merged:
                        continue
                    self.budget.cell(rr * cr)
                    self.budget.text((len(text) + len(formula or '') +
                                      (len(value) if isinstance(value, str) else 0)) * rr * cr)
                    for r in range(row_index, row_index + rr):
                        for c in range(column, column + cr):
                            sheet.cells.append(SpreadsheetCell(r, c, value, kind, text, formula,
                                                               formula is not None))
                            if merged:
                                sheet.merges.append(CellRange(r, c, r + rs - 1, c + cs - 1))
                sheet.rows = max(sheet.rows, row_index + rr - 1)
                row_index += rr
            sheet.cells.sort(key=lambda c: (c.row, c.column))

    def slides(self, body):
        for page in body:
            if page.tag != q('draw:page'):
                self.unsupported(page)
                continue
            if len(self.doc.slides) >= self.limits.max_slides:
                raise LimitExceededError('ODF slide limit exceeded')
            slide = Slide(len(self.doc.slides) + 1)
            slide.hidden = (page.get(q('presentation:visibility')) == 'hidden' or
                            self.hidden(page, 'drawing-page', 'style:drawing-page-properties',
                                        'presentation:visibility'))
            parts = {'title': [], 'text': [], 'notes': []}

            def walk(e, destination='text'):
                if e.tag in SKIP:
                    self.unsupported(e)
                    return
                if e.tag == q('presentation:notes'):
                    destination = 'notes'
                elif e.get(q('presentation:class')) in {'title', 'subtitle'} and destination != 'notes':
                    destination = 'title'
                elif e.get(q('presentation:class')) in {'header', 'footer', 'date-time', 'page-number'}:
                    self.warn('ODF slide headers, footers, dates and page numbers omitted.')
                    return
                if e.tag in PARAS:
                    text = self.inline(e)
                    self.budget.text(len(text))
                    parts[destination].append(text)
                    return
                if e.tag == q('table:table'):
                    table = self.table(e)
                    parts[destination].extend('\t'.join(c.text for c in row) for row in table.rows)
                    return
                if e.tag not in {q('draw:page'), q('draw:g'), q('draw:frame'), q('draw:text-box'),
                                 q('draw:custom-shape'), q('draw:rect'), q('draw:ellipse'),
                                 q('draw:a'), q('presentation:notes')} | BLOCK_WRAPPERS:
                    self.unsupported(e)
                    return
                for child in e:
                    walk(child, destination)
            walk(page)
            slide.title, slide.text, slide.notes = ('\n'.join(parts[k]) for k in ('title', 'text', 'notes'))
            self.doc.slides.append(slide)


def _check_visible_text(doc, limits):
    """Include model-rendered separators/coordinates without joining the output."""
    def joined(lengths, separator):
        total = count = 0
        for length in lengths:
            total += length
            count += 1
        return total + max(0, count - 1) * separator

    if doc.format == 'ods':
        size = joined((joined([len(s.name)] + [len(c.address) + 1 + len(c.text)
                                              for c in s.cells if c.text], 1)
                       for s in doc.sheets), 2)
    elif doc.format == 'odp':
        size = joined((joined((len(v) for v in (s.title, s.text, s.notes) if v), 1)
                       for s in doc.slides), 2)
    else:
        lengths = []
        for block in doc.blocks:
            if isinstance(block, Paragraph):
                length = len(block.text)
            else:
                length = joined((joined((len(c.text) for c in row), 1)
                                 for row in block.rows), 1)
            if length:
                lengths.append(length)
        size = joined(lengths, 2)
    if size > cap(limits, 'max_text_chars', 10_000_000):
        raise LimitExceededError('ODF rendered text limit exceeded')


def parse_odf_bytes(data: bytes, limits: Limits, expected_format: str | None = None) -> Document:
    """Parse a ZIP ODF package by MIME, never by filename; never execute formulas."""
    budget = Budget(limits)
    fmt, root, styles, no_manifest = read_package(data, budget, expected_format)
    if root.tag != q('office:document-content'):
        raise InvalidDocumentError('Invalid ODF content root')
    bodies = root.findall(q('office:body'))
    if len(bodies) != 1 or len(bodies[0]) != 1:
        raise InvalidDocumentError('Missing or ambiguous ODF body')
    body = bodies[0][0]
    expected_body = {'odt': 'text', 'ods': 'spreadsheet', 'odp': 'presentation'}[fmt]
    if body.tag != q('office:' + expected_body):
        raise InvalidDocumentError('ODF MIME/body mismatch')
    doc = Document(format=fmt)
    parser = _Parser(doc, budget, (styles, root))
    if no_manifest:
        parser.warn('ODF manifest missing; package encryption declarations could not be checked.')
    for style_root in (styles, root):
        if style_root is not None:
            for master in style_root.iter(q('style:master-page')):
                if len(master):
                    parser.warn('ODF master-page content is not rendered.')
                    break
    {'odt': parser.blocks, 'ods': parser.sheets, 'odp': parser.slides}[fmt](body)
    _check_visible_text(doc, limits)
    return doc
