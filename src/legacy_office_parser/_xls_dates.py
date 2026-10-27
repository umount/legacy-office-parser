"""Bounded XLS date recognition and elapsed display, independent of numeric rendering.

Calendar/clock values retain the legacy normalized ISO value == text contract.
Elapsed formats retain the serial as a number and render only text. No locale
names, source calendar display, numeric section selection, or formula evaluation occurs.

Grammar references: Microsoft 'Format numbers as dates or times', 'Review
 guidelines for customizing a number format', and Open XML NumberingFormat
(built-ins 14-22, 45-47). See docs/OUTPUT_FORMAT.md for legacy ISO semantics.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Context, Decimal, ROUND_DOWN, ROUND_HALF_UP, localcontext
import math
import re
from typing import Literal

from ._xls_formats import _split_sections, _text_parts


MAX_FORMAT_LENGTH = 64
MAX_ELAPSED_DAYS = 2958465
BUILTIN_DATE = {
    14: 'mm-dd-yy', 15: 'd-mmm-yy', 16: 'd-mmm', 17: 'mmm-yy',
    18: 'h:mm AM/PM', 19: 'h:mm:ss AM/PM', 20: 'h:mm',
    21: 'h:mm:ss', 22: 'm/d/yy h:mm', 45: 'mm:ss',
    46: '[h]:mm:ss', 47: 'mmss.0',
}
# Only ordinary locale tags with known Gregorian defaults. Do not silently
# consume calendar modifiers, currency tags, or system-dependent F400/F800.
_LOCALES = {'409', '809', '407', '40c', '419'}
_COLOR = re.compile(r'\[(?:black|blue|cyan|green|magenta|red|white|yellow)\]', re.I)
_TOKEN = re.compile(r'am/pm|a/p|y+|m+|d+|h+|s+', re.I)
_SIZES = {'y': (2, 4), 'm': (1, 2, 3, 4, 5), 'd': (1, 2, 3, 4),
          'h': (1, 2), 's': (1, 2)}
Status = Literal['ok', 'unsupported', 'unrepresentable', 'out_of_range']
CellResult = tuple[float | str, str, str]


@dataclass(frozen=True)
class DateResult:
    """Result always contains a cell triple, including raw numeric fallback.

    `status` maps to the parent's existing diagnostic categories. `reason` is
    explanatory internal text, not a public diagnostic code.
    """

    status: Status
    result: CellResult
    reason: str | None = None


def _tokens(code: str) -> list[tuple[str, str]] | None:
    if not code or len(code) > MAX_FORMAT_LENGTH:
        return None
    tokens = []
    pos = 0
    locale_seen = color_seen = False
    while pos < len(code):
        char = code[pos]
        if char == '"':
            end = code.find('"', pos + 1)
            if end < 0:
                return None
            tokens.append(('literal', code[pos + 1:end]))
            pos = end + 1
        elif char == '\\':
            if pos + 1 == len(code):
                return None
            tokens.append(('literal', code[pos + 1]))
            pos += 2
        elif char == '[':
            end = code.find(']', pos + 1)
            if end < 0:
                return None
            tag = code[pos:end + 1].lower()
            if tag in ('[h]', '[hh]', '[m]', '[mm]', '[s]', '[ss]'):
                tokens.append(('elapsed', tag[1:-1]))
            elif (tag.startswith('[$-') and tag[3:-1].lstrip('0') in _LOCALES
                  and len(tag[3:-1]) <= 4 and not locale_seen
                  and not any(k != 'literal' for k, _ in tokens)):
                locale_seen = True
            elif (_COLOR.fullmatch(tag) and not color_seen
                  and not any(k != 'literal' for k, _ in tokens)):
                color_seen = True
            else:
                return None
            pos = end + 1
        elif char == '.' and pos + 1 < len(code) and code[pos + 1] == '0':
            # Fractions must immediately follow a seconds token, not a quoted
            # suffix, and have a bounded precision independent of Decimal state.
            if not tokens or tokens[-1][0] not in ('s', 'elapsed') or not tokens[-1][1].startswith('s'):
                return None
            end = pos + 1
            while end < len(code) and code[end] == '0':
                end += 1
            if end - pos - 1 > 3:
                return None
            tokens.append(('fraction', code[pos + 1:end]))
            pos = end
        elif char in ' /:.,-':
            tokens.append(('literal', char))
            pos += 1
        else:
            match = _TOKEN.match(code, pos)
            if match is None:
                return None
            token = match.group().lower()
            kind = 'ampm' if '/' in token else token[0]
            if kind != 'ampm' and len(token) not in _SIZES[kind]:
                return None
            tokens.append((kind, token))
            pos = match.end()
    return tokens


def _elapsed(value: float, tokens: list[tuple[str, str]]) -> str | None:
    fields = [(k, t) for k, t in tokens if k != 'literal']
    if not fields or fields[0][0] != 'elapsed':
        return None
    unit = fields[0][1][0]
    rest = fields[1:]
    precision = 0
    if rest and rest[-1][0] == 'fraction':
        precision = len(rest.pop()[1])
    kinds = [k for k, _ in rest]
    allowed = {'h': ([], ['m'], ['s'], ['m', 's']), 'm': ([], ['s']), 's': ([],)}
    if kinds not in allowed[unit] or any(len(t) > 2 for _, t in rest):
        return None
    # A fractional token can only occur on seconds, as checked by _tokens.
    with localcontext(Context(prec=40)):
        seconds = Decimal(str(value)) * 86400
        # Seconds round with carry; omitted seconds/minutes truncate.
        # Confirmed with a small independent LibreOffice CSV probe.
        resolution = (Decimal(1).scaleb(-precision) if precision or unit == 's' or 's' in kinds
                      else Decimal(60) if unit == 'm' or 'm' in kinds else Decimal(3600))
        rounding = ROUND_HALF_UP if resolution <= 1 else ROUND_DOWN
        rounded = (seconds / resolution).quantize(Decimal(1), rounding=rounding) * resolution
        ticks = int(rounded * 10 ** precision)
    whole, fractional = divmod(ticks, 10 ** precision)
    rendered = []
    for kind, token in tokens:
        if kind == 'literal':
            rendered.append(token)
        elif kind == 'elapsed':
            count = whole // {'h': 3600, 'm': 60, 's': 1}[unit]
            rendered.append(str(count).zfill(len(token)))
        elif kind == 'fraction':
            rendered.append('.' + str(fractional).zfill(precision))
        else:
            count = whole // 60 % 60 if kind == 'm' else whole % 60
            rendered.append(str(count).zfill(len(token)))
    return ''.join(rendered)


def interpret_date(value: float, code: str | int, datemode: int) -> DateResult:
    """Interpret a date mask/built-in ID; return status plus a safe cell triple.

    Unsupported masks, negative serials and dates outside datetime's range
    retain `(value, 'number', str(value))`. Non-finite inputs are classified as
    out_of_range here; the public parser must still reject them as invalid XLS.
    One date/time section may be followed by a validated text section with @.
    Other multi-section masks remain unsupported, without choosing a branch.
    """
    raw = (value, 'number', str(value))

    def fallback(status: Status, reason: str) -> DateResult:
        return DateResult(status, raw, reason)

    if datemode not in (0, 1):
        return fallback('unsupported', 'invalid date mode')
    if isinstance(code, int):
        code = BUILTIN_DATE.get(code, '')
    # Validate the whole bounded format before ignoring a trailing text section.
    # Shared splitting preserves semicolons inside quoted/escaped literals.
    sections = _split_sections(code)
    if (sections is None or len(sections) > 2
            or (len(sections) == 2 and _text_parts(sections[1]) is None)):
        return fallback('unsupported', 'unsupported date/time sections')
    tokens = _tokens(sections[0])
    if tokens is None:
        return fallback('unsupported', 'unsupported date/time mask')
    fields = [(k, t) for k, t in tokens if k not in ('literal', 'fraction')]
    if not any(k in ('y', 'm', 'd', 'h', 's', 'elapsed') for k, _ in fields):
        return fallback('unsupported', 'no date/time fields')
    elapsed = any(k == 'elapsed' for k, _ in fields)
    if elapsed and _elapsed(0, tokens) is None:
        return fallback('unsupported', 'unsupported elapsed field combination')
    if not math.isfinite(value):
        return fallback('out_of_range', 'non-finite serial')
    if value < 0:
        return fallback('unrepresentable', 'negative date/time serial')
    if elapsed:
        if value > MAX_ELAPSED_DAYS:
            return fallback('out_of_range', 'elapsed serial exceeds bounded range')
        return DateResult('ok', (value, 'number', _elapsed(value, tokens)))
    calendar_month = any(
        k == 'm' and (len(t) > 2 or not (
            (i > 0 and fields[i - 1][0] == 'h') or
            (i + 1 < len(fields) and fields[i + 1] == ('s', 'ss'))
        )) for i, (k, t) in enumerate(fields)
    )
    time_only = (not calendar_month and not any(k in ('y', 'd') for k, _ in fields)
                 and any(k in ('h', 's') for k, _ in fields))
    if not datemode and not time_only and 60 <= value < 61:
        return fallback('unrepresentable', 'fictitious 1900 leap day')
    try:
        base = datetime(1904, 1, 1) if datemode else datetime(1899, 12, 31)
        serial = value if datemode or value < 60 else value - 1
        dt = base + timedelta(days=serial)
        if time_only:
            text = dt.time().isoformat(timespec='milliseconds').rstrip('0').rstrip('.')
        else:
            text = dt.isoformat(timespec='milliseconds').rstrip('0').rstrip('.')
            if dt.time() == datetime.min.time():
                text = dt.date().isoformat()
    except (ValueError, OverflowError):
        return fallback('out_of_range', 'date outside datetime range')
    return DateResult('ok', (text, 'date', text))
