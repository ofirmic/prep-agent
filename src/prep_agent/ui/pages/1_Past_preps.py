"""Past prep docs."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import streamlit as st

from prep_agent.ui.helpers import get_settings, require_auth
from prep_agent.ui.style import apply_style

st.set_page_config(page_title="Past preps · prep-agent", layout="wide")
apply_style()
require_auth()
st.markdown("# Past preps")
st.caption("Everything you've generated, newest first.")

settings = get_settings()
out_dir: Path = settings.output_dir

if not out_dir.exists():
    st.info("No prep docs yet — head back to the home page and generate one.")
    st.stop()

files = sorted(
    out_dir.glob("*.md"),
    key=lambda p: p.stat().st_mtime,
    reverse=True,
)

if not files:
    st.info("No prep docs yet — head back to the home page and generate one.")
    st.stop()

with st.sidebar:
    st.markdown("### Prep docs")
    labels = [
        f"{f.stem}  ·  {datetime.fromtimestamp(f.stat().st_mtime):%Y-%m-%d %H:%M}"
        for f in files
    ]
    idx = st.radio(
        "Select",
        options=list(range(len(files))),
        format_func=lambda i: labels[i],
        label_visibility="collapsed",
    )

selected = files[idx]
size_kb = selected.stat().st_size / 1024
modified = datetime.fromtimestamp(selected.stat().st_mtime)

with st.container(border=True):
    st.markdown(f"### {selected.name}")
    st.caption(f"{size_kb:.1f} KB · modified {modified:%Y-%m-%d %H:%M}")

content = selected.read_text(encoding="utf-8")

tab_render, tab_raw = st.tabs(["Rendered", "Markdown source"])
with tab_render:
    st.markdown(content)
with tab_raw:
    st.code(content, language="markdown")
