"""Bounded RTF text/structure reader, not a layout engine.

Original implementation; reference/research provenance: docs/research-rtf.md.
The lexer consumes bytes, including opaque binary payloads, before interpretation.
"""
from __future__ import annotations

import codecs
from dataclasses import dataclass, replace

from .errors import InvalidDocumentError, LimitExceededError
from .limits import Limits
from .models import Cell, Document, Paragraph, Table

# RTF destination names and charset numbers are format facts, not executable code
# imported from another reader. Unknown starred destinations are also suppressed.
_SKIP = set("""
author title subject keywords company manager operator category comment doccomm
hlinkbase creatim revtim printim buptim
colortbl stylesheet info filetbl revtbl rsidtbl listtable listoverridetable
latentstyles generator xmlnstbl datastore themedata colorschememapping
pict object objdata objclass objname objalias result shppict nonshppict
shprslt sp sn sv background do private datafield fontemb fontfile
fldinst fldtype formfield annotation atnauthor atnid atndate
bkmkstart bkmkend xe tc txe rxe pn pntxta pntxtb
ftnsep ftnsepc ftncn aftnsep aftnsepc aftncn
userprops docvar template nextfile htmltag mhtmltag xmlopen xmlclose
xmlattrname xmlattrvalue mmath mmathPict moMath moMathPara
nesttableprops nonesttables
""".split())
_SHAPE_CONTAINERS = {'shp', 'shpinst', 'shpgrp'}
_HEADERS = set('header headerl headerr headerf footer footerl footerr footerf'.split())
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


@dataclass(slots=True)
class _State:
    skip: bool = False
    font_table: bool = False
    shape_container: bool = False
    font: int | None = None
    encoding: str = 'cp1252'
    uc: int = 1
    hidden: bool = False
    deleted: bool = False
    first: bool = True
    starred: bool = False
    target: int = 0
    upr: bool = False
    children: int = 0


