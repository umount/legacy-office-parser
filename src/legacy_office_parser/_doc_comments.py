"""Bounded MS-DOC annotation ownership; no text search or whole-story fallback.

Reference/body ordinals are paired before visibility filtering. Bookmark tags
join metadata to starts, whose ibkl selects an exclusive limit. Marker CFSpec,
body paragraph/table validity, and ordinary selection validity belong to _Doc.
"""
from dataclasses import dataclass
import struct
import warnings

from .errors import InvalidDocumentError, LimitExceededError
from .limits import Limits


@dataclass(frozen=True, slots=True)
class SourceComment:
    ordinal: int
    source_cp: int
    body_start: int
    body_end: int
    author: str | None
    initials: str
    selection_start: int | None
    selection_end: int | None
    reply_depth: int | None = None
    parent_ordinal: int | None = None


def decode_comments(parts, main_utf16, story_utf16, limits: Limits, *,
                    record=None, warn=warnings.warn, source_text_count=None):
    """Return only PLC-owned bodies; missing ownership returns an empty list.

    parts maps FIB indices 4/5/36/37/42/43/112 to already bounded stream slices.
    The main and comment slices are unnormalized UTF-16, with their own CP zero.
    Present structures are checked even if an ownership PLC is absent.
    """
    used = 0

    def charge(n=1):
        nonlocal used
        used += n
        if used > limits.max_records:
            raise LimitExceededError('DOC comment record limit exceeded')
        if record is not None:
            record(n)

    def invalid(message):
        raise InvalidDocumentError('DOC comment ' + message)

    def u16(data, offset=0):
        return struct.unpack_from('<H', data, offset)[0]

    def u32(data, offset=0):
        return struct.unpack_from('<I', data, offset)[0]

    def metadata_text(units):
        nonlocal source_units
        source_units += units
        if source_units > limits.max_text_chars:
            raise LimitExceededError('DOC comment source metadata text limit exceeded')

    def unicode(data):
        try:
            return bytes(data).decode('utf-16le')
        except UnicodeDecodeError as exc:
            raise InvalidDocumentError('invalid DOC comment metadata UTF-16') from exc

    if len(main_utf16) % 2 or len(story_utf16) % 2:
        invalid('story has odd UTF-16 length')
    main_count, story_count = len(main_utf16) // 2, len(story_utf16) // 2
    if main_count >= 0x7fffffff or story_count >= 0x7fffffff:
        invalid('story length is invalid')
    source_units = main_count + story_count if source_text_count is None else source_text_count
    if source_units < main_count + story_count:
        invalid('aggregate source count is smaller than its stories')
    if source_units > limits.max_text_chars:
        raise LimitExceededError('DOC comment source text limit exceeded')
    if any(len(p) > limits.max_stream_bytes for p in
           (*parts.values(), main_utf16, story_utf16)):
        raise LimitExceededError('DOC comment stream limit exceeded')
    refs, texts = parts.get(4, b''), parts.get(5, b'')
    if refs and (len(refs) < 4 or (len(refs) - 4) % 34):
        invalid('reference PLC size is invalid')
    if texts and (len(texts) < 8 or len(texts) % 4):
        invalid('body PLC size is invalid')
    n = (len(refs) - 4) // 34 if refs else 0
    body_count = len(texts) // 4 - 2 if texts else 0
    charge((2 * n + 1 if refs else 0) + (body_count + 2 if texts else 0))
    boundaries = []
    previous = -1
    for i in range(body_count + 1 if texts else 0):
        cp = u32(texts, i * 4)
        if not previous < cp < story_count:
            invalid('body CP order or bounds are invalid')
        boundaries.append(cp)
        previous = cp
    if texts and boundaries[-1] != story_count - 1:
        invalid('body PLC does not end at reserved final CP')
    for begin, end in zip(boundaries, boundaries[1:]):
        if u16(story_utf16, begin * 2) != 5 or u16(story_utf16, (end - 1) * 2) != 13:
            invalid('body requires initial U+0005 and final CR')

    owners_raw = parts.get(36, b'')
    owners, owner_set = [], set()
    pos = 0
    while pos < len(owners_raw):
        if pos + 2 > len(owners_raw):
            invalid('author length is truncated')
        size = u16(owners_raw, pos)
        if size >= 56 or pos + 2 + size * 2 > len(owners_raw):
            invalid('author string length is invalid')
        if len(owners) >= 0x7fff:
            invalid('author count is invalid')
        charge()
        metadata_text(size)
        value = unicode(owners_raw[pos + 2:pos + 2 + size * 2])
        if value in owner_set:
            invalid('author names are not unique')
        owner_set.add(value)
        owners.append(value)
        pos += 2 + size * 2

    meta, starts, ends = (parts.get(i, b'') for i in (37, 42, 43))
    tags = {}
    m = None
    if meta:
        if len(meta) < 6 or u16(meta) != 0xffff or u16(meta, 4) != 10:
            invalid('bookmark metadata header is invalid')
        m = u16(meta, 2)
        if m > 0x3ffb or len(meta) != 6 + 12 * m:
            invalid('bookmark metadata size is invalid')
        charge(m)
        for i in range(m):
            at = 6 + i * 12
            if u16(meta, at) or u16(meta, at + 2) != 0x100:
                invalid('bookmark metadata entry is invalid')
            tag = u32(meta, at + 4)
            if tag in tags:
                invalid('bookmark tag is duplicated')
            tags[tag] = i
    start_cps, end_cps, indexes = [], [], []
    for raw, stride, dest in ((starts, 8, start_cps), (ends, 4, end_cps)):
        if not raw:
            continue
        if len(raw) < 4 or (len(raw) - 4) % stride:
            invalid('bookmark PLC size is invalid')
        count = (len(raw) - 4) // stride
        if count > 0x3ffb:
            invalid('bookmark count is invalid')
        charge(count + 1)
        previous = -1
        for i in range(count):
            cp = u32(raw, i * 4)
            if not previous <= cp <= main_count:
                invalid('bookmark CP order or bounds are invalid')
            dest.append(cp)
            previous = cp
        if u32(raw, count * 4) != main_count + 1:
            invalid('bookmark sentinel is invalid')
        if stride == 8:
            charge(count)
            seen = set()
            for i in range(count):
                at = (count + 1) * 4 + i * 4
                index, flags = u16(raw, at), u16(raw, at + 2)
                if index >= count or index in seen or flags & 0x8000:
                    invalid('bookmark index or annotation fCol is invalid')
                indexes.append(index)
                seen.add(index)
    counts = ([m] if meta else []) + ([len(start_cps)] if starts else []) + ([len(end_cps)] if ends else [])
    if counts and any(count != counts[0] for count in counts):
        invalid('bookmark array counts differ')
    if starts and ends:
        for begin, index in zip(start_cps, indexes):
            if begin > end_cps[index]:
                invalid('bookmark range is reversed')

    reply_metadata = []
    extra = parts.get(112, b'')
    if extra:
        if len(extra) % 18 or (refs and len(extra) != n * 18):
            invalid('extra record count is invalid')
        charge(len(extra) // 18)
        ancestors = []
        ink = False
        for i in range(len(extra) // 18):
            depth, parent, flags = struct.unpack_from('<IiI', extra, i * 18 + 6)
            if depth > limits.max_depth:
                raise LimitExceededError('DOC comment reply depth limit exceeded')
            if depth > len(ancestors) or (depth == 0 and parent != 0):
                invalid('reply tree depth or parent is invalid')
            if depth and (not parent or i + parent != ancestors[depth - 1]):
                invalid('reply parent does not match preorder ancestry')
            del ancestors[depth:]
            ancestors.append(i)
            reply_metadata.append((depth, i + parent + 1 if depth else None))
            ink |= bool(flags & 2)
        if ink:
            warn('DOC comment ink is not rendered; proven textual bodies retain stored order.')

    descriptors = []
    previous = -1
    for i in range(n):
        cp = u32(refs, i * 4)
        if not previous < cp < main_count or u16(main_utf16, cp * 2) != 5:
            invalid('reference CP or U+0005 marker is invalid')
        previous = cp
        at = (n + 1) * 4 + i * 30
        length = u16(refs, at)
        if length > 9:
            invalid('initials length is invalid')
        metadata_text(length)
        initials = unicode(refs[at + 2:at + 2 + length * 2])
        owner = u16(refs, at + 20)
        if owners_raw and owner >= len(owners):
            invalid('author index is invalid')
        author = owners[owner] if owners_raw else None
        if not owners_raw:
            warn('DOC comment authors are absent; initials are retained without inferring names.')
        tag = u32(refs, at + 26)
        begin = end = None
        if tag == 0xffffffff:
            begin = end = cp
        elif meta and starts and ends and tag in tags:
            index = tags[tag]
            begin, end = start_cps[index], end_cps[indexes[index]]
            if begin == end:
                invalid('non-point comment bookmark has an empty range')
        else:
            warn('DOC comment selection bookmark is unresolved; reference ownership is retained.')
        charge()
        descriptors.append((i + 1, cp, author, initials, begin, end))
    if refs and texts and n != body_count:
        invalid('reference and body counts differ')
    if not refs or not texts:
        if story_count or refs or texts or extra:
            warn('DOC comment ownership PLC is absent; unproven comment story text is omitted.')
        return []
    if boundaries[0] != 0:
        warn('DOC comment story has an unassigned prefix; only PLC-owned bodies are considered.')
    charge(n)
    return [SourceComment(ordinal, cp, boundaries[i], boundaries[i + 1], author,
                          initials, begin, end,
                          *(reply_metadata[i] if extra else (None, None)))
            for i, (ordinal, cp, author, initials, begin, end) in enumerate(descriptors)]
