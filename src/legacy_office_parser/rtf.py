"""Bounded RTF text/structure reader, not a layout engine.

Original implementation; reference/research provenance: docs/RTF.md.
The lexer consumes bytes, including opaque binary payloads, before interpretation.
"""
from __future__ import annotations

import codecs
from dataclasses import dataclass, replace

from .diagnostics import diagnostic_warning
from .errors import InvalidDocumentError, LimitExceededError
from .limits import Limits
from .models import Cell, Document, Note, NoteBodyRange, Paragraph, Table

# RTF destination names and charset numbers are format facts, not executable code
# imported from another reader. Unknown starred destinations are also suppressed.
_SKIP = set("""
author title subject keywords company manager operator category comment doccomm
hlinkbase creatim revtim printim buptim
colortbl stylesheet info filetbl revtbl rsidtbl listtable listoverridetable
latentstyles generator xmlnstbl datastore themedata colorschememapping
pict object objdata objclass objname objalias result shppict nonshppict
shprslt sp sn sv background private datafield fontemb fontfile
fldinst fldtype formfield annotation atnauthor atnid atndate
bkmkstart bkmkend xe tc txe rxe pn pntxta pntxtb
ftnsep ftnsepc ftncn aftnsep aftnsepc aftncn
userprops docvar template nextfile htmltag mhtmltag xmlopen xmlclose
xmlattrname xmlattrvalue mmath mmathPict moMath moMathPara
nonesttables
""".split())
_SHAPE_CONTAINERS = {'shp', 'shpinst', 'shpgrp'}
_HEADERS = set('header headerl headerr headerf footer footerl footerr footerf'.split())
# Visibility filters character content, not table coordinates or boundaries.
_STRUCTURAL = set('par sect page intbl itap trowd cellx trleft cell row '
                  'clmgf clmrg clvmgf clvmrg nestcell nestrow'.split())
_CHARS = dict(zip(
    'tab line emdash endash bullet lquote rquote ldblquote rdblquote emspace enspace '
    'qmspace zwj zwnj ltrmark rtlmark'.split(),
    ['\t', '\n', '—', '–', '•', '‘', '’', '“', '”', '\u2003', '\u2002',
     '\u2005', '\u200d', '\u200c', '\u200e', '\u200f'], strict=True,
))
_CHARSETS = {
    77: 'mac_roman', 128: 'cp932', 129: 'cp949', 130: 'cp1361', 134: 'gbk',
    136: 'cp950', 161: 'cp1253', 162: 'cp1254', 163: 'cp1258', 177: 'cp1255',
    178: 'cp1256', 186: 'cp1257', 204: 'cp1251', 222: 'cp874', 238: 'cp1250',
    254: 'cp437', 255: 'cp850',
}


def _letter(b: int) -> bool:
    return 65 <= b <= 90 or 97 <= b <= 122


def _tokens(data: bytes, start: int, limits: Limits):
    """Yield bounded lexical records; binary data is never sliced or decoded."""
    i, records, size = start, 0, len(data)
    while i < size:
        records += 1
        if records > limits.max_records:
            raise LimitExceededError('RTF lexical record limit exceeded')
        b = data[i]
        i += 1
        if b in (123, 125):
            yield ('open' if b == 123 else 'close'), None, None
        elif b in (10, 13):
            continue
        elif b != 92:
            begin = i - 1
            # Bounded slices, even in ignored destinations.
            stop = min(size, begin + min(4096, limits.max_text_chars))
            while i < stop and data[i] not in (92, 123, 125, 10, 13):
                i += 1
            yield 'bytes', data[begin:i], None
        elif i == size:
            raise InvalidDocumentError('Truncated RTF escape')
        elif data[i] == 39:
            raw = data[i + 1:i + 3]
            if len(raw) != 2 or any(c not in b'0123456789abcdefABCDEF' for c in raw):
                raise InvalidDocumentError('Invalid RTF hexadecimal escape')
            i += 3
            yield 'bytes', bytes([int(raw, 16)]), None
        elif not _letter(data[i]):
            symbol = chr(data[i])
            i += 1
            if symbol == '\r' and i < size and data[i] == 10:
                i += 1
            if symbol in {'\\', '{', '}'}:
                # Escaped syntax characters are encoded bytes too: in DBCS
                # documents they can complete a preceding lead byte.
                yield 'bytes', symbol.encode('ascii'), None
            else:
                yield 'symbol', symbol, None
        else:
            begin = i
            while i < size and _letter(data[i]):
                i += 1
                if i - begin > 32:
                    raise InvalidDocumentError('RTF control word exceeds 32 letters')
            word = data[begin:i].decode('ascii')
            negative = i < size and data[i] == 45
            if negative and i + 1 < size and 48 <= data[i + 1] <= 57:
                i += 1
            else:
                negative = False
            number = None
            digits = 0
            while i < size and 48 <= data[i] <= 57:
                digits += 1
                if digits > 10:
                    raise InvalidDocumentError('Oversized RTF numeric parameter')
                number = (number or 0) * 10 + data[i] - 48
                i += 1
            if negative:
                number = -number
            if i < size and data[i] == 32:
                i += 1
            if word == 'bin':
                if number is None or number < 0:
                    raise InvalidDocumentError('Invalid RTF binary length')
                if number > limits.max_stream_bytes:
                    raise LimitExceededError('RTF binary payload limit exceeded')
                if number > size - i:
                    raise InvalidDocumentError('Truncated RTF binary payload')
                i += number
                yield 'binary', None, None
            else:
                yield 'word', word, number


