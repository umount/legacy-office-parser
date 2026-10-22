"""Explicit display-text normalization; source values and positions stay unchanged."""
from __future__ import annotations

from dataclasses import fields, is_dataclass
import unicodedata

from ._serialization import clone_model
from ._validation import _validate_result
from .limits import Limits
from .diagnostics import diagnostic_warning
from .models import Cell, Document, Paragraph, Sheet, Slide, SlideComment, SpreadsheetCell

# CRLF is handled before this translation so one source break stays one break.
_TRANSLATE = {n: None for n in (*range(32), *range(127, 160)) if n not in (9, 10)}
_TRANSLATE.update({11: '\n', 12: '\n', 13: '\n', 133: '\n'})
_TRANSLATE.update({n: '\ufffd' for n in range(0xD800, 0xE000)})
_TEXT_FIELDS = {
    Document: {'footnotes', 'endnotes', 'headers_footers', 'textboxes', 'comment_text'},
    Paragraph: {'text'}, Cell: {'text'}, Slide: {'title', 'text', 'notes'},
    SlideComment: {'text'}, Sheet: {'name'},
}


def normalize_text(document: Document, *, unicode_form: str | None = None,
                   limits: Limits | None = None) -> Document:
    """Copy a document, normalize display text, and validate retained budgets.

    Preserve TAB/LF and spaces; map CRLF/CR/VT/FF/NEL to LF; remove other C0/C1
    controls and DEL; replace lone surrogate code points with U+FFFD. Optional
    NFC is explicit, never compatibility normalization. Spreadsheet values and
    formulas, source offsets, metadata and warning messages remain unchanged.
    This is not a sanitizer for markup, bidi controls, or hidden source content.
    """
    if not isinstance(document, Document):
        raise TypeError('document must be a Document')
    if unicode_form not in (None, 'NFC'):
        raise ValueError('unicode_form must be None or NFC')
    if limits is not None and not isinstance(limits, Limits):
        raise TypeError('limits must be Limits or None')
    limits = limits if limits is not None else Limits()
    result = clone_model(document)
    _validate_result(result, limits)
    changed = False

    def clean(text):
        nonlocal changed
        value = text.replace('\r\n', '\n').translate(_TRANSLATE)
        if unicode_form:
            value = unicodedata.normalize(unicode_form, value)
        changed |= value != text
        return value

    def block_text(block):
        if isinstance(block, Paragraph):
            return block.text
        return '\n'.join('\t'.join(cell.text for cell in row) for row in block.rows)

    projections = []
    for story, blocks in result.story_blocks.items():
        projections.append((result, story, blocks, getattr(result, story),
                            [block_text(block) for block in blocks]))
    pending = [result]
    while pending:
        item = pending.pop()
        if is_dataclass(item):
            selected = next((names for cls, names in _TEXT_FIELDS.items()
                             if isinstance(item, cls)), set())
            if isinstance(item, Cell) and item.blocks:
                projections.append((item, 'text', item.blocks, item.text,
                                    [block_text(block) for block in item.blocks]))
            # Spreadsheet display text is separate from its typed source value.
            if isinstance(item, SpreadsheetCell):
                selected = {'text'}
            for f in fields(item):
                value = getattr(item, f.name)
                if f.name in selected:
                    setattr(item, f.name, clean(value))
                elif isinstance(item, Sheet) and f.name == 'drawings':
                    item.drawings = [clean(s) for s in value]
                elif isinstance(value, (list, dict)) or is_dataclass(value):
                    pending.append(value)
        elif isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, dict):
            pending.extend(item.values())
    # Normalize text atoms before their separators. A source CR followed by an
    # inserted paragraph LF is two boundaries, not an encoded CRLF within text.
    for owner, field, blocks, original, before in reversed(projections):
        after = [block_text(block) for block in blocks]
        for separator, keep_empty, suffix in (
                ('\n', True, ''), ('\n', True, '\n'),
                ('\n', False, ''), ('\n\n', True, ''), ('\n\n', False, '')):
            indices = [i for i, text in enumerate(before) if keep_empty or text]
            if separator.join(before[i] for i in indices) + suffix == original:
                value = separator.join(after[i] for i in indices) + suffix
                changed |= value != original
                setattr(owner, field, value)
                break
    if changed:
        warning = diagnostic_warning('text_normalized',
                                     'Display text normalized; source values and positions retained.')
        if warning not in result.warnings:
            result.warnings.append(warning)
    return _validate_result(result, limits)
