"""
streamlit_app.py
Should-Cost Estimator — V2 UI
Single-part estimation for machined aerospace parts.

Run:
    streamlit run streamlit_app.py

Requires:
    pip install -r requirements.txt
"""

import sys
import os
from html import escape
from pathlib import Path
import tempfile

import streamlit as st

# ─── PATH SETUP ───────────────────────────────────────────────────────────────
# Allow running from the project root or from app/
_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_here)
if _root not in sys.path:
    sys.path.insert(0, _root)

from engine.models import (
    Material, ComplexityTier, ToleranceTier, Region, OutsideProcess,
    OverrideSource, PartInputs
)
from engine.estimator import estimate_cost
from engine.explain import summarize_estimate
from exporters.excel_export import export_to_excel

# ─── PAGE CONFIG ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Should-Cost Estimator",
    page_icon="⚙",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─── MINIMAL CSS ──────────────────────────────────────────────────────────────
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

  html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

  .hero-card {
    background: #ffffff;
    border: 1px solid #d0cfc9;
    border-top: 3px solid #c94a1e;
    padding: 24px 28px 20px;
    margin-bottom: 16px;
  }
  .hero-label {
    font-size: 0.62rem;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: #6b6b6b;
    font-family: 'Courier New', monospace;
    margin-bottom: 6px;
  }
  .mid-price {
    font-size: 2.8rem;
    font-weight: 700;
    color: #c94a1e;
    line-height: 1;
    margin-bottom: 4px;
  }
  .band-range {
    font-family: 'Courier New', monospace;
    font-size: 0.8rem;
    color: #6b6b6b;
  }
  .conf-high  { color: #2d7a4e; font-weight: 700; font-family: 'Courier New', monospace; }
  .conf-med   { color: #c4a227; font-weight: 700; font-family: 'Courier New', monospace; }
  .conf-low   { color: #c94a1e; font-weight: 700; font-family: 'Courier New', monospace; }
  .section-rule {
    border: none;
    border-top: 1px solid #d0cfc9;
    margin: 24px 0 20px;
  }
  .source-label {
    font-family: 'Courier New', monospace;
    font-size: 0.62rem;
    color: #2d7a4e;
    letter-spacing: 0.08em;
  }
  .footer-meta {
    font-family: 'Courier New', monospace;
    font-size: 0.62rem;
    color: #aaa;
    margin-top: 32px;
    padding-top: 12px;
    border-top: 1px solid #d0cfc9;
  }
</style>
""", unsafe_allow_html=True)


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def _conf_html(level: str) -> str:
    cls = {"High": "conf-high", "Medium": "conf-med", "Low": "conf-low"}.get(level, "conf-low")
    return f'<span class="{cls}">{level}</span>'


def _fmt(val: float) -> str:
    return f"${val:,.0f}"


def _pct(part: float, total: float) -> str:
    if total == 0:
        return "—"
    return f"{part / total * 100:.1f}%"


# ─── HEADER ───────────────────────────────────────────────────────────────────
st.markdown("#### — Sourcing Operations Suite")
st.title("Parametric Should-Cost Estimator")
st.caption("Defensible price estimation for machined aerospace parts  ·  Kenyon Woodley")
st.caption("Use fictional part and program details in this public demo.")
st.markdown('<hr class="section-rule">', unsafe_allow_html=True)


# ─── SECTION 1: PART INPUTS ───────────────────────────────────────────────────
st.subheader("01 — Part Inputs")

col_left, col_right = st.columns(2)

with col_left:
    st.markdown("**Identification**")
    part_id   = st.text_input("Part ID",          value="DEMO-001", help="A fictional part identifier for the demo.")
    part_desc = st.text_input("Part Description", value="Example machined bracket",       help="Short description — surfaces in Excel output.")
    program   = st.text_input("Program / Project", value="",      help="Optional. For tracking only.")

    st.markdown("**Material & Geometry**")
    material_options = [m.value for m in Material]
    material_str = st.selectbox("Material", material_options, index=0)
    material = Material(material_str)

    finished_weight = st.number_input(
        "Finished Weight (lb)",
        min_value=0.01, max_value=500.0,
        value=1.0, step=0.1,
        help="Finished part weight in pounds."
    )

    st.caption("Buy-to-fly ratio is estimated from the material and complexity tier.")

with col_right:
    st.markdown("**Process Parameters**")
    complexity_options = {
        "Tier 1 — Simple":     ComplexityTier.SIMPLE,
        "Tier 2 — Low":        ComplexityTier.LOW,
        "Tier 3 — Medium":     ComplexityTier.MEDIUM,
        "Tier 4 — High":       ComplexityTier.HIGH,
        "Tier 5 — Very High":  ComplexityTier.VERY_HIGH,
    }
    complexity_label = st.selectbox("Complexity Tier", list(complexity_options.keys()), index=2)
    complexity = complexity_options[complexity_label]

    tolerance_options = {"Standard": ToleranceTier.STANDARD, "Tight": ToleranceTier.TIGHT}
    tolerance_label = st.selectbox("Tolerance Tier", list(tolerance_options.keys()))
    tolerance = tolerance_options[tolerance_label]

    region_options = {r.value: r for r in Region}
    region_label = st.selectbox("Manufacturing Region", list(region_options.keys()))
    region = region_options[region_label]

    st.markdown("**Volume**")
    col_v1, col_v2 = st.columns(2)
    annual_volume = col_v1.number_input("Annual Volume", min_value=1, max_value=100000, value=500, step=50)
    batch_size    = col_v2.number_input("Batch Size",    min_value=1, max_value=annual_volume, value=min(100, annual_volume), step=10)

    st.markdown("**Outside Processes**")
    op_options = {op.value.replace("_", " ").title(): op for op in OutsideProcess}
    selected_ops_labels = st.multiselect("Select processes (optional)", list(op_options.keys()))
    outside_processes = [op_options[lbl] for lbl in selected_ops_labels]

    st.markdown("**Overrides**")
    with st.expander("Machining / Setup Hour Overrides (optional)"):
        mach_override = st.number_input("Machining Hours Override (0 = use table default)", min_value=0.0, max_value=100.0, value=0.0, step=0.5)
        setup_override = st.number_input("Setup Hours Override (0 = use table default)", min_value=0.0, max_value=50.0, value=0.0, step=0.25)
        if mach_override > 0 or setup_override > 0:
            override_src_label = st.radio("Override source", ["Verified (from routing/CAM)", "Unverified (estimate)"])
            override_source = OverrideSource.VERIFIED if "Verified" in override_src_label else OverrideSource.UNVERIFIED
        else:
            mach_override = None
            setup_override = None
            override_source = None

    notes = st.text_area("Notes (optional)", value="", height=80,
                          help="Free-text field — surfaces in Excel Notes tab.")

st.markdown('<hr class="section-rule">', unsafe_allow_html=True)


# ─── SECTION 2: RUN ───────────────────────────────────────────────────────────
st.subheader("02 — Estimate")

run_disabled = False
run_btn = st.button("Run Should-Cost Estimate", type="primary", disabled=run_disabled)

if run_btn:
    try:
        inputs = PartInputs(
            part_id=part_id,
            part_description=part_desc,
            material=material,
            finished_weight_lb=finished_weight,
            complexity_tier=complexity,
            tolerance_tier=tolerance,
            annual_volume=annual_volume,
            batch_size=batch_size,
            region=region,
            machining_hours_override=mach_override if mach_override else None,
            setup_hours_override=setup_override if setup_override else None,
            override_source=override_source,
            outside_processes=outside_processes,
            program=program or None,
            notes=notes or None,
        )

        with st.spinner("Computing estimate…"):
            estimate = estimate_cost(inputs)

        st.session_state["estimate"] = estimate
        st.session_state["inputs_raw"] = inputs.model_dump()
        st.session_state["run_complete"] = True

    except Exception as e:
        st.error(f"Estimation failed: {e}")
        st.session_state["run_complete"] = False


# ─── OUTPUT CARD ──────────────────────────────────────────────────────────────
if st.session_state.get("run_complete") and "estimate" in st.session_state:
    est = st.session_state["estimate"]
    pb  = est.price_band
    bd  = est.breakdown

    st.markdown('<hr class="section-rule">', unsafe_allow_html=True)
    st.subheader("03 — Results")

    # Hero row
    hero_col, conf_col = st.columns([3, 1])

    with hero_col:
        st.markdown(f"""
        <div class="hero-card">
          <div class="hero-label">Should-Cost Estimate — {escape(est.part_id)}</div>
          <div class="mid-price">{_fmt(pb.mid)}</div>
          <div class="band-range">Low: {_fmt(pb.low)} &nbsp;|&nbsp; Mid: {_fmt(pb.mid)} &nbsp;|&nbsp; High: {_fmt(pb.high)}</div>
        </div>
        """, unsafe_allow_html=True)

    with conf_col:
        st.markdown(f"""
        <div class="hero-card" style="text-align:center;">
          <div class="hero-label">Confidence</div>
          <div style="font-size:1.6rem; margin:8px 0;">{_conf_html(est.confidence.value)}</div>
          <div style="font-size:0.7rem; color:#6b6b6b; font-family:'Courier New',monospace;">
            {"<br>".join(est.confidence_notes) if est.confidence_notes else "No demerits"}
          </div>
        </div>
        """, unsafe_allow_html=True)

    # Price band metrics
    band_cols = st.columns(3)
    band_cols[0].metric("Low", _fmt(pb.low),  delta=_fmt(pb.low  - pb.mid), delta_color="off")
    band_cols[1].metric("Mid", _fmt(pb.mid))
    band_cols[2].metric("High", _fmt(pb.high), delta=_fmt(pb.high - pb.mid), delta_color="off")

    st.markdown('<hr class="section-rule">', unsafe_allow_html=True)

    # Cost breakdown + sensitivity side by side
    breakdown_col, sensitivity_col = st.columns(2)

    with breakdown_col:
        st.markdown("**Cost Breakdown — Mid Scenario**")
        breakdown_data = {
            "Element": [
                "Material", "Machining", "Setup (per piece)",
                "Outside Processes", "Scrap", "Overhead", "Margin", "Unit Price"
            ],
            "Amount": [
                _fmt(bd.material_cost),
                _fmt(bd.machining_cost),
                _fmt(bd.setup_cost_per_piece),
                _fmt(bd.outside_process_cost),
                _fmt(bd.scrap_cost),
                _fmt(bd.overhead_cost),
                _fmt(bd.supplier_margin),
                _fmt(bd.unit_price_mid),
            ],
            "% of Price": [
                _pct(bd.material_cost,        bd.unit_price_mid),
                _pct(bd.machining_cost,       bd.unit_price_mid),
                _pct(bd.setup_cost_per_piece, bd.unit_price_mid),
                _pct(bd.outside_process_cost, bd.unit_price_mid),
                _pct(bd.scrap_cost,           bd.unit_price_mid),
                _pct(bd.overhead_cost,        bd.unit_price_mid),
                _pct(bd.supplier_margin,      bd.unit_price_mid),
                "100%",
            ]
        }
        import pandas as pd
        st.dataframe(
            pd.DataFrame(breakdown_data),
            use_container_width=True,
            hide_index=True
        )

    with sensitivity_col:
        st.markdown("**Sensitivity Analysis — Top Drivers (+10% perturbation)**")
        if est.sensitivity:
            sens_data = {
                "Variable": [s.variable for s in est.sensitivity],
                "Δ Price":  [_fmt(s.delta_dollar) for s in est.sensitivity],
                "Δ %":      [f"+{s.delta_pct:.1f}%" for s in est.sensitivity],
            }
            st.dataframe(
                pd.DataFrame(sens_data),
                use_container_width=True,
                hide_index=True
            )
            st.caption(
                "Machine rate and machining hours dominate for most machined parts. "
                "Material price becomes significant on high buy-to-fly or expensive alloys."
            )

    st.markdown('<hr class="section-rule">', unsafe_allow_html=True)

    with st.expander("Sourcing summary", expanded=True):
        summary = summarize_estimate(est)
        st.markdown(summary.replace("$", r"\$"))

    # ── EXPORT BUTTON ─────────────────────────────────────────────────────────
    st.markdown('<hr class="section-rule">', unsafe_allow_html=True)

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            export_path = Path(temp_dir) / "should_cost.xlsx"
            export_to_excel(est, st.session_state.get("inputs_raw", {}), export_path)
            excel_bytes = export_path.read_bytes()

        fname = f"{est.part_id}_should_cost.xlsx"
        st.download_button(
            label="Download Should-Cost Report (.xlsx)",
            data=excel_bytes,
            file_name=fname,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except Exception as e:
        st.error(f"Export failed: {e}")


# ─── FOOTER ───────────────────────────────────────────────────────────────────
st.markdown("""
<div class="footer-meta">
  Parametric Should-Cost Model V2 &nbsp;|&nbsp;
  Python engine + Streamlit &nbsp;|&nbsp;
  8 materials, 5 complexity tiers, 3 regions, 9 outside processes &nbsp;|&nbsp;
  Excel export is read-only. Python is source of truth.
</div>
""", unsafe_allow_html=True)
