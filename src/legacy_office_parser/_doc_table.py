"""Sequential MS-DOC 2.6.3 cell-definition operations (not a layout engine)."""
from dataclasses import dataclass, replace
import struct

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
            warn('Vertical merge without a defined cell was ignored.')
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
            warn('Invalid horizontal merge range was ignored.')
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
