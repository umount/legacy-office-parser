"""Bounded numeric display subset, not an Excel format interpreter.

Return None for unsupported syntax; never strip literals into executable tokens.
See docs/research-xls-formats.md for grammar, rounding, bounds and provenance.
"""
from __future__ import annotations

import re
import operator
from decimal import Context, Decimal, ROUND_FLOOR, ROUND_HALF_UP, localcontext


BUILTIN_NUMERIC = {
    0: 'General', 1: '0', 2: '0.00', 3: '#,##0', 4: '#,##0.00',
    9: '0%', 10: '0.00%', 11: '0.00E+00',
    12: '# ?/?', 13: '# ??/??',
}
MAX_FORMAT_LENGTH = 64
_COLOR = re.compile(r'\[(?:Black|Blue|Cyan|Green|Magenta|Red|White|Yellow)\]', re.I)
# MS-XLS 2.4.126 NFPartCondNum, restricted to an ASCII, finite binary64
# threshold and at most three exponent digits. Never use eval or ambient Decimal
# arithmetic to interpret conditions.
_CONDITION = re.compile(r'\[(<=|>=|<>|<|>|=)(-?[0-9]+(?:\.[0-9]+)?(?:E[+-][0-9]{1,3})?)\]')
_COMPARE = {'<': operator.lt, '<=': operator.le, '>': operator.gt,
            '>=': operator.ge, '=': operator.eq, '<>': operator.ne}
_MAX_THRESHOLD = Decimal('1.7976931348623157E+308')
_MIN_THRESHOLD = Decimal('5E-324')
_FIXED = re.compile(r'(0|#,##0)(?:\.(0{1,15}#{0,14}|#{1,15}))?(,{0,63})(%)?')
# Deliberate evidence-backed whitelist, not a general locale interpreter.
_CURRENCY = {'[$$-409]': '$', '[$€-407]': '€', '[$USD-409]': 'USD'}
# Fixed, unreduced fractions only; no best-fit denominator or layout placeholders.
# MS-XLS 2.4.126; reference probes/bounds: docs/research-xls-fractions.md.
_FRACTION = re.compile(r'(0 )?(0{1,3})/([1-9][0-9]{0,2})')
_VARIABLE_FRACTIONS = {'# ?/?': 1, '# ??/??': 2}
_FRACTION_MAX_VALUE = Decimal('1000000')
_FRACTION_MIDPOINT_GUARD = Decimal('1e-12')
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


def _numeric_parts(code: str, *, allow_literal: bool = False) -> tuple[str, str, str] | None:
    """Split explicit affixes from one contiguous core; never join split masks.

    Quotes (including empty pairs) enclose verbatim text; outside quotes a
    backslash consumes exactly one literal character. Bare signs/parentheses
    are affixes; scientific exponent signs are consumed with the numeric core.
    """
    prefix, suffix = [], []
    core = None
    bare_affix = False
    currency = False
    pos = 0
    while pos < len(code):
        char = code[pos]
        if char == '"':
            end = code.find('"', pos + 1)
            if end < 0:
                return None
            literal = code[pos + 1:end]
            pos = end + 1
        elif char == '\\':
            if pos + 1 == len(code):
                return None
            literal = code[pos + 1]
            pos += 2
        elif char == '[':
            token = next((tag for tag in _CURRENCY if code.startswith(tag, pos)), None)
            if token is None or currency:
                return None
            literal = _CURRENCY[token]
            currency = True
            pos += len(token)
        elif char in '+-()':
            literal = char
            bare_affix = True
            pos += 1
        else:
            if core is not None:
                return None
            match = (_FRACTION.match(code, pos) or _SCIENTIFIC.match(code, pos)
                     or _FIXED.match(code, pos))
            if match is None:
                return None
            core = match.group()
            pos = match.end()
            continue
        (prefix if core is None else suffix).append(literal)
    if core is None:
        if not allow_literal or bare_affix or not ''.join(prefix):
            return None
        core = ''
    fixed = _FIXED.fullmatch(core)
    if currency and (fixed is None or fixed.group(4)):
        return None
    if fixed is not None:
        _, fraction, commas, percent = fixed.groups()
        optional_only = bool(fraction and fraction.startswith('#'))
        # Optional-only decimals may scale OR use percent, but not currency.
        # Their integral-after-rounding ambiguity is checked by the renderer.
        if optional_only and currency:
            return None
        if len(fraction or '') > 15 or (percent and (
                commas or ('#' in (fraction or '') and not optional_only))):
            return None
    return ''.join(prefix), core, ''.join(suffix)


