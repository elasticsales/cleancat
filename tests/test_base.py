import datetime
import enum
import re
from uuid import UUID as PythonUUID

import pytest
from pytz import utc

from cleancat import (
    URL,
    Bool,
    Choices,
    DateTime,
    Dict,
    Email,
    Embedded,
    Enum,
    Field,
    Integer,
    List,
    Regex,
    RelaxedURL,
    Schema,
    SortedSet,
    StopValidation,
    String,
    TrimmedString,
    ValidationError,
)
from cleancat.base import (
    UUID,
    CleanDict,
    EmbeddedFactory,
    LazyField,
    PolymorphicField,
)


class TestField:
    def test_it_supports_multiple_base_types(self):
        class IntOrStrField(Field):
            base_type = (int, str)

        assert IntOrStrField().clean(5) == 5
        assert IntOrStrField().clean("five") == "five"

        expected_err_msg = "The value must be of int or str type."
        with pytest.raises(ValidationError, match=expected_err_msg):
            assert IntOrStrField().clean(4.5)


class TestStringField:
    def test_it_accepts_valid_input(self):
        value = "hello world"
        assert String().clean(value) == value

    @pytest.mark.parametrize("value", ["", None])
    def test_it_enforces_the_required_flag(self, value):
        expected_err_msg = "This field is required."
        with pytest.raises(ValidationError, match=expected_err_msg):
            String().clean(value)

    def test_it_accepts_valid_input_if_not_required(self):
        value = "hello world"
        assert String().clean(value) == value

    @pytest.mark.parametrize("value", ["", None])
    def test_it_can_be_optional(self, value):
        with pytest.raises(StopValidation) as e:
            String(required=False).clean(value)
        assert e.value.args[0] == ""

    @pytest.mark.parametrize("value", ["", None])
    def test_it_falls_back_to_the_default_value(self, value):
        with pytest.raises(StopValidation) as e:
            String(required=False, default="default").clean(value)
        assert e.value.args[0] == "default"

    def test_it_enforces_valid_data_type(self):
        expected_err_msg = "The value must be of str type."
        with pytest.raises(ValidationError, match=expected_err_msg):
            String().clean(True)

    @pytest.mark.parametrize(
        ("value", "valid"), [("long enough", True), ("short", False)]
    )
    def test_it_enforces_min_length(self, value, valid):
        field = String(min_length=10)
        if valid:
            assert field.clean(value) == value
        else:
            err_msg = "The value must be at least 10 characters long."
            with pytest.raises(ValidationError, match=err_msg):
                field.clean(value)

    @pytest.mark.parametrize(
        ("value", "valid"),
        [("short is ok", True), ("this is way too long enough", False)],
    )
    def test_it_enforces_max_length(self, value, valid):
        field = String(max_length=12)
        if valid:
            assert field.clean(value) == value
        else:
            err_msg = "The value must be no longer than 12 characters."
            with pytest.raises(ValidationError, match=err_msg):
                field.clean(value)

    @pytest.mark.parametrize(
        ("value", "valid"),
        [
            ("right in the middle", True),
            ("too short", False),
            ("way too long to be valid", False),
        ],
    )
    def test_it_enforces_min_and_max_length(self, value, valid):
        field = String(min_length=10, max_length=20)
        if valid:
            assert field.clean(value) == value
        else:
            with pytest.raises(ValidationError) as e:
                field.clean(value)
            assert e.value.args[0] in (
                "The value must be at least 10 characters long.",
                "The value must be no longer than 20 characters.",
            )


class TestTrimmedStringField:
    def test_it_accepts_valid_input(self):
        value = "hello world"
        assert TrimmedString().clean(value) == value

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("   hello world    ", "hello world"),
            ("   hello   world", "hello   world"),
            ("\rhello\tworld \n", "hello\tworld"),
        ],
    )
    def test_it_trims_input_surrounded_by_whitespace(self, value, expected):
        assert TrimmedString().clean(value) == expected

    @pytest.mark.parametrize("value", ["", "   ", "\t\n\r", None])
    def test_it_enforces_required_flag(self, value):
        expected_err_msg = "This field is required."
        with pytest.raises(ValidationError, match=expected_err_msg):
            TrimmedString().clean(value)

    @pytest.mark.parametrize("value", ["", "   ", "\t\n\r", None])
    def test_it_can_be_optional(self, value):
        with pytest.raises(StopValidation) as e:
            TrimmedString(required=False).clean(value)
        assert e.value.args[0] == ""

    def test_it_enforces_valid_data_type(self):
        expected_err_msg = "The value must be of str type."
        with pytest.raises(ValidationError, match=expected_err_msg):
            TrimmedString().clean(True)

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("      valid      ", "valid"),
            ("        x        ", None),
            ("   way too long  ", None),
        ],
    )
    def test_it_enforces_min_and_max_length(self, value, expected):
        field = TrimmedString(min_length=3, max_length=10)
        if expected:
            assert field.clean(value) == expected
        else:
            with pytest.raises(ValidationError) as e:
                field.clean(value)
            assert e.value.args[0] in (
                "The value must be at least 3 characters long.",
                "The value must be no longer than 10 characters.",
            )


