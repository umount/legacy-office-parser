"""Validate shared output models and budgets independently of input dispatch.

Parsers enforce limits while decoding. This second boundary checks their public
results without reading files or selecting a document format.
"""
import math

from .errors import InvalidDocumentError, LimitExceededError
from .limits import Limits
from .models import Document

def _validate_result(doc: Document, limits: Limits) -> Document:
    # Defence in depth; individual parsers enforce limits during decoding too.
    from .models import Paragraph, SlideComment
    _validate_notes(doc, limits)
    _validate_comments(doc, limits)
    total = 0
    cells = 0
    stack = [(block, 1) for block in doc.blocks]
    stack.extend((block, 1) for blocks in doc.story_blocks.values() for block in blocks)
    while stack:
        block, depth = stack.pop()
        if depth > limits.max_depth:
            raise LimitExceededError('output table nesting depth limit exceeded')
        if isinstance(block, Paragraph):
            if block.heading_level is not None and (
                    type(block.heading_level) is not int or not 1 <= block.heading_level <= 9):
                raise InvalidDocumentError('invalid paragraph heading level')
            total += len(block.text)
        else:
            for row in block.rows:
                cells += len(row)
                for cell in row:
                    if cell.omitted and (cell.covered or cell.text or cell.blocks or
                                         cell.row_span != 1 or cell.col_span != 1):
                        raise InvalidDocumentError('invalid omitted table position')
                    total += len(cell.text)
                    stack.extend((child, depth + 1) for child in cell.blocks)
        if cells > limits.max_cells:
            raise LimitExceededError('table cell limit exceeded')
        if total > limits.max_text_chars:
            raise LimitExceededError('output text size limit exceeded')
    comment_count = 0
    slide_visible = max(0, len(doc.slides) - 1) * 2
    for slide in doc.slides:
        total += len(slide.title) + len(slide.text) + len(slide.notes)
        parts = [part for part in (slide.title, slide.text, slide.notes) if part]
        slide_visible += sum(map(len, parts)) + max(0, len(parts) - 1)
        has_text = bool(parts)
        comment_count += len(slide.comments)
        if comment_count > limits.max_records:
            raise LimitExceededError('slide comment record limit exceeded')
        for comment in slide.comments:
            if (not isinstance(comment, SlideComment) or not all(isinstance(value, str)
                    for value in (comment.text, comment.author, comment.initials))):
                raise InvalidDocumentError('invalid slide comment')
            total += len(comment.text) + len(comment.author) + len(comment.initials)
            if comment.text:
                slide_visible += int(has_text) + len(comment.text)
                has_text = True
            if total > limits.max_text_chars:
                raise LimitExceededError('output comment text size limit exceeded')
    if comment_count and slide_visible > limits.max_text_chars:
        raise LimitExceededError('slide rendered text limit exceeded')
    if len(doc.sheets) > limits.max_sheets:
        raise LimitExceededError('sheet count limit exceeded')
    drawing_records = 0
    sheet_visible = max(0, len(doc.sheets) - 1) * 2
    for sheet in doc.sheets:
        if not 0 <= sheet.rows <= limits.max_rows or not 0 <= sheet.columns <= limits.max_columns:
            raise LimitExceededError('sheet dimensions exceed limits')
        total += len(sheet.name)
        sheet_visible += len(sheet.name)
        drawing_records += len(sheet.drawings)
        if drawing_records > limits.max_records:
            raise LimitExceededError('sheet drawing record limit exceeded')
        for drawing in sheet.drawings:
            total += len(drawing)
            if drawing:
                sheet_visible += 1 + len(drawing)
        if total > limits.max_text_chars:
            raise LimitExceededError('output text size limit exceeded')
        cells += len(sheet.cells) + len(sheet.merges)
        for cell in sheet.cells:
            if not 1 <= cell.row <= limits.max_rows or not 1 <= cell.column <= limits.max_columns:
                raise LimitExceededError('cell coordinates exceed limits')
            if cell.text:
                sheet_visible += 2 + len(cell.address) + len(cell.text)
            total += len(cell.text) + len(cell.formula or '')
            if isinstance(cell.value, str) and cell.value != cell.text:
                total += len(cell.value)
            if isinstance(cell.value, float) and not math.isfinite(cell.value):
                raise InvalidDocumentError('non-finite spreadsheet value')
        for merged in sheet.merges:
            if not (1 <= merged.start_row <= merged.end_row <= limits.max_rows and
                    1 <= merged.start_column <= merged.end_column <= limits.max_columns):
                raise LimitExceededError('merged cell coordinates exceed limits')
    if drawing_records and sheet_visible > limits.max_text_chars:
        raise LimitExceededError('sheet rendered text limit exceeded')
    total += sum(len(s) for s in (doc.footnotes, doc.endnotes, doc.headers_footers, doc.textboxes, doc.comment_text))
    total += sum(len(c.author or '') + len(c.initials or '') for c in doc.comments)
    if total > limits.max_text_chars:
        raise LimitExceededError('output text size limit exceeded')
    if cells > limits.max_cells:
        raise LimitExceededError('table cell limit exceeded')
    if len(doc.slides) > limits.max_slides:
        raise LimitExceededError('slide count limit exceeded')
    return doc


