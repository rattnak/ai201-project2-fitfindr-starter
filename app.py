"""
app.py

Gradio interface for FitFindr. The layout and wiring are already set up —
your job is to fill in handle_query() so it calls run_agent() and maps
the session results to the three output panels.

Run with:
    python app.py

Then open the localhost URL shown in your terminal (usually http://localhost:7860,
but check your terminal — the port may differ).
"""

import gradio as gr

from agent import run_agent
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe
from profile import get_saved_wardrobe, update_profile_from_session


# ── query handler ─────────────────────────────────────────────────────────────

def handle_query(user_query: str, wardrobe_choice: str) -> tuple[str, str, str]:
    """
    Called by Gradio when the user submits a query.

    Args:
        user_query:     The text the user typed into the search box.
        wardrobe_choice: "Example wardrobe", "Empty wardrobe (new user)", or
                         "Saved profile" (stretch: loads the persisted wardrobe).

    Returns:
        A tuple of three strings:
            (listing_text, outfit_suggestion, fit_card)
        Each string maps to one of the three output panels in the UI. The
        listing panel also surfaces the stretch features (retry adjustments,
        price-fairness verdict, and trending styles).
    """
    # 1. Guard against an empty query.
    if not user_query or not user_query.strip():
        return "Please enter what you're looking for (e.g. 'vintage graphic tee under $30').", "", ""

    # 2. Select the wardrobe based on the radio choice.
    if wardrobe_choice == "Empty wardrobe (new user)":
        wardrobe = get_empty_wardrobe()
    elif wardrobe_choice == "Saved profile":
        # Stretch: style profile memory — reuse the wardrobe from disk.
        wardrobe = get_saved_wardrobe()
        if not wardrobe.get("items"):
            # Nothing saved yet — fall back to the example wardrobe.
            wardrobe = get_example_wardrobe()
    else:
        wardrobe = get_example_wardrobe()

    # 3. Run the planning loop.
    session = run_agent(user_query, wardrobe)

    # 4. Error branch: show the message in panel 1, leave the others empty.
    if session["error"]:
        return session["error"], "", ""

    # Stretch: learn from this run and persist the profile for next time.
    update_profile_from_session(session)

    # 5. Happy path: format the selected listing + stretch info, return 3 panels.
    item = session["selected_item"]

    parts = []

    # Retry/fallback note (only present if constraints were relaxed).
    if session.get("adjustments"):
        parts.append("⚠️ Adjusted your search: " + "; ".join(session["adjustments"]) + ".\n")

    parts.append(
        f"{item['title']}\n"
        f"Price:     ${item['price']:.0f}\n"
        f"Platform:  {item['platform']}\n"
        f"Condition: {item['condition']}\n"
        f"Size:      {item['size']}\n"
        f"Category:  {item['category']}\n"
        f"Colors:    {', '.join(item['colors'])}\n"
        f"Style:     {', '.join(item['style_tags'])}\n\n"
        f"{item['description']}"
    )

    # Stretch: price-fairness verdict.
    if session.get("price_check"):
        parts.append("\n💰 Price check: " + session["price_check"]["message"])

    # Stretch: trending styles.
    if session.get("trending"):
        tags = ", ".join(t["tag"] for t in session["trending"])
        parts.append("📈 Trending right now: " + tags)

    listing_text = "\n".join(parts)
    return listing_text, session["outfit_suggestion"], session["fit_card"]


# ── interface ─────────────────────────────────────────────────────────────────

EXAMPLE_QUERIES = [
    "vintage graphic tee under $30",
    "90s track jacket in size M",
    "flowy midi skirt under $40",
    "black combat boots size 8",
    "designer ballgown size XXS under $5",   # deliberate no-results test
]

def build_interface():
    with gr.Blocks(title="FitFindr") as demo:
        gr.Markdown("""
# FitFindr 🛍️
Find secondhand pieces and get outfit ideas based on your wardrobe.
Describe what you're looking for — include size and price if you want to filter.
        """)

        with gr.Row():
            query_input = gr.Textbox(
                label="What are you looking for?",
                placeholder="e.g. vintage graphic tee under $30, size M",
                lines=2,
                scale=3,
            )
            wardrobe_choice = gr.Radio(
                choices=[
                    "Example wardrobe",
                    "Empty wardrobe (new user)",
                    "Saved profile",
                ],
                value="Example wardrobe",
                label="Wardrobe",
                scale=1,
            )

        submit_btn = gr.Button("Find it", variant="primary")

        with gr.Row():
            listing_output = gr.Textbox(
                label="🛍️ Top listing found",
                lines=8,
                interactive=False,
            )
            outfit_output = gr.Textbox(
                label="👗 Outfit idea",
                lines=8,
                interactive=False,
            )
            fitcard_output = gr.Textbox(
                label="✨ Your fit card",
                lines=8,
                interactive=False,
            )

        gr.Examples(
            examples=[[q, "Example wardrobe"] for q in EXAMPLE_QUERIES],
            inputs=[query_input, wardrobe_choice],
            label="Try these queries",
        )

        submit_btn.click(
            fn=handle_query,
            inputs=[query_input, wardrobe_choice],
            outputs=[listing_output, outfit_output, fitcard_output],
        )
        query_input.submit(
            fn=handle_query,
            inputs=[query_input, wardrobe_choice],
            outputs=[listing_output, outfit_output, fitcard_output],
        )

    return demo


if __name__ == "__main__":
    demo = build_interface()
    demo.launch()
