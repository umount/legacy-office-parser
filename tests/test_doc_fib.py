import pytest
from test_doc import fixture, parse, mutate, u16
from legacy_office_parser import InvalidDocumentError, UnsupportedFormatError, EncryptedDocumentError


def test_obfuscation_bit_is_ignored_without_encryption(monkeypatch):
    streams = mutate(fixture([('OK\r', True)]), 'WordDocument', 10, u16(0x8200))
    assert parse(monkeypatch, streams).text == 'OK'


@pytest.mark.parametrize('flags', [0x100, 0x8100])
def test_encryption_still_rejected(monkeypatch, flags):
    streams = mutate(fixture([('OK\r', True)]), 'WordDocument', 10, u16(flags))
    with pytest.raises(EncryptedDocumentError):
        parse(monkeypatch, streams)


@pytest.mark.parametrize('version,error', [(0xD9, InvalidDocumentError),
                                           (0x1234, UnsupportedFormatError)])
def test_extension_version_controls_validation(monkeypatch, version, error):
    streams = mutate(fixture([('OK\r', True)]), 'WordDocument', 898,
                     u16(2) + u16(version) + u16(0))
    with pytest.raises(error):
        parse(monkeypatch, streams)


def test_truncated_fib_extension(monkeypatch):
    streams = mutate(fixture([('OK\r', True)]), 'WordDocument', 898, u16(65535))
    with pytest.raises(InvalidDocumentError):
        parse(monkeypatch, streams)


def test_valid_extension_overrides_base_version(monkeypatch):
    streams = fixture([('OK\r', True)])
    mutate(streams, 'WordDocument', 152, u16(108))
    mutate(streams, 'WordDocument', 1018, u16(2) + u16(0xD9) + u16(0))
    assert parse(monkeypatch, streams).text == 'OK'
