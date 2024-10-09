import datetime
import inspect
import re
from operator import attrgetter
from uuid import UUID as PythonUUID

import pytz
from dateutil import parser

# Sentinel value which means "pick the default value" when encountered.
default_sentinel = object()


class ValidationError(Exception):
    pass


class StopValidation(Exception):
    pass


class Field:
    # If specified, the field ensures that the supplied value is an instance
    # of this type. Can be either a single specific type (e.g. int) or a tuple
    # of multiple types.
    base_type = None

    # Value to be used when there was no specific value supplied for this
    # field and the field is not required.
    blank_value = None

    def __init__(
        self,
        required=True,
        default=None,
        field_name=None,
        raw_field_name=None,
        mutable=True,
        read_only=False,
        blank_value=default_sentinel,
    ):
        """
        By default, the field name is derived from the schema model, but in
        certain cases it can be overridden. Specifying field_name overrides
        both the name of the field in the raw (unclean) data, as well as in the
        clean data model. If the raw data has a different field name than the
        clean data, raw_field_name can be overridden.
        """
        self.required = required
        self.default = default
        self.mutable = mutable
        self.field_name = field_name
        self.raw_field_name = raw_field_name or field_name
        self.read_only = read_only
        if blank_value is not default_sentinel:
            self.blank_value = blank_value

    def has_value(self, value):
        return value is not None

    def clean(self, value):
        """Take a dirty value and clean it."""
        if (
            self.base_type is not None
            and value is not None
            and not isinstance(value, self.base_type)
        ):
            if isinstance(self.base_type, tuple):
                allowed_types = [typ.__name__ for typ in self.base_type]
                allowed_types_text = " or ".join(allowed_types)
            else:
                allowed_types_text = self.base_type.__name__
            err_msg = "The value must be of %s type." % allowed_types_text
            raise ValidationError(err_msg)

        if not self.has_value(value):
            if self.default is not None:
                raise StopValidation(self.default)

            if self.required:
                raise ValidationError("This field is required.")
            else:
                raise StopValidation(self.blank_value)

        return value

    def serialize(self, value):
        """
        Takes a cleaned value and serializes it.

        Keep in mind that if this field is not required, the cleaned value
        might be None.
        """
        return value


class String(Field):
    base_type = str
    blank_value = ""
    min_length = None
    max_length = None

    def __init__(self, min_length=None, max_length=None, **kwargs):
        if min_length is not None:
            self.min_length = min_length
        if max_length is not None:
            self.max_length = max_length
        super().__init__(**kwargs)

    def _check_length(self, value):
        if self.max_length is not None and len(value) > self.max_length:
            err_msg = "The value must be no longer than %s characters." % (
                self.max_length
            )
            raise ValidationError(err_msg)

        if self.min_length is not None and len(value) < self.min_length:
            err_msg = "The value must be at least %s characters long." % (
                self.min_length
            )
            raise ValidationError(err_msg)

    def clean(self, value):
        value = super().clean(value)
        self._check_length(value)
        return value

    def has_value(self, value):
        return bool(value)


class TrimmedString(String):
    base_type = str
    blank_value = ""

    def clean(self, value):
        # XXX we skip a level of inheritance so that we can perform length
        # checks *after* trimming.
        value = super(String, self).clean(value)

        if value:
            value = value.strip()
        self._check_length(value)
        return value

    def has_value(self, value):
        return bool(value and value.strip())


class Bool(Field):
    base_type = bool
    blank_value = False


class Regex(String):
    regex = None
    regex_flags = 0
    regex_message = "Invalid input."

    def __init__(
        self, regex=None, regex_flags=None, regex_message=None, **kwargs
    ):
        super().__init__(**kwargs)
        if regex is not None:
            self.regex = regex
        if regex_flags is not None:
            self.regex_flags = regex_flags
        if regex_message is not None:
            self.regex_message = regex_message

    def get_regex(self):
        if not getattr(self, "_compiled_regex", None):
            self._compiled_regex = re.compile(self.regex, self.regex_flags)
        return self._compiled_regex

    def clean(self, value):
        value = super().clean(value)

        if not self.get_regex().match(value):
            raise ValidationError(self.regex_message)

        return value


