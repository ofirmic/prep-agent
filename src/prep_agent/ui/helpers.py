"""Shared helpers for the Streamlit UI.

Caches the expensive resources (Pipeline carries Anthropic + FastEmbed +
ChromaDB) so Streamlit's rerun-on-interaction model doesn't reinitialize them
on every keystroke. The cache is process-wide.

`require_auth()` is the single-password gate for deployed instances. Locally
(no STREAMLIT_AUTH_PASSWORD set) it's a no-op; on hosted deploys it blocks
random visitors from spending your Anthropic budget.
"""
from __future__ import annotations

import hmac
import os

import streamlit as st

from prep_agent.config import Settings
from prep_agent.obs.store import TraceStore
from prep_agent.pipeline import Pipeline


@st.cache_resource
def get_settings() -> Settings:
    return Settings.from_env()


@st.cache_resource
def get_pipeline() -> Pipeline:
    return Pipeline(get_settings())


@st.cache_resource
def get_trace_store() -> TraceStore:
    return TraceStore(db_path=get_settings().trace_db_path)


def require_auth() -> None:
    """Gate the page on a single shared password.

    Pattern:
    - Locally: STREAMLIT_AUTH_PASSWORD unset → no gate, just pass through.
    - Hosted: STREAMLIT_AUTH_PASSWORD set → password input until correct.

    Uses hmac.compare_digest to avoid timing leaks. Each Streamlit page
    script must call this — Streamlit runs them independently.
    """
    expected = os.getenv("STREAMLIT_AUTH_PASSWORD", "")
    if not expected:
        return  # No gate configured.

    if st.session_state.get("authed") is True:
        return

    st.title("prep-agent")
    st.caption("Enter password to continue.")
    pwd = st.text_input("Password", type="password", label_visibility="collapsed")
    if pwd:
        if hmac.compare_digest(pwd, expected):
            st.session_state.authed = True
            st.rerun()
        else:
            st.error("Wrong password")
    st.stop()
