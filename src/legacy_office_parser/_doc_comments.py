"""Bounded MS-DOC annotation ownership; no text search or whole-story fallback.

Reference/body ordinals are paired before visibility filtering. Bookmark tags
join metadata to starts, whose ibkl selects an exclusive limit. Marker CFSpec,
body paragraph/table validity, and ordinary selection validity belong to _Doc.
The source table index proves exact spans without changing bookmark endpoints.
"""
from bisect import bisect_right
from dataclasses import dataclass
import struct
import warnings

from ._doc_fields import FieldSelections
from .diagnostics import diagnostic_warning
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
    # Decoded UTF-16 uses the aggregate CP budget above, not the input-byte cap.
    if any(len(p) > limits.max_stream_bytes for p in parts.values()):
        raise LimitExceededError('DOC comment stream limit exceeded')
    refs, texts = parts.get(4, b''), parts.get(5, b'')
    if refs and (len(refs) < 4 or (len(refs) - 4) % 34):
        invalid('reference PLC size is invalid')
    if texts and (len(texts) < 8 or len(texts) % 4):
        invalid('body PLC size is invalid')
    n = (len(refs) - 4) // 34 if refs else 0
    body_count = len(texts) // 4 - 2 if texts else 0
    charge((2 * n + 1 if refs else 0) + (body_count + 2 if texts else 0))
    empty_body = not story_count and not n and len(texts) == 8 and u32(texts) == 0
    if empty_body:
        warn(diagnostic_warning('doc_empty_comment_plc_ignored',
                                'Empty comment body PLC for an absent story ignored; '
                                'no comment relationships inferred.'))
    boundaries = []
    previous = -1
    for i in range(body_count + 1 if texts and not empty_body else 0):
        cp = u32(texts, i * 4)
        if not previous < cp < story_count:
            invalid('body CP order or bounds are invalid')
        boundaries.append(cp)
        previous = cp
    if texts and not empty_body and boundaries[-1] != story_count - 1:
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
            warn(diagnostic_warning('doc_comment_ink_is_not_rendered_proven_textual_bodies', 'DOC comment ink is not rendered; proven textual bodies retain stored order.'))

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
            warn(diagnostic_warning('doc_comment_authors_are_absent_initials_are_retained_without', 'DOC comment authors are absent; initials are retained without inferring names.'))
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
            warn(diagnostic_warning('doc_comment_selection_bookmark_is_unresolved_reference_ownership_is', 'DOC comment selection bookmark is unresolved; reference ownership is retained.'))
        charge()
        descriptors.append((i + 1, cp, author, initials, begin, end))
    if empty_body:
        return []
    if refs and texts and n != body_count:
        invalid('reference and body counts differ')
    if not refs or not texts:
        if story_count or refs or texts or extra:
            warn(diagnostic_warning('doc_comment_ownership_plc_is_absent_unproven_comment_story', 'DOC comment ownership PLC is absent; unproven comment story text is omitted.'))
        return []
    if boundaries[0] != 0:
        warn(diagnostic_warning('doc_comment_story_has_an_unassigned_prefix_only_plc', 'DOC comment story has an unassigned prefix; only PLC-owned bodies are considered.'))
    charge(n)
    return [SourceComment(ordinal, cp, boundaries[i], boundaries[i + 1], author,
                          initials, begin, end,
                          *(reply_metadata[i] if extra else (None, None)))
            for i, (ordinal, cp, author, initials, begin, end) in enumerate(descriptors)]


@dataclass(slots=True)
class _SelectionTable:
    begin: int
    end: int
    cell_starts: list[int]
    cell_marks: list[int]
    row_starts: set[int]
    row_marks: list[int]

    def allows(self, begin, end):
        # MS-DOC 2.8.10 rule 1 (annotation bookmarks have fCol=0).
        # Limits are exclusive CPs; the unusual -1/-2 offsets are specified
        # by the format, not rounded to cells or projected output rows.
        outside_end = not self.begin < end < self.end
        cell = bisect_right(self.cell_marks, begin - 1)
        if cell < len(self.cell_marks) and self.cell_marks[cell] < end:
            if begin > self.cell_starts[cell]:
                return False
            i = bisect_right(self.cell_marks, end + 1) - 1
            j = bisect_right(self.row_marks, end - 1) - 1
            if not (outside_end or (i >= 0 and self.cell_marks[i] == end + 1)
                    or (j >= 0 and self.row_marks[j] == end - 1)):
                return False
        row = bisect_right(self.row_marks, begin - 1)
        if row < len(self.row_marks) and self.row_marks[row] < end:
            if self.begin <= begin < self.end and begin not in self.row_starts:
                return False
            i = bisect_right(self.row_marks, end + 2) - 1
            j = bisect_right(self.row_marks, end - 1) - 1
            if not (outside_end or (i >= 0 and self.row_marks[i] == end + 2)
                    or (j >= 0 and self.row_marks[j] == end - 1)):
                return False
        return True


