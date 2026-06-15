"""
tests/test_stretch.py

Pytest suite for the stretch features:
  - estimate_price_fairness (Tool 4)
  - get_trending_styles (Tool 5)
  - retry/fallback search in the planning loop (_search_with_fallback)
  - style profile memory (profile.py)

All tests are pure Python (no network / no LLM), so the suite stays fast.
Run with:  pytest tests/
"""

import os
import tempfile

from tools import estimate_price_fairness, get_trending_styles, search_listings
from utils.data_loader import load_listings
from agent import _search_with_fallback
from profile import (
    load_profile,
    save_profile,
    get_saved_wardrobe,
    update_profile_from_session,
)


# ── estimate_price_fairness ─────────────────────────────────────────────────────

def test_price_fairness_returns_expected_shape():
    item = load_listings()[0]
    result = estimate_price_fairness(item)
    for key in (
        "verdict", "item_price", "comp_count", "comp_avg",
        "comp_low", "comp_high", "message",
    ):
        assert key in result
    assert result["verdict"] in (
        "great deal", "fair", "a bit high", "no comparables",
    )


def test_price_fairness_no_comparables():
    # An item with a category/tag combo that nothing else shares.
    weird = {
        "id": "zzz",
        "category": "tops",
        "style_tags": ["__no_such_tag__"],
        "price": 99.0,
        "title": "weird",
    }
    result = estimate_price_fairness(weird)
    assert result["verdict"] == "no comparables"
    assert result["comp_count"] == 0


def test_price_fairness_great_deal_when_cheap():
    listings = load_listings()
    item = next(l for l in listings if l["id"] == "lst_002")  # Y2K Baby Tee, $18
    result = estimate_price_fairness(item, listings)
    assert result["comp_count"] > 0
    # $18 is below the comparable average for tops in this dataset.
    assert result["item_price"] <= result["comp_avg"]


# ── get_trending_styles ─────────────────────────────────────────────────────────

def test_trending_returns_ranked_tags():
    trending = get_trending_styles(top_n=5)
    assert isinstance(trending, list)
    assert len(trending) == 5
    counts = [t["count"] for t in trending]
    assert counts == sorted(counts, reverse=True)  # descending


def test_trending_empty_for_impossible_size():
    assert get_trending_styles(size="ZZZ", top_n=5) == []


def test_trending_respects_top_n():
    assert len(get_trending_styles(top_n=3)) == 3


# ── retry / fallback search ─────────────────────────────────────────────────────

def test_fallback_no_adjustment_when_query_matches():
    parsed = {"description": "vintage graphic tee", "size": None, "max_price": 50}
    results, adjustments = _search_with_fallback(parsed)
    assert results
    assert adjustments == []  # matched directly, nothing relaxed


def test_fallback_drops_size_when_no_size_match():
    # A leather bomber exists, but not in size XXS → size filter should be dropped.
    parsed = {"description": "leather bomber", "size": "XXS", "max_price": None}
    results, adjustments = _search_with_fallback(parsed)
    assert results
    assert any("size" in note for note in adjustments)


def test_fallback_returns_empty_when_truly_no_match():
    parsed = {"description": "unicorn sequin ballgown", "size": "XXS", "max_price": 5}
    results, adjustments = _search_with_fallback(parsed)
    assert results == []


# ── style profile memory ────────────────────────────────────────────────────────

def _tmp_path():
    return os.path.join(tempfile.gettempdir(), "fitfindr_test_profile.json")


def test_profile_missing_file_returns_empty_default():
    path = _tmp_path()
    if os.path.exists(path):
        os.remove(path)
    profile = load_profile(path)
    assert profile == {"wardrobe": {"items": []}, "preferred_styles": []}


def test_profile_corrupt_file_returns_empty_default():
    path = _tmp_path()
    with open(path, "w", encoding="utf-8") as f:
        f.write("{ this is not valid json")
    try:
        profile = load_profile(path)
        assert profile["wardrobe"]["items"] == []
        assert profile["preferred_styles"] == []
    finally:
        os.remove(path)


def test_profile_round_trip_and_learning():
    path = _tmp_path()
    try:
        session = {
            "wardrobe": {"items": [{"id": "w1", "name": "jeans", "style_tags": ["denim"]}]},
            "selected_item": {"id": "lst_006", "style_tags": ["graphic tee", "grunge"]},
        }
        update_profile_from_session(session, path)

        reloaded = load_profile(path)
        assert reloaded["wardrobe"]["items"][0]["id"] == "w1"
        # Selected item's tags are learned, most-recent first.
        assert reloaded["preferred_styles"][:2] == ["graphic tee", "grunge"]

        # get_saved_wardrobe returns just the wardrobe.
        assert get_saved_wardrobe(path)["items"][0]["name"] == "jeans"
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_save_profile_returns_true_on_success():
    path = _tmp_path()
    try:
        ok = save_profile({"wardrobe": {"items": []}, "preferred_styles": ["y2k"]}, path)
        assert ok is True
        assert load_profile(path)["preferred_styles"] == ["y2k"]
    finally:
        if os.path.exists(path):
            os.remove(path)
