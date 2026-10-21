"""Malformed ZIP offsets must fail through the public parse-error contract."""
from struct import pack_into

import pytest

from legacy_office_parser import parse, InvalidDocumentError
from test_odf import package


@pytest.mark.parametrize('fmt', ['odt', 'ods', 'odp'])
def test_forged_directory_offset_cannot_seek_before_archive(fmt):
    data = bytearray(package(fmt=fmt))
    end = data.rindex(b'PK\x05\x06')
    pack_into('<I', data, end + 16, 0x70000000)
    with pytest.raises(InvalidDocumentError):
        parse(bytes(data))


@pytest.mark.parametrize('offset', [0x7fffffff, 0xffffffff])
def test_member_local_header_outside_archive_is_classified(offset):
    data = bytearray(package())
    directory = data.index(b'PK\x01\x02')
    pack_into('<I', data, directory + 42, offset)
    with pytest.raises(InvalidDocumentError):
        parse(bytes(data))
