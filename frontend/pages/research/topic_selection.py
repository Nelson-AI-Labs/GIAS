# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Topic Selection UI Components
UI components for topic selection and management in the research interface.

Layout: 3-column chip grid for anchor topics + BETA card for custom topics below.
"""

import streamlit as st
from frontend.pages.research.research_state import TOPIC_DESCRIPTIONS
from core.cache_layer.categorized_data_helpers import load_categorized_data_by_id, count_topic_stats

# Import custom topic interpreter from extraction system
from functionalities.extraction.agents.custom_topic_interpreter import TopicInterpreterAgent

MAX_CHAT_EXCHANGES = 8


def _compose_ai_bubble(turn_result: dict, current_questions_asked: int) -> tuple:
    """
    Build the AI chat bubble text and return the updated questions_asked count.

    The question (if any) is appended to the message naturally. Options are
    stored separately in session state and rendered as buttons — not in the bubble.

    Returns:
        (ai_text: str, new_questions_asked: int)
    """
    ai_text = turn_result["message"]
    new_questions_asked = current_questions_asked
    if turn_result["question"]:
        ai_text = f"{turn_result['message']}\n\n{turn_result['question']}"
        new_questions_asked += 1
    return ai_text, new_questions_asked


def show_custom_topic_chat():
    """
    Compact chat panel for clarifying a custom topic, rendered inside the
    BETA card section of show_topic_selection_with_counters().

    Shows only the latest AI message — full history is preserved in session
    state for AI context but not displayed. This keeps the panel height
    bounded and avoids accumulation of previous interpretations.
    """
    chat = st.session_state.custom_topic_chat
    exchange_count = chat["exchange_count"]
    options = chat.get("current_options", [])

    # ── Header ────────────────────────────────────────────────────────
    st.markdown(f"**{chat['topic']}**")
    st.caption(f"{exchange_count} / {MAX_CHAT_EXCHANGES} exchanges")

    st.divider()

    # ── Latest AI message only ─────────────────────────────────────────
    last_ai_msg = next((m for m in reversed(chat["history"]) if m["role"] == "ai"), None)
    if last_ai_msg:
        with st.chat_message("assistant"):
            st.markdown(last_ai_msg["text"])

    # ── Response area ─────────────────────────────────────────────────
    if exchange_count >= MAX_CHAT_EXCHANGES:
        st.caption("Exchange limit reached. Confirm or cancel.")
    elif options:
        # Primary: stacked option buttons (cleaner in narrow column)
        for i, option in enumerate(options):
            if st.button(option, key=f"opt_{i}_{exchange_count}", width="stretch"):
                _process_chat_reply(chat, option)

        # Secondary: custom text input tucked in expander
        with st.expander("Or type a reply..."):
            user_reply = st.text_input(
                "Custom reply",
                key=f"custom_reply_{exchange_count}",
                label_visibility="collapsed",
                placeholder="Type something else...",
            )
            if st.button("Send", key=f"send_custom_{exchange_count}"):
                if user_reply.strip():
                    _process_chat_reply(chat, user_reply.strip())
    else:
        # No options — AI was confident; plain text for context or confirmation
        user_reply = st.text_input(
            "Reply",
            key=f"chat_reply_{exchange_count}",
            placeholder="Add context or confirm...",
            label_visibility="collapsed",
        )
        if st.button("Send", key=f"send_reply_{exchange_count}", width="stretch"):
            if user_reply.strip():
                _process_chat_reply(chat, user_reply.strip())

    # ── Confirm / Cancel at the bottom ────────────────────────────────
    st.divider()
    confirm_col, cancel_col = st.columns(2)
    with confirm_col:
        if st.button("Confirm", type="primary", key="confirm_custom_topic", width="stretch", icon=":material/check:"):
            _commit_custom_topic(chat)
    with cancel_col:
        if st.button("Cancel", key="cancel_custom_topic", width="stretch", icon=":material/close:"):
            del st.session_state.custom_topic_chat
            st.rerun()


def _process_chat_reply(chat: dict, user_reply: str) -> None:
    """Append user reply, call the AI for the next turn, update chat state."""
    chat["history"].append({"role": "user", "text": user_reply})

    with st.spinner("Thinking..."):
        try:
            interpreter = TopicInterpreterAgent()
            turn_result = interpreter.run_turn(
                custom_topic=chat["topic"],
                species_name=chat["species_name"],
                history=chat["history"],
                questions_asked=chat["questions_asked"],
            )

            ai_text, chat["questions_asked"] = _compose_ai_bubble(turn_result, chat["questions_asked"])

            chat["history"].append({"role": "ai", "text": ai_text})
            chat["exchange_count"] += 1
            chat["current_options"] = turn_result.get("options", [])
            chat["last_interpretation"] = {
                "interpretation": turn_result["interpretation"],
                "key_concepts": turn_result["key_concepts"],
                "scope_boundaries": turn_result["scope_boundaries"],
            }
            st.rerun()

        except Exception as e:
            st.error(f"Error processing reply: {str(e)}")
            print(f"Chat reply error: {e}")


def _commit_custom_topic(chat: dict) -> None:
    """Commit the negotiated topic to research state and clear the chat."""
    research_state = st.session_state.research_state
    topic = chat["topic"]

    if topic in research_state['custom_topics'] or topic in research_state['anchor_topics']:
        st.warning(f"Topic '{topic}' already exists.")
        return

    interp = chat["last_interpretation"]

    research_state['custom_topic_interpretations'][topic] = {
        'interpretation': interp['interpretation'],
        'key_concepts': interp['key_concepts'],
        'scope_boundaries': interp['scope_boundaries'],
    }

    research_state['custom_topics'].append(topic)
    research_state['topic_sources'][topic] = {
        'dcp_sources': [],
        'research_source_urls': [],
        'dcp_count': 0,
        'research_count': 0,
        'total_count': 0,
        'dashboard_card': None,
    }

    del st.session_state.custom_topic_chat
    st.rerun()


def show_topic_selection_with_counters():
    """
    Topic selection: 3-column chip grid for anchor topics + BETA custom-topic card.

    Each anchor topic renders as a bordered chip with a checkbox and KB-style
    stats ("X data points · Y sources") loaded from categorized_data once per
    render and passed down — identical to the Knowledge Base dashboard figures.
    Wiring (checkbox → selected_for_next_run) is unchanged — layout only.
    """
    st.markdown("#### 1 · Topics")

    research_state = st.session_state.research_state
    anchor_topics = research_state['anchor_topics']
    custom_topics = research_state['custom_topics']

    # Load categorized_data once — all per-topic stat lookups reuse this dict.
    universal_id = st.session_state.get('universal_id')
    categorized_data = load_categorized_data_by_id(universal_id) if universal_id else None
    cat_fields = (categorized_data or {}).get('categorized_fields', {})

    # 3-column chip grid — rendered one row at a time so the three cards in a
    # row are real flex siblings and the cardgrid standard equalises their height.
    with st.container(key="cardgrid_rtopics"):
        for row_start in range(0, len(anchor_topics), 3):
            row_topics = anchor_topics[row_start:row_start + 3]
            cols = st.columns(3)
            for col, topic in zip(cols, row_topics):
                with col:
                    with st.container(border=True, key=f"rtopic_{topic}"):
                        _render_topic_checkbox(research_state, topic, cat_fields, is_anchor=True)

    st.markdown("")  # vertical spacer before BETA card

    # Make it obvious the BETA tool is expandable
    st.caption(
        ":material/expand_more: Need a topic that isn't listed above? "
        "**Expand** the BETA custom-topic tool below."
    )

    # BETA custom-topic card — collapsed by default, last-resort only
    with st.expander("▸ :orange-badge[BETA] Custom topic — last resort  ·  click to expand",
                     expanded=False, icon=":material/warning:"):
        st.caption(
            "Experimental. Extraction quality for custom topics is not guaranteed. "
            "Prefer the predefined topics above where possible."
        )

        with st.container(height=360):
            if 'custom_topic_chat' in st.session_state:
                show_custom_topic_chat()
            else:
                # Compact add-topic form
                input_col, btn_col = st.columns([4, 1])
                with input_col:
                    new_topic = st.text_input(
                        "Add topic",
                        placeholder="Describe a custom topic…",
                        key="custom_topic_input",
                        label_visibility="collapsed",
                    )
                with btn_col:
                    if st.button("+ Add", key="add_custom_topic"):
                        if new_topic and new_topic not in custom_topics and new_topic not in anchor_topics:
                            species_name = (
                                st.session_state.get('standardized_species_name')
                                or st.session_state.get('selected_species', '')
                            )
                            with st.spinner("Analyzing…"):
                                try:
                                    interpreter = TopicInterpreterAgent()
                                    turn_result = interpreter.run_turn(
                                        custom_topic=new_topic,
                                        species_name=species_name,
                                        history=[],
                                        questions_asked=0,
                                    )
                                    ai_text, questions_asked = _compose_ai_bubble(turn_result, 0)
                                    st.session_state.custom_topic_chat = {
                                        "topic": new_topic,
                                        "species_name": species_name,
                                        "history": [{"role": "ai", "text": ai_text}],
                                        "questions_asked": questions_asked,
                                        # First AI turn already happened, so count it as 1
                                        "exchange_count": 1,
                                        "current_options": turn_result.get("options", []),
                                        "last_interpretation": {
                                            "interpretation": turn_result["interpretation"],
                                            "key_concepts": turn_result["key_concepts"],
                                            "scope_boundaries": turn_result["scope_boundaries"],
                                        },
                                    }
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Failed to analyze topic: {str(e)}")
                                    print(f"Error generating interpretation: {e}")

        # Confirmed custom topics live below the scroll-bounded area so they
        # stay visible even while the clarification chat is open.
        if custom_topics:
            st.divider()
            for topic in custom_topics:
                _render_custom_topic_checkbox(research_state, topic, cat_fields)
        elif 'custom_topic_chat' not in st.session_state:
            st.caption("No custom topics yet.")


def _render_topic_checkbox(research_state, topic, cat_fields, is_anchor=True):
    """Render a single topic checkbox with KB-style data points · sources stats."""
    # Map topic key → category key via dashboard_card (same as KB uses)
    card_key = research_state['topic_sources'].get(topic, {}).get('dashboard_card') or topic
    cat_data = cat_fields.get(card_key, {})
    pts, n_srcs = count_topic_stats(cat_data)

    is_researched = topic in research_state.get('researched_topics', [])
    help_text = TOPIC_DESCRIPTIONS.get(topic, None) if is_anchor else None

    checked = st.checkbox(
        f"**{topic.title()}**",
        key=f"topic_checkbox_{topic}",
        help=help_text,
        disabled=is_researched,
    )
    if not is_researched:
        if checked and topic not in research_state['selected_for_next_run']:
            research_state['selected_for_next_run'].append(topic)
        elif not checked and topic in research_state['selected_for_next_run']:
            research_state['selected_for_next_run'].remove(topic)

    if is_researched:
        st.caption(":material/check_circle: researched — use **Show more sources** below, or **Reset** to retry")
    elif pts:
        s_pts = "s" if pts != 1 else ""
        s_srcs = "s" if n_srcs != 1 else ""
        st.caption(f"**{pts}** data point{s_pts} · {n_srcs} source{s_srcs}")
    else:
        st.caption("not in your knowledge base yet")


def _render_custom_topic_checkbox(research_state, topic, cat_fields):
    """Render a custom topic checkbox with delete button, interpretation, and KB-style stats."""
    # Custom topics use their own name as the category key after merge
    cat_data = cat_fields.get(topic, {})
    pts, n_srcs = count_topic_stats(cat_data)

    is_researched = topic in research_state.get('researched_topics', [])
    checkbox_col, delete_col = st.columns([4, 1])

    with checkbox_col:
        checked = st.checkbox(topic, key=f"topic_checkbox_{topic}", disabled=is_researched)
        if not is_researched:
            if checked and topic not in research_state['selected_for_next_run']:
                research_state['selected_for_next_run'].append(topic)
            elif not checked and topic in research_state['selected_for_next_run']:
                research_state['selected_for_next_run'].remove(topic)

    with delete_col:
        if st.button("", key=f"delete_topic_{topic}", help="Delete this custom topic", icon=":material/delete:"):
            research_state['custom_topics'].remove(topic)
            if topic in research_state['topic_sources']:
                del research_state['topic_sources'][topic]
            if topic in research_state['selected_for_next_run']:
                research_state['selected_for_next_run'].remove(topic)
            if topic in research_state.get('custom_topic_interpretations', {}):
                del research_state['custom_topic_interpretations'][topic]
            for source in research_state['all_sources'].values():
                if topic in source.get('topics', []):
                    source['topics'].remove(topic)
            st.rerun()

    if is_researched:
        st.caption(":material/check_circle: researched — use **Show more sources** below, or **Reset** to retry")
    elif pts:
        s_pts = "s" if pts != 1 else ""
        s_srcs = "s" if n_srcs != 1 else ""
        st.caption(f"**{pts}** data point{s_pts} · {n_srcs} source{s_srcs}")
    else:
        st.caption("not in your knowledge base yet")

    interpretations = research_state.get('custom_topic_interpretations', {})
    if topic in interpretations:
        with st.expander("Topic Interpretation", expanded=False, icon=":material/info:"):
            interp_data = interpretations[topic]
            st.markdown("**How this topic will be interpreted:**")
            st.write(interp_data['interpretation'])
            if interp_data.get('key_concepts'):
                st.markdown("**Key concepts to look for:**")
                for concept in interp_data['key_concepts']:
                    st.markdown(f"• {concept}")
            if interp_data.get('scope_boundaries'):
                st.markdown("**Scope:**")
                st.write(interp_data['scope_boundaries'])
