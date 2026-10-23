"""Source-only MS-DOC Plcfld selection proof; never evaluates field codes."""
from bisect import bisect_left
from dataclasses import dataclass
import struct

from .errors import LimitExceededError


@dataclass(slots=True)
class FieldSelections:
    cps: list[int]
    size: int
    bounds: list[tuple[int, int]]

    def contains(self, begin, end):
        # A delimiter-free substring (including stored results) needs no field
        # closure proof. Every selected delimiter must own a complete field.
        left = bisect_left(self.cps, begin)
        right = bisect_left(self.cps, end)
        left += self.size
        right += self.size
        while left < right:
            if left & 1:
                low, high = self.bounds[left]
                if low < begin or high > end:
                    return False
                left += 1
            if right & 1:
                right -= 1
                low, high = self.bounds[right]
                if low < begin or high > end:
                    return False
            left //= 2
            right //= 2
        return True


def field_selection_index(delimiters, plc, count, limits, *, record=None, special=None):
    """Verify main-story Plcfld (FIB pair 16) against all source delimiters.

    Input delimiters are ordered (CP, code-unit) pairs, already charged by the
    source scanner; special(cp) must prove CFSpec=1 with known coverage.
    XE/TC/RD/TA/PRIVATE delimiters omitted from Plcfld are not inferred: a
    mismatch conservatively leaves ownership unverified. Invalid/missing PLC
    or unbalanced nesting leaves delimiter ownership unproven, without
    poisoning delimiter-free source ranges.
    """
    n = len(delimiters)
    cost = 8 * n + 1
    if cost > limits.max_records:
        raise LimitExceededError('DOC field selection record limit exceeded')
    if record is not None:
        record(cost)
    if len(plc) > limits.max_stream_bytes:
        raise LimitExceededError('DOC field selection stream limit exceeded')
    size = 1 << (n - 1).bit_length() if n else 1
    unknown = (-1, count + 1)
    neutral = (count + 1, -1)
    bounds = [neutral] * (2 * size)
    for i in range(n):
        bounds[size + i] = unknown
    # PLC has n+1 CPs followed by n two-byte FLD records. The last CP
    # is not a delimiter. FLD's second byte describes type/flags, not a CP.
    verified = (special is not None and len(plc) == 6 * n + 4
                and (not n or struct.unpack_from('<I', plc, 4 * n)[0] > delimiters[-1][0]))
    stack = []
    if verified:
        for i, (cp, kind) in enumerate(delimiters):
            if (not 0 <= cp < count or (i and cp <= delimiters[i - 1][0])
                    or struct.unpack_from('<I', plc, 4 * i)[0] != cp
                    or (plc[4 * (n + 1) + 2 * i] & 0x1f) != kind
                    or not special(cp)):
                verified = False
                break
            if kind == 19:
                if len(stack) >= limits.max_depth:
                    raise LimitExceededError('DOC field selection depth limit exceeded')
                stack.append([i, None])
            elif kind == 20:
                if not stack or stack[-1][1] is not None:
                    verified = False
                    break
                stack[-1][1] = i
            elif kind == 21:
                if not stack:
                    verified = False
                    break
                first, separator = stack.pop()
                owner = (delimiters[first][0], cp + 1)
                bounds[size + first] = bounds[size + i] = owner
                if separator is not None:
                    bounds[size + separator] = owner
            else:
                verified = False
                break
    if not verified or stack:
        for i in range(n):
            bounds[size + i] = unknown
    for i in range(size - 1, 0, -1):
        a, b = bounds[2 * i], bounds[2 * i + 1]
        bounds[i] = min(a[0], b[0]), max(a[1], b[1])
    return FieldSelections([cp for cp, _ in delimiters], size, bounds)
