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
    LLM_URL = os.getenv("LLM_BASE_URL", "http://local-deepseek-backend:8080/v1") + "/chat/completions"
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
    """POST with exponential backoff on HTTP 429. Shared across backends."""
    retry_count, max_retries, backoff = 0, 3, 10
    while True:
        response = requests.post(url, json=payload, headers=headers, stream=stream)
        if response.status_code == 429 and retry_count < max_retries:
            print(f"\n[-] Rate limit hit (429). Retrying in {backoff}s… ({retry_count + 1}/{max_retries})")
            time.sleep(backoff)
            retry_count += 1
            backoff *= 2
            continue
        response.raise_for_status()
        return response


def _query_openai_compat(messages, stream, temp):
    """OpenAI-compatible chat-completions backend (local llama.cpp, Gemini)."""
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
                            print(content, end="", flush=True)
                            full_response += content
                    except json.JSONDecodeError:
                        pass
    finally:
        print("\033[0m\n")
    return full_response


def _query_anthropic(messages, stream, temp):
    """
    Native Anthropic /v1/messages backend with prompt caching (Phase 4).

    Cache breakpoints are declared by the caller as `cache_control: {"type": "ephemeral"}`
    on text blocks. Anthropic caches every prefix up to and including each marked
    block; cache TTL is 5 minutes. Cycle cadence keeps the system prompt + task
    description hot, cutting prompt tokens billed per cycle by ~75%.
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
                    print(text, end="", flush=True)
                    full_response += text
            elif etype == "message_start":
                usage = evt.get("message", {}).get("usage", {})
                cache_stats["cache_creation_input_tokens"] = usage.get("cache_creation_input_tokens")
                cache_stats["cache_read_input_tokens"] = usage.get("cache_read_input_tokens")
            elif etype == "message_stop":
                break
    finally:
        print("\033[0m\n")
    if cache_stats["cache_read_input_tokens"] is not None:
        print(f"[*] Anthropic cache: read={cache_stats['cache_read_input_tokens']} "
              f"created={cache_stats['cache_creation_input_tokens']} tokens")
    return full_response


def query_llm(messages, stream=True, temp=0.3):
    """
    Dispatch a chat request to the configured backend.

    Backends:
      - Anthropic (USE_ANTHROPIC=true) — native /v1/messages with cache_control breakpoints.
      - Gemini (USE_GEMINI=true) — OpenAI-compatible endpoint, no explicit cache.
      - Default — OpenAI-compatible local llama.cpp (automatic KV prefix cache).

    Message content may be a plain string OR a list of text blocks. The Anthropic
    backend preserves the block structure (including any `cache_control` markers);
    the other backends flatten the blocks into a single string.

    Cancellation: SIGTERM aborts before the request and again mid-stream by
    closing the socket so the inference server stops generation immediately (Phase 9).
    """
    _check_cancel(None, "before LLM call")
    if USE_ANTHROPIC:
        return _query_anthropic(messages, stream, temp)
    return _query_openai_compat(messages, stream, temp)

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
                    print(f"[*] Candidate {idx + 1}/{len(candidates)}: val_loss={result.loss:.6f}")
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


def select_parent(population: Population) -> PopulationMember:
    """Softmax-weighted selection: lower loss → higher probability of being chosen."""
    if len(population.members) == 1:
        return population.members[0]
    losses = [m.loss for m in population.members]
    max_loss = max(losses)
    # Shift by max so exponents stay small; lower loss → larger weight
    weights = [math.exp(max_loss - l) for l in losses]
    total = sum(weights)
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
# Outer Evolutionary Research Loop
# ---------------------------------------------------------------------------

def main():
    print("[*] Booting AutoResearch Agent with Self-Healing Inner Loop…")

    max_iterations = int(os.environ.get("MAX_ITERATIONS", 5))

    # --- Resume from checkpoint / population, or run fresh baseline ---
    checkpoint = load_checkpoint()
    population = load_population()
    iteration=1
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
            population = Population()
            population.members.append(PopulationMember(code=champ_code, loss=best_loss, cycle=0))
        print(f"[*] Resumed: cycle {iteration}, pop={len(population.members)}, "
              f"best_loss={best_loss:.6f}, {len(experiment_log)} history entries")
    else:
        iteration = 1
        print("[*] Running initial baseline evaluation…")
        baseline_output = run_cmd("python train.py")
        best_loss = extract_val_loss(baseline_output)
        if best_loss == float("inf"):
            print(
                "[!] Baseline script did not output a 'val_loss'. "
                "The AI will invent an appropriate metric and beat Infinity."
            )
        print(f"[*] Baseline val_loss established: {best_loss}")
        with open("train.py", "r") as f:
            baseline_code = f.read()
        started_at = datetime.datetime.utcnow().isoformat() + "Z"
        experiment_log = []
        history_prefix = ""
        population = Population()
        population.members.append(PopulationMember(code=baseline_code, loss=best_loss, cycle=0))

    with open("program.md", "r") as f:
        program_instructions = f.read()

    while iteration <= max_iterations:
        if _sigterm_received:
            print("[!] Shutdown requested — exiting loop.")
            break
        print(f"\n{'='*50}")
        print(f"--- AutoResearch Cycle {iteration} ---")

        # Rate-limit mitigation for Gemini
        if iteration > 1 and os.environ.get("USE_GEMINI") == "true":
            print("[*] Rate-limit mitigation: sleeping 5 s before next cycle…")
            time.sleep(5)

        model_name = "Gemini-2.0-Flash" if os.environ.get("USE_GEMINI") == "true" else "DeepSeek-32B"

        # Cosine annealing: 0.8 (explore) → 0.1 (exploit) over the run
        cycle_ratio = (iteration - 1) / max_iterations
        base_temp = 0.1 + 0.7 * 0.5 * (1 + math.cos(math.pi * cycle_ratio))
        # Per-candidate spread: low (exploit) / balanced / high (explore)
        candidate_temps = [
            max(0.05, base_temp * 0.5),
            base_temp,
            min(1.0, base_temp * 1.5),
        ]

        # Select parent from population (softmax-weighted by loss)
        parent = select_parent(population)
        print(f"[*] Selected parent from population "
              f"(loss={parent.loss:.6f}, from cycle {parent.cycle}).")

        print(f"[*] Querying {model_name} for {CANDIDATE_POOL_SIZE} parallel candidates "
              f"(base_temp={base_temp:.2f})…\n")

        # Stage A: analyze the selected parent (not frozen baseline) each cycle
        weakness_report = analyze_baseline(parent.code, program_instructions)

        # Phase 4: split the prompt into stable-prefix blocks (cacheable) +
        # a variable tail (per-cycle parent code, history hint, weaknesses).
        # SYSTEM_PROMPT and program_instructions are marked as ephemeral cache
        # breakpoints for Anthropic; OpenAI/Gemini receive the flattened string.
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

        research_messages = [
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

        # --- Generate CANDIDATE_POOL_SIZE independent candidates from the LLM ---
        candidates = []
        for idx in range(CANDIDATE_POOL_SIZE):
            temp = candidate_temps[idx % len(candidate_temps)]
            try:
                llm_response = query_llm(research_messages, temp=temp)
            except Exception as e:
                print(f"\n[-] LLM query failed (candidate {idx + 1}): {e}")
                continue
            code = extract_code_block(llm_response)
            if code:
                candidates.append(code)
            else:
                print(f"[-] Candidate {idx + 1} did not return a parseable code block.")

        if not candidates:
            print("[-] No valid candidates generated. Skipping cycle.")
            experiment_log.append({
                "cycle": iteration, "loss": None, "delta": None,
                "status": "failed", "target": weakness_report.split("\n")[0][:100],
            })
            save_checkpoint(iteration, best_loss, baseline_code, started_at, experiment_log, history_prefix)
            iteration += 1
            continue

        # --- Run all candidates in isolated sandboxes in parallel ---
        # Pass best_loss as the robustness threshold (Phase 8): candidates that
        # land within ROBUST_EVAL_MARGIN of the current champion are re-evaluated
        # k times and reported by median, to suppress false breakthroughs from
        # lucky random seeds.
        print(f"[*] Running {len(candidates)} candidate(s) in parallel sandboxes…")
        best_result = run_candidate_pool(candidates, threshold_loss=best_loss)

        if best_result is None:
            print("[-] All candidates failed evaluation. Keeping current champion.")
            champion = population.best()
            with open("train.py", "w") as f:
                f.write(champion.code)
            experiment_log.append({
                "cycle": iteration, "loss": None, "delta": None,
                "status": "failed", "target": weakness_report.split("\n")[0][:100],
            })
            save_checkpoint(iteration, best_loss, baseline_code, started_at, experiment_log, history_prefix)
            iteration += 1
            continue

        new_loss = best_result.loss
        print(f"[*] Best candidate val_loss: {new_loss:.6f}")

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
            print(f"[*] Population updated (new member loss={new_loss:.6f}). "
                  f"Champion unchanged at {best_loss:.6f}.")
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

        save_checkpoint(iteration, best_loss, baseline_code, started_at, experiment_log, history_prefix)
        iteration += 1

    print(f"\n{'='*50}")
    print(f"[*] AutoResearch Loop Completed! Final val_loss: {best_loss}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        # Raised by query_llm when SIGTERM arrives. Exit 0 so the parent
        # /run stream sees a normal EOF and still emits [FINAL_CODE_*].
        print("\n[!] Cancellation received — exiting cleanly.")