class TestChoicesField:
    @pytest.mark.parametrize("value", ["Hello", "World"])
    def test_it_accepts_valid_choices(self, value):
        assert Choices(choices=["Hello", "World"]).clean(value) == value

    @pytest.mark.parametrize("value", ["hello", "Invalid"])
    def test_it_rejects_invalid_choices(self, value):
        expected_err_msg = "Not a valid choice."
        with pytest.raises(ValidationError, match=expected_err_msg):
            Choices(choices=["Hello", "World"]).clean(value)

    def test_it_supports_case_insensitiveness(self):
        field = Choices(choices=["Hello", "WORLD"], case_insensitive=True)
        assert field.clean("HeLlO") == "Hello"
        assert field.clean("woRlD") == "WORLD"


class TestBoolField:
    @pytest.mark.parametrize("value", [True, False])
    def test_it_accepts_valid_input(self, value):
        assert Bool().clean(value) == value

    def test_it_enforces_required_flag(self):
        expected_err_msg = "This field is required."
        with pytest.raises(ValidationError, match=expected_err_msg):
            Bool().clean(None)

    def test_it_enforces_valid_data_type(self):
        expected_err_msg = "The value must be of bool type."
        with pytest.raises(ValidationError, match=expected_err_msg):
            Bool().clean("")

    def test_it_can_be_optional(self):
        with pytest.raises(StopValidation) as e:
            Bool(required=False).clean(None)
        # TODO should the blank value for a Bool really be False and not None?
        assert e.value.args[0] is False


class TestRegexField:
    @pytest.mark.parametrize("value", ["a", "m", "z"])
    def test_it_accepts_valid_input(self, value):
        assert Regex("^[a-z]$").clean(value) == value

    @pytest.mark.parametrize("value", ["A", "M", "Z", "aa", "mm", "zz"])
    def test_it_rejects_invalid_input(self, value):
        expected_err_msg = "Invalid input."
        with pytest.raises(ValidationError, match=expected_err_msg):
            Regex("^[a-z]$").clean(value)

    @pytest.mark.parametrize("value", ["A", "M", "Z"])
    def test_it_accepts_case_insensitive_input(self, value):
        assert Regex("^[a-z]$", re.IGNORECASE).clean(value) == value

    def test_it_supports_custom_error_messaging(self):
        err_msg = "Not a lowercase letter."
        with pytest.raises(ValidationError, match=err_msg):
            Regex("^[a-z]$", regex_message=err_msg).clean("aa")

    @pytest.mark.parametrize("value", ["", None])
    def test_it_enforces_required_flag(self, value):
        expected_err_msg = "This field is required."
        with pytest.raises(ValidationError, match=expected_err_msg):
            Regex("^[a-z]$").clean(value)

    @pytest.mark.parametrize("value", ["", None])
    def test_it_can_be_optional(self, value):
        with pytest.raises(StopValidation) as e:
            Regex("^[a-z]$", required=False).clean(value)
        assert e.value.args[0] == ""

    def test_it_enforces_valid_data_type(self):
        expected_err_msg = "The value must be of str type."
        with pytest.raises(ValidationError, match=expected_err_msg):
            Regex("^[a-z]$").clean(True)


