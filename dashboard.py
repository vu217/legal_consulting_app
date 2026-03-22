"""
dashboard.py  —  Legal RAG Analytical Dashboard
Run with:  streamlit run dashboard.py
"""

import os
import tempfile
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from dotenv import load_dotenv

from ingestion import ingest_pdf
from master_agent import run_analysis

load_dotenv()

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="LegalMind — Case Intelligence",
    page_icon="⚖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Main background */
    .stApp { background-color: #0d1117; color: #e6edf3; }
    .block-container { padding: 1.5rem 2rem; max-width: 1400px; }

    /* Headers */
    h1, h2, h3 { color: #e6edf3 !important; font-weight: 500 !important; }

    /* Metric cards */
    [data-testid="metric-container"] {
        background: #161b22;
        border: 1px solid #30363d;
        border-radius: 10px;
        padding: 1rem;
    }
    [data-testid="metric-container"] label { color: #8b949e !important; font-size: 12px; }
    [data-testid="metric-container"] [data-testid="stMetricValue"] {
        color: #58a6ff !important; font-size: 28px; font-weight: 500;
    }

    /* Section cards */
    .legal-card {
        background: #161b22;
        border: 1px solid #30363d;
        border-radius: 10px;
        padding: 1.2rem 1.4rem;
        margin-bottom: 1rem;
    }
    .card-title {
        font-size: 13px;
        font-weight: 500;
        color: #8b949e;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 0.6rem;
    }
    .card-body { color: #c9d1d9; font-size: 14px; line-height: 1.7; }

    /* Case reference pill */
    .case-pill {
        display: inline-block;
        background: #1f2937;
        border: 1px solid #374151;
        border-radius: 6px;
        padding: 3px 10px;
        font-size: 12px;
        color: #93c5fd;
        margin: 3px 3px 3px 0;
    }

    /* Outcome badge */
    .badge-win  { background:#0d4a2a; color:#4ade80; border:1px solid #16a34a; border-radius:4px; padding:2px 8px; font-size:11px; }
    .badge-loss { background:#4a0d0d; color:#f87171; border:1px solid #dc2626; border-radius:4px; padding:2px 8px; font-size:11px; }
    .badge-unk  { background:#1f2937; color:#9ca3af; border:1px solid #374151; border-radius:4px; padding:2px 8px; font-size:11px; }

    /* Streamlit sidebar */
    section[data-testid="stSidebar"] { background: #0d1117; border-right: 1px solid #21262d; }
    section[data-testid="stSidebar"] .stMarkdown { color: #8b949e; }

    /* Input boxes */
    .stTextInput input, .stTextArea textarea {
        background: #0d1117 !important;
        border: 1px solid #30363d !important;
        color: #e6edf3 !important;
        border-radius: 8px !important;
    }
    .stButton button {
        background: #238636 !important;
        color: #ffffff !important;
        border: none !important;
        border-radius: 8px !important;
        font-weight: 500 !important;
    }
    .stButton button:hover { background: #2ea043 !important; }

    /* Divider */
    hr { border-color: #21262d !important; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def win_gauge(probability: int) -> go.Figure:
    color = "#4ade80" if probability >= 60 else "#facc15" if probability >= 40 else "#f87171"
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=probability,
        number={"suffix": "%", "font": {"size": 48, "color": color}},
        gauge={
            "axis": {"range": [0, 100], "tickcolor": "#8b949e", "tickfont": {"color": "#8b949e", "size": 11}},
            "bar":  {"color": color, "thickness": 0.3},
            "bgcolor": "#161b22",
            "bordercolor": "#30363d",
            "steps": [
                {"range": [0,  40], "color": "#1a0a0a"},
                {"range": [40, 60], "color": "#1a180a"},
                {"range": [60, 100], "color": "#0a1a0e"},
            ],
            "threshold": {
                "line": {"color": color, "width": 3},
                "thickness": 0.8,
                "value": probability,
            },
        },
    ))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": "#e6edf3"},
        height=220,
        margin=dict(l=20, r=20, t=20, b=10),
    )
    return fig


def outcome_chart(cases: list) -> go.Figure:
    if not cases:
        return None
    df = pd.DataFrame(cases)
    outcome_counts = df["outcome"].value_counts().reset_index()
    outcome_counts.columns = ["outcome", "count"]
    color_map = {
        "acquitted": "#4ade80", "allowed": "#4ade80", "upheld": "#4ade80", "quashed": "#4ade80",
        "convicted": "#f87171", "dismissed": "#f87171", "sentenced": "#f87171",
        "unknown":   "#9ca3af",
    }
    colors = [color_map.get(o.lower(), "#9ca3af") for o in outcome_counts["outcome"]]
    fig = go.Figure(go.Bar(
        x=outcome_counts["outcome"],
        y=outcome_counts["count"],
        marker_color=colors,
        text=outcome_counts["count"],
        textposition="auto",
    ))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": "#8b949e", "size": 12},
        xaxis=dict(tickfont={"color": "#8b949e"}, gridcolor="#21262d"),
        yaxis=dict(tickfont={"color": "#8b949e"}, gridcolor="#21262d"),
        height=220,
        margin=dict(l=10, r=10, t=10, b=30),
        showlegend=False,
    )
    return fig


def badge_html(outcome: str) -> str:
    o = outcome.lower()
    if any(w in o for w in ["acquitted", "allowed", "upheld", "quashed"]):
        return f'<span class="badge-win">{outcome}</span>'
    if any(w in o for w in ["convicted", "dismissed", "sentenced", "remanded"]):
        return f'<span class="badge-loss">{outcome}</span>'
    return f'<span class="badge-unk">{outcome or "unknown"}</span>'


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## ⚖ LegalMind")
    st.markdown("*100% local · DeepSeek R1 · Qdrant*")
    st.divider()

    st.markdown("### Index PDFs")
    uploaded_files = st.file_uploader(
        "Upload case PDFs", type="pdf", accept_multiple_files=True, label_visibility="collapsed"
    )
    if uploaded_files:
        if st.button("Ingest all PDFs"):
            progress = st.progress(0)
            total_chunks = 0
            for i, f in enumerate(uploaded_files):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                    tmp.write(f.read())
                    tmp_path = tmp.name
                with st.spinner(f"Indexing {f.name}..."):
                    try:
                        n = ingest_pdf(tmp_path)
                        total_chunks += n
                        st.success(f"{f.name}: {n} chunks")
                    except Exception as e:
                        st.error(f"{f.name}: {e}")
                os.unlink(tmp_path)
                progress.progress((i + 1) / len(uploaded_files))
            st.success(f"Done — {total_chunks} total chunks indexed")

    st.divider()
    st.markdown("### Model")
    st.caption(f"LLM: `{os.getenv('LLM_MODEL','deepseek-r1:8b')}`")
    st.caption(f"Embeddings: `{os.getenv('EMBED_MODEL','nomic-embed-text')}`")
    st.caption(f"Vector DB: Qdrant @ `{os.getenv('QDRANT_URL','localhost:6333')}`")
    st.divider()
    st.caption("All inference runs locally. No data leaves your machine.")


# ── Main area ─────────────────────────────────────────────────────────────────

st.markdown("# Case Intelligence Dashboard")
st.markdown("Describe your case below. The system runs 5 specialist agents in parallel and synthesises the results.")

query = st.text_area(
    "Case description",
    placeholder="e.g. My client is accused of cheating under Section 420 IPC. The complainant alleges financial fraud of ₹15 lakhs. There is no written agreement and the transaction was cash-based. What are the chances of acquittal and how should we proceed?",
    height=100,
    label_visibility="collapsed",
)

col_btn, col_hint = st.columns([1, 4])
with col_btn:
    analyse = st.button("Run analysis", use_container_width=True)
with col_hint:
    st.caption("Runs ~5-8 seconds on a modern laptop with Ollama")

# ── Session state ─────────────────────────────────────────────────────────────
if "result" not in st.session_state:
    st.session_state.result = None

if analyse and query.strip():
    with st.spinner("Running 5 parallel agents..."):
        st.session_state.result = run_analysis(query)

result = st.session_state.result

if result:
    st.divider()

    # ── Row 1: KPI metrics ────────────────────────────────────────────────────
    m1, m2, m3, m4 = st.columns(4)
    win_prob      = result.get("win_probability", 50)
    cases_found   = len(result.get("precedent", {}).get("similar_cases", []))
    statutes_raw  = result.get("statute", {}).get("statutes_raw", [])
    stats         = result.get("winrate", {}).get("stats", {})

    with m1:
        st.metric("Win probability", f"{win_prob}%")
    with m2:
        st.metric("Similar cases found", cases_found)
    with m3:
        st.metric("Statutes identified", len(statutes_raw))
    with m4:
        base = stats.get("base_rate_pct", "—")
        st.metric("Historical base rate", f"{base}%" if isinstance(base, int) else base)

    st.markdown("")

    # ── Row 2: Gauge + Outcome chart ──────────────────────────────────────────
    gc1, gc2 = st.columns([1, 1])

    with gc1:
        st.markdown('<div class="legal-card"><div class="card-title">Win probability gauge</div>', unsafe_allow_html=True)
        fig_gauge = win_gauge(win_prob)
        st.plotly_chart(fig_gauge, use_container_width=True, config={"displayModeBar": False})
        verdict = "Favourable outlook" if win_prob >= 60 else "Uncertain" if win_prob >= 40 else "Challenging case"
        st.caption(f"Assessment: {verdict}")
        st.markdown('</div>', unsafe_allow_html=True)

    with gc2:
        similar_cases = result.get("precedent", {}).get("similar_cases", [])
        st.markdown('<div class="legal-card"><div class="card-title">Outcome distribution in similar cases</div>', unsafe_allow_html=True)
        if similar_cases:
            fig_bar = outcome_chart(similar_cases)
            if fig_bar:
                st.plotly_chart(fig_bar, use_container_width=True, config={"displayModeBar": False})
        else:
            st.caption("No similar cases retrieved yet. Index some PDFs first.")
        st.markdown('</div>', unsafe_allow_html=True)

    st.divider()

    # ── Row 3: Executive summary ──────────────────────────────────────────────
    st.markdown('<div class="legal-card">', unsafe_allow_html=True)
    st.markdown('<div class="card-title">Executive summary</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="card-body">{result.get("summary","")}</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    # ── Row 4: Case references ────────────────────────────────────────────────
    st.markdown("### Similar case references")
    if similar_cases:
        cols = st.columns(min(len(similar_cases), 3))
        for i, case in enumerate(similar_cases[:3]):
            with cols[i % 3]:
                st.markdown(f"""
<div class="legal-card">
  <div class="card-title">Case {case['rank']}</div>
  <div class="card-body">
    <strong style="color:#93c5fd">{case.get('case_name','Unknown case')}</strong><br>
    <small>{case.get('court','')} &nbsp;·&nbsp; {case.get('year','')}</small><br><br>
    {badge_html(case.get('outcome',''))}<br><br>
    <small style="color:#8b949e">{case.get('chunk','')[:250]}...</small>
  </div>
</div>""", unsafe_allow_html=True)
    else:
        st.info("No similar cases found. Upload and index PDFs to populate the knowledge base.")

    # ── Row 5: Statutes + Evidence (side by side) ─────────────────────────────
    sc1, sc2 = st.columns(2)

    with sc1:
        st.markdown("### Statute map")
        st.markdown('<div class="legal-card"><div class="card-title">Applicable laws</div>', unsafe_allow_html=True)
        if statutes_raw:
            pills_html = " ".join(f'<span class="case-pill">{s[:60]}</span>' for s in statutes_raw[:10])
            st.markdown(f'<div style="margin-bottom:0.8rem">{pills_html}</div>', unsafe_allow_html=True)
        analysis = result.get("statute", {}).get("analysis", "")
        st.markdown(f'<div class="card-body">{analysis}</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with sc2:
        st.markdown("### Evidence to seek")
        st.markdown('<div class="legal-card"><div class="card-title">Recommended evidence</div>', unsafe_allow_html=True)
        ev_analysis = result.get("evidence", {}).get("analysis", "")
        st.markdown(f'<div class="card-body">{ev_analysis}</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    # ── Row 6: Strategy ───────────────────────────────────────────────────────
    st.markdown("### Case framing strategies")
    st.markdown('<div class="legal-card"><div class="card-title">Recommended approaches</div>', unsafe_allow_html=True)
    strat_analysis = result.get("strategy", {}).get("analysis", "")
    st.markdown(f'<div class="card-body">{strat_analysis}</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    # ── Row 7: Win-rate deep dive ─────────────────────────────────────────────
    st.markdown("### Win-rate analysis")
    wc1, wc2 = st.columns([2, 1])
    with wc1:
        st.markdown('<div class="legal-card"><div class="card-title">Detailed probability breakdown</div>', unsafe_allow_html=True)
        wr_analysis = result.get("winrate", {}).get("analysis", "")
        st.markdown(f'<div class="card-body">{wr_analysis}</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
    with wc2:
        st.markdown('<div class="legal-card"><div class="card-title">Probability components</div>', unsafe_allow_html=True)
        base_r  = result.get("winrate", {}).get("base_rate",    50)
        llm_est = result.get("winrate", {}).get("llm_estimate", 50)
        fig_comp = go.Figure(go.Bar(
            x=["Historical base rate", "LLM estimate", "Blended"],
            y=[base_r, llm_est, win_prob],
            marker_color=["#60a5fa", "#a78bfa", "#4ade80"],
            text=[f"{v}%" for v in [base_r, llm_est, win_prob]],
            textposition="auto",
        ))
        fig_comp.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font={"color": "#8b949e", "size": 11},
            xaxis=dict(tickfont={"color": "#8b949e"}, gridcolor="#21262d"),
            yaxis=dict(tickfont={"color": "#8b949e"}, gridcolor="#21262d", range=[0,100]),
            height=200,
            margin=dict(l=10, r=10, t=10, b=10),
            showlegend=False,
        )
        st.plotly_chart(fig_comp, use_container_width=True, config={"displayModeBar": False})
        st.markdown('</div>', unsafe_allow_html=True)

elif not result:
    # Empty state
    st.markdown("""
<div style="text-align:center; padding:4rem 2rem; color:#8b949e;">
  <div style="font-size:48px; margin-bottom:1rem">⚖</div>
  <div style="font-size:18px; font-weight:500; color:#c9d1d9; margin-bottom:0.5rem">No case loaded yet</div>
  <div style="font-size:14px">Upload PDFs in the sidebar to build your knowledge base,<br>then describe your case above to run the analysis.</div>
</div>
""", unsafe_allow_html=True)