class DateTime(Regex):
    """ISO 8601 from http://www.pelagodesign.com/blog/2009/05/20/iso-8601-date-validation-that-doesnt-suck/"""

    regex = "^([\\+-]?\\d{4}(?!\\d{2}\\b))((-?)((0[1-9]|1[0-2])(\\3([12]\\d|0[1-9]|3[01]))?|W([0-4]\\d|5[0-2])(-?[1-7])?|(00[1-9]|0[1-9]\\d|[12]\\d{2}|3([0-5]\\d|6[1-6])))([T\\s]((([01]\\d|2[0-3])((:?)[0-5]\\d)?|24\\:?00)([\\.,]\\d+(?!:))?)?(\\17[0-5]\\d([\\.,]\\d+)?)?([zZ]|([\\+-])([01]\\d|2[0-3]):?([0-5]\\d)?)?)?)?$"
    regex_message = "Invalid ISO 8601 datetime."
    blank_value = None
    _force_datetime: bool

    def __init__(self, *args, force_datetime: bool = False, **kwargs):
        """
        Args:
            force_datetime: If True, always return a datetime object, even if
                the input does not specify a time.
        """
        self.min_date = kwargs.pop("min_date", None)
        self._force_datetime = force_datetime
        super().__init__(*args, **kwargs)

    def clean(self, value):
        # XXX we're skipping a level of inheritance so that we can reuse
        # the regex match later in this method.
        value = super(Regex, self).clean(value)
        match = self.get_regex().match(value)
        if not match:
            raise ValidationError(self.regex_message)
        try:
            dt = parser.parse(value)
        except ValueError as e:
            raise ValidationError("Could not parse datetime") from e
        if self.min_date:
            if dt.tzinfo is not None and self.min_date.tzinfo is None:
                min_date = self.min_date.replace(tzinfo=pytz.utc)
            else:
                min_date = self.min_date
            if dt < min_date:
                err_msg = "Date cannot be earlier than %s." % (
                    self.min_date.strftime("%Y-%m-%d")
                )
                raise ValidationError(err_msg)

        if self._force_datetime:  # don't convert to a date
            return dt

        time_group = match.groups()[11]
        if time_group and len(time_group) > 1:
            return dt
        return dt.date()

    def serialize(self, value):
        if value is not None:
            return value.isoformat()


class Email(Regex):
    regex = (
        r"^(?:[^\.@\s]|[^\.@\s]\.(?!\.))*[^.@\s]@"
        r"[^.@\s](?:[^\.@\s]|\.(?!\.))*\.[a-z]{2,63}$"
    )
    regex_flags = re.IGNORECASE
    regex_message = "Invalid email address."
    max_length = 254

    def clean(self, value):
        # trim any leading/trailing whitespace before validating the email
        if isinstance(value, str):
            value = value.strip()
        return super().clean(value)


