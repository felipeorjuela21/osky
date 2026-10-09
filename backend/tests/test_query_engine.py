from backend.app.services.query_engine import validate_dataset, validate_field
import pytest

def test_allowed_dataset():
    validate_dataset("customers")

def test_invalid_dataset():
    with pytest.raises(ValueError):
        validate_dataset("secret_table")

def test_allowed_field():
    validate_field("sales", "amount")

def test_invalid_field():
    with pytest.raises(ValueError):
        validate_field("sales", "password")
