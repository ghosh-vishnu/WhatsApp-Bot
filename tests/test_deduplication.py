"""
Tests for duplicate detection via content hashing.
"""

from __future__ import annotations

import pytest

from app.utils.security import compute_content_hash


class TestDeduplication:
    def test_same_content_produces_same_hash(self):
        h1 = compute_content_hash("NSE", "TCS Ltd", "Quarterly Results")
        h2 = compute_content_hash("NSE", "TCS Ltd", "Quarterly Results")
        assert h1 == h2

    def test_different_content_produces_different_hash(self):
        h1 = compute_content_hash("NSE", "TCS Ltd", "Quarterly Results")
        h2 = compute_content_hash("NSE", "Infosys Ltd", "Quarterly Results")
        assert h1 != h2

    def test_different_source_produces_different_hash(self):
        h1 = compute_content_hash("NSE", "TCS Ltd", "Quarterly Results")
        h2 = compute_content_hash("BSE", "TCS Ltd", "Quarterly Results")
        assert h1 != h2

    def test_hash_is_64_char_hex(self):
        h = compute_content_hash("NSE", "Company", "Title")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_case_insensitive_normalisation(self):
        h1 = compute_content_hash("NSE", "TCS Ltd", "QUARTERLY RESULTS")
        h2 = compute_content_hash("nse", "tcs ltd", "quarterly results")
        assert h1 == h2

    def test_whitespace_normalisation(self):
        h1 = compute_content_hash("NSE", "  TCS Ltd  ", "  Results  ")
        h2 = compute_content_hash("NSE", "TCS Ltd", "Results")
        assert h1 == h2

    def test_with_description(self):
        h1 = compute_content_hash("NSE", "TCS", "Title", "Description A")
        h2 = compute_content_hash("NSE", "TCS", "Title", "Description B")
        assert h1 != h2

    def test_without_description(self):
        h1 = compute_content_hash("NSE", "TCS", "Title")
        h2 = compute_content_hash("NSE", "TCS", "Title", None)
        assert h1 == h2