class _WordArt:
    """Strict, passive observer for one standalone, explicitly enabled shape.

    This does not reopen property destinations in the story parser. Only flat
    strings use the existing decoder; unknown syntax invalidates the candidate.
    The grammar stack has at most four entries, independent of hostile nesting.
    """
    _NUMERIC = {'shapeType', 'fGtext', 'fGtextOK', 'fHidden', 'fBackground',
                'fIsButton', 'gtextSize'}
    _NAMES = _NUMERIC | {'gtextUNICODE', 'gtextFont'}
    _GEOMETRY = {'shpleft', 'shptop', 'shpright', 'shpbottom'}

    def __init__(self, depth: int, limits: Limits, encoding: str, uc: int):
        self.limits = limits
        self.encoding = encoding
        self.uc = uc
        self.value_reader: _PropertyText | None = None
        self.depth = depth
        self.frames = ['shp']
        self.valid = True
        self.instructions = False
        self.attempted = False
        self.text_overflow = False
        self.ignored = 0
        self.starred = False
        self.props: dict[str, str] = {}
        self.name = ''
        self.parts: list[str] = []
        self.size = 0
        self.phase = 0

    def token(self, kind, value, number, depth):
        if not self.valid:
            return
        if self.ignored:
            if kind == 'close' and depth == self.ignored:
                self.ignored = 0
                self.frames.pop()
            return
        frame = self.frames[-1]
        if frame == 'sv' and self.value_reader is not None and kind != 'close':
            self.value_reader.token(kind, value, number)
            self.valid = self.value_reader.valid
            return
        if kind == 'open':
            if frame not in {'shp', 'shpinst', 'sp'}:
                self.valid = False
            else:
                self.frames.append('pending')
                self.starred = False
        elif kind == 'close':
            if frame in {'sn', 'sv'}:
                if self.value_reader is not None:
                    reader, self.value_reader = self.value_reader, None
                    reader.flush()
                    reader.high_end()
                    self.valid = reader.valid
                    self.text_overflow = reader.overflow
                    text = ''.join(reader.parts)
                else:
                    text = ''.join(self.parts)
                self.parts.clear()
                self.size = 0
                if frame == 'sn':
                    self.name = text
                    self.attempted |= text == 'gtextUNICODE'
                    self.valid = text in self._NAMES and text not in self.props
                    self.phase = 1
                else:
                    if self.name in self._NUMERIC:
                        self.valid = (bool(text) and len(text) <= 11
                                      and (text[1:] if text.startswith('-') else text).isascii()
                                      and (text[1:] if text.startswith('-') else text).isdigit()
                                      and -2147483648 <= int(text) <= 2147483647)
                    self.props[self.name] = text
                    self.phase = 2
            elif frame == 'sp':
                self.valid = self.phase == 2
            elif frame == 'pending':
                self.valid = False
            self.frames.pop()
        elif kind == 'symbol' and value == '*' and frame == 'pending':
            self.valid = not self.starred and self.frames[-2] == 'shp'
            self.starred = True
        elif kind == 'word':
            if frame == 'pending':
                parent = self.frames[-2]
                if parent == 'shp' and value == 'shpinst' and not self.instructions:
                    self.instructions = True
                elif parent == 'shp' and value == 'shprslt' and not self.starred:
                    self.ignored = depth
                elif parent == 'shpinst' and value == 'sp':
                    self.name = ''
                    self.phase = 0
                elif parent == 'sp' and ((value == 'sn' and self.phase == 0)
                                         or (value == 'sv' and self.phase == 1)):
                    pass
                else:
                    self.valid = False
                self.frames[-1] = value
                self.valid = self.valid and number is None
                if self.valid and value == 'sv' and self.name == 'gtextUNICODE':
                    self.value_reader = _PropertyText(self.limits, self.encoding, self.uc)
            elif frame == 'shp':
                self.valid = (value in self._GEOMETRY and number is not None
                              and -2147483648 <= number <= 2147483647)
            else:
                self.valid = False
        elif kind == 'bytes':
            if frame not in {'sn', 'sv'}:
                self.valid = not value.strip(b' \t')
            elif any(b < 32 or b > 126 for b in value):
                self.valid = False
            else:
                bound = 128 if frame == 'sv' and self.name == 'gtextFont' else 32
                if len(value) > bound - self.size:
                    self.valid = False
                else:
                    self.parts.append(value.decode('ascii'))
                    self.size += len(value)
        else:
            self.valid = False

    def text(self):
        p = self.props
        if (self.valid and self.instructions and p.get('shapeType') == '136'
                and p.get('fGtext') == p.get('fGtextOK') == '1'
                and all(p.get(k, '0') == '0' for k in ('fHidden', 'fBackground', 'fIsButton'))):
            if self.text_overflow:
                raise LimitExceededError('RTF WordArt property text limit exceeded')
            return p.get('gtextUNICODE')
        return None


class _Stylesheet:
    """Observe top-level paragraph/character styles; retain a bounded ASCII name.

    The existing lexer bounds records and depth. Resolution is iterative and
    memoized, including cycles and missing bases, so long chains stay linear.
    """
    def __init__(self, depth: int, limits: Limits, uc: int):
        self.depth = depth
        self.limits = limits
        self.default_uc = self.uc = uc
        self.fallback = 0
        self.styles: dict[int, tuple[int | None, int | None]] = {}
        self.style = 0
        self.base = self.outline = None
        self.paragraph_style = True
        self.name = bytearray()
        self.name_valid = True
        self.named = set()
        self.visibility = {}
        self.kind = 's'
        self.entry_first = True
        self.hidden = self.deleted = None
        self.additive = False
        self.visibility_cycle = False
        self.visibility_missing = False

    def token(self, kind, value, number, depth):
        if kind in {'open', 'close'}:
            self.fallback = 0
        elif depth == self.depth + 1 and self.fallback:
            count = min(self.fallback, len(value)) if kind == 'bytes' else 1
            self.fallback -= count
            if kind != 'bytes' or count == len(value):
                return
            value = value[count:]
        if kind == 'open' and depth == self.depth:
            self.style = 0
            self.base = self.outline = None
            self.paragraph_style = True
            self.name.clear()
            self.name_valid = True
            self.kind = 's'
            self.entry_first = True
            self.hidden = self.deleted = None
            self.additive = False
            self.uc = self.default_uc
        elif depth == self.depth + 1:
            if kind == 'close' and self.kind is not None:
                self.visibility[self.kind, self.style] = (
                    self.base, self.hidden, self.deleted, self.additive)
            if kind == 'close' and self.paragraph_style:
                # Compatibility with Word/LibreOffice built-in style names:
                # LibreOffice sw/source/writerfilter/dmapper/StyleSheetTable.cxx,
                # StyleNameMap; no localized names, prefixes or sN heuristics.
                name = bytes(self.name).strip().removesuffix(b';').strip()
                if (self.outline is None and self.name_valid and len(name) == 9
                        and name[:8] in {b'heading ', b'Heading '}
                        and b'1' <= name[8:] <= b'9'):
                    self.outline = name[8] - ord('1')
                    self.named.add(self.style)
                else:
                    self.named.discard(self.style)
                self.styles[self.style] = self.base, self.outline
            elif kind == 'bytes':
                self.entry_first = False
                if len(self.name) + len(value) <= 64 and value.isascii():
                    self.name.extend(value)
                else:
                    self.name_valid = False
            elif kind in {'symbol', 'binary'}:
                self.name_valid = False
                if kind == 'symbol' and value == '*':
                    self.paragraph_style = False
                    self.kind = None
            elif kind == 'word':
                if value == 'cs' and self.entry_first:
                    self.kind = 'cs'
                    if number is None or number < 0:
                        self.kind = None
                    else:
                        self.style = number
                elif value in {'cs', 'ds', 'ts'}:
                    self.kind = None
                self.entry_first = False
                if value in {'v', 'deleted'}:
                    if value == 'v':
                        self.hidden = number != 0
                    else:
                        self.deleted = number != 0
                elif value == 'plain':
                    self.hidden = self.deleted = False
                elif value == 'additive':
                    self.additive = number != 0
                if value in {'u', 'uc'}:
                    self.name_valid = False
                    if value == 'u':
                        self.fallback = self.uc
                    else:
                        if number is None or number < 0:
                            raise InvalidDocumentError('Invalid RTF Unicode fallback count')
                        if number > self.limits.max_stream_bytes:
                            raise LimitExceededError('RTF Unicode fallback limit exceeded')
                        self.uc = number
                if value in {'cs', 'ds', 'ts'}:
                    self.paragraph_style = False
                elif value == 's':
                    if number is None or number < 0:
                        self.paragraph_style = False
                        self.kind = None
                    else:
                        self.style = number
                elif value == 'sbasedon':
                    self.base = number if number != 222 else None
                elif value == 'outlinelevel' and number is not None and 0 <= number <= 9:
                    self.outline = number

    def resolve(self):
        resolved: dict[int, int | None] = {}
        for style in self.styles:
            path = set()
            current = style
            outline = None
            while current in self.styles and current not in path:
                if current in resolved:
                    outline = resolved[current]
                    break
                path.add(current)
                current, outline = self.styles[current]
                if outline is not None:
                    break
            for item in path:
                resolved[item] = outline
        return resolved

    def resolve_visibility(self):
        # Resolve each property independently: a nearer explicit false is as
        # significant as true. Missing properties do not overwrite ancestors.
        # Iterative memoization bounds work by the lexically bounded style count.
        properties = []
        for slot in (1, 2):
            resolved = {}
            for key in self.visibility:
                path, seen = [], set()
                current = key
                value = None
                while current in self.visibility:
                    if current in resolved:
                        value = resolved[current]
                        break
                    if current in seen:
                        self.visibility_cycle = True
                        break
                    seen.add(current)
                    path.append(current)
                    record = self.visibility[current]
                    value = record[slot]
                    if value is not None or record[0] is None:
                        break
                    current = current[0], record[0]
                else:
                    self.visibility_missing = True
                for item in path:
                    resolved[item] = value
            properties.append(resolved)
        return {key: (properties[0][key], properties[1][key], record[3])
                for key, record in self.visibility.items()}