class _Sink:
    def __init__(self, parser: _Parser, story: str = ''):
        self.parser = parser
        self.story = story
        self.blocks: list[Paragraph | Table] = []
        self.parts: list[str] = []
        self.row: list[Cell] | None = None
        self.expected = 0
        self.table: Table | None = None
        self.definitions: list[tuple[int | None, str, str]] = []
        self.horizontal = self.vertical = ''
        self.left = 0
        self.nested = False
        self.vertical_anchors: dict[tuple[int, int, int, int], Cell] = {}

    def text(self, text: str):
        if text:
            self.parser.charge(len(text))
            self.parts.append(text)

    def paragraph(self, force: bool = False):
        if self.row is not None:
            self.text('\n')
        elif self.parts or force:
            self.blocks.append(Paragraph(''.join(self.parts)))
            self.parts.clear()
            self.table = None
            self.vertical_anchors.clear()

    def start_row(self):
        # Writers may repeat row properties after cell content, before \row.
        # Only \row (or final recovery) ends a row; \trowd resets definitions.
        if self.row is None:
            self.paragraph()
            self.row = []
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
                    'Merged table cells retained as separate cells; spans not reconstructed.')

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
            anchor.text = '\n'.join(fragments)
            anchor.col_span = end - start
            for cell in self.row[start + 1:end]:
                cell.text = ''
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
                        'Vertical merge continuation ambiguous or nonempty; cells retained.')

    def cell(self):
        if self.row is None:
            self.parser.warn('Table cell without row definition recovered.')
            self.row = []
        self.parser.cells += 1
        if self.parser.cells > self.parser.limits.max_cells:
            raise LimitExceededError('RTF cell limit exceeded')
        self.row.append(Cell(''.join(self.parts)))
        self.parts.clear()

    def end_row(self, recovered: bool = False):
        if self.row is None:
            self.start_row()
        if self.parts or not self.row:
            self.cell()
        complete = bool(self.expected) and len(self.row) == self.expected
        while len(self.row) < self.expected:
            self.cell()
        if self.expected and len(self.row) != self.expected:
            self.parser.warn('Table cell count differs from row definition.')
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

    def finish(self):
        if self.row is not None:
            self.parser.warn('Incomplete table row recovered.')
            self.end_row(recovered=True)
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

    def warn(self, message: str):
        if message not in self.document.warnings:
            self.document.warnings.append(message)

    def charge(self, count: int):
        if count > self.limits.max_text_chars - self.chars:
            raise LimitExceededError('RTF text limit exceeded')
        self.chars += count

    @property
    def sink(self):
        return self.sinks[self.state.target]

    def visible(self):
        return not (self.state.skip or self.state.font_table or self.state.shape_container
                    or self.state.hidden or self.state.deleted)

    def high_end(self):
        if self.pending_high is not None:
            self.pending_high = None
            self.warn('Unpaired Unicode surrogate replaced.')
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
            self.warn('Unsupported code page replaced with Windows-1252.')
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
                self.warn('Invalid encoded text replaced.')
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
                    self.warn('Unpaired Unicode surrogate replaced.')
                    self.sink.text('\ufffd')
                else:
                    self.sink.text(chr(unit))
        self.fallback = self.state.uc

    def destination(self, word: str):
        s = self.state
        if s.skip:
            return
        if word in _SKIP:
            s.skip = True
            if word in {'pict', 'object', 'mmath', 'moMath', 'moMathPara'}:
                self.warn('Pictures, objects, shapes or equations omitted.')
            elif word == 'annotation':
                self.warn('Annotations omitted.')
        elif word == 'fonttbl':
            s.font_table = True
        elif s.font_table:
            return
        elif word in _SHAPE_CONTAINERS:
            # Traverse only recognized shape containers, never reopen a skipped
            # ancestor. Property values and the legacy rendering are hard skips.
            self.high_end()
            s.shape_container = True
            self.warn('Shape drawing and layout omitted.')
        elif s.shape_container and word in _HEADERS | {'footnote'}:
            s.skip = True
        elif word in _HEADERS or word in {'footnote', 'shptxt'}:
            self.high_end()
            story = 'headers_footers' if word in _HEADERS else (
                'footnotes' if word == 'footnote' else 'textboxes')
            self.sinks.append(_Sink(self, story))
            s.target = len(self.sinks) - 1
            s.shape_container = False
            if word != 'shptxt':
                s.hidden = False
                s.deleted = False
        elif s.starred and word not in {'fldrslt', 'ud'}:
            s.skip = True
            self.warn('Unknown optional destinations omitted.')

    def word(self, word: str, number: int | None):
        s = self.state
        if s.first or s.starred:
            self.destination(word)
        s.first = s.starred = False
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
                        self.warn('Unsupported font charset or symbol font; using document code page.')
                self.fonts[s.font] = charset, explicit
            return
        if word in _SKIP or word in _SHAPE_CONTAINERS or word == 'fonttbl':
            self.destination(word)
        elif s.shape_container:
            # Shape controls/stray text cannot modify the surrounding story.
            return
        elif word == 'upr':
            s.upr = True
            s.children = 0
            self.warn('Unicode alternate selected; ANSI alternate omitted.')
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
            s.font = self.default_font
            s.hidden = False
            s.deleted = False
        elif word in {'v', 'deleted'}:
            self.high_end()
            if word == 'v':
                s.hidden = number != 0
            else:
                s.deleted = number != 0
            self.warn('Hidden or deleted text omitted.')
        elif word == 'ftnalt' and self.sink.story == 'footnotes':
            self.sink.story = 'endnotes'
        elif self.visible():
            if word in _CHARS:
                self.emit(_CHARS[word])
            elif word in {'par', 'sect', 'page'}:
                self.high_end()
                self.sink.paragraph(force=True)
            elif word == 'trowd':
                self.high_end()
                self.sink.start_row()
            elif word == 'cellx':
                self.definitions += 1
                if self.definitions > self.limits.max_cells:
                    raise LimitExceededError('RTF cell definition limit exceeded')
                self.sink.define_cell(number)
            elif word == 'trleft':
                self.sink.left = number if number is not None else 0
            elif word == 'cell':
                self.high_end()
                self.sink.cell()
            elif word == 'row':
                self.high_end()
                self.sink.end_row()
            elif word in {'clmgf', 'clmrg', 'clvmgf', 'clvmrg'}:
                if word in {'clmgf', 'clmrg'}:
                    self.sink.horizontal = word
                else:
                    self.sink.vertical = word
            elif word in {'nestcell', 'nestrow'} or (word == 'itap' and number and number > 1):
                self.sink.nested = True
                self.warn('Nested table structure flattened; cell spans not reconstructed.')
                if word in {'nestcell', 'nestrow'}:
                    self.emit('\t' if word == 'nestcell' else '\n')

    def parse(self, data: bytes, start: int) -> Document:
        closed = False
        for kind, value, number in _tokens(data, start, self.limits):
            if closed:
                if kind == 'bytes' and all(b in b' \t\r\n' for b in value):
                    continue
                raise InvalidDocumentError('Data after RTF root group')
            if kind == 'bytes':
                self.state.first = False
                self.byte_text(value)
                continue
            self.flush()
            if kind == 'open':
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
            elif kind == 'close':
                self.fallback = 0
                if not self.stack:
                    raise InvalidDocumentError('Unbalanced RTF closing group')
                parent = self.stack.pop()
                if parent.target != self.state.target:
                    self.high_end()
                    self.sink.finish()
                self.state = parent
                if not self.stack:
                    closed = True
            elif self.fallback:
                # One control word/symbol or an entire bin token is one fallback
                # character. Its semantic side effects must not be applied.
                self.fallback -= 1
            elif kind == 'binary':
                if self.visible():
                    self.warn('Binary payload omitted.')
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
        extras: dict[str, list[str]] = {}
        for sink in self.sinks[1:]:
            # Story tables are preserved as tab/newline text in model extras.
            self.charge(max(0, len(sink.blocks) - 1))
            parts = []
            for block in sink.blocks:
                if isinstance(block, Paragraph):
                    parts.append(block.text)
                else:
                    self.warn('Tables in headers or notes flattened to text.')
                    self.charge(sum(max(0, len(row) - 1) for row in block.rows)
                                + max(0, len(block.rows) - 1))
                    parts.append('\n'.join('\t'.join(c.text for c in row) for row in block.rows))
            text = '\n'.join(parts)
            if text:
                if extras.get(sink.story):
                    self.charge(1)
                extras.setdefault(sink.story, []).append(text)
        for story, parts in extras.items():
            setattr(self.document, story, '\n'.join(parts))
        return self.document


def parse_rtf_bytes(data: bytes, limits: Limits) -> Document:
    """Extract RTF text, simple tables and separate stories within ``limits``.

    Malformed syntax raises InvalidDocumentError; resource exhaustion raises
    LimitExceededError. Both derive from ParseError. Formatting is intentionally
    discarded. Only an uncompressed RTF root with version 1 is accepted.
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
