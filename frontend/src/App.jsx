import { useState, useRef, useEffect, useCallback, useMemo } from "react";

const AGENT_BASE = "/agent";
const AUTORESEARCH_BASE = "/autoresearch";

const SYNTHESIS_PROMPT = `You are an expert ML research engineer. Convert a user's raw idea into a precise, structured AutoResearch task definition in Markdown.

Output ONLY this exact structure, no preamble, no extra text:

## AutoResearch Task

### Objective
[Clear, specific statement of what must be achieved]

### Dataset
[Dataset description, format, features, and target variable]

### Evaluation Metric
[Primary metric and how it is computed, e.g., validation accuracy, F1-macro, MSE]

### Baseline
[What train.py should implement as a starting baseline — keep it simple]

### Constraints
[Hard constraints: libraries, compute, time budget, code style]

### Success Criteria
[What score or threshold marks a successful improvement over baseline]

Be specific, technical, and concise. Do not add extra sections.`;

const BASELINE_PLACEHOLDER = `# train.py — Baseline Implementation
# Paste or write your baseline training code here.
# The autonomous agent will read this and try to beat it.

import numpy as np

# def load_data(): ...
# def train(data): ...
# def evaluate(model, data): ...
#
# if __name__ == "__main__":
#     data = load_data()
#     model = train(data)
#     score = evaluate(model, data)
#     print(f"Baseline score: {score}")
`;

const TASK_PLACEHOLDER = `## AutoResearch Task

### Objective
Describe what the model should learn to do.

### Dataset
Describe the dataset format, features, and target variable.

### Evaluation Metric
Define how success is measured (e.g., accuracy, F1, MSE).

### Baseline
What train.py implements as the starting point.

### Constraints
Any constraints on the approach.

### Success Criteria
What improvement over baseline counts as success.
`;

const RUN_STATUS = { IDLE: "idle", RUNNING: "running", DONE: "done", ERROR: "error" };
const GEN_STATUS = { IDLE: "idle", LOADING: "loading", DONE: "done", ERROR: "error" };

const CSS = `
  @import url('https://fonts.googleapis.com/css2?family=Syne:wght@600;700;800&family=DM+Sans:ital,wght@0,300;0,400;0,500;1,300&family=JetBrains+Mono:wght@400;500&display=swap');

  :root {
    --bg0:      #06070f;
    --bg1:      #090b17;
    --bg2:      #0e1120;
    --bg3:      #141828;
    --bg4:      #1a1f33;

    --blue:     #7b9fff;
    --blue2:    #5b7df5;
    --blue3:    #3a56cc;
    --blueDim:  rgba(91,125,245,0.12);
    --blueGlow: rgba(123,159,255,0.22);
    --blueDeep: rgba(58,86,204,0.18);

    --violet:   #c084fc;
    --violetDim:rgba(192,132,252,0.1);

    --border:   rgba(91,125,245,0.08);
    --border2:  rgba(91,125,245,0.16);
    --border3:  rgba(91,125,245,0.3);

    --amber:    #fbbf24;
    --amberDim: rgba(251,191,36,0.1);
    --red:      #f87171;
    --redDim:   rgba(248,113,113,0.1);

    --text0:    #eef1ff;
    --text1:    #8b96c8;
    --text2:    #3d4670;

    --font-display: 'Syne', sans-serif;
    --font-ui:      'DM Sans', sans-serif;
    --font-mono:    'JetBrains Mono', monospace;
  }

  html, body, #root {
    width: 100%; height: 100%;
    margin: 0; padding: 0; overflow: hidden;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  textarea, input, button { font-family: var(--font-ui); outline: none; }

  @media (max-width: 900px) {
    :root {
      --panel-font-scale: 0.92;
    }
    .tab-btn { font-size: 11px; padding: 5px 8px; }
    .ghost-btn { font-size: 11px; padding: 4px 9px; }
  }
  @media (max-width: 640px) {
    .tab-btn span { display: none; }
  }

  ::-webkit-scrollbar       { width: 4px; height: 4px; }
  ::-webkit-scrollbar-track { background: var(--bg0); }
  ::-webkit-scrollbar-thumb { background: var(--blue3); border-radius: 2px; }

  @keyframes pulseGlow {
    0%,100% { box-shadow: 0 0 0 0   rgba(123,159,255,0.5); }
    50%      { box-shadow: 0 0 0 6px rgba(123,159,255,0);   }
  }
  @keyframes blink        { 0%,49%{opacity:1} 50%,100%{opacity:0} }
  @keyframes dotPulse     { 0%,80%,100%{transform:scale(.5);opacity:.3} 40%{transform:scale(1);opacity:1} }
  @keyframes fadeSlideIn  { from{opacity:0;transform:translateY(5px)} to{opacity:1;transform:translateY(0)} }
  @keyframes gradientShift {
    0%   { background-position: 0%   50%; }
    50%  { background-position: 100% 50%; }
    100% { background-position: 0%   50%; }
  }

  .tab-btn {
    background: none; border: none; cursor: pointer;
    font-family: var(--font-ui); font-size: 12px; font-weight: 500;
    padding: 5px 12px; border-radius: 6px;
    color: var(--text1); transition: all 0.2s;
    display: flex; align-items: center; gap: 5px; white-space: nowrap;
    letter-spacing: 0.02em;
  }
  .tab-btn:hover  { color: var(--text0); background: var(--blueDim); }
  .tab-btn.active { color: var(--blue);  background: var(--blueDim); box-shadow: inset 0 0 0 1px var(--border2); }

  .ghost-btn {
    background: var(--bg4); border: 1px solid var(--border2); border-radius: 6px;
    cursor: pointer; font-family: var(--font-ui); font-size: 12px; font-weight: 500;
    padding: 5px 12px; color: var(--text1); transition: all 0.2s; white-space: nowrap;
  }
  .ghost-btn:hover { color: var(--blue); border-color: var(--border3); background: var(--blueDim); }
  .ghost-btn:disabled { opacity: 0.35; cursor: not-allowed; }

  .icon-btn {
    background: none; border: none; cursor: pointer;
    color: var(--text2); font-size: 13px; padding: 3px 7px;
    border-radius: 4px; transition: all 0.15s;
  }
  .icon-btn:hover        { color: var(--blue);  background: var(--blueDim); }
  .icon-btn.danger:hover { color: var(--red);   background: var(--redDim);  }

  .primary-btn {
    font-family: var(--font-ui); font-size: 13px; font-weight: 600;
    border: none; border-radius: 8px; cursor: pointer;
    padding: 10px 22px; transition: all 0.2s; letter-spacing: 0.03em;
  }
  .primary-btn:disabled       { opacity: 0.3; cursor: not-allowed; }
  .primary-btn:not(:disabled):active { transform: scale(0.97); }

  .blue-btn {
    background: linear-gradient(135deg, var(--blue3), var(--blue2));
    color: #fff;
    box-shadow: 0 0 22px rgba(91,125,245,0.35), inset 0 1px 0 rgba(255,255,255,0.1);
  }
  .blue-btn:not(:disabled):hover {
    box-shadow: 0 0 32px rgba(123,159,255,0.5), inset 0 1px 0 rgba(255,255,255,0.15);
    background: linear-gradient(135deg, var(--blue2), var(--blue));
  }

  .stop-btn {
    background: var(--redDim); color: var(--red);
    border: 1px solid rgba(248,113,113,0.28);
  }
  .stop-btn:hover { background: rgba(248,113,113,0.18); }

  .code-area {
    width: 100%; resize: none; background: var(--bg0); border: none;
    color: var(--text0); font-family: var(--font-mono);
    font-size: 12.5px; line-height: 1.75; padding: 14px 16px; tab-size: 4;
  }
  .prose-area {
    width: 100%; resize: none; background: var(--bg0); border: none;
    color: var(--text0); font-family: var(--font-mono);
    font-size: 12.5px; line-height: 1.75; padding: 14px 16px;
  }
  .raw-area {
    width: 100%; background: var(--bg3);
    border: 1px solid var(--border2); border-radius: 8px;
    color: var(--text0); font-family: var(--font-ui);
    font-size: 13px; line-height: 1.6; padding: 10px 12px; resize: vertical;
  }
  .raw-area:focus { border-color: var(--border3); box-shadow: 0 0 0 3px var(--blueDim); }

  .card {
    background: var(--bg2); border: 1px solid var(--border);
    border-radius: 10px; padding: 14px; transition: border-color 0.2s;
  }
  .card:hover { border-color: var(--border2); }

  .step-card {
    display: flex; align-items: flex-start; gap: 14;
    padding: 10px 10px; border-radius: 9px;
    border: 1px solid transparent; transition: all 0.2s;
    cursor: default;
  }
  .step-card.clickable { cursor: pointer; }
  .step-card.clickable:hover {
    background: var(--blueDim);
    border-color: var(--border2);
  }
`;

