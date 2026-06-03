"""Prove that bootstrap helpers are dataset-agnostic.

Exercises `_detect_date_columns` against preview shapes from completely
different domains (retail, NYC taxi, IoT sensor, German finance, etc.).
Asserts the detector handles each correctly without any per-dataset
heuristics.

Run from autoresearch_agent/:
    python3 test_bootstrap_generality.py

Exits 0 on success, non-zero on assertion failure.
"""
import os
import sys
import tempfile

# Match autoresearch's import-time cwd contract (it reads program.md on import? no,
# but signal handlers and module-level state should still work fine from any cwd).
os.chdir(tempfile.mkdtemp(prefix="bootstrap_generality_"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import autoresearch  # noqa: E402


def _assert_eq(actual, expected, label):
    if actual != expected:
        print(f"[FAIL] {label}")
        print(f"  expected: {expected}")
        print(f"  actual:   {actual}")
        sys.exit(1)
    print(f"[PASS] {label}: {actual}")


# Each case: (label, preview, expected_detected_columns)

CASES = [
    (
        "retail / Walmart-style DD-MM-YYYY (the failing case)",
        "Store,Date,Weekly_Sales,Holiday_Flag\n"
        "1,05-02-2010,1643690.9,0\n"
        "1,12-02-2010,1641957.44,1\n"
        "1,19-02-2010,1611968.17,0\n"
        "1,26-02-2010,1409727.59,0",
        [("Date", "%d-%m-%Y")],
    ),
    (
        "American MM/DD/YYYY (e.g. NYC taxi-style)",
        "pickup_time,fare,distance\n"
        "03/15/2023,12.50,3.1\n"
        "04/01/2023,8.75,1.7\n"
        "12/31/2023,22.40,7.8",
        [("pickup_time", "%m/%d/%Y")],
    ),
    (
        "ISO YYYY-MM-DD (most analytics warehouses)",
        "id,event_date,value\n"
        "1,2024-01-15,100\n"
        "2,2024-02-20,200\n"
        "3,2024-03-10,150",
        [("event_date", "%Y-%m-%d")],
    ),
    (
        "ISO 8601 datetime with seconds",
        "id,timestamp,reading\n"
        "1,2024-01-15T08:30:00,72.5\n"
        "2,2024-01-15T08:31:00,72.7\n"
        "3,2024-01-15T08:32:00,72.9",
        [("timestamp", "%Y-%m-%dT%H:%M:%S")],
    ),
    (
        "ISO 8601 with Z suffix (UTC)",
        "id,created_at\n"
        "1,2024-01-15T08:30:00Z\n"
        "2,2024-01-15T08:31:00Z",
        [("created_at", "%Y-%m-%dT%H:%M:%SZ")],
    ),
    (
        "German dotted DD.MM.YYYY",
        "kunde,datum,umsatz\n"
        "A,15.03.2024,250.00\n"
        "B,16.03.2024,180.50\n"
        "C,17.03.2024,310.75",
        [("datum", "%d.%m.%Y")],
    ),
    (
        "compact YYYYMMDD (no separator)",
        "id,batch_date,units\n"
        "1,20240115,500\n"
        "2,20240116,520\n"
        "3,20240117,495",
        [("batch_date", "%Y%m%d")],
    ),
    (
        "multiple date columns in one dataset",
        "order_id,order_date,ship_date,amount\n"
        "1001,2024-01-05,2024-01-08,150\n"
        "1002,2024-01-06,2024-01-09,200\n"
        "1003,2024-01-07,2024-01-10,175",
        [("order_date", "%Y-%m-%d"), ("ship_date", "%Y-%m-%d")],
    ),
    (
        "no date columns at all (pure numeric features)",
        "feature_a,feature_b,target\n"
        "0.5,1.2,0\n"
        "0.7,0.8,1\n"
        "0.3,2.1,0",
        [],
    ),
    (
        "single non-empty sample — refuses (ambiguity)",
        "col\n01-02-2010",
        [],
    ),
    (
        "string-typed columns that are NOT dates",
        "name,category,score\n"
        "Alice,A,90\n"
        "Bob,B,85\n"
        "Carol,A,92",
        [],
    ),
    (
        "DD-MM-YYYY with day>12 in only one row (still disambiguates)",
        "Store,Date,Sales\n"
        "1,01-02-2010,100\n"
        "1,15-02-2010,110",
        # day=15 in row 2 forces day-first; %m-%d-%Y fails on month=15
        [("Date", "%d-%m-%Y")],
    ),
    (
        "completely ambiguous DD-MM/MM-DD (all days ≤ 12) — picks first match",
        "Store,Date,Sales\n"
        "1,01-02-2010,100\n"
        "1,03-04-2010,110",
        # Both formats match. DATE_FORMATS_TO_TRY lists day-first first, so we get %d-%m-%Y.
        # This is a documented choice — day-first is the safer default.
        [("Date", "%d-%m-%Y")],
    ),
]


def main():
    print(f"[generality] cwd={os.getcwd()}")
    print(f"[generality] running {len(CASES)} date-detection cases…\n")
    for label, preview, expected in CASES:
        actual = autoresearch._detect_date_columns(preview)
        _assert_eq(actual, expected, label)

    print("\n[generality] running column-name extraction cases…\n")
    column_cases = [
        (
            "Walmart shape",
            "Store,Date,Weekly_Sales,Holiday_Flag,Temperature,Fuel_Price,CPI,Unemployment\n1,05-02-2010,1643690.9,0,42.31,2.572,211.0963582,8.106",
            ["Store", "Date", "Weekly_Sales", "Holiday_Flag",
             "Temperature", "Fuel_Price", "CPI", "Unemployment"],
        ),
        (
            "header with whitespace",
            "  id ,  name  , score \n1,Alice,90",
            ["id", "name", "score"],
        ),
        (
            "no preview (empty string)",
            "",
            [],
        ),
        (
            "header only, no data",
            "col_a,col_b,col_c",
            ["col_a", "col_b", "col_c"],
        ),
        (
            "trailing comma should not produce empty column",
            "a,b,c,\n1,2,3,",
            ["a", "b", "c"],
        ),
    ]
    for label, preview, expected in column_cases:
        actual = autoresearch._extract_column_names(preview)
        _assert_eq(actual, expected, label)

    print("\n[ALL PASSED] bootstrap helpers are dataset-agnostic.")


if __name__ == "__main__":
    main()
