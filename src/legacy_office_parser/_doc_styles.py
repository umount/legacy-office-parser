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
        self.conditions = {}
        self.condition_cache = {}
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
            conditional = {}
            bands = {}
            unsafe = False
            if kind == 3:
                # Phase-one proof: any paragraph properties may affect frame
                # identity. Unknown TAPX likewise cannot establish a safe grid.
                unsafe = bool(groups[1])
                for op, arg in doc._sprms(groups[0], allow_padding=False):
                    if op in (0x3488, 0x3489):
                        if not 1 <= arg[0] <= 3:
                            raise InvalidDocumentError('invalid DOC table band size')
                        bands[op] = arg[0]
                    else:
                        unsafe = True

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
                        if len(arg) < 3:
                            raise InvalidDocumentError('short DOC conditional character style operand')
                        cnfc = u16(arg, 1)
                        if cnfc not in (1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048):
                            raise InvalidDocumentError('invalid DOC conditional style condition')
                        values = conditional.setdefault(cnfc, [])
                        for subop, subarg in doc._sprms(arg[3:], allow_padding=False):
                            if ((subop >> 10) & 7 != 2 or subop in _UPX_CHPX_FORBIDDEN
                                    or subop in (0x0800, 0x0801, 0x0802, 0x0855, 0x6A09, 0xCA85)):
                                raise InvalidDocumentError('forbidden DOC conditional character style property')
                            if subop == 0x083C:
                                if subarg[0] not in (0, 1, 128, 129):
                                    raise InvalidDocumentError('invalid DOC CFVanish toggle')
                                # Relative toggles need a separately established
                                # conditional-style base; don't guess it here.
                                unsafe |= subarg[0] in (128, 129)
                                values.append(subarg[0])
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
            if kind == 3:
                self.conditions[index] = (conditional, bands, unsafe)
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

    def table_conditions(self, index):
        """Bounded inherited condition sequences, band sizes and proof status."""
        if index is None:
            return {}, {}, False
        if not 0 <= index < len(self.styles) or not self.styles[index] or self.styles[index][0] != 3:
            index = 11
        if index not in self.conditions:
            return {}, {}, False
        if index in self.condition_cache:
            return self.condition_cache[index]
        self.hidden(index, 3)  # Strict parent validation and depth checks.
        path = []
        current = index
        while current != 0xFFF:
            self.doc.budget.record()
            path.append(current)
            current = self.styles[current][1]
        conditions, bands, unsafe = {}, {}, False
        for current in reversed(path):
            local, local_bands, local_unsafe = self.conditions[current]
            bands.update(local_bands)
            unsafe |= local_unsafe
            for condition, operations in local.items():
                self.doc.budget.record()
                conditions.setdefault(condition, []).append(tuple(operations))
        result = conditions, bands, unsafe
        self.condition_cache[index] = result
        return result

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