class TestDateTimeField:
    def test_it_accepts_date_string(self):
        assert DateTime().clean("2012-10-09") == datetime.date(2012, 10, 9)

    def test_it_forces_datetime_resolution(self):
        ret_dt = DateTime(force_datetime=True).clean("2012-10-09")
        assert isinstance(ret_dt, datetime.datetime)
        assert ret_dt == datetime.datetime(2012, 10, 9)

        ret_date = DateTime(force_datetime=False).clean("2012-10-09")
        assert isinstance(ret_date, datetime.date)
        assert not isinstance(ret_date, datetime.datetime)
        assert ret_date == datetime.date(2012, 10, 9)

    def test_it_accepts_datetime_string(self):
        expected = datetime.datetime(2012, 10, 9, 13, 10, 4)
        assert DateTime().clean("2012-10-09 13:10:04") == expected

    def test_it_supports_tzinfo(self):
        raw = "2013-03-27T01:02:01.137000+00:00"
        expected = datetime.datetime(2013, 3, 27, 1, 2, 1, 137000, tzinfo=utc)
        assert DateTime().clean(raw) == expected

    def test_it_rejects_invalid_year_range(self):
        with pytest.raises(ValidationError, match="Could not parse datetime"):
            DateTime().clean("0000-01-01T00:00:00-08:00")

    @pytest.mark.parametrize("value", ["2012a", "alksdjf", "111111111"])
    def test_it_rejects_invalid_dates(self, value):
        expected_err_msg = "Invalid ISO 8601 datetime."
        with pytest.raises(ValidationError, match=expected_err_msg):
            DateTime().clean(value)

    @pytest.mark.parametrize("value", ["", None])
    def test_it_enforces_required_flag(self, value):
        expected_err_msg = "This field is required."
        with pytest.raises(ValidationError, match=expected_err_msg):
            DateTime().clean(value)

    @pytest.mark.parametrize("value", ["", None])
    def test_it_can_be_optional(self, value):
        with pytest.raises(StopValidation) as e:
            DateTime(required=False).clean(value)
        assert e.value.args[0] is None

    def test_it_enforces_valid_data_type(self):
        expected_err_msg = "The value must be of str type."
        with pytest.raises(ValidationError, match=expected_err_msg):
            DateTime().clean(True)


class TestEmailField:
    @pytest.mark.parametrize(
        "value", ["t@e.com", "test@example.com", "test.test@example.com"]
    )
    def test_it_accepts_valid_email_addresses(self, value):
        assert Email().clean(value) == value

    @pytest.mark.parametrize(
        "value",
        [
            "test@example",
            "test.example.com",
            "test@@example.com",
            "test@example..com",
            "test.@example.com",
            ".test@example.com",
            "test..test@example.com",
            "test @example.com",
            "test@ example.com",
            "test@example .com",
        ],
    )
    def test_it_rejects_invalid_email_addresses(self, value):
        expected_err_msg = "Invalid email address."
        with pytest.raises(ValidationError, match=expected_err_msg):
            Email().clean(value)

    def test_it_autotrims_input(self):
        assert Email().clean("   test@example.com   ") == "test@example.com"

    @pytest.mark.parametrize(
        ("value", "valid"),
        [
            ("{u}@{d}.{d}.{d}.example".format(u="u" * 54, d="d" * 63), True),
            # Emails must not be longer than 254 characters.
            ("{u}@{d}.{d}.{d}.example".format(u="u" * 55, d="d" * 63), False),
        ],
    )
    def test_it_enforces_max_email_address_length(self, value, valid):
        field = Email()
        if valid:
            assert field.clean(value) == value
        else:
            err_msg = "The value must be no longer than 254 characters."
            with pytest.raises(ValidationError, match=err_msg):
                field.clean(value)

    @pytest.mark.parametrize("value", ["", None])
    def test_it_enforces_required_flag(self, value):
        expected_err_msg = "This field is required."
        with pytest.raises(ValidationError, match=expected_err_msg):
            Email().clean(value)

    @pytest.mark.parametrize("value", ["", None])
    def test_it_can_be_optional(self, value):
        with pytest.raises(StopValidation) as e:
            Email(required=False).clean(value)
        assert e.value.args[0] == ""

    def test_it_enforces_valid_data_type(self):
        expected_err_msg = "The value must be of str type."
        with pytest.raises(ValidationError, match=expected_err_msg):
            Email().clean(True)


class TestIntegerField:
    @pytest.mark.parametrize("value", [-1, 0, 100, 1000000])
    def test_it_accepts_valid_integers(self, value):
        assert Integer().clean(value) == value

    @pytest.mark.parametrize(
        ("value", "valid"), [(10, True), (0, True), (-1, False)]
    )
    def test_it_enforces_min_value(self, value, valid):
        field = Integer(min_value=0)
        if valid:
            assert field.clean(value) == value
        else:
            expected_err_msg = "The value must be at least 0."
            with pytest.raises(ValidationError, match=expected_err_msg):
                field.clean(value)

    @pytest.mark.parametrize(
        ("value", "valid"), [(-1, True), (0, True), (100, True), (101, False)]
    )
    def test_it_enforces_max_value(self, value, valid):
        field = Integer(max_value=100)
        if valid:
            assert field.clean(value) == value
        else:
            expected_err_msg = "The value must not be larger than 100."
            with pytest.raises(ValidationError, match=expected_err_msg):
                field.clean(value)

    @pytest.mark.parametrize(
        ("value", "valid"),
        [(-1, False), (0, True), (50, True), (100, True), (101, False)],
    )
    def test_it_enforces_min_and_max_value(self, value, valid):
        field = Integer(min_value=0, max_value=100)
        if valid:
            assert field.clean(value) == value
        else:
            with pytest.raises(ValidationError) as e:
                field.clean(value)
            assert e.value.args[0] in (
                "The value must be at least 0.",
                "The value must not be larger than 100.",
            )

    def test_it_enforces_required_flag(self):
        expected_err_msg = "This field is required."
        with pytest.raises(ValidationError, match=expected_err_msg):
            Integer().clean(None)

    def test_it_can_be_optional(self):
        with pytest.raises(StopValidation) as e:
            Integer(required=False).clean(None)
        assert e.value.args[0] is None

    @pytest.mark.parametrize("value", ["", "0", 23.0])
    def test_it_enforces_valid_data_type(self, value):
        expected_err_msg = "The value must be of int type."
        with pytest.raises(ValidationError, match=expected_err_msg):
            Integer().clean(value)


