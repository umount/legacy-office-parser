"""Small, format-independent extraction model; no rendering or service dependencies."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

@dataclass(slots=True)
class Paragraph:
    text: str
    heading_level: int | None = None
    kind: Literal['paragraph'] = field(default='paragraph', init=False)

@dataclass(slots=True)
class Cell:
    text: str = ''
    row_span: int = 1
    col_span: int = 1
    # Covered coordinates are retained so columns never silently shift.
    covered: bool = False
    # Ordered content for cells containing nested tables; text is its plain projection.
    blocks: list[Block] = field(default_factory=list)
    # No source cell occupies this coordinate; distinct from empty or covered cells.
    omitted: bool = False

@dataclass(slots=True)
class Table:
    rows: list[list[Cell]] = field(default_factory=list)
    kind: Literal['table'] = field(default='table', init=False)

Block = Paragraph | Table

@dataclass(slots=True)
class SlideComment:
    text: str
    author: str = ''
    initials: str = ''


@dataclass(slots=True)
class Slide:
    number: int
    title: str = ''
    text: str = ''
    notes: str = ''
    hidden: bool = False
    comments: list[SlideComment] = field(default_factory=list)

@dataclass(slots=True)
class SpreadsheetCell:
    # Sparse 1-based coordinates; no allocation for absent rows/columns.
    row: int
    column: int
    value: str | float | int | bool | None = None
    value_type: str = 'empty'
    text: str = ''
    formula: str | None = None
    is_formula: bool = False

    @property
    def address(self) -> str:
        column = self.column
        letters = ''
        while column > 0:
            column, digit = divmod(column - 1, 26)
            letters = chr(65 + digit) + letters
        return f'{letters}{self.row}'


@dataclass(slots=True)
class CellRange:
    start_row: int
    start_column: int
    end_row: int
    end_column: int


@dataclass(slots=True)
class Sheet:
    name: str
    cells: list[SpreadsheetCell] = field(default_factory=list)
    merges: list[CellRange] = field(default_factory=list)
    hidden: bool = False
    rows: int = 0
    columns: int = 0
    # Sheet-owned ordinary drawing text, in source order; never cell values.
    drawings: list[str] = field(default_factory=list)



@dataclass(slots=True)
class NoteBodyRange:
    story: Literal['footnotes', 'endnotes']
    block_start: int
    block_end: int


@dataclass(slots=True)
class Note:
    kind: Literal['footnote', 'endnote']
    ordinal: int
    body: NoteBodyRange
    # Source CP is NOT an offset into any normalized output string.
    source_cp: int | None = None
    reference_kind: Literal['automatic', 'custom', 'unknown'] = 'unknown'
    anchor_path: list[str | int] | None = None
    visibility: list[Literal['hidden', 'deleted', 'field_hidden', 'field_instruction', 'unknown']] = field(
        default_factory=lambda: ['unknown'])

@dataclass(slots=True)
class CommentBodyRange:
    story: Literal['comment_text']
    block_start: int
    block_end: int


@dataclass(slots=True)
class Comment:
    ordinal: int
    body: CommentBodyRange
    author: str | None = None
    initials: str | None = None
    # Source UTF-16 positions, never offsets into normalized output text.
    source_cp: int | None = None
    selection_start: int | None = None
    selection_end: int | None = None
    anchor_path: list[str | int] | None = None
    visibility: list[Literal['hidden', 'deleted', 'field_hidden', 'field_instruction', 'unknown']] = field(
        default_factory=lambda: ['unknown'])

    # Validated source tree depth; a missing retained parent is never guessed.
    reply_depth: int | None = None
    parent_ordinal: int | None = None


@dataclass(slots=True)
class Document:
    format: Literal['doc', 'xls', 'ppt', 'rtf', 'odt', 'ods', 'odp']
    blocks: list[Block] = field(default_factory=list)
    slides: list[Slide] = field(default_factory=list)
    footnotes: str = ''
    endnotes: str = ''
    headers_footers: str = ''
    textboxes: str = ''
    warnings: list[str] = field(default_factory=list)
    sheets: list[Sheet] = field(default_factory=list)

    # Optional structured auxiliary content; the matching string is its projection.
    # Keys name existing story fields; notes separately reference body ranges.
    story_blocks: dict[str, list[Block]] = field(default_factory=dict)
    notes: list[Note] = field(default_factory=list)
    comments: list[Comment] = field(default_factory=list)
    comment_text: str = ''

    @property
    def text(self) -> str:
        if self.format in ('xls', 'ods'):
            return '\n\n'.join(
                '\n'.join([sheet.name] + [f'{c.address}\t{c.text}' for c in
                          sorted(sheet.cells, key=lambda c: (c.row, c.column)) if c.text] +
                          [text for text in sheet.drawings if text])
                for sheet in self.sheets)
        if self.format in ('ppt', 'odp'):
            return '\n\n'.join('\n'.join(p for p in
                [s.title, s.text, s.notes] + [c.text for c in s.comments] if p)
                for s in self.slides)
        parts = []
        for b in self.blocks:
            if isinstance(b, Paragraph):
                parts.append(b.text)
            else:
                parts.append('\n'.join('\t'.join(c.text for c in row) for row in b.rows))
        parts.extend(p for p in (self.footnotes, self.endnotes, self.headers_footers, self.textboxes, self.comment_text) if p)
        return '\n\n'.join(p for p in parts if p)

    @property
    def diagnostics(self):
        from .diagnostics import diagnostics_for
        return diagnostics_for(self.warnings)

    def to_dict(self) -> dict:
        from ._serialization import model_to_dict
        result = model_to_dict(self)
        if self.warnings:
            result['diagnostics'] = [{'code': d.code, 'message': d.message}
                                     for d in self.diagnostics]
        return result


def _clone_cell(source: Cell) -> Cell:
    """Copy a nested cell iteratively; repeated source rows must not share trees."""
    result = Cell(source.text, source.row_span, source.col_span, source.covered, omitted=source.omitted)
    pending = [(source.blocks, result.blocks)]
    while pending:
        src, dst = pending.pop()
        for block in src:
            if isinstance(block, Paragraph):
                dst.append(Paragraph(block.text, heading_level=block.heading_level))
            else:
                table = Table()
                dst.append(table)
                for row in block.rows:
                    copied = []
                    table.rows.append(copied)
                    for cell in row:
                        item = Cell(cell.text, cell.row_span, cell.col_span, cell.covered, omitted=cell.omitted)
                        copied.append(item)
                        pending.append((cell.blocks, item.blocks))
    return result
