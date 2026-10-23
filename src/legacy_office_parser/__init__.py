"""Extract legacy Office, RTF and OpenDocument without an office runtime."""
from .api import parse, parse_doc, parse_ppt, parse_xls, parse_rtf, parse_odt, parse_ods, parse_odp
from .errors import (ParseError, InvalidDocumentError, UnsupportedFormatError,
                     EncryptedDocumentError, LimitExceededError)
from .limits import Limits
from .models import AuxiliaryStory, Document, Paragraph, Table, Cell, Slide, SlideComment, SpreadsheetCell, CellRange, Sheet, Note, NoteBodyRange, Comment, CommentBodyRange

__version__ = '0.28.0'
__all__ = ['AuxiliaryStory', 'Diagnostic', 'normalize_text', 'parse_xls', 'parse_rtf', 'parse_odt', 'parse_ods', 'parse_odp',
           'SpreadsheetCell', 'CellRange', 'Sheet', 'parse', 'parse_doc', 'parse_ppt', 'Limits', 'Document', 'Paragraph',
           'Table', 'Cell', 'Slide', 'SlideComment', 'Note', 'NoteBodyRange', 'Comment', 'CommentBodyRange', 'ParseError', 'InvalidDocumentError',
           'UnsupportedFormatError', 'EncryptedDocumentError', 'LimitExceededError']

from .normalization import normalize_text
from .diagnostics import Diagnostic
