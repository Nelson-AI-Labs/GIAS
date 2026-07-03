# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
GIAS — Home / Landing page
===========================
Informational landing: explains what GIAS is and how to use it.
The only navigational element is the "Start researching →" CTA.
Screen cards open explainer dialogs — they do not navigate.
"""

import streamlit as st
import base64
import frontend.components as ui


def _read_base64(path: str) -> str:
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    except FileNotFoundError:
        return ""


# ── Dashed-frame SVG thumbnail wrapper ───────────────────────────────────────

def _thumb(svg: str) -> str:
    """Wrap an SVG string in a dashed-frame thumbnail container (inline HTML)."""
    return (
        "<div style='border:1.5px dashed #DBE6EA;border-radius:8px;"
        "display:flex;align-items:center;justify-content:center;"
        "width:80px;min-width:80px;height:72px;background:#F2F7F8;flex-shrink:0'>"
        f"{svg}"
        "</div>"
    )


# ── Badge icon (tinted square, small SVG inside) ─────────────────────────────

def _badge(key: str, variant: str) -> str:
    """Small tinted badge for the principle cards. variant: ocean|kelp|gold."""
    bg = {"ocean": "#EAF6F9", "kelp": "#DCEFE9",
          "gold": "#F6EBD2"}.get(variant, "#EAF6F9")
    stroke = {"ocean": "#2E9DB5", "kelp": "#2E9E8B",
              "gold": "#DDA033"}.get(variant, "#136BAE")
    return (
        f"<div style='display:inline-flex;align-items:center;justify-content:center;"
        f"width:38px;height:38px;border-radius:9px;background:{bg};margin-bottom:.7rem'>"
        f"{ui.step_icon_svg(key, stroke=stroke, size=20)}"
        f"</div>"
    )


# ── Per-step explainer dialogs ────────────────────────────────────────────────

_STEP_CONTENT = {
    "search": (
        "Search & ingest",
        """
Enter a species name and GIAS will attempt to match it to an accepted Latin binomial.
For the most reliable results, use the Latin name directly.
Common names and misspellings are accepted, but always verify that the resolved name
matches the species you intended before relying on the results.

Once matched, GIAS expands the name to all known synonyms and name variants.

**What to do:**
1. Type the species name in the search field.
2. Click **Fetch Species Data**.
3. GIAS queries **six databases simultaneously** (GBIF, IUCN, EASIN, CABI, WRiMS,
   AquaNIS) across every synonym variant — this takes 30–60 seconds.
4. Per-source status is shown in real time. Any failures are reported clearly.

After the run, you land on the Knowledge base dashboard automatically.
        """,
    ),
    "dashboard": (
        "Knowledge base dashboard",
        """
All collected data organised by research category (ecology, distribution, impacts,
management, …). Every data point is pinned to its exact source.

**What to do:**
- Browse topic cards — click **↗ inspect** to read the raw facts for any topic.
- Where sources disagree on taxonomy (rank or authority), a conflict box shows all values
  side by side. GIAS never silently resolves these — you decide what to keep.
  Other fields list every source's value without flagging.
- The stats bar (fields · sources) gives an honest count of what has been filled.

From here you can go to Deep research to supplement with literature.
        """,
    ),
    "research": (
        "Deep research",
        """
Discover relevant studies. The first run queries all sources at once — Semantic
Scholar, OpenAlex, Europe PMC, DOAJ, Google Scholar, and Tavily (institutional /
grey literature). "Load more sources" pulls additional results from the four core
academic databases.

**What to do:**
1. Select one or more **topics** to target — the search focuses on filling those gaps.
2. Optionally set filters: publication year range, citation count minimum.
3. Click **Run research**. GIAS returns ranked source cards with abstracts.
4. Click any source card to open it in the right panel and start analyzing it.

The beta custom-topic agent lets you define topics not in the standard taxonomy —
it is clearly flagged as last-resort because quality is lower.
        """,
    ),
    "extract": (
        "Analyze & extract facts",
        """
After opening a source in Deep Research, GIAS reads the full text and extracts
structured facts topic by topic — nothing is written to the knowledge base until
you approve it.

**What to do:**
1. Click **Analyze** — AI gives an overview of the paper and suggests which topics
   it can contribute to.
