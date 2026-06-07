"""Playbook — browse all of your interview prep docs with TOC navigation.

Markdown docs render with an auto-built H2/H3 TOC sidebar.
Image docs (e.g. the annotated architecture diagram) render full-width.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import streamlit as st

from prep_agent.ui.helpers import require_auth
from prep_agent.ui.style import apply_style

st.set_page_config(page_title="Playbook · prep-agent", layout="wide")
apply_style()
require_auth()


@dataclass(frozen=True)
class Doc:
    label: str
    filename: str
    description: str
    kind: Literal["md", "image"] = "md"


DOCS: tuple[Doc, ...] = (
    Doc(
        "Drill sheet",
        "interview-drill-sheet.md",
        "Compact night-before + morning-of: Skai/AMC narrative + system design.",
    ),
    Doc(
        "AMC architecture",
        "amc-architecture-annotated.png",
        "Annotated diagram of the end-to-end AMC integration — 15 callouts with explanations.",
        kind="image",
    ),
    Doc(
        "Senior playbook",
        "interview-playbook.md",
        "The full framework — how interviews are graded, 5-layer system talk, scaling.",
    ),
    Doc(
        "AMC deep dive",
        "amc-project-deepdive.md",
        "Every component of the AMC integration — for owning the project end-to-end.",
    ),
    Doc(
        "AMC Q&A",
        "amc-deepdive-answers.md",
        "Answer key to the 'Stop and answer' boxes in the AMC deep dive.",
    ),
    Doc(
        "AMC interview prep",
        "amc-interview-prep.md",
        "Long-form AMC interview preparation notes.",
    ),
    Doc(
        "Hebrew prep",
        "interview-hebrew.md",
        "Hebrew + English code-switching drills for Israeli interviews.",
    ),
)

CANDIDATE_ROOTS = (
    Path.home() / "Documents",
    Path(__file__).resolve().parents[3] / "playbook",
    Path(__file__).resolve().parents[3] / "docs" / "screenshots",
    Path("/app/playbook"),
    Path("/app/docs/screenshots"),
)


def _find_doc(filename: str) -> Path | None:
    for root in CANDIDATE_ROOTS:
        candidate = root / filename
        if candidate.exists():
            return candidate
    return None


def _slugify_heading(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_]+", "-", text).strip("-")


def _build_toc(md: str) -> list[tuple[int, str, str]]:
    out: list[tuple[int, str, str]] = []
    for line in md.splitlines():
        m = re.match(r"^(#{1,3})\s+(.*?)\s*$", line)
        if not m:
            continue
        depth = len(m.group(1))
        title = re.sub(r"[*_`]", "", m.group(2))
        out.append((depth, _slugify_heading(title), title))
    return out


def _inject_anchors(md: str) -> str:
    def replace(match: re.Match[str]) -> str:
        hashes = match.group(1)
        title = match.group(2)
        slug = _slugify_heading(re.sub(r"[*_`]", "", title))
        return f'{hashes} <a id="{slug}"></a>{title}'

    return re.sub(r"^(#{1,3})\s+(.*?)$", replace, md, flags=re.MULTILINE)


# --- Hero ---
st.markdown('<div class="hero-eyebrow">PLAYBOOK</div>', unsafe_allow_html=True)
st.markdown("# Your interview prep library")
st.markdown(
    '<div class="hero-sub">Every prep doc you\'ve written, with jump-to-section navigation.</div>',
    unsafe_allow_html=True,
)


# --- Resolve which docs are actually available on disk ---
available: list[tuple[Doc, Path]] = []
missing: list[Doc] = []
for d in DOCS:
    p = _find_doc(d.filename)
    if p is not None:
        available.append((d, p))
    else:
        missing.append(d)

if not available:
    st.warning(
        "No playbook docs found. Drop your interview docs into `~/Documents/` "
        "or the repo's `playbook/` directory."
    )
    st.stop()

# --- Doc picker (deep-linkable via ?doc=slug) ---
labels = [d.label for d, _ in available]
qp_doc = st.query_params.get("doc", "").strip().lower()
default_index = 0
if qp_doc:
    for i, (d, _) in enumerate(available):
        if _slugify_heading(d.label) == qp_doc:
            default_index = i
            break

selected_label = st.radio(
    "Choose a doc",
    options=labels,
    index=default_index,
    horizontal=True,
    label_visibility="collapsed",
)
selected_doc, selected_path = next(
    (d, p) for d, p in available if d.label == selected_label
)
st.query_params["doc"] = _slugify_heading(selected_doc.label)

st.caption(selected_doc.description)
st.divider()

# --- Sidebar (filled per-doc-kind below) ---
sidebar_placeholder = st.sidebar.empty()


def _render_sidebar_md(toc_items: list[tuple[int, str, str]]) -> None:
    with sidebar_placeholder.container():
        st.markdown("### Jump to section")
        st.caption(f"_{selected_doc.label}_")
        if toc_items:
            html = []
            for depth, slug, title in toc_items:
                display = title if len(title) < 48 else title[:47] + "…"
                html.append(
                    f'<a class="toc-link depth-{depth}" href="#{slug}">{display}</a>'
                )
            st.markdown("\n".join(html), unsafe_allow_html=True)
        else:
            st.caption("(no headings)")
        if missing:
            st.divider()
            st.caption("**Not found:**")
            for d in missing:
                st.caption(f"• `{d.filename}`")
        st.divider()
        st.caption(f"Source: `{selected_path.name}`")


def _render_sidebar_image() -> None:
    with sidebar_placeholder.container():
        st.markdown("### About this diagram")
        st.caption(
            "Two halves: top = request → execution → ingest. "
            "Bottom = serving → product. Snowflake is the boundary."
        )
        st.divider()
        st.markdown("**Drill yourself:**")
        st.caption(
            "Cover the legend. Walk every numbered callout out loud. "
            "If you can't explain a box without peeking, that's tonight's drill."
        )
        st.divider()
        st.caption(f"Source: `{selected_path.name}`")


# --- Body ---
if selected_doc.kind == "image":
    _render_sidebar_image()
    st.image(str(selected_path), use_container_width=True)
else:
    content = selected_path.read_text(encoding="utf-8")
    toc = _build_toc(content)
    _render_sidebar_md(toc)
    st.markdown(_inject_anchors(content), unsafe_allow_html=True)