class URL(Regex):
    blank_value = None

    def __init__(
        self,
        require_tld=True,
        default_scheme=None,
        allowed_schemes=None,
        disallowed_schemes=None,
        **kwargs,
    ):
        def normalize_scheme(sch):
            if sch.endswith(("://", ":")):
                return sch
            return sch + "://"

        # FQDN validation similar to https://github.com/chriso/validator.js/blob/master/src/lib/isFQDN.js

        # ff01-ff5f -> full-width chars, not allowed
        alpha_numeric_and_symbols_ranges = "0-9a-z\u00a1-\uff00\uff5f-\uffff"

        tld_part = (
            require_tld
            and r"\.[%s-]{2,63}" % alpha_numeric_and_symbols_ranges
            or ""
        )
        scheme_part = "[a-z]+://"
        self.default_scheme = default_scheme
        if self.default_scheme:
            self.default_scheme = normalize_scheme(self.default_scheme)
        self.scheme_regex = re.compile("^" + scheme_part, re.IGNORECASE)
        if default_scheme:
            scheme_part = "(%s)?" % scheme_part
        regex = rf"^{scheme_part}([-{alpha_numeric_and_symbols_ranges}@:%_+.~#?&/\\=]{{1,256}}{tld_part}|([0-9]{{1,3}}\.){{3}}[0-9]{{1,3}})(:[0-9]+)?([/?].*)?$"
        super().__init__(
            regex=regex,
            regex_flags=re.IGNORECASE | re.UNICODE,
            regex_message="Invalid URL.",
            **kwargs,
        )

        def compile_schemes_to_regexes(schemes):
            return [
                re.compile("^" + normalize_scheme(sch) + ".*", re.IGNORECASE)
                for sch in schemes
            ]

        self.allowed_schemes = allowed_schemes or []
        self.allowed_schemes_regexes = compile_schemes_to_regexes(
            self.allowed_schemes
        )

        self.disallowed_schemes = disallowed_schemes or []
        self.disallowed_schemes_regexes = compile_schemes_to_regexes(
            self.disallowed_schemes
        )

    def clean(self, value):
        value = super().clean(value)
        if not self.scheme_regex.match(value):
            value = self.default_scheme + value

        if self.allowed_schemes and not any(
            allowed_regex.match(value)
            for allowed_regex in self.allowed_schemes_regexes
        ):
            allowed_schemes_text = " or ".join(self.allowed_schemes)
            err_msg = (
                "This URL uses a scheme that's not allowed. You can only "
                "use %s." % allowed_schemes_text
            )
            raise ValidationError(err_msg)

        if self.disallowed_schemes and any(
            disallowed_regex.match(value)
            for disallowed_regex in self.disallowed_schemes_regexes
        ):
            err_msg = "This URL uses a scheme that's not allowed."
            raise ValidationError(err_msg)

        return value


class RelaxedURL(URL):
    """Like URL but will just ignore values like "http://" and treat them
    as blank.
    """

    def clean(self, value):
        if not self.required and value == self.default_scheme:
            return None
        value = super().clean(value)
        return value


class Integer(Field):
    base_type = int

    def __init__(self, min_value=None, max_value=None, **kwargs):
        self.max_value = max_value
        self.min_value = min_value
        super().__init__(**kwargs)

    def _check_value(self, value):
        if self.max_value is not None and value > self.max_value:
            err_msg = "The value must not be larger than %d." % self.max_value
            raise ValidationError(err_msg)

        if self.min_value is not None and value < self.min_value:
            err_msg = "The value must be at least %d." % self.min_value
            raise ValidationError(err_msg)

    def clean(self, value):
        value = super().clean(value)
        self._check_value(value)
        return value


class List(Field):
    base_type = list
    blank_value = []

    def __init__(self, field_instance, max_length=None, **kwargs):
        self.max_length = max_length
        super().__init__(**kwargs)
        self.field_instance = field_instance

    def has_value(self, value):
        return bool(value)

    def clean(self, value):
        value = super().clean(value)

        item_cnt = len(value)
        if self.required and not item_cnt:
            raise ValidationError("List must not be empty.")

        if self.max_length and item_cnt > self.max_length:
            raise ValidationError("List is too long.")

        errors = {}
        data = []
        for n, item in enumerate(value):
            try:
                cleaned_data = self.field_instance.clean(item)
            except ValidationError as e:
                errors[n] = e.args and e.args[0]
            except StopValidation as e:
                data.append(e.args and e.args[0])
            else:
                data.append(cleaned_data)

        if errors:
            raise ValidationError({"errors": errors})

        return data

    def serialize(self, value):
        # Serialize all falsy values as an empty list.
        if not value:
            return []
        return [self.field_instance.serialize(item) for item in value]


class Dict(Field):
    base_type = dict

    def has_value(self, value):
        return bool(value)

    def serialize(self, value):
        # Serialize all falsy values as an empty dict.
        return value or {}


class Embedded(Dict):
    def __init__(self, schema_class, **kwargs):
        super().__init__(**kwargs)
        self.schema_class = schema_class

    def clean(self, value):
        value = super().clean(value)
        try:
            cleaned_value = self.schema_class(value).full_clean()
        except ValidationError as e:
            raise e
        else:
            return cleaned_value

    def is_valid(self):
        try:
            self.clean()
        except ValidationError:
            return False
        else:
            return True

    def serialize(self, value):
        if value is not None:
            return self.schema_class(data=value).serialize()