class TestListField:
    def test_it_accepts_a_list_of_values(self):
        values = ["a", "b", "c"]
        assert List(String()).clean(values) == values

    def test_it_validates_each_value(self):
        with pytest.raises(ValidationError) as e:
            List(String(max_length=3)).clean(["a", 2, "c", "long"])
        assert e.value.args[0]["errors"][1] in (
            "The value must be of basestring type.",
            "The value must be of str type.",
        )
        assert e.value.args[0]["errors"][3] == (
            "The value must be no longer than 3 characters."
        )

    @pytest.mark.parametrize(
        ("value", "valid"),
        [
            (["a", "b"], True),
            (["a", "b", "c"], True),
            (["a", "b", "c", "d"], False),
        ],
    )
    def test_it_enforces_max_length(self, value, valid):
        field = List(String(), max_length=3)
        if valid:
            assert field.clean(value) == value
        else:
            expected_err_msg = "List is too long."
            with pytest.raises(ValidationError, match=expected_err_msg):
                field.clean(value)

    @pytest.mark.parametrize("value", [None, []])
    def test_it_enforces_required_flag(self, value):
        expected_err_msg = "This field is required."
        with pytest.raises(ValidationError, match=expected_err_msg):
            List(String()).clean(value)

    @pytest.mark.parametrize("value", [None, []])
    def test_it_can_be_optional(self, value):
        with pytest.raises(StopValidation) as e:
            List(String(), required=False).clean(value)
        assert e.value.args[0] == []

    def test_it_handles_defaults(self):
        field = List(String(default="xyz"))
        assert field.clean(["abc", None]) == ["abc", "xyz"]


class ClassWithID:
    id = None

    def __init__(self, id_):
        self.id = id_

    def __eq__(self, other):
        return type(self) is type(other) and self.id == other.id

    def __hash__(self):
        return hash(self.id)


class ClassWithIDField(Field):
    def clean(self, value):
        return ClassWithID(int(value["id"]))


class TestSortedSetField:
    def test_it_dedupes_valid_values(self):
        assert SortedSet(String()).clean(["a", "b", "a"]) == ["a", "b"]

    def test_it_sorts_valid_values(self):
        assert SortedSet(String()).clean(["b", "a"]) == ["a", "b"]

    def test_it_sorts_objects(self):
        sorted_set = SortedSet(ClassWithIDField(), key=lambda o: o.id).clean(
            [{"id": "2"}, {"id": "1"}]
        )
        assert sorted_set == [ClassWithID(1), ClassWithID(2)]

    def test_it_sorts_enums(self):
        class MyChoices(enum.Enum):
            A = "a"
            B = "b"
            C = "c"

        sorted_set = SortedSet(Enum(MyChoices)).clean(
            [MyChoices.C.value, MyChoices.B.value, MyChoices.A.value]
        )
        assert sorted_set == [MyChoices.A, MyChoices.B, MyChoices.C]

    def test_it_enforces_required_flag(self):
        expected_err_msg = "This field is required."
        with pytest.raises(ValidationError, match=expected_err_msg):
            SortedSet(String()).clean(None)

    def test_it_can_be_optional(self):
        with pytest.raises(StopValidation) as e:
            SortedSet(String(), required=False).clean(None)
        assert e.value.args[0] == []

    @pytest.mark.parametrize("value", [23.0, True])
    def test_it_enforces_valid_data_type(self, value):
        expected_err_msg = "The value must be of list type."
        with pytest.raises(ValidationError, match=expected_err_msg):
            SortedSet(String()).clean(value)


