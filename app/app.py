"""MRSA Ward Map: the P30 results told as one story, chapter by chapter.

Run from the project root:
    streamlit run app/app.py

A sidebar lists the chapters. Most chapters show the animated scene from
app/demo/ (embedded, locked to that scene); two add a Streamlit view the scenes
do not have (the contact matrix and the what-if outbreak). Everything shown
comes from files the pipeline already saved in results/: nothing is simulated
or fitted here. Run locally only: the I-Bird data licence is unverified.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import plotly.express as px  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402
import streamlit.components.v1 as components  # noqa: E402

import config  # noqa: E402
from src import app_data as ad  # noqa: E402

# Pastel palette (matches app/streamlit_style.css): lavender = Koopman, coral = MRSA, mint = protection
ACCENT = "#7c6cf0"     # lavender: the Koopman model
HIGHLIGHT = "#ef7f73"  # coral: MRSA / the ward in focus
MUTED = "rgba(150, 143, 170, 0.5)"
FONT = "Geist, Inter, system-ui, sans-serif"

# (title, one-line lede, demo scene number or None). Demo scene order:
# 0 story, 1 hospital, 2 contacts, 3 forecast, 4 superspreader, 5 intervention.
CHAPTERS = [
    ("How it spreads", "Three real people, one strain, step by step.", 0),
    ("The hospital", "Six groups, seventeen weeks of swabs.", 1),
    ("Who meets whom", "Most contact stays inside a ward.", 2),
    ("Forecasting", "Can the Koopman model see next week coming?", 3),
    ("What if", "Start an outbreak in one ward and roll the model forward.", None),
    ("Superspreader", "Which ward drives the most spread?", 4),
    ("Intervention", "Same effort, different targets.", 5),
    ("Takeaways", "What the project shows, and what it does not.", None),
]
# Starting iframe height per scene (px); the scene then resizes its frame to fit its content.
DEMO_HEIGHT = {0: 520, 1: 600, 2: 600, 3: 600, 4: 600, 5: 600}

st.set_page_config(page_title="MRSA Ward Map", page_icon="🏥", layout="wide", initial_sidebar_state="auto")  # open on desktop, a closed drawer on phones
st.markdown(f"<style>{(Path(__file__).parent / 'streamlit_style.css').read_text(encoding='utf-8')}</style>",
            unsafe_allow_html=True)


@st.cache_data
def cached_states():
    return ad.load_states_real()


@st.cache_data
def cached_w():
    return ad.load_w()


@st.cache_resource
def cached_model():
    return ad.load_app_model()


@st.cache_data
def cached_demo(scene, stamp):
    """Packed scene HTML; `stamp` (the demo files' latest edit time) refreshes the cache after edits."""
    return ad.demo_html(scene)


def demo_stamp():
    return max(f.stat().st_mtime for f in config.DEMO_DIR.iterdir() if f.is_file())


def chart(fig, pct_title=None):
    """Plotly figure in the app style: Geist type, hairline grid, no toolbar."""
    if pct_title:
        fig.update_yaxes(tickformat=".0%", title=pct_title, rangemode="tozero")
    fig.update_layout(font=dict(family=FONT, size=13), margin=dict(l=8, r=8, t=36, b=8),
                      hoverlabel=dict(font_family=FONT), hovermode="x unified",
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, title_text=""))
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="rgba(128,128,128,0.14)", zeroline=False)
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def answer(text):
    st.info(text)


def go_to(i):
    st.session_state["chapter"] = i


states, W, model = cached_states(), cached_w(), cached_model()

# ------------------------------------------------------------------ sidebar --
with st.sidebar:
    st.markdown(
        f"""<div class="sb-brand">
          <svg viewBox="0 0 40 40" aria-hidden="true"><rect width="40" height="40" rx="10" fill="currentColor"/>
            <path d="M16 9h8v7h7v8h-7v7h-8v-7H9v-8h7z" class="sb-cross"/><circle cx="20" cy="20" r="3.2" fill="{HIGHLIGHT}"/></svg>
          <div><b>MRSA Ward Map</b><span>P30 · Koopman / EDMD</span></div></div>
        <div class="sb-label">Chapters</div>""",
        unsafe_allow_html=True,
    )
    idx = st.radio("Chapter", range(len(CHAPTERS)), key="chapter", label_visibility="collapsed",
                   format_func=lambda i: f"{i + 1:02d} {CHAPTERS[i][0]}")
    st.markdown(
        f"""<div class="sb-progress"><div><span style="width:{(idx + 1) / len(CHAPTERS) * 100:.0f}%"></span></div>
          <small>{idx + 1} of {len(CHAPTERS)}</small></div>
        <div class="sb-foot">I-Bird study · Berck-sur-Mer, 2009<br>Obadia et al. 2015 · Duval et al. 2018</div>""",
        unsafe_allow_html=True,
    )

# ----------------------------------------------------------------- chapter --
# On phones the sidebar is a drawer: close it on the first load and after a
# chapter is picked, so the chapter is never hidden behind it (wide screens: no effect).
if st.session_state.get("_shown_chapter") != idx:
    # the chapter number makes the HTML differ per chapter, so Streamlit runs the script again
    components.html(f'<script data-chapter="{idx}">' + """
      const p = window.parent;
      if (p.innerWidth < 900) {
        const b = [...p.document.querySelectorAll("button")].find((x) => x.getAttribute("aria-label") === "Collapse sidebar");
        if (b) b.click();
      }
    </script>""", height=0)
