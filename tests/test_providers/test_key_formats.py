"""Tests for provider API key format helpers."""

from providers.key_formats import is_valid_gemini_key_format


def test_gemini_key_format_accepts_legacy_aiza_keys():
    assert is_valid_gemini_key_format("AIza" + "A" * 35)


def test_gemini_key_format_accepts_new_aq_keys():
    assert is_valid_gemini_key_format("AQ.Ab8RN6J12345678")
    assert is_valid_gemini_key_format("AQ.Ab8RN6J.......")


def test_gemini_key_format_rejects_unknown_prefixes():
    assert not is_valid_gemini_key_format("sk-not-a-gemini-key")


def test_gemini_key_format_rejects_short_or_spaced_aq_keys():
    assert not is_valid_gemini_key_format("AQ.")
    assert not is_valid_gemini_key_format("AQ.Ab8 RN6J")
