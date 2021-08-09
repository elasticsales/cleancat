import functools
import itertools
import typing
from typing import Dict, TypeVar, Type, Any, Union

from cleancat.chausie.consts import omitted, empty
from cleancat.chausie.field import (
    Field,
    FIELD_TYPE_MAP,
    ValidationError,
    Error,
    Value,
    simple_field,
    Optional as CCOptional,
    UnvalidatedWrappedValue,
)


def getter(dict_or_obj, field, default):
    if isinstance(dict_or_obj, dict):
        return dict_or_obj.get(field, default)
    else:
        getattr(dict_or_obj, field, default)


SchemaCls = TypeVar('SchemaCls')


def get_fields(cls: Type[SchemaCls]) -> Dict[str, Field]:
    return {
        field_name: field_def
        for field_name, field_def in cls.__dict__.items()
        if isinstance(field_def, Field)
    }


def _field_def_from_annotation(annotation) -> Field:
    """Turn an annotation into an equivalent simple_field."""
    if annotation in FIELD_TYPE_MAP:
        return simple_field(parents=(FIELD_TYPE_MAP[annotation],))
    elif typing.get_origin(annotation) is Union:
        # basic support for `Optional`
        union_of = typing.get_args(annotation)
        if not (len(union_of) == 2 and type(None) in union_of):
            raise TypeError('Unrecognized type annotation.')

        inner = next(
            t for t in typing.get_args(annotation) if t is not type(None)
        )
        if inner in FIELD_TYPE_MAP:
            return simple_field(
                parents=(FIELD_TYPE_MAP[inner],),
                nullability=CCOptional(),
            )

    raise TypeError('Unrecognized type annotation.')


def _clean(
    cls: Type[SchemaCls], data: Any, context: Any
) -> Union[SchemaCls, ValidationError]:
    """Entrypoint for cleaning some set of data for a given class."""
    field_defs = [(name, f_def) for name, f_def in get_fields(cls).items()]

    # initial set are those with no
    eval_queue: typing.List[typing.Tuple[str, Field]] = []
    delayed_eval = []
    for name, f in field_defs:
        if f.depends_on:
            delayed_eval.append((name, f))
        else:
            eval_queue.append((name, f))
    assert len(field_defs) == len(eval_queue) + len(delayed_eval)

    results: Dict[str, Union[Value, Error]] = {}
    while eval_queue:
        field_name, field_def = eval_queue.pop()

        accepts = field_def.accepts or (field_name,)
        value = empty
        for accept in accepts:
            value = getter(data, accept, omitted)
            if value is not omitted:
                break
        assert value is not empty

        results[field_name] = field_def.run_validators(
            field=(field_name,),
            value=value,
            context=context,
            intermediate_results=results,
        )

        queued_fields = {n for n, _f in eval_queue}
        for name, f in delayed_eval:
            if (
                name not in results
                and name not in queued_fields
                and all(
                    [
                        (dep in results and isinstance(results[dep], Value))
                        for dep in f.depends_on
                    ]
                )
            ):
                eval_queue.append((name, f))

    errors = list(
        itertools.chain(
            *[
                v.flatten()
                for v in results.values()
                if not isinstance(v, Value)
            ]
        )
    )
    if errors:
        return ValidationError(errors=errors)

    return cls(**{k: v.value for k, v in results.items()})


def _new_init(self: SchemaCls, **kwargs):
    defined_fields = get_fields(self.__class__)
    attribs = {k: v for k, v in kwargs.items() if k in defined_fields}
    for k, v in attribs.items():
        setattr(self, k, v)


def _serialize(self: SchemaCls):
    """Serialize a schema to a dictionary, respecting serialization settings."""
    return {
        (field_def.serialize_to or field_name): field_def.serialize_func(
            getattr(self, field_name)
        )
        for field_name, field_def in get_fields(self.__class__).items()
    }


def _check_for_dependency_loops(cls: Type[SchemaCls]) -> None:
    deps = {
        name: set(f_def.depends_on) for name, f_def in get_fields(cls).items()
    }
    seen = set()
    while deps:
        prog = len(seen)
        for f_name, f_deps in deps.items():
            if not f_deps or all([f_dep in seen for f_dep in f_deps]):
                seen.add(f_name)
                deps.pop(f_name)
                break

        if len(seen) == prog:
            # no progress was made
            raise ValueError('Field dependencies could not be resolved.')


def schema(cls: Type[SchemaCls], autodef=True):
    """
    Annotate a class to turn it into a schema.

    Args:
        autodef: automatically define simple fields for annotated attributes
    """
    # auto define simple annotations
    if autodef:
        existing_fields = get_fields(cls)
        for field, f_type in getattr(cls, '__annotations__', {}).items():
            if field not in existing_fields:
                setattr(cls, field, _field_def_from_annotation(f_type))

    # check for dependency loops
    _check_for_dependency_loops(cls)

    cls.__clean = functools.partial(_clean, cls=cls)
    cls.__init__ = _new_init
    cls.__serialize = _serialize

    return cls


def clean(
    schema: Type[SchemaCls], data: Any, context: Any = empty
) -> SchemaCls:
    return schema.__clean(data=data, context=context)


def serialize(schema: SchemaCls) -> Dict:
    return schema.__serialize()