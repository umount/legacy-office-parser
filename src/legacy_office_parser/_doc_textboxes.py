"""Live textbox CP ranges, shared by main and header textbox subdocuments.

MS-DOC 2.8.23 (PlcfHdrtxbxTxt), 2.8.32 (PlcftxbxTxt), 2.9.106
(FTXBXS). FIB pair indexes are 56 and 58, respectively. Both PLCs use
relative CPs and 22-byte records; the last record is always reserved.

Missing PLC policy: retain the full nonempty subdocument with an explicit
warning that active ranges cannot be verified. A present malformed PLC raises
InvalidDocumentError; limits raise LimitExceededError, without fallback.

This helper validates ranges, not drawing associations or text bytes. The
caller can check the required final CR of each non-final range against its
text buffer. Walk each returned range separately and reset field state at
its end, so a malformed field cannot consume the next textbox.
"""
from collections.abc import Callable
import struct
import warnings

from .diagnostics import diagnostic_warning
from .errors import InvalidDocumentError, LimitExceededError
from .limits import Limits

PLCF_TXBX_TXT = 56
PLCF_HDR_TXBX_TXT = 58


def live_textbox_ranges(
    plc: bytes | bytearray | memoryview,
    story_count: int,
    limits: Limits,
    *,
    record: Callable[[int], None] | None = None,
    warn: Callable[[str], None] = warnings.warn,
) -> list[tuple[int, int]]:
    """Return live half-open CP ranges relative to the selected subdocument.

    Pass ``record=budget.record`` to charge all FTXBXS records (including
    reserved records) against the document-wide budget before iteration.
    Without a callback, max_records still bounds this individual PLC.
    The caller remains responsible for aggregate text/stream limits. Pass
    ``warn=self.warn`` to collect absent-PLC warnings in the output document;
    otherwise they are emitted as Python UserWarnings.
    """
    if story_count < 0 or story_count > 0x7FFFFFFF:
        raise InvalidDocumentError('invalid DOC textbox story length')
    if story_count > limits.max_text_chars:
        raise LimitExceededError('DOC textbox text limit exceeded')
    if len(plc) > limits.max_stream_bytes:
        raise LimitExceededError('DOC textbox PLC size limit exceeded')
    if not plc:
        if story_count:
            warn(diagnostic_warning('doc_textbox_plc_is_absent_active_ranges_cannot_be_verified', 'Textbox PLC is absent; active ranges cannot be verified. '
                 'The full textbox story is retained and may include reserved text.'))
            return [(0, story_count)]
        return []
    if len(plc) < 4 or (len(plc) - 4) % 26:
        raise InvalidDocumentError('invalid DOC textbox PLC size')
    count = (len(plc) - 4) // 26
    if not count:
        raise InvalidDocumentError('DOC textbox PLC has no reserved record')
    if count > limits.max_records:
        raise LimitExceededError('DOC textbox record limit exceeded')
    if record is not None:
        record(count)

    data_at = (count + 1) * 4
    start = struct.unpack_from('<I', plc, 0)[0]
    if start > story_count:
        raise InvalidDocumentError('DOC textbox CP outside its story')
    ranges = []
    for i in range(count):
        end = struct.unpack_from('<I', plc, (i + 1) * 4)[0]
        # MS-DOC 2.8.23/2.8.32: the last range is ignored. Its
        # terminal CP is not a readable story endpoint (writers may use a
        # document-wide sentinel). Never return or slice that reserved span.
        # Keep CP validity/order, and bound every nonfinal endpoint as before.
        if end >= 0x7FFFFFFF:
            raise InvalidDocumentError('invalid DOC textbox CP')
        if i != count - 1 and end > story_count:
            raise InvalidDocumentError('DOC textbox CP outside its story')
        if end <= start:
            raise InvalidDocumentError('DOC textbox CPs are not strictly increasing')
        # The final FTXBXS is reserved regardless of its flag, lid or span.
        if i != count - 1:
            reusable = struct.unpack_from('<H', plc, data_at + i * 22 + 8)[0]
            if reusable:
                if not reusable & 1:
                    raise InvalidDocumentError('invalid DOC textbox reusable flag')
                if end - start != 1:
                    raise InvalidDocumentError('invalid DOC reusable textbox range')
            else:
                if end - start <= 1:
                    raise InvalidDocumentError('invalid DOC live textbox range')
                ranges.append((start, end))
        start = end
    return ranges