@dataclass(slots=True)
class BookmarkSelections:
    """Source bookmark index, including partial and arbitrarily nested rows."""
    starts: list[int]
    ends: list[int]
    unsafe: list[int]
    tables: list[tuple[list[int], list[_SelectionTable]]]
    text: memoryview
    fields: FieldSelections | None = None

    def contains(self, begin, end):
        if not 0 <= begin < end <= len(self.text) // 2:
            return False
        if self.fields is not None and not self.fields.contains(begin, end):
            return False
        i = bisect_right(self.starts, begin) - 1
        j = bisect_right(self.starts, end - 1) - 1
        if not (0 <= i <= j and end <= self.ends[j]
                and self.unsafe[j + 1] == self.unsafe[i]):
            return False
        if (0xdc00 <= struct.unpack_from('<H', self.text, begin * 2)[0] <= 0xdfff
                or 0xd800 <= struct.unpack_from('<H', self.text, (end - 1) * 2)[0] <= 0xdbff):
            return False
        # Fully enclosed tables satisfy both outside-table alternatives.
        # Only tables containing an endpoint require examination. At each
        # depth the intervals are disjoint, so queries are O(depth * log N).
        for starts, tables in self.tables:
            first = bisect_right(starts, begin) - 1
            last = bisect_right(starts, end - 1) - 1
            for index in (first,) if first == last else (first, last):
                if index >= 0:
                    table = tables[index]
                    if begin < table.end and end > table.begin and not table.allows(begin, end):
                        return False
        return True


