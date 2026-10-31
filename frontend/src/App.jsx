import { useCallback, useEffect, useMemo, useRef, useState } from "react";

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const text = await response.text();
  let body = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = { detail: text };
  }
  if (!response.ok) throw new Error(body?.detail || `request failed (${response.status})`);
  return body;
}

async function streamPost(path, body, onEvent) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const text = await response.text();
    let detail = text;
    try {
      detail = JSON.parse(text).detail || text;
    } catch {
      /* keep the raw text */
    }
    throw new Error(detail || `request failed (${response.status})`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() || "";
    for (const frame of frames) {
      const line = frame.trim();
      if (!line.startsWith("data:")) continue;
      try {
        onEvent(JSON.parse(line.slice(5).trim()));
      } catch {
        /* ignore malformed frame */
      }
    }
  }
}

const shortDate = (iso) => (iso ? iso.slice(0, 10) : "—");
const year = (iso) => (iso ? iso.slice(0, 4) : "—");

function ModelPicker({ models, model, onChange }) {
  if (models === null) return <span className="model-pill dim">detecting local models…</span>;
  if (!models.length) return <span className="model-pill dim">no local model</span>;
  return (
    <label className="model-pill">
      <span className="dot" />
      <select value={model} onChange={(event) => onChange(event.target.value)}>
        {models.map((entry) => (
          <option key={entry.name} value={entry.name}>
            {entry.name}
          </option>
        ))}
      </select>
    </label>
  );
}

function Landing({ repos, health, models, model, setModel, onImport, onSpecimen, busy, error, online }) {
  const [source, setSource] = useState("");
  return (
    <div className="landing">
      <header className="topbar">
        <div className="brand">THE LAST COMMIT</div>
        <div className="topbar-right">
          <ModelPicker models={models} model={model} onChange={setModel} />
          <span className={`net ${online ? "" : "off"}`}>{online ? "network available" : "offline · still haunted"}</span>
        </div>
      </header>

      <main className="landing-main">
        <section className="landing-left">
          <p className="eyebrow">a local archaeologist for abandoned repositories</p>
          <h1 className="wordmark">
            <span className="thin">THE LAST</span>
            <span className="fat">COMMIT</span>
          </h1>

          <pre className="glyph" aria-hidden="true">{`  ● 2017-03-04  init: prove the idea
  │
  ● 2017-11-02  NOTES: WAL and fork()
  │
  ● 2018-02-11  fix typo in --help output
  ·
  ·
  ·  3,184 days of silence`}</pre>

          <p className="lede">
            Import a repository that stopped talking. Its history is read on this machine,
            broken into memories, and given a voice. Every answer cites the commit, the TODO or
            the skipped test it came from.
          </p>

          <form
            className="import"
            onSubmit={(event) => {
              event.preventDefault();
              if (source.trim()) onImport(source.trim());
            }}
          >
            <span className="prompt">&gt;</span>
            <input
              value={source}
              onChange={(event) => setSource(event.target.value)}
              placeholder="/path/to/abandoned/repository   or   https://github.com/owner/repo"
              spellCheck={false}
              aria-label="repository path or URL"
            />
            <button type="submit" disabled={busy}>
              {busy ? "DIGGING…" : "OPEN THE GRAVE"}
            </button>
          </form>

          <div className="landing-actions">
            <button className="ghost-btn" onClick={onSpecimen} disabled={busy}>
              SUMMON THE SPECIMEN · sundial, 2017–2018
            </button>
          </div>

          {error ? <p className="error">{error}</p> : null}

          <p className="fineprint">
            {!health
              ? "checking the archive…"
              : health?.ollama?.ok
              ? `local inference ready · ${health.ollama.models.length} model${health.ollama.models.length === 1 ? "" : "s"} on this machine · nothing is uploaded`
              : "no model server detected · the archive can still answer from evidence alone"}
          </p>
        </section>

        <aside className="landing-right">
          <div className="panel-head">RECENT GRAVES</div>
          {repos.length ? (
            <div className="grave-list">
              {repos.map((entry) => (
                <button key={entry.id} className="grave-row" onClick={() => onImport(entry.id, true)}>
                  <span className="grave-name">{entry.name}</span>
                  <span className="grave-meta">
                    {entry.commit_count ?? "?"} commits · last {shortDate(entry.last_commit?.date)}
                  </span>
                  <span className="grave-silence">{entry.silence_days ?? "?"} days quiet</span>
                </button>
              ))}
            </div>
          ) : (
            <p className="dim small">no repositories read yet.</p>
          )}

          <div className="how">
            <div><b>1</b><span>read the history, without running it</span></div>
            <div><b>2</b><span>ask the ghost a question</span></div>
            <div><b>3</b><span>open the evidence behind each claim</span></div>
            <div><b>4</b><span>propose a revival, apply nothing</span></div>
          </div>
        </aside>
      </main>
    </div>
  );
}