// ── Primitives ───────────────────────────────────────────────────────────────

function Dot({ active, pulse }) {
  return (
    <span style={{
      display: "inline-block", width: 7, height: 7, borderRadius: "50%", flexShrink: 0,
      background: active ? "var(--blue)" : "var(--bg4)",
      boxShadow: active ? "0 0 8px var(--blue)" : "none",
      animation: pulse ? "pulseGlow 1.6s ease-in-out infinite" : "none",
    }} />
  );
}

function SectionLabel({ children }) {
  return (
    <div style={{
      fontSize: 10, fontWeight: 600, letterSpacing: "0.1em",
      textTransform: "uppercase", color: "var(--blue3)",
      marginBottom: 10, fontFamily: "var(--font-ui)",
    }}>{children}</div>
  );
}

function StatusBadge({ status }) {
  const cfg = {
    [RUN_STATUS.IDLE]: { label: "STANDBY", color: "var(--text2)", glow: false },
    [RUN_STATUS.RUNNING]: { label: "EVOLVING", color: "var(--blue)", glow: true },
    [RUN_STATUS.DONE]: { label: "COMPLETE", color: "var(--blue2)", glow: false },
    [RUN_STATUS.ERROR]: { label: "FAULT", color: "var(--red)", glow: false },
  }[status];
  return (
    <div style={{
      display: "inline-flex", alignItems: "center", gap: 7,
      padding: "4px 12px 4px 8px",
      background: "var(--bg2)", border: "1px solid var(--border2)", borderRadius: 20,
    }}>
      <Dot active={status !== RUN_STATUS.IDLE} pulse={status === RUN_STATUS.RUNNING} />
      <span style={{
        fontSize: 10, fontWeight: 700, letterSpacing: "0.12em",
        color: cfg.color, fontFamily: "var(--font-mono)",
        textShadow: cfg.glow ? `0 0 10px ${cfg.color}` : "none",
      }}>{cfg.label}</span>
    </div>
  );
}

function ProgressBar({ current, total }) {
  const pct = total > 0 ? Math.round((current / total) * 100) : 0;
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
        <span style={{ fontSize: 10, color: "var(--text2)", letterSpacing: "0.08em", textTransform: "uppercase", fontFamily: "var(--font-ui)" }}>
          Evolution Progress
        </span>
        <span style={{ fontSize: 11, color: "var(--blue)", fontFamily: "var(--font-mono)" }}>
          {current} / {total}
        </span>
      </div>
      <div style={{ background: "var(--bg4)", borderRadius: 3, height: 3, overflow: "hidden", border: "1px solid var(--border)" }}>
        <div style={{
          height: "100%", width: `${pct}%`,
          background: "linear-gradient(90deg, var(--blue3), var(--blue))",
          borderRadius: 3, transition: "width 0.6s ease",
          boxShadow: "0 0 8px var(--blue)",
        }} />
      </div>
    </div>
  );
}

// ── Loss Sparkline ───────────────────────────────────────────────────────────

