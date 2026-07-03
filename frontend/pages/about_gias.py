# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
About GIAS - Sidebar explanation content
Contains all the explanatory information about the GIAS system
"""

import streamlit as st

def show_about_gias():
    """Display comprehensive information about GIAS in the sidebar"""

    # Header with GuardIAS logo
    st.image("frontend/images/guardias_logo.png", width="stretch")

    st.title("About G.I.A.S")
    st.markdown("**GuardIAS Intelligence Analyst System**")

    st.markdown("""
    ### What is GIAS?

    G.I.A.S is an intelligence platform for aquatic invasive species research. Enter a species name and the system automatically queries authoritative biodiversity databases, discovers relevant academic literature, and generates comprehensive intelligence reports — with full source traceability throughout.

    ---

    ### How to Use GIAS

    **Step 1 — Enter a species name**

    Type a species name into the search bar. You can enter the name in any language — GIAS automatically translates and standardises it to the accepted Latin name. Minor spelling mistakes are detected and corrected automatically.

    **Step 2 — Fetch species data**

    Click **Fetch Species Data**. GIAS queries multiple authoritative biodiversity databases simultaneously, searching across all known synonyms and name variants. This takes roughly 30–60 seconds.

    **Step 3 — Explore the Dashboard**

    Once loaded, the **Dashboard** shows all collected data organised by research category. Each data point is linked to its original source. Where databases disagree on taxonomy or on native-vs-introduced status, conflicts are flagged for your review.

    **Step 4 — Research Mode (optional)**

    Switch to **Research Mode** to supplement your dashboard with academic literature.

    1. **Select topics** from the predefined list, or type a **custom topic** in natural language and press **+ Add Topic**. *Custom topics are AI-interpreted and may be less consistent than the predefined standard topics.*
    2. Press **Run Research** — GIAS searches across academic databases (Semantic Scholar, Europe PMC, OpenAlex, DOAJ) and uses an AI-powered web search engine (Tavily) to find institutional and government documents.
    3. Sources appear in two tabs: **Academic Papers** (peer-reviewed literature, preprints) and **AI Supported Web Search** (institutional reports, government documents). You can also add your own PDFs via the manual upload expander below the tabs.
    4. For each source, upload a PDF if one is not already available, then press **Analyze study** — this runs in the background and does two things: extracts study context (location, population, methodology) and suggests which topics are covered by the document.
    5. Review the suggested topics assigned to the source. Adjust if needed, then press **Extract** to run AI data extraction on those topics.
    6. Review the extracted results, then press **Merge** to push the data into your dashboard.

    **Step 5 — Generate a Report**

    Scroll to the bottom of the Dashboard to generate an intelligence report. Choose a format:

    - **Structured (no AI)** — bullet points and tables containing only statements directly extracted from your sources. Zero hallucination risk.
    - **Narrative (AI-enhanced)** — flowing prose written by AI. The AI never draws on its own training data; every statement is grounded exclusively in data from the biodiversity databases and your approved extracted sources.

    Both formats include full source citations and can be downloaded.

    ---

    ### Key Features

    - **Multilingual input** — Enter species names in any language; GIAS translates to the accepted Latin name
    - **Spelling correction** — Minor typos are detected and corrected automatically
    - **Synonym-aware search** — All known scientific name variants are queried across every database
    - **Source traceability** — Every statement is linked back to its original source
    - **Human oversight** — You control which sources, topics, and extractions enter your dashboard
    - **Conflict highlighting** — Disagreements between databases are surfaced clearly
    - **Custom topic research** — Define your own research topics beyond the standard set
    - **PDF upload** — Manually add your own sources for AI-assisted extraction

    ---

    ### Development Team

    **Head Developer & Creator**
    Samuel Vander Velpen

    *Developed as the primary project for Samuel's Master's thesis.*
    """)

    # Contact section with LinkedIn icon
    import base64

    def get_base64_image(image_path):
        """Read an image file and return its base64-encoded string for inline HTML embedding."""
        with open(image_path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode()

    linkedin_icon_base64 = get_base64_image("frontend/images/linkedIn_icon.png")

    st.markdown(
        f"""
        **Contact:**
        <a href="https://linkedin.com/in/samuel-vander-velpen-910b31138" target="_blank">
            <img src="data:image/png;base64,{linkedin_icon_base64}" width="35" style="vertical-align: middle; margin-left: 10px;">
        </a>
        """,
        unsafe_allow_html=True
    )

    st.markdown("---")

    # NAI Logo
    st.markdown("**Developed in employment of**")
    st.image("frontend/images/NAI_Logo.png", width=200)

    st.markdown("---")

    # Project branding
    st.image("frontend/images/EN_fundedbyEU_VERTICAL_RGB_Monochrome.png", width=200)