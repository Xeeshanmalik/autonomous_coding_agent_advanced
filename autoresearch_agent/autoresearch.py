import asyncio
import datetime
import math
import os
import random
import re
import signal
import shutil
import subprocess
import tempfile
import requests
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace

# ---------------------------------------------------------------------------
# Graceful SIGTERM handling (Phase 9) — set by server /cancel endpoint
# ---------------------------------------------------------------------------

_sigterm_received = False


def _handle_sigterm(signum, frame):
    global _sigterm_received
    print("[!] SIGTERM received — will exit after the current cycle completes.")
    _sigterm_received = True


signal.signal(signal.SIGTERM, _handle_sigterm)

# ---------------------------------------------------------------------------
# LLM Endpoint Configuration
# ---------------------------------------------------------------------------
USE_ANTHROPIC = os.environ.get("USE_ANTHROPIC") == "true"
USE_GEMINI = os.environ.get("USE_GEMINI") == "true"

if USE_ANTHROPIC:
    # Native /v1/messages endpoint — only backend that honours cache_control breakpoints (Phase 4)
    LLM_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1") + "/messages"
    MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    ANTHROPIC_VERSION = os.getenv("ANTHROPIC_VERSION", "2023-06-01")
    ANTHROPIC_MAX_TOKENS = int(os.getenv("ANTHROPIC_MAX_TOKENS", 4096))
elif USE_GEMINI:
    LLM_URL = "https://generativelanguage.googleapis.com/v1beta/openai/v1/chat/completions"
    MODEL = "models/gemini-2.0-flash"
    API_KEY = os.environ.get("GEMINI_API_KEY", "")
else:
    LLM_URL = os.getenv("LLM_BASE_URL", "http://local-qwen-backend:8080/v1") + "/chat/completions"
    MODEL = os.getenv("LLM_MODEL", "deepSeek-R1-Distill-Qwen-32B")
    API_KEY = "dummy"

CANDIDATE_POOL_SIZE = int(os.environ.get("CANDIDATE_POOL_SIZE", 3))
POPULATION_SIZE = int(os.environ.get("POPULATION_SIZE", 3))


