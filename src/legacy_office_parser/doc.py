"""Bounded, native Word 97–2003 text and table extraction.

Format authority: [MS-DOC] sections 2.4.1, 2.4.3, 2.4.6.1, 2.5 and
Clx/PlcPcd/PapxFkp/PapxInFkp/Sprm/TCGRF. Technical reference and adapted
layout/operand-size logic: MIT-licensed wordcraft crates/docbin/src/{fib,
piece,fkp,sprm,table}.rs (review checkout /tmp/wordcraft-parser-review).
This is an extraction implementation, not a Word layout/revision engine.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
import struct

from ._ole import open_ole, read_stream
from .errors import (EncryptedDocumentError, InvalidDocumentError,
                     LimitExceededError, UnsupportedFormatError)
from .limits import Limits
from .models import Cell, Document, Paragraph, Table


__all__ = ['parse_doc_bytes']


def _span(data, offset, size):
    if offset < 0 or size < 0 or offset + size > len(data):
        raise InvalidDocumentError('DOC structure extends outside its stream')
    return memoryview(data)[offset:offset + size]


def _u16(data, offset=0):
    return struct.unpack('<H', _span(data, offset, 2))[0]


def _u32(data, offset=0):
    return struct.unpack('<I', _span(data, offset, 4))[0]


class _Budget:
    def __init__(self, limits):
        self.limits = limits
        self.records = 0
        self.cells = 0

    def record(self, count=1):
        self.records += count
        if self.records > self.limits.max_records:
            raise LimitExceededError('DOC record limit exceeded')

    def cell(self, count=1):
        self.cells += count
        if self.cells > self.limits.max_cells:
            raise LimitExceededError('DOC cell limit exceeded')


def _ascending(values):
    if any(a >= b for a, b in zip(values, values[1:])):
        raise InvalidDocumentError('DOC position array is not strictly increasing')


# MS-DOC FcCompressed differs from cp1252 at 80, 8D, 8E, 8F, 90, 9D, 9E.
_COMPRESSED = {n: ord(bytes([n]).decode('cp1252')) for n in
               (0x82, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89, 0x8A,
                0x8B, 0x8C, 0x91, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97,
                0x98, 0x99, 0x9A, 0x9B, 0x9C, 0x9F)}


@dataclass(slots=True)
class _Piece:
    cp: int
    end: int
    fc: int
    width: int
    prm: int


@dataclass(slots=True)
class _Props:
    in_table: bool = False
    row_end: bool = False
    depth: int = 0
    inner: bool = False
    edges: list[int] = field(default_factory=list)
    flags: list[int] = field(default_factory=list)
    merges: list[tuple[int, int]] = field(default_factory=list)
    vmerges: dict[int, int] = field(default_factory=dict)


class _Doc:
    def __init__(self, ole, limits):
        self.ole = ole
        self.limits = limits
        self.budget = _Budget(limits)
        self.document = Document(format='doc')
        self.word = read_stream(ole, 'WordDocument', limits)
        self.data = None
        self.pages = {}
        self.fields = []
        self._fib()
        self.table = read_stream(ole, self.table_name, limits)
        self._pieces()
        self._bins()

    def warn(self, message):
        if message not in self.document.warnings:
            self.document.warnings.append(message)

    def _fib(self):
        magic = _u16(self.word)
        if magic == 0xA5DC:
            raise UnsupportedFormatError('Word 6/95 DOC is not supported')
        if magic != 0xA5EC:
            raise InvalidDocumentError('invalid WordDocument signature')
        flags = _u16(self.word, 10)
        if flags & (0x0100 | 0x8000):
            raise EncryptedDocumentError('encrypted or obfuscated DOC is not supported')
        version = _u16(self.word, 2)
        versions = {0xC1: 93, 0xD9: 108, 0x101: 136, 0x10C: 164, 0x112: 183}
        if version not in versions:
            raise UnsupportedFormatError('unsupported DOC FIB version')
        if _u16(self.word, 32) != 14 or _u16(self.word, 62) != 22:
            raise InvalidDocumentError('invalid DOC FIB layout')
        count = _u16(self.word, 152)
        if count < versions[version]:
            raise InvalidDocumentError('truncated DOC FIB offset array')
        self.budget.record(count)
        self.pairs = _span(self.word, 154, count * 8)
        self.counts = [_u32(self.word, 64 + i * 4) for i in (3, 4, 5, 7, 8, 9, 10)]
        if any(n & 0x80000000 for n in self.counts):
            raise InvalidDocumentError('negative DOC story length')
        self.total = sum(self.counts)
        if self.total > self.limits.max_text_chars:
            raise LimitExceededError('DOC text limit exceeded')
        cbmac = _u32(self.word, 64)
        if cbmac < 154 + count * 8 or cbmac > len(self.word):
            raise InvalidDocumentError('invalid DOC cbMac')
        self.word = memoryview(self.word)[:cbmac]
        self.table_name = '1Table' if flags & 0x0200 else '0Table'
        if flags & 0x1000:
            self.warn('Far East DOC flag is set; language-specific legacy encoding is not interpreted.')

    def pair(self, index):
        return _u32(self.pairs, index * 8), _u32(self.pairs, index * 8 + 4)

    def table_part(self, index):
        fc, size = self.pair(index)
        return _span(self.table, fc, size) if size else memoryview(b'')

    def _pieces(self):
        clx = self.table_part(33)
        if not clx:
            raise UnsupportedFormatError('DOC without a CLX piece table is not supported')
        pos = 0
        self.prcs = []
        while pos < len(clx) and clx[pos] == 1:
            self.budget.record()
            length = _u16(clx, pos + 1)
            self.prcs.append(_span(clx, pos + 3, length))
            pos += 3 + length
        if pos >= len(clx) or clx[pos] != 2:
            raise InvalidDocumentError('DOC CLX is missing its Pcdt')
        size = _u32(clx, pos + 1)
        plc = _span(clx, pos + 5, size)
        if size < 4 or (size - 4) % 12:
            raise InvalidDocumentError('invalid DOC piece table size')
        if pos + 5 + size != len(clx):
            raise InvalidDocumentError('unexpected trailing DOC CLX bytes')
        count = (size - 4) // 12
        self.budget.record(count)
        cps = [_u32(plc, i * 4) for i in range(count + 1)]
        _ascending(cps)
        if cps[0] != 0 or cps[-1] < self.total:
            raise InvalidDocumentError('DOC piece table does not cover its stories')
        if cps[-1] > self.limits.max_text_chars:
            raise LimitExceededError('DOC piece CP limit exceeded')
        if cps[-1] > self.total + 1:
            self.warn('Piece table contains CPs outside the declared stories; these are excluded.')
        self.pieces = []
        # UTF-16 bytes preserve CP indexing even for astral characters and split pairs.
        self.text = bytearray(self.total * 2)
        for i in range(count):
            at = (count + 1) * 4 + i * 8
            raw = _u32(plc, at + 2)
            compressed = bool(raw & 0x40000000)
            fc = raw & 0x3FFFFFFF
            if compressed and fc % 2:
                raise InvalidDocumentError('odd compressed DOC piece offset')
            fc = fc // 2 if compressed else fc
            width = 1 if compressed else 2
            prm = _u16(plc, at + 6)
            if prm & 1 and prm >> 1 >= len(self.prcs):
                raise InvalidDocumentError('DOC piece references a missing PRC')
            _span(self.word, fc, (cps[i + 1] - cps[i]) * width)
            self.pieces.append(_Piece(cps[i], cps[i + 1], fc, width, prm))
            stop = min(cps[i + 1], self.total)
            if stop <= cps[i]:
                continue
            raw_text = bytes(_span(self.word, fc, (stop - cps[i]) * width))
            if compressed:
                raw_text = raw_text.decode('latin1').translate(_COMPRESSED).encode('utf-16le')
            self.text[cps[i] * 2:stop * 2] = raw_text
        self.cps = cps

    def _bins(self):
        plc = self.table_part(13)
        self.bin_fcs, self.bin_pages = [], []
        if not plc:
            self.warn('Paragraph formatting is absent; table structure cannot be established.')
            return
        if len(plc) < 4 or (len(plc) - 4) % 8:
            raise InvalidDocumentError('invalid DOC paragraph bin table')
        count = (len(plc) - 4) // 8
        self.budget.record(count)
        self.bin_fcs = [_u32(plc, i * 4) for i in range(count + 1)]
        _ascending(self.bin_fcs)
        self.bin_pages = [_u32(plc, (count + 1 + i) * 4) & 0x3FFFFF for i in range(count)]

    def _papx(self, fc):
        i = bisect_right(self.bin_fcs, fc) - 1
        if i < 0 or i >= len(self.bin_pages):
            if self.bin_pages:
                self.warn('Some paragraphs have no PAPX coverage; their table membership is unknown.')
            return memoryview(b'')
        pn = self.bin_pages[i]
        if pn not in self.pages:
            page = _span(self.word, pn * 512, 512)
            count = page[511]
            if not 1 <= count <= 29:
                raise InvalidDocumentError('invalid DOC PAPX FKP run count')
            self.budget.record(count)
            fcs = [_u32(page, j * 4) for j in range(count + 1)]
            _ascending(fcs)
            groups = []
            front = (count + 1) * 4 + count * 13
            for j in range(count):
                off = page[(count + 1) * 4 + j * 13] * 2
                if not off:
                    groups.append(memoryview(b''))
                    continue
                if off < front or off >= 511:
                    raise InvalidDocumentError('invalid DOC PAPX offset')
                cb = page[off]
                start, size = (off + 1, cb * 2 - 1) if cb else (off + 2, page[off + 1] * 2)
                if size < 2 or start + size > 511:
                    raise InvalidDocumentError('invalid DOC PAPX size')
                if _u16(page, start):
                    self.warn('Paragraph style inheritance is not evaluated; only direct table properties are used.')
                groups.append(_span(page, start + 2, size - 2))
            self.pages[pn] = fcs, groups
        fcs, groups = self.pages[pn]
        j = bisect_right(fcs, fc) - 1
        if j < 0 or j >= len(groups):
            raise InvalidDocumentError('DOC PAPX bin does not cover its paragraph')
        return groups[j]

    def _sprms(self, group):
        pos = 0
        while pos < len(group):
            # PAPX can have one alignment byte after its last Prl.
            if len(group) - pos == 1 and group[pos] == 0:
                return
            self.budget.record()
            op = _u16(group, pos)
            pos += 2
            spra = op >> 13
            if op in (0xD608, 0xD606):
                size = _u16(group, pos) + 1
            elif op == 0xC615 and _span(group, pos, 1)[0] == 255:
                deleted = _span(group, pos + 1, 1)[0]
                added = _span(group, pos + 2 + deleted * 4, 1)[0]
                size = 3 + deleted * 4 + added * 3
            elif spra == 6:
                size = 1 + _span(group, pos, 1)[0]
            else:
                size = (1, 1, 2, 4, 2, 2, 0, 3)[spra]
            operand = _span(group, pos, size)
            pos += size
            yield op, operand

    def _apply(self, props, group):
        depth, seen = 0, set()
        while True:
            if depth > self.limits.max_depth:
                raise LimitExceededError('DOC property indirection depth limit exceeded')
            for op, arg in self._sprms(group):
                if op == 0x2416:
                    props.in_table = bool(arg[0])
                elif op == 0x2417:
                    props.row_end = bool(arg[0])
                elif op == 0x6649:
                    props.depth = _u32(arg)
                    if props.depth > self.limits.max_depth:
                        raise LimitExceededError('DOC table depth limit exceeded')
                elif op in (0x244B, 0x244C):
                    props.inner |= bool(arg[0])
                elif op == 0x6646:  # sprmPHugePapx: grpprl in Data, prefixed by cb u16.
                    offset = _u32(arg)
                    if offset in seen:
                        raise InvalidDocumentError('cyclic DOC huge PAPX reference')
                    if self.data is None:
                        self.data = read_stream(self.ole, 'Data', self.limits)
                    length = _u16(self.data, offset)
                    group = _span(self.data, offset + 2, length)
                    seen.add(offset)
                    depth += 1
                    break  # Ignore remaining Prls after a processed HugePapx.
                elif op in (0x6645, 0x646B):
                    self.warn('External table properties are unsupported; available inline table properties are used.')
                elif op == 0xD608:
                    n = _span(arg, 2, 1)[0]
                    if n > 63:
                        raise InvalidDocumentError('DOC row has more than 63 defined cells')
                    props.edges = [struct.unpack('<h', _span(arg, 3 + 2 * j, 2))[0] for j in range(n + 1)]
                    base = 3 + (n + 1) * 2
                    remaining = len(arg) - base
                    if remaining < 0 or remaining % 20:
                        raise InvalidDocumentError('invalid DOC TC80 array')
                    props.flags = [_u16(arg, base + 20 * j) for j in range(min(n, remaining // 20))]
                    props.flags.extend([0] * (n - len(props.flags)))
                    if any(a > b for a, b in zip(props.edges, props.edges[1:])):
                        raise InvalidDocumentError('DOC cell boundaries are decreasing')
                elif op == 0x5624:
                    props.merges.append((arg[0], arg[1]))
                elif op == 0xD62B:
                    if len(arg) != 3:
                        raise InvalidDocumentError('invalid DOC vertical merge operand')
                    props.vmerges[arg[1]] = arg[2]
                elif op in (0x7621, 0x5622, 0x5625, 0xD606):
                    self.warn('Legacy or incremental table geometry is unsupported; explicit cell marks are retained.')
            else:
                return

    def properties(self, cp):
        piece = self.pieces[bisect_right(self.cps, cp) - 1]
        props = _Props()
        self._apply(props, self._papx(piece.fc + (cp - piece.cp) * piece.width))
        if piece.prm & 1:
            self._apply(props, self.prcs[piece.prm >> 1])
        elif piece.prm:
            self.warn('Compact piece formatting (Prm0) is not evaluated.')
        return props

    def clean(self, start, end):
        raw = bytes(self.text[start * 2:end * 2])
        try:
            value = raw.decode('utf-16le')
        except UnicodeDecodeError:
            self.warn('Invalid UTF-16 was replaced with U+FFFD.')
            value = raw.decode('utf-16le', errors='replace')
        out = []
        for ch in value:
            if ch == '\x13':
                if len(self.fields) >= self.limits.max_depth:
                    raise LimitExceededError('DOC field nesting limit exceeded')
                self.fields.append(False)
                self.warn('Fields use stored results; field instructions are not evaluated.')
                continue
            if ch == '\x14':
                if self.fields:
                    self.fields[-1] = True
                else:
                    self.warn('Unbalanced DOC field delimiters were encountered.')
                continue
            if ch == '\x15':
                if self.fields:
                    self.fields.pop()
                else:
                    self.warn('Unbalanced DOC field delimiters were encountered.')
                continue
            if self.fields and not all(self.fields):
                continue
            if ch in ('\x01', '\x08'):
                self.warn('Embedded objects and drawings are omitted; textbox stories are extracted separately.')
            elif ch in ('\x02', '\x05'):
                self.warn('Note/comment reference marks are omitted; note stories are extracted separately.')
            elif ch in ('\x0b', '\x0c', '\x0e', '\r'):
                out.append('\n')
            elif ch == '\x07':
                out.append('\t')
            elif ch == '\x1e':
                out.append('\u2011')
            elif ch == '\x1f':
                out.append('\u00ad')
            elif ord(ch) >= 32 or ch in ('\t', '\n'):
                out.append(ch)
            else:
                self.warn('Unsupported control characters were omitted from extracted text.')
        return ''.join(out)

    def paragraphs(self, start, count):
        begin = start
        for cp in range(start, start + count):
            unit = self.text[cp * 2] | self.text[cp * 2 + 1] << 8
            if unit in (7, 13):
                self.budget.record()
                yield self.clean(begin, cp), cp, unit
                begin = cp + 1
        if begin < start + count:
            self.budget.record()
            self.warn('A DOC story has no final paragraph mark; trailing text is retained.')
            yield self.clean(begin, start + count), start + count - 1, 0

    def parse(self):
        assembler = _Tables(self)
        for text, cp, mark in self.paragraphs(0, self.counts[0]):
            assembler.add(text, mark, self.properties(cp))
        assembler.finish()
        self._end_fields()
        start = self.counts[0]
        for index, count in enumerate(self.counts[1:], 1):
            if count:
                if index == 3:
                    self.warn('Comment story text is omitted; the output model has no comments field.')
                else:
                    parts = []
                    for text, cp, mark in self.paragraphs(start, count):
                        props = self.properties(cp)
                        if props.in_table or props.depth or props.inner:
                            self.warn('Tables in auxiliary stories are flattened to text.')
                        if props.depth > 1 or props.inner:
                            self.warn('Nested tables are unsupported and flattened in CP order.')
                        parts.append(text)
                    value = '\n'.join(parts)
                    attr = {1: 'footnotes', 2: 'headers_footers', 4: 'endnotes',
                            5: 'textboxes', 6: 'textboxes'}[index]
                    old = getattr(self.document, attr)
                    setattr(self.document, attr, old + ('\n' if old and value else '') + value)
                    self.warn('Auxiliary stories are separated by type; note anchors, header variants and textbox placement are not modeled.')
                self._end_fields()
            start += count
        if self.pair(12)[1]:
            self.warn('Character formatting is not evaluated; hidden and revision-deleted text may be included.')
        return self.document

    def _end_fields(self):
        if self.fields:
            self.warn('Unbalanced DOC field delimiters were encountered.')
            self.fields.clear()


class _Tables:
    def __init__(self, doc):
        self.doc = doc
        self.table = None
        self.cells = []
        self.paras = []
        self.vertical = {}
        self.row_edges = []

    def cell(self):
        self.doc.budget.cell()
        self.cells.append(Cell(text='\n'.join(self.paras)))
        self.paras = []

    def row(self, props):
        if props.edges and len(props.edges) - 1 != len(self.cells):
            self.doc.warn('Table definition and cell marks disagree; observed cells are retained without inferred cells.')
        self._merge(props)
        self.table.rows.append(self.cells)
        self.row_edges.append(props.edges)
        self.cells = []

    def _merge(self, props):
        cells = self.cells
        flags = props.flags[:len(cells)] + [0] * max(0, len(cells) - len(props.flags))
        for first, stop in props.merges:
            if not 0 <= first < stop <= len(cells):
                self.doc.warn('Invalid horizontal merge range was ignored.')
                continue
            flags[first] = flags[first] & ~3 | 2
            for i in range(first + 1, stop):
                flags[i] = flags[i] & ~3 | 1
        anchor = None
        for i, cell in enumerate(cells):
            hm = flags[i] & 3
            if hm in (2, 3):
                anchor = cell
            elif hm == 1 and anchor is not None:
                anchor.col_span += 1
                cell.covered = True
                if cell.text:
                    self.doc.warn('Covered merged cells contain text; their text is retained at its original coordinate.')
            else:
                if hm == 1:
                    self.doc.warn('Orphan horizontal merge continuation was retained as a normal cell.')
                anchor = None
        current = {}
        for i, cell in enumerate(cells):
            if cell.covered:
                continue
            vm = props.vmerges.get(i, (flags[i] >> 5) & 3)
            # Matching boundaries prevent invented vertical spans across different grids.
            key = None
            if len(props.edges) == len(cells) + 1 and i + cell.col_span < len(props.edges):
                key = (props.edges[i], props.edges[i + cell.col_span])
            if vm == 3 and key is not None:
                current[key] = cell
            elif vm == 1 and key in self.vertical:
                previous = self.vertical[key]
                if previous.col_span == cell.col_span:
                    previous.row_span += 1
                    current[key] = previous
                    cell.covered = True
                    if cell.text:
                        self.doc.warn('Covered merged cells contain text; their text is retained at its original coordinate.')
                else:
                    self.doc.warn('Vertical merge with mismatched columns was not applied.')
            elif vm:
                self.doc.warn('Vertical merge without a matching explicit grid was not applied.')
        self.vertical = current

    def add(self, text, mark, props):
        nested = props.depth > 1 or props.inner
        if nested:
            self.doc.warn('Nested tables are unsupported and flattened in CP order.')
            # Preserve nested paragraphs inside the currently open outer cell.
            if self.table is not None:
                self.paras.append(text)
            else:
                self.doc.document.blocks.append(Paragraph(text))
            return
        in_table = props.in_table or props.depth == 1
        if not in_table:
            self.finish()
            if mark == 7:
                self.doc.warn('Cell mark without table membership was retained as a paragraph boundary.')
            self.doc.document.blocks.append(Paragraph(text))
            return
        if self.table is None:
            self.table = Table()
            self.doc.document.blocks.append(self.table)
        if props.row_end:
            # A TTP is a separate, empty paragraph after the final cell mark.
            if text or self.paras:
                if text:
                    self.paras.append(text)
                self.cell()
                self.doc.warn('Row terminator contains content; content is retained as a cell.')
            if not self.cells:
                self.cell()
            self.row(props)
        elif mark == 7:
            self.paras.append(text)
            self.cell()
        else:
            self.paras.append(text)

    def finish(self):
        if self.table is None:
            return
        if self.paras or self.cells:
            self.doc.warn('Table ends without a row terminator; the incomplete row is retained.')
            if self.paras:
                self.cell()
            self.row(_Props())
        self._normalize_grid()
        self.table = None
        self.vertical = {}
        self.row_edges = []

    def _normalize_grid(self):
        # A wide physical cell can span boundaries introduced by other rows.
        # Build a grid from explicit TDefTable edges, never from text or spacing.
        valid = [(row, edges) for row, edges in zip(self.table.rows, self.row_edges)
                 if len(edges) == len(row) + 1 and len(edges) > 1
                 and all(a < b for a, b in zip(edges, edges[1:]))]
        if len(valid) != len(self.table.rows):
            if any(self.row_edges):
                self.doc.warn('Incomplete or zero-width table grids cannot be normalized; physical cell coordinates are retained.')
            return
        if not valid:
            return
        left, right = valid[0][1][0], valid[0][1][-1]
        if any(edges[0] != left or edges[-1] != right for _, edges in valid):
            self.doc.warn('Rows with different outer boundaries retain their physical cell coordinates.')
            return
        grid = sorted({edge for _, edges in valid for edge in edges})
        indexes = {edge: i for i, edge in enumerate(grid)}
        # Check before constructing the expanded coordinate matrix.
        extra = sum(len(grid) - 1 - len(row) for row, _ in valid)
        self.doc.budget.cell(extra)
        for row, edges in valid:
            expanded = []
            for i, cell in enumerate(row):
                start = indexes[edges[i]]
                end = indexes[edges[i + 1]]
                if not cell.covered:
                    cell.col_span = indexes[edges[min(i + cell.col_span, len(row))]] - start
                expanded.append(cell)
                expanded.extend(Cell(covered=True) for _ in range(end - start - 1))
            row[:] = expanded


def parse_doc_bytes(data: bytes, limits: Limits) -> Document:
    """Extract declared DOC stories and PAPX-backed tables, or raise ParseError.

    CP units (including discarded stories) count against max_text_chars. Record
    budgets include FIB pairs, pieces, PAPX runs, Prls and emitted paragraphs.
    No salvage scan is performed when structural metadata is corrupt.
    """
    with open_ole(data, limits) as ole:
        return _Doc(ole, limits).parse()
