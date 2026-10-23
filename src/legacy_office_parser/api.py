from pathlib import Path
from ._ole import open_ole
from .errors import EncryptedDocumentError, LimitExceededError, UnsupportedFormatError
from .limits import Limits
from .number_locale import NumberLocale, resolve_locale
from .models import Document
# Preserve the existing internal import used by regression tests and tooling.
from ._validation import _validate_result as _validate_result

Source = str | Path | bytes


def _limits(value: Limits | None) -> Limits:
    if value is None:
        return Limits()
    if not isinstance(value, Limits):
        raise TypeError('limits must be Limits or None')
    return value

def _read(source: Source, limits: Limits) -> bytes:
    if isinstance(source, bytes):
        data = source
    elif isinstance(source, (str, Path)):
        with open(source, 'rb') as stream:
            data = stream.read(limits.max_file_bytes + 1)
    else:
        raise TypeError('source must be a path or bytes')
    if len(data) > limits.max_file_bytes:
        raise LimitExceededError('input size limit exceeded')
    return data

def parse_doc(source: Source, *, limits: Limits | None = None) -> Document:
    from .doc import parse_doc_bytes
    limits = _limits(limits)
    return _validate_result(parse_doc_bytes(_read(source, limits), limits), limits)

def parse_ppt(source: Source, *, limits: Limits | None = None) -> Document:
    from .ppt import parse_ppt_bytes
    limits = _limits(limits)
    return _validate_result(parse_ppt_bytes(_read(source, limits), limits), limits)

def parse_xls(source: Source, *, limits: Limits | None = None,
              display_locale: str | NumberLocale | None = None) -> Document:
    from .xls import parse_xls_bytes
    limits = _limits(limits)
    locale = resolve_locale(display_locale)
    return _validate_result(parse_xls_bytes(_read(source, limits), limits, display_locale=locale), limits)


def parse_rtf(source: Source, *, limits: Limits | None = None) -> Document:
    from .rtf import parse_rtf_bytes
    limits = _limits(limits)
    return _validate_result(parse_rtf_bytes(_read(source, limits), limits), limits)


def _parse_odf(source: Source, expected: str | None, limits: Limits | None) -> Document:
    from .odf import parse_odf_bytes
    limits = _limits(limits)
    return _validate_result(parse_odf_bytes(_read(source, limits), limits,
                                           expected_format=expected), limits)


def parse_odt(source: Source, *, limits: Limits | None = None) -> Document:
    return _parse_odf(source, 'odt', limits)


def parse_ods(source: Source, *, limits: Limits | None = None) -> Document:
    return _parse_odf(source, 'ods', limits)


def parse_odp(source: Source, *, limits: Limits | None = None) -> Document:
    return _parse_odf(source, 'odp', limits)


def parse(source: Source, *, limits: Limits | None = None,
          display_locale: str | NumberLocale | None = None) -> Document:
    """Detect by content. display_locale affects XLS numeric display only."""
    locale = resolve_locale(display_locale)
    limits = _limits(limits)
    data = _read(source, limits)
    signature = data.removeprefix(b'\xef\xbb\xbf').lstrip(b' \t\r\n')
    if signature.startswith(b'{\\rtf'):
        return parse_rtf(data, limits=limits)
    if data.startswith((b'PK\x03\x04', b'PK\x05\x06')):
        return _parse_odf(data, None, limits)
    with open_ole(data, limits) as ole:
        if ole.exists('EncryptedPackage') or ole.exists('EncryptionInfo'):
            raise EncryptedDocumentError('encrypted Office document')
        candidates = [parser for name, parser in (
            ('WordDocument', parse_doc), ('PowerPoint Document', parse_ppt),
            ('Workbook', parse_xls), ('Book', parse_xls)) if ole.exists(name)]
    if len(candidates) != 1:
        raise UnsupportedFormatError('expected exactly one DOC, XLS or PPT document stream')
    if candidates[0] is parse_xls:
        return parse_xls(data, limits=limits, display_locale=locale)
    return candidates[0](data, limits=limits)