function LossSparkline({ history }) {
  if (history.length < 2) return null;
  const W = 110, H = 28, PAD = 3;
  const losses = history.map(p => p.loss);
  const minL = Math.min(...losses);
  const maxL = Math.max(...losses);
  const range = maxL - minL || 1;
  const pts = losses.map((l, i) => {
    const x = PAD + (i / (losses.length - 1)) * (W - PAD * 2);
    const y = H - PAD - ((l - minL) / range) * (H - PAD * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const lastPt = pts.split(" ").at(-1).split(",");
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <svg width={W} height={H} style={{ overflow: "visible", flexShrink: 0 }}>
        <polyline points={pts} fill="none" stroke="var(--blue)" strokeWidth="1.5"
          strokeLinejoin="round" strokeLinecap="round" opacity="0.75" />
        <circle cx={lastPt[0]} cy={lastPt[1]} r="2.5" fill="var(--blue)"
          style={{ filter: "drop-shadow(0 0 3px var(--blue))" }} />
      </svg>
      <span style={{
        fontSize: 10, color: "var(--blue)", fontFamily: "var(--font-mono)",
        letterSpacing: "0.04em", minWidth: 52,
      }}>
        {losses.at(-1).toFixed(4)}
      </span>
    </div>
  );
}

// ── Diff Utilities ───────────────────────────────────────────────────────────

function computeDiff(aLines, bLines) {
  const n = aLines.length, m = bLines.length;
  if (!n && !m) return [];
  if (!n) return bLines.map(line => ({ type: "insert", line }));
  if (!m) return aLines.map(line => ({ type: "delete", line }));
  const dp = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = 1; i <= n; i++)
    for (let j = 1; j <= m; j++)
      dp[i][j] = aLines[i - 1] === bLines[j - 1]
        ? dp[i - 1][j - 1] + 1
        : Math.max(dp[i - 1][j], dp[i][j - 1]);
  const result = [];
  let i = n, j = m;
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && aLines[i - 1] === bLines[j - 1]) {
      result.unshift({ type: "equal", line: aLines[i - 1] }); i--; j--;
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      result.unshift({ type: "insert", line: bLines[j - 1] }); j--;
    } else {
      result.unshift({ type: "delete", line: aLines[i - 1] }); i--;
    }
  }
  return result;
}

