"""Focused BIFF8 extraction with bounded numeric display; no calculation runtime.

Protocol/reference provenance is recorded in docs/XLS.md.
"""
from __future__ import annotations

import math
import struct

from .diagnostics import diagnostic_warning
from ._ole import open_ole, read_stream
from ._xls_formats import BUILTIN_NUMERIC, hides_text, text_affixes, text_literal, render_number
from ._xls_dates import interpret_date
from .number_locale import resolve_locale
from ._xls_strings import Segments, shared_strings
from .errors import EncryptedDocumentError, InvalidDocumentError, LimitExceededError, UnsupportedFormatError
from .limits import Limits
from .models import CellRange, Document, Sheet, SpreadsheetCell

ERRORS = {0: '#NULL!', 7: '#DIV/0!', 15: '#VALUE!', 23: '#REF!', 29: '#NAME?',
          36: '#NUM!', 42: '#N/A', 43: '#GETTING_DATA'}
BOFS = {0x0009, 0x0209, 0x0409, 0x0809}


def _need(data, size, exact=False):
    if len(data) < size or (exact and len(data) != size):
        raise InvalidDocumentError('invalid BIFF record length')


def _rk(data):
    """Decode signed 30-bit integer or high 30 IEEE bits, then optional /100."""
    bits = int.from_bytes(data, 'little')
    if bits & 2:
        value = struct.unpack('<i', data)[0] >> 2
    else:
        value = struct.unpack('<d', struct.pack('<Q', (bits & ~3) << 32))[0]
    return value / 100 if bits & 1 else value


