# FitFindr 🛍️

FitFindr is a secondhand-shopping styling agent. You describe what you want in
plain language; it searches a mock listings dataset, picks the best find, styles
it against your existing wardrobe, and writes a short, shareable "fit card"
caption for the piece. It runs as a small **planning loop** over three tools,
passing state through a single session dict, with a guarded error branch so it
never styles an empty search result.

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
python agent.py          # CLI: runs the happy path + the no-results branch
pytest tests/            # runs the tool test suite
```

Open the URL shown in your terminal (usually http://localhost:7860). Enter a
query, pick **Example wardrobe** or **Empty wardrobe (new user)**, and hit
**Find it** — the three panels fill with the top listing, an outfit idea, and a
fit card.

---

## Tool Inventory

All three tools live in [tools.py](tools.py) and can be called and tested in
isolation.

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

---

## How the Planning Loop Works

The loop ([`run_agent()` in agent.py](agent.py)) is a **fixed, conditional
pipeline** — search → suggest → card — not a free-form "LLM decides" loop. What
matters is that it *branches*: it does not call all three tools unconditionally.

1. **Parse** the query (`_parse_query`, regex/string rules) into
   `{description, size, max_price}`.
2. **Search** with those params.
   - **If `results == []`** → write a helpful message to `session["error"]` and
     **return early**. The styling tools are never called on empty input. *(This
     is the decision that makes the loop a real planning loop.)*
   - **If results found** → `selected_item = results[0]` and continue.
3. **Suggest** an outfit for `selected_item` against the wardrobe.
4. **Card:** turn that suggestion into a caption.
5. **Return** the session.

The agent therefore behaves differently per input: an impossible query stops
after step 2 with `fit_card is None`; a matchable query runs all three tools.

## State Management

All state for one interaction lives in a **single session dict** built by
`_new_session(query, wardrobe)` — the single source of truth. Each step writes
its result into the session, and the next step reads from it; there are no
globals and no re-prompting.

| Key | Set by | Read by |
|-----|--------|---------|
| `parsed` | parse | search args |
| `search_results` | search | branch + selection |
| `selected_item` | success branch | suggest_outfit & create_fit_card |
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
| `search_listings` | No results | Returns `[]`; the loop sets `session["error"]` and returns early without styling. |
| `suggest_outfit` | Empty wardrobe | Falls back to general styling advice; never crashes or returns "". |
| `create_fit_card` | Empty/whitespace outfit | Returns a descriptive error string instead of raising. |

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
