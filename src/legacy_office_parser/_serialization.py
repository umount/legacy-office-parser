"""Iterative copying of the model's dataclass/list/dict/scalar trees.

Only active ancestors are tracked: repeated acyclic references are copied once
per occurrence, not shared in the result. Work and output size therefore follow
the expanded tree, not the number of distinct source objects. No additional
serialization limit is imposed. Callers must not mutate the input during a copy.
This module does not validate model semantics or make downstream JSON encoders
iterative. Unsupported values/keys raise TypeError; cycles raise
InvalidDocumentError without including source values in the diagnostic.
"""
from dataclasses import fields, is_dataclass

from .errors import InvalidDocumentError


def _omit_defaults(result):
    """Apply the legacy Document.to_dict dict_factory, in its original order."""
    if result.get('kind') == 'paragraph' and result.get('heading_level') is None:
        result.pop('heading_level', None)
    if 'row_span' in result:
        if not result.get('blocks'):
            result.pop('blocks', None)
        if not result.get('omitted'):
            result.pop('omitted', None)
    if 'reply_depth' in result and result['reply_depth'] is None:
        result.pop('reply_depth')
        if result.get('parent_ordinal') is None:
            result.pop('parent_ordinal', None)
    if 'comments' in result and not result['comments']:
        result.pop('comments')
    if 'drawings' in result and not result['drawings']:
        result.pop('drawings')
    if 'format' in result:
        if not result.get('story_blocks'):
            result.pop('story_blocks', None)
        if not result.get('notes'):
            result.pop('notes', None)
        if not result.get('comment_text'):
            result.pop('comment_text', None)


def _scalar(value):
    # Literal/str-enum values stay values; never stringify or coerce them.
    return value is None or isinstance(value, (str, bool, int, float))


def _copy_tree(obj, *, clone):
    active = set()
    stack = []

    def enter(source):
        if _scalar(source):
            return source
        if id(source) in active:
            raise InvalidDocumentError('Cyclic output model')
        if is_dataclass(source) and not isinstance(source, type):
            kind = 'model'
            # Do not invoke constructors or __post_init__: this is a field copy,
            # including init=False fields, not a second validation/conversion.
            target = object.__new__(type(source)) if clone else {}
            children = ((f.name, getattr(source, f.name)) for f in fields(source))
        elif isinstance(source, list):
            kind = 'list'
            target = []
            children = enumerate(source)
        elif isinstance(source, dict):
            kind = 'dict'
            target = {}
            children = iter(source.items())
        else:
            raise TypeError('Output model must contain dataclasses, lists, dicts, or scalars')
        active.add(id(source))
        # Keep source alive as well as its identity for the whole active frame.
        stack.append((source, target, kind, children))
        return target

    result = enter(obj)
    while stack:
        source, target, kind, children = stack[-1]
        try:
            key, value = next(children)
        except StopIteration:
            if kind == 'model' and not clone:
                _omit_defaults(target)
            active.remove(id(source))
            stack.pop()
            continue
        if kind == 'dict' and not _scalar(key):
            raise TypeError('Output model dictionary keys must be scalars')
        copied = enter(value)
        if kind == 'list':
            target.append(copied)
        elif kind == 'model' and clone:
            object.__setattr__(target, key, copied)
        else:
            target[key] = copied
    return result


def model_to_dict(obj):
    """Copy model trees to dict/list/scalars, preserving field and key order.

    Omission rules apply only to dataclass nodes, exactly as the old asdict
    dict_factory did; ordinary dictionaries are not treated as model records.
    Cycles are rejected even through fields that would otherwise be omitted.
    """
    return _copy_tree(obj, clone=False)


def clone_model(obj):
    """Copy model trees without omissions, retaining each dataclass's type.

    Mutable dataclasses, lists and dictionaries are independent at every output
    occurrence, including when the input reuses the same acyclic object. Frozen
    and slotted dataclasses and init=False fields are copied without constructors.
    Immutable scalar values (None, str, bool, int, float) are retained as-is.
    """
    return _copy_tree(obj, clone=True)
