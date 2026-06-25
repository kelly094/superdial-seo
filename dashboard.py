"""
SuperDial SEO Dashboard — run with: streamlit run dashboard.py
"""

import json
import re
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import publish_webflow
import state

state.init_db()

st.set_page_config(page_title="SuperDial SEO", layout="wide", initial_sidebar_state="expanded")

# ── Global CSS ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/*
  Brand palette
  Backgrounds: #FFFCF8  #FDF4E5
  Accents:     #D0E2CE  #ADDBA4  #9487C2  #043E3E
  Primaries:   #043E3E  #2A195A
*/

/* ── Ground ── */
.stApp { background: #FFFCF8; }
.block-container { padding: 4.5rem 2.5rem 4rem; max-width: 1400px; }
[data-testid="stHeader"] { background: transparent; }

/* ── Sidebar ── */
[data-testid="stSidebar"] { background: #2A195A !important; min-width: 210px !important; max-width: 210px !important; }
[data-testid="stSidebar"] > div { padding: 0 !important; }
[data-testid="stSidebarContent"] { padding: 1.75rem 1rem 1.5rem !important; }

/* Sidebar brand */
.sb-brand {
    font-size: 0.7rem; font-weight: 700; letter-spacing: 0.12em;
    text-transform: uppercase; color: #6B5FA0;
    padding: 0 0.5rem; margin-bottom: 1.5rem;
}

/* Sidebar nav buttons */
[data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"] {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    color: #FFFFFF !important;
    padding: 0.48rem 0.85rem !important;
    border-radius: 6px !important;
    font-size: 0.875rem !important;
    font-weight: 400 !important;
    width: 100% !important;
    margin-bottom: 2px;
    line-height: 1.4 !important;
    transition: background 0.12s, color 0.12s !important;
    /* left-align text inside button */
    display: flex !important;
    align-items: center !important;
    justify-content: flex-start !important;
}
[data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"] p,
[data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"] div {
    text-align: left !important;
    justify-content: flex-start !important;
    margin: 0 !important;
}
[data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"]:hover {
    background: rgba(148,135,194,0.15) !important;
    color: #C8BEE8 !important;
}
/* Active state injected dynamically via .nav-active-style below */

/* Sidebar mini-stats */
.sb-stats { font-size: 0.78rem; padding: 0 0.5rem; }
.sb-stats .row { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 7px; }
.sb-stats .lbl { color: #7868A8; }
.sb-stats .val { color: #C8BEE8; font-weight: 700; font-variant-numeric: tabular-nums; font-size: 0.85rem; }

/* ── Metric bar ── */
.metric-bar { display: flex; gap: 12px; margin-bottom: 1.75rem; }
.metric-card {
    flex: 1; background: #FFFFFF; border: 1px solid #EBE5DE;
    border-radius: 8px; padding: 16px 20px; border-left: 3px solid transparent;
}
.metric-card.m1 { border-left-color: #ADDBA4; }
.metric-card.m2 { border-left-color: #9487C2; }
.metric-card.m3 { border-left-color: #D0E2CE; }
.metric-card.m4 { border-left-color: #043E3E; }
.metric-value {
    font-size: 1.85rem; font-weight: 700; color: #18141E;
    font-variant-numeric: tabular-nums; line-height: 1;
}
.metric-value.primary { color: #043E3E; }
.metric-value.dim     { color: #C8C0D0; font-size: 1.4rem; }
.metric-label {
    font-size: 0.65rem; color: #9990A4; text-transform: uppercase;
    letter-spacing: 0.1em; margin-top: 5px;
}

/* ── Section heading ── */
.section-head {
    font-size: 0.65rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.1em; color: #9990A4; margin: 0 0 14px;
}

/* ── Article cards (stVerticalBlockBorderWrapper override) ── */
div[data-testid="stVerticalBlockBorderWrapper"] {
    background: #FFFFFF !important;
    border: 1px solid #EBE5DE !important;
    border-radius: 8px !important;
    margin-bottom: 8px;
}
div[data-testid="stVerticalBlockBorderWrapper"] > div[data-testid="stVerticalBlock"] {
    padding: 10px 16px !important;
    gap: 0 !important;
}
div[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stVerticalBlock"] {
    gap: 0 !important;
}
div[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stMarkdownContainer"] p {
    margin: 0 !important;
}

/* Keyword name */
.kw-name { font-size: 0.92rem; font-weight: 600; color: #18141E; margin: 0 0 6px; line-height: 1.3; }

/* ── Chips ── */
.chips { display: flex; gap: 5px; flex-wrap: wrap; }
.chip {
    display: inline-block; padding: 2px 7px; border-radius: 3px;
    font-size: 0.67rem; font-weight: 500; font-variant-numeric: tabular-nums; white-space: nowrap;
}
.ch-gray   { background: #F0EDE8; color: #5A5068; }
.ch-purple { background: #EDE8F7; color: #2A195A; }
.ch-sage   { background: #D0E2CE; color: #043E3E; }
.ch-amber  { background: #FEF3C7; color: #92400E; }
.ch-green  { background: #C2E4BA; color: #032B2B; }
.ch-red    { background: #FEE2E2; color: #991B1B; }
.ch-teal   { background: #D0E2CE; color: #043E3E; }

/* ── Review button → deep teal primary ── */
button[data-testid="stBaseButton-primary"] {
    background: #043E3E !important;
    border: none !important;
    color: white !important;
    font-size: 0.8rem !important;
}
button[data-testid="stBaseButton-primary"]:hover {
    background: #032B2B !important;
}
button[data-testid="stBaseButton-primary"]:focus {
    box-shadow: 0 0 0 2px rgba(4,62,62,0.3) !important;
}

/* ── QA cards ── */
.qa-card {
    border-radius: 0 5px 5px 0; padding: 9px 12px; margin-bottom: 8px;
    font-size: 0.8rem;
}
.qa-roi_claim         { background: #FFFBEB; border-left: 3px solid #F59E0B; }
.qa-statistic         { background: #EDE8F7; border-left: 3px solid #9487C2; }
.qa-compliance_claim  { background: #FEF2F2; border-left: 3px solid #EF4444; }
.qa-regulatory        { background: #F5F3FF; border-left: 3px solid #8B5CF6; }
.qa-medical_assertion { background: #FDF2F8; border-left: 3px solid #EC4899; }
.qa-title_seo         { background: #F0FDF4; border-left: 3px solid #22C55E; }
.qa-meta_seo          { background: #F0FDF4; border-left: 3px solid #86EFAC; }
.qa-cat {
    font-size: 0.62rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.07em; color: #6B6076;
}
.qa-excerpt { color: #374151; margin-top: 3px; font-style: italic; line-height: 1.45; }

/* ── Reading panel ── */
.reading-panel {
    background: #FFFFFF; border: 1px solid #EBE5DE; border-radius: 8px;
    padding: 2rem 2.75rem; overflow-y: auto;
    font-family: Georgia, 'Times New Roman', serif;
    font-size: 1rem; line-height: 1.8; color: #2D2025;
}
.reading-panel h1 {
    font-family: -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
    font-size: 1.45rem; font-weight: 700; color: #18141E;
    margin: 0 0 1.25rem; line-height: 1.25;
}
.reading-panel h2 {
    font-family: -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
    font-size: 1.05rem; font-weight: 600; color: #1C1C2E;
    margin: 1.75rem 0 0.4rem;
}
.reading-panel h3 {
    font-family: -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
    font-size: 0.92rem; font-weight: 600; color: #1C1C2E;
    margin: 1.25rem 0 0.3rem;
}
.reading-panel p  { margin: 0 0 0.9rem; }
.reading-panel ul, .reading-panel ol { padding-left: 1.35rem; margin: 0 0 0.9rem; }
.reading-panel li { margin-bottom: 0.3rem; }
.reading-panel hr { border: none; border-top: 1px solid #F0EBE3; margin: 1.5rem 0; }
.reading-panel a  { color: #043E3E; }
.reading-panel strong { font-weight: 700; color: #18141E; }

/* ── Keywords table ── */
.kw-table-wrap {
    background: #FFFFFF; border: 1px solid #EBE5DE; border-radius: 8px;
    overflow: hidden; overflow-x: auto;
}
.kw-table { width: 100%; border-collapse: collapse; font-size: 0.84rem; }
.kw-table th {
    text-align: left; font-size: 0.63rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.09em; color: #9990A4; padding: 12px 14px 10px;
    border-bottom: 1px solid #EBE5DE; background: #FDF4E5;
}
.kw-table th.r, .kw-table td.r { text-align: right; }
.kw-table td {
    padding: 11px 14px; border-bottom: 1px solid #F5F0EB;
    color: #18141E; font-variant-numeric: tabular-nums; vertical-align: middle;
}
.kw-table tr:last-child td { border-bottom: none; }
.kw-table tr:hover td { background: #FFFCF8; }
.kw-table .dim { color: #C8C0D0; }

/* State badge */
.badge {
    display: inline-block; padding: 3px 8px; border-radius: 3px;
    font-size: 0.67rem; font-weight: 600; letter-spacing: 0.02em; white-space: nowrap;
}
.b-selected  { background: #EDE8F7; color: #2A195A; }
.b-drafted   { background: #FEF3C7; color: #92400E; }
.b-approved  { background: #D0E2CE; color: #043E3E; }
.b-published { background: #ADDBA4; color: #032B2B; }

/* Remove Streamlit's default top spacing on columns */
div[data-testid="column"] { padding: 0 !important; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ────────────────────────────────────────────────────────────────────

_QA_S = "«QASTART»"
_QA_E = "«QAEND»"


def article_to_html(text: str, highlight_excerpt: str = None) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        text = parts[2].strip() if len(parts) > 2 else text

    # Inject highlight placeholder before markdown→HTML conversion.
    # Try progressively shorter prefixes so partial matches still work.
    if highlight_excerpt:
        for length in (len(highlight_excerpt), 120, 90, 60, 40):
            frag = highlight_excerpt[:length].strip()
            if frag and frag in text:
                text = text.replace(frag, f"{_QA_S}{frag}{_QA_E}", 1)
                break

    def inline(s: str) -> str:
        s = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', s)
        s = re.sub(r'\*(.*?)\*', r'<em>\1</em>', s)
        s = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" target="_blank">\1</a>', s)
        return s

    parts, in_ul = [], False
    for line in text.splitlines():
        if line.startswith("# "):
            if in_ul: parts.append("</ul>"); in_ul = False
            parts.append(f"<h1>{inline(line[2:].strip())}</h1>")
        elif line.startswith("## "):
            if in_ul: parts.append("</ul>"); in_ul = False
            parts.append(f"<h2>{inline(line[3:].strip())}</h2>")
        elif line.startswith("### "):
            if in_ul: parts.append("</ul>"); in_ul = False
            parts.append(f"<h3>{inline(line[4:].strip())}</h3>")
        elif line.startswith(("- ", "* ")):
            if not in_ul: parts.append("<ul>"); in_ul = True
            parts.append(f"<li>{inline(line[2:].strip())}</li>")
        elif line.strip() == "---":
            if in_ul: parts.append("</ul>"); in_ul = False
            parts.append("<hr>")
        elif line.strip() == "":
            if in_ul: parts.append("</ul>"); in_ul = False
        else:
            if in_ul: parts.append("</ul>"); in_ul = False
            parts.append(f"<p>{inline(line.strip())}</p>")
    if in_ul:
        parts.append("</ul>")

    html = "\n".join(parts)

    # Replace placeholders with the actual <mark> element
    html = html.replace(
        _QA_S,
        '<mark id="qa-active" style="background:rgba(173,219,164,0.55);'
        'border-radius:2px;padding:1px 3px;outline:2px solid #ADDBA4">'
    ).replace(_QA_E, "</mark>")

    return html


def fmt_num(v) -> str:
    if v is None or (isinstance(v, float) and v != v): return "—"
    return f"{v:,.0f}"

def fmt_pos(v) -> str:
    if v is None or (isinstance(v, float) and v != v): return "—"
    return f"{v:.1f}"

def chip(text, cls): return f'<span class="chip {cls}">{text}</span>'
def badge(state_val): return f'<span class="badge b-{state_val}">{state_val.title()}</span>'

QA_LABELS = {
    "roi_claim": "ROI Claim",
    "statistic": "Statistic",
    "compliance_claim": "Compliance",
    "regulatory": "Regulatory",
    "medical_assertion": "Medical Assertion",
    "title_seo": "Title SEO",
    "meta_seo": "Meta SEO",
}


# ── Session state ──────────────────────────────────────────────────────────────

if "page" not in st.session_state:
    st.session_state.page = "queue"
if "reviewing_slug" not in st.session_state:
    st.session_state.reviewing_slug = None
if "active_qa_warning" not in st.session_state:
    st.session_state.active_qa_warning = None
if "edit_mode" not in st.session_state:
    st.session_state.edit_mode = False
if "edit_draft_text" not in st.session_state:
    st.session_state.edit_draft_text = ""


# ── Pipeline stats ─────────────────────────────────────────────────────────────

with state.get_db() as conn:
    n_published = conn.execute("SELECT COUNT(*) FROM keywords WHERE state='published'").fetchone()[0]
    n_drafted   = conn.execute("SELECT COUNT(*) FROM keywords WHERE state='drafted'").fetchone()[0]
    n_approved  = conn.execute("SELECT COUNT(*) FROM keywords WHERE state='approved'").fetchone()[0]
    avg_pos_raw = conn.execute("""
        SELECT ROUND(AVG(position), 1) FROM rank_history rh
        WHERE source='page'
          AND date = (SELECT MAX(date) FROM rank_history WHERE slug=rh.slug AND source='page')
    """).fetchone()[0]


# ── Sidebar ────────────────────────────────────────────────────────────────────

NAV = [("queue", "Overview"), ("keywords", "Keywords"), ("rankings", "Rankings"), ("runs", "Run History")]

with st.sidebar:
    st.markdown('<div class="sb-brand">SuperDial SEO</div>', unsafe_allow_html=True)

    # Inject active style by position — sidebar: brand(1), nav buttons(2-5)
    active_nth = [k for k, _ in NAV].index(st.session_state.page) + 2
    st.markdown(f"""
<style>
[data-testid="stSidebarContent"] [data-testid="stVerticalBlock"] > div:nth-child({active_nth}) button {{
    color: #C4B8E8 !important;
    font-weight: 600 !important;
    background: rgba(196,184,232,0.15) !important;
}}
</style>
""", unsafe_allow_html=True)

    for key, label in NAV:
        if st.button(label, key=f"nav_{key}", use_container_width=True):
            st.session_state.page = key
            st.session_state.reviewing_slug = None
            st.session_state.active_qa_warning = None
            st.session_state.edit_mode = False
            st.session_state.edit_draft_text = ""
            st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown(
        f'<div class="sb-stats">'
        f'<div class="row"><span class="lbl">Published</span><span class="val">{n_published}</span></div>'
        f'<div class="row"><span class="lbl">In Review</span><span class="val">{n_drafted}</span></div>'
        f'<div class="row"><span class="lbl">Approved</span><span class="val">{n_approved}</span></div>'
        f'</div>',
        unsafe_allow_html=True,
    )


# ── Metric bar ────────────────────────────────────────────────────────────────

if avg_pos_raw is not None:
    pos_html = f'<div class="metric-value primary">{avg_pos_raw:.1f}</div>'
else:
    pos_html = '<div class="metric-value dim">—</div>'

st.markdown(f"""
<div class="metric-bar">
  <div class="metric-card m1">
    <div class="metric-value">{n_published}</div>
    <div class="metric-label">Published</div>
  </div>
  <div class="metric-card m2">
    <div class="metric-value">{n_drafted}</div>
    <div class="metric-label">Awaiting Review</div>
  </div>
  <div class="metric-card m3">
    <div class="metric-value">{n_approved}</div>
    <div class="metric-label">Approved, Unpublished</div>
  </div>
  <div class="metric-card m4">
    {pos_html}
    <div class="metric-label">Avg GSC Position</div>
  </div>
</div>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: REVIEW QUEUE
# ══════════════════════════════════════════════════════════════════════════════

if st.session_state.page == "queue":

    # ── Review mode (single article) ──────────────────────────────────────────
    if st.session_state.reviewing_slug:
        slug = st.session_state.reviewing_slug

        with state.get_db() as conn:
            kw = conn.execute("SELECT * FROM keywords WHERE slug=?", (slug,)).fetchone()

        if not kw:
            st.session_state.reviewing_slug = None
            st.rerun()

        draft_path = Path(f"drafts/{slug}.md")
        warnings   = state.get_qa_warnings(slug, unresolved_only=True)

        art_state = kw["state"]  # drafted / approved / published
        can_edit    = art_state in ("drafted", "approved")
        can_approve = art_state == "drafted"

        # Back / edit / approve row
        if st.session_state.edit_mode:
            c_back, c_spacer, c_cancel, c_save = st.columns([1, 3, 1.5, 1.5])
            with c_back:
                if st.button("← Back", key="back_btn"):
                    st.session_state.reviewing_slug = None
                    st.session_state.active_qa_warning = None
                    st.session_state.edit_mode = False
                    st.session_state.edit_draft_text = ""
                    st.rerun()
            with c_cancel:
                if st.button("✕ Cancel", key="cancel_edit_btn", use_container_width=True):
                    st.session_state.edit_mode = False
                    st.session_state.edit_draft_text = ""
                    st.rerun()
            with c_save:
                if st.button("Save", type="primary", use_container_width=True, key="save_edit_btn"):
                    draft_path.write_text(st.session_state.edit_draft_text)
                    st.session_state.edit_mode = False
                    st.session_state.edit_draft_text = ""
                    st.rerun()
        else:
            can_publish = art_state == "approved"
            if can_approve:
                cols = [1, 3, 1.5, 1.5]
            elif can_publish:
                cols = [1, 2.5, 1.5, 2]
            elif can_edit:
                cols = [1, 4.5, 1.5]
            else:
                cols = [1, 7]
            btn_cols = st.columns(cols)
            with btn_cols[0]:
                if st.button("← Back", key="back_btn"):
                    st.session_state.reviewing_slug = None
                    st.session_state.active_qa_warning = None
                    st.rerun()
            if can_edit:
                with btn_cols[2]:
                    if st.button("✎ Edit", key="edit_btn", use_container_width=True):
                        st.session_state.edit_mode = True
                        st.session_state.edit_draft_text = draft_path.read_text() if draft_path.exists() else ""
                        st.rerun()
            if can_approve:
                with btn_cols[3]:
                    if st.button("✓ Approve", type="primary", use_container_width=True, key="approve_btn"):
                        state.mark_approved(kw["keyword"])
                        st.session_state.reviewing_slug = None
                        st.session_state.active_qa_warning = None
                        st.rerun()
            if can_publish:
                with btn_cols[3]:
                    if st.button("Ready in Webflow", type="primary", use_container_width=True, key="publish_btn"):
                        try:
                            webflow_id = publish_webflow.publish_draft_and_return_id(draft_path)
                            state.mark_published(kw["keyword"], webflow_item_id=webflow_id)
                            st.session_state.reviewing_slug = None
                            st.session_state.active_qa_warning = None
                            st.rerun()
                        except Exception as e:
                            st.error(f"Webflow publish failed: {e}")

        st.markdown("<div style='margin-bottom:12px'></div>", unsafe_allow_html=True)

        left, right = st.columns([2, 3], gap="medium")

        with left:
            intent = kw["intent"] or "informational"
            n_warn = len(warnings)
            warn_chip  = (
                chip(f"{n_warn} warning{'s' if n_warn != 1 else ''}", "chip ch-amber")
                if n_warn else chip("QA clean", "chip ch-sage")
            )
            vol_c  = chip(f"vol {kw['volume']:.0f}", "chip ch-gray")
            diff_c = chip(f"diff {kw['difficulty']:.0f}", "chip ch-gray")
            int_c  = chip(intent, "chip ch-purple")
            st.markdown(
                f'<p style="font-size:1rem;font-weight:700;color:#1C1C2E;margin:0 0 6px">{kw["keyword"]}</p>'
                f'<div class="chips" style="margin-bottom:1rem">{vol_c}{diff_c}{int_c}{warn_chip}</div>',
                unsafe_allow_html=True,
            )

            # Build lookup so we can resolve active excerpt for the reading panel
            warning_by_id = {w["id"]: w for w in warnings}

            with st.container(height=480, border=True):
                if not warnings:
                    st.success("No QA warnings — article looks clean.")
                else:
                    st.markdown(f'<div class="section-head">QA Flags ({n_warn})</div>', unsafe_allow_html=True)
                    for w in warnings:
                        cat   = w["category"]
                        label = QA_LABELS.get(cat, cat)
                        is_active = st.session_state.active_qa_warning == w["id"]
                        active_ring = "outline:2px solid #ADDBA4;outline-offset:2px;" if is_active else ""
                        st.markdown(
                            f'<div class="qa-card qa-{cat}" style="{active_ring}">'
                            f'<div class="qa-cat">{label}</div>'
                            f'<div class="qa-excerpt">{w["excerpt"]}</div>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
                        ca, cb, cc = st.columns([5, 5, 3])
                        if ca.button("Accept", key=f"acc_{w['id']}"):
                            state.resolve_qa_warning(w["id"], "accepted")
                            if st.session_state.active_qa_warning == w["id"]:
                                st.session_state.active_qa_warning = None
                            st.rerun()
                        if cb.button("Dismiss", key=f"dis_{w['id']}"):
                            state.resolve_qa_warning(w["id"], "dismissed")
                            if st.session_state.active_qa_warning == w["id"]:
                                st.session_state.active_qa_warning = None
                            st.rerun()
                        if cc.button("Find ↗", key=f"find_{w['id']}"):
                            st.session_state.active_qa_warning = w["id"]
                            st.rerun()

        with right:
            if not draft_path.exists():
                st.warning(f"Draft not found: drafts/{slug}.md")
            elif st.session_state.edit_mode:
                st.session_state.edit_draft_text = st.text_area(
                    "Edit draft (markdown)",
                    value=st.session_state.edit_draft_text,
                    height=580,
                    label_visibility="collapsed",
                    key="draft_editor",
                )
            else:
                active_excerpt = None
                active_id = st.session_state.active_qa_warning
                if active_id and active_id in warning_by_id:
                    active_excerpt = warning_by_id[active_id].get("excerpt")

                article_body = article_to_html(
                    draft_path.read_text(),
                    highlight_excerpt=active_excerpt,
                )

                scroll_script = ""
                if active_excerpt:
                    scroll_script = (
                        "<script>"
                        "(function(){"
                        "function go(){"
                        "var el=document.getElementById('qa-active');"
                        "if(el){el.scrollIntoView({behavior:'smooth',block:'center'});}"
                        "}"
                        "go();setTimeout(go,120);setTimeout(go,350);"
                        "})();"
                        "</script>"
                    )

                panel_css = """
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: #FFFFFF; }
body {
    font-family: Georgia, 'Times New Roman', serif;
    font-size: 1rem; line-height: 1.8; color: #2D2025;
    padding: 2rem 2.75rem 3rem;
}
h1 {
    font-family: -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
    font-size: 1.45rem; font-weight: 700; color: #18141E;
    margin: 0 0 1.25rem; line-height: 1.25;
}
h2 {
    font-family: -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
    font-size: 1.05rem; font-weight: 600; color: #18141E;
    margin: 1.75rem 0 0.4rem;
}
h3 {
    font-family: -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
    font-size: 0.92rem; font-weight: 600; color: #18141E;
    margin: 1.25rem 0 0.3rem;
}
p  { margin: 0 0 0.9rem; }
ul, ol { padding-left: 1.35rem; margin: 0 0 0.9rem; }
li { margin-bottom: 0.3rem; }
hr { border: none; border-top: 1px solid #F0EBE3; margin: 1.5rem 0; }
a  { color: #043E3E; }
strong { font-weight: 700; color: #18141E; }
mark#qa-active {
    background: rgba(173,219,164,0.55);
    border-radius: 3px;
    padding: 2px 4px;
    outline: 2px solid #ADDBA4;
    outline-offset: 1px;
}
"""
                panel_html = (
                    "<!DOCTYPE html><html><head><meta charset='utf-8'>"
                    "<style>" + panel_css + "</style>"
                    "</head><body>"
                    + article_body
                    + scroll_script
                    + "</body></html>"
                )

                components.html(panel_html, height=620, scrolling=True)

    # ── List mode ─────────────────────────────────────────────────────────────
    else:
        # Search bar
        search = st.text_input(
            "Search",
            placeholder="Filter by keyword…",
            label_visibility="collapsed",
            key="queue_search",
        ).strip().lower()

        with state.get_db() as conn:
            all_kws = conn.execute(
                "SELECT * FROM keywords WHERE state IN ('drafted','approved','published') ORDER BY volume DESC"
            ).fetchall()

        def matches(kw):
            return not search or search in kw["keyword"].lower()

        drafted   = [k for k in all_kws if k["state"] == "drafted"   and matches(k)]
        approved  = [k for k in all_kws if k["state"] == "approved"  and matches(k)]
        published = [k for k in all_kws if k["state"] == "published" and matches(k)]

        def render_kw_card(kw, btn_label, btn_key):
            slug   = kw["slug"]
            intent = kw["intent"] or "informational"
            n_warn = len(state.get_qa_warnings(slug, unresolved_only=True))
            warn_chip = (
                chip(f"{n_warn} warning{'s' if n_warn != 1 else ''}", "chip ch-amber")
                if n_warn else chip("QA clean", "chip ch-sage")
            )
            vol_chip  = chip(f"vol {fmt_num(kw['volume'])}", "chip ch-gray")
            diff_chip = chip(f"diff {kw['difficulty']:.0f}", "chip ch-gray")
            int_chip  = chip(intent, "chip ch-purple")
            state_chip = badge(kw["state"])
            with st.container(border=True):
                col_info, col_btn = st.columns([5, 1], gap="small", vertical_alignment="center")
                with col_info:
                    st.markdown(
                        f'<div style="padding:4px 0">'
                        f'<p class="kw-name">{kw["keyword"]}</p>'
                        f'<div class="chips">{vol_chip}{diff_chip}{int_chip}{warn_chip}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                with col_btn:
                    if st.button(btn_label, key=btn_key, type="primary", use_container_width=True):
                        st.session_state.reviewing_slug = slug
                        st.rerun()

        # ── Awaiting Review ──
        st.markdown('<div class="section-head">Awaiting Review</div>', unsafe_allow_html=True)
        if drafted:
            for kw in drafted:
                render_kw_card(kw, "Review →", f"open_{kw['slug']}")
        else:
            st.markdown(
                '<p style="font-size:0.82rem;color:#9990A4;margin:0 0 1.25rem">'
                + ("No matches." if search else "No drafts — run: python pipeline.py --step generate")
                + "</p>",
                unsafe_allow_html=True,
            )

        # ── Approved ──
        st.markdown('<div class="section-head" style="margin-top:1.5rem">Approved</div>', unsafe_allow_html=True)
        if approved:
            for kw in approved:
                render_kw_card(kw, "View →", f"open_{kw['slug']}")
        else:
            st.markdown(
                '<p style="font-size:0.82rem;color:#9990A4;margin:0 0 1.25rem">'
                + ("No matches." if search else "Nothing approved yet.")
                + "</p>",
                unsafe_allow_html=True,
            )

        # ── Published ──
        st.markdown('<div class="section-head" style="margin-top:1.5rem">Published</div>', unsafe_allow_html=True)
        if published:
            for kw in published:
                render_kw_card(kw, "View →", f"open_{kw['slug']}")
        else:
            st.markdown(
                '<p style="font-size:0.82rem;color:#9990A4;margin:0 0 1.25rem">'
                + ("No matches." if search else "Nothing published yet.")
                + "</p>",
                unsafe_allow_html=True,
            )


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: KEYWORDS
# ══════════════════════════════════════════════════════════════════════════════

elif st.session_state.page == "keywords":
    st.markdown('<div class="section-head">All Keywords</div>', unsafe_allow_html=True)

    with state.get_db() as conn:
        rows = conn.execute("""
            SELECT
                k.keyword, k.slug, k.state,
                k.volume, k.difficulty, k.cpc, k.intent,
                rh.position   AS gsc_position,
                rh.impressions, rh.clicks
            FROM keywords k
            LEFT JOIN rank_history rh
                ON  rh.slug   = k.slug
                AND rh.source = 'page'
                AND rh.date   = (
                    SELECT MAX(date) FROM rank_history
                    WHERE slug = k.slug AND source = 'page'
                )
            ORDER BY k.volume DESC
        """).fetchall()

    if not rows:
        st.info("No keywords yet. Run: python pipeline.py --step keywords")
    else:
        def intent_chip_html(i):
            return chip(i, "chip ch-purple") if i else '<span class="dim">—</span>'

        def cpc_html(v):
            return f"${v:.2f}" if v else '<span class="dim">—</span>'

        tbody = ""
        for r in rows:
            state_val = r["state"]
            cpc_cell  = f"${r['cpc']:.2f}" if r["cpc"] else '<span class="dim">—</span>'
            tbody += (
                f"<tr>"
                f'<td style="font-weight:500">{r["keyword"]}</td>'
                f'<td>{badge(state_val)}</td>'
                f'<td class="r">{fmt_num(r["volume"])}</td>'
                f'<td class="r">{fmt_num(r["difficulty"])}</td>'
                f'<td class="r">{cpc_cell}</td>'
                f'<td>{intent_chip_html(r["intent"])}</td>'
                f'<td class="r">{fmt_pos(r["gsc_position"])}</td>'
                f'<td class="r">{fmt_num(r["impressions"])}</td>'
                f'<td class="r">{fmt_num(r["clicks"])}</td>'
                f"</tr>"
            )

        st.markdown(f"""
        <div class="kw-table-wrap">
          <table class="kw-table">
            <thead><tr>
              <th>Keyword</th>
              <th>State</th>
              <th class="r">Volume</th>
              <th class="r">Difficulty</th>
              <th class="r">CPC</th>
              <th>Intent</th>
              <th class="r">GSC Position</th>
              <th class="r">Impressions</th>
              <th class="r">Clicks</th>
            </tr></thead>
            <tbody>{tbody}</tbody>
          </table>
        </div>
        <p style="font-size:0.7rem;color:#A0AABB;margin-top:8px">
          {len(rows)} keyword{"s" if len(rows) != 1 else ""} &nbsp;·&nbsp;
          GSC data from most recent tracking run
        </p>
        """, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: RANKINGS
# ══════════════════════════════════════════════════════════════════════════════

elif st.session_state.page == "rankings":
    st.markdown('<div class="section-head">Rankings</div>', unsafe_allow_html=True)

    with state.get_db() as conn:
        rank_df = pd.read_sql_query("""
            SELECT rh.slug, k.target_keyword, rh.date, rh.position, rh.impressions, rh.clicks
            FROM rank_history rh
            LEFT JOIN keywords k ON k.slug = rh.slug
            WHERE rh.source = 'page'
            ORDER BY rh.date DESC
        """, conn)

    if rank_df.empty:
        st.info("No rank data yet. Run: python pipeline.py --step track")
    else:
        latest = rank_df.groupby("slug").first().reset_index()
        prev   = rank_df.groupby("slug").nth(1).reset_index()[["slug", "position"]].rename(
            columns={"position": "prev_position"}
        )
        latest = latest.merge(prev, on="slug", how="left")
        latest["Δ"] = (latest["prev_position"] - latest["position"]).round(1)
        latest = latest.sort_values("clicks", ascending=False)

        st.dataframe(
            latest[["slug", "target_keyword", "position", "impressions", "clicks", "Δ"]],
            use_container_width=True,
        )
        st.caption("Δ = positive means rank improved (lower number = higher on page). Blank = no prior week data.")

        st.markdown('<div class="section-head" style="margin-top:1.5rem">Avg Position Over Time</div>', unsafe_allow_html=True)
        avg_time = rank_df.groupby("date")["position"].mean().reset_index()
        avg_time.columns = ["date", "avg_position"]
        st.line_chart(avg_time.set_index("date"))

    st.markdown('<div class="section-head" style="margin-top:1.5rem">Unexpected Ranking Queries</div>', unsafe_allow_html=True)
    st.caption("Queries your published pages rank for beyond their target keyword.")

    with state.get_db() as conn:
        q_df = pd.read_sql_query("""
            SELECT rh.slug, k.target_keyword, rh.query, rh.position, rh.impressions, rh.clicks
            FROM rank_history rh
            LEFT JOIN keywords k ON k.slug = rh.slug
            WHERE rh.source = 'query'
              AND rh.date = (SELECT MAX(date) FROM rank_history WHERE slug=rh.slug AND source='query')
            ORDER BY rh.impressions DESC
            LIMIT 100
        """, conn)

    if q_df.empty:
        st.info("No query-level data yet.")
    else:
        st.dataframe(q_df, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: RUN HISTORY
# ══════════════════════════════════════════════════════════════════════════════

elif st.session_state.page == "runs":
    st.markdown('<div class="section-head">Run History</div>', unsafe_allow_html=True)

    with state.get_db() as conn:
        runs = conn.execute(
            "SELECT * FROM run_log ORDER BY started_at DESC LIMIT 20"
        ).fetchall()

    if not runs:
        st.info("No runs logged yet. Run: python pipeline.py")
    else:
        for run in runs:
            metrics = json.loads(run["metrics"] or "{}")
            with st.expander(f"{run['started_at']}"):
                st.json(metrics)