# ---------------------------------------------------------------------------
# System Prompt (shared between outer research loop and self-healer)
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are an elite autonomous research engineer. Output ONLY raw Python code inside ```python blocks. Do NOT output explanations or conversational text.

# YOUR ONLY JOB
Read the provided baseline script carefully. Understand what it is trying to do, then make it measurably better — lower val_loss. The task could be anything: data synthesis, regression, classification, optimisation, simulation, compression, etc. Your improvements must match the intent of the baseline.

# ABSOLUTE RULES

## Output
- Script MUST end with: `print(f'val_loss {score}')` where score is a float.
- The engine MINIMISES val_loss. Configure every metric so LOWER IS BETTER.
- Never remove or rename the val_loss print — the loop depends on it.

## Task Awareness (read baseline before writing)
- Understand what the baseline does BEFORE choosing an algorithm.
- If it generates synthetic data → improve the generation / distribution matching. Do NOT introduce supervised classifiers.
- If it trains a regressor → improve the regression model. Do NOT switch to a classifier.
- If it trains a classifier → improve classification. Do NOT switch to a regressor.
- When in doubt: keep the same algorithmic family as the baseline. Improve parameters, preprocessing, or training strategy only.

## Environment
- CPU-only sandbox. No GPU. Set `n_jobs=1` everywhere. Never use `-1`.
- Read data: `os.environ.get('DATASET_PATH', 'dataset.csv')`. No hardcoded paths.
- Only use: Python 3.9 stdlib, pandas, numpy, scipy, sklearn. Import everything explicitly.
- Do NOT use ctgan, copulas, torch, tensorflow, or any lib that requires installation.

## Code Quality
- Do not rewrite from scratch. Make surgical, mathematical improvements to the baseline.
- Never hallucinate function names. Verify every import exists in the library.
- If ERROR FEEDBACK is given: fix only that specific bug. Return the complete corrected script.

## Dashboard Export (do this IN ADDITION to val_loss, never instead of it)
- A helper module `dashboard_export` is ALREADY present in the working directory. After
  computing val_loss, export the results dashboard in ONE line — do NOT inline json.dump or
  build the dict yourself:
      import dashboard_export
      dashboard_export.dump(target_name=<target column name>, target=<validation actuals>,
                            y_true=<validation actuals>, y_pred=<validation predictions>, mse=<val MSE>)
- `target`, `y_true`, and `y_pred` must all cover ONLY the validation split (the held-out
  rows, same length and order) so the Target and Actual-vs-Predicted charts line up and never
  show rows the model was trained on. Do NOT pass the full target column. `mse` is the val MSE.
- Pass numpy arrays / pandas Series / lists directly; the helper handles JSON conversion,
  subsampling, and its own errors. The call must never affect val_loss.
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class CandidateResult:
    loss: float
    output: str
    code: str


def run_cmd(cmd, timeout=300):
    """Execute a shell command, returning combined stdout+stderr. CPU-only sandbox."""
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = "-1"  # Protect LLM VRAM by forcing scripts to CPU
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, env=env, timeout=timeout
        )
        return result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return f"TimeoutError: Script execution exceeded {timeout} seconds!"


def extract_val_loss(output):
    """Parse val_loss from script output. Returns inf if not found."""
    match = re.search(r"val_loss[\s:=]+([0-9.]+)", output, re.IGNORECASE)
    return float(match.group(1)) if match else float("inf")


# ---------------------------------------------------------------------------
# Dashboard export — stream the final champion's chart data to the frontend
# ---------------------------------------------------------------------------
# The frontend routes `__EVENT__{json}` lines through processLine and dispatches
# on `ev.type` (cycle_result, predictions). Emitting these events reuses that path.
EVENT_PREFIX = "__EVENT__"
DASHBOARD_MAX_POINTS = 500


def emit_event(payload):
    """Emit one machine-readable `__EVENT__` line for the frontend stream.
    Always a single compact line (the frontend splits the stream on \\n) and
    never raises — telemetry must not be able to break a run."""
    try:
        print(EVENT_PREFIX + json.dumps(payload, separators=(",", ":")))
    except Exception:  # noqa: BLE001
        pass


def _downsample(seq, limit=DASHBOARD_MAX_POINTS):
    """Uniformly subsample a list to at most `limit` points, preserving order
    and endpoints. Defensive: the champion is asked to cap its own series, but
    we never trust a freeform script to comply."""
    if not isinstance(seq, list) or len(seq) <= limit:
        return seq
    step = len(seq) / limit
    return [seq[min(len(seq) - 1, int(i * step))] for i in range(limit)]


def _ensure_dashboard_helper():
    """Copy `dashboard_export.py` into the current per-run working directory so
    champion scripts can `import dashboard_export`. run_in_sandbox copies every
    file in the cwd into each candidate sandbox, so staging it here makes it
    available to candidates and to the final champion run alike."""
    try:
        src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard_export.py")
        dst = os.path.join(os.getcwd(), "dashboard_export.py")
        if os.path.abspath(src) != os.path.abspath(dst):
            shutil.copy2(src, dst)
    except Exception as e:  # noqa: BLE001 — never block a run on the helper
        print(f"[*] Could not stage dashboard_export helper: {e}")


def emit_dashboard_data():
    """Run the final champion once (plain execution — NOT an LLM call) so it
    writes dashboard.json, then stream it to the frontend as a single
    `__EVENT__{"type":"predictions",...}` line. Best-effort: any failure is
    swallowed so a missing chart never affects the run's exit status or the
    [FINAL_CODE_*] block."""
    try:
        if not os.path.exists("train.py"):
            return
        run_cmd("python train.py")  # champion writes dashboard.json per SYSTEM_PROMPT contract
        if not os.path.exists("dashboard.json"):
            print("[*] Champion produced no dashboard.json — skipping chart export.")
            return
        with open("dashboard.json", "r") as f:
            data = json.load(f)
        for key in ("target", "y_true", "y_pred"):
            if isinstance(data.get(key), list):
                data[key] = _downsample(data[key])
        # The Actual-vs-Predicted chart pairs y_true[i] with y_pred[i], so the
        # two must stay the same length and index-aligned. The helper already
        # guarantees this, but a champion that writes dashboard.json by hand may
        # not — truncate to the common length as a last-ditch safety net so the
        # actual/predicted lines can't drift apart.
        yt, yp = data.get("y_true"), data.get("y_pred")
        if isinstance(yt, list) and isinstance(yp, list) and len(yt) != len(yp):
            n = min(len(yt), len(yp))
            data["y_true"], data["y_pred"] = yt[:n], yp[:n]
        emit_event({"type": "predictions", **data})
        print("[*] Dashboard chart data streamed to frontend.")
    except Exception as e:  # noqa: BLE001 — chart export must never break the run
        print(f"[*] Dashboard export skipped: {e}")


def extract_code_block(llm_text):
    """
    Pull the first ```python … ``` block out of LLM output.
    Falls back to everything after </think> for reasoning models.
    Returns the code string, or None if nothing usable is found.
    """
    # Strip <think>…</think> reasoning before searching
    text = re.sub(r"<think>.*?</think>", "", llm_text, flags=re.DOTALL)

    match = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()

    # Fallback: raw text after </think>
    if "</think>" in llm_text:
        tail = llm_text.split("</think>")[-1].strip()
        if tail:
            return tail

    return None


def _flatten_content(content):
    """
    Normalise a message's content to a plain string for OpenAI-compatible
    backends. Accepts:
      - str (returned as-is)
      - list of {"type": "text", "text": str, ...} blocks (joined with "\n\n";
        any cache_control marker is dropped because only Anthropic honours it).
    """
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
        elif isinstance(block, str):
            parts.append(block)
    return "\n\n".join(parts)


def _split_system(messages):
    """Return (system_content, non_system_messages) — used to lift the system
    role into Anthropic's top-level `system` field."""
    system = None
    rest = []
    for m in messages:
        if m.get("role") == "system" and system is None:
            system = m.get("content")
        else:
            rest.append(m)
    return system, rest


def _check_cancel(response=None, when="before LLM call"):
    if _sigterm_received:
        if response is not None:
            response.close()
            print("\033[0m\n[!] LLM stream aborted — cancellation requested.")
        raise KeyboardInterrupt(f"cancellation requested {when}")


def _post_with_retry(url, headers, payload, stream):
    """POST with exponential backoff on HTTP 429. Shared across backends.

    On any other non-2xx status, raise HTTPError with the response body
    included — `response.raise_for_status()` alone discards it, hiding
    diagnostic info like llama.cpp's "prompt token count exceeds context".
    """
    retry_count, max_retries, backoff = 0, 3, 10
    while True:
        response = requests.post(url, json=payload, headers=headers, stream=stream)
        if response.status_code == 429 and retry_count < max_retries:
            print(f"\n[-] Rate limit hit (429). Retrying in {backoff}s… ({retry_count + 1}/{max_retries})")
            time.sleep(backoff)
            retry_count += 1
            backoff *= 2
            continue
        if not response.ok:
            # response.text would consume the streaming body, but on a
            # non-2xx the server has already finished writing the error
            # payload — safe to read here.
            try:
                body = response.text[:1000]
            except Exception:
                body = "<could not read response body>"
            raise requests.HTTPError(
                f"HTTP {response.status_code} from {url}\nResponse body: {body}",
                response=response,
            )
        return response


def _query_openai_compat(messages, stream, temp, quiet=False):
    """OpenAI-compatible chat-completions backend (local llama.cpp, Gemini).

    When `quiet=True`, do not print streaming chunks to stdout — the caller
    will print the full response with a per-agent prefix once it returns.
    Used by parallel agents (CodeGen, SelfHealer) to avoid character-level
    interleave across concurrent threads writing to the same stdout.
    """
    headers = {"Content-Type": "application/json"}
    if USE_GEMINI:
        headers["Authorization"] = f"Bearer {API_KEY}"

    # Flatten any structured content blocks — cache_control is silently dropped
    # because llama.cpp / Gemini do not honour Anthropic's ephemeral-cache API.
    # The stable-prefix layout still helps llama.cpp's automatic KV-prefix cache.
    flat_messages = [
        {"role": m["role"], "content": _flatten_content(m["content"])}
        for m in messages
    ]

    payload = {
        "model": MODEL,
        "messages": flat_messages,
        "temperature": temp,
        "stream": stream,
    }

    response = _post_with_retry(LLM_URL, headers, payload, stream)
    full_response = ""
    if not quiet:
        print("\033[96m", end="")  # Cyan text for LLM output
    try:
        for line in response.iter_lines():
            _check_cancel(response, "mid-stream")
            if line:
                line_str = line.decode("utf-8")
                if line_str.startswith("data: "):
                    data_str = line_str[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        content = chunk.get("choices", [{}])[0].get("delta", {}).get("content")
                        if content is not None:
                            if not quiet:
                                print(content, end="", flush=True)
                            full_response += content
                    except json.JSONDecodeError:
                        pass
    finally:
        if not quiet:
            print("\033[0m\n")
    return full_response


def _query_anthropic(messages, stream, temp, quiet=False):
    """
    Native Anthropic /v1/messages backend with prompt caching (Phase 4).

    Cache breakpoints are declared by the caller as `cache_control: {"type": "ephemeral"}`
    on text blocks. Anthropic caches every prefix up to and including each marked
    block; cache TTL is 5 minutes. Cycle cadence keeps the system prompt + task
    description hot, cutting prompt tokens billed per cycle by ~75%.

    `quiet=True` suppresses streaming prints — same semantics as the OpenAI-compat
    path: caller buffers and prints with a per-agent prefix afterward.
    """
    headers = {
        "Content-Type": "application/json",
        "x-api-key": API_KEY,
        "anthropic-version": ANTHROPIC_VERSION,
    }

    system_content, user_messages = _split_system(messages)

    # Anthropic accepts either a string or a list of blocks for `system`.
    # Normalise to the block form when a cache_control marker is present so the
    # system prompt becomes a cache breakpoint.
    if system_content is None:
        system_field = None
    elif isinstance(system_content, str):
        system_field = system_content
    else:
        system_field = system_content  # already a list of blocks

    payload = {
        "model": MODEL,
        "max_tokens": ANTHROPIC_MAX_TOKENS,
        "messages": user_messages,
        "temperature": temp,
        "stream": stream,
    }
    if system_field is not None:
        payload["system"] = system_field

    response = _post_with_retry(LLM_URL, headers, payload, stream)
    full_response = ""
    cache_stats = {"cache_creation_input_tokens": None, "cache_read_input_tokens": None}
    if not quiet:
        print("\033[96m", end="")
    try:
        for line in response.iter_lines():
            _check_cancel(response, "mid-stream")
            if not line:
                continue
            line_str = line.decode("utf-8")
            if not line_str.startswith("data: "):
                continue
            data_str = line_str[6:]
            try:
                evt = json.loads(data_str)
            except json.JSONDecodeError:
                continue
            etype = evt.get("type")
            if etype == "content_block_delta":
                delta = evt.get("delta", {})
                if delta.get("type") == "text_delta":
                    text = delta.get("text", "")
                    if not quiet:
                        print(text, end="", flush=True)
                    full_response += text
            elif etype == "message_start":
                usage = evt.get("message", {}).get("usage", {})
                cache_stats["cache_creation_input_tokens"] = usage.get("cache_creation_input_tokens")
                cache_stats["cache_read_input_tokens"] = usage.get("cache_read_input_tokens")
            elif etype == "message_stop":
                break
    finally:
        if not quiet:
            print("\033[0m\n")
    if cache_stats["cache_read_input_tokens"] is not None and not quiet:
        print(f"[*] Anthropic cache: read={cache_stats['cache_read_input_tokens']} "
              f"created={cache_stats['cache_creation_input_tokens']} tokens")
    return full_response


def query_llm(messages, stream=True, temp=0.3, quiet=False):
    """
    Dispatch a chat request to the configured backend.

    Backends:
      - Anthropic (USE_ANTHROPIC=true) — native /v1/messages with cache_control breakpoints.
      - Gemini (USE_GEMINI=true) — OpenAI-compatible endpoint, no explicit cache.
      - Default — OpenAI-compatible local llama.cpp (automatic KV prefix cache).

    Message content may be a plain string OR a list of text blocks. The Anthropic
    backend preserves the block structure (including any `cache_control` markers);
    the other backends flatten the blocks into a single string.

    `quiet=True` suppresses the live streaming print so the caller can buffer
    and emit the response with its own prefix. Parallel agents (CodeGen,
    SelfHealer) use this to avoid character-level interleave on stdout when
    K threads stream concurrently.

    Cancellation: SIGTERM aborts before the request and again mid-stream by
    closing the socket so the inference server stops generation immediately (Phase 9).
    """
    _check_cancel(None, "before LLM call")
    if USE_ANTHROPIC:
        return _query_anthropic(messages, stream, temp, quiet=quiet)
    return _query_openai_compat(messages, stream, temp, quiet=quiet)

    # Persist raw LLM response for offline debugging
    with open("last_llm_response.log", "w") as f:
        f.write(full_response)

    return full_response


# ---------------------------------------------------------------------------
# Parallel Candidate Pool (Phase 1)
# ---------------------------------------------------------------------------

def run_in_sandbox(code, workdir):
    """Copy CWD files to workdir, run code as train.py, return CandidateResult."""
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


def classify_candidate_failure(output):
    """Return a short human label for why a candidate produced val_loss=inf.

    Used purely for diagnostic logging — the loop logic still keys off
    `result.loss == inf`. Three reasons cover the common cases:
      - "timeout" — sandbox killed the script at 300s.
      - "crashed: <last traceback line>" — Python exception.
      - "no val_loss line" — script ran cleanly but forgot the final print.
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


# ---------------------------------------------------------------------------
# Multi-Run Variance Reduction (Phase 8)
# ---------------------------------------------------------------------------

ROBUST_EVAL_K = int(os.environ.get("ROBUST_EVAL_K", 3))
ROBUST_EVAL_MARGIN = float(os.environ.get("ROBUST_EVAL_MARGIN", 0.05))


def robust_eval(code, workdir, threshold_loss, k=ROBUST_EVAL_K):
    """
    Eval `code` once. If the result is within ROBUST_EVAL_MARGIN of `threshold_loss`,
    re-eval k-1 more times in the same workdir and return the median-loss result.
    Otherwise return the single eval untouched — most candidates miss the threshold,
    so the overhead is only paid for near-frontier ones.

    `threshold_loss=inf` (e.g. first cycle, no champion yet) disables re-evaluation
    because inf * (1 + margin) == inf and the short-circuit always fires.
    """
    initial = run_in_sandbox(code, workdir)
    if not math.isfinite(threshold_loss) or initial.loss > threshold_loss * (1 + ROBUST_EVAL_MARGIN):
        return initial
    if k <= 1 or not math.isfinite(initial.loss):
        return initial

    extra = [run_in_sandbox(code, workdir) for _ in range(k - 1)]
    losses = sorted(r.loss for r in [initial] + extra)
    median_loss = losses[len(losses) // 2]
    print(f"[*] robust_eval: near-frontier candidate re-run {k}x, "
          f"losses={['%.6f' % l for l in losses]}, median={median_loss:.6f}")
    return replace(initial, loss=median_loss)


def run_candidate_pool(candidates, threshold_loss=float("inf")):
    """Run each candidate in an isolated sandbox in parallel, return the best.

    Each candidate is wrapped in robust_eval — near-frontier candidates
    (within ROBUST_EVAL_MARGIN of `threshold_loss`) are re-evaluated k times
    to suppress false breakthroughs from lucky random seeds (Phase 8).
    """
    worktrees = []
    results = []
    try:
        worktrees = [tempfile.mkdtemp(prefix=f"run_{i}_") for i in range(len(candidates))]
        with ThreadPoolExecutor(max_workers=len(candidates)) as executor:
            futures = {
                executor.submit(robust_eval, code, wdir, threshold_loss): i
                for i, (code, wdir) in enumerate(zip(candidates, worktrees))
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    result = future.result()
                    if math.isfinite(result.loss):
                        print(f"[*] Candidate {idx + 1}/{len(candidates)}: val_loss={result.loss:.6f}")
                    else:
                        reason = classify_candidate_failure(result.output)
                        print(f"[-] Candidate {idx + 1}/{len(candidates)}: val_loss=inf — {reason}")
                    results.append(result)
                except Exception as e:
                    print(f"[-] Candidate {idx + 1} raised an exception: {e}")
    finally:
        for wdir in worktrees:
            shutil.rmtree(wdir, ignore_errors=True)

    valid = [r for r in results if r.loss < float("inf")]
    if not valid:
        return None
    return min(valid, key=lambda r: r.loss)


# ---------------------------------------------------------------------------
# Population-Based Selection (Phase 2)
# ---------------------------------------------------------------------------

POPULATION_PATH = "population.json"


@dataclass
class PopulationMember:
    code: str
    loss: float
    cycle: int


class Population:
    def __init__(self, size: int = POPULATION_SIZE):
        self.size = size
        self.members: list[PopulationMember] = []

    def is_full(self) -> bool:
        return len(self.members) >= self.size

    def best(self) -> PopulationMember:
        return min(self.members, key=lambda m: m.loss)

    def worst(self) -> PopulationMember:
        return max(self.members, key=lambda m: m.loss)

    def to_json(self) -> list:
        return [{"code": m.code, "loss": m.loss, "cycle": m.cycle} for m in self.members]

    @classmethod
    def from_json(cls, data: list, size: int = POPULATION_SIZE) -> "Population":
        pop = cls(size=size)
        pop.members = [
            PopulationMember(code=d["code"], loss=d["loss"], cycle=d["cycle"])
            for d in data
        ]
        return pop


SELECT_PARENT_BETA = 4.0


def select_parent(population: Population) -> PopulationMember:
    """Softmax-weighted selection: lower loss → higher probability of being chosen.

    Weights are exp(-beta * (l - min_loss) / spread). Normalising by the spread
    keeps the exponent bounded regardless of loss magnitude — without this,
    losses like 1500 vs 0.3 (a crashed baseline alongside good members) push
    `math.exp` past its overflow threshold (~709) and crash the loop.
    Non-finite losses get weight 0 so a crashed member is never selected.
    """
    if len(population.members) == 1:
        return population.members[0]
    losses = [m.loss for m in population.members]
    finite = [l for l in losses if math.isfinite(l)]
    if not finite:
        return random.choice(population.members)
    min_loss = min(finite)
    spread = max(finite) - min_loss
    T = spread if spread > 0 else 1.0
    weights = [
        math.exp(-SELECT_PARENT_BETA * (l - min_loss) / T) if math.isfinite(l) else 0.0
        for l in losses
    ]
    total = sum(weights)
    if total == 0:
        return random.choice(population.members)
    r = random.random() * total
    cumulative = 0.0
    for member, w in zip(population.members, weights):
        cumulative += w
        if r <= cumulative:
            return member
    return population.members[-1]


def update_population(population: Population, new_member: PopulationMember) -> bool:
    """Add new_member if population has room or new_member beats the worst member."""
    if not population.is_full():
        population.members.append(new_member)
        return True
    worst = population.worst()
    if new_member.loss < worst.loss:
        population.members.remove(worst)
        population.members.append(new_member)
        return True
    return False


def save_population(population: Population) -> None:
    with open(POPULATION_PATH, "w") as f:
        json.dump({"size": population.size, "members": population.to_json()}, f, indent=2)


def load_population() -> "Population | None":
    if not os.path.exists(POPULATION_PATH):
        return None
    try:
        with open(POPULATION_PATH) as f:
            data = json.load(f)
        pop = Population.from_json(data["members"], size=data.get("size", POPULATION_SIZE))
        print(f"[*] Population loaded: {len(pop.members)} member(s), "
              f"best_loss={pop.best().loss:.6f}.")
        return pop
    except Exception as e:
        print(f"[!] Failed to load population ({e}). Starting fresh.")
        return None


# ---------------------------------------------------------------------------
# Two-Stage Prompting — Stage A: Baseline Analysis (Phase 3)
# ---------------------------------------------------------------------------

ANALYSIS_SYSTEM_PROMPT = "You are an expert ML engineer performing code analysis. Output ONLY a numbered bullet list — no code, no prose, no preamble."


def analyze_baseline(baseline_code, program_instructions):
    """Stage A: identify the top 3 weaknesses in the baseline. Returns a bullet-point string.

    Messages are structured as cacheable prefix blocks (Phase 4): the system prompt and
    the task context are stable across the whole run, so cache_control marks them as
    ephemeral cache breakpoints. The candidate-code-to-analyze tail varies per cycle.
    """
    messages = [
        {"role": "system", "content": [
            {"type": "text", "text": ANALYSIS_SYSTEM_PROMPT,
             "cache_control": {"type": "ephemeral"}},
        ]},
        {"role": "user", "content": [
            {"type": "text", "text": f"Task context:\n{program_instructions}",
             "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": (
                f"\n\nBaseline script:\n```python\n{baseline_code}\n```\n\n"
                "In exactly 3 numbered bullet points, identify the top 3 specific mathematical "
                "or algorithmic weaknesses most likely to reduce val_loss if fixed. "
                "Be precise: name the exact technique, parameter, or formula that is suboptimal."
            )},
        ]},
    ]
    print("[*] Stage A: analyzing baseline for weaknesses…")
    return query_llm(messages).strip()


# ---------------------------------------------------------------------------
# Baseline Bootstrap — refuse to start at val_loss=inf
# ---------------------------------------------------------------------------
#
# When the user-supplied baseline does not print `val_loss <float>`, the
# evolutionary loop has no signal to optimise against and silently runs all
# cycles against +inf. Instead, force a choice up front:
#
#   BOOTSTRAP_MODE=auto    → ask the LLM to write a baseline from program.md
#                            and re-evaluate. If the LLM-written script also
#                            fails to print val_loss, refuse.
#   BOOTSTRAP_MODE=manual  → refuse with instructions so the user can fix
#                            their baseline.
#   (unset)                → same as manual: refuse with instructions.
#
# Surfaced through server.py's POST /run as the `bootstrapMode` form field.


BOOTSTRAP_REFUSE_MSG = (
    "[-] Baseline script did not output a 'val_loss' line.\n"
    "    The evolutionary loop cannot start from val_loss=inf.\n"
    "    Either:\n"
    "      • Fix your baseline to end with `print(f'val_loss {score}')` (manual mode), or\n"
    "      • Re-run with bootstrapMode='auto' and the LLM will write a baseline for you."
)


BOOTSTRAP_MAX_ATTEMPTS = int(os.environ.get("BOOTSTRAP_MAX_ATTEMPTS", 3))


DATE_FORMATS_TO_TRY = (
    # Day-first is tried first because pandas auto-inference picks month-first
    # by default and silently crashes on DD-MM-YYYY datasets. Listing day-first
    # variants ahead of month-first means an unambiguous DD-MM-YYYY column
    # (one with day>12) gets the right format.
    "%d-%m-%Y", "%m-%d-%Y", "%Y-%m-%d",
    "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d",
    "%d.%m.%Y", "%m.%d.%Y",          # dot separator — German/French CSVs
    "%Y%m%d",                          # compact, no separator
    "%d-%m-%y", "%m-%d-%y", "%y-%m-%d",
    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%SZ",  # ISO 8601 with µs / Z
)


def _infer_date_format(samples):
    """Return the first strftime format that parses ALL non-empty samples, or None.

    Requires at least two distinct non-empty samples so we don't false-positive
    on a single ambiguous date like "01-02-2010" (could be d-m-Y or m-d-Y).
    Formats are tried in `DATE_FORMATS_TO_TRY` order, so day-first is preferred
    over month-first — that's the failure mode pandas auto-inference hits on
    DD-MM-YYYY datasets.
    """
    non_empty = [s.strip() for s in samples if s and s.strip()]
    if len(set(non_empty)) < 2:
        return None
    for fmt in DATE_FORMATS_TO_TRY:
        try:
            for s in non_empty:
                datetime.datetime.strptime(s, fmt)
            return fmt
        except (ValueError, TypeError):
            continue
    return None


def _extract_column_names(preview_text):
    """Return the list of column names from the preview's header row.

    Surfaced separately from the preview itself because the LLM otherwise
    skims past the CSV header and hallucinates plausible-sounding column
    names (e.g. `df['price']` for a retail dataset whose actual target is
    `Weekly_Sales`). The explicit list makes ANY other name an obvious bug.
    """
    lines = preview_text.strip().splitlines()
    if not lines:
        return []
    return [c.strip() for c in lines[0].split(",") if c.strip()]


# Words that look like `identifiers` in a task description but are clearly
# library / metric / framework references, not column names. Used by
# _detect_task_column_mismatch to avoid false-positive "column not in dataset"
# warnings on backticked code symbols.
_TASK_NON_COLUMN_WORDS = frozenset({
    # Libraries / frameworks
    "sklearn", "pandas", "numpy", "scipy", "scikit", "torch", "tensorflow",
    "pd", "np", "csv",
    # Common sklearn classes / functions seen in task descriptions
    "LinearRegression", "RandomForestRegressor", "GridSearchCV",
    "StandardScaler", "OneHotEncoder", "train_test_split",
    "mean_squared_error", "r2_score",
    # Metrics
    "MSE", "RMSE", "MAE", "R2", "AUC", "F1",
    # Pipeline tokens
    "train", "val", "test", "DATASET_PATH", "val_loss", "fit", "predict",
    "transform", "score", "model", "pipeline",
    # Other
    "Python", "PEP",
})


def _detect_task_column_mismatch(program_instructions, actual_columns):
    """Return backticked identifiers in the task that are NOT in the dataset.

    Helps detect the case where program.md uses a stale or generic template
    (real-estate examples like `size` / `location` / `price`) while the
    uploaded CSV is something else (e.g. crude-oil prices). The mismatch
    lets us tell the LLM "ignore those names — the actual dataset is here".

    Identifier detection is intentionally crude: `[a-zA-Z_][a-zA-Z0-9_]*`
    inside backticks. Library names, metrics, and common sklearn symbols
    are filtered via `_TASK_NON_COLUMN_WORDS`. The result is a best-effort
    warning, not a hard error.
    """
    referenced = set(re.findall(r"`([a-zA-Z_][a-zA-Z0-9_]*)`", program_instructions))
    actual_lower = {c.lower() for c in actual_columns}
    suspicious = sorted(
        name for name in referenced
        if name not in _TASK_NON_COLUMN_WORDS
        and name.lower() not in actual_lower
    )
    return suspicious


def _detect_date_columns(preview_text):
    """Inspect a CSV preview string and return [(column_name, strftime_format), ...]
    for every column whose sample values match a known date format unambiguously.

    Lets the bootstrap prompt give the LLM an explicit `format='%d-%m-%Y'` instead
    of letting `pd.to_datetime` auto-infer (which silently picks month-first and
    crashes mid-column on day-first datasets).
    """
    lines = preview_text.strip().splitlines()
    if len(lines) < 2:
        return []
    headers = [h.strip() for h in lines[0].split(",")]
    data_rows = [row.split(",") for row in lines[1:]]
    detected = []
    for col_idx, col_name in enumerate(headers):
        samples = [
            r[col_idx].strip() if col_idx < len(r) else ""
            for r in data_rows
        ]
        fmt = _infer_date_format(samples)
        if fmt:
            detected.append((col_name, fmt))
    return detected


def _read_dataset_preview(max_rows=5):
    """Return the dataset header + first `max_rows` data rows as a plain string.

    Returned to the LLM so the bootstrap baseline uses real column names instead
    of guessing 'target'. Returns "" if the file is missing or unreadable —
    the LLM then has to do its best from program.md alone, which is the
    previous behaviour.
    """
    path = os.environ.get("DATASET_PATH", "dataset.csv")
    if not os.path.exists(path):
        return ""
    try:
        lines = []
        with open(path, "r", errors="replace") as f:
            for i, line in enumerate(f):
                if i > max_rows:
                    break
                lines.append(line.rstrip("\n"))
        return "\n".join(lines)
    except Exception as e:
        print(f"[!] Could not read dataset preview ({e}). Continuing without it.")
        return ""


def generate_baseline_from_task(program_instructions, error_hint=None):
    """Ask the LLM for a minimal runnable baseline derived from program.md
    plus a small preview of the dataset.

    When `error_hint` is supplied (e.g. the traceback from a previous failed
    attempt), it is included in the prompt so the LLM can fix the specific
    bug rather than guessing again from scratch.

    Returns the extracted code string, or None if the LLM call failed or did
    not produce a parseable ```python block.
    """
    dataset_preview = _read_dataset_preview()
    dataset_path = os.environ.get("DATASET_PATH", "dataset.csv")

    columns_block = ""
    date_hints_block = ""
    mismatch_block = ""
    if dataset_preview:
        columns = _extract_column_names(dataset_preview)
        if columns:
            columns_block = (
                "\n\nAvailable columns (use ONLY these exact names — any other name "
                "will KeyError):\n  " + ", ".join(columns)
            )
            # Detect when the task description references columns that are not
            # in the uploaded dataset — common when program.md is a stale
            # template and the user uploaded a different CSV.
            mismatch = _detect_task_column_mismatch(program_instructions, columns)
            if mismatch:
                print(f"[!] Task description references columns NOT in the uploaded "
                      f"dataset: {mismatch}.")
                print(f"    Actual dataset columns: {columns}")
                print(f"    Bootstrap will instruct the LLM to ignore the task's "
                      f"column names and use the dataset's actual ones.")
                mismatch_block = (
                    "\n\nIMPORTANT — task/dataset mismatch detected. "
                    f"The task description references column names that do NOT exist in "
                    f"the uploaded dataset: {', '.join(mismatch)}. "
                    "The task is a generic / stale template; the uploaded CSV is what "
                    "matters. IGNORE those names. Use ONLY the 'Available columns' "
                    "above. Pick the target column by best semantic match in the "
                    "actual list (e.g. anything that looks like a price/score/value), "
                    "or fall back to the last column."
                )
        detected_dates = _detect_date_columns(dataset_preview)
        if detected_dates:
            lines = [
                f"  - df['{name}']: use pd.to_datetime(df['{name}'], format='{fmt}')"
                for name, fmt in detected_dates
            ]
            date_hints_block = (
                "\n\nDate columns (use these exact formats — do NOT rely on auto-inference):\n"
                + "\n".join(lines)
            )

    dataset_block = (
        f"\n\nDataset preview ({dataset_path}):\n```\n{dataset_preview}\n```"
    ) if dataset_preview else ""

    error_block = (
        f"\n\nPrevious attempt failed with this traceback — fix the SPECIFIC bug "
        f"(do not repeat the same mistake):\n```\n{error_hint}\n```"
    ) if error_hint else ""

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            "Write a minimal, runnable Python baseline for the task below.\n"
            "Rules:\n"
            "- Must end with `print(f'val_loss {score}')` (finite float).\n"
            "- Also export the dashboard in one line: `import dashboard_export; dashboard_export.dump(target_name=..., target=..., y_true=..., y_pred=..., mse=...)` (helper already in the working dir). Pass VALIDATION-only rows to target/y_true/y_pred (the held-out split, NOT the full column or training rows) so both charts cover the same rows; mse is the val MSE.\n"
            "- Must run in <90 s. No GridSearchCV with big grids, no n_estimators>50, no nested CV.\n"
            "- Stdlib + pandas, numpy, scipy, sklearn only. Read data from `os.environ.get('DATASET_PATH', 'dataset.csv')`.\n"
            "- The 'Available columns' list below is AUTHORITATIVE. If the task description mentions a column name that is NOT in that list, IGNORE it — the task may be a generic/stale template. Use ONLY columns from the list. Pick target by best name match against the task; if no match, the last column in the list.\n"
            "- Don't `pd.get_dummies` on Date/ID columns — derive features (Day/Month/Year) or drop them.\n\n"
            f"Task:\n{program_instructions}"
            f"{columns_block}"
            f"{mismatch_block}"
            f"{dataset_block}"
            f"{date_hints_block}"
            f"{error_block}"
            "\n\nOutput ONLY the Python code inside a ```python block."
        )},
    ]
    print("[*] Bootstrap: asking LLM to write a baseline…"
          + (" (retry with error hint)" if error_hint else ""))
    try:
        response = query_llm(messages)
    except Exception as e:
        print(f"[-] LLM call failed during bootstrap: {e}")
        return None
    return extract_code_block(response)


def bootstrap_baseline_if_needed(best_loss, program_instructions):
    """Gate the loop: if val_loss is non-finite, branch on BOOTSTRAP_MODE.

    In `auto` mode, retries up to BOOTSTRAP_MAX_ATTEMPTS times, feeding the
    previous traceback back to the LLM each retry so it can fix specific
    bugs (wrong column name, missing import, etc.) instead of starting fresh.

    Returns (best_loss, baseline_code) on success. Raises SystemExit(2) when
    no valid baseline can be produced — that exit propagates through main()
    and ends the streamed /run cleanly with the user-facing message above.
    """
    if math.isfinite(best_loss):
        with open("train.py", "r") as f:
            return best_loss, f.read()

    mode = os.environ.get("BOOTSTRAP_MODE", "").strip().lower()
    if mode != "auto":
        # manual or unset — refuse without invoking the LLM
        print(BOOTSTRAP_REFUSE_MSG)
        raise SystemExit(2)

    error_hint = None
    last_output = ""
    for attempt in range(1, BOOTSTRAP_MAX_ATTEMPTS + 1):
        print(f"[*] Bootstrap attempt {attempt}/{BOOTSTRAP_MAX_ATTEMPTS}…")
        generated = generate_baseline_from_task(program_instructions, error_hint=error_hint)
        if not generated:
            error_hint = "Previous response did not contain a parseable ```python block."
            continue

        with open("train.py", "w") as f:
            f.write(generated)
        regen_output = run_cmd("python train.py")
        last_output = regen_output
        new_loss = extract_val_loss(regen_output)
        if math.isfinite(new_loss):
            print(f"[*] Bootstrap succeeded on attempt {attempt} — val_loss={new_loss:.6f}")
            return new_loss, generated

        # Capture tail of the output as the error hint for the next attempt.
        # Use 200 lines, not 80 — sklearn/pandas tracebacks include a deep
        # stack of internal frames plus deprecation noise, and the actual
        # exception summary can sit above an 80-line window.
        error_lines = regen_output.strip().splitlines()
        error_hint = "\n".join(error_lines[-200:]) if error_lines else "Script exited without producing val_loss."
        print(f"[-] Attempt {attempt} produced no finite val_loss; will retry with traceback.")

    print(f"[-] All {BOOTSTRAP_MAX_ATTEMPTS} bootstrap attempts failed.")
    print("    Last script output ↓")
    print(last_output[-3000:])
    print(BOOTSTRAP_REFUSE_MSG)
    raise SystemExit(2)


# ---------------------------------------------------------------------------
# Checkpointing (Phase 6)
# ---------------------------------------------------------------------------

CHECKPOINT_PATH = "checkpoint.json"


def save_checkpoint(iteration, best_loss, baseline_code, started_at,
                    experiment_log=None, history_prefix=""):
    """Persist loop state to checkpoint.json so a crashed run can resume."""
    data = {
        "iteration": iteration,
        "best_loss": best_loss if best_loss != float("inf") else None,
        "baseline_code": baseline_code,
        "started_at": started_at,
        "experiment_log": experiment_log or [],
        "history_prefix": history_prefix,
    }
    with open(CHECKPOINT_PATH, "w") as f:
        json.dump(data, f, indent=2)
    print(f"[*] Checkpoint saved (iteration {iteration}, best_loss={best_loss:.6f}).")


def load_checkpoint():
    """Return checkpoint dict if checkpoint.json exists and is valid, else None."""
    if not os.path.exists(CHECKPOINT_PATH):
        return None
    try:
        with open(CHECKPOINT_PATH) as f:
            data = json.load(f)
        loss = data["best_loss"] if data["best_loss"] is not None else float("inf")
        data.setdefault("experiment_log", [])
        data.setdefault("history_prefix", "")
        print(f"[*] Checkpoint found — resuming from iteration {data['iteration'] + 1}, best_loss={loss:.6f}.")
        return data
    except Exception as e:
        print(f"[!] Failed to load checkpoint ({e}). Starting fresh.")
        return None


# ---------------------------------------------------------------------------
# Experiment History (Phase 7)
# ---------------------------------------------------------------------------

HISTORY_COMPRESS_AFTER = 10


def compress_history(experiment_log):
    """LLM call to compress a long experiment log into a short summary paragraph."""
    entries = "\n".join(
        "- Cycle {cycle}: {status} | loss={loss} (delta={delta}) | targeted: {target}".format(
            cycle=e["cycle"],
            status=e["status"],
            loss=f"{e['loss']:.4f}" if e["loss"] is not None else "N/A",
            delta=f"{e['delta']:+.4f}" if e["delta"] is not None else "N/A",
            target=e["target"],
        )
        for e in experiment_log
    )
    messages = [
        {
            "role": "system",
            "content": (
                "You are a concise research summarizer. "
                "Output ONLY a 3–5 sentence paragraph — no lists, no headers."
            ),
        },
        {
            "role": "user",
            "content": (
                "Summarize the following ML optimization experiment history. "
                "Highlight which approaches worked, which failed, and what the "
                "current champion method uses. A future LLM will read this summary "
                "to avoid repeating failed approaches.\n\n"
                f"{entries}"
            ),
        },
    ]
    print("[*] Compressing experiment history…")
    return query_llm(messages).strip()


def format_history_hint(experiment_log, history_prefix=""):
    """Format experiment history into a concise prompt block."""
    if not experiment_log and not history_prefix:
        return ""
    lines = []
    if history_prefix:
        lines.append(f"Summary of earlier cycles:\n{history_prefix}")
    recent = experiment_log[-5:]
    if recent:
        lines.append("Recent attempts (do NOT re-propose these exact approaches):")
        for e in recent:
            if e["status"] == "breakthrough":
                icon = "[BREAKTHROUGH]"
            elif e["status"] == "failed":
                icon = "[FAILED]"
            else:
                icon = "[no improvement]"
            loss_str = f"{e['loss']:.4f}" if e["loss"] is not None else "N/A"
            delta_str = f"{e['delta']:+.4f}" if e["delta"] is not None else "N/A"
            lines.append(
                f"  - Cycle {e['cycle']}: {icon} loss={loss_str} (delta={delta_str}) | targeted: {e['target']}"
            )
    return "\n".join(lines)


def git_commit_champion(iteration, best_loss):
    """Commit the current train.py to the local git history after a breakthrough."""
    try:
        subprocess.run(["git", "add", "train.py"], capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", f"cycle {iteration}: loss {best_loss:.6f}"],
            capture_output=True,
            check=True,
        )
        print(f"[*] Champion committed to git (cycle {iteration}: loss {best_loss:.6f}).")
    except subprocess.CalledProcessError:
        pass  # git not configured in this workdir — non-fatal


# ---------------------------------------------------------------------------
# Self-Healing Inner Loop
# ---------------------------------------------------------------------------

def execute_and_heal(initial_code, max_retries=3):
    """
    Run `initial_code` as train.py and attempt to self-heal on failure.

    Algorithm
    ---------
    1. Write `code` to train.py and execute it via subprocess.
    2. If the process exits cleanly (returncode == 0) → return (stdout, code).
    3. If the process fails:
       a. Capture the full stderr traceback.
       b. Build a targeted repair prompt containing the broken code + traceback.
       c. Query the LLM for a corrected script.
       d. Replace `code` with the LLM's fix and go back to step 1.
    4. After `max_retries` failed healing attempts, log the failure and return None.

    Parameters
    ----------
    initial_code : str   – The Python source code to execute.
    max_retries  : int   – Maximum LLM-assisted fix attempts before giving up.

    Returns
    -------
    (stdout_output : str, final_code : str)  on success.
    None                                      if all healing attempts are exhausted.
    """
    code = initial_code
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = "-1"  # Keep training strictly on CPU

    for attempt in range(max_retries + 1):  # attempt 0 = first run, 1..max = heals

        # --- Write the current code to disk ---
        with open("train.py", "w") as f:
            f.write(code)

        label = "initial execution" if attempt == 0 else f"heal attempt {attempt}/{max_retries}"
        print(f"[*] Running train.py ({label})…")

        # --- Execute: capture stdout and stderr SEPARATELY for precise diagnosis ---
        try:
            proc = subprocess.run(
                ["python", "train.py"],
                capture_output=True,
                text=True,
                env=env,
                timeout=300,
            )
        except subprocess.TimeoutExpired:
            print("[-] Script timed out after 300 s.")
            if attempt == max_retries:
                print("[-] Self-healer exhausted all retries (timeout). Giving up.")
                return None
            # Feed timeout as error context so LLM can optimise runtime
            stderr_snapshot = "TimeoutError: Script exceeded 300-second execution limit. Optimise for speed."
        else:
            stdout_snapshot = proc.stdout
            stderr_snapshot = proc.stderr

            if proc.returncode == 0:
                
                print("[+] Script executed successfully.")
                return stdout_snapshot, code

            # Non-zero exit: print the FULL traceback to the operator log
            print(f"[-] Script exited with code {proc.returncode}.")
            if stderr_snapshot.strip():
                print("    STDERR ↓")
                print(stderr_snapshot.strip())

            # Cap stderr sent to the LLM repair prompt to the last 100 lines.
            # Long tracebacks from complex generated scripts can push the heal
            # prompt over the server's 4096-token context limit ("Error in
            # input stream"). The full output is already printed above for ops.
            stderr_lines = stderr_snapshot.strip().splitlines()
            if len(stderr_lines) > 100:
                stderr_snapshot = (
                    "[... truncated — showing last 100 lines ...]\n"
                    + "\n".join(stderr_lines[-100:])
                )

        # --- Healing exhausted? ---
        if attempt == max_retries:
            print(f"[-] Self-healer exhausted all {max_retries} repair attempts. Giving up on this code.")
            return None

        # --- Build a surgical repair prompt for the LLM ---
        print(f"[*] Querying LLM for a surgical fix (heal {attempt + 1}/{max_retries})…")

        repair_messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "The following Python script raised a runtime error. "
                    "Your ONLY task is to return the FULLY CORRECTED script inside a ```python block. "
                    "Do NOT explain anything. Do NOT change the algorithm logic — fix ONLY the bug.\n\n"
                    f"=== BROKEN CODE ===\n```python\n{code}\n```\n\n"
                    f"=== FULL ERROR TRACEBACK ===\n{stderr_snapshot}\n\n"
                    "Return the complete, corrected Python script now."
                ),
            },
        ]

        try:
            llm_response = query_llm(repair_messages)
        except Exception as e:
            print(f"[-] LLM query failed during healing: {e}")
            return None

        fixed_code = extract_code_block(llm_response)
        if not fixed_code:
            print("[-] LLM did not return a parseable code block. Retrying healing prompt…")
            # Keep `code` unchanged so we retry with the same broken version + same error
            continue

        print("[*] LLM returned a candidate fix. Applying and re-testing…")
        code = fixed_code  # Use the fixed code in the next loop iteration


# ---------------------------------------------------------------------------
# Phase 10 — Multi-Agent Harness
# ---------------------------------------------------------------------------
#
# Restructures the per-cycle work into specialised async agents coordinated
# by a Research Director:
#
#   Analyst        — analyse the parent, produce weakness bullets.
#   CodeGen × K    — produce K candidate scripts (parallel).
#   EvalWorker × K — sandbox-eval candidates (parallel).
#   SelfHealer     — repair candidates that crashed (parallel, opt-in).
#
# All LLM calls are blocking (uses `requests` + streaming). We bridge to
# asyncio with `asyncio.to_thread` so the K candidate calls overlap on the
# event loop while individual calls still block their worker thread. This
# is the dominant speedup at K=3: ~1× LLM wall-time per cycle instead of K×.
#
# Parallel agents call query_llm with `quiet=True` so the streaming prints
# don't interleave character-by-character across concurrent worker threads.
# Each parallel agent buffers its full LLM response and prints it once with
# a per-agent prefix after the call completes.


ENABLE_SELF_HEALER = os.environ.get("ENABLE_SELF_HEALER", "true").lower() == "true"


async def analyst_agent(parent_code, program_instructions):
    """Single Analyst: returns the weakness bullet report or raises."""
    return await asyncio.to_thread(analyze_baseline, parent_code, program_instructions)


def _emit_with_prefix(prefix, body):
    """Print `body` to stdout with `prefix` on every line, plus blank-line padding.

    Used by parallel agents to surface their LLM output without character-
    level interleave. The whole call runs in the asyncio event-loop thread
    (single-threaded), so concurrent agents emit their blocks one after the
    other, not mixed together.
    """
    print(f"\033[96m{prefix}\033[0m")
    for line in body.splitlines() or [""]:
        print(f"  {prefix}  {line}")
    print()


async def code_gen_agent(messages, temp, agent_id):
    """One CodeGen worker: returns extracted candidate code or None."""
    print(f"[*] CodeGen {agent_id} (temp={temp:.2f}): requesting…")
    try:
        response = await asyncio.to_thread(query_llm, messages, True, temp, True)
    except Exception as e:
        print(f"[-] CodeGen {agent_id} failed: {e}")
        return None
    _emit_with_prefix(f"[CodeGen {agent_id}]", response)
    code = extract_code_block(response)
    if not code:
        print(f"[-] CodeGen {agent_id}: no parseable code block.")
        return None
    print(f"[+] CodeGen {agent_id}: got candidate ({len(code)} chars)")
    return code


async def eval_worker(code, workdir, threshold_loss, agent_id):
    """One EvalWorker: sandbox-evaluates a candidate via robust_eval."""
    result = await asyncio.to_thread(robust_eval, code, workdir, threshold_loss)
    if math.isfinite(result.loss):
        print(f"[+] EvalWorker {agent_id}: val_loss={result.loss:.6f}")
    else:
        reason = classify_candidate_failure(result.output)
        print(f"[-] EvalWorker {agent_id}: val_loss=inf — {reason}")
    return result


async def self_healer_agent(code, error_output, agent_id):
    """SelfHealer: one repair attempt for a crashed candidate.

    Returns healed code or None. Mirrors the repair prompt that
    execute_and_heal uses but is invoked async and per-candidate so multiple
    failures can be repaired concurrently. Only fired when the failure
    output contains a traceback — a candidate that ran cleanly but didn't
    print val_loss is not repairable from the output alone.
    """
    error_lines = error_output.strip().splitlines()
    error_snippet = "\n".join(error_lines[-80:]) if error_lines else error_output
    repair_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            "The following Python script crashed. Return the corrected version "
            "inside a ```python block. Fix ONLY the specific bug — do not change "
            "the algorithm.\n\n"
            f"=== BROKEN CODE ===\n```python\n{code}\n```\n\n"
            f"=== TRACEBACK ===\n{error_snippet}\n\n"
            "Return the complete, corrected Python script now."
        )},
    ]
    print(f"[*] SelfHealer {agent_id}: requesting repair…")
    try:
        response = await asyncio.to_thread(query_llm, repair_messages, True, 0.2, True)
    except Exception as e:
        print(f"[-] SelfHealer {agent_id} failed: {e}")
        return None
    _emit_with_prefix(f"[SelfHealer {agent_id}]", response)
    healed = extract_code_block(response)
    if healed:
        print(f"[+] SelfHealer {agent_id}: got patched code")
    else:
        print(f"[-] SelfHealer {agent_id}: no parseable code block")
    return healed


def _build_research_messages(parent, weakness_report, experiment_log, history_prefix, program_instructions):
    """Build the cacheable-prefix research messages handed to every CodeGen."""
    history_hint = format_history_hint(experiment_log, history_prefix)
    variable_tail = (
        f"\n\nParent script to improve (loss={parent.loss:.6f}, cycle {parent.cycle}):\n"
        f"```python\n{parent.code}\n```\n\n"
    )
    if history_hint:
        variable_tail += f"{history_hint}\n\n"
    variable_tail += (
        f"Identified weaknesses:\n{weakness_report}\n\n"
        "Implement exactly ONE targeted fix addressing one of the weaknesses above. "
        "Output the complete corrected script in a ```python block."
    )
    return [
        {"role": "system", "content": [
            {"type": "text", "text": SYSTEM_PROMPT,
             "cache_control": {"type": "ephemeral"}},
        ]},
        {"role": "user", "content": [
            {"type": "text", "text": program_instructions,
             "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": variable_tail},
        ]},
    ]


def _record_failed_cycle(iteration, best_loss, baseline_code, started_at,
                         experiment_log, history_prefix, target):
    """Append a 'failed' experiment-log entry and persist the checkpoint."""
    experiment_log.append({
        "cycle": iteration, "loss": None, "delta": None,
        "status": "failed", "target": target,
    })
    save_checkpoint(iteration, best_loss, baseline_code, started_at,
                    experiment_log, history_prefix)


async def director_one_cycle(iteration, max_iterations, population, best_loss,
                              baseline_code, started_at, experiment_log,
                              history_prefix, program_instructions):
    """Run one full cycle: Analyst → CodeGens → EvalWorkers → SelfHealer.

    Returns the updated (best_loss, experiment_log, history_prefix). The
    population, train.py, population.json and checkpoint.json are mutated /
    written in-place.
    """
    print(f"\n{'='*50}")
    print(f"--- AutoResearch Cycle {iteration} ---")

    if iteration > 1 and os.environ.get("USE_GEMINI") == "true":
        print("[*] Rate-limit mitigation: sleeping 5 s before next cycle…")
        await asyncio.sleep(5)

    cycle_ratio = (iteration - 1) / max_iterations
    base_temp = 0.1 + 0.7 * 0.5 * (1 + math.cos(math.pi * cycle_ratio))
    candidate_temps = [
        max(0.05, base_temp * 0.5),
        base_temp,
        min(1.0, base_temp * 1.5),
    ]

    parent = select_parent(population)
    print(f"[*] Director: parent (loss={parent.loss:.6f}, cycle {parent.cycle}); "
          f"base_temp={base_temp:.2f}")

    try:
        weakness_report = await analyst_agent(parent.code, program_instructions)
    except Exception as e:
        print(f"[-] Analyst failed ({e}). Skipping cycle.")
        _record_failed_cycle(iteration, best_loss, baseline_code, started_at,
                             experiment_log, history_prefix, "analysis_failed")
        return best_loss, experiment_log, history_prefix

    research_messages = _build_research_messages(
        parent, weakness_report, experiment_log, history_prefix, program_instructions
    )

    print(f"[*] Director: dispatching {CANDIDATE_POOL_SIZE} CodeGen agents in parallel…")
    codegen_tasks = [
        code_gen_agent(research_messages, candidate_temps[i % len(candidate_temps)], i + 1)
        for i in range(CANDIDATE_POOL_SIZE)
    ]
    candidates_raw = await asyncio.gather(*codegen_tasks)
    candidates = [c for c in candidates_raw if c]

    if not candidates:
        print("[-] No valid candidates generated. Skipping cycle.")
        _record_failed_cycle(iteration, best_loss, baseline_code, started_at,
                             experiment_log, history_prefix,
                             weakness_report.split("\n")[0][:100])
        return best_loss, experiment_log, history_prefix

    worktrees = [tempfile.mkdtemp(prefix=f"eval_{i}_") for i in range(len(candidates))]
    try:
        print(f"[*] Director: dispatching {len(candidates)} EvalWorkers in parallel…")
        eval_tasks = [
            eval_worker(code, wdir, best_loss, i + 1)
            for i, (code, wdir) in enumerate(zip(candidates, worktrees))
        ]
        results = await asyncio.gather(*eval_tasks)
    finally:
        for w in worktrees:
            shutil.rmtree(w, ignore_errors=True)

    healed_results = []
    if ENABLE_SELF_HEALER:
        crashed_indices = [
            i for i, r in enumerate(results)
            if not math.isfinite(r.loss) and "Traceback (most recent call last)" in r.output
        ]
        if crashed_indices:
            print(f"[*] Director: {len(crashed_indices)} candidate(s) crashed — "
                  f"launching SelfHealer(s) in parallel…")
            heal_tasks = [
                self_healer_agent(results[i].code, results[i].output, i + 1)
                for i in crashed_indices
            ]
            healed_codes = await asyncio.gather(*heal_tasks)
            heal_pairs = [
                (code, orig_idx) for code, orig_idx in zip(healed_codes, crashed_indices)
                if code
            ]
            if heal_pairs:
                heal_worktrees = [
                    tempfile.mkdtemp(prefix=f"heal_{orig_idx}_")
                    for _, orig_idx in heal_pairs
                ]
                try:
                    heal_eval_tasks = [
                        eval_worker(code, wdir, best_loss, f"heal{orig_idx + 1}")
                        for (code, orig_idx), wdir in zip(heal_pairs, heal_worktrees)
                    ]
                    healed_results = await asyncio.gather(*heal_eval_tasks)
                finally:
                    for w in heal_worktrees:
                        shutil.rmtree(w, ignore_errors=True)

    all_results = list(results) + list(healed_results)
    valid = [r for r in all_results if math.isfinite(r.loss)]

    if not valid:
        print("[-] All candidates failed evaluation. Keeping current champion.")
        champion = population.best()
        with open("train.py", "w") as f:
            f.write(champion.code)
        _record_failed_cycle(iteration, best_loss, baseline_code, started_at,
                             experiment_log, history_prefix,
                             weakness_report.split("\n")[0][:100])
        return best_loss, experiment_log, history_prefix

    best_result = min(valid, key=lambda r: r.loss)
    new_loss = best_result.loss
    print(f"[*] Director: best candidate val_loss={new_loss:.6f}")

    prev_loss = best_loss
    new_member = PopulationMember(code=best_result.code, loss=new_loss, cycle=iteration)
    admitted = update_population(population, new_member)
    champion = population.best()

    if champion.loss < best_loss:
        print(f"[+] BREAKTHROUGH! Loss improved: {best_loss:.6f} → {champion.loss:.6f}")
        best_loss = champion.loss
        with open("train.py", "w") as f:
            f.write(champion.code)
        git_commit_champion(iteration, best_loss)
        cycle_status = "breakthrough"
    elif admitted:
        print(f"[*] Population updated (new loss={new_loss:.6f}). "
              f"Champion at {best_loss:.6f}.")
        with open("train.py", "w") as f:
            f.write(champion.code)
        cycle_status = "no_improvement"
    else:
        print(f"[-] Candidate (loss={new_loss:.6f}) did not improve population. "
              f"Champion at {best_loss:.6f}.")
        with open("train.py", "w") as f:
            f.write(champion.code)
        cycle_status = "no_improvement"

    pop_summary = ", ".join(f"{m.loss:.4f}" for m in
                            sorted(population.members, key=lambda m: m.loss))
    print(f"[*] Population losses: [{pop_summary}]")
    save_population(population)

    experiment_log.append({
        "cycle": iteration,
        "loss": new_loss,
        "delta": round(new_loss - prev_loss, 6),
        "status": cycle_status,
        "target": weakness_report.split("\n")[0][:100],
    })

    if len(experiment_log) % HISTORY_COMPRESS_AFTER == 0:
        try:
            history_prefix = compress_history(experiment_log[:-5])
        except Exception as e:
            print(f"[!] History compression failed ({e}) — keeping raw log.")

    save_checkpoint(iteration, best_loss, baseline_code, started_at,
                    experiment_log, history_prefix)
    return best_loss, experiment_log, history_prefix


async def research_director(iteration, max_iterations, population, best_loss,
                             baseline_code, started_at, experiment_log,
                             history_prefix, program_instructions):
    """Director outer loop. Iterates director_one_cycle until done or SIGTERM."""
    while iteration <= max_iterations:
        if _sigterm_received:
            print("[!] Shutdown requested — exiting director loop.")
            break
        best_loss, experiment_log, history_prefix = await director_one_cycle(
            iteration, max_iterations, population, best_loss, baseline_code,
            started_at, experiment_log, history_prefix, program_instructions
        )
        # Per-cycle champion loss for the frontend loss-over-cycles chart.
        # Single emission point covers every cycle path inside director_one_cycle.
        emit_event({"type": "cycle_result", "cycle": iteration, "loss": best_loss})
        iteration += 1
    print(f"\n{'='*50}")
    print(f"[*] AutoResearch Loop Completed! Final val_loss: {best_loss}")


# ---------------------------------------------------------------------------
# Outer Evolutionary Research Loop
# ---------------------------------------------------------------------------

def main():
    """Synchronous setup + bootstrap. Hands off to the async research_director
    for the per-cycle work, which fans out CodeGen / EvalWorker / SelfHealer
    agents in parallel (Phase 10).
    """
    print("[*] Booting AutoResearch Agent (Phase 10: Multi-Agent Harness)…")

    # Stage the dashboard export helper so champions can import it (here and in
    # every candidate sandbox) instead of inlining json-dump boilerplate.
    _ensure_dashboard_helper()

    max_iterations = int(os.environ.get("MAX_ITERATIONS", 5))

    # program_instructions is needed by both branches (bootstrap on fresh
    # runs, weakness analysis in the loop) so read it once up-front.
    with open("program.md", "r") as f:
        program_instructions = f.read()

    # --- Resume from checkpoint / population, or run fresh baseline ---
    checkpoint = load_checkpoint()
    population = load_population()
    iteration = 1
    if checkpoint:
        iteration = checkpoint["iteration"] + 1
        baseline_code = checkpoint["baseline_code"]
        started_at = checkpoint["started_at"]
        experiment_log = checkpoint["experiment_log"]
        history_prefix = checkpoint["history_prefix"]
        if population:
            best_loss = population.best().loss
        else:
            with open("train.py", "r") as f:
                champ_code = f.read()
            print("[*] population.json missing on resume — re-evaluating train.py to seed best_loss.")
            best_loss = extract_val_loss(run_cmd("python train.py"))
            population = Population()
            population.members.append(PopulationMember(code=champ_code, loss=best_loss, cycle=0))
        print(f"[*] Resumed: cycle {iteration}, pop={len(population.members)}, "
              f"best_loss={best_loss:.6f}, {len(experiment_log)} history entries")
    else:
        iteration = 1
        print("[*] Running initial baseline evaluation…")
        baseline_output = run_cmd("python train.py")
        initial_loss = extract_val_loss(baseline_output)
        best_loss, baseline_code = bootstrap_baseline_if_needed(
            initial_loss, program_instructions
        )
        print(f"[*] Baseline val_loss established: {best_loss}")
        started_at = datetime.datetime.utcnow().isoformat() + "Z"
        experiment_log = []
        history_prefix = ""
        population = Population()
        population.members.append(PopulationMember(code=baseline_code, loss=best_loss, cycle=0))

    asyncio.run(research_director(
        iteration, max_iterations, population, best_loss, baseline_code,
        started_at, experiment_log, history_prefix, program_instructions,
    ))

    # Evolution finished normally — run the final champion once more so it emits
    # dashboard.json, and stream that chart data to the frontend. Skipped on
    # cancellation (KeyboardInterrupt propagates past this to __main__).
    emit_dashboard_data()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        # Raised by query_llm when SIGTERM arrives. Exit 0 so the parent
        # /run stream sees a normal EOF and still emits [FINAL_CODE_*].
        print("\n[!] Cancellation received — exiting cleanly.")