def comment_selection_index(text, paragraphs, section_ends, paragraph_known,
                            limits: Limits, *, record=None, fields=None):
    """Validate source structure once, then test fCol=0 bookmark boundaries.

    All depths and ordinary/section paragraphs use the same source rules. Unknown or
    malformed tables invalidate their own source span, never unrelated text.
    """
    cost = 12 * len(paragraphs) + 1
    if cost > limits.max_records:
        raise LimitExceededError('DOC comment selection record limit exceeded')
    if record is not None:
        record(cost)
    if len(text) // 2 > limits.max_text_chars:
        raise LimitExceededError('DOC comment selection source limit exceeded')
    view = memoryview(text)
    empty = BookmarkSelections([], [], [0], [], view)
    if len(text) % 2:
        return empty
    count = len(text) // 2
    starts, ends, safe = [], [], []
    levels, stack, invalid = [], [], []
    previous_end = cells = 0
    delimiters = []

    def charge(n):
        nonlocal cost
        cost += n
        if cost > limits.max_records:
            raise LimitExceededError('DOC comment selection record limit exceeded')
        if record is not None:
            record(n)

    def close():
        frame = stack.pop()
        if frame['row_bad'] or frame['cells'] or frame['open'] or not frame['table'].row_marks:
            frame['bad'] = True
        if frame['bad']:
            if stack:
                stack[-1]['row_bad'] = True
            else:
                invalid.append((frame['first'], len(starts)))

    for begin, end, mark, mark_cp, props, _, known in paragraphs:
        if not (begin == previous_end and begin <= end == mark_cp < count):
            return empty
        if struct.unpack_from('<H', text, end * 2)[0] != mark:
            return empty
        previous_end = end + 1
        depth = props.depth or (1 if props.in_table else 0)
        if depth < 0:
            return empty
        if depth > limits.max_depth:
            raise LimitExceededError('DOC comment selection depth limit exceeded')
        while len(stack) > depth:
            close()
        ordinary = known and paragraph_known(mark_cp)
        for cp in range(begin, end):
            unit = struct.unpack_from('<H', text, cp * 2)[0]
            if fields is None and unit in (19, 20, 21):
                charge(2)
                delimiters.append((cp, unit))
            ordinary &= unit >= 32 or unit in (5, 9, 19, 20, 21)
        starts.append(begin)
        ends.append(end + 1)
        safe.append(bool(ordinary))
        if not depth:
            safe[-1] &= (not (props.row_end or props.inner_cell or props.inner_ttp)
                         and ((mark == 13 and mark_cp not in section_ends)
                              or (mark == 12 and mark_cp in section_ends)))
            continue
        # A cell may start with a nested table. Its later cell/TTP marks
        # prove the enclosing scope; no leading parent paragraph is required.
        extra = max(0, depth - len(stack) - 1) * 4
        cost += extra
        if cost > limits.max_records:
            raise LimitExceededError('DOC comment selection record limit exceeded')
        if extra and record is not None:
            record(extra)
        while depth > len(stack):
            if stack:
                stack[-1]['open'] = True
            table = _SelectionTable(begin, begin, [], [], set(), [])
            level = len(stack)
            if len(levels) <= level:
                levels.append([])
            levels[level].append(table)
            stack.append(dict(table=table, first=len(starts)-1, row=begin, cell=begin,
                              cells=0, open=False, bad=False, row_bad=False,
                              row_first=len(starts)-1, props=None, frame=None,
                              first_frame=None))
        frame = stack[-1]
        frame['row_bad'] |= not ordinary or mark_cp in section_ends
        is_row = props.row_end if depth == 1 else props.inner_ttp
        is_cell = mark == 7 if depth == 1 else props.inner_cell
        coherent = (mark in (7, 13) and props.in_table
                    and not (depth == 1 and (props.inner_cell or props.inner_ttp))
                    and not (depth > 1 and (mark != 13 or props.row_end)))
        frame['row_bad'] |= not coherent
        if frame['first_frame'] is None and not is_row and not frame['cells']:
            frame['first_frame'] = getattr(props, 'frame', None)
        if is_row:
            if (begin != end or frame['open'] or not 1 <= frame['cells'] <= 63
                    or len(props.flags) != frame['cells']
                    or len(props.edges) != frame['cells'] + 1
                    or any(a > b for a, b in zip(props.edges, props.edges[1:]))
                    or (depth == 1 and mark != 7) or (depth > 1 and is_cell)):
                frame['row_bad'] = True
            # Adjacent rows with different source identities are separate
            # tables even if their nesting depth and output grid agree.
            previous = frame['props']
            if previous is not None and hasattr(props, 'identity'):
                from ._doc_conditions import row_boundary
                if row_boundary(previous.identity, previous.bidi or previous.bidi90,
                                frame['frame'], props, frame['first_frame']):
                    if frame['bad']:
                        invalid.append((frame['first'], frame['row_first']))
                    frame['first'], frame['bad'] = frame['row_first'], False
                    old = frame['table']
                    n = len(old.cell_marks) - frame['cells']
                    table = _SelectionTable(frame['row'], frame['row'],
                                            old.cell_starts[n:], old.cell_marks[n:], set(), [])
                    del old.cell_starts[n:]
                    del old.cell_marks[n:]
                    levels[depth - 1].append(table)
                    frame['table'] = table
            table = frame['table']
            table.row_starts.add(frame['row'])
            table.row_marks.append(end)
            table.end = end + 1
            frame['bad'] |= frame['row_bad']
            frame.update(row=end+1, cell=end+1, cells=0, open=False, row_bad=False,
                         row_first=len(starts), props=props, frame=frame['first_frame'], first_frame=None)
        elif is_cell:
            cells += 1
            if cells > limits.max_cells:
                raise LimitExceededError('DOC comment selection cell limit exceeded')
            frame['table'].cell_starts.append(frame['cell'])
            frame['table'].cell_marks.append(end)
            frame.update(cell=end+1, cells=frame['cells']+1, open=False)
            frame['row_bad'] |= frame['cells'] > 63
        else:
            frame['open'] = True
    while stack:
        close()
    if fields is None and delimiters:
        from ._doc_fields import field_selection_index
        fields = field_selection_index(delimiters, b'', count, limits, record=charge)
    # Difference counts handle overlapping invalid enclosing/inner scopes
    # without walking their paragraphs repeatedly.
    invalid_delta = [0] * (len(safe) + 1)
    for begin, end in invalid:
        invalid_delta[begin] += 1
        invalid_delta[end] -= 1
    unsafe = [0]
    active = 0
    for i, valid in enumerate(safe):
        active += invalid_delta[i]
        unsafe.append(unsafe[-1] + (not valid or active > 0))
    return BookmarkSelections(starts, ends, unsafe,
                              [([t.begin for t in level], level) for level in levels], view, fields)
