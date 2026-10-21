"""Bounded text extraction from the live object graph of PowerPoint 97–2003.

Independent implementation of MS-PPT §§2.3, 2.4.14, 2.5 and 2.9:
https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/1fc22d56-28f9-4818-bd45-67c2bf721ccf
Cross-checked against Apache POI HSLF UserEditAtom, PersistPtrHolder and
EscherTextboxWrapper (https://github.com/apache/poi/tree/trunk/poi-scratchpad/src/main/java/org/apache/poi/hslf).
No code copied from POI or sharepoint2text. No repair scan or stale-text fallback.

Extracts outline and native drawing text, including grouped shapes/table cells.
Does not render layouts, inherit master text, OCR pictures, or extract embedded
objects, comments or version-specific extension text. Stored WordArt geometry
text is extracted from live shapes; alternate XML representations are not merged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from struct import unpack_from
from typing import Iterator

from ._ole import open_ole, read_stream
from .errors import (EncryptedDocumentError, InvalidDocumentError,
                     LimitExceededError, UnsupportedFormatError)
from .limits import Limits
from .models import Document, Slide


@dataclass(frozen=True, slots=True)
class _Record:
    type: int
    version: int
    instance: int
    start: int
    end: int
    depth: int


@dataclass(slots=True)
class _Entry:
    persist_id: int
    slide_id: int
    records: list[_Record] = field(default_factory=list)


class _Parser:
    def __init__(self, data: bytes, limits: Limits):
        self.data = data
        self.limits = limits
        self.records = 0
        self.text_chars = 0
        self.persist: dict[int, int] = {}
        self.warnings: list[str] = []

    def charge(self, count: int = 1) -> None:
        self.records += count
        if self.records > self.limits.max_records:
            raise LimitExceededError('PPT record/persist-entry limit exceeded')

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def record(self, offset: int, end: int, depth: int = 1) -> _Record:
        if depth > self.limits.max_depth:
            raise LimitExceededError('PPT nesting depth limit exceeded')
        if not 0 <= offset <= end - 8 or end > len(self.data):
            raise InvalidDocumentError('PPT record offset/header outside parent bounds')
        self.charge()
        vi, typ, size = unpack_from('<HHI', self.data, offset)
        start = offset + 8
        if size > end - start:
            raise InvalidDocumentError('PPT record payload outside parent bounds')
        return _Record(typ, vi & 15, vi >> 4, start, start + size, depth)

    def children(self, rec: _Record) -> Iterator[_Record]:
        offset = rec.start
        while offset < rec.end:
            child = self.record(offset, rec.end, rec.depth + 1)
            yield child
            offset = child.end

    def size(self, rec: _Record, minimum: int, exact: bool = False) -> None:
        n = rec.end - rec.start
        if n < minimum or (exact and n != minimum):
            raise InvalidDocumentError(f'invalid PPT record length for type {rec.type}')

    def u32(self, rec: _Record, offset: int = 0) -> int:
        self.size(rec, offset + 4)
        return unpack_from('<I', self.data, rec.start + offset)[0]

    def resolve(self, pid: int, typ: int) -> _Record:
        if pid not in self.persist:
            raise InvalidDocumentError('unresolved PPT persist reference')
        rec = self.record(self.persist[pid], len(self.data))
        if rec.type != typ or rec.version != 15:
            raise InvalidDocumentError('PPT persist reference has incorrect object type')
        return rec

    def directory(self, edit_offset: int) -> int:
        seen: set[int] = set()
        document_id = None
        while edit_offset:
            if edit_offset in seen:
                raise InvalidDocumentError('cyclic PPT UserEdit chain')
            seen.add(edit_offset)
            edit = self.record(edit_offset, len(self.data))
            if edit.type != 4085 or edit.version != 0 or edit.end - edit.start not in (28, 32):
                raise InvalidDocumentError('invalid PPT UserEditAtom')
            if edit.end - edit.start == 32 and self.u32(edit, 28):
                raise EncryptedDocumentError('encrypted PPT is not supported')
            previous = self.u32(edit, 8)
            directory_offset = self.u32(edit, 12)
            if previous >= edit_offset or not previous < directory_offset < edit_offset:
                raise InvalidDocumentError('invalid PPT edit/directory ordering or cycle')
            if document_id is None:
                document_id = self.u32(edit, 16)
            directory = self.record(directory_offset, edit_offset)
            if directory.type not in (6001, 6002) or directory.version != 0:
                raise InvalidDocumentError('invalid PPT persist directory')
            offset = directory.start
            local_ids: set[int] = set()
            while offset < directory.end:
                if directory.end - offset < 4:
                    raise InvalidDocumentError('truncated PPT persist directory')
                packed = unpack_from('<I', self.data, offset)[0]
                first, count = packed & 0xfffff, packed >> 20
                offset += 4
                if not first or not count or first + count > 0x100000 or count * 4 > directory.end - offset:
                    raise InvalidDocumentError('invalid PPT persist directory run')
                self.charge(count)
                for pid in range(first, first + count):
                    target = unpack_from('<I', self.data, offset)[0]
                    offset += 4
                    # Entries belong to this edit; unchanged objects are inherited
                    # from older directories, never reintroduced via stale offsets.
                    if pid in local_ids or not previous <= target <= directory_offset - 8:
                        raise InvalidDocumentError('duplicate persist ID or invalid PPT object offset')
                    local_ids.add(pid)
                    # Newest edit wins; older entries supply unchanged objects only.
                    self.persist.setdefault(pid, target)
            edit_offset = previous
        if document_id is None:
            raise InvalidDocumentError('missing current PPT edit')
        return document_id

    def entries(self, rec: _Record) -> list[_Entry]:
        if rec.version != 15:
            raise InvalidDocumentError('invalid PPT slide list container')
        result: list[_Entry] = []
        ids: set[int] = set()
        pids: set[int] = set()
        for child in self.children(rec):
            if child.type == 1011:
                self.size(child, 20, exact=True)
                pid, sid = self.u32(child), self.u32(child, 12)
                if not pid or not sid or sid in ids or pid in pids:
                    raise InvalidDocumentError('duplicate or null PPT slide/notes ID')
                ids.add(sid)
                pids.add(pid)
                result.append(_Entry(pid, sid))
                if len(result) > self.limits.max_slides:
                    raise LimitExceededError('PPT slide/notes count limit exceeded')
            elif result:
                result[-1].records.append(child)
            elif child.type in (3999, 4000, 4008):
                raise InvalidDocumentError('PPT outline text precedes slide reference')
        return result

    def decode(self, rec: _Record, terminated: bool = False) -> str:
        length = rec.end - rec.start
        if rec.type == 4000 and length % 2:
            raise InvalidDocumentError('odd-length PPT UTF-16 text')
        # Bound allocation before decoding. UTF-16 code units are a conservative
        # character budget, including discarded controls and surrogate pairs.
        self.text_chars += length // 2 if rec.type == 4000 else length
        if self.text_chars > self.limits.max_text_chars:
            raise LimitExceededError('PPT text limit exceeded')
        try:
            text = self.data[rec.start:rec.end].decode('utf-16-le' if rec.type == 4000 else 'latin-1')
        except UnicodeDecodeError as exc:
            raise InvalidDocumentError('invalid PPT UTF-16 text') from exc
        if terminated and '\x00' in text[:-1]:
            raise InvalidDocumentError('embedded null in OfficeArt geometry text')
        return text.replace('\r\n', '\n').replace('\r', '\n').replace('\v', '\n').replace('\f', '\n').replace('\x00', '').strip()

    def text_blocks(self, records: list[_Record], outline_count: int | None = None) -> list[tuple[int, str]]:
        blocks: list[tuple[int, str]] = []
        kind: int | None = None
        chunks: list[str] = []
        def flush() -> None:
            if kind is not None:
                blocks.append((kind, ''.join(chunks)))
        for rec in records:
            if rec.type == 3999:
                self.size(rec, 4, exact=True)
                flush()
                kind = self.u32(rec)
                chunks = []
            elif rec.type in (4000, 4008):
                if kind is None:
                    raise InvalidDocumentError('PPT text has no TextHeaderAtom')
                chunks.append(self.decode(rec))
            elif rec.type == 3998:
                self.size(rec, 4, exact=True)
                if outline_count is None or self.u32(rec) >= outline_count:
                    raise InvalidDocumentError('invalid PPT outline text reference')
                # Already emitted from this slide's outline; no value-based dedup.
        flush()
        return blocks

    def shape_properties(self, rec: _Record) -> str | None:
        """Read only gtextUNICODE, never names/fonts/alternate XML as text.

        MS-ODRAW 2.2.9 and 2.3.22.1–2: six-byte entries precede complex
        payloads in entry order. fBid is undefined for gtext and ignored.
        """
        if rec.version != 3:
            raise InvalidDocumentError('invalid OfficeArt property table version')
        self.charge(rec.instance)
        offset = rec.start + rec.instance * 6
        if offset > rec.end:
            raise InvalidDocumentError('OfficeArt property table outside bounds')
        value = None
        seen_text = False
        for pos in range(rec.start, offset, 6):
            flags, size = unpack_from('<HI', self.data, pos)
            pid = flags & 0x3fff
            if pid == 0xc0:
                if seen_text:
                    raise InvalidDocumentError('duplicate OfficeArt geometry text property')
                seen_text = True
                if not flags & 0x8000 and size:
                    raise InvalidDocumentError('non-complex OfficeArt geometry text')
            if not flags & 0x8000:
                continue
            # Legacy pVertices/pSegmentInfo may exclude the six-byte array
            # header from op (also handled by POI EscherArrayProperty).
            if pid in (0x145, 0x146) and size:
                if rec.end - offset < 6:
                    raise InvalidDocumentError('truncated OfficeArt array header')
                count, _, width = unpack_from('<HHh', self.data, offset)
                width = (-width >> 2) if width < 0 else width
                if count * width == size:
                    size += 6
            if size > rec.end - offset:
                raise InvalidDocumentError('OfficeArt complex property outside bounds')
            if pid == 0xc0 and rec.type == 0xf00b:
                if size < 2 or size % 2 or self.data[offset + size - 2:offset + size] != b'\0\0':
                    raise InvalidDocumentError('invalid OfficeArt geometry text terminator/length')
                # Reuse the strict UTF-16 decoder and shared budget, including
                # the terminator and any surrogate pairs, before allocation.
                value = self.decode(_Record(4000, 0, 0, offset, offset + size, rec.depth),
                                    terminated=True)
            elif pid == 0x3a9 and size:
                self.warn('PPT alternate OfficeArt XML is not extracted; extension-only content may be omitted.')
            offset += size
        if offset != rec.end:
            raise InvalidDocumentError('unclaimed OfficeArt complex property bytes')
        return value

    def shape_text(self, shape: _Record, outline: list[tuple[int, str]]) -> list[tuple[int, str]]:
        blocks: list[tuple[int, str]] = []
        geometry = None
        native: list[str] = []
        for rec in self.children(shape):
            if rec.type == 0xf00d:
                atoms = list(self.children(rec))
                texts = self.text_blocks(atoms, len(outline))
                blocks.extend(texts)
                native.extend(text for _, text in texts)
                for atom in atoms:
                    if atom.type == 3998:
                        native.append(outline[self.u32(atom)][1])
            elif rec.type in (0xf00b, 0xf122):
                text = self.shape_properties(rec)
                if text is not None:
                    if geometry is not None:
                        raise InvalidDocumentError('duplicate OfficeArt geometry text table')
                    geometry = text
        # Suppress an identical representation only on this exact shape,
        # including a validated outline reference. Equal text on other shapes
        # remains independent content; distinct attached text is retained.
        if geometry and geometry not in native:
            blocks.append((1, geometry))
        return blocks

    def drawing_text(self, drawing: _Record, outline: list[tuple[int, str]]) -> list[tuple[int, str]]:
        blocks: list[tuple[int, str]] = []
        stack = [iter(self.children(drawing))]
        while stack:
            rec = next(stack[-1], None)
            if rec is None:
                stack.pop()
            elif rec.type in (0xf002, 0xf003, 0xf004):
                if rec.version != 15:
                    raise InvalidDocumentError('invalid OfficeArt container')
                if rec.type == 0xf004:
                    blocks.extend(self.shape_text(rec, outline))
                else:
                    stack.append(iter(self.children(rec)))
        return blocks

    def sheet(self, entry: _Entry, typ: int) -> tuple[list[tuple[int, str]], int, bool]:
        rec = self.resolve(entry.persist_id, typ)
        outline = self.text_blocks(entry.records)
        blocks = list(outline)
        link = None
        hidden = False
        for child in self.children(rec):
            if child.type == (1007 if typ == 1006 else 1009):
                if link is not None:
                    raise InvalidDocumentError('duplicate PPT slide/notes atom')
                self.size(child, 24 if typ == 1006 else 8, exact=True)
                link = self.u32(child, 16 if typ == 1006 else 0)
            elif child.type == 1036:
                blocks.extend(self.drawing_text(child, outline))
            elif child.type == 1017:
                self.size(child, 16, exact=True)
                hidden = bool(self.data[child.start + 10] & 4)
            elif child.type == 5000:
                self.warn('PPT extension records are not extracted; extension-only content may be omitted.')
        if link is None:
            raise InvalidDocumentError('missing PPT slide/notes atom')
        return blocks, link, hidden

    def parse(self, edit_offset: int) -> Document:
        root = self.resolve(self.directory(edit_offset), 1000)
        lists: dict[int, list[_Entry]] = {}
        for rec in self.children(root):
            if rec.type == 4080 and rec.instance in (0, 2):
                if rec.instance in lists:
                    raise InvalidDocumentError('duplicate PPT slide/notes list')
                lists[rec.instance] = self.entries(rec)
        notes = {e.slide_id: e for e in lists.get(2, [])}
        document = Document(format='ppt')
        emitted_chars = 0
        for entry in lists.get(0, []):
            blocks, note_id, hidden = self.sheet(entry, 1006)
            title = '\n'.join(text for kind, text in blocks if kind in (0, 6) and text)
            body = '\n'.join(text for kind, text in blocks if kind not in (0, 6) and text)
            note_text = ''
            if note_id:
                if note_id not in notes:
                    raise InvalidDocumentError('unresolved PPT notes ID')
                note_blocks, slide_id, _ = self.sheet(notes[note_id], 1008)
                if slide_id != entry.slide_id:
                    raise InvalidDocumentError('PPT notes backlink does not match slide ID')
                note_text = '\n'.join(text for _, text in note_blocks if text)
            parts = [part for part in (title, body, note_text) if part]
            emitted_chars += sum(map(len, parts)) + max(0, len(parts) - 1)
            if document.slides:
                emitted_chars += 2  # Document.text inserts blank lines between slides.
            if emitted_chars > self.limits.max_text_chars:
                raise LimitExceededError('PPT output text limit exceeded')
            document.slides.append(Slide(len(document.slides) + 1, title, body, note_text, hidden))
        document.warnings = self.warnings
        return document


def parse_ppt_bytes(data: bytes, limits: Limits) -> Document:
    """Extract active slides in presentation order, retaining empty slides.

    Malformed live structures fail closed. Inactive persist objects, old edits'
    text, masters and unreferenced notes are never scanned for fallback content.
    """
    with open_ole(data, limits) as ole:
        if ole.exists('EncryptedPackage') or ole.exists('EncryptionInfo'):
            raise EncryptedDocumentError('encrypted PPT is not supported')
        if not ole.exists('PowerPoint Document') and ole.exists('PP40'):
            raise UnsupportedFormatError('PowerPoint 95 is not supported')
        current = read_stream(ole, 'Current User', limits)
        stream = read_stream(ole, 'PowerPoint Document', limits)
    parser = _Parser(current, limits)
    user = parser.record(0, len(current))
    if user.type != 4086 or user.version != 0:
        raise InvalidDocumentError('invalid PPT CurrentUserAtom')
    parser.size(user, 20)
    token = parser.u32(user, 4)
    if token == 0xf3d1c4df:
        raise EncryptedDocumentError('encrypted PPT is not supported')
    if token != 0xe391c05f:
        raise UnsupportedFormatError('unsupported PPT Current User token')
    if parser.u32(user) != 20:
        raise InvalidDocumentError('invalid PPT Current User fixed size')
    if unpack_from('<H', current, user.start + 14)[0] != 0x03f4 or current[user.start + 16:user.start + 18] != b'\x03\x00':
        raise UnsupportedFormatError('unsupported PPT binary version')
    name_length = unpack_from('<H', current, user.start + 12)[0]
    parser.size(user, 24 + name_length)
    edit_offset = parser.u32(user, 8)
    parser.data = stream
    return parser.parse(edit_offset)