class TestEnumField:
    @pytest.fixture()
    def enum_cls(self):
        class MyChoices(enum.Enum):
            A = "a"
            B = "b"
            C = "c"

        return MyChoices

    def test_it_accepts_valid_choices(self, enum_cls):
        assert Enum(enum_cls).clean("a") == enum_cls.A
        assert Enum(enum_cls).clean("b") == enum_cls.B
        assert Enum(enum_cls).clean("c") == enum_cls.C

    def test_it_rejects_invalid_choices(self, enum_cls):
        expected_err_msg = "Not a valid choice."
        with pytest.raises(ValidationError, match=expected_err_msg):
            Enum(enum_cls).clean("d")

    def test_it_has_custom_message(self, enum_cls):
        expected_err_msg = "Invalid choice d. Valid choices: a, b, c"
        with pytest.raises(ValidationError, match=expected_err_msg):
            Enum(
                enum_cls,
                error_invalid_choice="Invalid choice {value}. Valid choices: {valid_choices}",
            ).clean("d")

    def test_it_accepts_a_sublist_of_choices(self, enum_cls):
        field = Enum([enum_cls.A, enum_cls.B])
        assert field.clean("a") == enum_cls.A
        assert field.clean("b") == enum_cls.B

        expected_err_msg = "Not a valid choice."
        with pytest.raises(ValidationError, match=expected_err_msg):
            field.clean("c")


class TestURLField:
    @pytest.mark.parametrize(
        "value",
        [
            "http://x.com",
            "http://♡.com",
            "http://example.com/a?b=c",
            "ftp://ftp.example.com",
            "http://example.com?params=without&path",
            # Russian unicode URL (IDN, unicode path and query params)
            "http://пример.com",
            "http://пример.рф",
            "http://пример.рф/путь/?параметр=значение",
            # Punicode stuff
            "http://test.XN--11B4C3D",
            # http://stackoverflow.com/questions/9238640/how-long-can-a-tld-possibly-be
            # Longest to date (Feb 2017) TLD in punicode format is 24 chars long
            "http://test.xn--vermgensberatung-pwb",
        ],
    )
    def test_in_accepts_valid_urls(self, value):
        assert URL().clean(value) == value

    @pytest.mark.parametrize(
        "value",
        [
            "www.example.com",
            "http:// invalid.com",
            "http://!nvalid.com",
            "http://.com",
            "http://",
            "http://.",
            "invalid",
            "http://ＧＯＯＧＬＥ.com",  # full-width chars are disallowed
            "javascript:alert()",  # TODO "javascript" is a valid scheme. "//" is not a part of some URIs.
        ],
    )
    def test_it_rejects_invalid_urls(self, value):
        expected_err_msg = "Invalid URL."
        with pytest.raises(ValidationError, match=expected_err_msg):
            URL().clean(value)

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("http://example.com/a?b=c", "http://example.com/a?b=c"),
            ("ftp://ftp.example.com", "ftp://ftp.example.com"),
            ("www.example.com", "http://www.example.com"),
            ("invalid", None),
            (True, None),
        ],
    )
    def test_it_supports_a_default_scheme(self, value, expected):
        field = URL(default_scheme="http://")
        if expected:
            assert field.clean(value) == expected
        else:
            pytest.raises(ValidationError, field.clean, value)

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("https://example.com/", "https://example.com/"),
            ("example.com/", "https://example.com/"),
            ("http://example.com", None),
        ],
    )
    def test_it_enforces_allowed_schemes(self, value, expected):
        field = URL(default_scheme="https://", allowed_schemes=["https://"])
        if expected:
            assert field.clean(value) == expected
        else:
            expected_err_msg = (
                "This URL uses a scheme that's not allowed. You can only "
                "use https://."
            )
            with pytest.raises(ValidationError, match=expected_err_msg):
                field.clean(value)

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("https://example.com/", "https://example.com/"),
            ("ftp://ftp.example.com", "ftp://ftp.example.com"),
            ("example.com/", "https://example.com/"),
            ("javascript://www.example.com/#%0aalert(document.cookie)", None),
        ],
    )
    def test_it_enforces_disallowed_schemes(self, value, expected):
        field = URL(
            default_scheme="https://", disallowed_schemes=["javascript:"]
        )
        if expected:
            assert field.clean(value) == expected
        else:
            expected_err_msg = "This URL uses a scheme that's not allowed."
            with pytest.raises(ValidationError, match=expected_err_msg):
                field.clean(value)

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("https://example.com/", "https://example.com/"),
            ("example.com/", "https://example.com/"),
            ("ftps://storage.example.com", "ftps://storage.example.com"),
        ],
    )
    def test_it_supports_simpler_allowed_scheme_values(self, value, expected):
        field = URL(default_scheme="https", allowed_schemes=["https", "ftps"])
        assert field.clean(value) == expected

    @pytest.mark.parametrize("value", ["", None])
    def test_it_enforces_required_flag(self, value):
        expected_err_msg = "This field is required."
        with pytest.raises(ValidationError, match=expected_err_msg):
            URL().clean(value)

    @pytest.mark.parametrize("value", ["", None])
    def test_it_can_be_optional(self, value):
        with pytest.raises(StopValidation) as e:
            URL(required=False).clean(value)
        assert e.value.args[0] is None

    @pytest.mark.parametrize("value", [23.0, True])
    def test_it_enforces_valid_data_type(self, value):
        expected_err_msg = "The value must be of str type."
        with pytest.raises(ValidationError, match=expected_err_msg):
            URL().clean(value)