2. Click **Extract** — the pipeline pulls facts for each selected topic.
3. Review the extracted facts per topic: uncheck any you want to discard.
4. Click **Merge** — only the facts you kept are added to the knowledge base,
   filed under their topic and tagged with the source paper.

Facts are session-only and do not overwrite the original database data.
        """,
    ),
    "report": (
        "Build report",
        """
Compile everything you have approved into a formatted intelligence dossier,
ready to export as a structured PDF.

**What to do:**
1. Choose which **topics** to include — uncheck anything not relevant to your brief.
2. Pick a **citation style** (APA, Vancouver, …).
3. Toggle optional sections: distribution map, executive summary.
4. Click **Generate report** — a live PDF preview appears immediately.
5. Download the PDF. The report includes full citations, conflict notes, and
   a provenance appendix.

The structured mode uses no AI in report assembly — every sentence traces to a
specific source record.
        """,
    ),
}


@st.dialog("How this step works", width="large")
def _step_dialog(key: str) -> None:
    title, body = _STEP_CONTENT[key]
    st.subheader(title)
    st.markdown(body)


# ── Returning-user redirect ───────────────────────────────────────────────────
if st.session_state.get("selected_species") and not st.session_state.get("_landing_seen"):
    st.session_state["_landing_seen"] = True
    st.switch_page("frontend/views/dashboard.py")
st.session_state["_landing_seen"] = True

st.session_state["_gias_view"] = "home"


# ── HERO ─────────────────────────────────────────────────────────────────────
# All inline styles — no dependency on shell.css class injection.
# Reference design: large two-tone serif catchphrase, italic cyan for the key phrase.

icon_b64 = _read_base64("frontend/images/GuardIAS_icon.png")

# Kicker: icon card on the left; stacked right side with GIAS (big) on top,
# icon + subtitle underneath. Uses plain px — clamp() gets stripped by the sanitizer.
kicker_html = (
    f"<div style='display:flex;align-items:center;justify-content:center;"
    f"gap:2.4rem;margin-bottom:2.5rem;margin-top:3rem'>"
    # ── left: icon in white card ──
    f"<div style='background:#fff;border-radius:22px;padding:18px;"
    f"box-shadow:0 2px 10px rgba(16,42,56,.14);flex-shrink:0'>"
    f"<img src='data:image/png;base64,{icon_b64}' width='130' height='130' "
    f"alt='GIAS shield' style='display:block'/>"
    f"</div>"
    # ── right: GIAS big, then icon + subtitle below ──
    f"<div style='text-align:left'>"
    f"<div style='font-family:\"Hanken Grotesk\",sans-serif;"
    f"font-size:120px;"
    f"font-weight:800;color:#0B3A60;letter-spacing:.05em;line-height:.9'>"
    f"G.I.A.S.</div>"
    f"<div style='margin-top:.6rem'>"
    f"<span style='font-family:\"Hanken Grotesk\",sans-serif;font-size:22px;"
    f"color:#6A828F;letter-spacing:.06em;text-transform:uppercase;font-weight:400'>"
    f"Intelligence Analyst System</span>"
    f"</div>"
    f"</div>"
    f"</div>"
)

# Two-tone catchphrase — dark serif + italic cyan for the key phrase
catchphrase_html = (
    f"<div style='max-width:680px;margin:0 auto 1.6rem;text-align:left;"
    f"padding:0 1rem'>"
    f"<h1 style='font-family:\"Hanken Grotesk\",sans-serif;font-weight:500;"
    f"color:#0B3A60;font-size:3rem;"
    f"line-height:1.18;margin:0 0 1rem'>"
    f"One place to assemble<br>what&#39;s known about an "
    f"<em style='color:#2E9DB5;font-style:italic'>invasive species.</em>"
    f"</h1>"
    f"<p style='font-family:\"Hanken Grotesk\",sans-serif;"
    f"font-size:var(--fs-body);color:#3C5867;"
    f"line-height:1.65;margin:0'>"
    f"A modern, transparent workspace for aquatic invasion biology. "
    f"GIAS queries six authoritative databases simultaneously, discovers relevant "
    f"literature, and lets you assemble a fully source-traceable dossier — "
    f"with every fact approved by you before it joins the knowledge base."
    f"</p>"
    f"</div>"
)

st.markdown(kicker_html, unsafe_allow_html=True)
st.html(catchphrase_html)

# Primary CTA — the only navigational element on this page
_, cta_col, _ = st.columns([1, 2, 1])
with cta_col:
    if st.button(
        "Start researching →",
        type="primary",
        width="stretch",
        icon=":material/search:",
    ):
        st.switch_page("frontend/views/ingest.py")


# ── CORE PRINCIPLES ───────────────────────────────────────────────────────────
# Rendered as pure HTML so we can enforce a fixed min-height on all three cards equally.

st.markdown("<div style='height:2rem'></div>", unsafe_allow_html=True)

_CARD_STYLE = (
    "flex:1;border:1px solid #DBE6EA;border-radius:11px;padding:1.4rem 1.2rem;"
    "display:flex;flex-direction:column;justify-content:flex-start;box-sizing:border-box;"
)

_principles = [
    ("dashboard", "ocean",
     "One place, many sources",
     "Six biodiversity databases and scientific literature — "
     "queried together, presented in one workspace."),
    ("search", "kelp",
     "Every fact, fully traced",
     "Each data point keeps its origin: database, paper, page. "
     "You always know where the information came from."),
    ("extract", "gold",
     "AI works, you lead",
     "AI handles the hours of searching, aggregating, and categorising. "
     "You pick the topics, shape the report, and your domain expertise stays central."),
]

_cards_html = "".join(
    f"<div style='{_CARD_STYLE}'>"
    f"{_badge(key, variant)}"
    f"<div style='font-weight:600;font-size:1.1rem;color:#102A38;"
    f"margin-bottom:.45rem'>{title}</div>"
    f"<div style='font-size:1.1rem;color:#6A828F;line-height:1.6'>{caption}</div>"
    f"</div>"
    for key, variant, title, caption in _principles
)
st.markdown(
    f"<div style='display:flex;gap:1rem;align-items:stretch'>{_cards_html}</div>",
    unsafe_allow_html=True,
)


# ── HOW TO USE GIAS ──────────────────────────────────────────────────────────

st.markdown("<div style='height:2rem'></div>", unsafe_allow_html=True)

st.markdown(
    "<p style='font-family:\"Hanken Grotesk\",sans-serif;font-size:.8rem;"
    "font-weight:600;color:#6A828F;letter-spacing:.1em;text-transform:uppercase;"
    "margin-bottom:.5rem'>How to use GIAS</p>",
    unsafe_allow_html=True,
)
st.markdown(
    "<p style='font-size:1.1rem;color:#3C5867;margin-bottom:1.2rem'>"
    "Five steps from a species name to a complete intelligence dossier. "
    "Click any step below to learn what it does and what to do."
    "</p>",
    unsafe_allow_html=True,
)

# Overview flow strip — always visible, purely visual, inline styles only
_flow_steps = [
    ("search",    "Search & ingest"),
    ("dashboard", "Knowledge base"),
    ("research",  "Deep research"),
    ("extract",   "Analyze & extract"),
    ("report",    "Build report"),
]

flow_parts = []
for j, (key, label) in enumerate(_flow_steps):
    svg = ui.step_icon_svg(key, stroke="#136BAE", size=24)
    flow_parts.append(
        f"<div style='display:flex;flex-direction:column;align-items:center;"
        f"gap:.3rem;font-size:1.1rem;color:#3C5867;font-weight:500'>"
        f"{svg}<span>{label}</span></div>"
    )
    if j < len(_flow_steps) - 1:
        flow_parts.append(
            "<span style='color:#93A7B1;font-size:1.1rem;align-self:center;"
            "flex-shrink:0'>→</span>"
        )

st.markdown(
    f"<div style='display:flex;flex-wrap:wrap;align-items:center;"
    f"justify-content:center;gap:.4rem;padding:1.2rem 1rem;"
    f"background:#F2F7F8;border-radius:11px;border:1px solid #DBE6EA'>"
    f"{''.join(flow_parts)}</div>",
    unsafe_allow_html=True,
)

st.markdown("<div style='height:.8rem'></div>", unsafe_allow_html=True)

# Equal card height comes from the cardgrid standard (shell.css). Here we only
# pin the "How this step works" button to the bottom so buttons line up per row.
st.markdown(
    """
    <style>
    /* Cards get flex:1 (fill height) from the cardgrid standard. Pin the button
       to the bottom: every stVerticalBlock in the column is flex-column, so
       space-between pushes the markdown to the top and the button to the base. */
    [class*="st-key-cardgrid_steps"] [data-testid="stColumn"] [data-testid="stVerticalBlock"] {
        display: flex;
        flex-direction: column;
        justify-content: space-between;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Reveal block — 5 screen cards, each opens an explainer dialog
with st.expander("Explore each step", expanded=False):
    _screens = [
        ("search",    "01 · ingest",   "Search & ingest",
         "Name → synonyms → six databases in parallel, narrated step by step."),
        ("dashboard", "02 · centrepiece", "Knowledge base",
         "All collected facts by topic; taxonomic & distribution conflicts surfaced, never hidden."),
        ("research",  "03 · discovery",   "Deep research",
         "Searches academic databases and web sources for relevant studies."),
        ("extract",   "04 · extraction",  "Analyze & extract",
         "AI-proposed facts, one by one — nothing added without your approval."),
        ("report",    "05 · output",      "Build report",
         "Curate topics, pick citation style, preview and download the PDF dossier."),
    ]

    # Wrapped in the cardgrid standard so paired cards share height per row.
    with st.container(key="cardgrid_steps"):
        for row_start in range(0, len(_screens), 2):
            pair = _screens[row_start:row_start + 2]
            cols = st.columns(2, gap="medium")
            # If only one item in this row, only use the first column so width matches paired rows
            items = list(zip(cols, pair)) if len(pair) == 2 else [(cols[0], pair[0])]
            for col, (key, eyebrow, title, desc) in items:
                with col:
                    with st.container(border=True):
                        thumb_svg = ui.step_icon_svg(
                            key, stroke="#136BAE", size=32)
                        card_html = (
                            f"<div style='display:flex;gap:1rem;align-items:flex-start'>"
                            f"{_thumb(thumb_svg)}"
                            f"<div style='flex:1;min-width:0'>"
                            f"<div style='font-family:\"Hanken Grotesk\",sans-serif;"
                            f"font-size:.75rem;font-weight:600;color:#2E9DB5;"
                            f"letter-spacing:.06em;margin-bottom:.3rem'>{eyebrow}</div>"
                            f"<div style='font-family:\"Hanken Grotesk\",sans-serif;"
                            f"font-weight:500;font-size:1.1rem;color:#102A38;"
                            f"margin:0 0 .35rem;line-height:1.25'>{title}</div>"
                            f"<div style='font-size:1.1rem;color:#3C5867;"
                            f"line-height:1.5;margin:0 0 .6rem'>{desc}</div>"
                            f"</div></div>"
                        )
                        st.markdown(card_html, unsafe_allow_html=True)
                        if st.button(
                            "How this step works →",
                            key=f"step_btn_{key}",
                            use_container_width=True,
                        ):
                            _step_dialog(key)


# ── CREDIT ────────────────────────────────────────────────────────────────────

st.markdown("<div style='height:2rem'></div>", unsafe_allow_html=True)
st.divider()

credit_left, credit_right = st.columns(
    [3, 2], gap="large", vertical_alignment="center")

with credit_left:
    li_svg = ui.linkedin_svg("#136BAE", 24)
    li_img = (
        f"<a href='https://linkedin.com/in/samuel-vander-velpen-910b31138' target='_blank' "
        f"style='margin-left:8px;display:inline-block;vertical-align:middle'>{li_svg}</a>"
    )
    st.markdown(
        f"<div style='color:#3C5867;line-height:1.7'>"
        f"<div style='font-size:1.25rem;font-weight:700;color:#102A38;margin-bottom:.3rem'>"
        f"Samuel Vander Velpen {li_img}"
        f"</div>"
        f"<div style='font-size:1.1rem;color:#3C5867'>"
        f"Developed as the primary project for Samuel's Master's thesis."
        f"</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

with credit_right:
    try:
        logo_col, nai_col, eu_col = st.columns(
            3, gap="small", vertical_alignment="center")
        with logo_col:
            st.image("frontend/images/guardias_logo.png", width="stretch")
        with nai_col:
            st.image("frontend/images/NAI_Logo.png", width="stretch")
        with eu_col:
            st.image(
                "frontend/images/EN_fundedbyEU_VERTICAL_RGB_Monochrome.png",
                width="stretch",
            )
    except Exception:
        pass
