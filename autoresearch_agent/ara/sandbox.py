"""Sandboxed execution of candidate scripts.

What this module does
---------------------
Runs untrusted, LLM-generated Python in isolation and reports the result:
  - ``CandidateResult`` — the (loss, output, code) triple every evaluation yields.
  - ``run_cmd`` — run a shell command CPU-only, returning combined output.
  - ``run_in_sandbox`` — copy the run's files into a temp dir, execute the code as
    ``train.py``, and parse its ``val_loss``.
  - ``classify_candidate_failure`` — human-readable reason a candidate scored inf.

Why it exists
-------------
Candidate code must never touch the real working directory or the GPU. This
module is the one place that enforces the CPU-only, copy-into-tempdir execution
contract, so the rest of the agent can treat evaluation as a pure function.

How it fits the architecture
----------------------------
Depends on ``parsing`` (``extract_val_loss``). Used by ``evaluation`` (which wraps
``run_in_sandbox`` with variance reduction), ``bootstrap`` and ``dashboard``
(``run_cmd``), and the Phase-10 agents (failure classification).

Monkeypatch point
-----------------
``run_in_sandbox`` is replaced in tests via ``ara.sandbox.run_in_sandbox``;
callers reach it through ``sandbox.run_in_sandbox`` attribute access so the patch
is seen everywhere.
"""

import os
import shutil
import subprocess
from dataclasses import dataclass

from ara.parsing import extract_val_loss


@dataclass
class CandidateResult:
    """Outcome of evaluating one candidate script.

    ``loss`` is the parsed ``val_loss`` (``inf`` on crash/timeout/missing print),
    ``output`` the combined stdout+stderr, and ``code`` the script that produced
    it. Ranking across a cycle keys entirely off ``loss``.
    """
    loss: float
    output: str
    code: str


def run_cmd(cmd: str, timeout: int = 300) -> str:
    """Execute a shell command, returning combined stdout+stderr. CPU-only sandbox.

    Forces ``CUDA_VISIBLE_DEVICES=-1`` to protect the inference server's VRAM,
    and converts a timeout into a readable error string rather than raising.
    """
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = "-1"  # Protect LLM VRAM by forcing scripts to CPU
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, env=env, timeout=timeout
        )
        return result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return f"TimeoutError: Script execution exceeded {timeout} seconds!"


def run_in_sandbox(code: str, workdir: str) -> CandidateResult:
    """Copy CWD files to ``workdir``, run ``code`` as ``train.py``, return a result.

    Every file in the current working directory is copied into the isolated
    ``workdir`` (so the candidate sees the dataset and the ``dashboard_export``
    helper), the code is written as ``train.py`` and run CPU-only with a 300s
    timeout. Returns a ``CandidateResult`` with the parsed ``val_loss``.
    """
    cwd = os.getcwd()
    for name in os.listdir(cwd):
        src = os.path.join(cwd, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(workdir, name))

    with open(os.path.join(workdir, "train.py"), "w") as f:
        f.write(code)

    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = "-1"
    try:
        proc = subprocess.run(
            ["python", "train.py"],
            capture_output=True,
            text=True,
            env=env,
            timeout=300,
            cwd=workdir,
        )
        output = proc.stdout + proc.stderr
    except subprocess.TimeoutExpired:
        output = "TimeoutError: Script execution exceeded 300 seconds!"

    return CandidateResult(loss=extract_val_loss(output), output=output, code=code)


def classify_candidate_failure(output: str) -> str:
    """Return a short human label for why a candidate produced ``val_loss=inf``.

    Purely diagnostic logging — the loop still keys off ``result.loss == inf``.
    Three reasons cover the common cases: ``timeout`` (killed at 300s),
    ``crashed: <last traceback line>`` (Python exception), and
    ``no val_loss line`` (ran cleanly but forgot the final print).
    """
    if "TimeoutError: Script execution exceeded" in output:
        return "timeout (>300s)"
    if "Traceback (most recent call last)" in output:
        # The last non-empty line of a traceback is the exception summary,
        # e.g. `KeyError: "['target'] not found in axis"`.
        for line in reversed(output.strip().splitlines()):
            line = line.strip()
            if line and not line.startswith(("File ", "  ", '"')):
                return f"crashed: {line[:200]}"
        return "crashed (no exception summary parsed)"
    return "no val_loss line printed"
