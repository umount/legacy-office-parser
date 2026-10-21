"""Bounded numeric display subset, not an Excel format interpreter.

Return None for unsupported syntax; never strip literals into executable tokens.
See docs/research-xls-formats.md for grammar, rounding, bounds and provenance.
"""
from __future__ import annotations

import re
from decimal import Context, Decimal, ROUND_HALF_UP, localcontext


BUILTIN_NUMERIC = {
    0: 'General', 1: '0', 2: '0.00', 3: '#,##0', 4: '#,##0.00',
    9: '0%', 10: '0.00%', 11: '0.00E+00',
}
MAX_FORMAT_LENGTH = 64
_FIXED = re.compile(r'(0|#,##0)(?:\.(0{1,15}))?(%)?')
_SCIENTIFIC = re.compile(r'0(?:\.(0{1,15}))?([Ee])([+-])(0{1,3})')
_DATE_TOKEN = re.compile(
    r'am/pm|a/p|y+|m+|d+|h+|s+|[ /:.,-]+|\\[ /:.,-]|"[ /:.,-]+"', re.I,
)


def simple_date_format(code: str) -> bool:
    """Gate the legacy date recognizer: allow only date tokens and plain/quoted/escaped separators."""
    if len(code) > MAX_FORMAT_LENGTH:
        return False
    end, has_date = 0, False
    for match in _DATE_TOKEN.finditer(code.lower()):
        if match.start() != end:
            return False
        token = match.group()
        if token[0] in 'ymdhs':
            sizes = {'y': (2, 4), 'm': (1, 2, 3, 4, 5), 'd': (1, 2, 3, 4),
                     'h': (1, 2), 's': (1, 2)}
            if len(token) not in sizes[token[0]]:
                return False
            has_date = True
        end = match.end()
    return end == len(code) and has_date


def render_number(value: int | float, code: str) -> str | None:
    """Render a finite BIFF number without altering its stored Python value.

    Decimal uses the shortest round-trip string, with explicit half-up rounding.
    A private context avoids ambient decimal precision/traps/rounding settings.
    Precision 340 covers finite binary64 fixed output plus percent and 15 places.
    """
    if len(code) > MAX_FORMAT_LENGTH:
        return None
    if code.lower() == 'general':
        return str(value)
    fixed = _FIXED.fullmatch(code)
    scientific = _SCIENTIFIC.fullmatch(code)
    if fixed is None and scientific is None:
        return None
    with localcontext(Context(prec=340, rounding=ROUND_HALF_UP)):
        number = Decimal(str(value))
        if not number.is_finite():
            return None
        if fixed is not None:
            integer, fraction, percent = fixed.groups()
            places = len(fraction or '')
            if percent:
                number *= 100
            number = number.quantize(Decimal(1).scaleb(-places))
            if not number:
                number = number.copy_abs()
            grouping = ',' if integer == '#,##0' else ''
            return format(number, f'{grouping}.{places}f') + ('%' if percent else '')
        fraction, letter, sign, zeros = scientific.groups()
        places = len(fraction or '')
        mantissa, exponent = format(number, f'.{places}E').split('E')
        power = int(exponent) if number else 0
        if not number:
            mantissa = format(Decimal(0), f'.{places}f')
        prefix = '-' if power < 0 else ('+' if sign == '+' else '')
        return mantissa + letter + prefix + str(abs(power)).zfill(len(zeros))
