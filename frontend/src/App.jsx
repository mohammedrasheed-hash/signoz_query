import React, { useState } from "react";
import "./App.css";

const API = "http://localhost:8731";

const PRODUCTS = ["ctix", "csol", "co-island", "cftr", "csap", "csap-webapp"];
const RELATIVE = [
  { v: "15m", l: "Last 15 min" },
  { v: "1h", l: "Last 1 hour" },
  { v: "6h", l: "Last 6 hours" },
  { v: "24h", l: "Last 24 hours" },
];

export default function App() {
  const [customer, setCustomer] = useState("");
  const [allCustomers, setAllCustomers] = useState([]);
  const [showSuggest, setShowSuggest] = useState(false);
  const [product, setProduct] = useState("ctix");
  const [env, setEnv] = useState({ prod: false, poc: true });
  const [harFile, setHarFile] = useState(null);

  const [timeMode, setTimeMode] = useState("relative"); // relative | absolute | none
  const [relative, setRelative] = useState("15m");
  const [absStart, setAbsStart] = useState("");
  const [absEnd, setAbsEnd] = useState("");

  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState("");

  const envString = Object.entries(env)
    .filter(([, on]) => on)
    .map(([k]) => k)
    .join(",");

  // Load the customer list once on mount
  React.useEffect(() => {
    fetch(`${API}/customers`)
      .then((r) => r.json())
      .then((d) => setAllCustomers(d.customers || []))
      .catch(() => setAllCustomers([]));
  }, []);

  // Filter suggestions by what's typed (max 8 shown)
  const matches =
    customer.trim().length === 0
      ? []
      : allCustomers
          .filter((c) => c.toLowerCase().includes(customer.trim().toLowerCase()))
          .slice(0, 8);
  const exactMatch = allCustomers.some(
    (c) => c.toLowerCase() === customer.trim().toLowerCase()
  );

  const generate = async () => {
    setError("");
    if (!customer.trim()) {
      setError("Enter a customer name.");
      return;
    }
    if (!envString) {
      setError("Pick at least one environment.");
      return;
    }
    setLoading(true);
    setResult(null);
    try {
      const fd = new FormData();
      fd.append("customer", customer.trim());
      fd.append("product", product);
      fd.append("env", envString);
      fd.append("time_mode", harFile ? "none" : timeMode);
      if (timeMode === "relative") fd.append("relative", relative);
      if (timeMode === "absolute") {
        fd.append("abs_start", absStart);
        fd.append("abs_end", absEnd);
      }
      if (harFile) fd.append("har", harFile);

      const res = await fetch(`${API}/generate`, { method: "POST", body: fd });
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      setResult(await res.json());
    } catch (e) {
      setError(`Could not reach the backend. ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  const copy = (text, which) => {
    navigator.clipboard.writeText(text);
    setCopied(which);
    setTimeout(() => setCopied(""), 1500);
  };

  return (
    <div className="page">
      <header className="masthead">
        <div className="mark">SQ</div>
        <div>
          <h1>SigNoz Query Builder</h1>
          <p>Turn a customer, product, and HAR into a narrowed log filter.</p>
        </div>
      </header>

      <div className="grid">
        {/* ── Inputs ─────────────────────────────────────────── */}
        <section className="panel">
          <h2 className="eyebrow">Target</h2>

          <label className="field field--autocomplete">
            <span>
              Customer
              {customer.trim() && !exactMatch && (
                <em className="muted"> — not in list, will search by body</em>
              )}
            </span>
            <input
              value={customer}
              onChange={(e) => {
                setCustomer(e.target.value);
                setShowSuggest(true);
              }}
              onFocus={() => setShowSuggest(true)}
              onBlur={() => setTimeout(() => setShowSuggest(false), 120)}
              placeholder="Type to search… e.g. bmo"
              autoFocus
              autoComplete="off"
            />
            {showSuggest && matches.length > 0 && (
              <ul className="suggest">
                {matches.map((c) => (
                  <li
                    key={c}
                    onMouseDown={() => {
                      setCustomer(c);
                      setShowSuggest(false);
                    }}
                  >
                    {c}
                  </li>
                ))}
              </ul>
            )}
          </label>

          <label className="field">
            <span>Product</span>
            <select value={product} onChange={(e) => setProduct(e.target.value)}>
              {PRODUCTS.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </label>

          <div className="field">
            <span>Environment</span>
            <div className="chips">
              {["prod", "poc"].map((k) => (
                <button
                  key={k}
                  className={`chip ${env[k] ? "chip--on" : ""}`}
                  onClick={() => setEnv((s) => ({ ...s, [k]: !s[k] }))}
                  type="button"
                >
                  {k === "poc" ? "poc (uat)" : "prod"}
                </button>
              ))}
            </div>
          </div>

          <h2 className="eyebrow eyebrow--spaced">Narrow with a HAR</h2>
          <label className={`drop ${harFile ? "drop--filled" : ""}`}>
            <input
              type="file"
              accept=".har,application/json"
              onChange={(e) => setHarFile(e.target.files[0] || null)}
              hidden
            />
            {harFile ? (
              <span className="drop-name">📎 {harFile.name}</span>
            ) : (
              <span className="drop-hint">
                Drop or choose a <strong>.har</strong> file — endpoint, status,
                and time are pulled automatically
              </span>
            )}
          </label>
          {harFile && (
            <button className="link-btn" onClick={() => setHarFile(null)} type="button">
              remove HAR
            </button>
          )}

          {/* Time — only relevant when no HAR */}
          <h2 className="eyebrow eyebrow--spaced">
            Time {harFile && <em className="muted">— taken from HAR</em>}
          </h2>
          <div className={`time-block ${harFile ? "time-block--disabled" : ""}`}>
            <div className="seg">
              {[
                ["relative", "Relative"],
                ["absolute", "Absolute"],
                ["none", "None"],
              ].map(([v, l]) => (
                <button
                  key={v}
                  type="button"
                  className={`seg-btn ${timeMode === v ? "seg-btn--on" : ""}`}
                  onClick={() => setTimeMode(v)}
                  disabled={!!harFile}
                >
                  {l}
                </button>
              ))}
            </div>

            {timeMode === "relative" && (
              <select
                className="relsel"
                value={relative}
                onChange={(e) => setRelative(e.target.value)}
                disabled={!!harFile}
              >
                {RELATIVE.map((r) => (
                  <option key={r.v} value={r.v}>
                    {r.l}
                  </option>
                ))}
              </select>
            )}

            {timeMode === "absolute" && (
              <div className="abs">
                <label>
                  <span>Start (UTC)</span>
                  <input
                    type="datetime-local"
                    value={absStart}
                    onChange={(e) => setAbsStart(e.target.value)}
                    disabled={!!harFile}
                  />
                </label>
                <label>
                  <span>End (UTC)</span>
                  <input
                    type="datetime-local"
                    value={absEnd}
                    onChange={(e) => setAbsEnd(e.target.value)}
                    disabled={!!harFile}
                  />
                </label>
              </div>
            )}
          </div>

          <button className="run" onClick={generate} disabled={loading} type="button">
            {loading ? "Building…" : "Build query"}
          </button>
          {error && <p className="err">{error}</p>}
        </section>

        {/* ── Output ─────────────────────────────────────────── */}
        <section className="panel panel--out">
          <h2 className="eyebrow">Query</h2>

          {!result && <div className="empty">Your generated filter will appear here.</div>}

          {result && (
            <>
              {result.har_summary && (
                <div className="summary">
                  {result.har_summary.endpoints.length > 0 && (
                    <div>
                      <span className="tag">endpoint</span>
                      {result.har_summary.endpoints.join(", ")}
                    </div>
                  )}
                  {result.har_summary.statuses.length > 0 && (
                    <div>
                      <span className="tag tag--err">status</span>
                      {result.har_summary.statuses.join(", ")}
                    </div>
                  )}
                </div>
              )}

              {result.time_label && (
                <div className="timepill">🕑 {result.time_label}</div>
              )}

              <div className="out">
                <div className="out-head">
                  <span>Base only — no body filters, no time</span>
                  <button
                    className="copy"
                    onClick={() => copy(result.base_query, "base")}
                    type="button"
                  >
                    {copied === "base" ? "✓ copied" : "copy"}
                  </button>
                </div>
                <code>{result.base_query}</code>
              </div>

              <div className="out">
                <div className="out-head">
                  <span>Without time — set the range in SigNoz's picker</span>
                  <button
                    className="copy"
                    onClick={() => copy(result.query_without_time, "a")}
                    type="button"
                  >
                    {copied === "a" ? "✓ copied" : "copy"}
                  </button>
                </div>
                <code>{result.query_without_time}</code>
              </div>

              <div className="out">
                <div className="out-head">
                  <span>With time — single string (ClickHouse mode)</span>
                  <button
                    className="copy"
                    onClick={() => copy(result.query_with_time, "b")}
                    type="button"
                  >
                    {copied === "b" ? "✓ copied" : "copy"}
                  </button>
                </div>
                <code>{result.query_with_time}</code>
              </div>

              {result.notes && result.notes.length > 0 && (
                <ul className="notes">
                  {result.notes.map((n, i) => (
                    <li key={i}>{n}</li>
                  ))}
                </ul>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  );
}
