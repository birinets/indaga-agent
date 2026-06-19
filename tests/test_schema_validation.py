"""P1.1 — dispatch-time schema validation (operations/_schema.py)."""

import pytest

from indaga.operations._schema import validate_params
from indaga.operations.model import OperationError


def _obj(**props):
    return {"type": "object", "properties": props}


def test_valid_passes():
    validate_params(_obj(rsid={"type": "string"}), {"rsid": "rs1"}, "t")


def test_wrong_type_rejected():
    with pytest.raises(OperationError) as e:
        validate_params(_obj(rsid={"type": "string"}), {"rsid": 123}, "t")
    assert e.value.code == "invalid_params"


def test_missing_required_rejected():
    s = {"type": "object", "properties": {"domain": {"type": "string"}}, "required": ["domain"]}
    with pytest.raises(OperationError):
        validate_params(s, {}, "domains.get")


def test_integer_not_string():
    s = _obj(limit={"type": "integer"})
    with pytest.raises(OperationError):
        validate_params(s, {"limit": "5"}, "t")
    validate_params(s, {"limit": 5}, "t")


def test_bool_is_not_integer():
    # bool is an int subclass in Python; the validator must reject it for an integer field.
    with pytest.raises(OperationError):
        validate_params(_obj(n={"type": "integer"}), {"n": True}, "t")


def test_enum():
    s = _obj(x={"type": "string", "enum": ["a", "b"]})
    validate_params(s, {"x": "a"}, "t")
    with pytest.raises(OperationError):
        validate_params(s, {"x": "c"}, "t")


def test_array_items():
    s = _obj(ids={"type": "array", "items": {"type": "string"}})
    validate_params(s, {"ids": ["a", "b"]}, "t")
    with pytest.raises(OperationError):
        validate_params(s, {"ids": ["a", 2]}, "t")


def test_extra_keys_allowed():
    validate_params(_obj(a={"type": "string"}), {"a": "x", "extra": 1}, "t")


def test_empty_schema_and_none_are_trivial():
    validate_params({}, {"anything": 1}, "t")
    validate_params(None, None, "t")
