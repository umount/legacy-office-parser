"""Stable errors callers can classify without inspecting document content."""
class ParseError(ValueError):
    """The file cannot be read as a supported document."""
class InvalidDocumentError(ParseError):
    pass
class UnsupportedFormatError(ParseError):
    pass
class EncryptedDocumentError(ParseError):
    pass
class LimitExceededError(ParseError):
    pass
