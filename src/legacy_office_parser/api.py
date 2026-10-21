from pathlib import Path
import math
from ._ole import open_ole
from .errors import EncryptedDocumentError, LimitExceededError, UnsupportedFormatError
from .limits import Limits
from .models import Document

Source = str | Path | bytes

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

def _validate_result(doc: Document, limits: Limits) -> Document:
    # Defence in depth; individual parsers enforce limits during decoding too.
    from .models import Paragraph
    total = 0
    cells = 0
    for block in doc.blocks:
        if isinstance(block, Paragraph):
            total += len(block.text)
        else:
            for row in block.rows:
                cells += len(row)
                total += sum(len(c.text) for c in row)
    for slide in doc.slides:
        total += len(slide.title) + len(slide.text) + len(slide.notes)
    if len(doc.sheets) > limits.max_sheets:
        raise LimitExceededError('sheet count limit exceeded')
    for sheet in doc.sheets:
        if not 0 <= sheet.rows <= limits.max_rows or not 0 <= sheet.columns <= limits.max_columns:
            raise LimitExceededError('sheet dimensions exceed limits')
        total += len(sheet.name)
        cells += len(sheet.cells) + len(sheet.merges)
        for cell in sheet.cells:
            if not 1 <= cell.row <= limits.max_rows or not 1 <= cell.column <= limits.max_columns:
                raise LimitExceededError('cell coordinates exceed limits')
            total += len(cell.text) + len(cell.formula or '')
            if isinstance(cell.value, str) and cell.value != cell.text:
                total += len(cell.value)
            if isinstance(cell.value, float) and not math.isfinite(cell.value):
                from .errors import InvalidDocumentError
                raise InvalidDocumentError('non-finite spreadsheet value')
        for merged in sheet.merges:
            if not (1 <= merged.start_row <= merged.end_row <= limits.max_rows and
                    1 <= merged.start_column <= merged.end_column <= limits.max_columns):
                raise LimitExceededError('merged cell coordinates exceed limits')
    total += sum(len(s) for s in (doc.footnotes, doc.endnotes, doc.headers_footers, doc.textboxes))
    if total > limits.max_text_chars:
        raise LimitExceededError('output text size limit exceeded')
    if cells > limits.max_cells:
        raise LimitExceededError('table cell limit exceeded')
    if len(doc.slides) > limits.max_slides:
        raise LimitExceededError('slide count limit exceeded')
    return doc

def parse_doc(source: Source, *, limits: Limits | None = None) -> Document:
    from .doc import parse_doc_bytes
    limits = limits or Limits()
    return _validate_result(parse_doc_bytes(_read(source, limits), limits), limits)

def parse_ppt(source: Source, *, limits: Limits | None = None) -> Document:
    from .ppt import parse_ppt_bytes
    limits = limits or Limits()
    return _validate_result(parse_ppt_bytes(_read(source, limits), limits), limits)

def parse_xls(source: Source, *, limits: Limits | None = None) -> Document:
    from .xls import parse_xls_bytes
    limits = limits or Limits()
    return _validate_result(parse_xls_bytes(_read(source, limits), limits), limits)


def parse_rtf(source: Source, *, limits: Limits | None = None) -> Document:
    from .rtf import parse_rtf_bytes
    limits = limits or Limits()
    return _validate_result(parse_rtf_bytes(_read(source, limits), limits), limits)


def _parse_odf(source: Source, expected: str | None, limits: Limits | None) -> Document:
    from .odf import parse_odf_bytes
    limits = limits or Limits()
    return _validate_result(parse_odf_bytes(_read(source, limits), limits,
                                           expected_format=expected), limits)


def parse_odt(source: Source, *, limits: Limits | None = None) -> Document:
    return _parse_odf(source, 'odt', limits)


def parse_ods(source: Source, *, limits: Limits | None = None) -> Document:
    return _parse_odf(source, 'ods', limits)


def parse_odp(source: Source, *, limits: Limits | None = None) -> Document:
    return _parse_odf(source, 'odp', limits)


def parse(source: Source, *, limits: Limits | None = None) -> Document:
    """Detect supported formats by content, never by filename extension."""
    limits = limits or Limits()
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
    return candidates[0](data, limits=limits)
