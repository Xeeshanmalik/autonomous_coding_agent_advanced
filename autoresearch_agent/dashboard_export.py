"""Champion-side dashboard export helper.

Staged into each per-run working directory (and copied into every candidate
sandbox) so a champion `train.py` can export its results-dashboard data in ONE
line instead of inlining json.dump boilerplate that would otherwise be echoed
to the application console:

    import dashboard_export
    dashboard_export.dump(
        target_name="price",   # name of the target column
        target=y,              # raw target column (numpy / pandas / list)
        y_true=y_val,          # validation actuals
        y_pred=y_pred,         # validation predictions (aligned to y_true)
        mse=score,             # validation mean squared error
    )

Writes ``dashboard.json`` next to the script. The backend reads it after
evolution and streams it to the frontend. This helper NEVER raises — a
dashboard failure must never affect a champion's ``val_loss``.
"""

import json

MAX_POINTS = 500


def _coerce(seq):
    """Turn a numpy array / pandas Series / list-like into a JSON-safe list of
    Python floats, uniformly subsampled to at most ``MAX_POINTS`` points."""
    if seq is None:
        return None
    try:
        seq = seq.tolist()  # numpy ndarray / pandas Series
    except AttributeError:
        seq = list(seq)
    if len(seq) > MAX_POINTS:
        step = len(seq) / MAX_POINTS
        seq = [seq[min(len(seq) - 1, int(i * step))] for i in range(MAX_POINTS)]
    out = []
    for v in seq:
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            out.append(None)
    return out


def dump(target_name=None, target=None, y_true=None, y_pred=None, mse=None,
         path="dashboard.json"):
    """Write the dashboard payload to ``path``. Swallows every error so it can
    never break the calling script."""
    try:
        data = {
            "target_name": str(target_name) if target_name is not None else None,
            "target": _coerce(target),
            "y_true": _coerce(y_true),
            "y_pred": _coerce(y_pred),
            "mse": float(mse) if mse is not None else None,
        }
        with open(path, "w") as f:
            json.dump(data, f)
    except Exception:  # noqa: BLE001 — export must never affect val_loss
        pass
