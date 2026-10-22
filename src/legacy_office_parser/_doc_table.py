"""Sequential MS-DOC 2.6.3 cell-definition operations (not a layout engine)."""
from dataclasses import dataclass, replace
import struct

from .diagnostics import diagnostic_warning
from .errors import InvalidDocumentError


@dataclass(frozen=True, slots=True)
class TableIdentity:
    """MS-DOC 2.4.3 row identity; positions are compared, never rendered."""
    ipgp: int = 0
    style: int = 11
    anchor: int = 0xF0  # Both PositionCodeOperand components: none (3).
    no_overlap: bool = False
    x: int = 0
    y: int = 0
    left: int = 0
    top: int = 0
    right: int = 0
    bottom: int = 0


    @property
    def default_position(self):
        # TIpgp/style/direction are separate identity criteria, not this gate.
        return (self.anchor == 0xF0 and not self.no_overlap
                and not any((self.x, self.y, self.left, self.top, self.right, self.bottom)))


@dataclass(frozen=True, slots=True)
class FrameIdentity:
    """Only the twelve paragraph frame properties named by MS-DOC 2.4.3."""
    anchor: int = 0xF0
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    drop_cap: int = 0
    wrap: int = 0
    distance_x: int = 0
    distance_y: int = 0
    locked: bool = False
    no_overlap: bool = False
    flow: int = 0


_FRAME_FIELDS = {
    0x261B: 'anchor', 0x8418: 'x', 0x8419: 'y', 0x841A: 'width',
    0x442B: 'height', 0x442C: 'drop_cap', 0x2423: 'wrap',
    0x842F: 'distance_x', 0x842E: 'distance_y', 0x2430: 'locked',
    0x2462: 'no_overlap', 0x443A: 'flow',
}


def frame_change(op, arg):
    """Decode one supported property, masking reserved bits before comparison."""
    name = _FRAME_FIELDS.get(op)
    if name is None:
        return None
    value = int.from_bytes(arg, 'little')
    if name == 'anchor':
        value &= 0xF0
    elif name in ('x', 'y'):
        value = struct.unpack('<h', arg)[0]
        if not -31679 <= value <= 31681:
            raise InvalidDocumentError('invalid DOC frame position operand')
    elif name in ('width', 'distance_x', 'distance_y'):
        if not 0 <= value <= 31680:
            raise InvalidDocumentError('invalid DOC frame distance operand')
    elif name in ('locked', 'no_overlap'):
        if value not in (0, 1):
            raise InvalidDocumentError('invalid DOC frame boolean operand')
    elif name == 'wrap':
        if value > 5:
            raise InvalidDocumentError('invalid DOC frame wrap operand')
    elif name == 'height':
        if (value & 0x7FFF) > 31680 or value == 0x8000:
            raise InvalidDocumentError('invalid DOC frame height operand')
    elif name == 'drop_cap':
        value &= 0xFF
        # Zero is the paragraph default (no drop cap).
        if value and ((value & 7) not in (1, 2) or not 1 <= value >> 3 <= 10):
            raise InvalidDocumentError('invalid DOC frame drop cap operand')
    elif name == 'flow':
        value &= 7
        if value & 2 and not value & 1:
            raise InvalidDocumentError('invalid DOC frame text flow operand')
    return name, value


_POSITION_FIELDS = {
    0x940E: 'x', 0x940F: 'y', 0x9410: 'left', 0x9411: 'top',
    0x941E: 'right', 0x941F: 'bottom',
}


