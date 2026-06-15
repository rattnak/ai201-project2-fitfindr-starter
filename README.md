# FitFindr 🛍️

FitFindr is a secondhand-shopping styling agent. You describe what you want in
plain language; it searches a mock listings dataset, picks the best find, styles
it against your existing wardrobe, and writes a short, shareable "fit card"
caption for the piece. It runs as a small **planning loop** over five tools,
passing state through a single session dict, with a guarded error branch so it
never styles an empty search result.

**All required features are implemented, plus all four stretch features** (price
comparison, style profile memory, trend awareness, and retry/fallback search) —
see [Stretch Features](#stretch-features) below.

---

## Setup

```bash
python -m venv .venv          # Python 3.10+ (uses str | None type hints)
source .venv/bin/activate
pip install -r requirements.txt
```

Set your Groq API key in a `.env` file in the project root (free key at
[console.groq.com](https://console.groq.com)):

```
GROQ_API_KEY=your_key_here
```

## Run

```bash
python app.py            # launches the Gradio UI (http://localhost:7860)
python agent.py          # CLI: happy path + retry/fallback + no-results branch
pytest tests/            # runs the full test suite (21 tests, offline)
```

Open the URL shown in your terminal (usually http://localhost:7860). Enter a
query, pick **Example wardrobe**, **Empty wardrobe (new user)**, or **Saved
profile**, and hit **Find it** — the three panels fill with the top listing
(plus a price-fairness verdict and trending styles), an outfit idea, and a fit
card.

---

## Tool Inventory

The three required tools (1–3) plus two stretch tools (4–5) live in
[tools.py](tools.py) and can be called and tested in isolation.

### 1. `search_listings(description, size, max_price) -> list[dict]`
**Purpose:** Find matching secondhand listings. Pure Python — no LLM.
| Param | Type | Meaning |
|-------|------|---------|
| `description` | `str` | Keywords; each word is substring-matched (case-insensitive) against each listing's `title`, `description`, `category`, and `style_tags`. |
| `size` | `str \| None` | Case-insensitive substring size filter (`"m"` matches `"S/M"`). `None` skips it. |
| `max_price` | `float \| None` | Inclusive price ceiling. `None` skips it. |

**Output:** a `list[dict]` of full listing dicts (`id, title, description,
category, style_tags, size, condition, price, colors, brand, platform`), sorted
by keyword-overlap score (best first), zero-score items dropped. Returns `[]`
when nothing matches — never raises.

### 2. `suggest_outfit(new_item, wardrobe) -> str`
**Purpose:** Style the selected item against the user's wardrobe. Calls Groq
`llama-3.3-70b-versatile` (temperature 0.7).
| Param | Type | Meaning |
|-------|------|---------|
| `new_item` | `dict` | The selected listing dict. |
| `wardrobe` | `dict` | `{"items": [...]}` in the wardrobe-schema shape. May be empty. |

**Output:** a non-empty `str`. With a populated wardrobe it names specific owned
pieces; with an empty wardrobe it returns general styling advice instead.

### 3. `create_fit_card(outfit, new_item) -> str`
**Purpose:** Turn the styling suggestion into a casual social-media caption.
Calls Groq `llama-3.3-70b-versatile` (temperature 0.9 for variety).
| Param | Type | Meaning |
|-------|------|---------|
| `outfit` | `str` | The styling string from `suggest_outfit()`. |
| `new_item` | `dict` | The listing dict, so the caption can mention title/price/platform. |

**Output:** a 2–4 sentence caption `str` (first-person OOTD voice, item name +
price + platform mentioned once each). Empty `outfit` → a descriptive error
string, not an exception.

### 4. `estimate_price_fairness(item, listings=None) -> dict` *(stretch)*
**Purpose:** Judge whether a listing's price is fair vs. comparable items. Pure Python.
| Param | Type | Meaning |
|-------|------|---------|
| `item` | `dict` | The selected listing dict. |
| `listings` | `list[dict] \| None` | Comparison pool; defaults to the full dataset. |

**Output:** a `dict` with `verdict` (`"great deal"` / `"fair"` / `"a bit high"` /
`"no comparables"`), the comparable count/avg/low/high, and a one-line `message`.
Comparables = same category + at least one shared style tag. No comparables →
`verdict="no comparables"`, never raises.

### 5. `get_trending_styles(size=None, top_n=5) -> list[dict]` *(stretch)*
**Purpose:** Surface popular style tags (a stand-in for live platform trends).
Pure Python.
| Param | Type | Meaning |
|-------|------|---------|
| `size` | `str \| None` | Optional size filter (same matching as search). |
| `top_n` | `int` | How many trending tags to return. |

**Output:** a `list[dict]` of `{"tag", "count"}`, most popular first. `[]` if the
size filter matches nothing — never raises.

---

## How the Planning Loop Works

The loop ([`run_agent()` in agent.py](agent.py)) is a **conditional pipeline** —
not a free-form "LLM decides" loop. What matters is that it *branches and adapts*:
it does not call every tool unconditionally, and its search path changes based on
what each attempt returns.

1. **Parse** the query (`_parse_query`, regex/string rules) into
   `{description, size, max_price}`.
2. **Search with retry/fallback** (`_search_with_fallback`). This is the adaptive
   core:
   - Try the original `(description, size, max_price)`.
   - **If empty** → drop the **size** filter and retry.
   - **If still empty** → also drop the **price** filter and retry.
   - Each relaxation is recorded in `session["adjustments"]` so the user is told
     exactly what changed.
   - **If still empty even fully relaxed** → write a message to `session["error"]`
     and **return early**. The styling tools are never called on empty input.
   - **If results found** (at any attempt) → `selected_item = results[0]`.
3. **Price check** (stretch) — `estimate_price_fairness(selected_item)` →
   `session["price_check"]`.
4. **Trend check** (stretch) — `get_trending_styles(size)` → `session["trending"]`.
5. **Suggest** an outfit for `selected_item` against the wardrobe.
6. **Card:** turn that suggestion into a caption.
7. **Return** the session.

The agent therefore behaves differently per input: an impossible query stops
early with `fit_card is None`; a query whose size has no match takes the
fallback path and reports the loosening; a clean match runs the full pipeline.

## State Management

All state for one interaction lives in a **single session dict** built by
`_new_session(query, wardrobe)` — the single source of truth. Each step writes
its result into the session, and the next step reads from it; there are no
globals and no re-prompting.

| Key | Set by | Read by |
|-----|--------|---------|
| `parsed` | parse | search args |
| `search_results` | search | branch + selection |
| `adjustments` | retry/fallback | UI (relaxation note) |
| `selected_item` | success branch | suggest_outfit, create_fit_card, price check |
| `price_check` | estimate_price_fairness | UI |
| `trending` | get_trending_styles | UI |
| `outfit_suggestion` | suggest_outfit | create_fit_card |
| `fit_card` | create_fit_card | UI |
| `error` | error branch | UI (checked first) |

The **exact same `selected_item` dict** chosen in step 2 is the object passed
into both `suggest_outfit` and `create_fit_card` — verified with
`session["selected_item"] is session["search_results"][0] → True`. So the listing
shown in the UI is provably the one that was styled and captioned.
`handle_query()` in [app.py](app.py) maps the returned session onto the three
panels.

---

## Error Handling (per tool, with a concrete example)

Each failure mode was deliberately triggered; full output is saved in
[docs/failure_modes.txt](docs/failure_modes.txt).

| Tool | Failure mode | What the agent does |
|------|-------------|---------------------|
| `search_listings` | No results | Returns `[]`; the loop first **retries with loosened constraints**, then sets `session["error"]` and returns early without styling. |
| `suggest_outfit` | Empty wardrobe | Falls back to general styling advice; never crashes or returns "". |
| `create_fit_card` | Empty/whitespace outfit | Returns a descriptive error string instead of raising. |
| `estimate_price_fairness` | No comparable listings | Returns `verdict="no comparables"` with a message; never raises. |
| `get_trending_styles` | Size matches nothing | Returns `[]`; the UI simply omits the trend note. |
| profile memory | Missing/corrupt profile file | `load_profile()` returns an empty default profile; never raises. |

**Concrete example — no results (from `agent.py`):**

```
$ python -c "from tools import search_listings; print(search_listings('designer ballgown', size='XXS', max_price=5))"
[]
```

Run through the full agent, the same impossible query produces:

```
error: No listings matched "designer ballgown size XXS under $5".
       Try broadening your keywords, raising your max price, or removing the size filter.
fit_card is None: True          # suggest_outfit / create_fit_card never ran
```

**Concrete example — empty outfit string:**

```
$ python -c "from tools import create_fit_card; print(create_fit_card('', {'title':'x'}))"
Can't make a fit card — no outfit suggestion was provided.
```

LLM calls in tools 2 and 3 are additionally wrapped in `try/except`, returning a
safe fallback string on network/API errors so the UI always has something to
show.

---

## Stretch Features

All four stretch features are implemented. `planning.md` was updated with a spec
for each before it was built.

### 1. Price comparison — `estimate_price_fairness` (Tool 4)
After the loop selects an item, it compares the price against listings in the
same category that share a style tag, and reports a verdict. Shown in the listing
panel, e.g. *"💰 Price check: $18 vs. an average of $22 across 14 similar tops
(range $15–$35) — great deal."*

### 2. Style profile memory — [profile.py](profile.py)
A JSON persistence layer (`data/user_profile.json`, gitignored). Picking the
**Saved profile** wardrobe option loads the stored wardrobe so a returning user
doesn't re-enter it; after each successful run the agent records the selected
item's style tags into `preferred_styles`. Missing/corrupt files degrade to an
empty profile.

### 3. Trend awareness — `get_trending_styles` (Tool 5)
Aggregates style-tag frequency across the dataset (a stand-in for live platform
activity, optionally filtered by size) and surfaces the top tags. Shown in the
listing panel, e.g. *"📈 Trending right now: vintage, classic, streetwear…"*.

### 4. Retry logic with fallback — in the planning loop
The key adaptive behavior: when `search_listings` returns nothing, the agent
**retries with progressively loosened constraints** (drop size → drop price)
instead of giving up, and tells the user exactly what it relaxed. Implemented in
`_search_with_fallback()` in [agent.py](agent.py); the relaxation notes flow to
`session["adjustments"]` and appear as *"⚠️ Adjusted your search: removed the
size filter (no exact match for size XXS)."* in the UI.

Example (from `python agent.py`):

```
=== Retry/fallback path (size has no match → loosened) ===
Found: 90s Leather Bomber — Black
Adjustments: ['removed the size filter (no exact match for size XXS)']
```

Tests for all stretch features are in
[tests/test_stretch.py](tests/test_stretch.py) (13 tests, all offline).

---

## AI Usage

I used **Claude (in Claude Code)** to implement the project from my
`planning.md` spec. Two specific instances:

1. **`search_listings` (Milestone 3).** *Input:* the Tool 1 spec block (the three
   params, the relevance-scoring rule, and the "return `[]`, never raise" failure
   mode) plus the `load_listings()` docstring. *Produced:* a filter-then-score
   function. *What I checked/changed before trusting it:* I verified it filtered
   on **all three** parameters and used case-insensitive **substring** size
   matching (so `"M"` matches `"S/M"`), made it drop zero-score listings, and
   confirmed an impossible query returns `[]` rather than throwing. I locked the
   behavior in with three pytest cases (results / empty / price filter) before
   moving on.

2. **The planning loop `run_agent()` (Milestone 4).** *Input:* the Architecture
   diagram (ASCII + Mermaid) and the Planning Loop + State Management sections.
   *Produced:* the step-by-step loop. *What I checked/changed before trusting it:*
   I confirmed it **branches on the empty search result and returns early**
   (rather than calling all three tools unconditionally), that every value is
   written into the session dict, and that the no-results query leaves
   `fit_card is None`. I also verified `selected_item is search_results[0]` to
   prove state is passed by reference, not re-derived.

---

## Spec Reflection

Writing the spec first paid off most on the **planning loop**: because
`planning.md` already named the exact branch ("if `results == []`, set error and
return early; else `selected_item = results[0]`"), the generated loop matched the
design on the first pass and I didn't have to untangle an agent that called every
tool every time. The place reality differed from the plan was **query parsing** —
the spec hand-waved it as "regex or LLM," and in practice the regex needed care
to avoid grabbing a size token out of the description or treating a stray number
as a price. I kept the regex approach (fast, offline, deterministic for tests)
and documented its limits rather than reaching for an LLM parse. If I extended
the project, the parser is the first thing I'd harden or swap for a small
LLM-based `parse_query` tool.