def _split_sections(code: str) -> list[str] | None:
    """Bounded split with the same quote/escape rules as numeric affixes."""
    if not code or len(code) > MAX_FORMAT_LENGTH:
        return None
    sections = []
    start = pos = 0
    while pos < len(code):
        char = code[pos]
        if char == '"':
            end = code.find('"', pos + 1)
            if end < 0:
                return None
            pos = end + 1
        elif char == '\\':
            if pos + 1 == len(code):
                return None
            pos += 2
        elif char == ';':
            sections.append(code[start:pos])
            if len(sections) == 4:
                return None
            pos += 1
            start = pos
        else:
            pos += 1
    sections.append(code[start:])
    return sections


def _text_parts(section: str, *, literal_only: bool = False) -> tuple[str, str] | None:
    """Quoted/escaped literals with one @, or no @ in literal-only mode."""
    prefix, suffix = [], []
    placeholder = False
    pos = 0
    while pos < len(section):
        char = section[pos]
        if char == '@':
            if placeholder or literal_only:
                return None
            placeholder = True
            pos += 1
            continue
        if char == '"':
            end = section.find('"', pos + 1)
            if end < 0:
                return None
            literal = section[pos + 1:end]
            pos = end + 1
        elif char == chr(92) and pos + 1 < len(section):
            literal = section[pos + 1]
            pos += 2
        else:
            return None
        (suffix if placeholder else prefix).append(literal)
    return (''.join(prefix), ''.join(suffix)) if placeholder or literal_only else None


def _with_affixes(text: str, prefix: str, suffix: str) -> str:
    # The implicit single-section minus precedes the whole display, including
    # its literal prefix. Use the rendered sign so rounded zero stays unsigned.
    if text.startswith('-'):
        return '-' + prefix + text[1:] + suffix
    return prefix + text + suffix


def _render_fraction(number: Decimal, match: re.Match) -> str | None:
    """Nearest fixed-denominator display in the caller's private Decimal context.

    Exact/near ties are intentionally unsupported: Calc probes disagree on tie
    direction, and the primary text does not define a universal tie rule.
    A conservative magnitude bound keeps numerator arithmetic below 10**9.
    """
    magnitude = number.copy_abs()
    if magnitude > _FRACTION_MAX_VALUE:
        return None
    mixed, zeros, denominator_text = match.groups()
    denominator = int(denominator_text)
    scaled = magnitude * denominator
    floor = scaled.to_integral_value(rounding=ROUND_FLOOR)
    if abs(scaled - floor - Decimal('0.5')) <= (
            _FRACTION_MIDPOINT_GUARD * max(Decimal(1), scaled)):
        return None
    numerator = int(scaled.to_integral_value(rounding=ROUND_HALF_UP))
    sign = '-' if number.is_signed() and numerator else ''
    whole = ''
    if mixed:
        integer, numerator = divmod(numerator, denominator)
        whole = str(integer) + ' '
    return sign + whole + str(numerator).zfill(len(zeros)) + '/' + denominator_text



def _render_variable_fraction(value: int | float, width: int) -> str | None:
    """Recognize small rationals encoded by the stored binary64 value.

    General best-fit rounding remains unproven: Microsoft's worked examples
    differ from nearest-rational Calc output. Here a candidate must round back
    to the identical stored value, not merely be nearest to it. Denominators
    are bounded by 9/99; at most 198 integer-division candidates are checked.
    """
    number = Decimal(str(value))
    magnitude = number.copy_abs()
    if not number.is_finite() or magnitude > _FRACTION_MAX_VALUE:
        return None
    stored = abs(value)
    source_numerator, source_denominator = stored.as_integer_ratio()
    candidate = None
    for denominator in range(1, 10 ** width):
        lower = source_numerator * denominator // source_denominator
        for numerator in (lower, lower + 1):
            if numerator / denominator == stored:
                candidate = numerator, denominator
                break
        if candidate is not None:
            break
    if candidate is None:
        return None
    # Increasing denominator order selects reduced form. Distinct rationals
    # with denominators <=99 differ by >=1/9801, far more than a binary64 ULP
    # below the magnitude cap, so two distinct candidates cannot round here.
    numerator, denominator = candidate
    whole, numerator = divmod(numerator, denominator)
    sign = '-' if number.is_signed() and magnitude else ''
    if not numerator:
        # The separator, numerator, slash and denominator all retain alignment
        # spaces for an integer. Zero itself remains visible.
        return sign + str(whole) + ' ' * (2 * width + 2)
    return (sign + (str(whole) if whole else '') + ' '
            + str(numerator).rjust(width) + '/' + str(denominator).ljust(width))


