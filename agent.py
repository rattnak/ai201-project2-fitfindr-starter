"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Complete tools.py and test each tool in isolation before implementing this file.

Usage (once implemented):
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import re

from tools import (
    search_listings,
    suggest_outfit,
    create_fit_card,
    estimate_price_fairness,
    get_trending_styles,
)


# ── query parsing ─────────────────────────────────────────────────────────────

# Common clothing size tokens we recognize as a standalone "size" filter.
_SIZE_TOKENS = {"xxs", "xs", "s", "m", "l", "xl", "xxl"}


def _parse_query(query: str) -> dict:
    """
    Extract a search description, optional size, and optional max_price from a
    natural-language query using lightweight regex/string rules (no LLM).

    Returns a dict: {"description": str, "size": str | None, "max_price": float | None}

    Examples:
        "vintage graphic tee under $30, size M"
            -> {"description": "vintage graphic tee", "size": "M", "max_price": 30.0}
        "90s track jacket in size M"
            -> {"description": "90s track jacket", "size": "M", "max_price": None}
    """
    text = query.strip()
    working = text  # we strip matched fragments out so they don't pollute the description

    # --- price: "under $30", "$30", "under 30 dollars", "below 25" ---
    max_price = None
    price_match = re.search(
        r"(?:under|below|less than|max|up to)?\s*\$?\s*(\d+(?:\.\d+)?)\s*(?:dollars|usd|bucks)?",
        working,
        flags=re.IGNORECASE,
    )
    # Only treat a number as a price if it's near a price cue ($ / under / dollars).
    price_cue = re.search(
        r"(?:under|below|less than|max|up to|\$)\s*\$?\s*(\d+(?:\.\d+)?)|"
        r"(\d+(?:\.\d+)?)\s*(?:dollars|usd|bucks)",
        working,
        flags=re.IGNORECASE,
    )
    if price_cue:
        num = price_cue.group(1) or price_cue.group(2)
        max_price = float(num)
        working = re.sub(
            r"(?:under|below|less than|max|up to)?\s*\$?\s*"
            + re.escape(num)
            + r"\s*(?:dollars|usd|bucks)?",
            " ",
            working,
            flags=re.IGNORECASE,
        )

    # --- size: explicit "size M" first, then a standalone size token ---
    size = None
    size_match = re.search(r"\bsize\s+([a-zA-Z0-9/]+)\b", working, flags=re.IGNORECASE)
    if size_match:
        size = size_match.group(1).upper()
        working = re.sub(r"\bsize\s+[a-zA-Z0-9/]+\b", " ", working, flags=re.IGNORECASE)
    else:
        for token in re.findall(r"\b[a-zA-Z]{1,3}\b", working):
            if token.lower() in _SIZE_TOKENS:
                size = token.upper()
                working = re.sub(rf"\b{token}\b", " ", working, count=1)
                break

    # --- description: whatever remains, cleaned of filler/punctuation ---
    description = re.sub(r"\b(in|under|for|the|a|an)\b", " ", working, flags=re.IGNORECASE)
    description = re.sub(r"[^\w\s/-]", " ", description)        # drop stray punctuation
    description = re.sub(r"\s+", " ", description).strip()

    return {"description": description, "size": size, "max_price": max_price}


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.

    You may add fields to this dict as needed for your implementation.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
        # --- stretch fields ---
        "price_check": None,         # dict from estimate_price_fairness
        "trending": [],              # list from get_trending_styles
        "adjustments": [],           # human-readable notes on relaxed constraints
    }


# ── search with retry/fallback (stretch) ──────────────────────────────────────

