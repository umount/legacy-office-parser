"""BIFF8 segmented Unicode strings. See docs/XLS.md for provenance."""
import struct
from .errors import InvalidDocumentError, LimitExceededError


class Segments:
    def __init__(self, parts):
        self.parts = parts
        self.segment = 0
        self.pos = 0

    def advance(self):
        self.segment += 1
        self.pos = 0
        if self.segment >= len(self.parts) or not self.parts[self.segment]:
            raise InvalidDocumentError('truncated BIFF string continuation')

    def remaining(self):
        return len(self.parts[self.segment]) - self.pos

    def fixed(self, size):
        if self.remaining() == 0:
            self.advance()
        if size > self.remaining():
            raise InvalidDocumentError('split or truncated BIFF string header')
        result = self.parts[self.segment][self.pos:self.pos + size]
        self.pos += size
        return result

    def skip(self, size):
        while size:
            if not self.remaining():
                self.advance()
            take = min(size, self.remaining())
            self.pos += take
            size -= take

    def string(self, budget, *, short=False, rich=True):
        if not self.remaining():
            self.advance()
        start_segment = self.segment
        count = int.from_bytes(self.fixed(1 if short else 2), 'little')
        flags = self.fixed(1)[0]
        runs = struct.unpack('<H', self.fixed(2))[0] if rich and flags & 8 else 0
        extra = struct.unpack('<i', self.fixed(4))[0] if rich and flags & 4 else 0
        if self.segment != start_segment or extra < 0:
            raise InvalidDocumentError('invalid BIFF string header')
        if count > 32767:
            raise InvalidDocumentError('BIFF string character count exceeds 32767')
        budget(count)
        wide = flags & 1
        raw = bytearray()
        while count:
            if not self.remaining():
                self.advance()
                # Only a continuation of character data has an encoding byte.
                wide = self.fixed(1)[0] & 1
            width = 2 if wide else 1
            take = min(count, self.remaining() // width)
            if not take:
                raise InvalidDocumentError('BIFF continuation splits a UTF-16 code unit')
            chunk = self.fixed(take * width)
            raw.extend(chunk if wide else chunk.decode('latin1').encode('utf-16-le'))
            count -= take
        self.skip(runs * 4 + extra)
        try:
            # Decode once, permitting a surrogate pair across a record boundary.
            return raw.decode('utf-16-le')
        except UnicodeError as exc:
            raise InvalidDocumentError('invalid BIFF Unicode string') from exc

    def finish(self):
        if self.remaining() or self.segment != len(self.parts) - 1:
            raise InvalidDocumentError('unexpected bytes after BIFF string data')


def shared_strings(parts, limits, budget):
    source = Segments(parts)
    total, unique = struct.unpack('<II', source.fixed(8))
    if unique > total:
        raise InvalidDocumentError('SST unique count exceeds total count')
    if unique > limits.max_cells:
        raise LimitExceededError('XLS shared string count limit exceeded')
    result = [source.string(budget) for _ in range(unique)]
    source.finish()
    return result