class TestRelaxedURLField:
    @pytest.mark.parametrize(
        "value",
        [
            "http://example.com/a?b=c",
            "ftp://ftp.example.com",
            "http://пример.рф",
        ],
    )
    def test_it_accepts_valid_urls(self, value):
        assert RelaxedURL().clean(value) == value

    @pytest.mark.parametrize(
        ("value", "is_required", "valid"),
        [
            ("http://", True, False),
            ("http://", False, True),
            ("ftp://", True, False),
            ("ftp://", False, True),
            ("invalid", True, False),
            ("invalid", False, False),
        ],
    )
    def test_it_accepts_scheme_only_urls_if_not_required(
        self, value, is_required, valid
    ):
        field = RelaxedURL(default_scheme=value, required=is_required)
        if valid:
            assert field.clean(value) is None
        else:
            expected_err_msg = "Invalid URL."
            with pytest.raises(ValidationError, match=expected_err_msg):
                field.clean(value)

    @pytest.mark.parametrize("value", [23.0, True])
    def test_it_enforces_valid_data_type(self, value):
        expected_err_msg = "The value must be of str type."
        with pytest.raises(ValidationError, match=expected_err_msg):
            RelaxedURL().clean(value)


class TestEmbeddedField:
    @pytest.fixture()
    def schema_cls(self):
        class UserSchema(Schema):
            email = Email()

        return UserSchema

    def test_it_accepts_valid_input(self, schema_cls):
        value = {"email": "valid@example.com"}
        assert Embedded(schema_cls).clean(value) == value

    def test_it_performs_validation_of_embedded_schema(self, schema_cls):
        value = {"email": "invalid"}
        with pytest.raises(ValidationError) as e:
            Embedded(schema_cls).clean(value)
        assert e.value.args[0] == {
            "errors": [],
            "field-errors": {"email": "Invalid email address."},
        }

    @pytest.mark.parametrize("value", [{}, None])
    def test_it_enforces_required_flag(self, value, schema_cls):
        expected_err_msg = "This field is required."
        with pytest.raises(ValidationError, match=expected_err_msg):
            Embedded(schema_cls).clean(value)


class TestSchemaExternalClean:
    """
    Collection of tests making sure Schema#external_clean works as
    expected.
    """

    @pytest.fixture()
    def message_schema_cls(self):
        # Generic message schema that may be used in composition with more
        # specific schemas
        class MessageSchema(Schema):
            status = String(required=True)

            def clean(self):
                orig_status = self.orig_data and self.orig_data["status"]
                new_status = self.data["status"]

                if orig_status == "sent" and new_status == "inbox":
                    self.field_errors[
                        "status"
                    ] = "Can't change from sent to inbox"

                self.data["message_cleaned"] = True

                return self.data

        return MessageSchema

    @pytest.fixture()
    def email_schema_cls(self, message_schema_cls):
        # Specific email schema that also calls the generic message schema
        # via external_clean
        class EmailSchema(Schema):
            subject = String()

            def full_clean(self):
                super().full_clean()
                self.external_clean(message_schema_cls)

        return EmailSchema

    def test_external_clean(self, email_schema_cls):
        schema = email_schema_cls({"subject": "hi", "status": "sent"})
        schema.full_clean()
        assert schema.data == {
            "subject": "hi",
            "status": "sent",
            "message_cleaned": True,
        }

    def test_orig_data_in_external_clean(self, email_schema_cls):
        """
        Create a schema for an existing object, which originally had
        subject='hi' and status='sent' and we're trying to validate an
        update to subject='hi updated' and status='inbox' (which shouldn't
        be allowed).
        """
        orig_data = {"subject": "hi", "status": "sent"}
        new_data = {"subject": "hi updated", "status": "inbox"}
        schema = email_schema_cls(new_data, orig_data)

        pytest.raises(ValidationError, schema.full_clean)
        assert schema.field_errors == {
            "status": "Can't change from sent to inbox"
        }


