"""Bounded MS-DOC STSH reader for extraction, not a formatting/layout engine."""
from dataclasses import replace

from ._doc_table import FrameIdentity, frame_change
from .errors import InvalidDocumentError, LimitExceededError, UnsupportedFormatError


# MS-DOC 2.9.336 UpxChpx: all ten explicitly forbidden SPRMs. Shared
# by paragraph, character and table styles; CCnf has a separate kind rule.
_UPX_CHPX_FORBIDDEN = frozenset((
    0x0818,  # CFSpecVanish
    0x4A30,  # CIstd
    0xCA31,  # CIstdPermute
    0x2A33,  # CPlain
    0xCA47,  # CMajority
    0xCA62,  # CDispFldRMark
    0x4867,  # CIdslRMarkDel
    0x2879,  # CLbcCRJ
    0x6887,  # CPbiIBullet
    0x4888,  # CPbiGrf
))


class Styles:
    def __init__(self, doc, span, u16):
        self.doc = doc
        self.styles = []
        self.cache = {}
        self.frame_overrides = {}
        self.frame_cache = {}
        data = doc.table_part(1)  # fcStshf, NOT the original stylesheet fcStshfOrig.
        self.present = bool(data)
        if not data:
            return
        size = u16(data)
        header = span(data, 2, size)
        if size < 18:
            raise InvalidDocumentError('short DOC stylesheet header')
        count, base_size = u16(header), u16(header, 2)
        if count > 0xFFE or base_size not in (10, 18):
            raise InvalidDocumentError('invalid DOC stylesheet header')
        doc.budget.record(count)
        pos = 2 + size
        for index in range(count):
            length = u16(data, pos)
            raw = span(data, pos + 2, length)
            pos += 2 + length
            if not length:
                self.styles.append(None)
                continue
            span(raw, 0, base_size)
            kind_base, cupx = u16(raw, 2), u16(raw, 4) & 15
            kind, base = kind_base & 15, kind_base >> 4
            if kind not in (1, 2, 3, 4):
                raise InvalidDocumentError('invalid DOC style kind')
            name_units = u16(raw, base_size)
            end_name = base_size + 2 + name_units * 2
            span(raw, base_size + 2, name_units * 2)
            if u16(raw, end_name):
                raise InvalidDocumentError('unterminated DOC style name')
            at = end_name + 2
            groups = []
            for _ in range(cupx):
                doc.budget.record()
                n = u16(raw, at)
                groups.append(span(raw, at + 2, n))
                at += 2 + n + (n & 1)
                span(raw, 0, at)
            if at != len(raw):
                raise InvalidDocumentError('unexpected DOC style trailing bytes')
            expected = {1: (2, 3), 2: (1, 2), 3: (3,), 4: (1,)}[kind]
            if cupx not in expected:
                raise InvalidDocumentError('invalid DOC style UPX count')
            hidden = ()
            frame = {}
            if kind in (1, 2, 3):
                if kind == 1:
                    if u16(groups[0]) != index:
                        raise InvalidDocumentError('DOC style PAPX index mismatch')
                    # These structural properties cannot be inherited (UpxPapx).
                    for op, arg in doc._sprms(groups[0][2:]):
                        if (op >> 10) & 7 != 1 or op in (
                                0x2416, 0x2417, 0x6649, 0x664A, 0x244B, 0x244C,
                                0x4600, 0xC601, 0x6646, 0x6645, 0x646B):
                            raise InvalidDocumentError('forbidden DOC paragraph style property')
                        change = frame_change(op, arg)
                        if change is not None:
                            frame[change[0]] = change[1]
                operations = []
                for op, arg in doc._sprms(groups[{1: 1, 2: 0, 3: 2}[kind]],
                                           allow_padding=kind != 3):
                    if kind == 3 and op == 0xCA85:
                        # The complete length-delimited operand is opaque here;
                        # never promote conditional CFVanish to an unconditional one.
                        if len(arg) < 3:
                            raise InvalidDocumentError('short DOC conditional character style operand')
                        doc.warn('Conditional table style character formatting is not evaluated.')
                        continue
                    if ((op >> 10) & 7 != 2 or op in _UPX_CHPX_FORBIDDEN
                            or op in (0x0800, 0x0801, 0x0802, 0x0855, 0x6A09,
                                      0xCA85)):
                        raise InvalidDocumentError('forbidden DOC character style property')
                    if op == 0x083C:
                        if arg[0] not in (0, 1, 128, 129):
                            raise InvalidDocumentError('invalid DOC CFVanish toggle')
                        operations.append(arg[0])

                hidden = tuple(operations)
            self.styles.append((kind, base, hidden))
            if frame:
                self.frame_overrides[index] = frame
        if pos != len(data):
            raise InvalidDocumentError('unexpected DOC stylesheet trailing bytes')

    def table_hidden(self, index=None):
        """Unconditional visibility only; None means no table style is applied.

        Normalize a TIstd selection as in MS-DOC 2.6.3, but validate the
        selected style's parent graph strictly. No outer-table inheritance.
        """
        if index is None:
            return False
        if (index < 0 or index >= len(self.styles) or self.styles[index] is None
                or self.styles[index][0] != 3):
            index = 11
        if (index >= len(self.styles) or self.styles[index] is None
                or self.styles[index][0] != 3):
            return False
        return self.hidden(index, 3)

    def frame(self, index):
        """Resolve paragraph frame inheritance, bounded by existing style limits."""
        if index in self.frame_cache:
            return self.frame_cache[index]
        # PIstd may temporarily name an invalid style before a later override.
        # Its specified effect is to restore default paragraph properties.
        if (index >= len(self.styles) or self.styles[index] is None
                or self.styles[index][0] != 1):
            return FrameIdentity()
        path, seen = [], set()
        current = index
        while current != 0xFFF:
            if current in seen:
                raise InvalidDocumentError('cyclic DOC style inheritance')
            if len(path) >= self.doc.limits.max_depth:
                raise LimitExceededError('DOC style inheritance depth limit exceeded')
            if current >= len(self.styles):
                raise InvalidDocumentError('DOC style reference is out of range')
            entry = self.styles[current]
            if entry is None:
                raise InvalidDocumentError('DOC style references an empty style')
            if entry[0] != 1:
                raise InvalidDocumentError('DOC style kind mismatch')
            self.doc.budget.record()
            seen.add(current)
            path.append(current)
            current = entry[1]
        value = FrameIdentity()
        for current in reversed(path):
            value = replace(value, **self.frame_overrides.get(current, {}))
        self.frame_cache[index] = value
        return value

    def hidden(self, index, kind, initial=False):
        """Resolve CFVanish against the parent style; no recursion or CP-sized cache."""
        key = index, kind, initial
        if key in self.cache:
            return self.cache[key]
        # Empty fixed styles are explicitly legal. Missing STSH is tolerated for
        # older extraction callers, but an explicit non-default reference is not.
        if not self.present and index in (0, 10):
            return initial
        path, seen = [], set()
        current = index
        while current != 0xFFF:
            if current in seen:
                raise InvalidDocumentError('cyclic DOC style inheritance')
            if len(path) >= self.doc.limits.max_depth:
                raise LimitExceededError('DOC style inheritance depth limit exceeded')
            if current >= len(self.styles):
                raise InvalidDocumentError('DOC style reference is out of range')
            entry = self.styles[current]
            if entry is None:
                if not path and current <= 12:
                    break
                raise InvalidDocumentError('DOC style references an empty style')
            if entry[0] != kind:
                raise InvalidDocumentError('DOC style kind mismatch')
            self.doc.budget.record()
            seen.add(current)
            path.append(entry)
            current = entry[1]
        value = initial
        for _, _, operations in reversed(path):
            parent = value
            for operand in operations:
                value = toggle(operand, parent)
        self.cache[key] = value
        return value


def toggle(value, inherited):
    if value in (0, 1):
        return bool(value)
    if value in (128, 129):
        return bool(inherited) ^ (value == 129)
    raise InvalidDocumentError('invalid DOC character toggle')


def character_ops(doc, group):
    result = []
    for op, arg in doc._sprms(group):
        if op in (0x083C, 0x0800, 0x0802, 0x0855):
            if arg[0] not in (0, 1, 128, 129):
                raise InvalidDocumentError('invalid DOC CFSpec/visibility toggle')
            result.append((op, arg[0]))
        elif op in (0x6A09, 0x4A30, 0x2A33, 0xCA47):
            result.append((op, bytes(arg)))
        elif op == 0xCA31:
            raise UnsupportedFormatError('DOC character style permutation is unsupported')
    return tuple(result)
