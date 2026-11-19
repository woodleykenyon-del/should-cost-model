# Parametric Should-Cost Model V2

Defensible price estimation for machined aerospace parts. Part of a five-tool sourcing operations portfolio.

**Stack:** Python + Streamlit + Excel (openpyxl) + cadquery (optional, local only)

---

## What it does

Given material, part weight, complexity tier, tolerance tier, volume, and region — the engine produces a three-scenario price band (Low / Mid / High) with sensitivity analysis, confidence scoring, and a sourcing summary derived from the computed results.

The web demo uses manual weight entry and a table-driven buy-to-fly ratio. The repository also includes a local STEP geometry parser.

## Live demo

[Launch on Streamlit Cloud →](https://kenyon-should-cost.streamlit.app/)

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
│   └── explain.py            # Deterministic sourcing summary
├── geometry/
│   └── step_reader.py        # STEP parser + BTF derivation (cadquery)
├── exporters/
│   └── excel_export.py       # 5-tab Excel workbook export
└── data/
    ├── assumptions_default.json
    ├── materials.csv
    └── machine_rates.csv
```

## Sourcing summary

The Streamlit results and the Notes sheet in the export use the same explanation of the price band, sensitivity, and input confidence. The summary runs locally with the estimator and needs no API key.

## Notes

- Python is the source of truth. Excel export is read-only.
- Use fictional part and program details in the public demo.
