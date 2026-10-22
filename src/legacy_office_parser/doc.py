"""Bounded, native Word 97–2003 text and table extraction.

Format authority: [MS-DOC] sections 2.4.1, 2.4.3, 2.4.6.1, 2.5 and
Clx/PlcPcd/PapxFkp/PapxInFkp/Sprm/TCGRF. Technical reference and adapted
layout/operand-size logic: MIT-licensed wordcraft crates/docbin/src/{fib,
piece,fkp,sprm,table}.rs (see THIRD_PARTY.md for source revision and license).
This is an extraction implementation, not a Word layout/revision engine.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field, replace
from itertools import chain
import struct

from .diagnostics import diagnostic_warning
from ._ole import open_ole, read_stream
from ._doc_textboxes import live_textbox_ranges
from ._doc_notes import decode_note_ranges
from ._doc_comments import decode_comments
from ._doc_table import FrameIdentity, TableIdentity, apply_table, frame_change
from ._doc_conditions import apply_conditions, row_boundary
from ._doc_styles import Styles, character_ops, outline_level, toggle
from .errors import (EncryptedDocumentError, InvalidDocumentError,
                     LimitExceededError, UnsupportedFormatError)
from .limits import Limits
from .models import (Cell, Document, Paragraph, Table, Note, NoteBodyRange,
                     Comment, CommentBodyRange)


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
        self.text_chars = 0

    def record(self, count=1):
        self.records += count
        if self.records > self.limits.max_records:
            raise LimitExceededError('DOC record limit exceeded')

    def cell(self, count=1):
        self.cells += count
        if self.cells > self.limits.max_cells:
            raise LimitExceededError('DOC cell limit exceeded')

    def text(self, count):
        self.text_chars += count
        if self.text_chars > self.limits.max_text_chars:
            raise LimitExceededError('DOC output text limit exceeded')


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
    style: int = 0
    outline: int = 9
    applied_table_style: int | None = None
    table_look: int = 0x600
    table_header: bool = False
    condition_known: bool = True
    in_table: bool = False
    row_end: bool = False
    depth: int = 0
    inner_cell: bool = False
    inner_ttp: bool = False
    bidi: bool = False
    bidi90: bool = False
    edges: list[int] = field(default_factory=list)
    flags: list[int] = field(default_factory=list)
    table_left: int = 0
    table_gap: int = 0
    identity: TableIdentity = field(default_factory=TableIdentity)
    frame: FrameIdentity = field(default_factory=FrameIdentity)

    @property
    def inner(self):
        return self.inner_cell or self.inner_ttp


class _Doc:
    def __init__(self, ole, limits):
        self.ole = ole
        self.limits = limits
        self.budget = _Budget(limits)
        self.document = Document(format='doc')
        self.word = read_stream(ole, 'WordDocument', limits)
        self.data = None
        self.pages = {}
        self.chpx_bins = None
        self.chpx_pages = {}
        self.symbol_prms = {}
        self.symbol_fonts = None
        self.fields = []
        self.comment_references = {}
        self.comment_markers = {}
        self.comment_marker_known = {}
        self.comment_selections = {}
        self.comment_structure_known = {}
        self.note_references = {}
        self.note_targets = {}
        self.note_object_cps = {}
        self.note_visibility = {}
        self.paragraph_anchors = []
        self.paragraph_cache = None
        self.character_cache = None
        self._fib()
        self.table = read_stream(ole, self.table_name, limits)
        self._pieces()
        self._sections()
        self._bins()
        self.styles = Styles(self, _span, _u16)

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
        if flags & 0x0100:
            raise EncryptedDocumentError('encrypted or obfuscated DOC is not supported')
        version = _u16(self.word, 2)
        versions = {0xC1: 93, 0xD9: 108, 0x101: 136, 0x10C: 164, 0x112: 183}
        if _u16(self.word, 32) != 14 or _u16(self.word, 62) != 22:
            raise InvalidDocumentError('invalid DOC FIB layout')
        count = _u16(self.word, 152)
        self.budget.record(count)
        self.pairs = _span(self.word, 154, count * 8)
        extension = 154 + count * 8
        csw_new = _u16(self.word, extension)
        fib_end = extension + 2 + csw_new * 2
        if csw_new:
            _span(self.word, extension + 2, csw_new * 2)
            version = _u16(self.word, extension + 2)
        self.fib_version = version
        if version not in versions:
            raise UnsupportedFormatError('unsupported DOC FIB version')
        if count < versions[version]:
            raise InvalidDocumentError('truncated DOC FIB offset array')
        self.counts = [_u32(self.word, 64 + i * 4) for i in (3, 4, 5, 7, 8, 9, 10)]
        if any(n & 0x80000000 for n in self.counts):
            raise InvalidDocumentError('negative DOC story length')
        self.total = sum(self.counts)
        if self.total > self.limits.max_text_chars:
            raise LimitExceededError('DOC text limit exceeded')
        cbmac = _u32(self.word, 64)
        if cbmac < fib_end or cbmac > len(self.word):
            raise InvalidDocumentError('invalid DOC cbMac')
        self.word = memoryview(self.word)[:cbmac]
        self.table_name = '1Table' if flags & 0x0200 else '0Table'
        # MS-DOC FibBase: bit 12 is fExtChar; fFarEast is bit 14.
        if flags & 0x4000:
            self.warn(diagnostic_warning('doc_far_east_doc_flag_is_set_language_specific_legacy', 'Far East DOC flag is set; language-specific legacy encoding is not interpreted.'))

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
            self.warn(diagnostic_warning('doc_piece_table_contains_cps_outside_the_declared_stories_these', 'Piece table contains CPs outside the declared stories; these are excluded.'))
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

    def _sections(self):
        # MS-DOC 2.8.26: aCP[i] starts a section, so aCP[i] - 1 is
        # its predecessor's section mark. Other U+000C characters are page
        # breaks. SEDs are 12 bytes; section layout (SEPX) is not needed here.
        plc = self.table_part(6)  # FibRgFcLcb97.fcPlcfSed
        self.section_ends = set()
        if not plc:
            return
        if len(plc) < 4 or (len(plc) - 4) % 16:
            raise InvalidDocumentError('invalid DOC section PLC size')
        count = (len(plc) - 4) // 16
        self.budget.record(count)  # Bound traversal and the set before allocation.
        previous = -1
        for i in range(count + 1):
            cp = _u32(plc, i * 4)
            if cp >= 0x7FFFFFFF or cp <= previous or (i == 0 and cp != 0):
                raise InvalidDocumentError('invalid DOC section CP order or range')
            if i == count:
                # The final sentinel may extend into/beyond auxiliary stories;
                # it does not begin a section and must never split those stories.
                if cp < self.counts[0]:
                    raise InvalidDocumentError('DOC sections do not cover the main story')
            elif i:
                if cp >= self.counts[0]:
                    raise InvalidDocumentError('DOC section starts outside the main story')
                if self.text[(cp - 1) * 2:cp * 2] != b'\x0c\0':
                    raise InvalidDocumentError('DOC section boundary has no section mark')
                self.section_ends.add(cp - 1)
            previous = cp

    def _bins(self):
        plc = self.table_part(13)
        self.bin_fcs, self.bin_pages = [], []
        if not plc:
            self.warn(diagnostic_warning('doc_paragraph_formatting_is_absent_table_structure_cannot_be_established', 'Paragraph formatting is absent; table structure cannot be established.'))
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
                self.warn(diagnostic_warning('doc_some_paragraphs_have_no_papx_coverage_their_table_membership', 'Some paragraphs have no PAPX coverage; their table membership is unknown.'))
            return 0, memoryview(b'')
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
                    groups.append((0, memoryview(b'')))
                    continue
                if off < front or off >= 511:
                    raise InvalidDocumentError('invalid DOC PAPX offset')
                cb = page[off]
                start, size = (off + 1, cb * 2 - 1) if cb else (off + 2, page[off + 1] * 2)
                if size < 2 or start + size > 511:
                    raise InvalidDocumentError('invalid DOC PAPX size')
                groups.append((_u16(page, start), _span(page, start + 2, size - 2)))
            self.pages[pn] = fcs, groups
        fcs, groups = self.pages[pn]
        j = bisect_right(fcs, fc) - 1
        if j < 0 or j >= len(groups):
            raise InvalidDocumentError('DOC PAPX bin does not cover its paragraph')
        return groups[j]

    def _sprms(self, group, *, allow_padding=True):
        pos = 0
        while pos < len(group):
            # PAPX can have one alignment byte after its last Prl.
            if allow_padding and len(group) - pos == 1 and group[pos] == 0:
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
        trail, seen, fallbacks = [], set(), []
        external_group, first_index = False, 0
        while True:
            consumed = 0
            for index, (op, arg) in enumerate(
                    self._sprms(group, allow_padding=not external_group), first_index):
                consumed += 2 + len(arg)
                if op in (0x560B, 0x5664):
                    props.condition_known &= _u16(arg) in (0, 1)
                if op == 0x740A:
                    props.table_look = _u16(arg, 2)
                    props.condition_known &= not bool(props.table_look & 0xF800)
                elif op == 0x3404:
                    props.table_header = bool(arg[0])
                    props.condition_known &= arg[0] in (0, 1)
                elif op == 0x4600:
                    props.style = _u16(arg)
                    props.frame = self.styles.frame(props.style)
                    props.outline = self.styles.outline(props.style)
                elif op == 0x2640:
                    value = outline_level(arg)
                    if not 1 <= props.style <= 9:
                        props.outline = value
                elif op in (0xC601, 0x2602):
                    raise UnsupportedFormatError('DOC paragraph style permutation/increment is unsupported')
                elif op == 0x563A:
                    table_style = _u16(arg)
                    props.applied_table_style = table_style
                    styles = self.styles.styles
                    # MS-DOC 2.6.3: invalid/non-table references mean Normal Table.
                    if (table_style >= len(styles) or styles[table_style] is None
                            or styles[table_style][0] != 3):
                        table_style = 11
                    props.identity = replace(props.identity, style=table_style)
                    self.warn(diagnostic_warning('doc_table_styles_hidden_text_is_evaluated_only_for_supported', 'Table styles: hidden text is evaluated only for supported contexts; other table-style formatting is not modeled.'))
                elif op == 0x2416:
                    props.in_table = bool(arg[0])
                elif op == 0x2417:
                    props.row_end = bool(arg[0])
                elif op in (0x6649, 0x664A):
                    value = struct.unpack('<i', arg)[0]
                    props.depth = value if op == 0x6649 else props.depth + value
                    if props.depth < 0:
                        raise InvalidDocumentError('negative DOC table depth')
                    if props.depth > self.limits.max_depth:
                        raise LimitExceededError('DOC table depth limit exceeded')
                elif op == 0x244B:
                    props.inner_cell = bool(arg[0])
                elif op == 0x244C:
                    props.inner_ttp = bool(arg[0])
                elif op == 0x560B:
                    props.bidi = bool(_u16(arg))
                elif op == 0x5664:
                    props.bidi90 = bool(_u16(arg))
                elif op in (0x6646, 0x646B):
                    # MS-DOC 2.6.2: HugePapx is effective only in first position.
                    if op == 0x6646 and index:
                        continue
                    offset = _u32(arg)
                    if offset in seen:
                        raise InvalidDocumentError('cyclic DOC external PAPX reference')
                    if len(trail) >= self.limits.max_depth:
                        raise LimitExceededError('DOC property indirection depth limit exceeded')
                    if self.data is None:
                        self.data = read_stream(self.ole, 'Data', self.limits)
                    length = _u16(self.data, offset)
                    if not 10 <= length <= 0x3FA2:
                        raise InvalidDocumentError('invalid DOC external PrcData length')
                    target = _span(self.data, offset + 2, length)
                    if op == 0x646B:
                        # A reader may decline PTableProps. Keep its unprocessed
                        # tail only if the trial chain provides no cell geometry.
                        saved = replace(props, edges=props.edges[:], flags=props.flags[:])
                        fallbacks.append((saved, group[consumed:], external_group, index + 1, len(trail)))
                    group = target
                    external_group, first_index = True, 0
                    seen.add(offset)
                    trail.append(offset)
                    break
                elif op == 0x6645:
                    self.warn(diagnostic_warning('doc_legacy_external_papx_properties_are_unsupported_available_inline_properties', 'Legacy external PAPX properties are unsupported; available inline properties are used.'))
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
                elif (change := frame_change(op, arg)) is not None:
                    props.frame = replace(props.frame, **{change[0]: change[1]})
                elif apply_table(props, op, arg, self.warn):
                    pass
                elif op == 0xD606:
                    self.warn(diagnostic_warning('doc_legacy_table_geometry_is_unsupported_explicit_cell_marks_are', 'Legacy table geometry is unsupported; explicit cell marks are retained.'))
                elif op in (0xF614, 0xF617, 0xF618, 0xD635, 0xF661) or (op == 0x3615 and arg[0]):
                    self.warn(diagnostic_warning('doc_preferred_table_widths_and_automatic_table_layout_are_not', 'Preferred table widths and automatic table layout are not evaluated; explicit cell geometry is used.'))
            else:
                if not props.flags and fallbacks:
                    saved, group, external_group, first_index, restore_depth = fallbacks.pop()
                    for offset in trail[restore_depth:]:
                        seen.remove(offset)
                    del trail[restore_depth:]
                    for name in props.__dataclass_fields__:
                        setattr(props, name, getattr(saved, name))
                    self.warn(diagnostic_warning('doc_external_table_properties_supplied_no_supported_cell_geometry_inline', 'External table properties supplied no supported cell geometry; inline fallback properties are used.'))
                    continue
                return

    def properties(self, cp):
        if self.paragraph_cache is not None and self.paragraph_cache[0] == cp:
            return self.paragraph_cache[1]
        piece = self.pieces[bisect_right(self.cps, cp) - 1]
        style, group = self._papx(piece.fc + (cp - piece.cp) * piece.width)
        props = _Props(style=style, frame=self.styles.frame(style), outline=self.styles.outline(style))
        self._apply(props, group)
        if piece.prm & 1:
            self._apply(props, self.prcs[piece.prm >> 1])
        elif piece.prm:
            # MS-DOC Prm0: table flags and frame properties use the same operands as
            # their full Sprms and override PAPX, including explicit zero.
            isprm = (piece.prm >> 1) & 0x7F
            if isprm == 0x04:
                raise UnsupportedFormatError('DOC paragraph style increment is unsupported')
            op = {0x18: 0x2416, 0x19: 0x2417, 0x1D: 0x261B,
                  0x25: 0x2423, 0x32: 0x2430, 0x78: 0x2640}.get(isprm)
            if op is not None:
                self._apply(props, struct.pack('<HB', op, piece.prm >> 8))
            elif isprm not in (0x41, 0x43, 0x53, 0x5C, 0x75):
                self.warn(diagnostic_warning('doc_this_compact_piece_formatting_prm0_property_is_not_evaluated', 'This compact piece formatting (Prm0) property is not evaluated.'))
        self.paragraph_cache = cp, props
        return props

    def _symbol_modifiers(self, group):
        return character_ops(self, group)

    def _symbol_chpx(self, fc):
        if self.chpx_bins is None:
            plc = self.table_part(12)
            fcs, pages = [], []
            if plc:
                if len(plc) < 4 or (len(plc) - 4) % 8:
                    raise InvalidDocumentError('invalid DOC character bin table')
                count = (len(plc) - 4) // 8
                self.budget.record(count)
                fcs = [_u32(plc, i * 4) for i in range(count + 1)]
                _ascending(fcs)
                pages = [_u32(plc, (count + 1 + i) * 4) & 0x3FFFFF for i in range(count)]
            self.chpx_bins = fcs, pages
        fcs, pages = self.chpx_bins
        i = bisect_right(fcs, fc) - 1
        self.character_coverage_known = 0 <= i < len(pages)
        if i < 0 or i >= len(pages):
            if pages:
                self.warn(diagnostic_warning('doc_some_characters_have_no_chpx_coverage_symbol_and_visibility', 'Some characters have no CHPX coverage; symbol and visibility properties may be missing.'))
            return ()
        pn = pages[i]
        if pn not in self.chpx_pages:
            page = _span(self.word, pn * 512, 512)
            count = page[511]
            if not 1 <= count <= 101:
                raise InvalidDocumentError('invalid DOC CHPX FKP run count')
            self.budget.record(count)
            starts = [_u32(page, j * 4) for j in range(count + 1)]
            _ascending(starts)
            front = (count + 1) * 4 + count
            groups, shared = [], {}
            for j in range(count):
                offset = page[(count + 1) * 4 + j] * 2
                if not offset:
                    groups.append(())
                    continue
                if offset < front or offset >= 511 or offset + 1 + page[offset] > 511:
                    raise InvalidDocumentError('invalid DOC CHPX offset or size')
                if offset not in shared:
                    shared[offset] = self._symbol_modifiers(
                        _span(page, offset + 1, page[offset]))
                groups.append(shared[offset])
            self.chpx_pages[pn] = starts, groups
        starts, groups = self.chpx_pages[pn]
        j = bisect_right(starts, fc) - 1
        if j < 0 or j >= len(groups):
            raise InvalidDocumentError('DOC CHPX bin does not cover its character')
        return groups[j]

    def _symbol_font(self, index):
        if self.symbol_fonts is None:
            data = self.table_part(15)  # SttbfFfn: byte-sized FFNs, Unicode names.
            fonts = []
            if data:
                count = _u16(data)
                if count > 0x7FF0 or _u16(data, 2):
                    raise InvalidDocumentError('invalid DOC font table header')
                self.budget.record(count)
                pos = 4
                for _ in range(count):
                    size = _span(data, pos, 1)[0]
                    font = _span(data, pos + 1, size)
                    names = bytes(_span(font, 39, size - 39))
                    if len(names) < 2 or len(names) % 2:
                        raise InvalidDocumentError('invalid DOC font name size')
                    try:
                        names = names.decode('utf-16le')
                    except UnicodeDecodeError:
                        raise InvalidDocumentError('invalid DOC font name encoding') from None
                    strings = names.split('\0')
                    # ixchSzAlt is measured in UTF-16 units, not Python chars.
                    alt = font[4]
                    if (not strings[0] or strings[-1] != '' or
                            len(strings) != (3 if alt else 2) or
                            (alt and (not strings[1] or
                             alt != len(strings[0].encode('utf-16le')) // 2 + 1))):
                        raise InvalidDocumentError('invalid DOC font names or alternate index')
                    fonts.append((font[3], strings[0].casefold()))
                    pos += size + 1
                if pos != len(data):
                    raise InvalidDocumentError('unexpected trailing DOC font table bytes')
            else:
                self.warn(diagnostic_warning('doc_symbol_font_table_is_absent_symbol_codes_are_retained', 'Symbol font table is absent; symbol codes are retained without font interpretation.'))
            self.symbol_fonts = fonts
        if not self.symbol_fonts and not self.pair(15)[1]:
            return None
        if index >= len(self.symbol_fonts):
            raise InvalidDocumentError('DOC symbol references a missing font')
        return self.symbol_fonts[index]

    def _character_props(self, cp, paragraph_style, table_hidden=False):
        piece = self.pieces[bisect_right(self.cps, cp) - 1]
        operations = self._symbol_chpx(piece.fc + (cp - piece.cp) * piece.width)
        if piece.prm not in self.symbol_prms:
            group = b''
            if piece.prm & 1:
                group = self.prcs[piece.prm >> 1]
            elif piece.prm:
                op = {0x41: 0x0800, 0x43: 0x0802, 0x53: 0x2A33,
                      0x5C: 0x083C, 0x75: 0x0855}.get((piece.prm >> 1) & 0x7F)
                if op is not None:
                    group = struct.pack('<HB', op, piece.prm >> 8)
            self.symbol_prms[piece.prm] = self._symbol_modifiers(group)
        key = paragraph_style, table_hidden, operations, piece.prm
        if self.character_cache is not None and self.character_cache[0] == key:
            return self.character_cache[1]
        para_hidden = self.styles.hidden(paragraph_style, 1, table_hidden)
        style_hidden = para_hidden
        props = {'hidden': para_hidden}
        char_style = 10
        for op, arg in operations + self.symbol_prms[piece.prm]:
            if op == 0x6A09:
                props['symbol'] = (_u16(arg), _u16(arg, 2))
            elif op == 0x4A30:
                char_style = _u16(arg)
                style_hidden = self.styles.hidden(char_style, 2, para_hidden)
                props['hidden'] = style_hidden
            elif op == 0x2A33:
                props['hidden'] = style_hidden = para_hidden
                char_style = 10
            elif op == 0xCA47:
                if char_style == 10:
                    compare = False
                    for subop, subarg in self._symbol_modifiers(arg[1:]):
                        if subop == 0x083C:
                            compare = toggle(subarg, style_hidden)
                    if props['hidden'] == compare:
                        props['hidden'] = para_hidden
            else:
                name = {0x083C: 'hidden', 0x0800: 'deleted',
                        0x0802: 'field_hidden', 0x0855: 'special'}[op]
                if op == 0x0855 and arg in (128, 129) and not self.styles.present:
                    props[name] = None
                    self.warn(diagnostic_warning('doc_style_relative_cfspec_is_not_resolved_without_a_stylesheet', 'Style-relative CFSpec is not resolved without a stylesheet; available symbol codes are retained.'))
                else:
                    props[name] = toggle(arg, style_hidden if op == 0x083C else False)
        self.character_cache = key, props
        return props

    def _symbol_char(self, props):
        if 'symbol' not in props or props.get('special') is False:
            return None
        font_index, code = props['symbol']
        font = self._symbol_font(font_index)
        # CSymbolOperand.xchar is Unicode, never an ANSI code-page byte.
        # Do not guess Wingdings/Symbol mappings or borrow unlicensed tables.
        if (0xE000 <= code <= 0xF8FF or
                (font and (font[0] == 2 or font[1] in
                 ('symbol', 'wingdings', 'wingdings 2', 'wingdings 3', 'webdings')))):
            self.warn(diagnostic_warning('doc_font_dependent_symbol_codes_are_retained_verbatim_no_font', 'Font-dependent symbol codes are retained verbatim; no font-specific Unicode glyph mapping is applied.'))
        if 0xD800 <= code <= 0xDFFF:
            self.warn(diagnostic_warning('doc_invalid_symbol_unicode_surrogate_was_replaced_with_u_fffd', 'Invalid symbol Unicode surrogate was replaced with U+FFFD.'))
            return '\ufffd'
        if code < 32:
            self.warn(diagnostic_warning('doc_symbol_control_code_is_retained_literally_not_interpreted_as', 'Symbol control code is retained literally, not interpreted as a DOC delimiter.'))
        return chr(code)

    def _observe_note_reference(self, cp, ch, props, *, fields, coverage_known,
                                styles_present, table_known):
        """Observe a note before field transitions, preserving its marker policy."""
        flags = [name for name in ('hidden', 'deleted') if props.get(name)]
        if props.get('field_hidden'):
            flags.append('field_hidden')
        if fields and not all(fields):
            flags.append('field_instruction')
        if not coverage_known or not styles_present or not table_known:
            flags.append('unknown')
        automatic = self.note_references[cp] == 'automatic'
        if automatic and ch != '\x02':
            raise InvalidDocumentError('DOC automatic note reference has no U+0002 marker')
        if automatic and props.get('special') is not True:
            if 'unknown' not in flags:
                flags.append('unknown')
            self.warn(diagnostic_warning('doc_note_reference_cfspec_is_not_established_its_output_anchor', 'Note reference CFSpec is not established; its output anchor is unresolved.'))
        else:
            self.paragraph_anchors.append(cp)
        self.note_visibility[cp] = flags

    def _observe_comment_marker(self, cp, props, *, fields, coverage_known,
                                styles_present, table_known):
        """Observe body/reference markers without borrowing note marker policy."""
        special = props.get('special')
        if special is False or ('special' not in props and coverage_known):
            raise InvalidDocumentError('DOC comment marker has CFSpec=false')
        known = special is True
        self.comment_marker_known[cp] = known
        if not known:
            self.warn(diagnostic_warning('doc_comment_marker_cfspec_is_unknown_its_unproven_body', 'DOC comment marker CFSpec is unknown; its unproven body is omitted.'))
        if cp in self.comment_references:
            flags = [name for name in ('hidden', 'deleted', 'field_hidden') if props.get(name)]
            if fields and not all(fields):
                flags.append('field_instruction')
            if not coverage_known or not styles_present or not table_known:
                flags.append('unknown')
            self.note_visibility[cp] = flags
            # CPs are unique in the scan. A custom note may already
            # have appended this CP; dictionary membership is constant time.
            if known and cp not in self.note_references:
                self.paragraph_anchors.append(cp)

    def clean(self, start, end, mark_cp=None, *, table_hidden=False, table_known=True):
        paragraph_style = self.properties(end if mark_cp is None else mark_cp).style
        self.styles.hidden(paragraph_style, 1, table_hidden)  # Also validate empty paragraphs.
        if mark_cp is None:
            mark_props = self._character_props(end, paragraph_style, table_hidden)
            if any(mark_props.get(name) for name in ('hidden', 'deleted', 'field_hidden')):
                self.warn(diagnostic_warning('doc_hidden_or_deleted_paragraph_cell_marks_retain_their_structural', 'Hidden or deleted paragraph/cell marks retain their structural boundaries; revision merging is not modeled.'))
        self.paragraph_anchors = []
        raw = bytes(self.text[start * 2:end * 2])
        try:
            value = raw.decode('utf-16le')
        except UnicodeDecodeError:
            self.warn(diagnostic_warning('doc_invalid_utf_16_was_replaced_with_u_fffd', 'Invalid UTF-16 was replaced with U+FFFD.'))
            value = raw.decode('utf-16le', errors='replace')
        out = []
        next_cp = start
        for ch in value:
            cp = next_cp
            next_cp += 2 if ord(ch) > 0xFFFF else 1
            # Reference observation precedes field transitions and text filtering.
            # Keep separate property lookups: each updates character coverage.
            if cp in self.note_references:
                props = self._character_props(cp, paragraph_style, table_hidden)
                self._observe_note_reference(
                    cp, ch, props, fields=self.fields,
                    coverage_known=self.character_coverage_known,
                    styles_present=self.styles.present, table_known=table_known)
            if cp in self.comment_markers:
                props = self._character_props(cp, paragraph_style, table_hidden)
                self._observe_comment_marker(
                    cp, props, fields=self.fields,
                    coverage_known=self.character_coverage_known,
                    styles_present=self.styles.present, table_known=table_known)
            if ch == '\x13':
                if len(self.fields) >= self.limits.max_depth:
                    raise LimitExceededError('DOC field nesting limit exceeded')
                self.fields.append(False)
                self.warn(diagnostic_warning('doc_fields_use_stored_results_field_instructions_are_not_evaluated', 'Fields use stored results; field instructions are not evaluated.'))
                continue
            if ch == '\x14':
                if self.fields:
                    self.fields[-1] = True
                else:
                    self.warn(diagnostic_warning('doc_unbalanced_doc_field_delimiters_were_encountered', 'Unbalanced DOC field delimiters were encountered.'))
                continue
            if ch == '\x15':
                if self.fields:
                    self.fields.pop()
                else:
                    self.warn(diagnostic_warning('doc_unbalanced_doc_field_delimiters_were_encountered', 'Unbalanced DOC field delimiters were encountered.'))
                continue
            if self.fields and not all(self.fields):
                continue
            props = self._character_props(cp, paragraph_style, table_hidden)
            if any(props.get(name) for name in ('hidden', 'deleted', 'field_hidden')):
                continue
            if ch == '(':
                symbol = self._symbol_char(props)
                if symbol is not None:
                    out.append(symbol)
                    continue
            if ch in ('\x01', '\x08'):
                self.warn(diagnostic_warning('doc_embedded_objects_and_drawings_are_omitted_textbox_stories_are', 'Embedded objects and drawings are omitted; textbox stories are extracted separately.'))
            elif ch in ('\x02', '\x05'):
                if ch == '\x02':
                    self.warn(diagnostic_warning('doc_note_comment_reference_marks_are_omitted_note_stories_are', 'Note/comment reference marks are omitted; note stories are extracted separately.'))
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
                self.warn(diagnostic_warning('doc_unsupported_control_characters_were_omitted_from_extracted_text', 'Unsupported control characters were omitted from extracted text.'))
        return ''.join(out)

    def paragraphs(self, start, count):
        # Structural prepass only: TTP follows its cell text, so effective row
        # context must be established before clean observes text or note flags.
        # Each CP is scanned once; retained metadata is per paragraph, not CP.
        paragraphs = []
        pending = []

        def close_incomplete():
            row = pending.pop()
            if row:
                self.warn(diagnostic_warning('doc_incomplete_table_row_has_no_proven_table_style_context', 'Incomplete table row has no proven table-style context; available text is retained.'))

        def add(begin, end, mark, mark_cp):
            props = self.properties(mark_cp)
            depth = props.depth or (1 if props.in_table else 0)
            if props.inner and depth < 2:
                raise InvalidDocumentError('DOC inner table marker has no nested table depth')
            if depth > self.limits.max_depth:
                raise LimitExceededError('DOC table depth limit exceeded')
            while len(pending) > depth:
                close_incomplete()
            while len(pending) < depth:
                self.budget.record()
                pending.append([])
            self.budget.record()
            entry = [begin, end, mark, mark_cp, props, False, not depth]
            paragraphs.append(entry)
            if depth:
                self.budget.record()
                pending[-1].append(entry)
                row_end = props.row_end if depth == 1 else props.inner_ttp
                if row_end:
                    hidden = self.styles.table_hidden(props.applied_table_style)
                    for item in pending[-1]:
                        item[5], item[6] = hidden, True
                    pending[-1].clear()

        begin = start
        for cp in range(start, start + count):
            unit = self.text[cp * 2] | self.text[cp * 2 + 1] << 8
            if unit in (7, 13) or cp in self.section_ends:
                add(begin, cp, unit, cp)
                begin = cp + 1
        if begin < start + count:
            self.warn(diagnostic_warning('doc_a_doc_story_has_no_final_paragraph_mark_trailing', 'A DOC story has no final paragraph mark; trailing text is retained.'))
            add(begin, start + count, 0, start + count - 1)
        while pending:
            close_incomplete()
        apply_conditions(self, paragraphs)
        if start == 0 and count == self.counts[0] and self.comment_references:
            self._comment_selection_ranges(paragraphs)
        for begin, end, mark, mark_cp, props, hidden, known in paragraphs:
            self.paragraph_cache = mark_cp, props
            yield self.clean(begin, end, mark_cp if mark == 0 else None,
                             table_hidden=hidden, table_known=known), mark_cp, mark

    def _prepare_notes(self):
        self.note_ranges = {}
        for index, ref_pair, text_pair in ((1, 2, 3), (4, 46, 47)):
            start, count = sum(self.counts[:index]), self.counts[index]
            refs, texts = self.table_part(ref_pair), self.table_part(text_pair)
            if not count and not refs and not texts:
                continue
            ranges = decode_note_ranges(refs, texts, self.counts[0],
                                        memoryview(self.text)[start * 2:(start + count) * 2],
                                        self.limits, record=self.budget.record, warn=self.warn)
            self.note_ranges[index] = ranges
            for note in ranges or ():
                if note.source_cp is not None:
                    if note.source_cp in self.note_references:
                        raise InvalidDocumentError('DOC note references share a source CP')
                    if (note.reference_kind == 'automatic' and
                            self.text[note.source_cp * 2:note.source_cp * 2 + 2] != b'\x02\0'):
                        raise InvalidDocumentError('DOC automatic note reference has no U+0002 marker')
                    self.note_references[note.source_cp] = note.reference_kind

    def _comment_paragraph_known(self, cp):
        piece = self.pieces[bisect_right(self.cps, cp) - 1]
        fc = piece.fc + (cp - piece.cp) * piece.width
        return 0 <= bisect_right(self.bin_fcs, fc) - 1 < len(self.bin_pages)

    def _prepare_comments(self):
        start, count = sum(self.counts[:3]), self.counts[3]
        parts = {i: self.table_part(i) for i in (4, 5, 36, 37, 42, 43)}
        if self.fib_version >= 0x101:
            parts[112] = self.table_part(112)
        self.comment_ranges = decode_comments(
            parts, memoryview(self.text)[:self.counts[0] * 2],
            memoryview(self.text)[start * 2:(start + count) * 2], self.limits,
            record=self.budget.record, warn=self.warn, source_text_count=self.total)
        for comment in self.comment_ranges:
            self.budget.record(3)
            self.comment_references[comment.source_cp] = comment
            self.comment_markers[comment.source_cp] = comment.ordinal
            self.comment_markers[start + comment.body_start] = comment.ordinal
            end_cp = start + comment.body_end - 1
            known = self._comment_paragraph_known(end_cp)
            self.comment_structure_known[comment.ordinal] = known
            if not known:
                self.warn(diagnostic_warning('doc_comment_final_paragraph_has_unknown_table_membership_its', 'DOC comment final paragraph has unknown table membership; its body is omitted.'))
            end_props = self.properties(end_cp)
            if end_props.in_table or end_props.depth or end_props.inner:
                raise InvalidDocumentError('DOC comment body final paragraph is inside a table')

    def _comment_selection_ranges(self, paragraphs):
        # Prefix counts and source regions make overlapping range validation
        # O(log paragraphs) each, without walking each selected paragraph again.
        # Regions break only on explicit cell/row/section marks or depth changes;
        # they never infer table identity, output-grid positions, or page layout.
        self.budget.record(4 * len(paragraphs) + 1)
        starts = [p[0] for p in paragraphs]
        unsafe = [0]
        regions = []
        completed_cells = set()
        region, previous_depth, boundary = 0, None, False
        fields = False
        for begin, end, mark, mark_cp, props, _, known in paragraphs:
            depth = props.depth or (1 if props.in_table else 0)
            if boundary or depth != previous_depth:
                region += 1
            regions.append(region)
            covered = known and self._comment_paragraph_known(mark_cp)
            ordinary = covered
            for cp in range(begin, end):
                unit = self.text[cp * 2] | self.text[cp * 2 + 1] << 8
                fields |= unit in (19, 20, 21)
                ordinary &= unit >= 32 or unit in (5, 9)
            unsafe.append(unsafe[-1] + (not ordinary))
            if covered and ((depth == 1 and mark == 7 and not props.row_end)
                            or (depth > 1 and mark == 13 and props.inner_cell and not props.inner_ttp)):
                completed_cells.add(region)
            boundary = (mark != 13 or props.row_end or props.inner_cell or props.inner_ttp
                        or mark_cp in self.section_ends)
            previous_depth = depth
        for source in self.comment_ranges:
            begin, end = source.selection_start, source.selection_end
            if begin is None:
                continue
            if begin == end:
                self.comment_selections[source.source_cp] = (begin, end)
                continue
            i = bisect_right(starts, begin) - 1
            j = bisect_right(starts, end - 1) - 1
            proven = not fields and i >= 0 and j >= i
            if proven:
                _, last_end, mark, mark_cp, props, _, _ = paragraphs[j]
                # Ordinary paragraph CR may be selected. Cell/TTP/section marks
                # require further selection rules and are never included here.
                include_cr = (mark == 13 and not (props.row_end or props.inner_cell or props.inner_ttp)
                              and mark_cp not in self.section_ends)
                depth = props.depth or (1 if props.in_table else 0)
                proven = (regions[i] == regions[j] and unsafe[j + 1] == unsafe[i]
                          and (i == j or not depth or regions[i] in completed_cells)
                          and end <= last_end + include_cr
                          and not 0xdc00 <= _u16(self.text, begin * 2) <= 0xdfff
                          and not 0xd800 <= _u16(self.text, (end - 1) * 2) <= 0xdbff)
            if proven:
                self.comment_selections[source.source_cp] = (begin, end)
            else:
                self.warn(diagnostic_warning('doc_comment_selection_validity_is_unproven_source_selection_bounds', 'DOC comment selection validity is unproven; source selection bounds are omitted.'))

    def _parse_comments(self, start):
        blocks = []
        retained = {}
        for source in self.comment_ranges:
            block_start = len(blocks)
            assembler = _Tables(self, blocks)
            for text, cp, mark in self.paragraphs(start + source.body_start,
                                                  source.body_end - source.body_start):
                assembler.add(text, mark, self.properties(cp))
            assembler.finish()
            self._end_fields()
            if not (self.comment_structure_known[source.ordinal]
                    and self.comment_marker_known.get(source.source_cp)
                    and self.comment_marker_known.get(start + source.body_start)):
                del blocks[block_start:]
                continue
            self.budget.record()
            self.budget.text(len(source.author or '') + len(source.initials))
            begin, end = self.comment_selections.get(source.source_cp, (None, None))
            depth, parent = source.reply_depth, source.parent_ordinal
            if parent is not None and retained.get(parent) is None:
                depth = parent = None
                self.warn(diagnostic_warning('doc_comment_reply_ancestry_is_unavailable_relationship_metadata_is', 'DOC comment reply ancestry is unavailable; relationship metadata is omitted without dropping the body.'))
            retained[source.ordinal] = depth
            self.document.comments.append(Comment(
                ordinal=source.ordinal, body=CommentBodyRange('comment_text', block_start, len(blocks)),
                author=source.author, initials=source.initials, source_cp=source.source_cp,
                selection_start=begin, selection_end=end,
                reply_depth=depth, parent_ordinal=parent,
                visibility=list(self.note_visibility.get(source.source_cp, ['unknown']))))
        if self.document.comments:
            self.budget.text(_projection_size(blocks))
            self.document.story_blocks['comment_text'] = blocks
            self.document.comment_text = _projection(blocks)

    def _bind_note_anchors(self, cps, target):
        if cps:
            self.note_object_cps.setdefault(id(target), []).extend(cps)
            for cp in cps:
                self.note_targets[cp] = target

    def _flatten_note_anchors(self, paragraphs, cell):
        for paragraph in paragraphs:
            self._bind_note_anchors(self.note_object_cps.pop(id(paragraph), ()), cell)

    def _resolve_note_paths(self):
        wanted = {}
        for note in chain(self.document.notes, self.document.comments):
            target = self.note_targets.get(note.source_cp)
            if target is not None:
                wanted.setdefault(id(target), []).append(note)
        if not wanted:
            if self.document.notes or self.document.comments:
                self.warn(diagnostic_warning('doc_note_comment_output_anchors_are_unresolved_source_cps_are', 'Note/comment output anchors are unresolved; source CPs are not output offsets.'))
            return
        def children(node):
            if isinstance(node, Table):
                for row_index, row in enumerate(node.rows):
                    for column, cell in enumerate(row):
                        yield cell, ('rows', row_index, column)
            elif isinstance(node, (Document, Cell)):
                for index, block in enumerate(node.blocks):
                    yield block, ('blocks', index)

        # Lazy sibling iterators and one mutable path keep traversal storage
        # proportional to depth, even for wide tables below deep nesting.
        path = []
        stack = [(children(self.document), 0)]
        while stack and wanted:
            iterator, base = stack[-1]
            del path[base:]
            entry = next(iterator, None)
            if entry is None:
                stack.pop()
                continue
            block, steps = entry
            path.extend(steps)
            matched = wanted.pop(id(block), ())
            if matched:
                # Charge all copies before allocating or publishing any of
                # them, including multiple references in the same container.
                self.budget.record(len(path) * len(matched))
                for note in matched:
                    note.anchor_path = list(path)
            if isinstance(block, (Table, Cell)):
                stack.append((children(block), len(path)))
        for note in chain(self.document.notes, self.document.comments):
            if note.anchor_path is None and note.source_cp is not None:
                if 'unknown' not in note.visibility:
                    note.visibility.append('unknown')
                self.warn(diagnostic_warning('doc_some_note_comment_references_could_not_be_linked_to', 'Some note/comment references could not be linked to an output paragraph or cell.'))

    def parse(self):
        self._prepare_notes()
        self._prepare_comments()
        assembler = _Tables(self)
        for text, cp, mark in self.paragraphs(0, self.counts[0]):
            assembler.add(text, mark, self.properties(cp), self.paragraph_anchors)
        assembler.finish()
        self._end_fields()
        start = self.counts[0]
        stories = {}
        note_stories = set()
        for index, count in enumerate(self.counts[1:], 1):
            if count:
                if index == 3:
                    self._parse_comments(start)
                else:
                    attr = {1: 'footnotes', 2: 'headers_footers', 4: 'endnotes',
                            5: 'textboxes', 6: 'textboxes'}[index]
                    blocks = stories.setdefault(attr, [])
                    source_notes = self.note_ranges.get(index)
                    ranges = ([(n.body_start, n.body_end) for n in source_notes]
                              if source_notes is not None else [(0, count)])
                    if source_notes is not None:
                        # The reserved final CP belongs to the legacy story
                        # projection, but never to the last discrete note.
                        ranges.append((count - 1, count))
                    textbox_plc = b''
                    if index in (5, 6):
                        textbox_plc = self.table_part(56 if index == 5 else 58)
                        ranges = live_textbox_ranges(
                            textbox_plc, count, self.limits,
                            record=self.budget.record, warn=self.warn,
                        )
                    for range_index, (begin, end) in enumerate(ranges):
                        if textbox_plc and self.text[(start + end - 1) * 2:(start + end) * 2] != b'\r\0':
                            raise InvalidDocumentError('DOC live textbox has no final paragraph mark')
                        block_start = len(blocks)
                        assembler = _Tables(self, blocks)
                        for text, cp, mark in self.paragraphs(start + begin, end - begin):
                            assembler.add(text, mark, self.properties(cp))
                        assembler.finish()
                        self._end_fields()
                        if source_notes is not None and range_index < len(source_notes):
                            source = source_notes[range_index]
                            self.budget.record()
                            self.document.notes.append(Note(
                                kind='footnote' if index == 1 else 'endnote',
                                ordinal=source.ordinal, source_cp=source.source_cp,
                                reference_kind=source.reference_kind,
                                visibility=list(self.note_visibility.get(source.source_cp, ['unknown'])),
                                body=NoteBodyRange(attr, block_start, len(blocks)),
                            ))
                            note_stories.add(attr)
                    if index in (2, 5, 6):
                        self.warn(diagnostic_warning('doc_header_variants_and_textbox_placement_are_not_modeled', 'Header variants and textbox placement are not modeled.'))
                self._end_fields()
            start += count
        for attr, blocks in stories.items():
            structured = attr in note_stories or any(
                isinstance(block, Table) or block.heading_level is not None for block in blocks)
            size = _projection_size(blocks)
            # Note bodies reference retained blocks; no additional text copy.
            self.budget.text(size if structured else max(0, len(blocks) - 1))
            setattr(self.document, attr, _projection(blocks))
            if structured:
                self.document.story_blocks[attr] = blocks
        self._resolve_note_paths()
        return self.document

    def _end_fields(self):
        if self.fields:
            self.warn(diagnostic_warning('doc_unbalanced_doc_field_delimiters_were_encountered', 'Unbalanced DOC field delimiters were encountered.'))
            self.fields.clear()


def _projection_size(blocks):
    size = max(0, len(blocks) - 1)
    for block in blocks:
        if isinstance(block, Paragraph):
            size += len(block.text)
        else:
            size += max(0, len(block.rows) - 1)
            size += sum(sum(len(c.text) for c in row) + max(0, len(row) - 1)
                        for row in block.rows)
    return size


def _projection(blocks):
    return '\n'.join(b.text if isinstance(b, Paragraph) else
                     '\n'.join('\t'.join(c.text for c in row) for row in b.rows)
                     for b in blocks)


class _Tables:
    """Route CP-ordered paragraphs through an iterative stack of table depths."""
    def __init__(self, doc, destination=None):
        self.doc = doc
        self.destination = doc.document.blocks if destination is None else destination
        self.levels = []

    def add(self, text, mark, props, anchors=()):
        depth = props.depth or (1 if props.in_table else 0)
        if props.inner and depth < 2:
            raise InvalidDocumentError('DOC inner table marker has no nested table depth')
        if depth > self.doc.limits.max_depth:
            raise LimitExceededError('DOC table depth limit exceeded')
        while len(self.levels) > depth:
            self.levels.pop().finish()
        if not depth:
            if mark == 7:
                self.doc.warn(diagnostic_warning('doc_cell_mark_without_table_membership_was_retained_as_a', 'Cell mark without table membership was retained as a paragraph boundary.'))
            self.doc.budget.text(len(text))
            paragraph = Paragraph(text, heading_level=props.outline + 1
                                  if props.outline < 9 and text.strip() else None)
            self.destination.append(paragraph)
            self.doc._bind_note_anchors(anchors, paragraph)
            return
        # A cell can begin with another table, without a preceding paragraph at
        # its own depth. Materialize its enclosing cells, not invented text.
        while len(self.levels) < depth:
            self.doc.budget.record()
            destination = self.destination
            if self.levels:
                parent = self.levels[-1]
                parent.ensure_table()
                destination = parent.paras
            self.levels.append(_TableLevel(self.doc, destination, len(self.levels) + 1))
        self.levels[-1].add(text, mark, props, anchors)

    def finish(self):
        while self.levels:
            self.levels.pop().finish()


class _TableLevel:
    def __init__(self, doc, destination, depth):
        self.doc = doc
        self.destination = destination
        self.depth = depth
        self.table = None
        self.cells = []
        self.paras = []
        self.vertical = {}
        self.row_edges = []
        self.direction = False
        self.identity = TableIdentity()
        self.first_frame = None
        self.previous_frame = None

    def cell(self):
        self.doc.budget.cell()
        complex_cell = any(isinstance(block, Table) or block.heading_level is not None
                           for block in self.paras)
        # Check the retained projection before allocating separators or copies.
        size = _projection_size(self.paras)
        retained_paragraphs = (sum(len(b.text) for b in self.paras if isinstance(b, Paragraph))
                               if complex_cell else 0)
        self.doc.budget.text(size + retained_paragraphs)
        cell = Cell(text=_projection(self.paras), blocks=self.paras if complex_cell else [])
        if not complex_cell:
            self.doc._flatten_note_anchors(self.paras, cell)
        self.cells.append(cell)
        self.paras = []

    def row(self, props, *, complete=True):
        direction = props.bidi or props.bidi90
        if self.table.rows and row_boundary(self.identity, self.direction,
                                            self.previous_frame, props, self.first_frame, complete):
            # Row properties arrive at the TTP, after its cells are buffered.
            # Close only the completed rows; keep this pending row intact.
            self._normalize_grid()
            self.table = Table()
            self.destination.append(self.table)
            self.vertical = {}
            self.row_edges = []
        self.direction = direction
        self.identity = props.identity
        self.previous_frame = self.first_frame
        self.first_frame = None
        if props.edges and len(props.edges) - 1 != len(self.cells):
            self.doc.warn(diagnostic_warning('doc_table_definition_and_cell_marks_disagree_observed_cells_are', 'Table definition and cell marks disagree; observed cells are retained without inferred cells.'))
        self._merge(props)
        self.table.rows.append(self.cells)
        self.row_edges.append(props.edges)
        self.cells = []

    def _merge(self, props):
        cells = self.cells
        flags = props.flags[:len(cells)] + [0] * max(0, len(cells) - len(props.flags))
        anchor = None
        for i, cell in enumerate(cells):
            hm = flags[i] & 3
            if hm in (2, 3):
                anchor = cell
            elif hm == 1 and anchor is not None:
                anchor.col_span += 1
                cell.covered = True
                if cell.text:
                    self.doc.warn(diagnostic_warning('doc_covered_merged_cells_contain_text_their_text_is_retained', 'Covered merged cells contain text; their text is retained at its original coordinate.'))
            else:
                if hm == 1:
                    self.doc.warn(diagnostic_warning('doc_orphan_horizontal_merge_continuation_was_retained_as_a_normal', 'Orphan horizontal merge continuation was retained as a normal cell.'))
                anchor = None
        current = {}
        for i, cell in enumerate(cells):
            if cell.covered:
                continue
            vm = (flags[i] >> 5) & 3
            # Matching boundaries prevent invented vertical spans across different grids.
            key = None
            if len(props.edges) == len(cells) + 1 and i + cell.col_span < len(props.edges):
                key = (props.edges[i], props.edges[i + cell.col_span])
            if vm == 3 and key is not None:
                current[key] = cell
            elif vm == 1 and key in self.vertical:
                previous = self.vertical[key]
                # Equal edge intervals can use different physical cell counts.
                # Column spans are normalized across rows when the table closes.
                previous.row_span += 1
                current[key] = previous
                cell.covered = True
                if cell.text:
                    self.doc.warn(diagnostic_warning('doc_covered_merged_cells_contain_text_their_text_is_retained', 'Covered merged cells contain text; their text is retained at its original coordinate.'))
            elif vm:
                self.doc.warn(diagnostic_warning('doc_vertical_merge_without_a_matching_explicit_grid_was_not', 'Vertical merge without a matching explicit grid was not applied.'))
        self.vertical = current

    def ensure_table(self):
        if self.table is None:
            self.table = Table()
            self.destination.append(self.table)

    def add(self, text, mark, props, anchors=()):
        self.ensure_table()
        row_end = props.row_end if self.depth == 1 else props.inner_ttp
        cell_end = mark == 7 if self.depth == 1 else props.inner_cell
        # At this depth only: a nested table's paragraphs are not its parent's
        # first paragraph. Empty/hidden paragraphs still have frame properties.
        if not row_end and not self.cells and self.first_frame is None:
            self.first_frame = props.frame
        if self.depth > 1 and (props.row_end or mark == 7):
            self.doc.warn(diagnostic_warning('doc_outer_table_markers_at_nested_depth_were_retained_as', 'Outer table markers at nested depth were retained as paragraph boundaries.'))
        paragraph = Paragraph(text, heading_level=props.outline + 1
                                  if props.outline < 9 and text.strip() else None)
        self.doc._bind_note_anchors(anchors, paragraph)
        if row_end:
            # TTP is a separate empty paragraph, not an additional cell.
            if text or self.paras or anchors:
                if text or anchors:
                    self.paras.append(paragraph)
                self.cell()
                self.doc.warn(diagnostic_warning('doc_row_terminator_contains_content_content_is_retained_as_a', 'Row terminator contains content; content is retained as a cell.'))
            if not self.cells:
                self.cell()
            self.row(props)
        elif cell_end:
            self.paras.append(paragraph)
            self.cell()
        else:
            self.paras.append(paragraph)

    def finish(self):
        if self.table is None:
            return
        if self.paras or self.cells:
            self.doc.warn(diagnostic_warning('doc_table_ends_without_a_row_terminator_the_incomplete_row', 'Table ends without a row terminator; the incomplete row is retained.'))
            if self.paras:
                self.cell()
            self.row(_Props(bidi=self.direction, identity=self.identity), complete=False)
        self._normalize_grid()
        self.table = None
        self.vertical = {}
        self.row_edges = []
        self.direction = False
        self.identity = TableIdentity()
        self.first_frame = None
        self.previous_frame = None

    def _normalize_grid(self):
        # A wide physical cell can span boundaries introduced by other rows.
        # Build a grid from explicit cell definitions, never from text or spacing.
        valid = [(row, edges) for row, edges in zip(self.table.rows, self.row_edges)
                 if len(edges) == len(row) + 1 and len(edges) > 1
                 and all(a < b for a, b in zip(edges, edges[1:]))]
        if len(valid) != len(self.table.rows):
            if any(self.row_edges):
                self.doc.warn(diagnostic_warning('doc_incomplete_or_zero_width_table_grids_cannot_be_normalized', 'Incomplete or zero-width table grids cannot be normalized; physical cell coordinates are retained.'))
            return
        if not valid:
            return
        grid = sorted({edge for _, edges in valid for edge in edges})
        indexes = {edge: i for i, edge in enumerate(grid)}
        # Exact source edges only: no rounding/snap-to-grid heuristics. Coordinates
        # outside a physical row are absent, not empty cells or merge continuations.
        # Check before constructing the expanded coordinate matrix.
        extra = sum(len(grid) - 1 - len(row) for row, _ in valid)
        self.doc.budget.cell(extra)
        for row, edges in valid:
            expanded = [Cell(omitted=True) for _ in range(indexes[edges[0]])]
            for i, cell in enumerate(row):
                start = indexes[edges[i]]
                end = indexes[edges[i + 1]]
                if not cell.covered:
                    cell.col_span = indexes[edges[min(i + cell.col_span, len(row))]] - start
                expanded.append(cell)
                expanded.extend(Cell(covered=True) for _ in range(end - start - 1))
            expanded.extend(Cell(omitted=True)
                            for _ in range(len(grid) - 1 - indexes[edges[-1]]))
            row[:] = expanded


def parse_doc_bytes(data: bytes, limits: Limits) -> Document:
    """Extract declared DOC stories and PAPX-backed tables, or raise ParseError.

    CP units (including discarded stories) count against max_text_chars. Record
    budgets include FIB pairs, pieces, PAPX runs, Prls and emitted paragraphs.
    No salvage scan is performed when structural metadata is corrupt.
    """
    with open_ole(data, limits) as ole:
        return _Doc(ole, limits).parse()
