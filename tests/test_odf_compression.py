"""ODF compression is checked before constructing any decompressor."""
from io import BytesIO
import struct
import zipfile

import pytest
from legacy_office_parser import parse, UnsupportedFormatError
from test_odf import package


@pytest.mark.parametrize('method', [zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA, 99])
@pytest.mark.parametrize('member', ['mimetype', 'unused.bin'])
def test_other_methods_rejected_before_decoder(method, member, monkeypatch):
    data = bytearray(package('<text:p>ok</text:p>', extra={'unused.bin': b'ignored'}))
    with zipfile.ZipFile(BytesIO(data)) as archive:
        local = archive.getinfo(member).header_offset
    struct.pack_into('<H', data, local + 8, method)
    position = 0
    while (position := data.find(b'PK\x01\x02', position)) >= 0:
        n = struct.unpack_from('<H', data, position + 28)[0]
        if bytes(data[position + 46:position + 46 + n]).decode() == member:
            struct.pack_into('<H', data, position + 10, method)
            break
        position += 4

    def forbidden_decoder(*args):
        pytest.fail('decompressor constructed before method validation')

    monkeypatch.setattr(zipfile, '_get_decompressor', forbidden_decoder)
    with pytest.raises(UnsupportedFormatError, match='compression'):
        parse(bytes(data))


@pytest.mark.parametrize('method', [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
def test_supported_methods_remain_readable(method):
    out = BytesIO()
    with zipfile.ZipFile(BytesIO(package('<text:p>ok</text:p>'))) as source:
        with zipfile.ZipFile(out, 'w', compression=method) as target:
            for name in source.namelist():
                target.writestr(name, source.read(name))
    assert parse(out.getvalue()).text == 'ok'
