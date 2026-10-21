"""Bounded ODF package/XML reader, implemented using Python's standard library."""
from io import BytesIO
import re
import zipfile
import zlib
from xml.etree import ElementTree as ET

from .errors import (EncryptedDocumentError, InvalidDocumentError,
                     LimitExceededError, UnsupportedFormatError)

NS = {p: f'urn:oasis:names:tc:opendocument:xmlns:{p}:1.0'
      for p in ('office', 'text', 'table', 'draw', 'presentation', 'manifest', 'style')}
NS['draw'] = 'urn:oasis:names:tc:opendocument:xmlns:drawing:1.0'

def q(name):
    prefix, local = name.split(':', 1)
    return '{' + NS[prefix] + '}' + local


def cap(limits, name, default):
    return getattr(limits, name, default)


class Budget:
    def __init__(self, limits):
        self.limits = limits
        self.nodes = self.source_chars = self.output_chars = self.cells = 0

    def text(self, n):
        self.output_chars += n
        if self.output_chars > cap(self.limits, 'max_text_chars', 10_000_000):
            raise LimitExceededError('ODF expanded text limit exceeded')

    def cell(self, n):
        self.cells += n
        if self.cells > cap(self.limits, 'max_cells', 100_000):
            raise LimitExceededError('ODF cell limit exceeded')


class _Tree:
    def __init__(self, budget):
        self.budget = budget
        self.depth = 0
        self.tree = ET.TreeBuilder()

    def start(self, tag, attrs):
        self.depth += 1
        self.budget.nodes += 1
        if self.depth > min(self.budget.limits.max_depth, 256):
            raise LimitExceededError('ODF XML depth limit exceeded')
        if self.budget.nodes > self.budget.limits.max_records:
            raise LimitExceededError('ODF XML node limit exceeded')
        self.charge(sum(len(k) + len(v) for k, v in attrs.items()))
        return self.tree.start(tag, attrs)

    def charge(self, n):
        self.budget.source_chars += n
        if self.budget.source_chars > cap(self.budget.limits, 'max_text_chars', 10_000_000):
            raise LimitExceededError('ODF XML text/attribute limit exceeded')

    def data(self, text):
        self.charge(len(text))
        self.tree.data(text)

    def end(self, tag):
        self.depth -= 1
        return self.tree.end(tag)

    def doctype(self, *args):
        raise InvalidDocumentError('ODF DTD/entity declarations are forbidden')

    def close(self):
        return self.tree.close()


def xml(data, budget):
    # NUL removal also exposes declaration tokens in UTF-16/32 before parsing.
    if re.search(br'<!\s*(?:DOCTYPE|ENTITY)\b', data.replace(b'\0', b''), re.I):
        raise InvalidDocumentError('ODF DTD/entity declarations are forbidden')
    try:
        parser = ET.XMLParser(target=_Tree(budget))
        for offset in range(0, len(data), 16384):
            parser.feed(data[offset:offset + 16384])
        return parser.close()
    except (ET.ParseError, ValueError) as exc:
        if isinstance(exc, (InvalidDocumentError, LimitExceededError)):
            raise
        raise InvalidDocumentError('Malformed ODF XML') from exc


MIMES = {f'application/vnd.oasis.opendocument.{suffix}': fmt
         for suffix, fmt in [('text', 'odt'), ('spreadsheet', 'ods'), ('presentation', 'odp')]}


def read_package(data, budget, expected):
    if len(data) > budget.limits.max_file_bytes:
        raise LimitExceededError('ODF file size limit exceeded')
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > cap(budget.limits, 'max_archive_entries', 4096):
                raise LimitExceededError('ODF archive entry limit exceeded')
            if len({e.filename for e in entries}) != len(entries):
                raise InvalidDocumentError('Duplicate ODF ZIP member')
            if any(e.flag_bits & 1 for e in entries):
                raise EncryptedDocumentError('Encrypted ODF ZIP member')
            if sum(e.file_size for e in entries) > cap(budget.limits, 'max_uncompressed_bytes', 128 * 1024**2):
                raise LimitExceededError('ODF ZIP expansion limit exceeded')
            if any(e.file_size > cap(budget.limits, 'max_stream_bytes', 64 * 1024**2) for e in entries):
                raise LimitExceededError('ODF ZIP member size limit exceeded')

            def read(name):
                with archive.open(name) as stream:
                    maximum = cap(budget.limits, 'max_stream_bytes', 64 * 1024**2)
                    result = stream.read(maximum + 1)
                    if len(result) > maximum:
                        raise LimitExceededError('ODF ZIP member size limit exceeded')
                    return result

            manifest = None
            root_mime = None
            if 'META-INF/manifest.xml' in archive.namelist():
                manifest = xml(read('META-INF/manifest.xml'), budget)
                if manifest.tag != q('manifest:manifest'):
                    raise InvalidDocumentError('Invalid ODF manifest root')
                if any(e.tag == q('manifest:encryption-data') for e in manifest.iter()):
                    raise EncryptedDocumentError('Encrypted ODF package')
                for e in manifest:
                    if e.get(q('manifest:full-path')) == '/':
                        if root_mime is not None:
                            raise InvalidDocumentError('Duplicate ODF manifest root entry')
                        root_mime = e.get(q('manifest:media-type'), '')
            mime = read('mimetype').decode('ascii') if 'mimetype' in archive.namelist() else root_mime
            if root_mime and root_mime != mime:
                raise InvalidDocumentError('ODF mimetype/manifest mismatch')
            if mime not in MIMES:
                raise UnsupportedFormatError('Unsupported or missing ODF mimetype')
            fmt = MIMES[mime]
            if expected is not None and expected != fmt:
                raise InvalidDocumentError('ODF format does not match expected format')
            content = xml(read('content.xml'), budget)
            styles = xml(read('styles.xml'), budget) if 'styles.xml' in archive.namelist() else None
            return fmt, content, styles, manifest is None
    except NotImplementedError as exc:
        raise UnsupportedFormatError('Unsupported ODF ZIP compression') from exc
    except (zipfile.BadZipFile, KeyError, UnicodeError, EOFError, zlib.error, RuntimeError) as exc:
        raise InvalidDocumentError('Malformed ODF ZIP package') from exc