def _validate_notes(doc: Document, limits: Limits) -> None:
    from .models import Note, NoteBodyRange

    def index(value):
        return type(value) is int and value >= 0

    if len(doc.notes) > limits.max_records:
        raise LimitExceededError('note record limit exceeded')
    previous = {}
    metadata = 0
    for note in doc.notes:
        if not isinstance(note, Note) or note.kind not in ('footnote', 'endnote'):
            raise InvalidDocumentError('invalid note kind')
        if not index(note.ordinal) or note.ordinal == 0:
            raise InvalidDocumentError('invalid note ordinal')
        if note.reference_kind not in ('automatic', 'custom', 'unknown'):
            raise InvalidDocumentError('invalid note reference kind')
        if note.source_cp is not None and (not index(note.source_cp) or note.source_cp >= 0x7FFFFFFF):
            raise InvalidDocumentError('invalid note source CP')
        if note.source_cp is not None and note.source_cp >= limits.max_text_chars:
            raise LimitExceededError('note source CP limit exceeded')
        if not isinstance(note.visibility, list) or any(flag not in (
                'hidden', 'deleted', 'field_hidden', 'field_instruction', 'unknown') for flag in note.visibility):
            raise InvalidDocumentError('invalid note visibility')
        if len(note.visibility) != len(set(note.visibility)):
            raise InvalidDocumentError('duplicate note visibility flag')
        body = note.body
        story = note.kind + 's'
        if (not isinstance(body, NoteBodyRange) or body.story != story
                or not index(body.block_start) or not index(body.block_end)
                or not body.block_start < body.block_end <= len(doc.story_blocks.get(story, []))):
            raise InvalidDocumentError('invalid note body range')
        ordinal, end = previous.get(story, (0, 0))
        if note.ordinal <= ordinal or body.block_start < end:
            raise InvalidDocumentError('unordered or overlapping note body ranges')
        previous[story] = note.ordinal, body.block_end
        path = note.anchor_path
        metadata += 1
        if metadata > limits.max_records:
            raise LimitExceededError('note metadata limit exceeded')
        if path is None:
            continue
        if not isinstance(path, list) or note.source_cp is None:
            raise InvalidDocumentError('invalid note anchor path')
        if len(path) > 5 * limits.max_depth + 2:
            raise LimitExceededError('note anchor depth limit exceeded')
        metadata += len(path)
        if metadata > limits.max_records:
            raise LimitExceededError('note metadata limit exceeded')
        _validate_anchor_path(doc, path, 'note')