function DiffView({ diff, championCode }) {
  if (!championCode) return (
    <div style={{
      flex: 1, display: "flex", flexDirection: "column",
      alignItems: "center", justifyContent: "center", gap: 10,
    }}>
      <div style={{ fontSize: 22, color: "var(--text2)" }}>◈</div>
      <div style={{ fontSize: 12, color: "var(--text1)", fontFamily: "var(--font-display)", fontWeight: 600 }}>
        Awaiting champion code
      </div>
      <div style={{ fontSize: 11, color: "var(--text2)", fontFamily: "var(--font-mono)" }}>
        Arrives via [FINAL_CODE_START/END]
      </div>
    </div>
  );
  const adds = diff.filter(d => d.type === "insert").length;
  const dels = diff.filter(d => d.type === "delete").length;
  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
      <div style={{
        padding: "6px 16px", borderBottom: "1px solid var(--border)",
        background: "var(--bg2)", fontSize: 11, fontFamily: "var(--font-mono)",
        flexShrink: 0, display: "flex", gap: 14, alignItems: "center",
      }}>
        <span style={{ color: "#4ade80" }}>+{adds} insertions</span>
        <span style={{ color: "var(--red)" }}>-{dels} deletions</span>
      </div>
      <div style={{ flex: 1, overflowY: "auto", paddingBottom: 18 }}>
        {diff.map((d, idx) => {
          const isIns = d.type === "insert", isDel = d.type === "delete";
          return (
            <div key={idx} style={{
              fontFamily: "var(--font-mono)", fontSize: 12, lineHeight: 1.65,
              padding: "0 16px",
              background: isIns ? "rgba(74,222,128,0.07)" : isDel ? "rgba(248,113,113,0.07)" : "transparent",
              color: isIns ? "#4ade80" : isDel ? "var(--red)" : "var(--text2)",
              whiteSpace: "pre-wrap", wordBreak: "break-all",
              borderLeft: `2px solid ${isIns ? "#4ade80" : isDel ? "var(--red)" : "transparent"}`,
            }}>
              {isIns ? "+" : isDel ? "-" : " "}{d.line}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Workflow Steps ───────────────────────────────────────────────────────────

const STEPS = [
  { n: "01", label: "Generate", sub: "Describe idea → agent synthesises a structured task", tab: "generate" },
  { n: "02", label: "Review", sub: "Edit the task definition written to program.md", tab: "task" },
  { n: "03", label: "Baseline", sub: "Paste train.py — the agent evolves beyond this", tab: "baseline" },
  { n: "04", label: "Configure", sub: "Set iterations, upload dataset if required", tab: "config" },
  { n: "05", label: "Launch", sub: "Agent self-evolves in a loop, logs stream live", tab: null },
];

function WorkflowSteps({ onTabSwitch }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      {STEPS.map((s, idx) => (
        <div
          key={s.n}
          className={`step-card${s.tab ? " clickable" : ""}`}
          onClick={() => s.tab && onTabSwitch(s.tab)}
          style={{ animation: `fadeSlideIn 0.3s ease both`, animationDelay: `${idx * 0.07}s` }}
        >
          <div style={{
            width: 34, height: 34, borderRadius: 8, flexShrink: 0,
            background: "var(--bg4)", border: "1px solid var(--border2)",
            display: "flex", alignItems: "center", justifyContent: "center",
            fontFamily: "var(--font-mono)", fontSize: 11, fontWeight: 500,
            color: "var(--blue2)", letterSpacing: "0.04em",
            boxShadow: "0 0 12px rgba(91,125,245,0.08)",
          }}>{s.n}</div>

          <div style={{ flex: 1, paddingTop: 2 }}>
            <div style={{
              fontSize: 13, fontWeight: 700, color: "var(--text0)",
              fontFamily: "var(--font-display)", letterSpacing: "0.01em", marginBottom: 2,
            }}>{s.label}</div>
            <div style={{
              fontSize: 11.5, color: "var(--text1)", lineHeight: 1.5, fontFamily: "var(--font-ui)",
            }}>{s.sub}</div>
          </div>

          {s.tab && (
            <div style={{ color: "var(--blue3)", fontSize: 13, paddingTop: 9, opacity: 0.8 }}>→</div>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Task Synthesiser (formerly Task Generator) ───────────────────────────────

function TaskSynthesiser({ onAccept, disabled, modelChoice, apiKey }) {
  const [prompt, setPrompt] = useState("");
  const [status, setStatus] = useState(GEN_STATUS.IDLE);
  const [preview, setPreview] = useState("");
  const abortRef = useRef(null);

  const generate = async () => {
    if (!prompt.trim()) return;
    setStatus(GEN_STATUS.LOADING);
    setPreview("");
    try {
      abortRef.current = new AbortController();
      const res = await fetch(`${AGENT_BASE}/v1/chat/completions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: abortRef.current.signal,
        body: JSON.stringify({
          model: "deepSeek-R1-Distill-Qwen-32B", stream: true,
          messages: [
            { role: "system", content: SYNTHESIS_PROMPT },
            { role: "user", content: prompt },
          ],
        }),
      });
      if (!res.ok) throw new Error(`Agent returned HTTP ${res.status}`);
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let acc = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        for (const line of dec.decode(value, { stream: true }).split("\n")) {
          if (!line.startsWith("data: ") || line.includes("[DONE]")) continue;
          try {
            const delta = JSON.parse(line.slice(6)).choices?.[0]?.delta?.content ?? "";
            acc += delta;
            setPreview(acc);
          } catch { /* partial */ }
        }
      }
      setStatus(GEN_STATUS.DONE);
    } catch (err) {
      if (err.name === "AbortError") { setStatus(GEN_STATUS.IDLE); return; }
      setPreview(`Error: ${err.message}`);
      setStatus(GEN_STATUS.ERROR);
    }
  };

  const cancel = () => { abortRef.current?.abort(); setStatus(GEN_STATUS.IDLE); setPreview(""); };
  const accept = () => { onAccept(preview); setStatus(GEN_STATUS.IDLE); setPreview(""); setPrompt(""); };
  const discard = () => { setStatus(GEN_STATUS.IDLE); setPreview(""); };

  const loading = status === GEN_STATUS.LOADING;
  const done = status === GEN_STATUS.DONE;
  const error = status === GEN_STATUS.ERROR;

  return (
    <div style={{
      border: "1px solid var(--border2)", borderRadius: 12, overflow: "hidden",
      background: "var(--bg1)", boxShadow: "0 0 30px rgba(91,125,245,0.05)",
    }}>
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center", gap: 10, padding: "10px 14px",
        background: "linear-gradient(90deg, var(--blueDeep), transparent)",
        borderBottom: "1px solid var(--border2)",
      }}>
        <div style={{
          width: 22, height: 22, borderRadius: 5, flexShrink: 0,
          background: "linear-gradient(135deg, var(--blue3), var(--blue))",
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 11, fontWeight: 800, color: "#fff",
          fontFamily: "var(--font-display)",
          boxShadow: "0 0 10px var(--blueGlow)",
        }}>✦</div>
        <span style={{
          fontSize: 12, fontWeight: 600, color: "var(--blue)",
          fontFamily: "var(--font-mono)", letterSpacing: "0.06em",
          textShadow: "0 0 10px rgba(123,159,255,0.4)",
        }}>TASK SYNTHESIS ENGINE</span>
        {loading && (
          <span style={{ marginLeft: "auto", display: "flex", gap: 4, alignItems: "center" }}>
            {[0, 1, 2].map(i => (
              <span key={i} style={{
                width: 5, height: 5, borderRadius: "50%", background: "var(--blue)",
                animation: `dotPulse 1s ease-in-out ${i * 0.16}s infinite`,
              }} />
            ))}
          </span>
        )}
        {done && (
          <span style={{
            fontSize: 10, color: "var(--blue2)", marginLeft: "auto",
            fontFamily: "var(--font-mono)", letterSpacing: "0.06em",
          }}>✓ READY</span>
        )}
      </div>

      <div style={{ padding: 14, display: "flex", flexDirection: "column", gap: 12 }}>
        <textarea
          className="raw-area"
          value={prompt}
          onChange={e => setPrompt(e.target.value)}
          disabled={loading || disabled}
          rows={4}
          placeholder={"Describe your research idea in plain language…\n\ne.g. \"Train a CNN to classify medical X-rays into 3 categories.\nDataset: 10k PNG images with labels in a CSV file.\""}
        />

        {preview && (
          <div style={{
            background: "var(--bg0)",
            border: `1px solid ${error ? "rgba(248,113,113,0.25)" : "var(--border2)"}`,
            borderRadius: 8, padding: 12, maxHeight: 230, overflowY: "auto",
          }}>
            <div style={{
              fontSize: 9, letterSpacing: "0.1em", textTransform: "uppercase",
              color: error ? "var(--red)" : loading ? "var(--blue)" : "var(--blue2)",
              marginBottom: 8, fontFamily: "var(--font-mono)",
            }}>
              {error ? "ERROR" : loading ? "SYNTHESISING…" : "PREVIEW — ACCEPT OR DISCARD"}
            </div>
            <pre style={{
              fontFamily: "var(--font-mono)", fontSize: 11.5, lineHeight: 1.75,
              color: error ? "var(--red)" : "var(--text0)",
              whiteSpace: "pre-wrap", wordBreak: "break-word", margin: 0,
            }}>{preview}{loading && <span style={{ animation: "blink 1s step-end infinite" }}>▌</span>}</pre>
          </div>
        )}

        <div style={{ display: "flex", gap: 8 }}>
          {loading ? (
            <button className="ghost-btn" onClick={cancel}
              style={{ color: "var(--red)", borderColor: "rgba(248,113,113,0.3)" }}>
              ✕ Cancel
            </button>
          ) : done ? (
            <>
              <button className="primary-btn blue-btn" onClick={accept} style={{ flex: 1 }}>
                ✓ Accept → Task Definition
              </button>
              <button className="ghost-btn" onClick={discard}>Discard</button>
            </>
          ) : (
            <button className="primary-btn blue-btn" onClick={generate}
              disabled={!prompt.trim() || disabled} style={{ width: "100%" }}>
              ⟳ Generate
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Log Line ─────────────────────────────────────────────────────────────────

function LogLine({ line, index }) {
  const lo = line.toLowerCase();
  let color = "var(--text0)";
  let glow = "none";
  if (lo.includes("error") || lo.includes("traceback")) {
    color = "var(--red)";
  } else if (lo.includes("best") || lo.includes("improved") || line.includes("✓")) {
    color = "var(--blue)"; glow = "0 0 6px rgba(123,159,255,0.35)";
  } else if (line.startsWith("═") || line.startsWith(">>>") || lo.startsWith("iteration")) {
    color = "var(--blue2)";
  } else if (line.startsWith("---")) {
    color = "var(--text2)";
  }
  return (
    <div style={{
      fontFamily: "var(--font-mono)", fontSize: 14, lineHeight: 1.8,
      color, padding: "2px 0 2px 18px", whiteSpace: "pre-wrap", wordBreak: "break-all",
      textShadow: glow, borderLeft: "2px solid transparent",
      textAlign: "left", display: "block", width: "100%",
      animation: index > 0 ? "fadeSlideIn 0.15s ease both" : "none",
    }}>{line}</div>
  );
}

// ── Tab Bar ──────────────────────────────────────────────────────────────────

function TabBar({ tabs, active, onChange }) {
  return (
    <div style={{
      display: "flex", gap: 2, padding: "8px 10px",
      borderBottom: "1px solid var(--border)", background: "var(--bg1)", flexShrink: 0,
    }}>
      {tabs.map(t => (
        <button key={t.id} className={`tab-btn${active === t.id ? " active" : ""}`}
          onClick={() => onChange(t.id)}>
          <span style={{ fontSize: 12 }}>{t.icon}</span>
          {t.label}
        </button>
      ))}
    </div>
  );
}

// ── Main ─────────────────────────────────────────────────────────────────────

export default function App() {
  const [leftTab, setLeftTab] = useState("generate");
  const [task, setTask] = useState(TASK_PLACEHOLDER);
  const [baseline, setBaseline] = useState(BASELINE_PLACEHOLDER);
  const [iterations, setIterations] = useState(5);
  const [modelChoice, setModelChoice] = useState("local");
  const [apiKey, setApiKey] = useState("");
  const [file, setFile] = useState(null);
  const [runStatus, setRunStatus] = useState(RUN_STATUS.IDLE);
  const [logs, setLogs] = useState([]);
  const [currentIter, setCurrentIter] = useState(0);
  const [lossHistory, setLossHistory] = useState([]);
  const [championCode, setChampionCode] = useState("");
  const [rightTab, setRightTab] = useState("log");
  const logEndRef = useRef(null);
  const streamRef = useRef(null);
  const fileRef = useRef(null);
  const lineBufferRef = useRef("");
  const collectingRef = useRef(false);
  const championBufRef = useRef("");

  useEffect(() => { logEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [logs]);

  const processLine = useCallback(line => {
    if (line.startsWith("__EVENT__")) {
      try {
        const ev = JSON.parse(line.slice(9));
        if (ev.type === "cycle_result")
          setLossHistory(h => [...h, { cycle: ev.cycle, loss: ev.loss }]);
      } catch {}
      return;
    }
    if (line === "[FINAL_CODE_START]") {
      collectingRef.current = true;
      championBufRef.current = "";
      return;
    }
    if (line === "[FINAL_CODE_END]") {
      collectingRef.current = false;
      setChampionCode(championBufRef.current.trimEnd());
      setRightTab("champion");
      return;
    }
    if (collectingRef.current) {
      championBufRef.current += line + "\n";
      return;
    }
    setLogs(p => [...p, line]);
    const m = line.match(/[Ii]teration\s+(\d+)/);
    if (m) setCurrentIter(parseInt(m[1]));
  }, []);

  const appendLogChunk = useCallback(chunk => {
    const combined = lineBufferRef.current + chunk;
    const lines = combined.split("\n");
    lineBufferRef.current = lines.pop() ?? "";
    for (const line of lines) processLine(line);
  }, [processLine]);

  const appendLog = useCallback(line => {
    setLogs(p => [...p, line]);
  }, []);

  const handleStart = async () => {
    if (!task.trim() || !baseline.trim()) return;
    setRunStatus(RUN_STATUS.RUNNING);
    setLogs([]);
    setCurrentIter(0);
    setLossHistory([]);
    setChampionCode("");
    setRightTab("log");
    lineBufferRef.current = "";
    collectingRef.current = false;
    championBufRef.current = "";
    try {
      if (modelChoice === "gemini" && !apiKey.trim()) {
        throw new Error("Gemini API Key is required when Gemini model is selected.");
      }

      const fd = new FormData();
      fd.append("task", task);
      fd.append("baseline", baseline);
      fd.append("iterations", iterations);
      fd.append("modelChoice", modelChoice);
      fd.append("apiKey", apiKey);
      if (file) fd.append("data", file);

      appendLog(">>> Initialising self-evolution loop…");
      appendLog(`>>> Target iterations : ${iterations}`);
      if (file) appendLog(`>>> Dataset          : ${file.name} (${(file.size / 1024).toFixed(1)} KB)`);
      appendLog("═".repeat(58));

      const res = await fetch(`${AUTORESEARCH_BASE}/run`, { method: "POST", body: fd });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      streamRef.current = reader;
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        // Process streaming text chunks directly
        const textChunk = dec.decode(value, { stream: true });
        if (textChunk) appendLogChunk(textChunk);
      }
      if (lineBufferRef.current) { processLine(lineBufferRef.current); lineBufferRef.current = ""; }
      appendLog("═".repeat(58));
      appendLog("✓ Evolution complete — check improved train.py in container.");
      setRunStatus(RUN_STATUS.DONE);
    } catch (err) {
      appendLog(`ERROR: ${err.message}`);
      setRunStatus(RUN_STATUS.ERROR);
    }
  };

  const handleStop = () => {
    streamRef.current?.cancel();
    lineBufferRef.current = "";
    collectingRef.current = false;
    appendLog("--- Evolution paused — progress saved ---");
    setRunStatus(RUN_STATUS.IDLE);
  };

  const taskLines = task.split("\n").length;
  const baselineLines = baseline.split("\n").length;

  const LEFT_TABS = [
    { id: "generate", icon: "⟳", label: "Generate" },
    { id: "task", icon: "◈", label: `Task (${taskLines}L)` },
    { id: "baseline", icon: "⌥", label: `Baseline (${baselineLines}L)` },
    { id: "config", icon: "◎", label: "Config" },
  ];

  const RIGHT_TABS = [
    { id: "log", icon: "▸", label: `Log (${logs.length}L)` },
    { id: "champion", icon: "◈", label: championCode ? "Champion ✓" : "Champion" },
  ];

  const diffLines = useMemo(
    () => championCode ? computeDiff(baseline.split("\n"), championCode.split("\n")) : [],
    [baseline, championCode],
  );

  return (
    <>
      <style>{CSS}</style>
      <div style={{
        position: "fixed", inset: 0,
        height: "100dvh",
        display: "flex", flexDirection: "column",
        background: "var(--bg0)", color: "var(--text0)", overflow: "hidden",
        fontFamily: "var(--font-ui)",
      }}>

        {/* ── Header ── */}
        <header style={{
          height: 58, flexShrink: 0,
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "0 22px", background: "var(--bg1)",
          borderBottom: "1px solid var(--border)",
          position: "relative", overflow: "hidden",
        }}>
          {/* Subtle scanlines */}
          <div style={{
            position: "absolute", inset: 0, pointerEvents: "none",
            background: "repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(91,125,245,0.015) 2px, rgba(91,125,245,0.015) 4px)",
          }} />
          {/* Right glow */}
          <div style={{
            position: "absolute", right: 160, top: "50%", transform: "translateY(-50%)",
            width: 200, height: 60, borderRadius: "50%",
            background: "radial-gradient(ellipse, rgba(91,125,245,0.12) 0%, transparent 70%)",
            pointerEvents: "none",
          }} />

          <div style={{ display: "flex", alignItems: "center", gap: 14, position: "relative" }}>
            {/* Logo */}
            <div style={{
              width: 38, height: 38, borderRadius: 10, flexShrink: 0,
              background: "linear-gradient(135deg, #1a1f45 0%, #3a56cc 100%)",
              border: "1px solid var(--border3)",
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 18, boxShadow: "0 0 20px rgba(91,125,245,0.3)",
            }}>⬡</div>

            <div>
              <div style={{
                fontFamily: "var(--font-display)",
                fontSize: "clamp(12px, 1.4vw, 16px)", fontWeight: 800, lineHeight: 1.15,
                background: "linear-gradient(90deg, #eef1ff 0%, #7b9fff 60%, #c084fc 100%)",
                backgroundSize: "200% auto",
                animation: "gradientShift 6s ease infinite",
                WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
                letterSpacing: "0.005em", whiteSpace: "nowrap",
              }}>
                Self Evolving Autonomous Agent
              </div>
              <div style={{
                fontSize: 10, color: "var(--blue3)", letterSpacing: "0.1em",
                fontFamily: "var(--font-mono)", marginTop: 2,
              }}>
                SYNTHESIS ENGINE &nbsp;·&nbsp; EVOLUTION CORE
              </div>
            </div>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 14, position: "relative" }}>
            <LossSparkline history={lossHistory} />
            <StatusBadge status={runStatus} />
          </div>
        </header>

        {/* ── Body ── */}
        <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>

          {/* ── Left Panel ── */}
          <div style={{
            width: "clamp(320px, 30vw, 480px)", flexShrink: 0, display: "flex", flexDirection: "column",
            borderRight: "1px solid var(--border)", background: "var(--bg1)", overflow: "hidden",
          }}>
            <TabBar tabs={LEFT_TABS} active={leftTab} onChange={setLeftTab} />

            <div style={{ flex: 1, overflowY: "auto" }}>

              {/* ── Generate ── */}
              {leftTab === "generate" && (
                <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 16 }}>
                  <p style={{ fontSize: 12, color: "var(--text1)", lineHeight: 1.65, fontFamily: "var(--font-ui)" }}>
                    Describe your research idea in plain language. The synthesis engine will
                    expand it into a structured task written to{" "}
                    <code style={{ color: "var(--blue2)", fontFamily: "var(--font-mono)", fontSize: 11 }}>
                      program.md
                    </code>.
                  </p>

                  <TaskSynthesiser
                    onAccept={text => { setTask(text); setLeftTab("task"); }}
                    disabled={runStatus === RUN_STATUS.RUNNING}
                    modelChoice={modelChoice}
                    apiKey={apiKey}
                  />

                  {/* Protocol steps */}
                  <div style={{
                    background: "var(--bg0)", border: "1px solid var(--border)",
                    borderRadius: 12, padding: "12px 10px",
                  }}>
                    <div style={{
                      fontSize: 10, fontWeight: 700, letterSpacing: "0.12em",
                      color: "var(--blue3)", textTransform: "uppercase",
                      fontFamily: "var(--font-mono)", padding: "0 4px", marginBottom: 8,
                    }}>
                      Protocol
                    </div>
                    <WorkflowSteps onTabSwitch={setLeftTab} />
                  </div>
                </div>
              )}

              {/* ── Task ── */}
              {leftTab === "task" && (
                <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
                  <div style={{
                    padding: "7px 12px", borderBottom: "1px solid var(--border)",
                    display: "flex", alignItems: "center", justifyContent: "space-between",
                    flexShrink: 0, background: "var(--bg2)",
                  }}>
                    <span style={{ fontSize: 11, color: "var(--blue2)", fontFamily: "var(--font-mono)" }}>
                      program.md
                    </span>
                    <div style={{ display: "flex", gap: 4 }}>
                      <button className="ghost-btn" onClick={() => setLeftTab("generate")}
                        style={{ fontSize: 11, padding: "3px 8px" }}>
                        ⟳ Re-generate
                      </button>
                      <button className="icon-btn" onClick={() => navigator.clipboard.writeText(task)} title="Copy">⎘</button>
                      <button className="icon-btn danger" onClick={() => setTask(TASK_PLACEHOLDER)} title="Reset">↺</button>
                    </div>
                  </div>
                  <textarea className="prose-area" value={task}
                    onChange={e => setTask(e.target.value)}
                    disabled={runStatus === RUN_STATUS.RUNNING}
                    style={{ flex: 1 }} spellCheck={false} />
                  <div style={{
                    padding: "5px 14px", borderTop: "1px solid var(--border)", background: "var(--bg2)",
                    fontSize: 10, color: "var(--text2)", fontFamily: "var(--font-mono)", flexShrink: 0,
                  }}>
                    {task.length} chars · {taskLines} lines
                  </div>
                </div>
              )}

              {/* ── Baseline ── */}
              {leftTab === "baseline" && (
                <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
                  <div style={{
                    padding: "7px 12px", borderBottom: "1px solid var(--border)",
                    display: "flex", alignItems: "center", justifyContent: "space-between",
                    flexShrink: 0, background: "var(--bg2)",
                  }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span style={{ fontSize: 11, color: "var(--blue2)", fontFamily: "var(--font-mono)" }}>train.py</span>
                      <span style={{
                        fontSize: 9, fontWeight: 600, letterSpacing: "0.08em",
                        background: "rgba(91,125,245,0.12)", color: "var(--blue2)",
                        border: "1px solid var(--border2)", borderRadius: 4,
                        padding: "1px 6px", fontFamily: "var(--font-mono)",
                      }}>BASELINE</span>
                    </div>
                    <div style={{ display: "flex", gap: 4 }}>
                      <button className="icon-btn" onClick={() => navigator.clipboard.writeText(baseline)} title="Copy">⎘</button>
                      <button className="icon-btn" onClick={() => navigator.clipboard.readText().then(t => setBaseline(t)).catch(() => { })} title="Paste from clipboard">📋</button>
                      <button className="icon-btn danger" onClick={() => setBaseline(BASELINE_PLACEHOLDER)} title="Reset">↺</button>
                    </div>
                  </div>
                  <div style={{ flex: 1, position: "relative", overflow: "hidden" }}>
                    <textarea className="code-area"
                      value={baseline} onChange={e => setBaseline(e.target.value)}
                      disabled={runStatus === RUN_STATUS.RUNNING}
                      spellCheck={false}
                      placeholder="Paste or write your baseline train.py here…"
                      style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
                    />
                  </div>
                  <div style={{
                    padding: "5px 14px", borderTop: "1px solid var(--border)", background: "var(--bg2)",
                    fontSize: 10, color: "var(--text2)", fontFamily: "var(--font-mono)",
                    flexShrink: 0, display: "flex", justifyContent: "space-between",
                  }}>
                    <span>{baseline.length} chars · {baselineLines} lines</span>
                    <span style={{ color: "var(--blue3)" }}>agent evolves beyond this</span>
                  </div>
                </div>
              )}

              {/* ── Config ── */}
              {leftTab === "config" && (
                <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 14 }}>

                  <div className="card">
                    <SectionLabel>Iterations</SectionLabel>
                    <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
                      <input type="range" min={1} max={50} step={1}
                        value={iterations}
                        onChange={e => setIterations(Number(e.target.value))}
                        disabled={runStatus === RUN_STATUS.RUNNING}
                        style={{ flex: 1, accentColor: "var(--blue2)" }}
                      />
                      <div style={{
                        width: 46, textAlign: "center",
                        background: "var(--bg4)", border: "1px solid var(--border2)",
                        borderRadius: 7, padding: "5px 0",
                        fontSize: 18, fontWeight: 700,
                        color: "var(--blue)", fontFamily: "var(--font-mono)",
                        boxShadow: "0 0 10px rgba(123,159,255,0.15)",
                      }}>{iterations}</div>
                    </div>
                    <div style={{ fontSize: 11, color: "var(--text2)", fontFamily: "var(--font-ui)" }}>
                      Each cycle: proposes → executes → benchmarks vs baseline
                    </div>
                  </div>

                  <div className="card">
                    <SectionLabel>Dataset (optional)</SectionLabel>
                    <div
                      onDrop={e => { e.preventDefault(); setFile(e.dataTransfer.files[0]); }}
                      onDragOver={e => e.preventDefault()}
                      onClick={() => fileRef.current?.click()}
                      style={{
                        border: `1px dashed ${file ? "var(--blue2)" : "var(--border2)"}`,
                        borderRadius: 8, padding: "18px 12px", textAlign: "center",
                        cursor: "pointer", background: file ? "var(--blueDeep)" : "transparent",
                        transition: "all 0.2s",
                      }}>
                      {file ? (
                        <>
                          <div style={{ fontSize: 20, color: "var(--blue)", marginBottom: 4 }}>◈</div>
                          <div style={{ fontSize: 13, fontWeight: 500, color: "var(--blue)", fontFamily: "var(--font-mono)" }}>{file.name}</div>
                          <div style={{ fontSize: 11, color: "var(--text1)" }}>{(file.size / 1024).toFixed(1)} KB</div>
                        </>
                      ) : (
                        <>
                          <div style={{ fontSize: 20, color: "var(--text2)", marginBottom: 6 }}>⬡</div>
                          <div style={{ fontSize: 13, color: "var(--text1)" }}>Drop file or click to upload</div>
                          <div style={{ fontSize: 10, color: "var(--text2)", marginTop: 3, letterSpacing: "0.06em", fontFamily: "var(--font-mono)" }}>
                            CSV · JSON · NPZ · PKL · TXT
                          </div>
                        </>
                      )}
                    </div>
                    {file && (
                      <button onClick={() => setFile(null)} style={{
                        marginTop: 6, background: "none", border: "none",
                        color: "var(--red)", fontSize: 12, cursor: "pointer",
                        fontFamily: "var(--font-ui)",
                      }}>✕ Remove</button>
                    )}
                    <input ref={fileRef} type="file" style={{ display: "none" }}
                      onChange={e => setFile(e.target.files[0])} />
                  </div>

                  <div className="card">
                    <SectionLabel>Model Selection</SectionLabel>
                    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                      <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, cursor: "pointer", color: "var(--text0)" }}>
                        <input type="radio" name="model" value="local" checked={modelChoice === "local"} onChange={() => setModelChoice("local")} style={{ accentColor: "var(--blue)" }} />
                        Local DeepSeek-32B
                      </label>
                      <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, cursor: "pointer", color: "var(--text0)" }}>
                        <input type="radio" name="model" value="gemini" checked={modelChoice === "gemini"} onChange={() => setModelChoice("gemini")} style={{ accentColor: "var(--blue)" }} />
                        Gemini 2.0 Flash API (Max Free Limit)
                      </label>
                      {modelChoice === "gemini" && (
                        <input type="password" placeholder="Paste Gemini API Key here..." value={apiKey} onChange={e => setApiKey(e.target.value)} className="raw-area" style={{ marginTop: 2 }} />
                      )}
                    </div>
                  </div>

                  <div className="card">
                    <SectionLabel>Services</SectionLabel>
                    {[
                      { label: "Synthesis Engine", url: "Connected" },
                      { label: "Evolution Core", url: "Connected" },
                    ].map(e => (
                      <div key={e.label} style={{
                        display: "flex", justifyContent: "space-between",
                        alignItems: "center", marginBottom: 8,
                      }}>
                        <span style={{ fontSize: 12, color: "var(--text1)", fontFamily: "var(--font-ui)" }}>{e.label}</span>
                        <code style={{
                          fontSize: 11, color: "var(--blue2)", background: "var(--bg4)",
                          padding: "2px 8px", borderRadius: 4, fontFamily: "var(--font-mono)",
                          border: "1px solid var(--border)",
                        }}>{e.url}</code>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* ── Launch / Stop ── */}
            <div style={{
              padding: 14, borderTop: "1px solid var(--border)",
              display: "flex", flexDirection: "column", gap: 10, flexShrink: 0,
              background: "var(--bg1)",
            }}>
              {runStatus === RUN_STATUS.RUNNING ? (
                <button className="primary-btn stop-btn" onClick={handleStop} style={{ width: "100%" }}>
                  ⏸ Pause & Save Progress
                </button>
              ) : (
                <button className="primary-btn blue-btn" onClick={handleStart}
                  disabled={!task.trim() || !baseline.trim()} style={{ width: "100%" }}>
                  ▶ Launch Evolution
                </button>
              )}
              {!baseline.trim() && runStatus !== RUN_STATUS.RUNNING && (
                <div style={{
                  fontSize: 11, color: "var(--amber)", textAlign: "center",
                  fontFamily: "var(--font-mono)", letterSpacing: "0.04em",
                }}>
                  ⚠ baseline train.py required
                </div>
              )}
              {runStatus === RUN_STATUS.RUNNING && (
                <ProgressBar current={currentIter} total={iterations} />
              )}
            </div>
          </div>

          {/* ── Right Panel ── */}
          <div style={{
            flex: 1, display: "flex", flexDirection: "column",
            background: "var(--bg0)", overflow: "hidden",
          }}>
            {/* Tab bar */}
            <div style={{
              height: 42, flexShrink: 0,
              display: "flex", alignItems: "center", justifyContent: "space-between",
              padding: "0 8px 0 4px", background: "var(--bg1)",
              borderBottom: "1px solid var(--border)",
            }}>
              <div style={{ display: "flex", gap: 2 }}>
                {RIGHT_TABS.map(t => (
                  <button key={t.id} className={`tab-btn${rightTab === t.id ? " active" : ""}`}
                    onClick={() => setRightTab(t.id)}>
                    <span style={{ fontSize: 12 }}>{t.icon}</span>
                    {t.label}
                  </button>
                ))}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                {rightTab === "log" && (
                  <Dot active={runStatus === RUN_STATUS.RUNNING} pulse={runStatus === RUN_STATUS.RUNNING} />
                )}
                <button className="ghost-btn"
                  onClick={() => {
                    setLogs([]); setCurrentIter(0); setRunStatus(RUN_STATUS.IDLE);
                    setLossHistory([]); setChampionCode(""); setRightTab("log");
                  }}
                  style={{ fontSize: 11, padding: "4px 10px" }}>
                  Clear
                </button>
              </div>
            </div>

            {/* Log tab */}
            {rightTab === "log" && (
              <div style={{
                flex: 1, overflowY: "auto",
                padding: "18px 24px 18px 32px",
                textAlign: "left",
                display: "flex", flexDirection: "column",
                alignItems: "stretch",
              }}>
                {logs.length === 0 ? (
                  <div style={{
                    flex: 1, display: "flex", flexDirection: "column",
                    alignItems: "center", justifyContent: "center", gap: 14,
                    textAlign: "center",
                  }}>
                    <div style={{
                      width: 58, height: 58, borderRadius: 14,
                      background: "var(--bg2)", border: "1px solid var(--border2)",
                      display: "flex", alignItems: "center", justifyContent: "center",
                      fontSize: 24, boxShadow: "0 0 24px rgba(91,125,245,0.08)",
                      color: "var(--blue3)",
                    }}>⬡</div>
                    <div style={{
                      fontSize: 13, color: "var(--text1)",
                      fontFamily: "var(--font-display)", fontWeight: 600, letterSpacing: "0.02em",
                    }}>
                      Awaiting evolution loop
                    </div>
                    <div style={{
                      fontSize: 11, color: "var(--text2)",
                      fontFamily: "var(--font-mono)", letterSpacing: "0.05em",
                    }}>
                      Complete protocol → Launch
                    </div>
                  </div>
                ) : (
                  <div style={{ textAlign: "left", width: "100%" }}>
                    {logs.map((l, i) => <LogLine key={i} line={l} index={i} />)}
                    <div ref={logEndRef} />
                  </div>
                )}
              </div>
            )}

            {/* Champion tab */}
            {rightTab === "champion" && (
              <DiffView diff={diffLines} championCode={championCode} />
            )}
          </div>
        </div>
      </div>
    </>
  );
}