"""Custom CSS for the Streamlit UI.

Keeps Streamlit's structure but layers card-style containers, tighter typography,
and status pills on top. Called once per page (after `st.set_page_config`).
"""
from __future__ import annotations

import streamlit as st

_CSS = """
<style>
  /* Tighter top padding so the title is closer to the top */
  .block-container { padding-top: 2.2rem; padding-bottom: 4rem; }

  h1 { font-weight: 700; letter-spacing: -0.02em; }
  h2 { font-weight: 600; letter-spacing: -0.01em; margin-top: 1.5rem; }
  h3 { font-weight: 600; }

  /* Caption / muted text */
  .stCaption, [data-testid="stCaptionContainer"] { color: #8B93A7 !important; }

  /* Card containers (used with st.container(border=True)) */
  div[data-testid="stVerticalBlockBorderWrapper"] {
    background: #131826;
    border: 1px solid #1F2A3F !important;
    border-radius: 12px !important;
    padding: 1.1rem 1.2rem !important;
    transition: border-color 120ms ease, transform 120ms ease;
  }
  div[data-testid="stVerticalBlockBorderWrapper"]:hover {
    border-color: #2C3A57 !important;
  }

  /* Buttons */
  .stButton > button {
    border-radius: 10px;
    border: 1px solid #2C3A57;
    font-weight: 600;
  }
  .stButton > button[kind="primary"] {
    background: linear-gradient(180deg, #8B5CF6, #6D28D9);
    border: none;
    box-shadow: 0 4px 12px -2px rgba(124, 58, 237, 0.4);
  }
  .stButton > button[kind="primary"]:hover {
    transform: translateY(-1px);
    box-shadow: 0 6px 18px -2px rgba(124, 58, 237, 0.55);
  }

  /* Text input */
  .stTextInput input {
    border-radius: 10px;
    border: 1px solid #2C3A57;
    background: #131826 !important;
  }
  .stTextInput input:focus {
    border-color: #7C3AED;
    box-shadow: 0 0 0 3px rgba(124, 58, 237, 0.2);
  }

  /* Dataframe rounded */
  div[data-testid="stDataFrame"] {
    border-radius: 10px;
    overflow: hidden;
  }

  /* Status pills (used via raw HTML span class="pill pill-ok|err|run") */
  .pill {
    display: inline-block;
    padding: 0.15rem 0.55rem;
    border-radius: 999px;
    font-size: 0.78rem;
    font-weight: 600;
    line-height: 1.2;
    letter-spacing: 0.02em;
  }
  .pill-ok  { background: rgba(34,197,94,0.15);  color: #4ADE80; }
  .pill-err { background: rgba(239,68,68,0.15);  color: #F87171; }
  .pill-run { background: rgba(234,179,8,0.15);  color: #FACC15; }
  .pill-muted { background: rgba(148,163,184,0.12); color: #94A3B8; }

  /* Cost / metric values: monospaced for alignment */
  .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
</style>
"""


def apply_style() -> None:
    """Inject custom CSS. Call once at the top of every page."""
    st.markdown(_CSS, unsafe_allow_html=True)


def pill(text: str, kind: str = "muted") -> str:
    """Return an HTML span for a status pill. Use with st.markdown(..., unsafe_allow_html=True)."""
    cls = {"ok", "err", "run", "muted"}.intersection({kind}).pop() if kind in {"ok", "err", "run", "muted"} else "muted"
    return f'<span class="pill pill-{cls}">{text}</span>'
