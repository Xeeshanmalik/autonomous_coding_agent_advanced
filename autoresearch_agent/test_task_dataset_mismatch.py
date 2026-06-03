"""Verify task/dataset mismatch detection works across realistic templates.

Specifically: a generic real-estate-style program.md uploaded with a
crude-oil dataset (the user-reported scenario). The detector should flag
the real-estate column names as missing from the dataset, while NOT
false-positiving on library / metric / framework symbols that legitimately
appear in backticks in task descriptions.

Run:
    python3 test_task_dataset_mismatch.py
"""
import os
import sys
import tempfile

os.chdir(tempfile.mkdtemp(prefix="mismatch_test_"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import autoresearch  # noqa: E402


def _assert(cond, msg):
    if not cond:
        print(f"[FAIL] {msg}")
        sys.exit(1)


CASES = [
    {
        "label": "user-reported: real-estate task + crude-oil dataset",
        "task": (
            "# AutoResearch Task\n"
            "## Objective\nDevelop a regression model.\n"
            "## Dataset\n- Features: `size`, `location`, `num_rooms`, `age`, `neighborhood`\n"
            "- Target Variable: `price`\n"
            "## Constraints\n- Libraries: Only use `sklearn` and `pandas`.\n"
            "- Code: PEP 8 compliant.\n"
        ),
        "actual_columns": ["Date", "Open", "High", "Low", "Close", "Volume"],
        "expected_mismatch": ["age", "location", "neighborhood", "num_rooms", "price", "size"],
    },
    {
        "label": "task matches dataset (no mismatch)",
        "task": (
            "Predict `Weekly_Sales` from `Store`, `Date`, `Holiday_Flag`, `Temperature`, "
            "`Fuel_Price`, `CPI`, `Unemployment` using `sklearn`.\n"
        ),
        "actual_columns": ["Store", "Date", "Weekly_Sales", "Holiday_Flag",
                           "Temperature", "Fuel_Price", "CPI", "Unemployment"],
        "expected_mismatch": [],
    },
    {
        "label": "case-insensitive match: task `Price`, column `price`",
        "task": "Predict `Price` from the other columns.",
        "actual_columns": ["date", "open", "price", "volume"],
        "expected_mismatch": [],
    },
    {
        "label": "library / metric symbols filtered (no false positives)",
        "task": (
            "Use `sklearn`'s `LinearRegression`. Optimise `MSE`. Read CSV with `pandas`.\n"
            "Target column: `Close`.\n"
        ),
        "actual_columns": ["Date", "Open", "High", "Low", "Close", "Volume"],
        "expected_mismatch": [],
    },
    {
        "label": "task with no backticked names at all",
        "task": "Predict the closing price from the other available features.",
        "actual_columns": ["Date", "Open", "Close"],
        "expected_mismatch": [],
    },
    {
        "label": "partial mismatch: target named in task but extras missing",
        "task": (
            "Target: `Close`. Engineered features include `volatility_30d` and "
            "`moving_avg_7d`.\n"
        ),
        "actual_columns": ["Date", "Open", "High", "Low", "Close", "Volume"],
        # task references engineered features that don't yet exist in raw data
        "expected_mismatch": ["moving_avg_7d", "volatility_30d"],
    },
]


def main():
    print(f"[mismatch] running {len(CASES)} cases…\n")
    for c in CASES:
        actual = autoresearch._detect_task_column_mismatch(c["task"], c["actual_columns"])
        _assert(
            actual == c["expected_mismatch"],
            f"{c['label']}: expected {c['expected_mismatch']}, got {actual}",
        )
        print(f"[PASS] {c['label']}: {actual}")

    print("\n[ALL PASSED] task/dataset mismatch detection works as designed.")


if __name__ == "__main__":
    main()