function Timeline({ commits, silenceDays, onPick }) {
  const HISTORY_WIDTH = 68;
  const points = useMemo(() => {
    if (!commits.length) return [];
    const first = new Date(commits[0].date).getTime();
    const last = new Date(commits[commits.length - 1].date).getTime();
    const span = Math.max(last - first, 1);
    return commits.map((commit, index) => {
      const at = new Date(commit.date).getTime();
      const churn = (commit.insertions || 0) + (commit.deletions || 0);
      return {
        ...commit,
        left: 2 + ((at - first) / span) * (HISTORY_WIDTH - 2),
        height: Math.max(4, Math.min(26, 3 + Math.sqrt(churn) * 2.4)),
        last: index === commits.length - 1,
      };
    });
  }, [commits]);

  if (!points.length) return null;

  return (
    <div className="timeline">
      <div className="timeline-axis">
        {points.map((point) => (
          <button
            key={point.sha}
            className={`tick ${point.last ? "last" : ""}`}
            style={{ left: `${point.left}%`, height: `${point.height}px` }}
            title={`${shortDate(point.date)} · ${point.author} · ${point.subject}`}
            onClick={() => onPick(`commit:${point.sha.slice(0, 10)}`)}
            aria-label={point.subject}
          />
        ))}
        <span className="silence-band" style={{ left: `${HISTORY_WIDTH}%` }} />
        <span className="timeline-now" />
      </div>
      <div className="timeline-labels">
        <span>{year(points[0].date)}</span>
        <span className="dim">{points.length} commits</span>
        <span>{year(points[points.length - 1].date)}</span>
      </div>
      <div className="timeline-silence">
        {silenceDays.toLocaleString()} days of silence →
      </div>
    </div>
  );
}

function Grounding({ grounding }) {
  if (!grounding) return null;
  const unknown = grounding.unknown_citations?.length || 0;
  const tone = unknown ? "bad" : grounding.coverage >= 0.99 ? "good" : "warn";
  const detail = [
    `${grounding.cited_claims} of ${grounding.claims} sentences carry a citation.`,
    grounding.inference_markers
      ? `${grounding.inference_markers} interpretation${grounding.inference_markers === 1 ? " is" : "s are"} explicitly marked.`
      : null,
    grounding.uncited?.length ? `Uncited: ${grounding.uncited.join(" ")}` : null,
    unknown ? `Unknown ids: ${grounding.unknown_citations.join(", ")}` : null,
  ]
    .filter(Boolean)
    .join("\n");

  return (
    <div className={`grounding ${tone}`} title={detail}>
      <span className="pips">
        {Array.from({ length: Math.max(grounding.claims, 1) }).map((_, index) => (
          <i key={index} className={index < grounding.cited_claims ? "on" : ""} />
        ))}
      </span>
      <span className="grounding-text">
        {grounding.cited_claims}/{grounding.claims} claims cited
      </span>
      {unknown ? <span className="grounding-flag">unknown citation</span> : null}
      {!unknown && grounding.coverage < 0.99 ? <span className="grounding-flag soft">partial</span> : null}
    </div>
  );
}