class TestSchema:
    def test_empty_data_dict_with_required_fields(self):
        class RequiredSchema(Schema):
            text = String()

        schema = RequiredSchema({})
        pytest.raises(ValidationError, schema.full_clean)
        assert schema.field_errors["text"] == "This field is required."

    def test_blank_values_for_optional_fields(self):
        class OptionalSchema(Schema):
            text = String(required=False)
            nullable_text = Bool(required=False, blank_value=None)
            boolean = Bool(required=False)
            nullable_boolean = Bool(required=False, blank_value=None)
            number = Integer(required=False)

        data = OptionalSchema({}).full_clean()
        assert data == {
            "text": "",
            "nullable_text": None,
            "boolean": False,
            "nullable_boolean": None,
            "number": None,
        }

    def test_it_preserves_orig_data_if_no_new_data_given(self):
        class OptionalSchema(Schema):
            text = String(required=False)

        orig_data = {"text": "old value"}
        data = OptionalSchema({}, orig_data).full_clean()
        assert data == orig_data

    @pytest.mark.parametrize(
        ("old_data", "new_data", "is_valid"),
        [
            (None, {"text": "hello"}, True),
            ({}, {"text": "hello"}, True),
            ({"text": "existing"}, {"text": "existing"}, True),
            ({"text": "existing"}, {}, True),
            ({"text": "existing"}, {"text": "new"}, False),
            ({"text": ""}, {"text": "new"}, False),
            ({"text": None}, {"text": "new"}, False),
        ],
    )
    def test_it_enforces_mutability(self, old_data, new_data, is_valid):
        class UnmutableSchema(Schema):
            text = String(mutable=False)

        if old_data is None:
            schema = UnmutableSchema(new_data)
        else:
            schema = UnmutableSchema(new_data, old_data)

        if is_valid:
            assert schema.full_clean() == new_data or old_data
        else:
            with pytest.raises(ValidationError) as e:
                schema.full_clean()
            assert e.value.args[0] == {
                "errors": [],
                "field-errors": {"text": "The value cannot be changed."},
            }

    def test_serialization(self):
        class EmbeddedSchema(Schema):
            date_time = DateTime()

        class TestSchema(Schema):
            string = String()
            boolean = Bool()
            date_time = DateTime()
            integer = Integer()
            lst = List(DateTime())
            embedded = Embedded(EmbeddedSchema)

        schema = TestSchema(
            data={
                "string": "foo",
                "boolean": True,
                "date_time": datetime.datetime(2016, 1, 2, 3, 4, 5),
                "integer": 1234,
                "lst": [
                    datetime.datetime(2016, 1, 2, 3, 4, 5),
                    datetime.datetime(2016, 1, 3),
                ],
                "embedded": {"date_time": datetime.datetime(2000, 1, 1)},
            }
        )

        serialized = schema.serialize()
        assert serialized == {
            "string": "foo",
            "boolean": True,
            "date_time": "2016-01-02T03:04:05",
            "integer": 1234,
            "lst": ["2016-01-02T03:04:05", "2016-01-03T00:00:00"],
            "embedded": {"date_time": "2000-01-01T00:00:00"},
        }

    def test_serialization_optional_fields(self):
        class EmbeddedSchema(Schema):
            date_time = DateTime()

        class TestSchema(Schema):
            name = String(required=True)
            string = String(required=False)
            choice = Choices(["a", "b"], required=False)
            boolean = Bool(required=False)
            date_time = DateTime(required=False)
            integer = Integer(required=False)
            embedded = Embedded(EmbeddedSchema, required=False)
            lst = List(DateTime(), required=False)
            sorted_set = SortedSet(String(), required=False)
            dictionary = Dict(required=False)

        schema = TestSchema(
            data={
                "name": "One Required Field",
                "string": None,
                "choice": None,
                "boolean": None,
                "date_time": None,
                "integer": None,
                "embedded": None,
                "lst": None,
                "sorted_set": None,
                "dictionary": None,
            }
        )
        serialized = schema.serialize()
        assert serialized == {
            "name": "One Required Field",
            "string": None,
            "choice": None,
            "boolean": None,
            "date_time": None,
            "integer": None,
            "embedded": None,
            "lst": [],
            "sorted_set": [],
            "dictionary": {},
        }

    def test_serialization_enum(self):
        class MyChoices(enum.Enum):
            A = "a"
            B = "b"

        class TestSchema(Schema):
            enum = Enum(MyChoices)
            optional_enum = Enum(MyChoices, required=False)
            lst = List(Enum(MyChoices))

        schema = TestSchema(
            data={
                "enum": MyChoices.A,
                "optional_enum": None,
                "lst": [MyChoices.A, MyChoices.B],
            }
        )

        serialized = schema.serialize()
        assert serialized == {
            "enum": "a",
            "optional_enum": None,
            "lst": ["a", "b"],
        }

    def test_raw_field_name_serialization(self):
        class TestSchema(Schema):
            value = String(raw_field_name="value_id")

        schema = TestSchema({"value_id": "val_xyz"})

        schema.full_clean()
        assert schema.data == {"value": "val_xyz"}

        serialized = schema.serialize()
        assert serialized == {"value_id": "val_xyz"}

    def test_raw_field_name_error(self):
        class TestSchema(Schema):
            value = Integer(raw_field_name="value_id")

        schema = TestSchema({"value_id": "not-an-integer"})

        with pytest.raises(ValidationError):
            schema.full_clean()

        assert schema.field_errors == {
            "value_id": "The value must be of int type."
        }


