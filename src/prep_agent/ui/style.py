"""Custom CSS for the Streamlit UI.

Keeps Streamlit's structure but layers a polished dark theme on top:
card containers, tighter typography, status pills, hero gradient, quick-action chips.
Called once per page (after `st.set_page_config`).
"""
from __future__ import annotations

import streamlit as st

_CSS = """
<style>
  /* ============ Global typography & layout ============ */
  .block-container { padding-top: 2rem; padding-bottom: 4rem; max-width: 1180px; }

  h1 {
    font-weight: 700;
    letter-spacing: -0.025em;
    line-height: 1.15;
    background: linear-gradient(180deg, #F8FAFC 0%, #C7D2FE 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }
  h2 { font-weight: 600; letter-spacing: -0.015em; margin-top: 2rem; color: #E2E8F0; }
  h3 { font-weight: 600; color: #E2E8F0; }
  h4 { font-weight: 600; color: #CBD5E1; }

  /* Caption / muted text */
  .stCaption, [data-testid="stCaptionContainer"] { color: #94A3B8 !important; }

  /* ============ Card containers ============ */
  div[data-testid="stVerticalBlockBorderWrapper"] {
    background: linear-gradient(180deg, #131826 0%, #0F1320 100%);
    border: 1px solid #1F2A3F !important;
    border-radius: 14px !important;
    padding: 1.2rem 1.3rem !important;
    transition: border-color 160ms ease, transform 160ms ease, box-shadow 160ms ease;
  }
  div[data-testid="stVerticalBlockBorderWrapper"]:hover {
    border-color: #3B4868 !important;
    transform: translateY(-1px);
    box-shadow: 0 8px 24px -8px rgba(124, 58, 237, 0.18);
  }

  /* ============ Buttons ============ */
  .stButton > button {
    border-radius: 10px;
    border: 1px solid #2C3A57;
    font-weight: 600;
    transition: all 140ms ease;
  }
  .stButton > button:hover { border-color: #4C5B82; }
  .stButton > button[kind="primary"] {
    background: linear-gradient(180deg, #8B5CF6, #6D28D9);
    border: none;
    box-shadow: 0 4px 14px -2px rgba(124, 58, 237, 0.45);
    color: white;
  }
  .stButton > button[kind="primary"]:hover {
    transform: translateY(-1px);
    box-shadow: 0 8px 22px -2px rgba(124, 58, 237, 0.6);
    background: linear-gradient(180deg, #9D6FF7, #7B30E6);
  }

  /* ============ Text input ============ */
  .stTextInput input {
    border-radius: 10px;
    border: 1px solid #2C3A57;
    background: #131826 !important;
    font-size: 1rem;
    padding: 0.6rem 0.9rem;
  }
  .stTextInput input:focus {
    border-color: #7C3AED;
    box-shadow: 0 0 0 3px rgba(124, 58, 237, 0.25);
  }

  /* ============ Dataframe ============ */
  div[data-testid="stDataFrame"] {
    border-radius: 10px;
    overflow: hidden;
    border: 1px solid #1F2A3F;
  }

  /* ============ Status pills ============ */
  .pill {
    display: inline-block;
    padding: 0.18rem 0.6rem;
    border-radius: 999px;
    font-size: 0.76rem;
    font-weight: 600;
    line-height: 1.2;
    letter-spacing: 0.02em;
  }
  .pill-ok    { background: rgba(34,197,94,0.15);  color: #4ADE80; border: 1px solid rgba(34,197,94,0.25); }
  .pill-err   { background: rgba(239,68,68,0.15);  color: #F87171; border: 1px solid rgba(239,68,68,0.25); }
  .pill-run   { background: rgba(234,179,8,0.15);  color: #FACC15; border: 1px solid rgba(234,179,8,0.25); }
  .pill-muted { background: rgba(148,163,184,0.12); color: #94A3B8; border: 1px solid rgba(148,163,184,0.20); }

  /* Monospaced metric values */
  .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }

  /* ============ Hero gradient block (home page) ============ */
  .hero-eyebrow {
    text-transform: uppercase;
    font-size: 0.72rem;
    letter-spacing: 0.15em;
    font-weight: 700;
    color: #A78BFA;
    margin-bottom: 0.5rem;
  }
  .hero-sub {
    color: #94A3B8;
    font-size: 1.02rem;
    margin-top: -0.2rem;
    margin-bottom: 1.4rem;
  }

  /* ============ Quick-action chip links ============ */
  .chip-row { display: flex; flex-wrap: wrap; gap: 0.5rem; margin: 0.4rem 0 1.4rem; }
  .chip {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.45rem 0.85rem;
    border-radius: 999px;
    border: 1px solid #2C3A57;
    background: #131826;
    color: #CBD5E1 !important;
    text-decoration: none !important;
    font-size: 0.85rem;
    font-weight: 500;
    transition: all 140ms ease;
  }
  .chip:hover {
    border-color: #7C3AED;
    background: #1A1F30;
    transform: translateY(-1px);
  }
  .chip-icon { opacity: 0.85; }

  /* ============ Card-as-link ============ */
  a.card-link, a.card-link:visited { color: inherit !important; text-decoration: none !important; }
  .company-card-title {
    font-size: 1.08rem;
    font-weight: 600;
    color: #E2E8F0;
    margin-bottom: 0.3rem;
  }
  .company-card-meta {
    font-size: 0.82rem;
    color: #8B93A7;
    margin-top: 0.4rem;
  }

  /* ============ Sidebar polish ============ */
  section[data-testid="stSidebar"] { background: #0B0F1A; }
  section[data-testid="stSidebar"] .stMarkdown { color: #CBD5E1; }

  /* ============ Drill sheet TOC ============ */
  .toc-link {
    display: block;
    padding: 0.35rem 0.6rem;
    margin-bottom: 0.1rem;
    border-radius: 6px;
    color: #94A3B8 !important;
    text-decoration: none !important;
    font-size: 0.86rem;
    transition: all 120ms ease;
  }
  .toc-link:hover { background: #131826; color: #E2E8F0 !important; }
  .toc-link.depth-1 { font-weight: 600; color: #CBD5E1 !important; }
  .toc-link.depth-2 { padding-left: 1.2rem; }
  .toc-link.depth-3 { padding-left: 2rem; font-size: 0.82rem; }
</style>
"""


def apply_style() -> None:
    """Inject custom CSS. Call once at the top of every page."""
    st.markdown(_CSS, unsafe_allow_html=True)


def pill(text: str, kind: str = "muted") -> str:
    """Return an HTML span for a status pill."""
    valid = {"ok", "err", "run", "muted"}
    cls = kind if kind in valid else "muted"
    return f'<span class="pill pill-{cls}">{text}</span>'


def chip(label: str, href: str, icon: str = "") -> str:
    """Return an HTML anchor styled as a quick-action chip."""
    icon_html = f'<span class="chip-icon">{icon}</span>' if icon else ""
    return f'<a class="chip" href="{href}" target="_self">{icon_html}{label}</a>'
