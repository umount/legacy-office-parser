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
class Document:
    format: Literal['doc', 'ppt']
    blocks: list[Block] = field(default_factory=list)
    slides: list[Slide] = field(default_factory=list)
    footnotes: str = ''
    endnotes: str = ''
    headers_footers: str = ''
    textboxes: str = ''
    warnings: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        if self.format == 'ppt':
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
        return asdict(self)
