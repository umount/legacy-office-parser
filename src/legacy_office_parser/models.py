"""Small, format-independent extraction model; no rendering or service dependencies."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from typing import Literal

@dataclass(slots=True)
class Paragraph:
    text: str
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
class Slide:
    number: int
    title: str = ''
    text: str = ''
    notes: str = ''
    hidden: bool = False

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
    # Keys name existing story fields, without claiming note anchors or placement.
    story_blocks: dict[str, list[Block]] = field(default_factory=dict)

    @property
    def text(self) -> str:
        if self.format in ('xls', 'ods'):
            return '\n\n'.join(
                '\n'.join([sheet.name] + [f'{c.address}\t{c.text}' for c in
                          sorted(sheet.cells, key=lambda c: (c.row, c.column)) if c.text])
                for sheet in self.sheets)
        if self.format in ('ppt', 'odp'):
            return '\n\n'.join('\n'.join(p for p in (s.title, s.text, s.notes) if p) for s in self.slides)
        parts = []
        for b in self.blocks:
            if isinstance(b, Paragraph):
                parts.append(b.text)
            else:
                parts.append('\n'.join('\t'.join(c.text for c in row) for row in b.rows))
        parts.extend(p for p in (self.footnotes, self.endnotes, self.headers_footers, self.textboxes) if p)
        return '\n\n'.join(p for p in parts if p)

    def to_dict(self) -> dict:
        def compatible_cells(items):
            result = dict(items)
            if 'row_span' in result:
                if not result.get('blocks'):
                    result.pop('blocks', None)
                if not result.get('omitted'):
                    result.pop('omitted', None)
            if 'format' in result and not result.get('story_blocks'):
                result.pop('story_blocks', None)
            return result
        return asdict(self, dict_factory=compatible_cells)


def _clone_cell(source: Cell) -> Cell:
    """Copy a nested cell iteratively; repeated source rows must not share trees."""
    result = Cell(source.text, source.row_span, source.col_span, source.covered, omitted=source.omitted)
    pending = [(source.blocks, result.blocks)]
    while pending:
        src, dst = pending.pop()
        for block in src:
            if isinstance(block, Paragraph):
                dst.append(Paragraph(block.text))
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
