from contextlib import contextmanager
from io import BytesIO
import struct
import olefile
from .errors import ParseError, InvalidDocumentError, LimitExceededError
from .limits import Limits

class _BoundedOle(olefile.OleFileIO):
    """Check directory links iteratively before olefile builds its recursive tree."""
    def __init__(self, data, limits):
        self._limits = limits
        super().__init__(BytesIO(data), raise_defects=olefile.DEFECT_INCORRECT)

    def loaddirectory(self, sector):
        # olefile's directory stream reader bounds sector chains to the input.
        # This preflight adds the same depth/record budgets used by our parsers.
        with self._open(sector, force_FAT=True) as directory:
            if directory.size > self._limits.max_stream_bytes:
                raise LimitExceededError('OLE directory size limit exceeded')
            count = directory.size // 128
            pending = [(0, 0)]
            seen = set()
            while pending:
                sid, depth = pending.pop()
                if sid == 0xFFFFFFFF:
                    continue
                if depth > self._limits.max_depth:
                    raise LimitExceededError('OLE directory depth limit exceeded')
                if sid >= count or sid in seen:
                    raise InvalidDocumentError('invalid OLE directory link')
                seen.add(sid)
                if len(seen) > self._limits.max_records:
                    raise LimitExceededError('OLE directory record limit exceeded')
                directory.seek(sid * 128 + 68)
                links = directory.read(12)
                if len(links) != 12:
                    raise InvalidDocumentError('truncated OLE directory entry')
                pending.extend((child, depth + 1) for child in struct.unpack('<III', links)
                               if child != 0xFFFFFFFF)
        super().loaddirectory(sector)


@contextmanager
def open_ole(data: bytes, limits: Limits):
    if len(data) > limits.max_file_bytes:
        raise LimitExceededError('input size limit exceeded')
    if not data.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'):
        raise InvalidDocumentError('expected an OLE compound document')
    try:
        obj = _BoundedOle(data, limits)
    except ParseError:
        raise
    except RecursionError as exc:
        raise LimitExceededError('OLE directory exceeds safe recursion depth') from exc
    except (OSError, ValueError, IndexError) as exc:
        raise InvalidDocumentError('invalid OLE container') from exc
    try:
        yield obj
    finally:
        obj.close()

def read_stream(ole, name: str, limits: Limits, *, required: bool = True) -> bytes:
    if not ole.exists(name):
        if required:
            raise InvalidDocumentError(f'missing required stream: {name}')
        return b''
    if ole.get_size(name) > limits.max_stream_bytes:
        raise LimitExceededError('OLE stream size limit exceeded')
    try:
        with ole.openstream(name) as stream:
            data = stream.read(limits.max_stream_bytes + 1)
    except (OSError, ValueError, IndexError) as exc:
        raise InvalidDocumentError('invalid OLE stream') from exc
    if len(data) > limits.max_stream_bytes:
        raise LimitExceededError('OLE stream size limit exceeded')
    return data