function CitationText({ text, refs, onCite }) {
  const parts = text.split(/(\[(?:C\d+(?:\s*,\s*C\d+)*)\])/g);
  return (
    <>
      {parts.map((part, index) => {
        const match = /^\[((?:C\d+(?:\s*,\s*C\d+)*))\]$/.exec(part);
        if (!match) return <span key={index}>{part}</span>;
        const ids = match[1].split(/[,\s]+/).filter(Boolean);
        return (
          <span key={index} className="cite-group">
            {ids.map((id) => {
              const ref = refs?.find((entry) => entry.ref === id);
              return (
                <button
                  key={id}
                  className={`cite ${ref ? "" : "unknown"}`}
                  title={ref ? ref.title : "this id was not in the ledger"}
                  onClick={() => ref && onCite(ref)}
                >
                  {id}
                </button>
              );
            })}
          </span>
        );
      })}
    </>
  );
}

function KindBadge({ kind }) {
  return <span className={`kind kind-${kind}`}>{kind}</span>;
}

function EvidenceCard({ entry, onOpen, dense }) {
  return (
    <button className={`evidence-card ${dense ? "dense" : ""}`} onClick={() => onOpen(entry)}>
      <div className="evidence-top">
        <span className="ref">{entry.ref || entry.kind}</span>
        <KindBadge kind={entry.kind} />
        {entry.anchored ? <span className="anchor">anchor</span> : null}
      </div>
      <div className="evidence-title">{entry.title}</div>
      <div className="evidence-meta">
        {entry.date ? shortDate(entry.date) : null}
        {entry.author ? ` · ${entry.author}` : null}
        {entry.path ? ` · ${entry.path}` : null}
      </div>
      {!dense && entry.preview ? <p className="evidence-preview">{entry.preview}</p> : null}
    </button>
  );
}

function ChunkModal({ repoId, chunkId, onClose }) {
  const [chunk, setChunk] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    setChunk(null);
    api(`/api/repos/${repoId}/chunk?id=${encodeURIComponent(chunkId)}`)
      .then((data) => alive && setChunk(data))
      .catch((err) => alive && setError(err.message));
    return () => {
      alive = false;
    };
  }, [repoId, chunkId]);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(event) => event.stopPropagation()}>
        <div className="modal-head">
          <div>
            <div className="modal-kicker">{chunk ? chunk.kind : "memory"}</div>
            <h3>{chunk ? chunk.title : "reading the archive…"}</h3>
          </div>
          <button className="close" onClick={onClose} aria-label="close">×</button>
        </div>
        {error ? <p className="error">{error}</p> : null}
        {chunk ? (
          <>
            <div className="modal-meta">
              {chunk.date ? <span>{shortDate(chunk.date)}</span> : null}
              {chunk.author ? <span>{chunk.author}</span> : null}
              {chunk.path ? <span>{chunk.path}</span> : null}
              {chunk.commit_sha ? <span className="mono">{chunk.commit_sha.slice(0, 10)}</span> : null}
            </div>
            <pre className="modal-body">{chunk.text}</pre>
            <p className="fineprint">verbatim from the repository · read only</p>
          </>
        ) : null}
      </div>
    </div>
  );
}