class ReferenceNotFoundError(Exception):
    """Exception to be raised when a referenced object isn't found."""


class EmbeddedReference(Dict):
    """Represents an object which can be referenced by its ID.

    This field allows one to submit a dict of values which will then create
    a new instance of the object, or it will update fields of an existing
    object if a field representing its ID (called `pk_field`) was included
    in the submitted dict.
    """

    def __init__(self, object_class, schema_class, pk_field="id", **kwargs):
        self.object_class = object_class
        self.schema_class = schema_class
        self.pk_field = pk_field
        super().__init__(**kwargs)

    def clean(self, value):
        # Clean the dict first.
        value = super().clean(value)

        # Then, depending on whether `pk_field` is in the dict of submitted
        # values or not, update an existing object or create a new one.
        if value and self.pk_field in value:
            return self.clean_existing(value)
        return self.clean_new(value)

    def serialize(self, obj):
        if obj is None:
            return

        obj_data = self.get_orig_data_from_existing(obj)
        serialized = self.schema_class(data=obj_data).serialize()
        serialized[self.pk_field] = getattr(obj, self.pk_field)
        return serialized

    def clean_new(self, value):
        """Return a new object instantiated with cleaned data."""
        value = self.schema_class(value).full_clean()
        return self.object_class(**value)

    def clean_existing(self, value):
        """Clean the data and return an existing document with its fields
        updated based on the cleaned values.
        """
        existing_pk = value[self.pk_field]
        try:
            obj = self.fetch_existing(existing_pk)
        except ReferenceNotFoundError as e:
            raise ValidationError("Object does not exist.") from e
        orig_data = self.get_orig_data_from_existing(obj)

        # Clean the data (passing the new data dict and the original data to
        # the schema).
        value = self.schema_class(value, orig_data).full_clean()

        # Set cleaned data on the object (except for the pk_field).
        for field_name, field_value in value.items():
            if field_name != self.pk_field:
                setattr(obj, field_name, field_value)

        return obj

    def fetch_existing(self, pk):
        """Fetch an existing object that corresponds to a given ID.

        This needs to be subclassed since, depending on the object class,
        the fetching mechanism might be different. See implementations of
        SQLAEmbeddedReference and MongoEmbeddedReference for a concrete
        example of fetching objects from a relational and non-relational
        database.

        :param str pk: ID of the object that's supposed to exist.
        :returns: an instance of the object class.
        :raises: ReferenceNotFoundError if the object doesn't exist.
        """
        raise NotImplementedError  # should be subclassed

    def get_orig_data_from_existing(self, obj):
        """Return a dictionary of field names and values for a given object.

        The values in the dictionary should be in their "cleaned" state (as
        in, exactly as they were set on the object, without any serialization).

        :param object obj: existing object for which new data is currently
            being cleaned.
        :returns: dict of fields and values that are currently set on the
            object (before the new cleaned data is applied).
        """
        raise NotImplementedError  # should be subclassed


class Reference(Field):
    """Represents an object which can be referenced by its ID.

    This field allows one to submit an ID of an object and get a cleaned
    instance of that object. Equivalently, serialization accepts an object
    and outputs its ID.
    """

    # The ID is assumed to be supplied as a string. However, subclasses can
    # change this field if need be (e.g. it's common for objects persisted in
    # relational databases to use integers as IDs).
    base_type = str

    def __init__(self, object_class, **kwargs):
        self.object_class = object_class
        super().__init__(**kwargs)

    def clean(self, value):
        obj_id = super().clean(value)
        try:
            return self.fetch_object(obj_id)
        except ReferenceNotFoundError as e:
            raise ValidationError("Object does not exist.") from e

    def fetch_object(self, ref_id):
        """Fetch an existing object that corresponds to a given ID.

        This needs to be subclassed since, depending on the object class,
        the fetching mechanism might be different. See implementations of
        SQLAReference and MongoReference for a concrete example of fetching
        objects from a relational and non-relational database.

        :param str pk: ID of the referenced object.
        :returns: an instance of the object class.
        :raises: ReferenceNotFoundError if the object doesn't exist.
        """
        raise NotImplementedError  # should be subclassed


