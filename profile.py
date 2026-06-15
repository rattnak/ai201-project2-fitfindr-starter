"""
profile.py  (Stretch feature: Style profile memory)

A tiny persistence layer so a returning user does not have to re-describe their
wardrobe every session. The profile is a JSON file on disk holding:

    {
      "wardrobe": {"items": [...]},        # same shape as the wardrobe schema
      "preferred_styles": ["vintage", ...] # style tags learned from selections
    }

All functions degrade gracefully: a missing or corrupt file yields an empty
default profile rather than raising.
"""

import json
import os

_PROFILE_PATH = os.path.join(os.path.dirname(__file__), "data", "user_profile.json")


def _empty_profile() -> dict:
    """Return a fresh, empty profile."""
    return {"wardrobe": {"items": []}, "preferred_styles": []}


def load_profile(path: str = _PROFILE_PATH) -> dict:
    """
    Load the saved style profile from disk.

    Returns a profile dict. If the file is missing or corrupt, returns an empty
    default profile — never raises.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Normalize shape so callers can rely on the keys existing.
        wardrobe = data.get("wardrobe") or {"items": []}
        if "items" not in wardrobe:
            wardrobe["items"] = []
        return {
            "wardrobe": wardrobe,
            "preferred_styles": data.get("preferred_styles", []),
        }
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return _empty_profile()


def save_profile(profile: dict, path: str = _PROFILE_PATH) -> bool:
    """
    Write the profile to disk. Returns True on success, False on failure
    (e.g. permission error) — never raises.
    """
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(profile, f, indent=2)
        return True
    except OSError:
        return False


def get_saved_wardrobe(path: str = _PROFILE_PATH) -> dict:
    """Convenience: return just the saved wardrobe dict ({"items": [...]})."""
    return load_profile(path)["wardrobe"]


def update_profile_from_session(session: dict, path: str = _PROFILE_PATH) -> dict:
    """
    Learn from a completed agent run: record the style tags of the selected item
    into the profile's preferred_styles (most-recent-first, de-duplicated), and
    persist the wardrobe that was used this session.

    Returns the updated profile. Safe to call even if the session ended in an
    error (no selected_item) — in that case only the wardrobe is persisted.
    """
    profile = load_profile(path)

    # Persist the wardrobe used this session so it carries to next time.
    if session.get("wardrobe") and session["wardrobe"].get("items"):
        profile["wardrobe"] = session["wardrobe"]

    # Learn preferred styles from the selected item's tags.
    item = session.get("selected_item")
    if item:
        existing = profile.get("preferred_styles", [])
        new_tags = list(item.get("style_tags", []))
        # New tags first, then prior ones, de-duplicated, capped at 12.
        merged: list[str] = []
        for tag in new_tags + existing:
            if tag not in merged:
                merged.append(tag)
        profile["preferred_styles"] = merged[:12]

    save_profile(profile, path)
    return profile


# --- Quick sanity check ---
if __name__ == "__main__":
    import tempfile

    tmp = os.path.join(tempfile.gettempdir(), "fitfindr_profile_demo.json")
    print("empty load:", load_profile(tmp))
    fake_session = {
        "wardrobe": {"items": [{"id": "w1", "name": "x", "style_tags": ["denim"]}]},
        "selected_item": {"id": "lst_006", "style_tags": ["graphic tee", "grunge"]},
    }
    print("after update:", update_profile_from_session(fake_session, tmp))
    print("reload:", load_profile(tmp))
    os.remove(tmp)