def render_number(value: int | float, code: str, *, _for_text: bool = False) -> str | None:
    """Render a finite BIFF number without altering its stored Python value.

    Decimal uses the shortest round-trip string, with explicit half-up rounding.
    A private context avoids ambient decimal precision/traps/rounding settings.
    Precision 340 covers finite binary64 fixed output plus percent and 15 places.
    """
    if code in _VARIABLE_FRACTIONS:
        return _render_variable_fraction(value, _VARIABLE_FRACTIONS[code])
    sections = _split_sections(code)
    if sections is None:
        return None
    text_section = ''
    if len(sections) == 4:
        text_section = sections.pop()
        if (_text_parts(text_section) is None
                and _text_parts(text_section, literal_only=True) is None):
            return None
    has_empty = '' in sections
    parsed = []
    conditions = []
    for index, section in enumerate(sections):
        if section == '':
            parsed.append(('', '', ''))
            conditions.append(None)
            continue
        color = _COLOR.match(section)
        if color:
            section = section[color.end():]
        condition = _CONDITION.match(section)
        if condition:
            if index > 1:
                return None
            op, threshold_text = condition.groups()
            threshold = Decimal(threshold_text)
            magnitude = threshold.copy_abs()
            if magnitude > _MAX_THRESHOLD or (magnitude and magnitude < _MIN_THRESHOLD):
                return None
            # Do not choose between decimal-exact and binary64-rounded branch
            # selection for an overprecise threshold. Accept only values equal
            # to their binary64 shortest-round-trip decimal representation.
            # Decimal(string), float conversion and finite Decimal comparison
            # do not round through or mutate the caller's Decimal context.
            if threshold != Decimal(str(float(threshold))):
                return None
            conditions.append((op, threshold))
            section = section[condition.end():]
            # Excel's custom-format guidance and Calc XLS export also place the
            # one color token after the condition. Do not accept duplicates.
            if color is None:
                color = _COLOR.match(section)
                if color:
                    section = section[color.end():]
        else:
            conditions.append(None)
        if section.lower() == 'general':
            parts = ('', 'General', '')
        else:
            parts = _numeric_parts(section, allow_literal=index == 2)
        if parts is None:
            return None
        if _for_text:
            # Numeric scaling support must not broaden fourth-section string
            # helpers via their -1/0/1 probes. These cores were unsupported
            # for strings before optional-decimal scaling was introduced.
            fixed = _FIXED.fullmatch(parts[1])
            if fixed is not None:
                _, fraction, commas, percent = fixed.groups()
                if fraction and fraction.startswith('#') and (commas or percent):
                    return None
        parsed.append(parts)

    # Validate the complete format before routing, including unused sections.
    # Deliberately exclude mixed implicit/explicit three-section routing and a
    # condition in section two alone: importers disagree on these combinations.
    conditional = any(condition is not None for condition in conditions)
    if conditional:
        # Fraction/condition interactions are not part of the verified subset.
        if any(_FRACTION.fullmatch(core) for _, core, _ in parsed):
            return None
        if text_section not in ('', '@'):
            return None
        if has_empty:
            return None
        if conditions[0] is None or (len(parsed) == 3 and conditions[1] is None):
            return None
        # The MS-XLS single-section conditional production is General only.
        if len(parsed) == 1 and parsed[0][1] != 'General':
            return None
        number = Decimal(str(value))
        if not number.is_finite():
            return None
        # INCOMPLETE: MS-XLS 2.4.126 specifies condition syntax and delegates
        # display semantics to ECMA-376 18.8.31. The consulted primary text does
        # not establish conditional negative-sign handling. Calc observations
        # are not a normative rule for arbitrary Excel formats. Reject EVERY
        # negative conditional value, including General and literal fallbacks,
        # rather than extrapolating a sign whitelist from finite probes.
        # Signed zero still follows numeric zero routing; its raw bits survive.
        if number < 0:
            return None
        selected = None
        for index, condition in enumerate(conditions):
            if condition is None or _COMPARE[condition[0]](number, condition[1]):
                selected = index
                break
        if selected is None:
            # Excel's unmatched display is width-dependent hashes. Keep the raw
            # value and warn instead of inventing text or an implicit General.
            return None
        if (not number and len(parsed) == 2 and conditions[1] is None
                and conditions[0] == ('>', Decimal(0))):
            # Calc normalizes this to ordinary sign sections (zero goes first),
            # contrary to literal predicate selection. Do not guess at zero.
            return None
    else:
        # Route on the stored value, before rounding. Both signed zeros use zero.
        selected = 1 if value < 0 and len(parsed) > 1 else (
            2 if value == 0 and len(parsed) == 3 else 0
        )
        if selected == 1:
            value = abs(value)
    prefix, core, suffix = parsed[selected]
    if core == 'General':
        # Width-independent whole-number subset. Larger General displays can
        # switch to scientific notation; retain their existing raw projection.
        if abs(value) < 100_000_000_000 and value == int(value):
            return str(int(value))
        return str(value)
    fixed = _FIXED.fullmatch(core)
    scientific = _SCIENTIFIC.fullmatch(core)
    fraction_format = _FRACTION.fullmatch(core)
    with localcontext(Context(prec=340, rounding=ROUND_HALF_UP)):
        number = Decimal(str(value))
        if not number.is_finite():
            return None
        if not core:  # Empty section or explicit literal-only third section.
            return prefix
        if fraction_format is not None:
            text = _render_fraction(number, fraction_format)
            return None if text is None else _with_affixes(text, prefix, suffix)
        if fixed is not None:
            integer, fraction, commas, percent = fixed.groups()
            places = len(fraction or '')
            # Scale before rounding; scaleb is exact within the private context.
            number = number.scaleb(-3 * len(commas))
            if percent:
                number *= 100
            number = number.quantize(Decimal(1).scaleb(-places))
            # Without mandatory decimals, integral results have an unresolved
            # decimal-point display. Keep fallback for zero and rounding carry.
            if fraction and fraction.startswith('#') and number == number.to_integral_value():
                return None
            if not number:
                number = number.copy_abs()
            grouping = ',' if integer == '#,##0' else ''
            text = format(number, f'{grouping}.{places}f')
            optional = (fraction or '').count('#')
            if optional:
                removable = min(optional, len(text) - len(text.rstrip('0')))
                if removable:
                    text = text[:-removable]
            text += '%' if percent else ''
            return _with_affixes(text, prefix, suffix)
        fraction, letter, sign, zeros = scientific.groups()
        places = len(fraction or '')
        mantissa, exponent = format(number, f'.{places}E').split('E')
        power = int(exponent) if number else 0
        if not number:
            mantissa = format(Decimal(0), f'.{places}f')
        exponent_sign = '-' if power < 0 else ('+' if sign == '+' else '')
        text = mantissa + letter + exponent_sign + str(abs(power)).zfill(len(zeros))
        return _with_affixes(text, prefix, suffix)


