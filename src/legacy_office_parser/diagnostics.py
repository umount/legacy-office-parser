"""Stable diagnostic identifiers attached at the point a warning is emitted."""
from dataclasses import dataclass
import re


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    message: str


class CodedWarning(str):
    """A string-compatible warning that carries its code across process boundaries."""
    __slots__ = ('_code',)

    def __new__(cls, code: str, message: str):
        if not isinstance(code, str) or not re.fullmatch(r'[a-z][a-z0-9_]*', code):
            raise ValueError('invalid diagnostic code')
        if not isinstance(message, str):
            raise TypeError('warning message must be a string')
        result = super().__new__(cls, message)
        object.__setattr__(result, '_code', code)
        return result

    @property
    def code(self):
        return self._code

    def __setattr__(self, name, value):
        raise AttributeError('warning codes are immutable')

    def __delattr__(self, name):
        raise AttributeError('warning codes are immutable')

    def __reduce__(self):
        return type(self), (self.code, str(self))


def diagnostic_warning(code: str, message: str) -> CodedWarning:
    return CodedWarning(code, message)


def diagnostics_for(warnings: list[str]) -> list[Diagnostic]:
    """Retain first encounter order; this is not an occurrence count or severity."""
    result, seen = [], set()
    for message in warnings:
        code = message.code if isinstance(message, CodedWarning) else 'unclassified_warning'
        key = code, str(message)
        if key not in seen:
            result.append(Diagnostic(*key))
            seen.add(key)
    return result