st.session_state["_shown_chapter"] = idx

title, lede, scene = CHAPTERS[idx]
st.markdown(
    f"""<header class="ch-head"><span class="ch-num">Chapter {idx + 1:02d} / {len(CHAPTERS):02d}</span>
      <h1>{title}</h1><p>{lede}</p></header>""",
    unsafe_allow_html=True,
)

if scene is not None:
    if config.DEMO_DATA_JS.exists():
        components.html(cached_demo(scene, demo_stamp()), height=DEMO_HEIGHT[scene], scrolling=False)
    else:
        st.warning("Demo data missing: run `python -m src.demo_data`, then reload.")

if title == "Who meets whom":
    left, right = st.columns([3, 2], gap="large")
    with left:
        fig = px.imshow(
            W.to_numpy(), x=list(W.columns), y=list(W.index), text_auto=".0%", zmin=0, zmax=1, aspect="auto",
            color_continuous_scale=[[0, "rgba(124,108,240,0.05)"], [0.25, "rgba(124,108,240,0.35)"], [1, ACCENT]],
            labels=dict(x="Contact time spent with", y="People in", color="Share"),
        )
        fig.update_layout(coloraxis_showscale=False, hovermode="closest")
        chart(fig)
    with right:
        share = ad.within_ward_share(W)
        wards = share.drop(index="Other")
        answer(f"Each row shows where a group's contact time goes. Wards keep {wards.min():.0%} to {wards.max():.0%} "
               f"of it inside; the staff-only 'Other' group keeps just {share['Other']:.0%}, so it links the wards.")

elif title == "What if":
    ward = st.selectbox("Outbreak starts in", config.APP_REAL_WARDS, index=3, key="whatif_ward")
    wi = ad.what_if_outbreak(ward, model, states, W)
    fig = go.Figure()
    for g in config.WARD_GROUPS:
        part = wi[wi["group"] == g]
        hot = g == ward
        fig.add_scatter(x=part["week"], y=part["with_outbreak"], name=g, mode="lines",
                        line=dict(color=HIGHLIGHT if hot else MUTED, width=4 if hot else 1.5))
    base = wi[wi["group"] == ward]
    fig.add_scatter(x=base["week"], y=base["without_outbreak"], name=f"{ward}, no outbreak", mode="lines",
                    line=dict(color=HIGHLIGHT, dash="dot", width=2))
    fig.update_xaxes(title="Weeks from now", dtick=1)
    chart(fig, "People with MRSA")
    answer(ad.what_if_sentence(wi, ward))

elif title == "Takeaways":
    weekly = states.groupby("week")[["n_positive", "n_tested"]].sum()
    mean_prev = float((weekly["n_positive"] / weekly["n_tested"]).mean())
    rmse, top = ad.holdout_rmse(), ad.ward_ranking().iloc[0]
    agree = ad.ranking_agreement()
    opts = ad.intervention_options(1, 0.5).set_index("strategy")
    focus_x = opts.loc[f"koopman_targeted_{config.APP_MODEL}", "drop_mean"] / opts.loc["whole_hospital", "drop_mean"]
    n_weeks = states["week"].nunique()
    cards = [
        ("MRSA in a typical week", f"{mean_prev:.0%}", "of people tested", "pos"),
        ("Forecast error, 1 week", f"{rmse['koopman'] * 100:.1f} vs {rmse['persistence'] * 100:.1f}", "Koopman vs last week: a tie", "acc"),
        ("Ward to protect first", top["ward"], f"{top['ground_truth_drop']:.0f} MRSA-days saved by halving its contacts", "safe"),
        ("Ranking agreement", f"{agree['koopman']:.2f} vs {agree['contacts']:.2f}", "Koopman vs plain contact counts", "acc"),
    ]
    st.markdown('<div class="tk-grid">' + "".join(
        f'<div class="tk {tone}"><span>{label}</span><b>{value}</b><small>{note}</small></div>'
        for label, value, note, tone in cards) + "</div>", unsafe_allow_html=True)
    st.markdown(
        f"""<ul class="tk-list">
          <li><b>Spread is local.</b> Most contact stays inside a ward; a few staff links carry MRSA between wards.</li>
          <li><b>Koopman ties the simplest forecast.</b> With {n_weeks} noisy weekly snapshots, nothing beats "same as last week".</li>
          <li><b>Targeting works.</b> Halving contacts in {opts.loc[f"koopman_targeted_{config.APP_MODEL}", "targeted_wards"]} prevents {focus_x:.1f}x as much as spreading the same cut over the whole hospital.</li>
          <li><b>Koopman adds little over contact counts</b> for choosing that ward: both pick it.</li>
        </ul>
        <p class="tk-limits">Limits: one hospital, four months, six groups, no admission or transfer records.</p>""",
        unsafe_allow_html=True,
    )

# ------------------------------------------------------------- next button --
if idx < len(CHAPTERS) - 1:
    st.button(f"Next: {CHAPTERS[idx + 1][0]}  →", on_click=go_to, args=(idx + 1,), type="primary", key="next")
else:
    st.button("Back to the start  ↺", on_click=go_to, args=(0,), key="restart")
