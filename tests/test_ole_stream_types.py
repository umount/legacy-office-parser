"""Wrong-kind OLE directory entries must produce structured parser errors."""
from pathlib import Path
import struct

import olefile
import pytest

from legacy_office_parser import InvalidDocumentError, Limits, parse, parse_xls
from legacy_office_parser._ole import open_ole, read_stream
from test_ole_limits import directory_chain


def named_entry(name, kind):
    data = bytearray(directory_chain(2))
    offset = 1024 + 128
    encoded = (name + '\0').encode('utf-16le')
    assert len(encoded) <= 64
    data[offset:offset + 64] = encoded.ljust(64, b'\0')
    struct.pack_into('<H', data, offset + 64, len(encoded))
    data[offset + 66] = kind
    return bytes(data)


@pytest.mark.parametrize('name', ['Workbook', 'Book', 'WordDocument', '0Table', '1Table',
                                   'Data', 'PowerPoint Document', 'Current User'])
@pytest.mark.parametrize('kind', [olefile.STGTY_EMPTY, olefile.STGTY_STORAGE])
@pytest.mark.parametrize('required', [True, False])
def test_wrong_type_rejected_before_size_or_open(monkeypatch, name, kind, required):
    with open_ole(named_entry(name, kind), Limits()) as compound:
        assert compound.exists(name)

        def unexpected(*args):
            pytest.fail('non-stream reached stream size or allocation')

        monkeypatch.setattr(compound, 'get_size', unexpected)
        monkeypatch.setattr(compound, 'openstream', unexpected)
        with pytest.raises(InvalidDocumentError, match='expected an OLE stream'):
            read_stream(compound, name, Limits(), required=required)


def test_missing_optional_and_valid_empty_stream_remain_supported():
    with open_ole(named_entry('Data', olefile.STGTY_STREAM), Limits()) as compound:
        assert read_stream(compound, 'Data', Limits()) == b''
        assert read_stream(compound, 'missing', Limits(), required=False) == b''
        with pytest.raises(InvalidDocumentError, match='missing required stream'):
            read_stream(compound, 'missing', Limits())


@pytest.mark.parametrize('reader', [parse, parse_xls])
@pytest.mark.parametrize('kind', [olefile.STGTY_EMPTY, olefile.STGTY_STORAGE])
def test_single_byte_mutation_of_authored_sections_xls(reader, kind):
    # Reproduces the mutation failure with just a directory object-type edit.
    # No stored mutated blob and no other random mutations are necessary.
    original = (Path(__file__).parent / 'fixtures/xls_sections/sign_sections.xls').read_bytes()
    with open_ole(original, Limits()) as compound:
        sid = compound._find('Workbook')
        assert compound.get_type('Workbook') == olefile.STGTY_STREAM
    sector_size = 1 << struct.unpack_from('<H', original, 30)[0]
    first_directory = struct.unpack_from('<I', original, 48)[0]
    assert sid * 128 + 128 <= sector_size  # entry is within first directory sector
    offset = (first_directory + 1) * sector_size + sid * 128 + 66
    assert original[offset] == olefile.STGTY_STREAM
    mutated = bytearray(original)
    mutated[offset] = kind
    with pytest.raises(InvalidDocumentError, match='expected an OLE stream'):
        reader(bytes(mutated))


def test_unrelated_typeerror_is_not_broadly_wrapped(monkeypatch):
    with open_ole(named_entry('Data', olefile.STGTY_STREAM), Limits()) as compound:
        def unexpected(*args):
            raise TypeError('unrelated implementation error')
        monkeypatch.setattr(compound, 'get_size', unexpected)
        with pytest.raises(TypeError, match='unrelated implementation error'):
            read_stream(compound, 'Data', Limits())