function Prompt({ repo, model, onCite, onEvidence }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const bottom = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    setMessages([
      {
        role: "assistant",
        content: repo.welcome,
        refs: [],
        grounding: null,
        welcome: true,
      },
    ]);
  }, [repo.id, repo.welcome]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  const send = useCallback(
    async (question) => {
      if (!question.trim() || busy) return;
      setBusy(true);
      setInput("");
      const history = messages
        .filter((message) => !message.welcome && message.content)
        .slice(-6)
        .map((message) => ({ role: message.role, content: message.content }));

      setMessages((current) => [
        ...current,
        { role: "user", content: question },
        { role: "assistant", content: "", pending: true, refs: [], grounding: null },
      ]);

      const patchLast = (patch) =>
        setMessages((current) => {
          const next = [...current];
          next[next.length - 1] = { ...next[next.length - 1], ...patch };
          return next;
        });

      try {
        await streamPost(
          `/api/repos/${repo.id}/chat`,
          { message: question, history, model: model || undefined },
          (event) => {
            if (event.type === "meta") {
              patchLast({ refs: event.evidence, model: event.model });
              onEvidence?.(event.evidence);
            }
            if (event.type === "token") {
              setMessages((current) => {
                const next = [...current];
                const last = next[next.length - 1];
                next[next.length - 1] = { ...last, content: (last.content || "") + event.text };
                return next;
              });
            }
            if (event.type === "notice") patchLast({ notice: event.text });
            if (event.type === "done") {
              patchLast({
                grounding: event.grounding,
                refs: event.refs || [],
                pending: false,
                model: event.model,
              });
              if (event.refs?.length) onEvidence?.(event.refs);
            }
            if (event.type === "error") patchLast({ pending: false, error: event.text });
          }
        );
      } catch (err) {
        patchLast({ pending: false, error: err.message });
      } finally {
        setBusy(false);
        inputRef.current?.focus();
      }
    },
    [busy, messages, model, onEvidence, repo.id]
  );

  const suggestions = [
    "Why were you abandoned?",
    "What is still unfinished?",
    "Where did it begin?",
    "Tell me about the storage code.",
  ];

  return (
    <section className="seance">
      <div className="panel-head">
        SÉANCE
        <span className="panel-sub">{repo.memory_count} memories indexed</span>
      </div>

      <div className="messages">
        {messages.map((message, index) => (
          <article key={index} className={`msg ${message.role} ${message.pending ? "pending" : ""}`}>
            <div className="msg-head">
              <span className="who">{message.role === "user" ? "you" : repo.name}</span>
              {message.role === "assistant" && (message.model || message.welcome) ? (
                <span className="model-tag">{message.welcome ? "archive" : message.model}</span>
              ) : null}
            </div>
            <div className="msg-body">
              {message.content ? (
                <CitationText text={message.content} refs={message.refs} onCite={onCite} />
              ) : (
                <span className="thinking">listening for the archive<span className="ellipsis" /></span>
              )}
              {message.pending && message.content ? <span className="caret" /> : null}
            </div>
            {message.notice ? <p className="notice">{message.notice}</p> : null}
            {message.error ? <p className="error">{message.error}</p> : null}
            {message.grounding ? <Grounding grounding={message.grounding} /> : null}
            {message.role === "assistant" && message.refs?.length ? (
              <div className="msg-refs">
                {message.refs.slice(0, 6).map((ref) => (
                  <button key={ref.ref} className="ref-chip" onClick={() => onCite(ref)} title={ref.title}>
                    {ref.ref}
                  </button>
                ))}
              </div>
            ) : null}
          </article>
        ))}
        <div ref={bottom} />
      </div>

      {messages.length <= 1 ? (
        <div className="suggestions">
          {suggestions.map((suggestion) => (
            <button key={suggestion} onClick={() => send(suggestion)} disabled={busy}>
              {suggestion}
            </button>
          ))}
        </div>
      ) : null}

      <form
        className="composer"
        onSubmit={(event) => {
          event.preventDefault();
          send(input);
        }}
      >
        <span className="prompt">&gt;</span>
        <textarea
          ref={inputRef}
          value={input}
          rows={1}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              send(input);
            }
          }}
          placeholder="ask the repository what happened…"
          aria-label="your question"
        />
        <button type="submit" disabled={busy || !input.trim()}>
          {busy ? "…" : "ASK"}
        </button>
      </form>
    </section>
  );
}