def _search_with_fallback(parsed: dict) -> tuple[list[dict], list[str]]:
    """
    Run search_listings, progressively loosening constraints if it returns nothing.

    Order of relaxation:
        1. Original (description, size, max_price).
        2. Drop the size filter.
        3. Also drop the price filter.

    Returns (results, adjustments) where `adjustments` is a list of human-readable
    notes describing which constraints were relaxed to produce the results. An empty
    `adjustments` list means the original query matched directly.
    """
    description = parsed["description"]
    size = parsed["size"]
    max_price = parsed["max_price"]

    # Attempt 1: original constraints.
    results = search_listings(description, size=size, max_price=max_price)
    if results:
        return results, []

    adjustments: list[str] = []

    # Attempt 2: drop size (only meaningful if a size was set).
    if size is not None:
        results = search_listings(description, size=None, max_price=max_price)
        if results:
            adjustments.append(f"removed the size filter (no exact match for size {size})")
            return results, adjustments

    # Attempt 3: drop price too (only meaningful if a price was set).
    if max_price is not None:
        results = search_listings(description, size=None, max_price=None)
        if results:
            if size is not None:
                adjustments.append(f"removed the size filter (no match for size {size})")
            adjustments.append(f"ignored the ${max_price:.0f} max price (nothing was under it)")
            return results, adjustments

    # Nothing worked, even fully relaxed.
    return [], adjustments


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.

    TODO — implement this function using the planning loop you designed in planning.md:

        Step 1: Initialize the session with _new_session().

        Step 2: Parse the user's query to extract a description, size, and
                max_price. You can use regex, string splitting, or ask the LLM
                to parse it — document your choice in planning.md.
                Store the result in session["parsed"].

        Step 3: Call search_listings() with the parsed parameters.
                Store results in session["search_results"].
                If no results: set session["error"] to a helpful message and
                return the session early. Do NOT proceed to suggest_outfit
                with empty input.

        Step 4: Select the item to use (e.g., the top result).
                Store it in session["selected_item"].

        Step 5: Call suggest_outfit() with the selected item and wardrobe.
                Store the result in session["outfit_suggestion"].

        Step 6: Call create_fit_card() with the outfit suggestion and selected item.
                Store the result in session["fit_card"].

        Step 7: Return the session.

    Before writing code, complete the Planning Loop and State Management sections
    of planning.md — your implementation should match what you described there.
    """
    # Step 1: fresh session — the single source of truth for this interaction.
    session = _new_session(query, wardrobe)

    # Step 2: parse the natural-language query into search parameters.
    parsed = _parse_query(query)
    session["parsed"] = parsed

    # Step 3: search WITH retry/fallback (stretch). If the original constraints
    # match nothing, the helper progressively loosens size, then price, and
    # records what it changed in session["adjustments"]. This is what makes the
    # loop adaptive: the same-looking query takes different paths depending on
    # what each search attempt returns.
    results, adjustments = _search_with_fallback(parsed)
    session["search_results"] = results
    session["adjustments"] = adjustments

    # --- ERROR BRANCH: no matches even fully relaxed → stop, do NOT style. ---
    if not results:
        session["error"] = (
            f"No listings matched \"{query}\", even after removing the size and "
            f"price filters. Try different keywords (e.g. a broader category or style)."
        )
        return session

    # Step 4: select the top-ranked match. This exact dict flows into the styling
    # tools and the price check — no re-querying, no hardcoding.
    session["selected_item"] = results[0]

    # Step 4b (stretch): is this a fair price vs. comparable listings?
    session["price_check"] = estimate_price_fairness(session["selected_item"])

    # Step 4c (stretch): what styles are trending in this size range?
    session["trending"] = get_trending_styles(size=parsed["size"], top_n=5)

    # Step 5: style the selected item against the wardrobe (handles empty wardrobe).
    session["outfit_suggestion"] = suggest_outfit(
        session["selected_item"], session["wardrobe"]
    )

    # Step 6: turn the styling suggestion into a shareable caption.
    session["fit_card"] = create_fit_card(
        session["outfit_suggestion"], session["selected_item"]
    )

    # Step 7: done — error stays None on the happy path.
    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"Price check: {session['price_check']['message']}")
        trend = ", ".join(t["tag"] for t in session["trending"])
        print(f"Trending: {trend}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print("\n\n=== Retry/fallback path (size has no match → loosened) ===\n")
    session_retry = run_agent(
        query="leather bomber jacket size XXS",
        wardrobe=get_example_wardrobe(),
    )
    if session_retry["error"]:
        print(f"Error: {session_retry['error']}")
    else:
        print(f"Found: {session_retry['selected_item']['title']}")
        print(f"Adjustments: {session_retry['adjustments']}")

    print("\n\n=== No-results path (even fully relaxed) ===\n")
    session2 = run_agent(
        query="designer ballgown unicorn sequins",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")
