"""Bounded source-slot identities for MS-DOC 2.3.3 and 2.8.22.

No inheritance resolution, page selection, or pooled-text changes happen here.
CPs address the unnormalized UTF-16 header subdocument, not Unicode scalars.
"""
from collections.abc import Callable
from dataclasses import dataclass
import struct
import warnings

from .diagnostics import diagnostic_warning
from .errors import InvalidDocumentError, LimitExceededError
from .limits import Limits


@dataclass(frozen=True, slots=True)
class SourceHeader:
    start: int
    end: int
    section: int | None
    kind: str
    variant: str
    ordinal: int


def _charge(count, limits, record):
    if count > limits.max_records:
        raise LimitExceededError('DOC header record limit exceeded')
    if record is not None:
        record(count)


def decode_section_count(plc, main_count: int, limits: Limits, *, record=None) -> int | None:
    """Validate PlcfSed structural CPs and return its section count.

    Missing PLC returns None. Caller still validates section-break characters
    and SEPX. The terminal CP can extend beyond the main story (MS-DOC 2.8.26).
    A zero-section PLC is accepted only for an empty synthetic main story.
    """
    if not isinstance(main_count, int) or isinstance(main_count, bool) or not 0 <= main_count < 0x7fffffff:
        raise InvalidDocumentError('invalid DOC main story length')
    if len(plc) > limits.max_stream_bytes or main_count > limits.max_text_chars:
        raise LimitExceededError('DOC section source limit exceeded')
    if not plc:
        return None
    if len(plc) < 4 or (len(plc) - 4) % 16:
        raise InvalidDocumentError('invalid DOC section PLC size')
    count = (len(plc) - 4) // 16
    _charge(2 * count + 1, limits, record)  # N SEDs and N+1 CPs
    previous = -1
    for index in range(count + 1):
        cp = struct.unpack_from('<I', plc, index * 4)[0]
        if not previous < cp < 0x7fffffff or (index == 0 and cp != 0):
            raise InvalidDocumentError('invalid DOC section CP order or range')
        if 0 < index < count and cp >= main_count:
            raise InvalidDocumentError('DOC section begins outside the main story')
        previous = cp
    if previous < main_count:
        raise InvalidDocumentError('DOC section PLC ends before the main story')
    return count


def decode_header_ranges(
    plc: bytes | bytearray | memoryview,
    story_bytes: bytes | bytearray | memoryview,
    limits: Limits,
    section_count: int | None = None,
    *,
    record: Callable[[int], None] | None = None,
    warn: Callable[[str], None] = warnings.warn,
) -> list[SourceHeader] | None:
    """Return every source slot, including empty slots, or None for fallback.

    section_count must come from a validated PlcfSed, e.g. decode_section_count
    or the caller's existing section validation. Missing evidence produces a
    coded warning, never invented section metadata. An empty header story with
    aligned all-zero defined CPs is ignored with a diagnostic, without inferring
    slots. Other malformed PLCs raise even when section_count is absent.
    record charges all CP entries
    before iteration/allocation; pass the caller's aggregate budget callback.

    Nonempty slots lose exactly one verified guard CR in their returned range.
    Header/footer contents must also end in CR; separators need not. The final
    PLC CP is undefined and ignored, and the final story CP is outside slots.
    Caller retains the original story bytes for legacy pooled projection.
    """
    if len(story_bytes) % 2 or len(story_bytes) // 2 >= 0x7fffffff:
        raise InvalidDocumentError('invalid DOC header story length')
    story_count = len(story_bytes) // 2
    # Decoded UTF-16 can exceed its compressed on-disk stream size.
    if len(plc) > limits.max_stream_bytes or story_count > limits.max_text_chars:
        raise LimitExceededError('DOC header source limit exceeded')
    if section_count is not None and (
        not isinstance(section_count, int) or isinstance(section_count, bool) or section_count < 0
    ):
        raise InvalidDocumentError('invalid DOC section count')
    if not plc:
        if not story_count:
            return []
        warn(diagnostic_warning('doc_header_plc_missing',
                                'Header PLC is absent; retain the whole story without source identities.'))
        return None
    if len(plc) < 8 or len(plc) % 4:
        raise InvalidDocumentError('invalid DOC header PLC size')
    cp_count = len(plc) // 4
    _charge(cp_count, limits, record)
    # Some producers retain a degenerate PLC despite ccpHdd == 0. There is
    # no source text or identity to recover. Check all defined CPs without
    # allocating ranges; the terminal CP remains undefined (MS-DOC 2.8.22).
    if not story_count and all(struct.unpack_from('<I', plc, i * 4)[0] == 0
                               for i in range(cp_count - 1)):
        warn(diagnostic_warning('doc_empty_header_plc_ignored',
                                'Degenerate header PLC for an empty story ignored; '
                                'no header identities inferred.'))
        return []
    slots = cp_count - 2
    if slots < 6 or (slots - 6) % 6:
        raise InvalidDocumentError('invalid DOC header slot count')
    if section_count is not None and slots != 6 + 6 * section_count:
        raise InvalidDocumentError('DOC header slots disagree with section count')
    # Never decode the final undefined CP, including for monotonicity checks.
    boundaries = []
    previous = -1
    for index in range(slots + 1):
        cp = struct.unpack_from('<I', plc, index * 4)[0]
        if not previous <= cp < story_count or (index == 0 and cp != 0):
            raise InvalidDocumentError('invalid DOC header CP order or range')
        boundaries.append(cp)
        previous = cp
    if boundaries[-1] != story_count - 1:
        raise InvalidDocumentError('DOC header PLC does not end at the reserved final CP')
    for index, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
        if start == end:
            continue
        if bytes(story_bytes[2 * (end - 1):2 * end]) != b'\r\0':
            raise InvalidDocumentError('DOC header slot has no guard paragraph mark')
        if index >= 6 and (end - start < 2 or bytes(story_bytes[2 * (end - 2):2 * (end - 1)]) != b'\r\0'):
            raise InvalidDocumentError('DOC header/footer contents have no final paragraph mark')
    if section_count is None:
        warn(diagnostic_warning('doc_header_section_count_missing',
                                'Validated section count is absent; retain the whole header story without source identities.'))
        return None
    result = []
    header_types = (('header', 'even'), ('header', 'odd'), ('footer', 'even'),
                    ('footer', 'odd'), ('header', 'first'), ('footer', 'first'))
    note_variants = ('separator', 'continuation_separator', 'continuation_notice')
    for index, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
        if index < 6:
            section = None
            kind = 'footnote_separator' if index < 3 else 'endnote_separator'
            variant = note_variants[index % 3]
        else:
            section = (index - 6) // 6 + 1
            kind, variant = header_types[(index - 6) % 6]
        result.append(SourceHeader(start, end - 1 if end > start else end,
                                   section, kind, variant, index + 1))
    return result
