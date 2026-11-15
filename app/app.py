"""MRSA in the hospital: a simple, read-only viewer of the P30 results.

Run from the project root:
    streamlit run app/app.py

Everything shown comes from files the pipeline already saved in results/.
Nothing is simulated or fitted here. Run locally only: the I-Bird data
licence is unverified, so do not deploy this app publicly.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import plotly.express as px  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402
import streamlit.components.v1 as components  # noqa: E402

import config  # noqa: E402
from src import app_data as ad  # noqa: E402

# Palette shared with the animated demo (app/demo/styles.css)
ACCENT = "#3b57d6"   # the Koopman model
HIGHLIGHT = "#e4553a"  # MRSA / the ward in focus
MUTED = "#a3a8b1"
GROUP_COLORS = dict(zip(config.WARD_GROUPS, ["#3b57d6", "#8197ff", "#22995a", "#e4553a", "#d4537e", "#8a8f98"]))
DEMO_HEIGHT = 860  # px; the demo's two-column layout fits in this at normal laptop widths

st.set_page_config(page_title="MRSA Ward Map", page_icon="🏥", layout="wide", initial_sidebar_state="collapsed")
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


def pct_axis(fig, title):
    fig.update_yaxes(tickformat=".0%", title=title, rangemode="tozero")
    fig.update_layout(margin=dict(l=10, r=10, t=30, b=10), legend_title_text="", hovermode="x unified")
    return fig


def answer(text):
    st.info(text, icon="💡")


states = cached_states()
W = cached_w()
model = cached_model()

summary = ad.hospital_summary()
st.markdown(
    f"""<div class="p30-hero">
      <svg viewBox="0 0 40 40" aria-hidden="true"><rect width="40" height="40" rx="12" fill="{ACCENT}"/>
        <path d="M16 9h8v7h7v8h-7v7h-8v-7H9v-8h7z" fill="#fff" opacity=".95"/><circle cx="20" cy="20" r="3.2" fill="{HIGHLIGHT}"/></svg>
      <div><h1>MRSA on the ward map</h1>
        <p>How MRSA moves between the wards of a 200-bed hospital (I-Bird study, Berck-sur-Mer, 2009), and which ward to protect first.</p></div>
      <div class="p30-chips"><span class="p30-chip"><b>{summary['people']}</b> people</span>
        <span class="p30-chip"><b>{summary['groups']}</b> groups</span><span class="p30-chip"><b>{summary['weeks']}</b> weeks</span>
        <span class="p30-chip">Koopman / EDMD</span></div>
    </div>""",
    unsafe_allow_html=True,
)

tab0, tab1, tab2, tab3, tab4 = st.tabs(
    ["▶  Guided demo", "The hospital", "What happened", "What will happen?", "Which ward to protect?"]
)

# ------------------------------------------------------------------ tab 0 --
with tab0:
    if config.DEMO_DATA_JS.exists():
        components.html(ad.demo_html(), height=DEMO_HEIGHT, scrolling=True)
        st.caption("Use ← → inside the demo to step, Space to play or pause, T to switch light / dark. "
                   "Every number comes from the saved results; the walking figures are decoration.")
    else:
        st.warning("The demo data is missing. Run `python -m src.demo_data` from the project root, then reload.")

# ------------------------------------------------------------------ tab 1 --
with tab1:
    c = st.columns(4)
    c[0].metric("People with sensor contacts", summary["people"])
    c[1].metric("Patients", summary["patients"])
    c[2].metric("Staff", summary["staff"])
    c[3].metric("Weeks of MRSA swabs", summary["weeks"])

    st.subheader("Who meets whom?")
    left, right = st.columns([3, 2])
    with left:
        fig = px.imshow(
            W.to_numpy(), x=list(W.columns), y=list(W.index),
            color_continuous_scale=[[0, "rgba(59,87,214,0.04)"], [0.25, "rgba(59,87,214,0.35)"], [1, ACCENT]],
            text_auto=".0%", zmin=0, zmax=1, aspect="auto",
            labels=dict(x="Contact time spent with…", y="People in…", color="Share"),
        )
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), coloraxis_showscale=False)
        st.plotly_chart(fig, width="stretch")
    with right:
        share = ad.within_ward_share(W)
        patient_wards = share.drop(index="Other")
        answer(
            f"People mostly meet others from their own ward: {patient_wards.min():.0%} to "
            f"{patient_wards.max():.0%} of their contact time stays inside the ward. "
            f"Staff in the 'Other' group (night shift, physio, etc.) spend only {share['Other']:.0%} "
            "of their time with each other, so they are the bridge between wards."
        )
        st.caption("Read each row left to right: where that ward's contact time goes. Rows add up to 100%.")
    network_png = config.RESULTS_FIGURES_DIR / "p2_network_by_ward_all.png"
    if network_png.exists():
        with st.expander("Show the full contact network"):
            st.image(str(network_png), width="stretch")

# ------------------------------------------------------------------ tab 2 --
with tab2:
    st.subheader("How much MRSA was there each week?")
    fig = px.line(
        states, x="week", y="prevalence", color="group", markers=True,
        color_discrete_map=GROUP_COLORS, category_orders={"group": config.WARD_GROUPS},
        labels={"week": "Week of study", "prevalence": "People with MRSA", "group": ""},
        hover_data={"n_tested": True, "n_positive": True},
    )
    st.plotly_chart(pct_axis(fig, "People with MRSA"), width="stretch")
    means = states.groupby("group")["prevalence"].mean().drop(index="Other")
    answer(
        f"{means.idxmax()} had the most MRSA, about {means.max():.0%} of people on average. "
        "The lines jump around partly because in some weeks only a few people were swabbed."
    )
    st.caption("Hover over a point to see how many people were tested that week. Gaps are weeks with no swabs in that group.")

    st.subheader("Could the model predict next week?")
    fva = ad.forecast_vs_actual()
    ward = st.selectbox("Ward", config.WARD_GROUPS, index=3, key="fva_ward")
    one = fva[fva["ward"] == ward].sort_values("landing_week")
    fig = go.Figure()
    fig.add_scatter(x=one["landing_week"], y=one["actual"], name="What really happened", mode="lines+markers",
                    line=dict(color=HIGHLIGHT, width=3))
    fig.add_scatter(x=one["landing_week"], y=one["koopman"], name="Koopman forecast", mode="lines+markers",
                    line=dict(color=ACCENT, width=2.5))
    fig.add_scatter(x=one["landing_week"], y=one["persistence"], name="'Same as this week' guess",
                    mode="lines", line=dict(color=MUTED, dash="dash"))
    fig.add_vrect(x0=min(config.HOLDOUT_WEEKS) - 0.5, x1=max(config.HOLDOUT_WEEKS) + 0.5,
                  fillcolor=ACCENT, opacity=0.08, line_width=0, annotation_text="Test weeks", layer="below",
                  annotation_position="top left")
    fig.update_xaxes(title="Week of study")
    st.plotly_chart(pct_axis(fig, "People with MRSA"), width="stretch")
    r = ad.holdout_rmse()
    answer(
        f"On the test weeks the model's one-week forecast is off by about {r['koopman'] * 100:.1f} percentage points "
        f"(RMSE), almost the same as simply guessing 'same as this week' ({r['persistence'] * 100:.1f} points). "
        "So the model is about as good as the simplest guess here, not better. Its real use is the what-if questions in the next two tabs."
    )

# ------------------------------------------------------------------ tab 3 --
with tab3:
    st.subheader("What if an outbreak starts in one ward?")
    ward = st.selectbox(
        f"If MRSA jumps by {config.APP_OUTBREAK_BUMP * 100:.0f} percentage points in…", config.APP_REAL_WARDS, index=3, key="whatif_ward"
    )
    wi = ad.what_if_outbreak(ward, model, states, W)
    fig = go.Figure()
    for g in config.WARD_GROUPS:
        part = wi[wi["group"] == g]
        hot = g == ward
        fig.add_scatter(x=part["week"], y=part["with_outbreak"], name=g, mode="lines",
                        line=dict(color=HIGHLIGHT if hot else MUTED, width=4 if hot else 1.5))
    base = wi[wi["group"] == ward]
    fig.add_scatter(x=base["week"], y=base["without_outbreak"], name=f"{ward} with no outbreak", mode="lines",
                    line=dict(color=HIGHLIGHT, dash="dot", width=2))
    fig.update_xaxes(title="Weeks from now", dtick=1)
    st.plotly_chart(pct_axis(fig, "People with MRSA"), width="stretch")
    answer(ad.what_if_sentence(wi, ward))
    with st.expander("How much extra MRSA does each group get?"):
        last = wi[wi["week"] == wi["week"].max()][["group", "without_outbreak", "with_outbreak", "extra"]]
        st.dataframe(
            last.rename(columns={"group": "Group", "without_outbreak": "No outbreak", "with_outbreak": "With outbreak",
                                 "extra": "Extra"}).style.format({c: "{:.1%}" for c in ["No outbreak", "With outbreak", "Extra"]}),
            hide_index=True, width="stretch",
        )
    st.caption(
        f"Forecast by the {config.APP_MODEL} Koopman model, starting from each ward's usual MRSA level "
        "(average of the first 12 weeks). The model learned from simulated outbreaks, so treat it as an estimate."
    )

# ------------------------------------------------------------------ tab 4 --
with tab4:
    st.subheader("If we can cut contacts in a few wards, which ones?")
    c1, c2 = st.columns(2)
    k = c1.radio("Number of wards we can protect", config.INTERVENTION_K_VALUES, horizontal=True,
                 format_func=lambda v: f"{v} ward" if v == 1 else f"{v} wards")
    red = c2.radio("Cut their contacts by", config.INTERVENTION_REDUCTIONS, index=1, horizontal=True,
                   format_func=lambda v: f"{v:.0%}")
    opts = ad.intervention_options(k, red)
    show = opts[opts["strategy"] != "none"].iloc[::-1]
    colors = [ACCENT if s.startswith("koopman") else MUTED for s in show["strategy"]]
    labels = [f"{l}  ({w})" if w else l for l, w in zip(show["label"], show["targeted_wards"])]
    fig = go.Figure(go.Bar(
        x=show["drop_mean"], y=labels, orientation="h", marker_color=colors,
        error_x=dict(type="data", symmetric=False,
                     array=show["drop_ci_high"] - show["drop_mean"], arrayminus=show["drop_mean"] - show["drop_ci_low"]),
        text=[f"{v:.0f}" for v in show["drop_mean"]], textposition="inside", insidetextanchor="start",
    ))
    fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), xaxis_title="MRSA patient-days prevented (over 16 weeks)")
    st.plotly_chart(fig, width="stretch")
    kp = opts[opts["strategy"].str.startswith("koopman")].iloc[0]
    dg = opts[opts["strategy"] == "degree_targeted"].iloc[0]
    rnd = opts[opts["strategy"] == "random"].iloc[0]
    best = opts.iloc[0]
    if kp["targeted_wards"] == dg["targeted_wards"]:
        lead = (f"The Koopman model and simple contact counting both pick {kp['targeted_wards']}, "
                f"preventing about {kp['drop_mean']:.0f} MRSA patient-days. ")
    elif kp["drop_ci_high"] >= dg["drop_ci_low"] and dg["drop_ci_high"] >= kp["drop_ci_low"]:  # 95% CIs overlap
        lead = (f"The Koopman pick ({kp['targeted_wards']}) and the most-contact pick ({dg['targeted_wards']}) "
                f"are too close to separate: about {kp['drop_mean']:.0f} and {dg['drop_mean']:.0f} "
                "MRSA patient-days prevented. ")
    else:
        lead = (f"Best here: {best['label'].lower()} ({best['targeted_wards'] or 'all wards'}), preventing about "
                f"{best['drop_mean']:.0f} MRSA patient-days. ")
    answer(lead + f"Either way, targeting prevents {kp['drop_mean'] / rnd['drop_mean']:.1f}x as much as choosing "
           "wards at random, for the same effort.")
    st.caption("Each bar is the average over 200 simulated runs; the thin line shows the 95% confidence interval.")

    st.subheader("Which ward matters most?")
    rank = ad.ward_ranking()
    fig = px.bar(rank, x="ward", y="ground_truth_drop", labels={"ward": "", "ground_truth_drop": "MRSA days prevented"},
                 color="ward", color_discrete_map=GROUP_COLORS)
    fig.update_layout(showlegend=False, margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, width="stretch")
    agree = ad.ranking_agreement()
    answer(
        f"Halving contacts in {rank.iloc[0]['ward']} prevents the most MRSA. The Koopman model's ranking of wards "
        f"agrees well with this (rank correlation {agree['koopman']:.2f}), but simply counting each ward's contact "
        f"time agrees even better ({agree['contacts']:.2f}). With only 6 groups, neither ranking is statistically strong."
    )

st.markdown(
    '<div class="p30-foot">Read-only viewer of the saved P30 results: nothing is simulated or fitted here. '
    "Data: I-Bird study (Obadia et al. 2015, PLOS Comput Biol; Duval et al. 2018, Sci Rep). "
    "Local use only: the data licence is unverified.</div>",
    unsafe_allow_html=True,
)
