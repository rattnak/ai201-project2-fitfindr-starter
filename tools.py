"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform

    TODO:
        1. Load all listings with load_listings().
        2. Filter by max_price and size (if provided).
        3. Score each remaining listing by keyword overlap with `description`.
        4. Drop any listings with a score of 0 (no relevant matches).
        5. Sort by score, highest first, and return the listing dicts.

    Before writing code, fill in the Tool 1 section of planning.md.
    """
    listings = load_listings()

    keywords = [w for w in description.lower().split() if w]
    size_filter = size.lower().strip() if size else None

    scored: list[tuple[int, dict]] = []
    for listing in listings:
        # Price filter (inclusive).
        if max_price is not None and listing["price"] > max_price:
            continue

        # Size filter (case-insensitive substring, e.g. "m" matches "S/M").
        if size_filter is not None and size_filter not in listing["size"].lower():
            continue

        # Score by keyword overlap across the searchable text fields.
        haystack = " ".join(
            [
                listing["title"],
                listing["description"],
                listing["category"],
                " ".join(listing["style_tags"]),
            ]
        ).lower()
        score = sum(1 for kw in keywords if kw in haystack)

        # Drop listings with no relevant keyword match.
        if score > 0:
            scored.append((score, listing))

    # Highest score first; stable for ties (preserves dataset order).
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [listing for _, listing in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.

    TODO:
        1. Check whether wardrobe['items'] is empty.
        2. If empty: call the LLM with a prompt for general styling ideas
           (what kinds of items pair well, what vibe it suits, etc.).
        3. If not empty: format the wardrobe items into a prompt and ask
           the LLM to suggest specific outfit combinations using the new item
           and named pieces from the wardrobe.
        4. Return the LLM's response as a string.

    Before writing code, fill in the Tool 2 section of planning.md.
    """
    item_desc = (
        f"{new_item.get('title', 'this piece')} "
        f"(category: {new_item.get('category', 'unknown')}, "
        f"colors: {', '.join(new_item.get('colors', [])) or 'n/a'}, "
        f"style: {', '.join(new_item.get('style_tags', [])) or 'n/a'}, "
        f"condition: {new_item.get('condition', 'n/a')})"
    )

    items = wardrobe.get("items", []) if wardrobe else []

    if not items:
        # Empty wardrobe: give general styling advice, do not invent pieces.
        prompt = (
            "You are a thoughtful personal stylist for secondhand fashion.\n"
            f"A shopper is considering this thrifted item: {item_desc}.\n"
            "They have NOT entered any wardrobe items yet.\n"
            "Give general styling advice for this piece in 2-4 sentences: what "
            "silhouettes, colors, and types of pieces pair well with it, and what "
            "vibe or occasions it suits. Do not reference specific items they own, "
            "since you don't know their wardrobe."
        )
    else:
        wardrobe_lines = "\n".join(
            f"- {it.get('name', 'item')} "
            f"({it.get('category', '')}; {', '.join(it.get('colors', []))})"
            + (f" — {it['notes']}" if it.get("notes") else "")
            for it in items
        )
        prompt = (
            "You are a thoughtful personal stylist for secondhand fashion.\n"
            f"A shopper is considering this thrifted item: {item_desc}.\n\n"
            "Here is their existing wardrobe:\n"
            f"{wardrobe_lines}\n\n"
            "Suggest 1-2 complete outfits that style the new item with SPECIFIC "
            "pieces from their wardrobe (name the pieces). Keep it to 2-4 sentences "
            "total. Include one concrete styling tip (e.g. tuck, roll, layer). "
            "Be specific and practical, not generic."
        )

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=300,
        )
        text = (response.choices[0].message.content or "").strip()
        if text:
            return text
    except Exception as exc:  # network/API failure — degrade gracefully.
        return (
            f"Style {new_item.get('title', 'this piece')} as a versatile layering "
            f"piece — lean into its {', '.join(new_item.get('style_tags', []) or ['vintage'])} "
            f"feel and build the rest of the look around its colors. "
            f"(Styling assistant was unavailable: {exc})"
        )

    # Fallback if the model returned an empty string.
    return (
        f"Style {new_item.get('title', 'this piece')} as a versatile staple — pair "
        f"it with simple bottoms and let its {', '.join(new_item.get('colors', []) or ['neutral'])} "
        f"tones lead the outfit."
    )


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)

    TODO:
        1. Guard against an empty or whitespace-only outfit string.
        2. Build a prompt that gives the LLM the item details and the outfit,
           and asks for a caption matching the style guidelines above.
        3. Call the LLM and return the response.

    Before writing code, fill in the Tool 3 section of planning.md.
    """
    # Guard against missing/incomplete outfit input.
    if not outfit or not outfit.strip():
        return "Can't make a fit card — no outfit suggestion was provided."

    title = new_item.get("title", "this thrifted find")
    price = new_item.get("price")
    price_str = f"${price:.0f}" if isinstance(price, (int, float)) else "a steal"
    platform = new_item.get("platform", "secondhand")

    prompt = (
        "Write a short, casual social-media caption (an Instagram/TikTok 'fit card') "
        "for a thrifted outfit. Voice: first-person, authentic OOTD energy, NOT a "
        "product description. 2-4 sentences. Mention the item name, its price, and the "
        "platform once each, woven in naturally. Capture the outfit's vibe in specific "
        "terms. A tasteful emoji or two is fine.\n\n"
        f"Item: {title}\n"
        f"Price: {price_str}\n"
        f"Platform: {platform}\n"
        f"Outfit / styling: {outfit}\n\n"
        "Caption:"
    )

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,  # high temperature → varied captions across runs
            max_tokens=200,
        )
        text = (response.choices[0].message.content or "").strip()
        if text:
            return text
    except Exception as exc:  # network/API failure — degrade gracefully.
        return (
            f"scored this {title} on {platform} for {price_str} and it's instantly a "
            f"favorite ✨ ({exc})"
        )

    # Fallback if the model returned an empty string.
    return (
        f"thrifted this {title} off {platform} for {price_str} and i'm obsessed — "
        f"already planning the next fit around it ✨"
    )
