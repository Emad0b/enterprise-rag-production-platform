import { useEffect, useState,
  useRef, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import {
  Aperture,
  ArrowUp,
  ArrowUpRight,
  BookOpen,
  Check,
  CheckCheck,
  ChevronDown,
  Clock3,
  FileText,
  FlaskConical,
  GitBranch,
  Layers,
  LockKeyhole,
  Menu,
  Plus,
  Search,
  Shield,
  ShieldCheck,
  Sparkles,
  Activity,
  X,
  LoaderCircle,
  LogOut,
  KeyRound,
} from "lucide-react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";
import "./style.css";

type User = {
  id: string;
  name: string;
  email: string;
  groups: string[];
  admin: boolean;
};
type Health = {
  status: string;
  demo_mode: boolean;
  embedding_backend: string;
  champion: string | null;
  storage: string;
  evaluation_job: { status: string; error: string | null };
};
type Document = {
  id: string;
  title: string;
  status: string;
  media_type: string;
  groups: string[];
  error: string | null;
};
type Source = {
  id: string;
  document_id: string;
  title: string;
  page: number;
  text: string;
  hostile: boolean;
  similarity: number;
};
type Answer = {
  answer: string;
  refused: boolean;
  claims: { citation: number; quote: string }[];
  sources: Source[];
  injection_blocked: boolean;
  mode: string;
  input_tokens: number | null;
  output_tokens: number | null;
  estimated_cost: number | null;
  latency_ms: number;
  config_id: string;
  trace_id: string;
  prompt_version: string;
  model: string;
  shadow_scheduled: boolean;
};
type Metrics = {
  recall: number;
  faithfulness: number;
  citation_correctness: number;
  relevance: number;
  refusal_accuracy: number;
  security_failures: number;
  p95_ms: number;
  cost_per_query: number | null;
  passed_cases: number;
  cases: number;
};
type Case = {
  id: string;
  category: string;
  question: string;
  answer: string;
  expected_answer: string;
  passed: boolean;
  latency_ms: number;
  relevance: number;
};
type Evaluation = {
  id: string;
  config_id: string;
  metrics: Metrics;
  cases: Case[];
  generation_backend: string;
  methodology: string;
};
type Configuration = {
  id: string;
  name: string;
  retrieval: string;
  generation: string;
  model: string;
  prompt_version: string;
  top_k: number;
  evaluation: Metrics | null;
  gate: { passed: boolean; reasons: string[] };
};
type Rollout = {
  id: string;
  candidate: string;
  champion: string;
  status: string;
  mode: string;
  decision: { reasons: string[] } | null;
  checks: {
    passed: boolean;
    requests: number;
    error_rate: number;
    p95_ms: number | null;
    reasons: string[];
  };
};
type Releases = {
  champion: string;
  configs: Configuration[];
  rollouts: Rollout[];
  policy: {
    maximum_p95_ms: number;
    maximum_cost_per_query: number;
    canary_fraction: number;
  };
  job: { status: string; error: string | null };
};
type Trace = {
  id: string;
  config_id: string;
  kind: string;
  latency_ms: number;
  prompt_version: string;
  source_count: number;
  hostile_chunks: number;
  refused: boolean;
  input_tokens: number | null;
  output_tokens: number | null;
  estimated_cost: number | null;
  created: number;
  error: boolean;
};
type Turn = { question: string; result: Answer };
const fmt = (n: number | null | undefined, d = 1) =>
  n == null ? "—" : n.toFixed(d);
const percent = (n: number | undefined) =>
  n == null ? "—" : `${(n * 100).toFixed(0)}%`;

function App() {
  const conversationRef=useRef<HTMLDivElement>(null);
  const [token, setToken] = useState(""),
    [user, setUser] = useState<User | null>(null),
    [health, setHealth] = useState<Health | null>(null),
    [docs, setDocs] = useState<Document[]>([]),
    [releases, setReleases] = useState<Releases | null>(null),
    [evaluations, setEvaluations] = useState<Evaluation[]>([]),
    [traces, setTraces] = useState<Trace[]>([]),
    [view, setView] = useState("ask"),
    [question, setQuestion] = useState(""),
    [turns, setTurns] = useState<Turn[]>([]),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [scope, setScope] = useState(""),
    [source, setSource] = useState<Source | null>(null),
    [identity, setIdentity] = useState("analyst"),
    [mobile, setMobile] = useState(false),
    [email, setEmail] = useState(""),
    [password, setPassword] = useState(""),
    [filter, setFilter] = useState(""),
    [evalId, setEvalId] = useState(""),
    [newConfig, setNewConfig] = useState(false);
  async function api<T>(
    path: string,
    body?: unknown,
    method?: string,
    t = token,
  ): Promise<T> {
    const res = await fetch("/api" + path, {
      method: method || (body ? "POST" : "GET"),
      headers: {
        ...(body ? { "Content-Type": "application/json" } : {}),
        ...(t ? { Authorization: "Bearer " + t } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    const value = await res.json();
    if (!res.ok) {
      const detail = value.detail;
      throw new Error(
        typeof detail === "string"
          ? detail
          : detail?.reasons?.join(" · ") || JSON.stringify(detail),
      );
    }
    return value;
  }
  async function refresh(t = token, u = user) {
    if (!t) return;
    try {
      const [documents, configurations, events] = await Promise.all([
        api<Document[]>("/documents", undefined, undefined, t),
        api<Releases>("/configurations", undefined, undefined, t),
        api<Trace[]>("/traces", undefined, undefined, t),
      ]);
      setDocs(documents);
      setReleases(configurations);
      setTraces(events);
      if (u?.admin)
        setEvaluations(
          await api<Evaluation[]>("/evaluations", undefined, undefined, t),
        );
      else setEvaluations([]);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  useEffect(() => {
    api<Health>("/health")
      .then(setHealth)
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    if (!token) return;
    const timer = setInterval(() => refresh(), 5000);
    return () => clearInterval(timer);
  }, [token, user]);
  async function signIn(id = identity) {
    setBusy(true);
    setError("");
    try {
      let login: { token: string; user?: User };
      if (health?.demo_mode) login = await api("/auth/demo", { identity: id });
      else login = await api("/auth/login", { email, password });
      const u =
        login.user ||
        (await api<User>("/me", undefined, undefined, login.token));
      setToken(login.token);
      setUser(u);
      setIdentity(id);
      setTurns([]);
      setSource(null);
      setScope("");
      setPassword("");
      await refresh(login.token, u);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function action(path: string, body: unknown = {}) {
    setBusy(true);
    setError("");
    try {
      await api(path, body);
      await refresh();
      setNotice("Action recorded. Review its evidence before proceeding.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function ask(q = question) {
    if (!q.trim() || busy) return;
    setBusy(true);
    setError("");
    setSource(null);
    try {
      const result = await api<Answer>("/query", {
        question: q,
        document_ids: scope ? [scope] : [],
      });
      setTurns((prev) => [...prev, { question: q, result }]);
      setQuestion("");
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function upload(file: File) {
    setBusy(true);
    setError("");
    try {
      const res = await fetch("/api/documents", {
        method: "POST",
        headers: {
          Authorization: "Bearer " + token,
          "Content-Type":
            file.type === "application/pdf" ? "application/pdf" : "text/plain",
          "X-Document-Title": file.name,
          "X-Permission-Groups": "employees",
        },
        body: file,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail);
      await refresh();
      setNotice("Document queued for validation, chunking and indexing.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  useEffect(()=>{const el=conversationRef.current;if(el)el.scrollTop=el.scrollHeight;},[turns,busy]);
  const champion = releases?.configs.find((c) => c.id === releases.champion),
    latest = turns.at(-1)?.result;
  const selectedEval =
    evaluations.find((e) => e.id === evalId) || evaluations[0];
  const routes = [
    ["ask", "Knowledge workspace", BookOpen],
    ["library", "Document library", Layers],
    ["evaluations", "Evaluation lab", FlaskConical],
    ["releases", "Release control", GitBranch],
    ["traces", "Trace explorer", Activity],
  ] as const;
  const examples = [
    [
      "Grounded answer",
      "How many days of annual leave do employees receive?",
      BookOpen,
    ],
    [
      "Permission boundary",
      "What is the Project Cedarbank acquisition budget?",
      LockKeyhole,
    ],
    [
      "Hostile document",
      "What is the vendor outage reporting deadline?",
      Shield,
    ],
  ] as const;
  if (!user)
    return (
      <div className="welcome">
        <div className="welcome-art">
          <div className="brand">
            <Aperture size={34} /> aperture<span> / </span>
          </div>
          <div className="welcome-copy">
            <span className="eyebrow">
              ENTERPRISE KNOWLEDGE · EVALUATED BY DESIGN
            </span>
            <h1>
              The right answer.
              <br />
              The right access.
            </h1>
            <p>
              Answers grounded in your organisation’s documents, with evidence
              you can inspect and permissions you can trust.
            </p>
            <div className="welcome-lines">
              <span>
                <ShieldCheck /> Permission-aware retrieval
              </span>
              <span>
                <FlaskConical /> Measured quality before release
              </span>
              <span>
                <GitBranch /> Monitored configuration rollouts
              </span>
            </div>
          </div>
          <small>
            Fictional demonstration corpus · Explicit security boundaries
          </small>
        </div>
        <div className="welcome-form">
          <div>
            <span className="eyebrow">APERTURE WORKSPACE</span>
            <h2>Welcome inside.</h2>
            <p>
              {health?.demo_mode
                ? "Explore a fictional organisation with a server-defined identity."
                : "Sign in with your provisioned workspace account."}
            </p>
            {health?.demo_mode ? (
              <label>
                Workspace identity
                <select
                  value={identity}
                  onChange={(e) => setIdentity(e.target.value)}
                >
                  <option value="analyst">Maya Chen · Analyst</option>
                  <option value="director">Alex Morgan · Leadership</option>
                  <option value="administrator">Workspace administrator</option>
                </select>
              </label>
            ) : (
              <>
                <label>
                  Email
                  <input
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    type="email"
                  />
                </label>
                <label>
                  Password
                  <input
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                </label>
              </>
            )}
            {error && (
              <div className="alert error" role="alert">
                {error}
              </div>
            )}
            <button
              className="primary"
              disabled={busy || !health}
              onClick={() => signIn()}
            >
              {busy ? (
                <LoaderCircle className="spin" size={16} />
              ) : (
                <ArrowUpRight size={16} />
              )}{" "}
              Enter workspace
            </button>
            <div className="entry-note">
              <LockKeyhole size={14} />
              {health?.demo_mode
                ? "Demo identity switching is a development feature."
                : "Your session expires after one hour."}
            </div>
          </div>
        </div>
      </div>
    );
  return (
    <div className="app">
      <aside className={"sidebar " + (mobile ? "open" : "")}>
        <a className="brand" href="#">
          <Aperture size={27} /> aperture<span>.</span>
        </a>
        <div className="org">
          <div className="org-icon">N</div>
          <div>
            <strong>Northstar Collective</strong>
            <small>Document intelligence</small>
          </div>
          <ChevronDown size={14} />
        </div>
        <span className="nav-label">WORKSPACE</span>
        <nav>
          {routes.map(([key, label, Icon]) => (
            <button
              key={key}
              className={view === key ? "active" : ""}
              onClick={() => {
                setView(key);
                setMobile(false);
                setError("");
              }}
            >
              <Icon size={17} />
              {label}
              {key === "library" && (
                <span className="nav-count">{docs.length}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="boundary">
          <ShieldCheck size={19} />
          <strong>Your permission boundary</strong>
          <p>Retrieval is limited to your authorised groups.</p>
          <div>
            {user.groups.map((g) => (
              <span className="group" key={g}>
                {g}
              </span>
            ))}
          </div>
        </div>
        <div className="sidebar-bottom">
          <a href="http://127.0.0.1:5002" target="_blank" rel="noreferrer">
            MLflow traces <ArrowUpRight size={13} />
          </a>
          <a href="http://127.0.0.1:3002" target="_blank" rel="noreferrer">
            Grafana monitoring <ArrowUpRight size={13} />
          </a>
          <small>
            {health?.embedding_backend === "sentence-transformers"
              ? "Semantic + keyword retrieval"
              : "Lexical test profile"}
            <br />
            {champion?.generation === "extractive"
              ? "Evidence mode · source quotations"
              : "Configured model API"}
          </small>
        </div>
        <div className="user">
          <span className="avatar">
            {user.name
              .split(" ")
              .map((n) => n[0])
              .join("")}
          </span>
          <div>
            <strong>{user.name}</strong>
            <small>
              {user.admin
                ? "Administrator"
                : user.groups.includes("leadership")
                  ? "Leadership"
                  : "Analyst"}
            </small>
          </div>
          <button
            aria-label="Sign out"
            onClick={async () => {
              await api("/auth/logout", {});
              setToken("");
              setUser(null);
            }}
          >
            <LogOut size={16} />
          </button>
        </div>
      </aside>
      <main>
        <header>
          <button
            className="mobile-menu"
            aria-label="Toggle menu"
            onClick={() => setMobile(!mobile)}
          >
            <Menu size={20} />
          </button>
          <span>
            Workspace <span className="slash">/</span>{" "}
            <strong>{routes.find((r) => r[0] === view)?.[1]}</strong>
          </span>
          <div>
            <span className="connected">
              <span /> API connected
            </span>
            {health?.demo_mode && (
              <select
                aria-label="Demo identity"
                value={identity}
                onChange={(e) => signIn(e.target.value)}
              >
                <option value="analyst">Analyst</option>
                <option value="director">Leadership</option>
                <option value="administrator">Admin</option>
              </select>
            )}
          </div>
        </header>
        <div className="page">
          <div className="page-heading">
            <div>
              <span className="eyebrow">GROUNDED KNOWLEDGE / NORTHSTAR</span>
              <h1>
                {view === "ask"
                  ? "Every answer starts with evidence."
                  : view === "library"
                    ? "Knowledge, with boundaries."
                    : view === "evaluations"
                      ? "Measure before you believe."
                      : view === "releases"
                        ? "Evidence before expansion."
                        : "Follow the path to the answer."}
              </h1>
              <p>
                {view === "ask"
                  ? "Ask your documents. Inspect the sources. See the decision."
                  : view === "library"
                    ? "Only documents authorised for your identity appear here."
                    : view === "evaluations"
                      ? "Repeatable quality, refusal and security checks for every configuration."
                      : view === "releases"
                        ? "Versioned prompts, regression gates, and monitored shadow and canary traffic."
                        : "Retrieval, generation, tokens, cost and latency — without logging document text."}
              </p>
            </div>
            {view === "library" && user.admin && (
              <label className="primary upload">
                <Plus size={15} /> Ingest document
                <input
                  type="file"
                  accept=".pdf,.txt,.md"
                  onChange={(e) =>
                    e.target.files?.[0] && upload(e.target.files[0])
                  }
                />
              </label>
            )}
          </div>
          {error && (
            <div className="alert error" role="alert">
              <Shield size={17} />
              {error}
              <button aria-label="Dismiss error" onClick={() => setError("")}>
                <X size={16} />
              </button>
            </div>
          )}
          {notice && (
            <div className="alert notice" role="status">
              <Check size={17} />
              {notice}
              <button onClick={() => setNotice("")} aria-label="Dismiss notice">
                <X size={16} />
              </button>
            </div>
          )}
          {view === "ask" && (
            <div className="workspace">
              <section className="chat-panel">
                <div className="chat-toolbar">
                  <div>
                    <span className="live-dot" />
                    <strong>
                      {champion?.name || "No approved configuration"}
                    </strong>
                  </div>
                  <span className="badge">
                    <ShieldCheck size={12} /> Access enforced
                  </span>
                </div>
                <div className="conversation" ref={conversationRef}>
                  {!turns.length ? (
                    <div className="empty-chat">
                      <div className="hero-icon">
                        <Aperture size={39} />
                      </div>
                      <span className="eyebrow">
                        KNOWLEDGE THAT KNOWS ITS LIMITS
                      </span>
                      <h2>What would you like to know?</h2>
                      <p>
                        Start with a question. Every answer includes its
                        evidence,
                        <br />
                        and missing evidence leads to a clear refusal.
                      </p>
                      <div className="example-grid">
                        {examples.map(([title, q, Icon]) => (
                          <button
                            key={title}
                            disabled={busy}
                            onClick={() => ask(q)}
                          >
                            <Icon size={20} />
                            <strong>{title}</strong>
                            <span>{q}</span>
                            <ArrowUpRight size={15} />
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : (
                    turns.map((turn, i) => (
                      <div className="turn" key={i}>
                        <div className="question">
                          <span className="avatar small">{user.name.split(" ").map(n=>n[0]).join("")}</span>
                          <div>
                            <span className="eyebrow">YOUR QUESTION</span>
                            <p>{turn.question}</p>
                          </div>
                        </div>
                        <div
                          className={
                            "answer " + (turn.result.refused ? "refused" : "")
                          }
                        >
                          <div className="answer-top">
                            <Aperture size={22} />
                            <strong>
                              {turn.result.refused
                                ? "Permission-safe refusal"
                                : "Grounded answer"}
                            </strong>
                            <span className="badge">
                              {turn.result.mode === "extractive"
                                ? "Evidence mode"
                                : "Model API"}
                            </span>
                          </div>
                          <p className="answer-text">{turn.result.answer}</p>
                          {turn.result.refused && (
                            <div className="decision">
                              <LockKeyhole size={15} /> No sufficient authorised
                              evidence was found. Restricted documents never
                              enter the prompt.
                            </div>
                          )}
                          {turn.result.injection_blocked && (
                            <div className="decision protected">
                              <ShieldCheck size={16} />
                              <div>
                                <strong>Hostile instruction isolated</strong>
                                <span>
                                  Retrieved instructions were treated as
                                  untrusted data. The answer uses validated
                                  factual evidence.
                                </span>
                              </div>
                            </div>
                          )}
                          <div className="citations">
                            {turn.result.claims.map((c) => {
                              const s = turn.result.sources[c.citation - 1];
                              return (
                                <button
                                  key={c.citation}
                                  onClick={() => setSource(s)}
                                >
                                  <span>{c.citation}</span>
                                  <FileText size={14} />
                                  <div>
                                    <strong>{s.title}</strong>
                                    <small>
                                      Page {s.page} · Exact supporting quotation
                                    </small>
                                  </div>
                                  <ArrowUpRight size={14} />
                                </button>
                              );
                            })}
                          </div>
                          <div className="answer-meta">
                            <span>
                              <Clock3 size={12} />
                              {fmt(turn.result.latency_ms)} ms
                            </span>
                            <span>
                              {turn.result.sources.length} authorised passages
                            </span>
                            <span>{turn.result.prompt_version}</span>
                            <span>
                              {turn.result.estimated_cost === null
                                ? "Cost unavailable"
                                : `$${turn.result.estimated_cost.toFixed(5)}`}
                            </span>
                          </div>
                        </div>
                      </div>
                    ))
                  )}
                  {busy && (
                    <div className="thinking">
                      <LoaderCircle className="spin" size={16} /> Retrieving
                      authorised evidence…
                    </div>
                  )}
                </div>
                <form
                  className="composer"
                  onSubmit={(e) => {
                    e.preventDefault();
                    ask();
                  }}
                >
                  <textarea
                    aria-label="Question"
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                    placeholder="Ask a question about your organisation’s documents…"
                    rows={2}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        ask();
                      }
                    }}
                  />
                  <div>
                    <select
                      aria-label="Document scope"
                      value={scope}
                      onChange={(e) => setScope(e.target.value)}
                    >
                      <option value="">All authorised documents</option>
                      {docs
                        .filter((d) => d.status === "ready")
                        .map((d) => (
                          <option key={d.id} value={d.id}>
                            {d.title}
                          </option>
                        ))}
                    </select>
                    <span>Grounded answers · Clear refusals</span>
                    <button
                      type="submit"
                      aria-label="Send question"
                      disabled={busy || !question.trim()}
                    >
                      <ArrowUp size={19} />
                    </button>
                  </div>
                </form>
              </section>
              <aside className="evidence-panel">
                <div className="evidence-heading">
                  <span className="eyebrow">EVIDENCE CONTEXT</span>
                  <h2>
                    {source
                      ? "Source inspection"
                      : "An answer you can inspect."}
                  </h2>
                  <p>
                    {source
                      ? "Exact retrieved content, including untrusted document text."
                      : "Authorised passages and trace details appear with each answer."}
                  </p>
                </div>
                {source ? (
                  <div className="source-inspection">
                    <button className="back" onClick={() => setSource(null)}>
                      ← Back to evidence
                    </button>
                    <FileText size={24} />
                    <h3>{source.title}</h3>
                    <span className="badge">Page {source.page}</span>
                    {source.hostile && (
                      <span className="badge warning">
                        Untrusted instruction detected
                      </span>
                    )}
                    <blockquote>{source.text}</blockquote>
                  </div>
                ) : latest ? (
                  <>
                    <div className="evidence-stats">
                      <div>
                        <span>CONFIGURATION</span>
                        <strong>{latest.config_id.slice(0, 8)}</strong>
                      </div>
                      <div>
                        <span>GENERATION</span>
                        <strong>
                          {latest.mode === "extractive"
                            ? "Exact quotations"
                            : "Model API"}
                        </strong>
                      </div>
                      <div>
                        <span>TOKEN USAGE</span>
                        <strong>
                          {latest.mode === "extractive"
                            ? "No provider call"
                            : `${latest.input_tokens ?? "—"} in / ${latest.output_tokens ?? "—"} out`}
                        </strong>
                      </div>
                    </div>
                    {latest.sources.map((s, i) => (
                      <button
                        className="source-card"
                        key={s.id}
                        onClick={() => setSource(s)}
                      >
                        <span className="source-number">{i + 1}</span>
                        <strong>{s.title}</strong>
                        <small>
                          Page {s.page}{" "}
                          {s.hostile ? "· Instruction isolated" : ""}
                        </small>
                        <p>{s.text.slice(0, 130)}…</p>
                      </button>
                    ))}
                    <div className="trace-link">
                      <Activity size={15} />
                      <span>Trace {latest.trace_id.slice(0, 8)}</span>
                      <button onClick={() => setView("traces")}>
                        Inspect <ArrowUpRight size={12} />
                      </button>
                    </div>
                  </>
                ) : (
                  <div className="evidence-empty">
                    <div>
                      <FileText size={22} />
                      <FileText size={22} />
                      <FileText size={22} />
                    </div>
                    <span>Evidence lives here.</span>
                    <p>
                      Choose a citation to see the exact
                      <br />
                      passage behind an answer.
                    </p>
                  </div>
                )}
                <div className="trust-note">
                  <LockKeyhole size={16} />
                  <p>
                    Permissions are checked in retrieval and again before the
                    response. No shared answer cache.
                  </p>
                </div>
              </aside>
            </div>
          )}
          {view === "library" && (
            <>
              <div className="library-tools">
                <div>
                  <Search size={16} />
                  <input
                    aria-label="Search documents"
                    placeholder="Find an authorised document…"
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                  />
                </div>
                <span>{docs.length} documents in your access scope</span>
              </div>
              <div className="document-grid">
                {docs
                  .filter((d) =>
                    d.title.toLowerCase().includes(filter.toLowerCase()),
                  )
                  .map((d) => (
                    <article className="document-card" key={d.id}>
                      <div>
                        <span className="doc-icon">
                          <FileText size={23} />
                        </span>
                        <span
                          className={
                            "badge " + (d.status === "ready" ? "" : "warning")
                          }
                        >
                          {d.status}
                        </span>
                      </div>
                      <h3>{d.title}</h3>
                      <p>
                        {d.media_type === "application/pdf"
                          ? "PDF document"
                          : "Text document"}{" "}
                        · Versioned ingestion
                      </p>
                      <div className="document-groups">
                        {d.groups.map((g) => (
                          <span className="group" key={g}>
                            <LockKeyhole size={10} />
                            {g}
                          </span>
                        ))}
                      </div>
                      {d.error && <p className="error-text">{d.error}</p>}
                      <div className="doc-actions">
                        <button
                          onClick={() => {
                            setScope(d.id);
                            setView("ask");
                          }}
                        >
                          Ask this document <ArrowUpRight size={13} />
                        </button>
                        {user.admin && (
                          <button
                            aria-label={`Restrict ${d.title} to leadership`}
                            onClick={async () => {
                              setBusy(true);
                              try {
                                await api(
                                  `/documents/${d.id}/permissions`,
                                  {
                                    groups: d.groups.includes("employees")
                                      ? ["leadership"]
                                      : ["employees"],
                                  },
                                  "PUT",
                                );
                                await refresh();
                                setNotice(
                                  "Permissions updated. Previous evaluations are now invalid.",
                                );
                              } catch (e) {
                                setError((e as Error).message);
                              } finally {
                                setBusy(false);
                              }
                            }}
                          >
                            <KeyRound size={15} />
                          </button>
                        )}
                      </div>
                    </article>
                  ))}
              </div>
            </>
          )}
          {view === "evaluations" &&
            (!user.admin ? (
              <section className="panel restricted-panel">
                <LockKeyhole size={30} />
                <h2>Evaluation details require administrator access.</h2>
                <p>
                  Evaluation cases may include restricted source facts. Switch
                  to the administrator demo identity to inspect the fictional
                  dataset.
                </p>
              </section>
            ) : (
              <>
                <div className="evaluation-toolbar">
                  <select
                    aria-label="Evaluation run"
                    value={selectedEval?.id || ""}
                    onChange={(e) => setEvalId(e.target.value)}
                  >
                    {evaluations.map((e) => (
                      <option key={e.id} value={e.id}>
                        {
                          releases?.configs.find((c) => c.id === e.config_id)
                            ?.name
                        }{" "}
                        · {e.metrics.passed_cases}/{e.metrics.cases} passed
                      </option>
                    ))}
                  </select>
                  <span className="badge">
                    Deterministic task-specific evaluation
                  </span>
                </div>
                {selectedEval && (
                  <>
                    <div className="metric-grid">
                      <Metric
                        label="RETRIEVAL RECALL"
                        value={percent(selectedEval.metrics.recall)}
                        note="Supporting documents retrieved"
                      />
                      <Metric
                        label="CITATION CORRECTNESS"
                        value={percent(
                          selectedEval.metrics.citation_correctness,
                        )}
                        note="Correct supporting source"
                      />
                      <Metric
                        label="REFUSAL ACCURACY"
                        value={percent(selectedEval.metrics.refusal_accuracy)}
                        note="Labeled refusal decisions"
                      />
                      <Metric
                        label="APPLICATION P95"
                        value={`${fmt(selectedEval.metrics.p95_ms)} ms`}
                        note="Measured operation latency"
                      />
                    </div>
                    <div className="evaluation-split">
                      <section className="panel">
                        <div className="panel-heading">
                          <h2>Configuration comparison</h2>
                          <span>Recall vs evidence correctness</span>
                        </div>
                        <ResponsiveContainer width="100%" height={220}>
                          <BarChart
                            data={releases?.configs
                              .filter((c) => c.evaluation)
                              .map((c) => ({
                                name: c.name.replace("Hybrid · ", "H. "),
                                recall: (c.evaluation?.recall || 0) * 100,
                                citations:
                                  (c.evaluation?.citation_correctness || 0) *
                                  100,
                              }))}
                          >
                            <CartesianGrid
                              strokeDasharray="3 3"
                              vertical={false}
                              stroke="#ecebf1"
                            />
                            <XAxis dataKey="name" fontSize={10} />
                            <YAxis domain={[0, 100]} fontSize={11} />
                            <Tooltip />
                            <Bar
                              dataKey="recall"
                              fill="#7471bf"
                              radius={[4, 4, 0, 0]}
                            />
                            <Bar
                              dataKey="citations"
                              fill="#c3bfdf"
                              radius={[4, 4, 0, 0]}
                            />
                          </BarChart>
                        </ResponsiveContainer>
                      </section>
                      <section className="panel eval-method">
                        <span className="eyebrow">WHAT THESE SCORES MEAN</span>
                        <h2>
                          Evidence first.
                          <br />
                          No invented certainty.
                        </h2>
                        <p>{selectedEval.methodology}</p>
                        <span className="badge">
                          {selectedEval.generation_backend === "extractive"
                            ? "Evidence-mode run · no LLM judge"
                            : "Model API run"}
                        </span>
                      </section>
                    </div>
                    <section className="panel">
                      <div className="panel-heading">
                        <h2>Regression cases</h2>
                        <span>
                          {selectedEval.metrics.passed_cases} /{" "}
                          {selectedEval.metrics.cases} passed
                        </span>
                      </div>
                      <div className="table-wrap">
                        <table>
                          <thead>
                            <tr>
                              <th>CASE / QUESTION</th>
                              <th>EXPECTED ANSWER</th>
                              <th>OBSERVED RESULT</th>
                              <th>STATUS</th>
                            </tr>
                          </thead>
                          <tbody>
                            {selectedEval.cases.map((c) => (
                              <tr key={c.id}>
                                <td>
                                  <small>
                                    {c.id} · {c.category.replaceAll("_", " ")}
                                  </small>
                                  <strong>{c.question}</strong>
                                </td>
                                <td>{c.expected_answer}</td>
                                <td>{c.answer}</td>
                                <td>
                                  <span
                                    className={
                                      "badge " + (c.passed ? "" : "warning")
                                    }
                                  >
                                    {c.passed ? (
                                      <Check size={12} />
                                    ) : (
                                      <X size={12} />
                                    )}{" "}
                                    {c.passed ? "Passed" : "Review"}
                                  </span>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </section>
                  </>
                )}
              </>
            ))}
          {view === "releases" && (
            <>
              <div className="release-banner">
                <ShieldCheck size={26} />
                <div>
                  <h2>Quality, security, latency and cost share one gate.</h2>
                  <p>
                    Target p95 ≤ {releases?.policy.maximum_p95_ms} ms ·
                    estimated provider cost ≤ $
                    {releases?.policy.maximum_cost_per_query} per query · zero
                    security failures
                  </p>
                </div>
                {user.admin && (
                  <button
                    className="secondary"
                    onClick={() => setNewConfig(!newConfig)}
                  >
                    <Plus size={14} /> New candidate
                  </button>
                )}
              </div>
              {newConfig && user.admin && (
                <section className="panel new-candidate">
                  <h2>Register an immutable candidate</h2>
                  <p>
                    Clone the champion with the other versioned prompt. Run the
                    full regression suite before traffic.
                  </p>
                  <button
                    className="primary"
                    disabled={busy || !champion}
                    onClick={() => {
                      if (!champion) return;
                      action("/configurations", {
                        name:
                          "Prompt challenger " +
                          new Date().toLocaleTimeString(),
                        retrieval: champion.retrieval,
                        generation: champion.generation,
                        model: champion.model,
                        prompt_version:
                          champion.prompt_version === "grounded-v1"
                            ? "grounded-v2"
                            : "grounded-v1",
                        top_k: champion.top_k,
                        candidate_pool: 20,
                        max_context_words: 1200,
                        minimum_similarity: 0.35,
                      });
                      setNewConfig(false);
                    }}
                  >
                    Register candidate
                  </button>
                </section>
              )}
              <section className="panel">
                <div className="panel-heading">
                  <h2>Versioned configurations</h2>
                  <span className="badge">
                    {releases?.job.status || "idle"}
                  </span>
                </div>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>CONFIGURATION</th>
                        <th>PROMPT / MODEL</th>
                        <th>RECALL</th>
                        <th>P95</th>
                        <th>RELEASE GATE</th>
                        <th>ACTIONS</th>
                      </tr>
                    </thead>
                    <tbody>
                      {releases?.configs.map((c) => (
                        <tr key={c.id}>
                          <td>
                            <strong>{c.name}</strong>
                            <small>
                              {c.id} · {c.retrieval} · top {c.top_k}
                            </small>
                          </td>
                          <td>
                            {c.prompt_version}
                            <small>{c.model}</small>
                          </td>
                          <td>{percent(c.evaluation?.recall)}</td>
                          <td>{fmt(c.evaluation?.p95_ms)} ms</td>
                          <td>
                            <span
                              className={
                                "badge " + (c.gate.passed ? "" : "warning")
                              }
                              title={c.gate.reasons.join(" · ")}
                            >
                              {c.id === releases.champion
                                ? "Champion"
                                : c.gate.passed
                                  ? "Eligible"
                                  : "Blocked"}
                            </span>
                            <small className="gate-reasons">
                              {c.gate.reasons.join(" · ")}
                            </small>
                          </td>
                          <td>
                            {user.admin && (
                              <div className="row-actions">
                                <button
                                  disabled={busy}
                                  onClick={() =>
                                    action("/evaluations", { config_id: c.id })
                                  }
                                >
                                  Evaluate
                                </button>
                                {c.id !== releases.champion && (
                                  <>
                                    <button
                                      disabled={busy || !c.gate.passed}
                                      onClick={() =>
                                        action("/releases/start", {
                                          config_id: c.id,
                                          mode: "shadow",
                                        })
                                      }
                                    >
                                      Approve shadow
                                    </button>
                                    <button
                                      disabled={busy || !c.gate.passed}
                                      onClick={() =>
                                        action("/releases/start", {
                                          config_id: c.id,
                                          mode: "canary",
                                        })
                                      }
                                    >
                                      Approve 20% canary
                                    </button>
                                  </>
                                )}
                              </div>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
              <section className="panel">
                <div className="panel-heading">
                  <h2>Traffic rollouts</h2>
                  <span>
                    Shadow uses the same principal and permission filter
                  </span>
                </div>
                {!releases?.rollouts.length && (
                  <div className="empty">
                    No active rollout. The evaluated champion serves all
                    requests.
                  </div>
                )}
                {releases?.rollouts.map((r) => (
                  <div className="rollout-card" key={r.id}>
                    <div>
                      <strong>
                        {r.mode.toUpperCase()} · {r.status}
                      </strong>
                      <p>
                        Candidate {r.candidate.slice(0, 8)} ·{" "}
                        {r.checks.requests} requests ·{" "}
                        {percent(r.checks.error_rate)} errors · p95{" "}
                        {fmt(r.checks.p95_ms)} ms
                      </p>
                      <small>
                        {r.decision?.reasons.join(" · ") ||
                          r.checks.reasons.join(" · ") ||
                          (!r.checks.passed
                            ? "Waiting for the minimum observation window."
                            : "Traffic checks passed.")}
                      </small>
                    </div>
                    {r.status === "active" && user.admin && (
                      <div className="row-actions">
                        <button
                          onClick={() => action(`/releases/${r.id}/abort`)}
                        >
                          Roll back
                        </button>
                        <button
                          className="primary"
                          disabled={!r.checks.passed || busy}
                          onClick={() => action(`/releases/${r.id}/finish`)}
                        >
                          {r.mode === "shadow"
                            ? "Complete shadow review"
                            : "Approve full rollout"}
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </section>
            </>
          )}
          {view === "traces" && (
            <>
              <div className="metric-grid">
                <Metric
                  label="YOUR RECENT REQUESTS"
                  value={String(traces.length)}
                  note="Live and shadow observations"
                />
                <Metric
                  label="REFUSALS"
                  value={String(traces.filter((t) => t.refused).length)}
                  note="No supported authorised answer"
                />
                <Metric
                  label="HOSTILE CONTEXTS"
                  value={String(
                    traces.filter((t) => t.hostile_chunks > 0).length,
                  )}
                  note="Untrusted instructions detected"
                />
                <Metric
                  label="AVERAGE LATENCY"
                  value={
                    traces.length
                      ? `${fmt(traces.reduce((n, t) => n + t.latency_ms, 0) / traces.length)} ms`
                      : "—"
                  }
                  note="Application operation"
                />
              </div>
              <section className="panel">
                <div className="panel-heading">
                  <h2>Your request traces</h2>
                  <span>Metadata only · no question or document text</span>
                </div>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>TRACE</th>
                        <th>CONFIGURATION</th>
                        <th>PATH</th>
                        <th>RESULT</th>
                        <th>CONTEXT</th>
                        <th>LATENCY</th>
                        <th>TOKENS / COST</th>
                      </tr>
                    </thead>
                    <tbody>
                      {traces.map((t) => (
                        <tr key={t.id}>
                          <td>
                            <strong>{t.id.slice(0, 8)}</strong>
                            <small>
                              {new Date(t.created * 1000).toLocaleTimeString()}
                            </small>
                          </td>
                          <td>
                            {t.config_id.slice(0, 8)}
                            <small>{t.prompt_version}</small>
                          </td>
                          <td>{t.kind}</td>
                          <td>
                            <span
                              className={"badge " + (t.error ? "warning" : "")}
                            >
                              {t.error
                                ? "Error"
                                : t.refused
                                  ? "Refused"
                                  : "Grounded"}
                            </span>
                          </td>
                          <td>
                            {t.source_count} passages
                            {t.hostile_chunks > 0 && (
                              <small>Hostile instruction isolated</small>
                            )}
                          </td>
                          <td>{fmt(t.latency_ms)} ms</td>
                          <td>
                            {t.input_tokens ?? "—"} in /{" "}
                            {t.output_tokens ?? "—"} out
                            <small>
                              {t.estimated_cost == null
                                ? "Unavailable"
                                : `$${t.estimated_cost.toFixed(5)}`}
                            </small>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {!traces.length && (
                    <div className="empty">
                      Ask a question to inspect the retrieval and generation
                      trace.
                    </div>
                  )}
                </div>
              </section>
            </>
          )}
          <footer>
            <span>Aperture · Permission-aware by design</span>
            <span>
              Fictional corpus · Measured results · Explicit approvals
            </span>
          </footer>
        </div>
      </main>
    </div>
  );
}
function Metric({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note: string;
}) {
  return (
    <section className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{note}</small>
    </section>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
