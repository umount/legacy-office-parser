"""Small original OLE directory fixtures exercise container budgets."""
import struct

import pytest

from legacy_office_parser import Limits, LimitExceededError, InvalidDocumentError
from legacy_office_parser._ole import open_ole


def directory_chain(entries=40):
    free, end = 0xFFFFFFFF, 0xFFFFFFFE
    sectors = (entries + 3) // 4
    header = bytearray(512)
    header[:8] = bytes.fromhex('d0cf11e0a1b11ae1')
    struct.pack_into('<HHHHH', header, 24, 0x3E, 3, 0xFFFE, 9, 6)
    struct.pack_into('<IIIIIIIII', header, 40, 0, 1, 1, 0, 4096, end, 0, end, 0)
    struct.pack_into('<109I', header, 76, 0, *([free] * 108))
    fat = [free] * 128
    fat[0] = 0xFFFFFFFD
    for i in range(1, sectors + 1):
        fat[i] = i + 1 if i < sectors else end
    directory = bytearray(sectors * 512)
    for i in range(entries):
        pos = i * 128
        name = ('Root Entry' if i == 0 else f'Storage{i}').encode('utf-16le') + b'\0\0'
        directory[pos:pos + len(name)] = name
        struct.pack_into('<HBBIII', directory, pos + 64, len(name), 5 if i == 0 else 1,
                         1, free, free, i + 1 if i + 1 < entries else free)
        struct.pack_into('<I', directory, pos + 116, end)
    return bytes(header) + struct.pack('<128I', *fat) + directory


def test_directory_depth_checked_before_recursive_library_traversal():
    data = directory_chain()
    with pytest.raises(LimitExceededError, match='depth'):
        with open_ole(data, Limits(max_depth=8)):
            pytest.fail('directory depth was ignored')
    with open_ole(data, Limits(max_depth=64)) as ole:
        assert ole.root.name == 'Root Entry'


def test_directory_record_budget():
    with pytest.raises(LimitExceededError, match='record'):
        with open_ole(directory_chain(), Limits(max_depth=64, max_records=10)):
            pytest.fail('directory record budget was ignored')


def test_directory_cycle_is_a_structured_error():
    data = bytearray(directory_chain(4))
    struct.pack_into('<I', data, 1024 + 3 * 128 + 76, 1)
    with pytest.raises(InvalidDocumentError):
        with open_ole(bytes(data), Limits()):
            pytest.fail('directory cycle accepted')
