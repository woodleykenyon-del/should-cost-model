# Parametric Should-Cost Model V2

Defensible price estimation for machined aerospace parts. Part of a five-tool sourcing operations portfolio.

**Stack:** Python + Streamlit + Excel (openpyxl) + cadquery (optional, local only)

---

## What it does

Given material, part weight, complexity tier, tolerance tier, volume, and region — the engine produces a three-scenario price band (Low / Mid / High) with sensitivity analysis, confidence scoring, and an optional AI-generated sourcing narrative.

V2 adds optional STEP file geometry ingestion (local only): upload a STEP file and the engine derives finished weight and a suggested buy-to-fly ratio from the actual part geometry.

## Live demo

[Launch on Streamlit Cloud →](https://your-app.streamlit.app)

---

## Running locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Optional: install cadquery for STEP file upload support
# Recommended via conda: conda install -c conda-forge cadquery

streamlit run streamlit_app.py
```

## Project structure

```
should-cost-model/
├── streamlit_app.py          # Streamlit UI
├── requirements.txt
├── engine/
│   ├── models.py             # Input/output dataclasses + enums
│   ├── estimator.py          # Deterministic cost engine
│   ├── assumptions.py        # Data loaders (CSV + JSON)
│   └── explain.py            # AI narrative layer (Claude API)
├── geometry/
│   └── step_reader.py        # STEP parser + BTF derivation (cadquery)
├── exporters/
│   └── excel_export.py       # 5-tab Excel workbook export
└── data/
    ├── assumptions_default.json
    ├── materials.csv
    └── machine_rates.csv
```

## AI narrative

The AI narrative feature requires an `ANTHROPIC_API_KEY` environment variable. On Streamlit Cloud, add it under **App settings → Secrets**:

```toml
ANTHROPIC_API_KEY = "your-key-here"
```

If the key is absent, the narrative section is hidden. All cost numbers are deterministic and unaffected.

## Notes

- Python is the source of truth. Excel export is read-only.
- STEP upload requires cadquery, which is not available on Streamlit Cloud. The app falls back to manual input automatically.
- All cost numbers are deterministic. The AI layer generates explanation text only — it never produces or modifies cost figures.
