"""End-to-end proof that the bootstrap PROMPT is dataset-agnostic.

The helper tests (test_bootstrap_generality.py) prove individual helpers
work on many shapes. This test goes one level higher: it intercepts
`generate_baseline_from_task` mid-call, captures the actual prompt the
LLM would see, and asserts:

  - The "Available columns" block lists the dataset's REAL columns
    (not a hardcoded list).
  - The date-hints block uses the dataset's REAL detected formats.
  - The prompt contains NO hardcoded dataset-specific column names
    (no "price", "target", "Weekly_Sales", "fare" etc. except where
    they came from the user's actual CSV).

Run:
    python3 test_bootstrap_prompt_generality.py
"""
import os
import sys
import tempfile

WORKDIR = tempfile.mkdtemp(prefix="bootstrap_prompt_generality_")
os.chdir(WORKDIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import autoresearch  # noqa: E402


# === Test datasets — totally unrelated domains ===
DATASETS = [
    {
        "label": "retail (Walmart-like) DD-MM-YYYY",
        "filename": "walmart.csv",
        "task": "Predict the target variable based on the available features.",
        "csv": (
            "Store,Date,Weekly_Sales,Holiday_Flag,Temperature,Fuel_Price\n"
            "1,05-02-2010,1643690.9,0,42.31,2.572\n"
            "1,12-02-2010,1641957.44,1,38.51,2.548\n"
            "1,19-02-2010,1611968.17,0,39.93,2.514"
        ),
        "expected_columns": ["Store", "Date", "Weekly_Sales", "Holiday_Flag",
                             "Temperature", "Fuel_Price"],
        "expected_dates": [("Date", "%d-%m-%Y")],
    },
    {
        "label": "rideshare MM/DD/YYYY",
        "filename": "rides.csv",
        "task": "Predict the fare for a ride.",
        "csv": (
            "ride_id,pickup_dt,distance_mi,tip_pct,fare\n"
            "r001,03/15/2023,3.1,15.0,12.50\n"
            "r002,04/01/2023,1.7,10.0,8.75\n"
            "r003,12/31/2023,7.8,20.0,22.40"
        ),
        "expected_columns": ["ride_id", "pickup_dt", "distance_mi", "tip_pct", "fare"],
        "expected_dates": [("pickup_dt", "%m/%d/%Y")],
    },
    {
        "label": "iot sensor ISO 8601",
        "filename": "sensor.csv",
        "task": "Model temperature readings from a sensor.",
        "csv": (
            "sensor_id,timestamp,reading_c,battery_v\n"
            "s1,2024-01-15T08:30:00,72.5,3.7\n"
            "s1,2024-01-15T08:31:00,72.7,3.7\n"
            "s1,2024-01-15T08:32:00,72.9,3.6"
        ),
        "expected_columns": ["sensor_id", "timestamp", "reading_c", "battery_v"],
        "expected_dates": [("timestamp", "%Y-%m-%dT%H:%M:%S")],
    },
    {
        "label": "genomics no-date numeric only",
        "filename": "expression.csv",
        "task": "Predict disease label from gene expression.",
        "csv": (
            "gene_a,gene_b,gene_c,gene_d,disease_label\n"
            "0.51,1.27,0.92,0.13,0\n"
            "0.73,0.81,1.02,0.45,1\n"
            "0.34,2.10,0.88,0.27,0"
        ),
        "expected_columns": ["gene_a", "gene_b", "gene_c", "gene_d", "disease_label"],
        "expected_dates": [],
    },
]


# Capture the prompt the LLM would have seen
captured_prompts = []


def fake_query_llm(messages, stream=True, temp=0.3):
    user_text = ""
    for m in messages:
        if m.get("role") != "user":
            continue
        c = m.get("content")
        if isinstance(c, str):
            user_text = c
        elif isinstance(c, list):
            user_text = "\n".join(
                b.get("text", "") for b in c if isinstance(b, dict)
            )
    captured_prompts.append(user_text)
    # Return a stub that won't be evaluated; the test only inspects the prompt.
    return "```python\nprint('val_loss 0.5')\n```"


def _assert(cond, msg):
    if not cond:
        print(f"[FAIL] {msg}")
        sys.exit(1)


def main():
    print(f"[prompt-generality] cwd={WORKDIR}")
    print(f"[prompt-generality] running {len(DATASETS)} schemas…\n")

    autoresearch.query_llm = fake_query_llm

    # Anti-leak check: column names referenced in code-style (df['name'],
    # df["name"], columns=['name']) must only appear if 'name' is in the
    # actual dataset header. Generic English uses of the same word (e.g.
    # "the target variable" in the rule text) are fine.
    leak_names = ["price", "target", "label", "y", "value"]  # common hallucinations
    import re
    def code_refs_to(name):
        return [
            f"df['{name}']", f'df["{name}"]',
            f"columns=['{name}']", f'columns=["{name}"]',
            f"'{name}'", f'"{name}"',
        ]

    for ds in DATASETS:
        captured_prompts.clear()

        # Write CSV to a temp file and point DATASET_PATH at it
        csv_path = os.path.join(WORKDIR, ds["filename"])
        with open(csv_path, "w") as f:
            f.write(ds["csv"])
        os.environ["DATASET_PATH"] = csv_path

        autoresearch.generate_baseline_from_task(ds["task"])

        _assert(len(captured_prompts) == 1, f"{ds['label']}: expected 1 prompt, got {len(captured_prompts)}")
        prompt = captured_prompts[0]

        # 1. Available-columns block must contain THIS dataset's columns.
        cols_marker = "Available columns"
        _assert(cols_marker in prompt, f"{ds['label']}: missing 'Available columns' block")
        for col in ds["expected_columns"]:
            _assert(col in prompt, f"{ds['label']}: column '{col}' not surfaced in prompt")

        # 2. Date-hints block must contain THIS dataset's date formats.
        for col_name, fmt in ds["expected_dates"]:
            snippet = f"pd.to_datetime(df['{col_name}'], format='{fmt}')"
            _assert(snippet in prompt,
                    f"{ds['label']}: date hint snippet missing: {snippet}")

        # 3. No anti-leak name should appear in code-style references
        #    (df['name'], "columns=['name']", quoted as a column literal)
        #    unless it's actually one of this dataset's columns.
        actual_cols_lower = {c.lower() for c in ds["expected_columns"]}
        for leak in leak_names:
            if leak in actual_cols_lower:
                continue
            for ref in code_refs_to(leak):
                _assert(ref not in prompt,
                        f"{ds['label']}: code-style leak '{ref}' in prompt")

        # 4. The Walmart-specific column 'Weekly_Sales' must not appear in
        #    other datasets' prompts (regression check for hardcoded leaks).
        if "Weekly_Sales" not in ds["expected_columns"]:
            _assert("Weekly_Sales" not in prompt,
                    f"{ds['label']}: 'Weekly_Sales' leaked into a non-retail prompt")

        # Cleanup
        os.remove(csv_path)
        print(f"[PASS] {ds['label']}")
        print(f"       cols seen: {ds['expected_columns']}")
        print(f"       dates:     {ds['expected_dates']}")

    print("\n[ALL PASSED] bootstrap prompt is shaped entirely by the uploaded dataset.")


if __name__ == "__main__":
    main()