function Diff({ text }) {
  return (
    <pre className="diff">
      {text.split("\n").map((line, index) => {
        let tone = "";
        if (line.startsWith("+") && !line.startsWith("+++")) tone = "add";
        else if (line.startsWith("-") && !line.startsWith("---")) tone = "del";
        else if (line.startsWith("@@")) tone = "hunk";
        else if (line.startsWith("+++") || line.startsWith("---")) tone = "file";
        return (
          <div key={index} className={tone}>
            {line || " "}
          </div>
        );
      })}
    </pre>
  );
}

function Resurrection({ repo, model, onCite }) {
  const [plan, setPlan] = useState(null);
  const [stage, setStage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [patch, setPatch] = useState(null);

  const begin = async () => {
    setBusy(true);
    setError("");
    setPlan(null);
    setStage("opening the excavation");
    try {
      await streamPost(`/api/repos/${repo.id}/revive`, { model: model || undefined }, (event) => {
        if (event.type === "stage") setStage(event.text);
        if (event.type === "roadmap") {
          setPlan(event.plan);
          setStage("");
        }
        if (event.type === "error") setError(event.text);
      });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
      setStage("");
    }
  };

  const propose = async (todo) => {
    setPatch({ loading: true, path: todo.path });
    try {
      const result = await api(`/api/repos/${repo.id}/patch`, {
        method: "POST",
        body: JSON.stringify({
          chunk_id: `todo:${todo.path}:${todo.line}`,
          model: model || undefined,
        }),
      });
      setPatch({ ...result, todo });
    } catch (err) {
      setPatch({ ok: false, reason: err.message, todo });
    }
  };

  return (
    <div className="resurrection">
      <div className="resurrect-head">
        <p className="dim small">
          The dead do not come back by themselves. This reads what is unfinished and proposes an order of work.
          It never writes to the repository.
        </p>
        <button className="ghost-btn" onClick={begin} disabled={busy}>
          {busy ? "EXHUMING…" : plan ? "READ AGAIN" : "BEGIN THE EXCAVATION"}
        </button>
      </div>

      {stage ? <p className="stage">{stage}<span className="ellipsis" /></p> : null}
      {error ? <p className="error">{error}</p> : null}

      {plan ? (
        <div className={`plan plan-${plan.readiness?.replace(/\s+/g, "-")}`}>
          <div className="plan-top">
            <span className="readiness">{plan.readiness}</span>
            <span className="score">{plan.score}<i>/100</i></span>
            <span className="plan-source">{plan.source === "model" ? "model" : "heuristic"}</span>
          </div>
          <p className="verdict">“{plan.verdict}”</p>
          {plan.note ? <p className="notice">{plan.note}</p> : null}

          <ol className="steps">
            {(plan.steps || []).map((step, index) => (
              <li key={index}>
                <div className="step-head">
                  <span className="step-n">{String(index + 1).padStart(2, "0")}</span>
                  <h4>{step.title}</h4>
                  <span className="effort">{step.effort}</span>
                </div>
                <p>{step.why}</p>
                {step.first_action ? <code className="first">{step.first_action}</code> : null}
                {step.evidence?.length ? (
                  <div className="step-refs">
                    {step.evidence.map((ref) => {
                      const entry = (plan.refs || []).find((item) => item.ref === ref);
                      if (!entry) return <span key={ref} className="ref-chip">{ref}</span>;
                      return (
                        <button key={ref} className="ref-chip" onClick={() => onCite(entry)} title={entry.title}>
                          {ref} · {entry.kind}
                        </button>
                      );
                    })}
                  </div>
                ) : null}
              </li>
            ))}
          </ol>

          <div className="plan-columns">
            <div>
              <div className="mini-head">RISKS</div>
              <ul>{(plan.risks || []).map((risk, index) => <li key={index}>{risk}</li>)}</ul>
            </div>
            <div>
              <div className="mini-head">KEEP</div>
              <ul>{(plan.keep || []).map((item, index) => <li key={index}>{item}</li>)}</ul>
            </div>
          </div>
        </div>
      ) : null}

      {repo.todos?.length ? (
        <div className="patches">
          <div className="mini-head">PROPOSE A PATCH · NOTHING IS APPLIED</div>
          {repo.todos.map((todo) => (
            <div className="todo-row" key={`${todo.path}:${todo.line}`}>
              <div className="todo-main">
                <span className="todo-keyword">{todo.keyword}</span>
                <code>{todo.path}:{todo.line}</code>
                <p>{todo.text}</p>
              </div>
              <button
                className="ghost-btn tiny"
                disabled={patch?.loading}
                onClick={() => propose(todo)}
              >
                {patch?.loading && patch.path === todo.path ? "THINKING…" : "PROPOSE"}
              </button>
            </div>
          ))}
        </div>
      ) : null}

      {patch && !patch.loading ? (
        <div className="patch">
          <div className="patch-head">
            <span className={`patch-verdict ${patch.applies ? "ok" : "no"}`}>
              {patch.ok
                ? patch.applies
                  ? "git apply --check: accepts"
                  : "git apply --check: rejects"
                : "no patch"}
            </span>
            <span className="dim small">{patch.reason}</span>
          </div>
          {patch.diff ? <Diff text={patch.diff} /> : null}
          <p className="fineprint">
            {patch.note || "Nothing was written to disk."} The diff is shown as a
            proposal, not a change. A diff that applies is not automatically correct;
            a human still has to read it.
          </p>
        </div>
      ) : null}
    </div>
  );
}

function Grave({ repo, models, model, setModel, onBack, online }) {
  const [tab, setTab] = useState("evidence");
  const [refs, setRefs] = useState([]);
  const [modal, setModal] = useState(null);

  const openRef = useCallback((entry) => setModal(entry.id), []);
  const openChunk = useCallback((chunkId) => setModal(chunkId), []);
  const trackRefs = useCallback((nextRefs) => setRefs(nextRefs), []);

  const last = repo.last_commit;
  const first = repo.first_commit;

  return (
    <div className="grave">
      <header className="grave-head">
        <button className="back" onClick={onBack}>← another grave</button>
        <div className="grave-ident">
          <h2>{repo.name}</h2>
          <p>
            {year(first?.date)} — {year(last?.date)} · {repo.commit_count} commits · {repo.authors?.length} authors
            <span className="sep">/</span>
            <span className="silent">{repo.silence_days} days of silence</span>
          </p>
        </div>
        <div className="grave-tools">
          <ModelPicker models={models} model={model} onChange={setModel} />
          <span className={`net ${online ? "" : "off"}`}>{online ? "online" : "offline · working"}</span>
        </div>
      </header>

      <main className="grave-grid">
        <aside className="left">
          <div className="panel">
            <div className="panel-head">THE REMAINS</div>
            <Timeline commits={repo.commits} silenceDays={repo.silence_days} onPick={openChunk} />
            <dl className="facts">
              <div><dt>born</dt><dd>{shortDate(first?.date)}</dd></div>
              <div><dt>last commit</dt><dd>{shortDate(last?.date)}</dd></div>
              <div className="wide"><dt>last words</dt><dd className="quote">“{last?.subject}”</dd></div>
              <div><dt>files</dt><dd>{repo.file_count}</dd></div>
              <div><dt>unmerged</dt><dd>{repo.branches?.length || 0}</dd></div>
            </dl>
          </div>

          <div className="panel">
            <div className="panel-head">SIGNALS</div>
            <ul className="signals">
              {(repo.signals || []).map((signal, index) => (
                <li key={index} className={signal.tone}>
                  <span className="signal-label">{signal.label}</span>
                  <span className="signal-detail">{signal.detail}</span>
                </li>
              ))}
            </ul>
          </div>

          <div className="panel">
            <div className="panel-head">AUTHORS</div>
            <ul className="authors">
              {(repo.authors || []).map((author) => (
                <li key={author.name}>
                  <span>{author.name}</span>
                  <span className="dim">{author.commits}</span>
                </li>
              ))}
            </ul>
          </div>
        </aside>

        <Prompt repo={repo} model={model} onCite={openRef} onEvidence={trackRefs} />

        <aside className="right">
          <div className="tabs">
            <button className={tab === "evidence" ? "on" : ""} onClick={() => setTab("evidence")}>
              EVIDENCE
            </button>
            <button className={tab === "resurrection" ? "on" : ""} onClick={() => setTab("resurrection")}>
              RESURRECTION
            </button>
          </div>

          {tab === "evidence" ? (
            <div className="ledger">
              <p className="dim small">
                Every citation in the conversation resolves to one of these. Open one to read the
                commit or file it came from.
              </p>
              {refs.length ? (
                refs.map((entry) => <EvidenceCard key={entry.ref} entry={entry} onOpen={openRef} />)
              ) : (
                <p className="dim small">the ledger fills after the first answer.</p>
              )}
            </div>
          ) : (
            <Resurrection repo={repo} model={model} onCite={openRef} />
          )}
        </aside>
      </main>

      {modal ? <ChunkModal repoId={repo.id} chunkId={modal} onClose={() => setModal(null)} /> : null}
    </div>
  );
}

export default function App() {
  const [repo, setRepo] = useState(null);
  const [repos, setRepos] = useState([]);
  const [health, setHealth] = useState(null);
  const [models, setModels] = useState(null);
  const [model, setModel] = useState(() => localStorage.getItem("ghost-model") || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [online, setOnline] = useState(navigator.onLine);

  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);

  const loadModels = useCallback(async () => {
    try {
      const data = await api("/api/models");
      setModels(data.models || []);
      setModel((current) => {
        const preferred = current || localStorage.getItem("ghost-model");
        if (preferred && (data.models || []).some((entry) => entry.name === preferred)) return preferred;
        const fallback = data.models?.find((entry) => entry.name === data.default) || data.models?.[0];
        return fallback?.name || "";
      });
    } catch {
      setModels([]);
    }
  }, []);

  const loadRepos = useCallback(async () => {
    try {
      const data = await api("/api/repos");
      setRepos(data.repos || []);
    } catch {
      setRepos([]);
    }
  }, []);

  useEffect(() => {
    api("/api/health").then(setHealth).catch(() => setHealth(null));
    loadModels();
    loadRepos();
  }, [loadModels, loadRepos]);

  useEffect(() => {
    if (model) localStorage.setItem("ghost-model", model);
  }, [model]);

  const open = async (value, existingId = false) => {
    setBusy(true);
    setError("");
    try {
      const data = existingId
        ? await api(`/api/repos/${value}`)
        : await api("/api/repos", {
            method: "POST",
            body: JSON.stringify(
              /^https?:\/\//.test(value) ? { url: value } : { path: value }
            ),
          });
      setRepo(data);
      loadRepos();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const specimen = async () => {
    setBusy(true);
    setError("");
    try {
      const data = await api("/api/specimen", { method: "POST", body: "{}" });
      setRepo(data);
      loadRepos();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="crt" aria-hidden="true" />
      <div className="vignette" aria-hidden="true" />
      {repo ? (
        <Grave
          repo={repo}
          models={models}
          model={model}
          setModel={setModel}
          online={online}
          onBack={() => {
            setRepo(null);
            loadRepos();
          }}
        />
      ) : (
        <Landing
          repos={repos}
          health={health}
          models={models}
          model={model}
          setModel={setModel}
          onImport={open}
          onSpecimen={specimen}
          busy={busy}
          error={error}
          online={online}
        />
      )}
    </>
  );
}