def hides_text(code: str) -> bool:
    """Only a validated, unconditional format with an empty fourth section.

    Validate every numeric branch; a blank text section must not legitimize
    unsupported syntax elsewhere. The bounded renderer never executes fields.
    """
    sections = _split_sections(code)
    return (sections is not None and len(sections) == 4 and sections[-1] == ''
            and all(render_number(value, code, _for_text=True) is not None for value in (-1, 0, 1)))


def text_affixes(code: str) -> tuple[str, str] | None:
    """Return affixes only for a fully validated ordinary four-section mask.

    Negative conditional values remain unsupported, so validating all three
    signs also excludes conditional routing without interpreting string signs.
    The caller charges expansion before concatenating the retained string.
    """
    sections = _split_sections(code)
    if sections is None or len(sections) != 4:
        return None
    parts = _text_parts(sections[-1])
    if parts is None or not all(render_number(value, code, _for_text=True) is not None
                                for value in (-1, 0, 1)):
        return None
    return parts


def text_literal(code: str) -> str | None:
    """A bounded literal-only fourth section in a validated ordinary format."""
    sections = _split_sections(code)
    if sections is None or len(sections) != 4:
        return None
    parts = _text_parts(sections[-1], literal_only=True)
    if parts is None or not all(render_number(value, code, _for_text=True) is not None
                                for value in (-1, 0, 1)):
        return None
    return parts[0]