@dataclass(slots=True)
class _State:
    skip: bool = False
    font_table: bool = False
    shape_container: bool = False
    legacy_container: bool = False
    # Ancestry survives entry into visible textbox text; suppression does not.
    shape_ancestor: bool = False
    legacy_ancestor: bool = False
    font: int | None = None
    encoding: str = 'cp1252'
    uc: int = 1
    # None means no direct override; explicit false must beat inherited true.
    hidden: bool | None = None
    deleted: bool | None = None
    character_style: int | None = None
    style_visibility: bool = True
    first: bool = True
    starred: bool = False
    target: int = 0
    upr: bool = False
    children: int = 0
    depth: int = 1
    nested_properties: bool = False
    style: int = 0
    outline: int | None = None


class _Sink:
    def __init__(self, parser: _Parser, story: str = ''):
        self.parser = parser
        self.story = story
        self.is_note = story == 'footnotes'
        self.note_depth = 0
        # A visible empty note is real. An entirely suppressed note sink is not
        # promoted merely because finishing it creates structural delimiters.
        self.note_observed = self.is_note and parser.visible()
        self.blocks: list[Paragraph | Table] = []
        self.parts: list[str] = []
        self.paragraph_ends: list[tuple[int, int | None]] = []
        self.heading_level: int | None = None
        self.text_heading_level: int | None = None
        self.row: list[Cell] | None = None
        self.expected = 0
        self.table: Table | None = None
        self.definitions: list[tuple[int | None, str, str]] = []
        self.horizontal = self.vertical = ''
        self.left = 0
        self.nested = False
        self.cell_blocks: list[Paragraph | Table] = []
        self.child: _Sink | None = None
        self.level = 1
        self.previous_definitions = None
        self.vertical_anchors: dict[tuple[int, int, int, int], Cell] = {}

    def at_depth(self, depth: int):
        current = self
        while depth > current.level:
            if depth > current.level + 1 and current.child is None:
                raise InvalidDocumentError('RTF nested table depth skips a parent level')
            if current.row is None:
                raise InvalidDocumentError('RTF nested table has no containing row')
            if current.child is None:
                current.flush_cell_paragraphs(implicit_boundary=True)
                current.nested = True
                self.parser.has_nested = True
                current.child = _Sink(self.parser)
                current.child.level = current.level + 1
                current.child.row = []
            current = current.child
        current.close_child()
        return current

    def flush_cell_paragraphs(self, implicit_boundary: bool = False):
        # Keep actual paragraph boundaries separate from \line text. A final
        # \par terminates the last paragraph; a final \line remains in its text.
        start = 0
        for end, heading in self.paragraph_ends:
            self.cell_blocks.append(Paragraph(''.join(self.parts[start:end - 1]), heading))
            start = end
        if start < len(self.parts):
            # A new nested table implicitly terminates its parent's pending
            # paragraph. Its leading pard/style controls belong to the child;
            # preserve the parent properties captured with its last text.
            heading = self.text_heading_level if implicit_boundary else self.heading_level
            self.cell_blocks.append(Paragraph(''.join(self.parts[start:]), heading))
        self.parts.clear()
        self.paragraph_ends.clear()

    def close_child(self):
        # Iterative postorder avoids Python recursion on caller-raised limits.
        parents = []
        current = self
        while current.child is not None:
            parents.append(current)
            current = current.child
        for parent in reversed(parents):
            child = parent.child
            child.finish()
            parent.cell_blocks.extend(child.blocks)
            parent.child = None

    def projected_cell(self):
        self.close_child()
        if not self.cell_blocks:
            text = ''.join(self.parts)
            if self.heading_level is None and not any(h is not None for _, h in self.paragraph_ends):
                return Cell(text)
            # Keep the legacy ordinary-cell projection, including trailing par.
            self.parser.charge(len(text))
            if not self.parts:
                self.cell_blocks.append(Paragraph('', self.heading_level))
            self.flush_cell_paragraphs()
            cell = Cell(text, blocks=self.cell_blocks)
            self.cell_blocks = []
            return cell
        self.flush_cell_paragraphs()
        # Charge every stored projection before constructing it, including
        # repeated descendant text at each ancestor and all delimiters.
        size = max(0, len(self.cell_blocks) - 1)
        for block in self.cell_blocks:
            if isinstance(block, Paragraph):
                size += len(block.text)
            else:
                size += max(0, len(block.rows) - 1)
                for row in block.rows:
                    size += sum(len(c.text) for c in row) + max(0, len(row) - 1)
        self.parser.charge(size)
        fragments = [b.text if isinstance(b, Paragraph) else
                     '\n'.join('\t'.join(c.text for c in row) for row in b.rows)
                     for b in self.cell_blocks]
        cell = Cell('\n'.join(fragments), blocks=self.cell_blocks)
        self.cell_blocks = []
        return cell

    def text(self, text: str):
        if text:
            if self.is_note and self.parser.visible():
                self.note_observed = True
            if self.level > 1 and self.row is None:
                self.row = []
            self.parser.charge(len(text))
            self.heading_level = self.parser.heading_level()
            self.text_heading_level = self.heading_level
            self.parts.append(text)

    def paragraph(self, force: bool = False):
        if force and self.is_note and self.parser.visible():
            self.note_observed = True
        if self.level > 1 and self.row is None:
            self.row = []
        if not self.parts or force:
            self.heading_level = self.parser.heading_level()
        if self.row is not None:
            heading = self.heading_level
            self.text('\n')
            self.paragraph_ends.append((len(self.parts), heading))
            self.heading_level = None
        elif self.parts or force:
            self.blocks.append(Paragraph(''.join(self.parts), self.heading_level))
            self.parts.clear()
            self.heading_level = None
            self.table = None
            self.vertical_anchors.clear()

    def check_definitions(self):
        if ((self.level > 1 or self.nested) and self.previous_definitions is not None and
                self.previous_definitions != (self.left, self.definitions)):
            self.parser.warn(diagnostic_warning('rtf_conflicting_rtf_row_properties_final_properties_used_text_retained', 'Conflicting RTF row properties; final properties used, text retained.'))

    def start_row(self):
        # Writers may repeat row properties after cell content, before \row.
        # Only \row (or final recovery) ends a row; \trowd resets definitions.
        if self.row is None:
            self.paragraph()
            self.row = []
        self.check_definitions()
        self.previous_definitions = (self.left, self.definitions[:]) if self.definitions else None
        self.expected = 0
        self.definitions.clear()
        self.horizontal = self.vertical = ''
        self.left = 0

    def define_cell(self, right: int | None):
        self.expected += 1
        self.definitions.append((right, self.horizontal, self.vertical))
        self.horizontal = self.vertical = ''

    def merge_cells(self, complete: bool):
        """Reconstruct only explicit, rectangular merges on an unambiguous grid.

        Coordinates remain in the model as covered cells. Active vertical spans
        live for one adjacent row only; no guessed merges across recovery, nested
        tables, changed column indices or body paragraphs.
        """
        previous, self.vertical_anchors = self.vertical_anchors, {}
        definitions = self.definitions
        marked = any(h or v for _, h, v in definitions)

        def unsupported():
            if marked:
                self.parser.warn(
                    diagnostic_warning('rtf_merged_table_cells_retained_as_separate_cells_spans_not', 'Merged table cells retained as separate cells; spans not reconstructed.'))

        if not complete or self.nested:
            unsupported()
            return
        left = self.left
        groups = []
        for i, (right, horizontal, vertical) in enumerate(definitions):
            if right is None or right <= left:
                unsupported()
                return
            if horizontal == 'clmrg':
                if not groups or definitions[groups[-1][0]][1] != 'clmgf':
                    unsupported()
                    return
                start, _, x, _, v = groups[-1]
                if v != vertical:
                    unsupported()
                    return
                groups[-1] = (start, i + 1, x, right, v)
            else:
                groups.append((i, i + 1, left, right, vertical))
            left = right
        for start, end, left, right, vertical in groups:
            anchor = self.row[start]
            # Join original fragments once, retaining continuation text. Charge
            # only newly inserted separators; input text was already budgeted.
            fragments = [c.text for c in self.row[start:end] if c.text]
            self.parser.charge(max(0, len(fragments) - 1))
            if any(c.blocks for c in self.row[start:end]):
                blocks = []
                for cell in self.row[start:end]:
                    if cell.blocks:
                        blocks.extend(cell.blocks)
                    elif cell.text:
                        self.parser.charge(len(cell.text))
                        blocks.append(Paragraph(cell.text))
                anchor.blocks = blocks
            anchor.text = '\n'.join(fragments)
            anchor.col_span = end - start
            for cell in self.row[start + 1:end]:
                cell.text = ''
                cell.blocks = []
                cell.covered = True
            key = (left, right, start, end)
            if vertical == 'clvmgf':
                self.vertical_anchors[key] = anchor
            elif vertical == 'clvmrg':
                top = previous.get(key)
                if top is not None and not anchor.text:
                    top.row_span += 1
                    anchor.col_span = 1
                    anchor.covered = True
                    self.vertical_anchors[key] = top
                else:
                    self.parser.warn(
                        diagnostic_warning('rtf_vertical_merge_continuation_ambiguous_or_nonempty_cells_retained', 'Vertical merge continuation ambiguous or nonempty; cells retained.'))

    def cell(self):
        if self.row is None:
            if self.level == 1:
                self.parser.warn(diagnostic_warning('rtf_table_cell_without_row_definition_recovered', 'Table cell without row definition recovered.'))
            self.row = []
        self.parser.cells += 1
        if self.parser.cells > self.parser.limits.max_cells:
            raise LimitExceededError('RTF cell limit exceeded')
        if not self.parts and not self.cell_blocks and self.child is None:
            # Cell terminators do not reset paragraph properties. Empty cells
            # have no text emission to refresh the cached heading themselves.
            self.heading_level = self.parser.heading_level()
        self.row.append(self.projected_cell())
        self.heading_level = None
        self.parts.clear()
        self.paragraph_ends.clear()

    def end_row(self, recovered: bool = False):
        if self.row is None:
            self.start_row()
        self.close_child()
        if self.level > 1:
            if self.parts or self.cell_blocks:
                self.parser.warn(diagnostic_warning('rtf_nested_cell_terminator_missing_text_retained', 'Nested cell terminator missing; text retained.'))
            if not self.expected:
                self.parser.warn(diagnostic_warning('rtf_nested_row_properties_missing_cells_retained', 'Nested row properties missing; cells retained.'))
        if self.parts or self.cell_blocks or not self.row:
            self.cell()
        self.check_definitions()
        complete = bool(self.expected) and len(self.row) == self.expected
        while len(self.row) < self.expected:
            self.cell()
        if self.expected and len(self.row) != self.expected:
            self.parser.warn(diagnostic_warning('rtf_table_cell_count_differs_from_row_definition', 'Table cell count differs from row definition.'))
        if self.table is None:
            self.table = Table()
            self.blocks.append(self.table)
        self.merge_cells(complete and not recovered)
        self.table.rows.append(self.row)
        self.row = None
        self.expected = 0
        self.definitions.clear()
        self.horizontal = self.vertical = ''
        self.nested = False
        self.previous_definitions = None

    def finish(self):
        if self.row is not None:
            self.parser.warn(diagnostic_warning('rtf_nested_table_row_incomplete_recovered_if_self_level_1', 'Nested table row incomplete; recovered.' if self.level > 1 else
                             'Incomplete table row recovered.'))
            self.end_row(recovered=True)
        if self.level == 1:
            self.paragraph()


