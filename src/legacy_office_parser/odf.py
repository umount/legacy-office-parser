"""Independent, stdlib-only ODT/ODS/ODP extraction (see docs/research-odf.md)."""
from __future__ import annotations

import math
import re

from ._odf_package import Budget, cap, q, read_package
from .errors import InvalidDocumentError, LimitExceededError
from .limits import Limits
from .models import _clone_cell, Cell, CellRange, Document, Paragraph, Sheet, Slide, SpreadsheetCell, Table

PARAS = {q('text:p'), q('text:h')}
ROW_WRAPPERS = {q('table:table-header-rows'), q('table:table-rows'), q('table:table-row-group')}
BLOCK_WRAPPERS = {q('text:section'), q('text:list'), q('text:list-item'),
                  q('text:list-header'), q('text:numbered-paragraph'),
                  q('text:index-body'), q('text:table-of-content')}
DRAW_STORIES = {q('draw:frame'), q('draw:text-box'), q('draw:g'), q('draw:a')}
HEADER_FOOTER = {q('style:' + name) for name in (
    'header', 'footer', 'header-left', 'footer-left', 'header-first', 'footer-first')}
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


def hidden_section(element):
    return element.tag == q('text:section') and element.get(q('text:display')) == 'none'


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
        self.roots = roots
        self.limits = budget.limits
        self.max_rows = cap(self.limits, 'max_rows', 1_048_576)
        self.max_columns = cap(self.limits, 'max_columns', 16_384)
        self.notes = {"footnote": [], "endnote": []}
        self.stories = {**self.notes, "textboxes": [], "headers_footers": []}
        # Additional retained text not already charged by the extraction budget.
        # Original stories already charge descendant cell projections; copies
        # charge only their legacy string until repeat_stories preflights them.
        self.retained_story_text = {kind: 0 for kind in self.stories}
        self.structured_stories = set()
        # Charges attributable to completed detached stories (including copies).
        # A containing story subtracts this delta to isolate its own block cost.
        self.story_budget_text = 0
        self.in_note = False
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
            self.warn('Unsupported or malformed ODF note omitted.')
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
                elif self.doc.format == 'odt' and child.tag in DRAW_STORIES:
                    self.drawing(child)
                elif child.tag == q('text:note'):
                    self.note(child)
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

    def note(self, element):
        # Only explicitly classified notes in visible ODT content are collected.
        # Citation labels are presentation, not part of the note body or anchor text.
        kind = element.get(q('text:note-class'))
        bodies = element.findall(q('text:note-body'))
        if self.doc.format != 'odt' or self.in_note or kind not in self.notes or len(bodies) != 1:
            self.unsupported(element)
            return
        self.in_note = True
        try:
            self.story(bodies[0], self.notes[kind])
        finally:
            self.in_note = False

    def story(self, element, destination):
        budget_start = self.budget.output_chars
        stories_start = self.story_budget_text
        # Reserve encounter order before extracting any nested frames. They are
        # routed to their own story, never flattened into this story's text.
        index = len(destination)
        blocks = []
        destination.append(('', blocks))
        self.blocks(element, blocks)
        # table() charges parent projections for repeats, but descendant blocks
        # can have been charged only for their template. Count this story's
        # actual retained tree once, before it can become a repeat template.
        # Detached nested stories are disjoint trees and have their own charges.
        full_text = 0
        pending = list(blocks)
        while pending:
            block = pending.pop()
            if isinstance(block, Paragraph):
                full_text += len(block.text)
            else:
                for row in block.rows:
                    for cell in row:
                        full_text += len(cell.text)
                        pending.extend(cell.blocks)
        own_charge = (self.budget.output_chars - budget_start -
                      (self.story_budget_text - stories_start))
        self.budget.text(max(0, full_text - own_charge))
        parts = []
        charged = 0
        for block in blocks:
            if isinstance(block, Paragraph):
                value = block.text
                charged += len(value)
            else:
                value = '\n'.join('\t'.join(c.text for c in row) for row in block.rows)
                charged += sum(len(c.text) for row in block.rows for c in row)
            if value:
                parts.append(value)
        value = '\n\n'.join(parts)
        if value:
            # Blocks already charged their text; also bound all rendered separators.
            self.budget.text(len(value) - charged + (2 if any(text for text, _ in destination) else 0))
            destination[index] = (value, blocks)
        # Include the legacy projection adjustment, but not nested stories a
        # second time. The outer story can now isolate its own budget delta.
        self.story_budget_text += (self.budget.output_chars - budget_start -
                                   (self.story_budget_text - stories_start))
        kind = next(kind for kind, stories in self.stories.items() if stories is destination)
        self.retained_story_text[kind] += charged
        if any(isinstance(block, Table) for block in blocks):
            self.structured_stories.add(kind)
        # Keep empty blocks too: an empty table still carries structure, and an
        # empty paragraph must survive if this pooled key contains a table.

    def drawing(self, element):
        if element.tag == q('draw:text-box'):
            self.warn('ODF text boxes pooled without anchor, chain, or layout identities.')
            self.story(element, self.stories['textboxes'])
            return
        for child in element:
            if child.tag in DRAW_STORIES:
                self.drawing(child)
            else:
                # Do not scrape image/object replacements, descriptions or extensions.
                self.unsupported(child)

    def used_masters(self, body):
        """Select evidenced main-flow masters, not every stored page template.

        ODF 1.3: 19.501, 19.503.2, 19.510 and 5.2. No layout/overflow
        inference: next-style links require a represented page transition.
        """
        masters, common, automatic, defaults = {}, {}, {}, {}

        def insert(index, key, element):
            # Ambiguous names never silently select either definition.
            index[key] = None if key in index else element

        for root in self.roots:
            if root is None:
                continue
            for e in root.findall(q('office:master-styles') + '/' + q('style:master-page')):
                insert(masters, e.get(q('style:name')), e)
            for e in root.findall(q('office:styles') + '/' + q('style:style')):
                insert(common, (e.get(q('style:family')), e.get(q('style:name'))), e)
            for e in root.findall(q('office:styles') + '/' + q('style:default-style')):
                insert(defaults, e.get(q('style:family')), e)
        # styles.xml automatic styles belong to its stories, not the main body.
        for e in self.roots[-1].findall(q('office:automatic-styles') + '/' + q('style:style')):
            insert(automatic, (e.get(q('style:family')), e.get(q('style:name'))), e)
        if not masters:
            return []
        cache = {}
        fo = '{urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0}'

        def style_properties(family, name):
            key = (family, name)
            if key in cache:
                return cache[key]
            values, visited = {}, set()
            index = automatic if key in automatic else common
            while name:
                lookup = (family, name)
                marker = (id(index), name)
                e = index.get(lookup)
                if e is None or marker in visited or e.find(q('style:map')) is not None:
                    self.warn('ODF master selection is ambiguous (missing, duplicate, cyclic, '
                              'or conditional style); affected page stories omitted.')
                    cache[key] = None
                    return None
                if len(visited) >= min(self.limits.max_depth, 256):
                    raise LimitExceededError('ODF style inheritance depth limit exceeded')
                visited.add(marker)
                if q('style:master-page-name') in e.attrib:
                    values.setdefault('master', e.get(q('style:master-page-name')))
                prop = e.find(q('style:' + family + '-properties'))
                if prop is not None:
                    for attr in ('break-before', 'break-after'):
                        if fo + attr in prop.attrib:
                            values.setdefault(attr, prop.get(fo + attr))
                name = e.get(q('style:parent-style-name'))
                index = common  # A parent cannot be an automatic style (19.510).
            if family in defaults:
                default = defaults[family]
                if default is None:
                    self.warn('ODF default style is ambiguous; affected page stories omitted.')
                    cache[key] = None
                    return None
                prop = default.find(q('style:' + family + '-properties'))
                if prop is not None:
                    for attr in ('break-before', 'break-after'):
                        if fo + attr in prop.attrib:
                            values.setdefault(attr, prop.get(fo + attr))
            cache[key] = values
            return values

        selected, current = {}, None
        next_chain = set()

        def select(name):
            nonlocal current
            current = name
            e = masters.get(name)
            if not name or e is None:
                self.warn('ODF master reference is missing or ambiguous; '
                          'affected page stories omitted.')
                current = None
                return
            selected.setdefault(name, e)
            next_name = e.get(q('style:next-style-name'))
            if next_name and next_name != name:
                self.warn('ODF automatic pagination is not computed; next master pages '
                          'are selected only at recorded or explicit page breaks.')

        sequences = body.findall(q('text:page-sequence'))
        pages = sequences[0].findall(q('text:page')) if len(sequences) == 1 else []
        if sequences:
            self.warn('ODF page-sequence selection uses its initial master and recorded '
                      'page transitions; automatic pagination is not computed.')
        page_index = 0

        def advance():
            nonlocal page_index
            page_index += 1
            if page_index < len(pages):
                select(pages[page_index].get(q('text:master-page-name')))
            elif current is not None:
                e = masters[current]
                target = e.get(q('style:next-style-name')) or current
                next_chain.add(current)
                next_chain.add(target)
                if len(next_chain) > min(self.limits.max_depth, 256):
                    raise LimitExceededError('ODF next master chain depth limit exceeded')
                select(target)

        def flow(parent):
            for e in parent:
                if e.tag in PARAS or e.tag == q('table:table'):
                    yield e
                elif e.tag in BLOCK_WRAPPERS and not hidden_section(e):
                    yield from flow(e)
                # No references from notes, frames, deleted text, or cell paragraphs.

        def soft_breaks(e):
            for child in e:
                if child.tag == q('text:soft-page-break'):
                    yield child
                elif child.tag in (INLINE | CACHED_FIELDS | PARAS | BLOCK_WRAPPERS |
                                   ROW_WRAPPERS | {q('table:table-row'), q('table:table-cell')}):
                    if (child.get(q('text:display')) != 'none' and
                            child.get(q('text:is-hidden')) not in {'true', '1'}):
                        yield from soft_breaks(child)

        def initial():
            if len(sequences) > 1:
                self.warn('ODF initial page sequence is ambiguous; page stories omitted.')
            elif pages:
                select(pages[0].get(q('text:master-page-name')))
            else:
                self.warn('ODF initial master is unspecified; using the first stored '
                          'master as an implementation-defined fallback.')
                select(next(iter(masters)))

        started, pending_break = False, False
        for e in flow(body):
            family = 'paragraph' if e.tag in PARAS else 'table'
            name = e.get(q('text:style-name') if family == 'paragraph' else q('table:style-name'))
            props = style_properties(family, name)
            if props is None:
                current = None
                started, pending_break = True, False
                continue
            explicit = props.get('master')
            if explicit:
                next_chain.clear()
                select(explicit)
            elif not started:
                initial()
            elif pending_break or props.get('break-before') == 'page':
                advance()
            started = True
            for _ in soft_breaks(e):
                self.warn('ODF cached soft page breaks used for master selection; '
                          'pagination is not recomputed.')
                advance()
            pending_break = props.get('break-after') == 'page'
        if not started:
            initial()
        return list(selected.values())

    def masters(self, body):
        for master in self.used_masters(body):
            for child in master:
                if child.tag in HEADER_FOOTER:
                    if child.get(q('style:display')) in {'false', '0'}:
                        self.warn('ODF disabled header/footer omitted.')
                        continue
                    self.warn('ODF headers/footers pooled from selected master-page variants; '
                              'page anchors and variant identities are not retained.')
                    self.story(child, self.stories['headers_footers'])
                else:
                    self.unsupported(child)

    def paragraphs(self, element):
        for child in element:
            if self.doc.format == 'odt' and hidden_section(child):
                self.warn('ODF hidden section omitted.')
                continue
            if child.tag in PARAS:
                yield self.inline(child)
            elif self.doc.format == 'odt' and child.tag in DRAW_STORIES:
                self.drawing(child)
            elif child.tag in BLOCK_WRAPPERS or child.tag in {
                q('draw:frame'), q('draw:text-box'), q('draw:g'), q('draw:custom-shape'),
                q('draw:rect'), q('draw:ellipse'), q('draw:a'), q('presentation:notes')}:
                yield from self.paragraphs(child)
            else:
                self.unsupported(child)

    def cell_text(self, e):
        parts = []
        size = 0
        for text in self.paragraphs(e):
            size += len(text) + bool(parts)
            # Paragraph expansion is individually bounded; check their aggregate
            # before retaining the next paragraph or allocating the joined cell.
            if size + self.budget.output_chars > self.limits.max_text_chars:
                raise LimitExceededError('ODF cell text limit exceeded')
            parts.append(text)
        return '\n'.join(parts)

    def cell_content(self, element):
        def nested(parent):
            for child in parent:
                if hidden_section(child):
                    continue
                if child.tag == q('table:table'):
                    return True
                if child.tag in BLOCK_WRAPPERS and nested(child):
                    return True
            return False
        if self.doc.format != 'odt' or not nested(element):
            return self.cell_text(element), []
        blocks = []
        self.blocks(element, blocks)
        # Check the projection before joining; table() charges it including repeats.
        size = max(0, len(blocks) - 1)
        for block in blocks:
            if isinstance(block, Paragraph):
                size += len(block.text)
            else:
                size += max(0, len(block.rows) - 1)
                for row in block.rows:
                    size += sum(len(cell.text) for cell in row) + max(0, len(row) - 1)
        if self.budget.output_chars + size > self.budget.limits.max_text_chars:
            raise LimitExceededError('ODF expanded text limit exceeded')
        value = '\n'.join(block.text if isinstance(block, Paragraph) else
                          '\n'.join('\t'.join(cell.text for cell in row) for row in block.rows)
                          for block in blocks)
        return value, blocks

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

    def repeat_stories(self, starts, copies, cells):
        """Clone detached stories with repeated table content, in reading order."""
        if not copies:
            return
        self.budget.cell(cells * copies)
        batches = {}
        copied_text = {}
        legacy_text = records = 0
        for kind, start in starts.items():
            values = self.stories[kind][start:]
            batches[kind] = values
            # Every cloned nonempty body follows an existing body of this kind.
            legacy_text += sum(len(value) + 2 for value, _ in values if value) * copies
            # Count every descendant projection, as _validate_result does, not
            # just the top-level cells represented by the legacy string.
            text = 0
            records += len(values) * copies
            pending = [block for _, blocks in values for block in blocks]
            while pending:
                block = pending.pop()
                records += copies
                if isinstance(block, Paragraph):
                    text += len(block.text)
                else:
                    records += len(block.rows) * copies
                    for row in block.rows:
                        records += len(row) * copies
                        for cell in row:
                            text += len(cell.text)
                            pending.extend(cell.blocks)
            copied_text[kind] = text * copies
        # Preflight ALL story kinds before cloning any of them. Keep this
        # separate from Budget.output_chars: that already includes the original
        # descendant projections, and XML source text has its own budget.
        retained = sum(self.retained_story_text[kind] + copied_text[kind]
                       for kind in self.structured_stories)
        self.budget.text(legacy_text)
        self.story_budget_text += legacy_text
        if self.budget.output_chars + retained > self.limits.max_text_chars:
            raise LimitExceededError('ODF retained story text limit exceeded')
        self.budget.nodes += records
        if self.budget.nodes > self.limits.max_records:
            raise LimitExceededError('ODF expanded story record limit exceeded')
        for kind, values in batches.items():
            self.retained_story_text[kind] += copied_text[kind]
            for _ in range(copies):
                for value, blocks in values:
                    cloned = _clone_cell(Cell(blocks=blocks)).blocks
                    self.stories[kind].append((value, cloned))

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
            row_stories = {kind: len(values) for kind, values in self.stories.items()}
            row_cells = self.budget.cells
            for e, column, cr, rs, cs in specs:
                if row_index + repeat + rs - 2 > self.max_rows:
                    raise LimitExceededError('ODF row span limit exceeded')
                covered = e.tag == q('table:covered-table-cell')
                cell_stories = {kind: len(values) for kind, values in self.stories.items()}
                cell_count = self.budget.cells
                value, children = ('', []) if covered else self.cell_content(e)
                self.repeat_stories(cell_stories, cr - 1, self.budget.cells - cell_count)
                self.budget.text(len(value) * cr * repeat)
                prototype = Cell(value, rs, cs, covered, children)
                template.extend(_clone_cell(prototype) for _ in range(cr))
            self.repeat_stories(row_stories, repeat - 1, self.budget.cells - row_cells)
            for _ in range(repeat):
                result.rows.append([_clone_cell(c) for c in template])
            row_index += repeat
        return result

    def blocks(self, parent, destination=None):
        if destination is None:
            destination = self.doc.blocks
        for e in parent:
            if hidden_section(e):
                self.warn('ODF hidden section omitted.')
                continue
            if e.tag in PARAS:
                value = self.inline(e)
                self.budget.text(len(value))
                destination.append(Paragraph(value))
            elif e.tag == q('table:table'):
                destination.append(self.table(e))
            elif self.doc.format == 'odt' and e.tag in DRAW_STORIES:
                self.drawing(e)
            elif e.tag in BLOCK_WRAPPERS:
                self.blocks(e, destination)
            else:
                self.unsupported(e)

    def hidden(self, e, family, property_tag, attribute):
        name = e.get(q('table:style-name') if family == 'table' else q('draw:style-name'))
        visited = set()
        while name and name not in visited:
            style = self.styles.get((family, name))
            if style is None:
                break
            if len(visited) >= min(self.limits.max_depth, 256):
                raise LimitExceededError('ODF style inheritance depth limit exceeded')
            visited.add(name)
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
        lengths.extend(len(value) for value in (doc.footnotes, doc.endnotes,
                                                doc.headers_footers, doc.textboxes) if value)
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
            if fmt == 'odt':
                continue
            for master in style_root.iter(q('style:master-page')):
                if len(master):
                    parser.warn('ODF master-page content is not rendered.')
                    break
    {'odt': parser.blocks, 'ods': parser.sheets, 'odp': parser.slides}[fmt](body)
    if fmt == 'odt':
        parser.masters(body)
    for kind, stories in parser.stories.items():
        field = {'footnote': 'footnotes', 'endnote': 'endnotes'}.get(kind, kind)
        setattr(doc, field, '\n\n'.join(value for value, _ in stories if value))
        # Opt in per pooled key, retaining all occurrences in encounter order.
        # No note identities, frame anchors, or page placement are inferred.
        if any(isinstance(block, Table) for _, blocks in stories for block in blocks):
            doc.story_blocks[field] = [block for _, blocks in stories for block in blocks]
    _check_visible_text(doc, limits)
    if doc.story_blocks:
        # Retained structure and its legacy projection are separate allocations.
        # Use the shared traversal for recursive cells, text, and depth budgets,
        # including callers of this byte-level entry point.
        from .api import _validate_result
        _validate_result(doc, limits)
    return doc