@pytest.mark.parametrize("keep_type_field", [False, True])
def test_polymorphic_field(keep_type_field):
    class Option1(Dict):
        def clean(self, value):
            value = super().clean(value)
            assert ("type" in value) == keep_type_field
            if "option-1" not in value:
                raise ValidationError("option-1 not in data")
            return value["option-1"]

    class Option2(Dict):
        def clean(self, value):
            value = super().clean(value)
            assert ("type" in value) == keep_type_field
            if "option-2" not in value:
                raise ValidationError("option-2 not in data")
            return value["option-2"]

    poly_field = PolymorphicField(
        type_map={"1": Option1(), "2": Option2()},
        keep_type_field=keep_type_field,
    )

    assert poly_field.clean({"type": "1", "option-1": "data"}) == "data"
    assert poly_field.clean({"type": "2", "option-2": "data"}) == "data"

    with pytest.raises(ValidationError):
        poly_field.clean({"type": "0"})

    with pytest.raises(ValidationError):
        poly_field.clean({"type": "1", "option-0": "data"})


def test_polymorphic_field_2():
    class Option(Dict):
        def clean(self, value):
            value = super().clean(value)
            if "option" not in value:
                raise ValidationError("option not in data")
            return value["option"]

    poly_field = PolymorphicField(type_map={"option": Option()})
    assert poly_field.clean({"type": "option", "option": 1}) == 1


def test_embedded_factory():
    class SumTwoInts(Schema):
        a = Integer(required=True)
        b = Integer(required=True)

    field = EmbeddedFactory(
        factory=(lambda a, b: a + b), schema_class=SumTwoInts
    )

    assert field.clean({"a": 1, "b": 2}) == 3


def test_lazy_field():
    side_effects = []

    class SideEffectingInteger(Integer):
        def __init__(self, *args, **kwargs):
            side_effects.append(1)
            super().__init__(*args, **kwargs)

    class TestSchema(Schema):
        lazy_side_effect = LazyField(SideEffectingInteger, required=True)

    assert side_effects == []
    TestSchema({"lazy_side_effect": 1})
    assert side_effects == [1]
    TestSchema({"lazy_side_effect": 1})
    assert side_effects == [1]


def test_uuid_field():
    my_id = "1a4c0351-3621-4860-b528-5ada0003fbda"

    with pytest.raises(ValidationError) as exc_info:
        UUID().clean("x")
    assert exc_info.value.args[0] == "Not a UUID."

    with pytest.raises(ValidationError) as exc_info:
        assert UUID().clean(None)
    assert exc_info.value.args[0] == "This field is required."

    assert UUID().clean(my_id) == PythonUUID(my_id)
    assert UUID().serialize(PythonUUID(my_id)) == my_id


def test_clean_dict():
    f = CleanDict(key_schema=Regex(r"^k*$"), value_schema=Regex(r"^v*$"))
    assert f.clean({"k": "v"}) == {"k": "v"}
    assert f.clean({"kkk": "vvv", "k": "v"}) == {"kkk": "vvv", "k": "v"}

    with pytest.raises(ValidationError):
        f.clean({"a": "v"})

    with pytest.raises(ValidationError):
        f.clean({"k": "a"})

    with pytest.raises(ValidationError):
        f.clean({"a": "a"})

    with pytest.raises(ValidationError):
        f.clean({"a": 1})

    with pytest.raises(ValidationError):
        f.clean({"a": [1]})


def test_optional_clean_dict():
    class TestSchema(Schema):
        f_opt = CleanDict(
            key_schema=Regex(r"^k*$"), value_schema=Integer(), required=False
        )

    assert TestSchema({"f_opt": {}}).full_clean() == {"f_opt": None}
    assert TestSchema({"f_opt": {"k": 1}}).full_clean() == {"f_opt": {"k": 1}}
    assert TestSchema({}).full_clean() == {"f_opt": None}

    with pytest.raises(ValidationError):
        assert TestSchema({"f_opt": {"x": 1}}).full_clean()

    with pytest.raises(ValidationError):
        assert TestSchema({"f_opt": {"k": 1.1}}).full_clean()


def test_clean_default():
    f = CleanDict(key_schema=String(), value_schema=String(default="xyz"))
    assert f.clean({"k": "v", "k1": None}) == {"k": "v", "k1": "xyz"}