class _Parser:
    def __init__(self, data, limits, *, display_locale=None):
        self.display_locale = resolve_locale(display_locale)
        self.data, self.limits = data, limits
        self.records = self.chars = self.cells = self.merges = 0
        self.warnings = []
        self.sst, self.xfs, self.formats = [], [], {}
        self.datemode = 0

    def warn(self, message):
        if message not in self.warnings:
            self.warnings.append(message)

    def text_budget(self, count):
        self.chars += count
        if self.chars > self.limits.max_text_chars:
            raise LimitExceededError('XLS text limit exceeded')

    def record(self, pos, end):
        if pos + 4 > end:
            raise InvalidDocumentError('truncated BIFF record header or missing EOF')
        code, size = struct.unpack_from('<HH', self.data, pos)
        if size > 8224 or pos + 4 + size > end:
            raise InvalidDocumentError('invalid BIFF record size')
        self.records += 1
        if self.records > self.limits.max_records:
            raise LimitExceededError('XLS record limit exceeded')
        if code == 0x002F:
            raise EncryptedDocumentError('encrypted XLS (FILEPASS) is unsupported')
        return code, self.data[pos + 4:pos + 4 + size], pos + 4 + size

    def bof(self, pos, end, expected=None):
        code, data, pos = self.record(pos, end)
        if code not in BOFS:
            raise InvalidDocumentError('expected BIFF BOF')
        _need(data, 4)
        version, kind = struct.unpack_from('<HH', data)
        if code != 0x0809 or version != 0x0600:
            raise UnsupportedFormatError('only XLS BIFF8 is supported')
        _need(data, 16, True)
        if expected is not None and kind != expected:
            raise InvalidDocumentError('unexpected BIFF substream type')
        return kind, pos

    def parts(self, data, pos, end):
        parts = [data]
        while pos + 4 <= end and struct.unpack_from('<H', self.data, pos)[0] == 0x003C:
            _, data, pos = self.record(pos, end)
            parts.append(data)
        return parts, pos

    def string(self, data, pos, end, *, rich=True):
        parts, pos = self.parts(data, pos, end)
        source = Segments(parts)
        value = source.string(self.text_budget, rich=rich)
        source.finish()
        return value, pos

    def coords(self, row, col):
        if not (0 <= row < 65536 and 0 <= col < 256):
            raise InvalidDocumentError('invalid BIFF8 cell coordinate')
        if row >= self.limits.max_rows or col >= self.limits.max_columns:
            raise LimitExceededError('XLS row or column limit exceeded')

    def number(self, value, xf):
        if not math.isfinite(value):
            raise InvalidDocumentError('non-finite XLS numeric value')
        if xf >= len(self.xfs):
            self.warn(diagnostic_warning('xls_missing_xf_numeric_values_retained_without_date_interpretation', 'Missing XF: numeric values retained without date interpretation.'))
            return value, 'number', str(value)
        fmt = self.xfs[xf]
        custom = self.formats.get(fmt)
        numeric_format = custom if custom is not None else BUILTIN_NUMERIC.get(fmt)
        if numeric_format is not None:
            text = render_number(value, numeric_format, display_locale=self.display_locale)
            if text is not None:
                return value, 'number', text
        outcome = interpret_date(value, custom if custom is not None else fmt, self.datemode)
        if outcome.status == 'ok':
            return outcome.result
        if outcome.status == 'unsupported':
            self.warn(diagnostic_warning('xls_unsupported_or_ambiguous_date_number_format_raw_numeric_value',
                                         'Unsupported or ambiguous date/number format: raw numeric value retained.'))
        elif outcome.status == 'unrepresentable':
            self.warn(diagnostic_warning('xls_unrepresentable_excel_date_including_serial_60_raw_numeric_value',
                                         'Unrepresentable Excel date (including serial 60): raw numeric value retained.'))
        else:
            self.warn(diagnostic_warning('xls_excel_date_outside_supported_range_raw_numeric_value_retained',
                                         'Excel date outside supported range: raw numeric value retained.'))
        return outcome.result

    def add(self, sheet, seen, row, col, xf, value=None, kind='empty', formula=False,
            charged=False):
        self.coords(row, col)
        self.cells += 1
        if self.cells + self.merges > self.limits.max_cells:
            raise LimitExceededError('XLS cell limit exceeded')
        if (row, col) in seen:
            raise InvalidDocumentError('duplicate XLS cell coordinate')
        seen.add((row, col))
        if kind == 'number':
            value, kind, text = self.number(value, xf)
        elif kind == 'boolean':
            text = 'TRUE' if value else 'FALSE'
        else:
            text = '' if value is None else str(value)
        if not charged:
            self.text_budget(len(text))
        # Charge retained raw strings before suppressing their display. LABEL
        # and formula STRING were charged while decoding; SST references are
        # charged above on each use, as for visible strings.
        if kind == 'string' and xf < len(self.xfs):
            custom = self.formats.get(self.xfs[xf])
            if custom is not None and hides_text(custom):
                text = ''
            elif custom is not None:
                affixes = text_affixes(custom)
                if affixes is not None:
                    prefix, suffix = affixes
                    if prefix or suffix:
                        # Both raw and distinct display strings are retained.
                        self.text_budget(len(text) + len(prefix) + len(suffix))
                        text = prefix + text + suffix
                else:
                    literal = text_literal(custom)
                    if literal is not None and literal != text:
                        # Raw text remains charged; distinct literal display
                        # has its own charge (including every SST occurrence).
                        self.text_budget(len(literal))
                        text = literal
        sheet.cells.append(SpreadsheetCell(row=row + 1, column=col + 1, value=value,
                                           value_type=kind, text=text, formula=None,
                                           is_formula=formula))
        sheet.rows = max(sheet.rows, row + 1)
        sheet.columns = max(sheet.columns, col + 1)

    def parse(self):
        end = len(self.data)
        _, pos = self.bof(0, end, 5)
        bounds = []
        got_sst = False
        while True:
            code, data, pos = self.record(pos, end)
            if code == 0x000A:
                _need(data, 0, True)
                break
            if code in BOFS:
                raise InvalidDocumentError('nested BOF in workbook globals')
            if code == 0x0085:
                _need(data, 8)
                offset, hidden, kind = struct.unpack_from('<IBB', data)
                source = Segments([data[6:]])
                name = source.string(self.text_budget, short=True, rich=False)
                source.finish()
                if hidden > 2 or not name or len(name) > 31:
                    raise InvalidDocumentError('invalid BOUNDSHEET metadata')
                bounds.append((offset, hidden, kind, name))
                if len(bounds) > self.limits.max_sheets:
                    raise LimitExceededError('XLS sheet limit exceeded')
            elif code == 0x00FC:
                if got_sst:
                    raise InvalidDocumentError('duplicate SST')
                parts, pos = self.parts(data, pos, end)
                self.sst = shared_strings(parts, self.limits, self.text_budget)
                got_sst = True
            elif code == 0x00E0:
                _need(data, 20, True)
                self.xfs.append(struct.unpack_from('<H', data, 2)[0])
            elif code == 0x041E:
                _need(data, 5)
                fmt = struct.unpack_from('<H', data)[0]
                self.formats[fmt], pos = self.string(data[2:], pos, end, rich=False)
            elif code == 0x0022:
                _need(data, 2, True)
                self.datemode = struct.unpack('<H', data)[0]
                if self.datemode not in (0, 1):
                    raise InvalidDocumentError('invalid XLS date mode')
        offsets = sorted(offset for offset, *_ in bounds)
        if len(set(offsets)) != len(offsets) or any(o < pos or o >= end for o in offsets):
            raise InvalidDocumentError('invalid or duplicate sheet offset')
        ends = dict(zip(offsets, offsets[1:] + [end]))
        sheets = []
        for offset, hidden, kind, name in bounds:
            expected = {0: 0x0010, 1: 0x0040, 2: 0x0020, 6: 0x0006}.get(kind)
            if expected is None:
                raise UnsupportedFormatError('unsupported XLS sheet type')
            _, start = self.bof(offset, ends[offset], expected)
            sheet = Sheet(name=name, hidden=bool(hidden)) if kind == 0 else None
            if sheet is None:
                self.warn(diagnostic_warning('xls_non_worksheet_sheets_omitted_charts_macros_vb_modules', 'Non-worksheet sheets omitted (charts/macros/VB modules).'))
            self.sheet(sheet, start, ends[offset])
            if sheet is not None:
                sheets.append(sheet)
        return Document(format='xls', sheets=sheets, warnings=self.warnings)

    def sheet(self, sheet, pos, end):
        seen = set()
        depth = 1
        pending = None
        while True:
            code, data, pos = self.record(pos, end)
            if code in BOFS:
                if pending is not None:
                    raise InvalidDocumentError('missing formula STRING result')
                _need(data, 16, True)
                if struct.unpack_from('<HH', data) != (0x600, 0x20):
                    raise InvalidDocumentError('unexpected nested sheet BOF')
                depth += 1
                if depth > self.limits.max_depth:
                    raise LimitExceededError('XLS substream depth limit exceeded')
                continue
            if code == 0x000A:
                _need(data, 0, True)
                depth -= 1
                if not depth:
                    if pending is not None:
                        raise InvalidDocumentError('missing formula STRING result')
                    break
                continue
            if depth != 1 or sheet is None:
                continue
            if pending is not None:
                if code in (0x04BC, 0x0221, 0x0236):
                    continue  # Shared/array/table definition may intervene.
                if code != 0x0207:
                    raise InvalidDocumentError('missing formula STRING result')
                value, pos = self.string(data, pos, end, rich=False)
                self.add(sheet, seen, *pending, value, 'string', True, charged=True)
                pending = None
                continue
            if code == 0x0207:
                raise InvalidDocumentError('orphan formula STRING record')
            if code == 0x0200:
                _need(data, 14, True)
                r0, r1, c0, c1 = struct.unpack_from('<IIHH', data)
                if r0 > r1 or c0 > c1 or r1 > 65536 or c1 > 256:
                    raise InvalidDocumentError('invalid XLS DIMENSIONS')
                if r1 > self.limits.max_rows or c1 > self.limits.max_columns:
                    raise LimitExceededError('XLS dimensions limit exceeded')
                # Extents are derived from actual sparse cells and merges.
            elif code == 0x00E5:
                _need(data, 2)
                count = struct.unpack_from('<H', data)[0]
                _need(data, 2 + 8 * count, True)
                self.merges += count
                if self.cells + self.merges > self.limits.max_cells:
                    raise LimitExceededError('XLS merge count limit exceeded')
                for at in range(2, len(data), 8):
                    r0, r1, c0, c1 = struct.unpack_from('<HHHH', data, at)
                    if r0 > r1 or c0 > c1:
                        raise InvalidDocumentError('reversed XLS merge range')
                    self.coords(r0, c0)
                    self.coords(r1, c1)
                    sheet.merges.append(CellRange(r0 + 1, c0 + 1, r1 + 1, c1 + 1))
                    sheet.rows, sheet.columns = max(sheet.rows, r1 + 1), max(sheet.columns, c1 + 1)
            elif code in (0x00BD, 0x00BE):
                _need(data, 6)
                row, first = struct.unpack_from('<HH', data)
                last = struct.unpack_from('<H', data, len(data) - 2)[0]
                width = 6 if code == 0x00BD else 2
                if last < first:
                    raise InvalidDocumentError('reversed multi-cell range')
                _need(data, 6 + (last - first + 1) * width, True)
                for col in range(first, last + 1):
                    at = 4 + (col - first) * width
                    xf = struct.unpack_from('<H', data, at)[0]
                    value = _rk(data[at + 2:at + 6]) if width == 6 else None
                    self.add(sheet, seen, row, col, xf, value, 'number' if width == 6 else 'empty')
            elif code in (0x0203, 0x027E, 0x00FD, 0x0204, 0x0205, 0x0201, 0x0006):
                _need(data, 6)
                row, col, xf = struct.unpack_from('<HHH', data)
                value, kind, charged = None, 'empty', False
                if code == 0x0203:
                    _need(data, 14, True)
                    value, kind = struct.unpack_from('<d', data, 6)[0], 'number'
                elif code == 0x027E:
                    _need(data, 10, True)
                    value, kind = _rk(data[6:]), 'number'
                elif code == 0x00FD:
                    _need(data, 10, True)
                    index = struct.unpack_from('<I', data, 6)[0]
                    if index >= len(self.sst):
                        raise InvalidDocumentError('invalid LABELSST index')
                    value, kind = self.sst[index], 'string'
                elif code == 0x0204:
                    value, pos = self.string(data[6:], pos, end, rich=False)
                    kind, charged = 'string', True
                elif code == 0x0205:
                    _need(data, 8)
                    if len(data) > 9 or data[7] not in (0, 1):
                        raise InvalidDocumentError('invalid BOOLERR')
                    value, kind = self.special(data[6], bool(data[7]))
                elif code == 0x0201:
                    _need(data, 6, True)
                elif code == 0x0006:
                    _need(data, 22)
                    _need(data, 22 + struct.unpack_from('<H', data, 20)[0])
                    self.warn(diagnostic_warning('xls_formula_expressions_are_not_decoded_or_executed_cached_results', 'Formula expressions are not decoded or executed; cached results may be stale.'))
                    if data[12:14] == b'\xff\xff':
                        tag = data[6]
                        if tag == 0:
                            self.coords(row, col)
                            pending = (row, col, xf)
                            continue
                        if tag in (1, 2):
                            value, kind = self.special(data[8], tag == 2)
                        elif tag == 3:
                            value, kind = '', 'string'
                        else:
                            raise InvalidDocumentError('invalid formula cache type')
                    else:
                        value, kind = struct.unpack_from('<d', data, 6)[0], 'number'
                self.add(sheet, seen, row, col, xf, value, kind, code == 6, charged)
        if sheet is not None:
            sheet.cells.sort(key=lambda cell: (cell.row, cell.column))

    @staticmethod
    def special(value, error):
        if error:
            if value not in ERRORS:
                raise InvalidDocumentError('invalid XLS error value')
            return ERRORS[value], 'error'
        if value not in (0, 1):
            raise InvalidDocumentError('invalid XLS boolean value')
        return bool(value), 'boolean'


def _parse_workbook(data: bytes, limits: Limits, *, display_locale=None) -> Document:
    """Internal stream entry, also used for synthetic protocol tests."""
    if len(data) > limits.max_stream_bytes:
        raise LimitExceededError('XLS stream size limit exceeded')
    return _Parser(data, limits, display_locale=display_locale).parse()


def parse_xls_bytes(data: bytes, limits: Limits, *, display_locale=None) -> Document:
    with open_ole(data, limits) as ole:
        name = 'Workbook' if ole.exists('Workbook') else 'Book'
        stream = read_stream(ole, name, limits)
    return _parse_workbook(stream, limits, display_locale=display_locale)
