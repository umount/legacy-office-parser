"""Bounded text extraction from the live object graph of PowerPoint 97–2003.

Independent implementation of MS-PPT §§2.3, 2.4.14, 2.5 and 2.9:
https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/1fc22d56-28f9-4818-bd45-67c2bf721ccf
Cross-checked against Apache POI HSLF UserEditAtom, PersistPtrHolder and
EscherTextboxWrapper (https://github.com/apache/poi/tree/trunk/poi-scratchpad/src/main/java/org/apache/poi/hslf).
No code copied from POI or sharepoint2text. No repair scan or stale-text fallback.

Extracts outline and native drawing text, including grouped shapes/table cells.
Includes ordinary text shapes from referenced masters when objects are inherited.
Preserves active stored footer/fixed-date strings; dynamic fields are not evaluated.
Does not render layouts, OCR pictures, or extract embedded
objects or unknown version-specific extension text. Active PPT10 comments are
retained separately from slide body and notes. Stored WordArt geometry
text is extracted from live shapes; alternate XML representations are not merged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from struct import unpack_from
from typing import Iterator

from ._ole import open_ole, read_stream
from ._ppt_extensions import _timing_metadata
from .errors import (EncryptedDocumentError, InvalidDocumentError,
                     LimitExceededError, UnsupportedFormatError)
from .limits import Limits
from .models import Document, Slide, SlideComment


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
        self.masters: dict[int, _Entry] = {}
        self.master_cache: dict[int, tuple[list[tuple[int, str]], int]] = {}
        self.master_fields: dict[int, set[int]] = {}
        self.master_hf: dict[int, _Record] = {}
        self.collect_master_fields: set[int] | None = None
        self.local_fields: set[int] | None = None
        self.default_hf: _Record | None = None
        self.hf_cache: dict[int, tuple[int, dict[int, _Record]]] = {}
        self.omit_title_fields = False
        self.inline_footer: _Record | None = None
        self.inline_footer_done = False
        self.outline_sources: list[str] = []

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

    def decode(self, rec: _Record, terminated: bool = False, normalize: bool = True) -> str:
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
        return self.normalize_text(text) if normalize else text

    @staticmethod
    def normalize_text(text: str) -> str:
        return text.replace('\r\n', '\n').replace('\r', '\n').replace('\v', '\n').replace('\f', '\n').replace('\x00', '').strip()

    def text_blocks(self, records: list[_Record], outline_count: int | None = None,
                    sources: list[str] | None = None) -> list[tuple[int, str]]:
        blocks: list[tuple[int, str]] = []
        kind: int | None = None
        chunks: list[str] = []
        text_units = 0
        markers: dict[int, int] = {}
        unknown = False

        def flush() -> None:
            if markers and max(markers) >= text_units:
                raise InvalidDocumentError('PPT field marker outside corresponding text')
            if kind is None:
                return
            original = ''.join(self.normalize_text(chunk) for chunk in chunks)
            if sources is not None:
                sources.append(original)
            # One text atom is the unambiguous association supported here.
            # Do not join independently encoded atoms or guess unknown metadata.
            if (markers and set(markers.values()) == {4090} and not unknown
                    and len(chunks) == 1 and self.inline_footer is not None):
                raw = chunks[0]
                positions = []
                unit = 0
                for index, char in enumerate(raw):
                    if unit in markers:
                        if char != '*':
                            break
                        positions.append(index)
                    unit += 2 if ord(char) > 0xffff else 1
                else:
                    if len(positions) == len(markers):
                        footer = self.inline_footer
                        # Source text was already charged. Charge every copy of
                        # the footer before decoding or constructing expanded text.
                        extra = (len(positions) - 1) * ((footer.end - footer.start) // 2)
                        if self.text_chars + extra + (footer.end - footer.start) // 2 > self.limits.max_text_chars:
                            raise LimitExceededError('PPT inline field text limit exceeded')
                        self.text_chars += extra
                        value = self.decode(_Record(4000, 0, 0, footer.start, footer.end, footer.depth),
                                            normalize=False)
                        pieces = []
                        previous = 0
                        for index in positions:
                            pieces.extend((raw[previous:index], value))
                            previous = index + 1
                        pieces.append(raw[previous:])
                        blocks.append((kind, self.normalize_text(''.join(pieces))))
                        self.inline_footer_done = True
                        return
            if markers:
                self.warn('PPT text field markers are not evaluated; stored text may contain placeholders.')
            blocks.append((kind, original))

        for rec in records:
            if rec.type == 3999:
                self.size(rec, 4, exact=True)
                flush()
                kind = self.u32(rec)
                chunks = []
                text_units = 0
                markers = {}
                unknown = False
            elif rec.type in (4000, 4008):
                if kind is None:
                    raise InvalidDocumentError('PPT text has no TextHeaderAtom')
                chunks.append(self.decode(rec, normalize=False))
                text_units += (rec.end - rec.start) // (2 if rec.type == 4000 else 1)
            elif rec.type in (4056, 4087, 4088, 4089, 4090, 4117):
                self.size(rec, 132 if rec.type == 4117 else (8 if rec.type == 4087 else 4), exact=True)
                if rec.version != 0 or rec.instance != 0 or kind is None:
                    raise InvalidDocumentError('invalid PPT field marker header or text association')
                if rec.type == 4087 and self.data[rec.start + 4] > 12:
                    raise InvalidDocumentError('invalid PPT datetime field format index')
                position = self.u32(rec)
                if position in markers:
                    raise InvalidDocumentError('duplicate or overlapping PPT field markers')
                markers[position] = rec.type
                if self.local_fields is not None:
                    self.local_fields.add({4056: 8, 4087: 7, 4088: 7, 4089: 10, 4090: 9, 4117: 7}[rec.type])
            elif rec.type == 3998:
                self.size(rec, 4, exact=True)
                if outline_count is None or self.u32(rec) >= outline_count:
                    raise InvalidDocumentError('invalid PPT outline text reference')
                unknown = True
                # Already emitted from this slide's outline; no value-based dedup.
            else:
                unknown = True
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

    def master_shape_allowed(self, shape: _Record) -> bool:
        """Ordinary master objects only, never template or header/footer fields.

        MS-PPT 2.7.3/2.7.8 and MS-ODRAW 2.2.40. Inspect metadata before
        decoding text, since client data need not precede the text box.
        """
        allowed = True
        placeholder = None
        for rec in self.children(shape):
            if rec.type == 0xf00a:
                self.size(rec, 8, exact=True)
                if rec.version != 2:
                    raise InvalidDocumentError('invalid master OfficeArtFSP version')
                if self.u32(rec, 4) & 0x408:  # deleted or background
                    allowed = False
            elif rec.type in (0xf00b, 0xf122):
                if rec.version != 3 or rec.instance * 6 > rec.end - rec.start:
                    raise InvalidDocumentError('invalid master OfficeArt property table')
                self.charge(rec.instance)
                for pos in range(rec.start, rec.start + rec.instance * 6, 6):
                    pid, value = unpack_from('<HI', self.data, pos)
                    if pid & 0x3fff in (0x33f, 0x3bf):
                        if pid & 0xc000:
                            raise InvalidDocumentError('invalid master visibility property')
                        if pid == 0x3bf and value & 0x20002 == 0x20002:
                            allowed = False  # explicit fUsefHidden + fHidden
                        if pid == 0x33f and value & 0x10001 == 0x10001:
                            allowed = False  # explicit background shape
            elif rec.type == 0xf011:
                if rec.version != 15:
                    raise InvalidDocumentError('invalid master OfficeArtClientData version')
                for atom in self.children(rec):
                    if atom.type == 3011:
                        self.size(atom, 8, exact=True)
                        # Position=-1 may still describe a conditional field.
                        placeholder = self.data[atom.start + 4]
        if allowed and placeholder in (7, 8, 9) and self.collect_master_fields is not None:
            self.collect_master_fields.add(placeholder)
        return allowed and placeholder is None

    def shape_text(self, shape: _Record, outline: list[tuple[int, str]]) -> list[tuple[int, str]]:
        blocks: list[tuple[int, str]] = []
        geometry = None
        native: list[str] = []
        for rec in self.children(shape):
            if rec.type == 0xf00d:
                atoms = list(self.children(rec))
                sources: list[str] = []
                texts = self.text_blocks(atoms, len(outline), sources)
                blocks.extend(texts)
                native.extend(text for _, text in texts)
                native.extend(sources)
                for atom in atoms:
                    if atom.type == 3998:
                        index = self.u32(atom)
                        native.append(outline[index][1])
                        native.append(self.outline_sources[index])
            elif rec.type == 0xf011 and self.local_fields is not None:
                if rec.version != 15:
                    raise InvalidDocumentError('invalid local OfficeArtClientData version')
                for atom in self.children(rec):
                    if atom.type == 1056:
                        self.size(atom, 1, exact=True)
                        if (atom.version != 0 or atom.instance != 0
                                or self.data[atom.start] not in (7, 8, 9, 10)):
                            raise InvalidDocumentError('invalid PPT round-trip field placeholder')
                        # Modern round-trip field shapes can already contain the
                        # actual text. Do not append a second legacy representation.
                        self.local_fields.add(0)
                    elif atom.type == 3011:
                        self.size(atom, 8, exact=True)
                        placement = self.data[atom.start + 4]
                        if placement in (7, 8, 9):
                            self.local_fields.add(placement)
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

    def drawing_text(self, drawing: _Record, outline: list[tuple[int, str]],
                     inherited: bool = False) -> list[tuple[int, str]]:
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
                    if not inherited or self.master_shape_allowed(rec):
                        blocks.extend(self.shape_text(rec, outline))
                else:
                    children = iter(self.children(rec))
                    if inherited and rec.type == 0xf003:
                        # First shape is the group itself. A deleted group must
                        # not leak text from otherwise ordinary child shapes.
                        first = next(children, None)
                        if first is None or first.type != 0xf004 or first.version != 15:
                            raise InvalidDocumentError('invalid master OfficeArt group')
                        if not self.master_shape_allowed(first):
                            continue
                        blocks.extend(self.shape_text(first, outline))
                    stack.append(children)
        return blocks

    def master_text(self, master_id: int) -> list[tuple[int, str]]:
        """Follow only active inheritance edges; cache each master's own text."""
        blocks: list[tuple[int, str]] = []
        seen: set[int] = set()
        while master_id:
            self.charge()  # cached edges still consume work budget
            if master_id in seen:
                raise InvalidDocumentError('cyclic PPT master inheritance')
            seen.add(master_id)
            if len(seen) > self.limits.max_depth:
                raise LimitExceededError('PPT master inheritance depth limit exceeded')
            if master_id not in self.master_cache:
                entry = self.masters.get(master_id)
                if entry is None or entry.persist_id not in self.persist:
                    raise InvalidDocumentError('unresolved PPT master reference')
                rec = self.record(self.persist[entry.persist_id], len(self.data))
                if rec.type not in (1006, 1016) or rec.version != 15:
                    raise InvalidDocumentError('PPT master reference has incorrect object type')
                own: list[tuple[int, str]] = []
                parent = None
                fields: set[int] = set()
                for child in self.children(rec):
                    if child.type == 1007:
                        if parent is not None:
                            raise InvalidDocumentError('duplicate PPT master slide atom')
                        self.size(child, 24, exact=True)
                        target = self.u32(child, 12)
                        if rec.type == 1016 and target:
                            raise InvalidDocumentError('PPT main master has a parent')
                        follows_objects = bool(self.data[child.start + 20] & 1)
                        if rec.type == 1006 and follows_objects and not target:
                            raise InvalidDocumentError('unresolved PPT master reference')
                        parent = target if follows_objects else 0
                    elif child.type == 1036:
                        # Master lists carry no presentation outline text.
                        self.collect_master_fields = fields
                        try:
                            own.extend(self.drawing_text(child, [], inherited=True))
                        finally:
                            self.collect_master_fields = None
                    elif child.type == 4057 and child.instance == 0:
                        if master_id in self.master_hf:
                            raise InvalidDocumentError('duplicate PPT master header/footer container')
                        self.master_hf[master_id] = child
                    elif child.type == 5000:
                        self.warn('PPT master extension records are not extracted; extension-only content may be omitted.')
                if parent is None:
                    raise InvalidDocumentError('missing PPT master slide atom')
                # Inherited title-kind text is still ordinary master artwork,
                # not the title of the presentation slide.
                self.master_cache[master_id] = ([(1, text) for _, text in own if text], parent)
                self.master_fields[master_id] = fields
            own, master_id = self.master_cache[master_id]
            # Cached text still costs a visit per block on every slide. Charge
            # before extending, not after the repeated allocation/iteration.
            self.charge(len(own))
            blocks.extend(own)
        return blocks

    def header_footer_settings(self, rec: _Record) -> tuple[int, dict[int, _Record]]:
        """MS-PPT 2.4.15: bounded flags and stored strings, never field evaluation."""
        if rec.start in self.hf_cache:
            self.charge()
            return self.hf_cache[rec.start]
        if rec.version != 15:
            raise InvalidDocumentError('invalid PPT header/footer container')
        flags = None
        strings: dict[int, _Record] = {}
        for child in self.children(rec):
            if child.type == 4058:
                self.size(child, 4, exact=True)
                if flags is not None or child.version != 0 or child.instance != 0:
                    raise InvalidDocumentError('invalid or duplicate PPT header/footer flags')
                flags = unpack_from('<H', self.data, child.start + 2)[0]
            elif child.type == 4026 and child.instance in (0, 2):
                length = child.end - child.start
                if child.version != 0 or length % 2 or (child.instance == 0 and length > 510):
                    raise InvalidDocumentError('invalid PPT header/footer string record')
                if child.instance in strings:
                    raise InvalidDocumentError('duplicate PPT header/footer string')
                strings[child.instance] = child
        if flags is None:
            raise InvalidDocumentError('missing PPT header/footer flags')
        self.hf_cache[rec.start] = (flags, strings)
        return flags, strings

    def static_slide_fields(self, master_id: int, local: _Record | None,
                            local_fields: set[int], title: bool) -> list[tuple[int, str]]:
        # A local container overrides the document default as a whole; missing
        # local strings must not resurrect stale default strings.
        source = local if local is not None else self.default_hf
        settings = self.header_footer_settings(source) if source is not None else None
        if settings is not None:
            flags, strings = settings
            # These strings are optional. An enabled but unset static field is
            # empty, not an unsupported dynamic field (common in blank decks).
            if not (flags & 8 or (flags & 1 and (flags & 2 or not flags & 4 or 0 in strings))
                    or (flags & 32 and 2 in strings)):
                return []
        fields: set[int] = set()
        master_sources = []
        current = master_id
        while current:
            self.charge()
            fields.update(self.master_fields.get(current, ()))
            if current in self.master_hf:
                master_sources.append(self.master_hf[current])
            current = self.master_cache[current][1]
        if title and self.omit_title_fields:
            return []
        if source is None:
            # Per-master footer settings are not established as slide defaults.
            for rec in master_sources:
                flags, _ = self.header_footer_settings(rec)
                if flags & 0x29:
                    self.warn('PPT active master header/footer settings are not resolved for slides.')
            return []
        flags, strings = settings
        blocks = []
        for placement, bit, instance, name in ((7, 1, 0, 'date'), (8, 8, None, 'slide-number'),
                                              (9, 32, 2, 'footer')):
            if not flags & bit:
                continue
            if (placement == 9 or (placement == 7 and flags & 4 and not flags & 2)) and instance not in strings:
                continue
            if placement == 9 and self.inline_footer_done:
                continue
            if placement in local_fields or 0 in local_fields:
                self.warn('PPT slide-local field shapes are retained as stored text; legacy field text is not merged.')
                continue
            if placement not in fields:
                self.warn('PPT active header/footer fields have unresolved placement or visibility; field text is omitted.')
                continue
            if placement == 8 or (placement == 7 and (not flags & 4 or flags & 2)):
                self.warn(f'PPT active {name} field is not evaluated; no generated value is extracted.')
                continue
            atom = strings.get(instance)
            if atom is None:
                continue
            # CString payloads use the same UTF-16 allocation and output budget.
            value = self.decode(_Record(4000, 0, 0, atom.start, atom.end, atom.depth))
            if value:
                blocks.append((1, value))
        return blocks

    def comment(self, rec: _Record) -> SlideComment:
        if rec.version != 15 or rec.instance != 0:
            raise InvalidDocumentError('invalid PPT comment container header')
        strings: dict[int, str] = {}
        settings = False
        for child in self.children(rec):
            if child.type == 4026:
                length = child.end - child.start
                if (child.version != 0 or child.instance not in (0, 1, 2)
                        or child.instance in strings or length % 2
                        or length > (64000 if child.instance == 1 else 104)):
                    raise InvalidDocumentError('invalid or duplicate PPT comment string')
                value = self.decode(
                    _Record(4000, 0, 0, child.start, child.end, child.depth), normalize=False)
                if any((ord(char) < 32 and not (child.instance == 1 and char in '\t\r\n'))
                       or 0x7f <= ord(char) <= 0x9f for char in value):
                    raise InvalidDocumentError('invalid control in PPT comment string')
                strings[child.instance] = self.normalize_text(value)
            elif child.type == 12001:
                self.size(child, 28, exact=True)
                if (settings or child.version != 0 or child.instance != 0
                        or unpack_from('<i', self.data, child.start)[0] < 0):
                    raise InvalidDocumentError('invalid or duplicate PPT comment settings')
                settings = True
            else:
                self.warn('PPT unknown comment metadata is not extracted.')
        if not settings:
            raise InvalidDocumentError('missing PPT comment settings')
        return SlideComment(strings.get(1, ''), strings.get(0, ''), strings.get(2, ''))

    def slide_comments(self, tags: _Record, comments: list[SlideComment], seen: set[str]) -> bool:
        """Only direct typed PPT10 comments; return whether remaining data is known."""
        if tags.version != 15 or tags.instance != 0:
            return False
        known = True
        for tag in self.children(tags):
            if tag.type != 5002 or tag.version != 15 or tag.instance != 0:
                known = False
                continue
            pair = list(self.children(tag))
            if (len(pair) != 2 or pair[0].type != 4026 or pair[0].version != 0
                    or pair[0].instance != 0 or pair[0].end - pair[0].start != 16
                    or self.data[pair[0].start:pair[0].end] != '___PPT10'.encode('utf-16-le')):
                known = False
                continue
            blob = pair[1]
            if blob.type != 5003 or blob.version != 0 or blob.instance != 0:
                raise InvalidDocumentError('invalid PPT10 data header')
            children = list(self.children(blob))
            has_comments = any(child.type == 12000 for child in children)
            if 'PPT10' in seen:
                if has_comments or 'comments' in seen:
                    raise InvalidDocumentError('duplicate PPT10 slide comment extension')
                known = False
                continue
            seen.add('PPT10')
            if has_comments:
                seen.add('comments')
            metadata_types: set[int] = set()
            for child in children:
                if child.type == 12000:
                    comments.append(self.comment(child))
                else:
                    # Reuse the existing metadata-only classifier on this record
                    # span. Do not copy payloads or search nested unknown records.
                    span = _Record(5003, 0, 0, child.start - 8, child.end, blob.depth)
                    if child.type in metadata_types or not _timing_metadata(self, span):
                        known = False
                    metadata_types.add(child.type)
        return known

    def sheet(self, entry: _Entry, typ: int) -> tuple[list[tuple[int, str]], int, bool, list[SlideComment]]:
        rec = self.resolve(entry.persist_id, typ)
        self.local_fields = set() if typ == 1006 else None
        self.inline_footer = None
        self.inline_footer_done = False
        children = list(self.children(rec))
        local_hf = None
        for child in children:
            if child.type == 4057 and child.instance == 0 and typ == 1006:
                if local_hf is not None:
                    raise InvalidDocumentError('duplicate PPT slide header/footer container')
                local_hf = child
        if local_hf is not None:
            flags, strings = self.header_footer_settings(local_hf)
            if flags & 32:
                self.inline_footer = strings.get(2)
        self.outline_sources = []
        outline = self.text_blocks(entry.records, sources=self.outline_sources)
        blocks = list(outline)
        link = None
        hidden = False
        master_id = 0
        title_layout = False
        comments: list[SlideComment] = []
        seen_extensions: set[str] = set()
        for child in children:
            if child.type == (1007 if typ == 1006 else 1009):
                if link is not None:
                    raise InvalidDocumentError('duplicate PPT slide/notes atom')
                self.size(child, 24 if typ == 1006 else 8, exact=True)
                link = self.u32(child, 16 if typ == 1006 else 0)
                if typ == 1006:
                    title_layout = self.u32(child) == 0
                if typ == 1006 and self.data[child.start + 20] & 1:
                    master_id = self.u32(child, 12)
                    if not master_id:
                        raise InvalidDocumentError('unresolved PPT master reference')
            elif child.type == 1036:
                blocks.extend(self.drawing_text(child, outline))
            elif child.type == 1017:
                self.size(child, 16, exact=True)
                hidden = bool(self.data[child.start + 10] & 4)
            elif child.type == 5000:
                if typ != 1006 or not self.slide_comments(child, comments, seen_extensions):
                    self.warn('PPT extension records are not extracted; extension-only content may be omitted.')
        if link is None:
            raise InvalidDocumentError('missing PPT slide/notes atom')
        local_fields = self.local_fields or set()
        self.local_fields = None
        self.inline_footer = None
        self.outline_sources = []
        if master_id:
            blocks.extend(self.master_text(master_id))
        if typ == 1006:
            blocks.extend(self.static_slide_fields(master_id, local_hf, local_fields, title_layout))
        return blocks, link, hidden, comments

    def parse(self, edit_offset: int) -> Document:
        root = self.resolve(self.directory(edit_offset), 1000)
        lists: dict[int, list[_Entry]] = {}
        seen_document_atom = False
        for rec in self.children(root):
            if rec.type == 1001:
                self.size(rec, 40, exact=True)
                if seen_document_atom:
                    raise InvalidDocumentError('duplicate PPT document atom')
                seen_document_atom = True
                self.omit_title_fields = bool(self.data[rec.start + 37])
            elif rec.type == 4057 and rec.instance == 3:
                if self.default_hf is not None:
                    raise InvalidDocumentError('duplicate PPT default header/footer container')
                self.default_hf = rec
            elif rec.type == 4080 and rec.instance in (0, 1, 2):
                if rec.instance in lists:
                    raise InvalidDocumentError('duplicate PPT slide/notes list')
                lists[rec.instance] = self.entries(rec)
        self.masters = {e.slide_id: e for e in lists.get(1, [])}
        notes = {e.slide_id: e for e in lists.get(2, [])}
        document = Document(format='ppt')
        emitted_chars = 0
        for entry in lists.get(0, []):
            blocks, note_id, hidden, comments = self.sheet(entry, 1006)
            title = '\n'.join(text for kind, text in blocks if kind in (0, 6) and text)
            body = '\n'.join(text for kind, text in blocks if kind not in (0, 6) and text)
            note_text = ''
            if note_id:
                if note_id not in notes:
                    raise InvalidDocumentError('unresolved PPT notes ID')
                note_blocks, slide_id, _, _ = self.sheet(notes[note_id], 1008)
                if slide_id != entry.slide_id:
                    raise InvalidDocumentError('PPT notes backlink does not match slide ID')
                note_text = '\n'.join(text for _, text in note_blocks if text)
            parts = [part for part in [title, body, note_text] + [c.text for c in comments] if part]
            emitted_chars += sum(map(len, parts)) + max(0, len(parts) - 1)
            if document.slides:
                emitted_chars += 2  # Document.text inserts blank lines between slides.
            if emitted_chars > self.limits.max_text_chars:
                raise LimitExceededError('PPT output text limit exceeded')
            document.slides.append(Slide(len(document.slides) + 1, title, body, note_text, hidden, comments))
        document.warnings = self.warnings
        return document


def parse_ppt_bytes(data: bytes, limits: Limits) -> Document:
    """Extract active slides in presentation order, retaining empty slides.

    Malformed live structures fail closed. Inactive persist objects, old edits'
    text, unused masters and unreferenced notes are never scanned for fallback content.
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
