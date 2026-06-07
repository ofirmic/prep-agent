"""Observability dashboard."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from prep_agent.ui.helpers import get_trace_store, require_auth
from prep_agent.ui.style import apply_style

st.set_page_config(page_title="Stats · prep-agent", layout="wide")
apply_style()
require_auth()
st.markdown("# Stats")
st.caption(
    "Engineering-grade metrics under the hood: per-call cost, latency, errors. "
    "Useful if something fails, otherwise just here for the portfolio narrative."
)

store = get_trace_store()

traces = store.list_traces(limit=500)
if not traces:
    st.warning(
        "No traces yet. Generate a prep doc on the **prep-agent** page first."
    )
    st.stop()

traces_df = pd.DataFrame(
    [
        {
            "trace_id": t.trace_id,
            "kind": t.kind,
            "label": t.label,
            "status": t.status,
            "started_at": datetime.fromtimestamp(t.started_at),
            "duration_s": (t.ended_at - t.started_at) if t.ended_at else None,
            "total_tokens": t.total_tokens,
            "total_cost_usd": t.total_cost_usd,
        }
        for t in traces
    ]
)

calls_rows = []
for t in traces:
    for c in store.get_calls(t.trace_id):
        calls_rows.append(
            {
                "trace_id": c.trace_id,
                "trace_label": t.label,
                "stage": c.stage,
                "model": c.model,
                "input_tokens": c.input_tokens,
                "output_tokens": c.output_tokens,
                "cost_usd": c.cost_usd,
                "latency_ms": c.latency_ms,
                "ts": datetime.fromtimestamp(c.ts),
                "error": c.error,
            }
        )
calls_df = pd.DataFrame(calls_rows)

# --- Top metrics as bordered cards ---
m1, m2, m3, m4 = st.columns(4)
with m1.container(border=True):
    st.metric("Traces", len(traces_df))
with m2.container(border=True):
    st.metric("LLM calls", len(calls_df))
with m3.container(border=True):
    st.metric("Total tokens", f"{int(traces_df['total_tokens'].sum()):,}")
with m4.container(border=True):
    st.metric("Total cost (USD)", f"${traces_df['total_cost_usd'].sum():.4f}")

# --- Cost over time ---
with st.container(border=True):
    st.markdown("### Cost over time")
    if not traces_df.empty:
        by_day = (
            traces_df.assign(day=traces_df["started_at"].dt.floor("D"))
            .groupby("day")["total_cost_usd"]
            .sum()
            .reset_index()
            .rename(columns={"total_cost_usd": "cost_usd"})
        )
        st.line_chart(by_day, x="day", y="cost_usd", height=220)

# --- Per-stage breakdown ---
with st.container(border=True):
    st.markdown("### Per-stage breakdown")
    if not calls_df.empty:
        by_stage = (
            calls_df.groupby("stage")
            .agg(
                calls=("stage", "size"),
                tokens=(
                    "input_tokens",
                    lambda s: int(
                        s.sum() + calls_df.loc[s.index, "output_tokens"].sum()
                    ),
                ),
                cost_usd=("cost_usd", "sum"),
                p50_ms=("latency_ms", lambda s: int(s.quantile(0.50))),
                p95_ms=("latency_ms", lambda s: int(s.quantile(0.95))),
            )
            .reset_index()
            .sort_values("cost_usd", ascending=False)
        )
        st.dataframe(by_stage, use_container_width=True, hide_index=True)

        col_l, col_r = st.columns(2)
        with col_l:
            st.caption("Cost by stage")
            st.bar_chart(by_stage.set_index("stage")["cost_usd"], height=220)
        with col_r:
            st.caption("p95 latency (ms) by stage")
            st.bar_chart(by_stage.set_index("stage")["p95_ms"], height=220)

# --- Recent traces with drill-in ---
with st.container(border=True):
    st.markdown("### Recent traces")
    shown = traces_df.head(50)
    st.dataframe(
        shown[
            [
                "trace_id",
                "kind",
                "label",
                "status",
                "started_at",
                "duration_s",
                "total_tokens",
                "total_cost_usd",
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )

    trace_ids = traces_df["trace_id"].tolist()
    selected_trace = st.selectbox(
        "Drill into a trace",
        options=trace_ids,
        format_func=lambda tid: (
            f"{tid} — {traces_df.loc[traces_df['trace_id'] == tid, 'label'].iloc[0]}"
        ),
    )
    if selected_trace:
        sub = calls_df[calls_df["trace_id"] == selected_trace]
        if sub.empty:
            st.caption("No LLM calls recorded for this trace.")
        else:
            st.dataframe(
                sub[
                    [
                        "stage",
                        "model",
                        "input_tokens",
                        "output_tokens",
                        "cost_usd",
                        "latency_ms",
                        "ts",
                        "error",
                    ]
                ],
                use_container_width=True,
                hide_index=True,
            )
