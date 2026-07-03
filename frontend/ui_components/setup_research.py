# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""Streamlit UI for the research-topics selection section shown on the home page."""

import streamlit as st

def create_research_topics_section():
    """Create the research topics selection interface"""
    
    st.markdown(":material/target: **Research Topics**")
    st.markdown("Select which aspects you want to research about the chosen species:")

    # Available topics (currently just location)
    location_research = st.checkbox(
        ":material/public: **Geographic Distribution & Location**",
        value=True,  # Default to checked since this is the main feature
        help="Research native habitat, invasive range, and geographic distribution",
        key="research_topic_location"
    )

    # Placeholder for future topics
    st.markdown("---")
    st.markdown(":material/construction: **Other topics perhaps coming soon**")

    # Disabled checkboxes for future features
    st.checkbox(
        ":material/biotech: Species Traits",
        value=False,
        disabled=True,
        help="Species traits (coming soon)",
        key="research_topic_traits"
    )

    st.checkbox(
        ":material/insights: Population Dynamics",
        value=False,
        disabled=True,
        help="Population trends and growth patterns (coming soon)",
        key="research_topic_population"
    )

    st.checkbox(
        ":material/eco: Environmental Impact",
        value=False,
        disabled=True,
        help="Ecological effects and ecosystem disruption (coming soon)",
        key="research_topic_impact"
    )

    st.checkbox(
        ":material/science: Management Strategies",
        value=False,
        disabled=True,
        help="Control and prevention methods (coming soon)",
        key="research_topic_management"
    )

    # Return the selected topics for use by other components
    selected_topics = {
        "location": location_research,
        "population": False,  # Future
        "impact": False,      # Future
        "management": False   # Future
    }

    # Validation check without displaying active topics
    if not any(selected_topics.values()):
        st.warning("Please select at least one research topic to proceed",
                   icon=":material/warning:")
    
    return selected_topics