def _validate_comments(doc: Document, limits: Limits) -> None:
    from .models import Comment, CommentBodyRange

    def index(value):
        return type(value) is int and value >= 0

    if not doc.comments:
        return
    if doc.format != 'doc':
        raise InvalidDocumentError('document comments require DOC format')
    # Notes and comments share the metadata budget, including copied anchor paths.
    metadata = sum(1 + len(note.anchor_path or []) for note in doc.notes)
    if metadata + len(doc.comments) > limits.max_records:
        raise LimitExceededError('document comment record limit exceeded')
    previous_ordinal = previous_end = 0
    previous_cp = -1
    reply_ancestors = []
    for comment in doc.comments:
        if not isinstance(comment, Comment):
            raise InvalidDocumentError('invalid document comment')
        if not index(comment.ordinal) or comment.ordinal <= previous_ordinal:
            raise InvalidDocumentError('unordered or invalid document comment ordinal')
        # Charge this metadata entry before growing the reply ancestry index.
        metadata += 1
        if metadata > limits.max_records:
            raise LimitExceededError('document comment metadata limit exceeded')
        depth, parent = comment.reply_depth, comment.parent_ordinal
        if depth is None:
            if parent is not None:
                raise InvalidDocumentError('document comment parent requires reply depth')
        else:
            if not index(depth):
                raise InvalidDocumentError('invalid document comment reply depth')
            if depth > limits.max_depth:
                raise LimitExceededError('document comment reply depth limit exceeded')
            if depth > 0 and parent is None:
                raise InvalidDocumentError('document comment reply requires a retained parent')
            if parent is not None:
                if (not index(parent) or depth == 0 or depth > len(reply_ancestors)
                        or reply_ancestors[depth - 1] != parent):
                    raise InvalidDocumentError('invalid document comment reply parent')
            # Unknown entries do not prove a branch closure. Known entries
            # must still follow preorder among the retained known ancestry.
            del reply_ancestors[depth:]
            reply_ancestors.append(comment.ordinal)
        if any(value is not None and not isinstance(value, str)
               for value in (comment.author, comment.initials)):
            raise InvalidDocumentError('invalid document comment author metadata')
        if (not isinstance(comment.visibility, list) or any(flag not in (
                'hidden', 'deleted', 'field_hidden', 'field_instruction', 'unknown')
                for flag in comment.visibility)):
            raise InvalidDocumentError('invalid document comment visibility')
        if len(comment.visibility) != len(set(comment.visibility)):
            raise InvalidDocumentError('duplicate document comment visibility flag')
        cp = comment.source_cp
        if cp is not None:
            if not index(cp) or not previous_cp < cp < 0x7FFFFFFF:
                raise InvalidDocumentError('unordered or invalid document comment source CP')
            if cp >= limits.max_text_chars:
                raise LimitExceededError('document comment source CP limit exceeded')
            previous_cp = cp
        start, end = comment.selection_start, comment.selection_end
        if (start is None) != (end is None):
            raise InvalidDocumentError('incomplete document comment selection')
        if start is not None:
            if cp is None or not index(start) or not index(end) or not start <= end < 0x7FFFFFFF:
                raise InvalidDocumentError('invalid document comment selection')
            if end >= limits.max_text_chars:
                raise LimitExceededError('document comment selection limit exceeded')
        body = comment.body
        if (not isinstance(body, CommentBodyRange) or body.story != 'comment_text'
                or not index(body.block_start) or not index(body.block_end)
                or not previous_end <= body.block_start < body.block_end <=
                len(doc.story_blocks.get('comment_text', []))):
            raise InvalidDocumentError('invalid document comment body range')
        previous_ordinal, previous_end = comment.ordinal, body.block_end
        path = comment.anchor_path
        if path is None:
            continue
        if not isinstance(path, list) or cp is None:
            raise InvalidDocumentError('invalid document comment anchor path')
        if len(path) > 5 * limits.max_depth + 2:
            raise LimitExceededError('document comment anchor depth limit exceeded')
        metadata += len(path)
        if metadata > limits.max_records:
            raise LimitExceededError('document comment metadata limit exceeded')
        _validate_anchor_path(doc, path, 'comment')


def _validate_anchor_path(doc, path, label):
    from .models import Cell, Paragraph, Table

    def index(value):
        return type(value) is int and value >= 0

    current, at = doc, 0
    while at < len(path):
        if isinstance(current, (Document, Cell)):
            if (at + 1 >= len(path) or path[at] != 'blocks'
                    or not index(path[at+1]) or path[at+1] >= len(current.blocks)):
                raise InvalidDocumentError(f'invalid {label} block path')
            current = current.blocks[path[at+1]]
            at += 2
        elif isinstance(current, Table):
            if (at + 2 >= len(path) or path[at] != 'rows'
                    or not index(path[at+1]) or path[at+1] >= len(current.rows)
                    or not index(path[at+2]) or path[at+2] >= len(current.rows[path[at+1]])):
                raise InvalidDocumentError(f'invalid {label} cell path')
            current = current.rows[path[at+1]][path[at+2]]
            at += 3
        else:
            raise InvalidDocumentError(f'{label} path continues beyond a paragraph')
    if not isinstance(current, (Paragraph, Cell)) or (isinstance(current, Cell) and current.omitted):
        raise InvalidDocumentError(f'{label} anchor is not a source paragraph or cell')


