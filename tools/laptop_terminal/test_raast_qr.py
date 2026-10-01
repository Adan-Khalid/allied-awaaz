"""Tests for the Raast amount QR. Run: python -m pytest tools/laptop_terminal -q"""
import pytest

from raast_qr import RaastQrError, build, crc16_ccitt, parse, validate, with_amount

# Published example from the open-source raast-qr project (EMVCo MPM, GUID pk.raast).
EXAMPLE = ("00020101021226290008pk.raast0113+92336786582352045411530358654071250.505802PK"
           "5915Faizan Shurjeel6006Lahore62160112INV-2026-00163044A1D")
STATIC = build([(t, "11" if t == "01" else v) for t, v in parse(EXAMPLE) if t != "54"])


def test_crc_matches_published_example():
    assert crc16_ccitt(EXAMPLE[:-4]) == "4A1D"


def test_amount_is_set_and_account_untouched():
    out = with_amount(STATIC, 1250)
    tags = dict(parse(out))
    assert tags["01"] == "12" and tags["54"] == "1250"
    assert tags["26"] == dict(parse(STATIC))["26"]        # account template copied byte for byte
    assert crc16_ccitt(out[:-4]) == out[-4:]
    assert [t for t, _ in parse(out)] == sorted(t for t, _ in parse(out))


def test_amount_replaces_an_existing_amount():
    assert dict(parse(with_amount(EXAMPLE, 99)))["54"] == "99"


def test_validate_masks_account():
    info = validate(STATIC)
    assert info["account_hint"] == "•••• 5823" and info["merchant"] == "Faizan Shurjeel"


@pytest.mark.parametrize("bad", [
    STATIC[:-4] + "0000",                                   # wrong checksum
    STATIC.replace("5802PK", "5802AE"),                     # not Pakistan
    "https://example.com/pay/abc",                          # not EMVCo
    build([(t, v.replace("pk.raast", "com.other")) for t, v in parse(STATIC)]),  # no Raast account
])
def test_rejects_non_raast(bad):
    with pytest.raises(RaastQrError):
        validate(bad)
