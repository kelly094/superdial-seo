"""
SuperDial SEO Dashboard.

Run with:  streamlit run dashboard.py
"""

import json
from pathlib import Path

import pandas as pd
import streamlit as st

import state

state.init_db()

st.set_page_config(page_title="SuperDial SEO", layout="wide")
st.title("SuperDial SEO Dashboard")

# ── Summary stats ──────────────────────────────────────────────────────────────

with state.get_db() as conn:
    total_published = conn.execute(
        "SELECT COUNT(*) FROM keywords WHERE state='published'"
    ).fetchone()[0]
    pending_review = conn.execute(
        "SELECT COUNT(*) FROM keywords WHERE state='drafted'"
    ).fetchone()[0]
    pending_approval = conn.execute(
        "SELECT COUNT(*) FROM keywords WHERE state='approved'"
    ).fetchone()[0]
    avg_pos = conn.execute("""
        SELECT ROUND(AVG(position), 1) FROM rank_history rh
        WHERE source='page'
          AND date = (SELECT MAX(date) FROM rank_history WHERE slug=rh.slug AND source='page')
    """).fetchone()[0]

col1, col2, col3, col4 = st.columns(4)
col1.metric("Published Articles", total_published)
col2.metric("Drafts Pending Review", pending_review)
col3.metric("Awaiting Approval", pending_approval)
col4.metric("Avg GSC Position", f"{avg_pos:.1f}" if avg_pos is not None else "—")

st.divider()

# ── Review queue ───────────────────────────────────────────────────────────────

st.subheader("Review Queue")

with state.get_db() as conn:
    drafted = conn.execute(
        "SELECT * FROM keywords WHERE state='drafted' ORDER BY drafted_at DESC"
    ).fetchall()

if not drafted:
    st.info("No drafts awaiting review.")
else:
    for kw in drafted:
        slug = kw["slug"]
        draft_path = Path(f"drafts/{slug}.md")
        with st.expander(f"📄 {kw['keyword']}  |  vol:{kw['volume']:.0f}  diff:{kw['difficulty']:.0f}  {kw['intent']}"):
            # QA warnings
            warnings = state.get_qa_warnings(slug, unresolved_only=True)
            if warnings:
                st.warning(f"⚠ {len(warnings)} unresolved QA warning(s)")
                for w in warnings:
                    col_a, col_b, col_c = st.columns([3, 1, 1])
                    col_a.markdown(f"**{w['category']}**: _{w['excerpt']}_")
                    if col_b.button("Accept", key=f"accept_{w['id']}"):
                        state.resolve_qa_warning(w["id"], "accepted")
                        st.rerun()
                    if col_c.button("Dismiss", key=f"dismiss_{w['id']}"):
                        state.resolve_qa_warning(w["id"], "dismissed")
                        st.rerun()
            else:
                st.success("No unresolved QA warnings.")

            if draft_path.exists():
                st.text_area("Draft preview", draft_path.read_text()[:2000], height=200)

            if st.button(f"✅ Approve '{kw['keyword']}'", key=f"approve_{slug}"):
                state.mark_approved(kw["keyword"])
                st.success(f"'{kw['keyword']}' approved. Run: python pipeline.py --step publish")
                st.rerun()

st.divider()

# ── Rank tracker ───────────────────────────────────────────────────────────────

st.subheader("Rank Tracker")

with state.get_db() as conn:
    rank_df_raw = pd.read_sql_query("""
        SELECT rh.slug, k.target_keyword, rh.date, rh.position, rh.impressions, rh.clicks
        FROM rank_history rh
        LEFT JOIN keywords k ON k.slug = rh.slug
        WHERE rh.source = 'page'
        ORDER BY rh.date DESC
    """, conn)

if rank_df_raw.empty:
    st.info("No rank data yet. Run: python pipeline.py --step track")
else:
    # Latest snapshot per slug
    latest = rank_df_raw.groupby("slug").first().reset_index()
    # Week-over-week position delta
    prev = rank_df_raw.groupby("slug").nth(1).reset_index()[["slug", "position"]].rename(
        columns={"position": "prev_position"}
    )
    latest = latest.merge(prev, on="slug", how="left")
    latest["Δ position"] = (latest["prev_position"] - latest["position"]).round(1)
    latest = latest.sort_values("clicks", ascending=False).head(10)

    st.dataframe(
        latest[["slug", "target_keyword", "position", "impressions", "clicks", "Δ position"]],
        use_container_width=True,
    )
    st.caption("Δ position: positive = improved rank (lower number). Blank = no prior week data.")

    # Position over time chart
    st.subheader("Average Position Over Time")
    avg_over_time = rank_df_raw.groupby("date")["position"].mean().reset_index()
    avg_over_time.columns = ["date", "avg_position"]
    st.line_chart(avg_over_time.set_index("date"))

st.divider()

# ── Unexpected ranking queries ─────────────────────────────────────────────────

st.subheader("Unexpected Ranking Queries")
st.caption("Queries your articles rank for that differ from their target keyword.")

with state.get_db() as conn:
    query_df = pd.read_sql_query("""
        SELECT rh.slug, k.target_keyword, rh.query, rh.position, rh.impressions, rh.clicks
        FROM rank_history rh
        LEFT JOIN keywords k ON k.slug = rh.slug
        WHERE rh.source = 'query'
          AND rh.date = (SELECT MAX(date) FROM rank_history WHERE slug=rh.slug AND source='query')
        ORDER BY rh.impressions DESC
        LIMIT 100
    """, conn)

if query_df.empty:
    st.info("No query-level data yet.")
else:
    st.dataframe(query_df, use_container_width=True)

st.divider()

# ── Run history ────────────────────────────────────────────────────────────────

st.subheader("Run History")

with state.get_db() as conn:
    runs = conn.execute(
        "SELECT * FROM run_log ORDER BY started_at DESC LIMIT 10"
    ).fetchall()

if not runs:
    st.info("No runs logged yet.")
else:
    for run in runs:
        metrics = json.loads(run["metrics"] or "{}")
        with st.expander(f"🗓 {run['started_at']}"):
            st.json(metrics)
