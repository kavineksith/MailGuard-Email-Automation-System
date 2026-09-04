from core.exceptions import (
    InvalidEmailError,
    MailGuardError,
    Severity,
)


def test_default_code_and_severity():
    exc = MailGuardError("boom")
    assert exc.code == "MG-1000"
    assert exc.severity == Severity.ERROR


def test_custom_code_overrides_default():
    exc = MailGuardError("boom", code="MG-9999")
    assert exc.code == "MG-9999"


def test_subclass_default_code():
    exc = InvalidEmailError("bad address")
    assert exc.code == "MG-1201"


def test_str_contains_code_and_message():
    exc = MailGuardError("boom", code="MG-1001")
    assert str(exc) == "[MG-1001] boom"


def test_repr_contains_class_name():
    exc = InvalidEmailError("bad")
    assert "InvalidEmailError" in repr(exc)


def test_to_dict_shape():
    exc = MailGuardError("boom", context={"a": 1})
    payload = exc.to_dict()
    assert payload["code"] == "MG-1000"
    assert payload["context"] == {"a": 1}
    assert "timestamp" in payload


def test_equality_and_hash():
    a = MailGuardError("same", code="MG-1")
    b = MailGuardError("same", code="MG-1")
    c = MailGuardError("different", code="MG-1")
    assert a == b
    assert hash(a) == hash(b)
    assert a != c


def test_equality_with_non_exception_returns_notimplemented():
    exc = MailGuardError("boom")
    assert exc.__eq__(42) is NotImplemented


def test_cause_preserved():
    original = ValueError("root cause")
    exc = MailGuardError("boom", cause=original)
    assert exc.__cause__ is original