class Choices(Field):
    """
    A field that accepts the given choices.
    """

    def __init__(
        self,
        choices,
        case_insensitive=False,
        error_invalid_choice=None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.choices = choices
        self.case_insensitive = case_insensitive
        self.error_invalid_choice = (
            error_invalid_choice or "Not a valid choice."
        )

    def get_choices(self):
        return self.choices

    def format_invalid_choice_msg(self, value):
        return self.error_invalid_choice.format(
            value=value, valid_choices=", ".join(self.get_choices())
        )

    def clean(self, value):
        value = super().clean(value)

        choices = self.get_choices()

        if self.case_insensitive:
            choices = {choice.lower(): choice for choice in choices}

            if not isinstance(value, str):
                raise ValidationError("The value needs to be a string.")

            if value.lower() not in choices:
                err_msg = self.format_invalid_choice_msg(value)
                raise ValidationError(err_msg)

            return choices[value.lower()]

        if value not in choices:
            err_msg = self.format_invalid_choice_msg(value)
            raise ValidationError(err_msg)

        return value


class Enum(Choices):
    """Like Choices, but expects a Python 3 Enum."""

    def __init__(self, choices, **kwargs):
        """Initialize the Enum field.

        The `choices` param can be either:
        * an enum.Enum class (in which case all of its values will become
          valid choices),
        * a list containing a subset of the enum's choices (e.g.
          `[SomeEnumCls.OptionA, SomeEnumCls.OptionB]`). You must provide
          more than one choice in this list and *all* of the choices must
          belong to the same enum class.
        """
        is_cls = inspect.isclass(choices)
        if is_cls:
            self.enum_cls = choices
        else:
            assert choices, "You need to provide at least one enum choice."
            self.enum_cls = choices[0].__class__
        super().__init__(choices, **kwargs)

    def get_choices(self):
        return [choice.value for choice in self.choices]

    def clean(self, value):
        value = super().clean(value)
        return self.enum_cls(value)

    def serialize(self, choice):
        if choice is not None:
            return choice.value


class SortedSet(List):
    """Sorted, unique set of values represented as a list."""

    def __init__(self, field_instance, max_length=None, key=None, **kwargs):
        super().__init__(field_instance, max_length, **kwargs)
        if isinstance(field_instance, Enum) and key is None:
            key = attrgetter("value")
        self.key = key

    def clean(self, value):
        return sorted(set(super().clean(value)), key=self.key)


class Schema:
    """
    Base Schema class. Provides core behavior like fields declaration
    and construction, validation, and data and error proxying.

    There are 3 steps to using a Schema:

    1. Define the Schema, e.g.

        class UserSchema(Schema):
            first_name = String()
            last_name = String()
            email = Email()

    2. Create a Schema instance, passing data into it.

        # Scenario 1: Creation of a new object.
        schema = UserSchema({
            'first_name': 'Donald',
            'last_name': 'Glover',
            'email': 'gambino@example.com'
        })

        # Scenario 2: Update of an existing object.
        schema = UserSchema(
            raw_data={
                'first_name': 'Childish',
                'last_name': 'Gambino'
            },
            data={
                'first_name': 'Donald',
                'last_name': 'Glover',
                'email': 'gambino@example.com'
            }
        )

    3. Clean the Schema (validating the data you passed into it).

        data = schema.full_clean()

    This operation will raise a ValidationError if the data you passed
    into the Schema is invalid.

    To introduce custom validation to the Schema (beyond the basics
    covered by various Field types), override the "clean" method and
    raise a ValidationError with a descriptive message if you encounter
    any invalid data.

    Parameters:
    - raw_data - a dict with the data you want to validate.
    - data - dict with existing data, e.g. based on some object you're
             trying to update.
    """

    @classmethod
    def get_fields(cls):
        """
        Returns a dictionary of fields and field instances for this schema.
        """
        fields = {}
        for field_name in dir(cls):
            if isinstance(getattr(cls, field_name), Field):
                field = getattr(cls, field_name)
                field_name = field.field_name or field_name
                fields[field_name] = field
        return fields

    @classmethod
    def obj_to_dict(cls, obj):
        """
        Takes a model object and converts it into a dictionary suitable for
        passing to the constructor's data attribute.
        """
        data = {}
        for field_name in cls.get_fields():
            try:
                value = getattr(obj, field_name)
            except AttributeError:
                # If the field doesn't exist on the object, fail gracefully
                # and don't include the field in the data dict at all. Fail
                # loudly if the field exists but produces a different error
                # (edge case: accessing an *existing* field could technically
                # produce an unrelated AttributeError).
                continue

            if callable(value):
                value = value()
            data[field_name] = value

        return data

    def __init__(self, raw_data=None, data=None):
        conflicting_fields = {
            "raw_data",
            "orig_data",
            "data",
            "errors",
            "field_errors",
            "fields",
        }.intersection(dir(self))
        if conflicting_fields:
            raise Exception(
                "The following field names are reserved and need to be renamed: %s. "
                "Please use the field_name keyword to use them."
                % list(conflicting_fields)
            )

        self.raw_data = raw_data or {}
        self.orig_data = data or None
        self.data = data and dict(data) or {}
        self.field_errors = {}
        self.errors = []
        self.fields = self.get_fields()

    def clean(self):
        """
        Override to add additional validations.

        Always called at the end of `full_clean()` method, even if validation
        failed for some fields.
        Cleaned input data are available in `self.data` dict.
        Keys that failed validation won't be set. Use conditional dictionary
        access or return early `if self.errors or self.field_errors`.
        """

    def full_clean(self):  # noqa: C901
        if not isinstance(self.raw_data, dict):
            raise ValidationError(
                {"errors": ["Invalid request: JSON dictionary expected."]}
            )

        for field_name, field in self.fields.items():
            if field.read_only:
                continue
            raw_field_name = field.raw_field_name or field_name
            try:
                # Validate a field if it's posted in raw_data, or if we don't
                # have a value for it in case it's required.
                if raw_field_name in self.raw_data or not field.has_value(
                    self.data.get(field_name, None)
                ):
                    value = field.clean(self.raw_data.get(raw_field_name))
                    if (
                        not field.mutable
                        and self.orig_data
                        and field_name in self.orig_data
                    ):
                        old_value = self.orig_data[field_name]

                        # compare datetimes properly, regardless of whether they're offset-naive or offset-aware
                        if isinstance(value, datetime.datetime) and isinstance(
                            old_value, datetime.datetime
                        ):
                            value = value.replace(tzinfo=None) + (
                                value.utcoffset()
                                or datetime.timedelta(seconds=0)
                            )
                            old_value = old_value.replace(tzinfo=None) + (
                                old_value.utcoffset()
                                or datetime.timedelta(seconds=0)
                            )

                        if value != old_value:
                            raise ValidationError("The value cannot be changed.")

                    self.data[field_name] = value

            except ValidationError as e:
                self.field_errors[raw_field_name] = e.args and e.args[0]
            except StopValidation as e:
                self.data[field_name] = e.args and e.args[0]

        try:
            self.clean()
        except ValidationError as e:
            self.errors = [e.args and e.args[0]]

        self.raise_on_errors()
        return self.data

    def raise_on_errors(self):
        if self.field_errors or self.errors:
            raise ValidationError(
                {"field-errors": self.field_errors, "errors": self.errors}
            )

    def external_clean(self, cls, raise_on_errors=True):
        try:
            # Instantiate the external schema with the right raw_data/data.
            external_schema = cls(raw_data=self.raw_data, data=self.data)

            # Make sure its orig_data is the same as this schema's
            external_schema.orig_data = self.orig_data

            # Validate the schema and update self.data with its results.
            self.data.update(external_schema.full_clean())
        except ValidationError as e:
            self.field_errors.update(e.args[0]["field-errors"])
            self.errors += e.args[0]["errors"]
            if raise_on_errors:
                self.raise_on_errors()

    def serialize(self):
        data = {}
        for field_name, field in self.fields.items():
            raw_field_name = field.raw_field_name or field_name
            value = self.data[field_name]
            data[raw_field_name] = field.serialize(value)
        return data


DEFAULT_TYPE_FIELD = "type"


class PolymorphicField(Dict):
    """A field that can be validated with one of multiple schemas,
    depending on type provided in input values.

    Requires a dictionary-shaped value.

    Actual schema is taken from provided mapping and selected using
    a field in the input dictionary, for example:

    PolymorphicField(type_map={'my_type': MySchema})

    {'type': 'my_type', 'more': 'data', ...} will be validated with
    MySchema based on 'my_type' value.

    keep_type_field (default no) allows keeping the type-dispatching field
    in dispatched schemas' data.
    """

    base_type = dict

    def __init__(
        self,
        type_map=None,
        type_field=DEFAULT_TYPE_FIELD,
        keep_type_field=False,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.type_map = type_map or {}
        self.type_field = type_field
        self.keep_type_field = keep_type_field

    def clean(self, value):
        clean = super().clean(value)
        field_type = clean.get(self.type_field)
        if field_type not in self.type_map:
            raise ValidationError(
                "{} must be one of {}".format(
                    self.type_field, ",".join(self.type_map.keys())
                )
            )

        return self.type_map[field_type].clean(
            {
                k: v
                for k, v in value.items()
                if self.keep_type_field or k != self.type_field
            }
        )


class UUID(String):
    """Schema field for UUIDs.

    It handles deserialization from a string to a Python UUID object
    and serialization from a Python UUID object to a string.
    """

    blank_value = None

    def clean(self, value):
        value = super().clean(value)
        try:
            return PythonUUID(value)
        except ValueError as e:
            raise ValidationError("Not a UUID.") from e

    def serialize(self, value):
        return str(value)


class CleanDict(Dict):
    """A dictionary in which both keys and values are validated with separate schema fields."""

    def __init__(self, key_schema, value_schema, max_length=None, **kwargs):
        super().__init__(**kwargs)
        self.key_schema = key_schema
        self.value_schema = value_schema
        self.max_length = max_length

    def clean(self, value):
        value = super().clean(value)

        if self.max_length and len(value) > self.max_length:
            raise ValidationError("Dict is too long.")

        errors = {}
        data = {}
        for key, item_value in value.items():
            try:
                cleaned_key = self.key_schema.clean(key)
            except ValidationError as e:
                errors[key] = e.args and e.args[0]
            else:
                try:
                    data[cleaned_key] = self.value_schema.clean(item_value)
                except ValidationError as e:
                    errors[key] = e.args and e.args[0]
                except StopValidation as e:
                    data[cleaned_key] = e.args and e.args[0]

        if errors:
            raise ValidationError({"errors": errors})

        return data

    def serialize(self, value):
        # Serialize all falsy values as an empty dict.
        if not value:
            return {}
        return {
            self.key_schema.serialize(key): self.value_schema.serialize(value)
            for key, value in value.items()
        }


class EmbeddedFactory(Embedded):
    """Schema field for arbitrary embedded object.

    It generates the object using provided factory function.
    Kwargs for the factory function is the input dict, validated
    validated with schema_class (from Embedded field).
    """

    def __init__(self, factory, *args, **kwargs):
        self.factory = factory
        super().__init__(*args, **kwargs)

    def clean(self, value):
        """Clean the provided dict of values and then return an
        an object created using a factory.
        """
        value = super().clean(value)
        return self.factory(**value)


class LazyField(Field):
    """A field which is instantiated later.

    Useful for resolving circular dependencies in code.
    """

    def __init__(self, fn, *args, **kwargs):
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.real_field = None

    def get_real_field(self):
        if self.real_field is None:
            self.real_field = self.fn(*self.args, **self.kwargs)
            assert self.real_field
        return self.real_field

    def __getattr__(self, item):
        return getattr(self.get_real_field(), item)

    def has_value(self, value):
        return self.get_real_field().has_value(value)

    def clean(self, value):
        return self.get_real_field().clean(value)

    def serialize(self, value):
        return self.get_real_field().serialize(value)
