"""Extract binary Office documents without a running office suite."""
from .api import parse, parse_doc, parse_ppt
from .errors import (ParseError, InvalidDocumentError, UnsupportedFormatError,
                     EncryptedDocumentError, LimitExceededError)
from .limits import Limits
from .models import Document, Paragraph, Table, Cell, Slide

__version__ = '0.1.0'
__all__ = ['parse', 'parse_doc', 'parse_ppt', 'Limits', 'Document', 'Paragraph',
           'Table', 'Cell', 'Slide', 'ParseError', 'InvalidDocumentError',
           'UnsupportedFormatError', 'EncryptedDocumentError', 'LimitExceededError']