class _Parser:
    def __init__(self, limits: Limits):
        self.limits = limits
        self.document = Document(format='rtf')
        self.state = _State()
        self.stack: list[_State] = []
        self.sinks = [_Sink(self)]
        self.fonts: dict[int, tuple[str | None, str | None]] = {}
        self.default_font: int | None = None
        self.fallback = 0
        self.pending_high: int | None = None
        self.buffer = bytearray()
        self.decoder = None
        self.chars = 0
        self.cells = 0
        self.definitions = 0
        self.has_nested = False
        self.wordart: _WordArt | None = None
        self.uncertain_encoding = False
        self.stylesheet: _Stylesheet | None = None
        self.style_outlines: dict[int, int | None] = {}
        self.style_visibility = {}

    def heading_level(self):
        if any(self.visibility()):
            return None
        outline = self.state.outline
        if outline is None:
            outline = self.style_outlines.get(self.state.style)
        return outline + 1 if outline is not None and 0 <= outline <= 8 else None

    def update_heading(self):
        # Property changes must not close/create nested tables (pard/intbl often
        # precede itap2). Routing structural content remains the sink's job.
        sink = self.sinks[self.state.target]
        while sink.child is not None and sink.level < self.state.depth:
            sink = sink.child
        sink.heading_level = self.heading_level()

    def warn(self, message: str):
        if message not in self.document.warnings:
            self.document.warnings.append(message)

    def charge(self, count: int):
        if count > self.limits.max_text_chars - self.chars:
            raise LimitExceededError('RTF text limit exceeded')
        self.chars += count

    @property
    def sink(self):
        root = self.sinks[self.state.target]
        if root.is_note and self.visible():
            root.note_observed = True
        return root.at_depth(self.state.depth)

    def visibility(self):
        s = self.state
        hidden = deleted = False
        if s.style_visibility:
            hidden, deleted, _ = self.style_visibility.get(('s', s.style), (None, None, False))
            character = self.style_visibility.get(('cs', s.character_style))
            if character is not None:
                char_hidden, char_deleted, additive = character
                if not additive:
                    hidden = deleted = False
                if char_hidden is not None:
                    hidden = char_hidden
                if char_deleted is not None:
                    deleted = char_deleted
        return (hidden if s.hidden is None else s.hidden,
                deleted if s.deleted is None else s.deleted)

    def visible(self):
        if (self.state.skip or self.state.font_table or self.state.shape_container
                or self.state.legacy_container):
            return False
        if any(self.visibility()):
            self.warn(diagnostic_warning('hidden_text_omitted', 'Hidden or deleted text omitted.'))
            return False
        return True

    def high_end(self):
        if self.pending_high is not None:
            self.pending_high = None
            self.warn(diagnostic_warning('rtf_unpaired_unicode_surrogate_replaced', 'Unpaired Unicode surrogate replaced.'))
            self.sink.text('\ufffd')

    def emit(self, text: str):
        if self.visible() and text:
            self.high_end()
            self.sink.text(text)

    def codec(self, number: int | None) -> str:
        if number is None or number <= 0:
            raise InvalidDocumentError('Invalid RTF code page')
        name = 'utf-8' if number == 65001 else f'cp{number}'
        try:
            codecs.lookup(name)
        except LookupError:
            self.uncertain_encoding = True
            self.warn(diagnostic_warning('rtf_unsupported_code_page_replaced_with_windows_1252', 'Unsupported code page replaced with Windows-1252.'))
            return 'cp1252'
        return name

    def encoding(self):
        font = self.state.font if self.state.font is not None else self.default_font
        charset, explicit = self.fonts.get(font, (None, None))
        return explicit or charset or self.state.encoding

    def flush(self, final: bool = True):
        if self.buffer or self.decoder is not None:
            if self.decoder is None:
                self.decoder = codecs.getincrementaldecoder(self.encoding())(errors='replace')
            text = self.decoder.decode(self.buffer, final=final)
            if '\ufffd' in text:
                self.warn(diagnostic_warning('invalid_encoded_text_replaced', 'Invalid encoded text replaced.'))
            self.buffer.clear()
            self.emit(text)
            if final:
                self.decoder = None

    def byte_text(self, raw: bytes):
        n = min(self.fallback, len(raw))
        self.fallback -= n
        if not self.visible() or n == len(raw):
            return
        # Decoder and scratch allocations are bounded independently of file size.
        # Preserve incomplete multibyte sequences across literal/hex tokens.
        chunk_size = min(4096, self.limits.max_text_chars)
        while n < len(raw):
            count = min(chunk_size - len(self.buffer), len(raw) - n)
            self.buffer.extend(raw[n:n + count])
            n += count
            if len(self.buffer) == chunk_size:
                self.flush(final=False)

    def unicode(self, number: int | None):
        if number is None or not -32768 <= number <= 65535:
            raise InvalidDocumentError('Invalid RTF Unicode code unit')
        if self.visible():
            unit = number & 0xffff
            if 0xdc00 <= unit <= 0xdfff and self.pending_high is not None:
                high, self.pending_high = self.pending_high, None
                self.sink.text(chr(0x10000 + ((high - 0xd800) << 10) + unit - 0xdc00))
            else:
                self.high_end()
                if 0xd800 <= unit <= 0xdbff:
                    self.pending_high = unit
                elif 0xdc00 <= unit <= 0xdfff:
                    self.warn(diagnostic_warning('rtf_unpaired_unicode_surrogate_replaced', 'Unpaired Unicode surrogate replaced.'))
                    self.sink.text('\ufffd')
                else:
                    self.sink.text(chr(unit))
        self.fallback = self.state.uc

    def destination(self, word: str):
        s = self.state
        if s.skip:
            return
        # Guard destinations before their handlers can mutate document state or
        # validate table controls. Visible text keeps its drawing ancestry.
        drawing = s.shape_ancestor or s.legacy_ancestor
        if (drawing and word in _HEADERS | {'footnote', 'fonttbl'}
                or (s.shape_container or s.legacy_container) and word == 'nesttableprops'
                or s.shape_ancestor and word == 'do'
                or s.legacy_ancestor and word in _SHAPE_CONTAINERS | {'shptxt'}):
            s.skip = True
            return
        if word == 'stylesheet' and not (drawing or s.font_table or any(self.visibility())):
            self.stylesheet = _Stylesheet(len(self.stack), self.limits, s.uc)
            s.skip = True
        elif word in _SKIP:
            s.skip = True
            if word in {'pict', 'object', 'mmath', 'moMath', 'moMathPara'}:
                self.warn(diagnostic_warning('rtf_pictures_objects_shapes_or_equations_omitted', 'Pictures, objects, shapes or equations omitted.'))
            elif word == 'annotation':
                self.warn(diagnostic_warning('rtf_annotations_omitted', 'Annotations omitted.'))
        elif word == 'nesttableprops':
            if s.depth < 2:
                raise InvalidDocumentError('RTF nested properties outside a nested table')
            s.nested_properties = True
        elif word == 'fonttbl':
            s.font_table = True
        elif s.font_table:
            return
        elif word == 'do':
            # Standalone legacy drawings only; modern alternatives are not a
            # proven fallback source. Hard-skipped ancestors returned above.
            self.high_end()
            s.legacy_container = True
            s.legacy_ancestor = True
            self.warn(diagnostic_warning('rtf_legacy_drawing_and_layout_omitted', 'Legacy drawing and layout omitted.'))
        elif word == 'dptxbxtext' and not s.legacy_container:
            s.skip = True
        elif word in _SHAPE_CONTAINERS:
            if (word == 'shp' and s.first and not s.starred
                    and not s.shape_ancestor and not s.font_table
                    and not any(self.visibility()) and self.wordart is None
                    and not self.uncertain_encoding
                    and self.encoding() in {'cp1250', 'cp1251', 'cp1252', 'cp1253', 'cp932'}):
                self.wordart = _WordArt(len(self.stack), self.limits, self.encoding(), s.uc)
            # Traverse only recognized shape containers, never reopen a skipped
            # ancestor. Property values and the legacy rendering are hard skips.
            self.high_end()
            s.shape_container = True
            s.shape_ancestor = True
            self.warn(diagnostic_warning('rtf_shape_drawing_and_layout_omitted', 'Shape drawing and layout omitted.'))
        elif word in _HEADERS or word in {'footnote', 'shptxt', 'dptxbxtext'}:
            if word == 'footnote' and s.target != 0:
                # Notes belong to the main story, including its table cells.
                # A nested destination is not another reference or a continuation
                # of the current note; do not merge its text into that note.
                s.skip = True
                self.warn(diagnostic_warning('rtf_note_destination_in_an_auxiliary_story_omitted', 'RTF note destination in an auxiliary story omitted.'))
                return
            self.high_end()
            story = 'headers_footers' if word in _HEADERS else (
                'footnotes' if word == 'footnote' else 'textboxes')
            self.sinks.append(_Sink(self, story))
            self.sinks[-1].note_depth = len(self.stack)
            s.target = len(self.sinks) - 1
            s.depth = 1
            s.nested_properties = False
            s.shape_container = False
            s.legacy_container = False
            if word == 'shptxt':
                s.shape_ancestor = True
            # Story ownership does not make inherited hidden/deleted text
            # visible. Explicit run/style resets inside the story still apply.
        elif s.starred and word not in {'fldrslt', 'ud'}:
            s.skip = True
            self.warn(diagnostic_warning('rtf_unknown_optional_destinations_omitted', 'Unknown optional destinations omitted.'))

    def word(self, word: str, number: int | None):
        s = self.state
        if s.first or s.starred:
            self.destination(word)
        s.first = s.starred = False
        if word == 'shp' and number is not None and self.wordart is not None:
            self.wordart.valid = False
        if s.skip:
            return
        if s.font_table:
            if word == 'f' and number is not None:
                s.font = number
                self.fonts.setdefault(number, (None, None))
            elif word in {'cpg', 'fcharset'} and s.font is not None:
                charset, explicit = self.fonts.get(s.font, (None, None))
                if word == 'cpg':
                    explicit = self.codec(number)
                else:
                    charset = _CHARSETS.get(number)
                    if number not in {0, 1} and charset is None:
                        self.uncertain_encoding = True
                        self.warn(diagnostic_warning('rtf_unsupported_font_charset_or_symbol_font_using_document_code', 'Unsupported font charset or symbol font; using document code page.'))
                self.fonts[s.font] = charset, explicit
            return
        if word in _SKIP or word in _SHAPE_CONTAINERS or word in {'fonttbl', 'nesttableprops', 'do'}:
            self.destination(word)
        elif s.shape_container or s.legacy_container:
            # Shape controls/stray text cannot modify the surrounding story.
            return
        elif word == 'upr':
            s.upr = True
            s.children = 0
            self.warn(diagnostic_warning('rtf_unicode_alternate_selected_ansi_alternate_omitted', 'Unicode alternate selected; ANSI alternate omitted.'))
        elif word == 'uc':
            if number is None or number < 0:
                raise InvalidDocumentError('Invalid RTF Unicode fallback count')
            if number > self.limits.max_stream_bytes:
                raise LimitExceededError('RTF Unicode fallback limit exceeded')
            s.uc = number
        elif word == 'u':
            self.unicode(number)
        elif word == 'ansicpg':
            s.encoding = self.codec(number)
        elif word in {'ansi', 'mac', 'pc', 'pca'}:
            s.encoding = {'ansi': 'cp1252', 'mac': 'mac_roman', 'pc': 'cp437', 'pca': 'cp850'}[word]
        elif word == 'deff':
            self.default_font = number
        elif word == 'f':
            s.font = number
        elif word == 'plain':
            self.high_end()
            s.font = self.default_font
            s.hidden = s.deleted = None
            s.character_style = None
            s.style_visibility = False
        elif word in {'s', 'cs'} and number is not None and number >= 0:
            self.high_end()
            if word == 's':
                s.style = number
            else:
                s.character_style = number
            s.style_visibility = True
            if self.visible():
                self.update_heading()
        elif word == 'pard':
            if s.nested_properties:
                raise InvalidDocumentError('Paragraph reset inside RTF nested properties')
            self.high_end()
            s.style = 0
            s.outline = None
            if self.visible():
                self.update_heading()
            s.depth = 1
        elif word in {'v', 'deleted'}:
            self.high_end()
            if word == 'v':
                s.hidden = number != 0
            else:
                s.deleted = number != 0
            self.warn(diagnostic_warning('hidden_text_omitted', 'Hidden or deleted text omitted.'))
        elif word == 'ftnalt':
            # Classification belongs to the note root, never a nested cell sink.
            root = self.sinks[s.target]
            if root.is_note and (len(self.stack) == root.note_depth or self.visible()):
                root.story = 'endnotes'
        elif self.visible() or word in _STRUCTURAL:
            if word in _CHARS:
                self.emit(_CHARS[word])
            elif word in {'par', 'sect', 'page'}:
                self.high_end()
                self.sink.paragraph(force=self.visible())
            elif word == 'intbl' and number != 0:
                # Late outer definitions are legal too. Do not resolve/reset
                # nesting here: writers emit pard/intbl/itap2 between cells.
                root = self.sinks[s.target]
                if s.depth == 1 and root.row is None:
                    root.row = []
            elif word == 'outlinelevel' and number is not None and 0 <= number <= 9:
                self.high_end()
                s.outline = number
                self.update_heading()
            elif word == 'itap':
                if number is None or number < 0:
                    raise InvalidDocumentError('Invalid RTF table nesting depth')
                if number > self.limits.max_depth:
                    raise LimitExceededError('RTF table nesting depth limit exceeded')
                if s.nested_properties and number != s.depth:
                    raise InvalidDocumentError('Conflicting depth inside RTF nested properties')
                self.high_end()
                if number == 0 and self.sinks[s.target].row is not None:
                    self.warn(diagnostic_warning('rtf_depth_zero_inside_unfinished_table_parent_cell_retained', 'RTF depth zero inside unfinished table; parent cell retained.'))
                s.depth = max(1, number)
                if s.depth > 1:
                    self.sinks[s.target].at_depth(s.depth)
            elif word == 'trowd':
                self.high_end()
                # Outside nesttableprops, Word repeats the outer row defaults
                # even while the last paragraph still carries itap2.
                if not s.nested_properties:
                    s.depth = 1
                self.sink.start_row()
            elif word == 'cellx':
                self.definitions += 1
                if self.definitions > self.limits.max_cells:
                    raise LimitExceededError('RTF cell definition limit exceeded')
                self.sink.define_cell(number)
            elif word == 'trleft':
                self.sink.left = number if number is not None else 0
            elif word == 'cell':
                if s.nested_properties:
                    raise InvalidDocumentError('Outer cell terminator inside RTF nested properties')
                self.high_end()
                s.depth = 1
                self.sink.cell()
            elif word == 'row':
                if s.nested_properties:
                    raise InvalidDocumentError('Outer row terminator inside RTF nested properties')
                self.high_end()
                s.depth = 1
                self.sink.end_row()
            elif word in {'clmgf', 'clmrg', 'clvmgf', 'clvmrg'}:
                if word in {'clmgf', 'clmrg'}:
                    if self.sink.level > 1 and self.sink.horizontal not in {'', word}:
                        self.warn(diagnostic_warning('rtf_conflicting_nested_cell_merge_properties_final_flag_used', 'Conflicting nested cell merge properties; final flag used.'))
                    self.sink.horizontal = word
                else:
                    if self.sink.level > 1 and self.sink.vertical not in {'', word}:
                        self.warn(diagnostic_warning('rtf_conflicting_nested_cell_merge_properties_final_flag_used', 'Conflicting nested cell merge properties; final flag used.'))
                    self.sink.vertical = word
            elif word in {'nestcell', 'nestrow'}:
                self.high_end()
                if s.depth < 2:
                    raise InvalidDocumentError('RTF nested terminator outside a nested table')
                if word == 'nestcell':
                    self.sink.cell()
                else:
                    self.sink.end_row()

        if word in {'plain', 'pard', 's', 'cs', 'v', 'deleted'}:
            # An explicit reset can reveal a real but empty note. Observe the
            # visibility transition without routing through sink/at_depth,
            # which would create or close table structure. Skipped destinations
            # and Unicode fallback controls never reach this point.
            root = self.sinks[s.target]
            if root.is_note and self.visible():
                root.note_observed = True

    def _enter_group(self):
        self.fallback = 0
        if len(self.stack) >= self.limits.max_depth:
            raise LimitExceededError('RTF group depth limit exceeded')
        parent = self.state
        parent.children += 1
        self.stack.append(parent)
        self.state = replace(parent, first=True, starred=False, upr=False, children=0)
        if parent.upr and parent.children == 1:
            self.state.skip = True
        elif parent.upr and parent.children > 2:
            self.state.skip = True

    def _exit_group(self) -> bool:
        self.fallback = 0
        if not self.stack:
            raise InvalidDocumentError('Unbalanced RTF closing group')
        parent = self.stack.pop()
        if parent.target != self.state.target:
            self.high_end()
            self.sinks[self.state.target].finish()
        self.state = parent
        return not self.stack

    def _finalize_auxiliary_stories(self):
        extras: dict[str, list[str]] = {}
        sinks = [sink for sink in self.sinks[1:]
                 if not sink.is_note or sink.note_observed]
        structured = {sink.story for sink in sinks
                      if sink.is_note or any(isinstance(block, Table)
                                             or block.heading_level is not None
                                             for block in sink.blocks)}
        ordinals = {'footnotes': 0, 'endnotes': 0}
        for sink in sinks:
            if sink.is_note and len(self.document.notes) >= self.limits.max_records:
                raise LimitExceededError('RTF note metadata limit exceeded')
            if sink.is_note and not sink.blocks:
                sink.blocks.append(Paragraph(''))
            # Preserve all blocks of each note, including empty bodies, in
            # encounter order. Ranges are in this story's block array, not CPs.
            if sink.story in structured:
                blocks = self.document.story_blocks.setdefault(sink.story, [])
                start = len(blocks)
                blocks.extend(sink.blocks)
                if sink.is_note:
                    ordinals[sink.story] += 1
                    self.document.notes.append(Note(
                        kind='footnote' if sink.story == 'footnotes' else 'endnote',
                        ordinal=ordinals[sink.story],
                        body=NoteBodyRange(sink.story, start, len(blocks))))
            self.charge(max(0, len(sink.blocks) - 1))
            parts = []
            for block in sink.blocks:
                if isinstance(block, Paragraph):
                    parts.append(block.text)
                else:
                    self.charge(sum(max(0, len(row) - 1) for row in block.rows)
                                + max(0, len(block.rows) - 1))
                    parts.append('\n'.join('\t'.join(c.text for c in row) for row in block.rows))
            text = '\n'.join(parts)
            if text:
                if extras.get(sink.story):
                    self.charge(1)
                extras.setdefault(sink.story, []).append(text)
        for story, parts in extras.items():
            text = '\n'.join(parts)
            if story in structured:
                # Both the retained blocks and their aggregate string count.
                self.charge(len(text))
            setattr(self.document, story, text)

    def parse(self, data: bytes, start: int) -> Document:
        closed = False
        terminal_nul = False
        for kind, value, number in _tokens(data, start, self.limits):
            if closed:
                if kind == 'bytes' and all(b in b' \t\r\n' for b in value):
                    continue
                # Compatibility for one literal NUL terminator at physical EOF.
                # Keep tokenization (and its budgets/errors) over the full input.
                if (not terminal_nul and kind == 'bytes' and value.endswith(b'\0')
                        and all(b in b' \t\r\n' for b in value[:-1])
                        and data.endswith(b'\0')):
                    terminal_nul = True
                    self.warn(diagnostic_warning('rtf_a_single_terminal_nul_after_the_rtf_root_was', 'A single terminal NUL after the RTF root was ignored.'))
                    continue
                raise InvalidDocumentError('Data after RTF root group')
            if self.stylesheet is not None:
                sheet = self.stylesheet
                sheet.token(kind, value, number, len(self.stack))
                if kind == 'close' and len(self.stack) == sheet.depth:
                    self.style_outlines.update(sheet.resolve())
                    self.style_visibility.update(sheet.resolve_visibility())
                    if sheet.visibility_cycle:
                        self.warn(diagnostic_warning('rtf_cyclic_rtf_style_inheritance_only_available_visibility_properties_used', 'Cyclic RTF style inheritance; only available visibility properties used.'))
                    if sheet.visibility_missing:
                        self.warn(diagnostic_warning('rtf_style_base_missing_or_wrong_kind_only_available', 'RTF style base missing or wrong kind; only available visibility properties used.'))
                    if sheet.named:
                        self.warn(diagnostic_warning('heading_name_fallback', 'RTF heading levels inferred from built-in style names.'))
                    self.stylesheet = None
            if self.wordart is not None:
                candidate = self.wordart
                candidate.token(kind, value, number, len(self.stack))
                if kind == 'close' and len(self.stack) == candidate.depth:
                    text = candidate.text()
                    self.wordart = None
                    if text:
                        sink = _Sink(self, 'textboxes')
                        sink.text(text)
                        sink.heading_level = None
                        sink.finish()
                        self.sinks.append(sink)
                    elif text is None and candidate.attempted:
                        self.warn(diagnostic_warning('rtf_unsupported_or_disabled_wordart_property_text_omitted', 'Unsupported or disabled WordArt property text omitted.'))
            if kind == 'bytes':
                self.state.first = False
                self.byte_text(value)
                continue
            self.flush()
            if kind == 'open':
                self._enter_group()
            elif kind == 'close':
                closed = self._exit_group()
            elif self.fallback:
                # One control word/symbol or an entire bin token is one fallback
                # character. Its semantic side effects must not be applied.
                self.fallback -= 1
            elif kind == 'binary':
                if self.visible():
                    self.warn(diagnostic_warning('rtf_binary_payload_omitted', 'Binary payload omitted.'))
            elif kind == 'symbol':
                if value == '*':
                    self.state.starred = True
                else:
                    self.state.first = False
                    if value in {'\r', '\n'}:
                        if self.visible():
                            self.high_end()
                            self.sink.paragraph(force=True)
                    else:
                        self.emit({'~': '\xa0', '-': '\xad', '_': '\u2011'}.get(value, ''))
            else:
                self.word(value, number)
        if not closed or self.stack:
            raise InvalidDocumentError('Unclosed RTF group')
        self.flush()
        self.high_end()
        self.sinks[0].finish()
        self.document.blocks = self.sinks[0].blocks
        self._finalize_auxiliary_stories()
        if self.has_nested:
            # Bound the public text projection too, without allocating it. The
            # retained parent/child strings were already charged while built.
            lengths = []
            for block in self.document.blocks:
                if isinstance(block, Paragraph):
                    size = len(block.text)
                else:
                    size = max(0, len(block.rows) - 1)
                    size += sum(sum(len(c.text) for c in row) + max(0, len(row) - 1)
                                for row in block.rows)
                if size:
                    lengths.append(size)
            lengths.extend(len(getattr(self.document, story)) for story in
                           ('footnotes', 'endnotes', 'headers_footers', 'textboxes')
                           if getattr(self.document, story))
            if sum(lengths) + 2 * max(0, len(lengths) - 1) > self.limits.max_text_chars:
                raise LimitExceededError('RTF output projection text limit exceeded')
        return self.document


