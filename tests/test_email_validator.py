import pytest

from core.exceptions import InvalidEmailError, SuspiciousEmailPatternError
from validators.email_validator import EmailValidator


@pytest.mark.parametrize("address", [
    "user@example.com",
    "first.last@sub.example.co.uk",
    "user+tag@example.org",
])
def test_valid_addresses(address):
    assert EmailValidator.is_valid(address)


@pytest.mark.parametrize("address", [
    "",
    "not-an-email",
    "@example.com",
    "user@",
    "user@@example.com",
])
def test_invalid_format(address):
    assert not EmailValidator.is_valid(address)
    with pytest.raises(InvalidEmailError):
        EmailValidator.validate(address)


def test_suspicious_pattern_rejected():
    with pytest.raises(SuspiciousEmailPatternError):
        EmailValidator.validate("user..name@example.com")


@pytest.mark.asyncio
async def test_validate_batch_yields_results():
    addresses = ["good@example.com", "bad-address"]
    results = [r async for r in EmailValidator.validate_batch(addresses)]
    assert results[0][0] == "good@example.com"
    assert results[0][1] is True
    assert results[1][1] is False


@pytest.mark.asyncio
async def test_validate_all_raises_on_invalid():
    with pytest.raises(InvalidEmailError):
        await EmailValidator.validate_all(["good@example.com", "bad"])


@pytest.mark.asyncio
async def test_validate_all_passes_when_clean():
    result = await EmailValidator.validate_all(["a@example.com", "b@example.com"])
    assert result == ["a@example.com", "b@example.com"]
