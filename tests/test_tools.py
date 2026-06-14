"""
tests/test_tools.py

Pytest suite for the three FitFindr tools. Each tool has at least one test for
its failure mode. Run with:  pytest tests/

The search_listings tests are pure (no network). The suggest_outfit and
create_fit_card guard tests exercise the failure modes that do NOT call the LLM,
so the whole suite runs fast and offline.
"""

from tools import search_listings, suggest_outfit, create_fit_card
from utils.data_loader import get_empty_wardrobe


# ── search_listings ───────────────────────────────────────────────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0


def test_search_empty_results():
    # Impossible query → empty list, no exception.
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=10)
    assert all(item["price"] <= 10 for item in results)


def test_search_size_filter_case_insensitive():
    results = search_listings("jacket", size="m", max_price=None)
    # "m" should match sizes like "M" and "M/L".
    assert all("m" in item["size"].lower() for item in results)


def test_search_results_have_expected_fields():
    results = search_listings("denim", size=None, max_price=None)
    assert results, "expected at least one denim listing"
    expected = {
        "id", "title", "description", "category", "style_tags",
        "size", "condition", "price", "colors", "brand", "platform",
    }
    assert expected.issubset(results[0].keys())


# ── suggest_outfit ────────────────────────────────────────────────────────────

def test_suggest_outfit_empty_wardrobe_returns_string():
    # Empty wardrobe must not crash; returns a non-empty advice string.
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    out = suggest_outfit(item, get_empty_wardrobe())
    assert isinstance(out, str)
    assert out.strip() != ""


# ── create_fit_card ───────────────────────────────────────────────────────────

def test_create_fit_card_empty_outfit_returns_error_string():
    # Empty outfit → descriptive error string, not an exception.
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    card = create_fit_card("", item)
    assert isinstance(card, str)
    assert "no outfit" in card.lower()


def test_create_fit_card_whitespace_outfit_returns_error_string():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    card = create_fit_card("   ", item)
    assert isinstance(card, str)
    assert "no outfit" in card.lower()