class _PropertyText(_Parser):
    """Flat gtextUNICODE sink sharing the main reader's text decoding methods.

    No second lexer, document parsing, story dispatch or local encoding changes.
    Invalid text rejects this property instead of publishing replacement text.
    Overflow stops retention, not validation, and is resolved by its shape owner.
    """
    def __init__(self, limits: Limits, encoding: str, uc: int):
        self.limits = limits
        self.state = _State(encoding=encoding, uc=uc)
        self.valid = True
        self.overflow = False
        self.parts: list[str] = []
        self.size = 0
        self.buffer = bytearray()
        self.decoder = None
        self.pending_high = None
        self.fallback = 0

    @property
    def sink(self):
        return self

    def visible(self):
        return self.valid

    def encoding(self):
        return self.state.encoding

    def warn(self, message: str):
        self.valid = False
        self.parts.clear()
        self.size = 0

    def text(self, text: str):
        if not self.valid:
            return
        if any(ord(c) < 32 or 0x7f <= ord(c) < 0xa0 for c in text):
            self.warn(diagnostic_warning('rtf_control_character_in_wordart_property', 'Control character in WordArt property.'))
        elif not self.overflow:
            if len(text) > min(65536, self.limits.max_text_chars) - self.size:
                self.overflow = True
                self.parts.clear()
                self.size = 0
            else:
                self.parts.append(text)
                self.size += len(text)

    def token(self, kind, value, number):
        if kind == 'bytes':
            self.byte_text(value)
            return
        self.flush()
        if kind in {'open', 'close'}:
            self.valid = False
        elif self.fallback:
            # Like _Parser.parse: a control/symbol or opaque bin is one fallback.
            self.fallback -= 1
        elif kind == 'word' and value == 'u' and number is not None and -32768 <= number <= 65535:
            self.unicode(number)
        elif (kind == 'word' and value == 'uc' and number is not None
              and 0 <= number <= self.limits.max_stream_bytes):
            self.state.uc = number
        else:
            self.valid = False


def parse_rtf_bytes(data: bytes, limits: Limits) -> Document:
    """Extract RTF text, simple tables and separate stories within ``limits``.

    Malformed syntax raises InvalidDocumentError; resource exhaustion raises
    LimitExceededError. Both derive from ParseError. Formatting other than
    paragraph heading levels is intentionally discarded. Only an uncompressed
    RTF root with version 1 is accepted.
    """
    if len(data) > limits.max_file_bytes:
        raise LimitExceededError('RTF file size limit exceeded')
    if len(data) > limits.max_stream_bytes:
        raise LimitExceededError('RTF stream size limit exceeded')
    start = 3 if data.startswith(b'\xef\xbb\xbf') else 0
    while start < len(data) and data[start] in b' \t\r\n':
        start += 1
    if not data.startswith(b'{\\rtf1', start):
        raise InvalidDocumentError('Not an RTF version 1 document')
    end = start + 6
    if end < len(data) and (_letter(data[end]) or 48 <= data[end] <= 57):
        raise InvalidDocumentError('Invalid RTF header')
    return _Parser(limits).parse(data, start)
