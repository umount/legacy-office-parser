from contextlib import contextmanager
from io import BytesIO
import olefile
from .errors import InvalidDocumentError, LimitExceededError
from .limits import Limits

@contextmanager
def open_ole(data: bytes, limits: Limits):
    if len(data) > limits.max_file_bytes:
        raise LimitExceededError('input size limit exceeded')
    if not data.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'):
        raise InvalidDocumentError('expected an OLE compound document')
    try:
        obj = olefile.OleFileIO(BytesIO(data), raise_defects=olefile.DEFECT_INCORRECT)
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
