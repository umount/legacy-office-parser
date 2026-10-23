"""Bounded note PLC decoding; no output-tree anchors or display numbering.

MS-DOC 2.8.16/17/19/20. Ref PLCs contain N CPs, one ignored sentinel,
then N uint16 automatic/custom indicators (NOT body indexes). Text PLCs
contain N+1 range boundaries and one ignored sentinel. Body CPs are local
to the footnote/endnote story, reference CPs are local to the main story.

None means retain the legacy whole-story extraction without inventing notes.
With valid text ranges but absent/count-mismatched references, return bodies
with source_cp=None and reference_kind='unknown'. A malformed present PLC
raises InvalidDocumentError; budget exhaustion never falls back.

The caller MUST establish effective CFSpec/visibility and associate reference
CPs with stable paragraph/cell objects before publishing anchor_path. This
module deliberately cannot assert that a reference is visible or live.
"""
from collections.abc import Callable
from dataclasses import dataclass
import struct
from typing import Literal
import warnings

from .diagnostics import diagnostic_warning
from .errors import InvalidDocumentError, LimitExceededError
from .limits import Limits

PLCF_FND_REF = 2
PLCF_FND_TXT = 3
PLCF_END_REF = 46
PLCF_END_TXT = 47


@dataclass(frozen=True, slots=True)
class SourceNote:
    ordinal: int
    source_cp: int | None
    reference_kind: Literal['automatic', 'custom', 'unknown']
    body_start: int
    body_end: int


def decode_note_ranges(
    references: bytes | bytearray | memoryview,
    texts: bytes | bytearray | memoryview,
    main_count: int,
    story_utf16: bytes | bytearray | memoryview,
    limits: Limits,
    *,
    record: Callable[[int], None] | None = None,
    warn: Callable[[str], None] = warnings.warn,
) -> list[SourceNote] | None:
    """Decode one note type; body_start/body_end are half-open source CPs.

    Pass the declared story slice from _Doc.text, not a normalized string.
    A missing text PLC or unexplained prefix retains whole-story extraction.
    _Doc must separately finish tables/fields for each returned body, and keep
    ordinal order when references are hidden/deleted; never filter then zip.
    """
    if not 0 <= main_count < 0x7FFFFFFF or len(story_utf16) % 2:
        raise InvalidDocumentError('invalid DOC note story length')
    story_count = len(story_utf16) // 2
    if story_count >= 0x7FFFFFFF:
        raise InvalidDocumentError('invalid DOC note story length')
    if main_count + story_count > limits.max_text_chars:
        raise LimitExceededError('DOC note source text limit exceeded')
    if max(len(references), len(texts)) > limits.max_stream_bytes:
        raise LimitExceededError('DOC note stream limit exceeded')
    ref_count = 0
    if references:
        if len(references) < 4 or (len(references) - 4) % 6:
            raise InvalidDocumentError('invalid DOC note reference PLC size')
        ref_count = (len(references) - 4) // 6
    if texts and (len(texts) < 8 or len(texts) % 4):
        raise InvalidDocumentError('invalid DOC note text PLC size')
    body_count = len(texts) // 4 - 2 if texts else 0
    # Charge both PLC arrays, including sentinels, before constructing lists.
    count = (ref_count + 1 if references else 0) + (body_count + 2 if texts else 0)
    if count > limits.max_records:
        raise LimitExceededError('DOC note record limit exceeded')
    if record is not None:
        record(count)
    if (not story_count and not ref_count and len(texts) == 8
            and struct.unpack_from('<I', texts)[0] == 0):
        warn(diagnostic_warning('doc_empty_note_plc_ignored',
                                'Empty note body PLC for an absent story ignored; '
                                'no note relationships inferred.'))
        return []
    refs = []
    previous = -1
    for index in range(ref_count):
        cp = struct.unpack_from('<I', references, index * 4)[0]
        if not previous < cp < main_count:
            raise InvalidDocumentError('invalid DOC note reference CP order or range')
        flag = struct.unpack_from('<H', references, (ref_count + 1) * 4 + index * 2)[0]
        refs.append((cp, 'automatic' if flag else 'custom'))
        previous = cp
    if not texts:
        if story_count or refs:
            warn(diagnostic_warning('doc_note_text_plc_is_absent_the_whole_story_is', 'Note text PLC is absent; the whole story is retained without note relationships.'))
            return None
        return []
    boundaries = []
    previous = -1
    for index in range(body_count + 1):
        cp = struct.unpack_from('<I', texts, index * 4)[0]
        if not previous < cp < story_count:
            raise InvalidDocumentError('invalid DOC note text CP order or range')
        boundaries.append(cp)
        previous = cp
    if boundaries[-1] != story_count - 1:
        raise InvalidDocumentError('DOC note text PLC does not end at the reserved final CP')
    for end in boundaries[1:]:
        if bytes(story_utf16[(end - 1) * 2:end * 2]) != b'\r\0':
            raise InvalidDocumentError('DOC note body has no final paragraph mark')
    if boundaries[0] != 0:
        warn(diagnostic_warning('doc_note_text_plc_leaves_an_unassigned_prefix_the_whole', 'Note text PLC leaves an unassigned prefix; the whole story is retained without note relationships.'))
        return None
    linked = bool(references) and ref_count == body_count
    if not linked and body_count:
        warn(diagnostic_warning('doc_note_reference_plc_is_absent_or_its_count_differs', 'Note reference PLC is absent or its count differs from the bodies; note bodies are unlinked.'))
    if refs and not body_count:
        warn(diagnostic_warning('doc_note_references_have_no_corresponding_bodies_no_note_relationships', 'Note references have no corresponding bodies; no note relationships are emitted.'))
    return [SourceNote(i + 1, refs[i][0] if linked else None,
                       refs[i][1] if linked else 'unknown', begin, end)
            for i, (begin, end) in enumerate(zip(boundaries, boundaries[1:]))]
