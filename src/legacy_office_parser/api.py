from pathlib import Path
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

def parse(source: Source, *, limits: Limits | None = None) -> Document:
    """Detect DOC/PPT using OLE streams, never trusting the filename extension."""
    limits = limits or Limits()
    data = _read(source, limits)
    with open_ole(data, limits) as ole:
        if ole.exists('EncryptedPackage') or ole.exists('EncryptionInfo'):
            raise EncryptedDocumentError('encrypted Office document')
        doc = ole.exists('WordDocument')
        ppt = ole.exists('PowerPoint Document')
    if doc == ppt:
        raise UnsupportedFormatError('expected exactly one DOC or PPT document stream')
    return parse_doc(data, limits=limits) if doc else parse_ppt(data, limits=limits)