def apply_identity(props, op, arg):
    if op == 0x7469:
        changes = {'ipgp': struct.unpack('<I', arg)[0]}
    elif op == 0x360D:
        # PositionCodeOperand's low four padding bits MUST be ignored.
        changes = {'anchor': arg[0] & 0xF0}
    elif op == 0x3465:
        if arg[0] not in (0, 1):
            raise InvalidDocumentError('invalid DOC table overlap operand')
        changes = {'no_overlap': bool(arg[0])}
    elif op in _POSITION_FIELDS:
        value = struct.unpack('<h', arg)[0]
        name = _POSITION_FIELDS[op]
        low, high = (-31679, 31681) if name in ('x', 'y') else (0, 31680)
        if not low <= value <= high:
            raise InvalidDocumentError('invalid DOC table position operand')
        changes = {name: value}
    else:
        return False
    props.identity = replace(props.identity, **changes)
    return True


def apply_table(props, op, arg, warn):
    """Mutate current cells, so index-based properties follow later edits."""
    if apply_identity(props, op, arg):
        return True
    if op in (0x9601, 0x9602):
        value = struct.unpack('<h', arg)[0]
        if not -31680 <= value <= 31680 or (op == 0x9602 and value < 0):
            raise InvalidDocumentError('invalid DOC table origin operand')
        if op == 0x9601:
            props.table_left = value
            shift = value - props.table_gap - (props.edges[0] if props.edges else 0)
        else:
            shift = props.table_gap - value
            props.table_gap = value
        if props.edges:
            props.edges = [edge + shift for edge in props.edges]
        return True
    if op not in (0x7621, 0x5622, 0x7623, 0x5624, 0x5625, 0xD62B):
        return False
    n = len(props.flags)
    if op == 0xD62B:
        if len(arg) != 3 or arg[0] != 2 or arg[2] not in (0, 1, 3):
            raise InvalidDocumentError('invalid DOC vertical merge operand')
        if arg[1] >= n:
            warn(diagnostic_warning('doc_vertical_merge_without_a_defined_cell_was_ignored', 'Vertical merge without a defined cell was ignored.'))
        else:
            i = arg[1]
            props.flags[i] = (props.flags[i] & ~0x60) | (arg[2] << 5)
        return True
    first, stop = arg[:2]
    if op == 0x7621:
        width = struct.unpack_from('<h', arg, 2)[0]
        count = stop
        if first > n or not count or n + count > 63:
            raise InvalidDocumentError('invalid DOC table insertion range')
        if not 0 <= width <= 31680:
            raise InvalidDocumentError('invalid DOC inserted cell width')
        edges = props.edges or [props.table_left - props.table_gap]
        if edges[-1] - edges[0] + count * width > 31680:
            raise InvalidDocumentError('DOC inserted table width exceeds 31680 twips')
        props.edges = (edges[:first + 1]
                       + [edges[first] + j * width for j in range(1, count + 1)]
                       + [x + count * width for x in edges[first + 1:]])
        props.flags[first:first] = [0] * count
        return True
    if not 0 <= first < n or not first <= stop <= n:
        if op in (0x5624, 0x5625):
            warn(diagnostic_warning('doc_invalid_horizontal_merge_range_was_ignored', 'Invalid horizontal merge range was ignored.'))
            return True
        raise InvalidDocumentError('invalid DOC table cell range')
    if op == 0x5622:
        if stop - first == n:
            raise InvalidDocumentError('DOC table deletion removes every cell')
        width = props.edges[stop] - props.edges[first]
        props.edges = props.edges[:first + 1] + [x - width for x in props.edges[stop + 1:]]
        del props.flags[first:stop]
    elif op == 0x7623:
        width = struct.unpack_from('<h', arg, 2)[0]
        if not 0 <= width <= 31680:
            raise InvalidDocumentError('invalid DOC column width')
        shift = (stop - first) * width - (props.edges[stop] - props.edges[first])
        props.edges = (props.edges[:first + 1]
                       + [props.edges[first] + j * width for j in range(1, stop - first + 1)]
                       + [x + shift for x in props.edges[stop + 1:]])
    else:
        for i in range(first, stop):
            flag = (2 if i == first else 1) if op == 0x5624 else 0
            props.flags[i] = (props.flags[i] & ~3) | flag
    return True
