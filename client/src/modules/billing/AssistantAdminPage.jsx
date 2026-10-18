import { useCallback, useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { api } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { confirmAction, showError, showSuccess } from "../../core/ui/alerts";
import { ErrorState, Loading } from "../../components/States";
import { FormField } from "../../components/forms/FormField";
import "./billing.css";
import { TextArea } from "../../components/forms/TextBox";

const BASE = "/api/v1/assistant/admin";
const dateText = (value) => (value ? new Date(value).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "—");
const SOURCE = { "built-in": "Built in", edited: "Edited", added: "Added by you" };
const slugFrom = (title) => title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 80);

// Money market fund rates the app looks up by itself, with why a look failed. Businesses only ever see the rate in use.
const STATUS = { APPLIED: "Used", UNCONFIRMED: "Waiting for a second look", FAILED: "Not used" };

function FundRates({ rates }) {
  if (!rates) return null;
  return (
    <section className="panel" aria-labelledby="fund-rates">
      <h2 id="fund-rates">Money market fund rates</h2>
      <p className="muted">Looked up with {rates.model} every {rates.every_days} days from the fund's own website, checked, and then used for
        every business whose investment follows the fund. A failed look keeps the last rate and is tried again 6 hours later.
        To look now: <code>python manage.py refresh_fund_rates --force</code>.</p>
      <ul className="assistantProviders">
        {rates.funds.map((f) => <li key={f.code}><strong>{f.name}</strong>: {f.annual_rate != null
          ? `${Number(f.annual_rate)}% a year as of ${f.as_of}, next look ${f.next_check_on}` : "no rate yet"}{f.followed ? "" : " · no business follows it"}</li>)}
      </ul>
      {rates.checks.length > 0 && (
        <table className="loanRepayments">
          <caption>Latest looks</caption>
          <thead><tr><th>When</th><th>Fund</th><th>Result</th><th>Rate</th><th>Details</th></tr></thead>
          <tbody>{rates.checks.map((c) => (
            <tr key={`${c.fund}-${c.checked_at}`}>
              <td>{dateText(c.checked_at)}</td><td>{c.fund}</td><td>{STATUS[c.status] || c.status}</td>
              <td>{c.annual_rate != null ? `${Number(c.annual_rate)}%${c.effective_annual_rate != null ? ` (effective ${Number(c.effective_annual_rate)}%)` : ""}` : "—"}
                {c.as_of && <small> · as of {c.as_of}</small>}</td>
              <td>{c.message}{c.source_url && <> · <a href={c.source_url} target="_blank" rel="noreferrer">source</a></>}</td>
            </tr>))}</tbody>
        </table>
      )}
    </section>
  );
}

// Keys, models and the public chat's switch, greeting and suggested questions.
function ChatSettings({ data, onSaved }) {
  const [enabled, setEnabled] = useState(data.enabled);
  const [greeting, setGreeting] = useState(data.greeting);
  const [suggestions, setSuggestions] = useState(data.suggestions.join("\n"));
  const [busy, setBusy] = useState(false);
  const claude = data.providers.find((p) => p.id === "anthropic");
  const save = async (event) => {
    event.preventDefault();
    setBusy(true);
    try {
      onSaved(await api(`${BASE}/settings/`, { method: "PUT", body: JSON.stringify({ enabled, greeting, suggestions: suggestions.split("\n").slice(0, 8) }) }));
      await showSuccess("Saved", "The website's chat uses the new settings now.");
    } catch (err) {
      await showError("Could not save the chat settings.", err.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="panel" aria-labelledby="assistant-setup">
      <h2 id="assistant-setup">AI set-up</h2>
      <ul className="assistantProviders">
        {data.providers.map((p) => <li key={p.id}><strong>{p.label}</strong>: {p.available ? "key set" : "no key on the server"}</li>)}
      </ul>
      <p className="muted">Models: public chat {data.models.public}; business assistants {data.models.business_claude} (Claude) or {data.models.business_chatgpt} (ChatGPT).
        Keys are set on the server (ANTHROPIC_API_KEY, OPENAI_API_KEY), never here; run <code>python manage.py check_assistants</code> to test them.</p>
      {!claude?.available && <p className="billingNote">Without ANTHROPIC_API_KEY the website chat and the Claude business assistants answer that they are not available.</p>}
      <form onSubmit={(event) => void save(event)} aria-label="Public chat settings">
        <h3>Website help chat</h3>
        <label className="checkRow"><input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} /> Show the chat on the website</label>
        <FormField label="Greeting" value={greeting} maxLength={600} placeholder={data.default_greeting} onChange={(event) => setGreeting(event.target.value)} />
        <label>Suggested questions (one per line, up to 8)
          <TextArea rows={5} value={suggestions} placeholder={data.default_suggestions.join("\n")} onChange={(event) => setSuggestions(event.target.value)} />
        </label>
        <p className="muted">Leave the greeting or questions empty to use the built-in ones (shown faded).</p>
        <button disabled={busy}>Save chat settings</button>
      </form>
    </section>
  );
}

// One article: its title, its questions ("## ") with answers, and whether the chat uses it.
function ArticleEditor({ audience, article, onDone, onCancel }) {
  const adding = !article.slug;
  const [title, setTitle] = useState(article.title || "");
  const [body, setBody] = useState(article.body || "");
  const [active, setActive] = useState(article.active ?? true);
  const [busy, setBusy] = useState(false);
  const slug = article.slug || slugFrom(title);
  const call = async (method, payload) => {
    setBusy(true);
    try {
      onDone(await api(`${BASE}/articles/${audience}/${slug}/`, { method, ...(payload ? { body: JSON.stringify(payload) } : {}) }));
    } catch (err) {
      await showError("Could not save the article.", err.message);
      setBusy(false);
    }
  };
  const revert = async () => {
    const built = article.source === "edited";
    if (!(await confirmAction({ title: built ? "Go back to the built-in article?" : "Delete this article?",
      text: built ? "Your changes to it are removed." : "The chat stops using it.", confirmButtonText: built ? "Restore" : "Delete" }))) return;
    await call("DELETE");
  };
  return (
    <form className="formCard" aria-label={adding ? "New article" : `Edit ${article.title}`}
      onSubmit={(event) => { event.preventDefault(); void call("PUT", { title, body, active }); }}>
      <h3>{adding ? "New article" : article.title}</h3>
      <FormField label="Title" required maxLength={160} value={title} onChange={(event) => setTitle(event.target.value)} />
      <label>Questions and answers
        <TextArea rows={16} required value={body} onChange={(event) => setBody(event.target.value)}
          placeholder={"## A question people ask?\nThe answer, in plain words.\n\n## Another question?\nIts answer."} />
      </label>
      <p className="muted">Start each question on its own line with "## ". Use **bold** for button and page names. Write {"{platform}"} for the platform's name.</p>
      <label className="checkRow"><input type="checkbox" checked={active} onChange={(event) => setActive(event.target.checked)} /> The chat answers from this article</label>
      <div className="actionRow">
        <button disabled={busy || !slug}>Save article</button>
        {!adding && article.source !== "built-in" && <button type="button" className="secondary" disabled={busy} onClick={() => void revert()}>
          {article.source === "edited" ? "Restore built-in version" : "Delete"}</button>}
        <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

function Articles({ draft, onDraftUsed }) {
  const [audience, setAudience] = useState("public");
  const [rows, setRows] = useState();
  const [editing, setEditing] = useState(null);
  const load = useCallback(() => api(`${BASE}/articles/${audience}/`).then((data) => setRows(data.articles)).catch((err) => showError("Could not load the articles.", err.message)), [audience]);
  useEffect(() => { setRows(undefined); void load(); }, [load]);
  useEffect(() => { if (draft) { setAudience("public"); setEditing(draft); onDraftUsed(); } }, [draft, onDraftUsed]);
  return (
    <section className="panel" aria-labelledby="assistant-articles">
      <div className="sectionHeading">
        <h2 id="assistant-articles">Help articles</h2>
        <button type="button" className="secondary" onClick={() => setEditing({})}>Add article</button>
      </div>
      <div className="segmented" role="tablist" aria-label="Which chat">
        {[["public", "Website chat"], ["admin", "Your admin assistant"]].map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-selected={audience === key} className={audience === key ? "active" : ""} onClick={() => { setAudience(key); setEditing(null); }}>{label}</button>))}
      </div>
      <p className="muted">{audience === "public" ? "Anyone on the website gets answers from these, and nothing else."
        : "Only your own assistant reads these, to explain how to run the platform."}</p>
      {editing && <ArticleEditor key={editing.slug || "new"} audience={audience} article={editing}
        onCancel={() => setEditing(null)} onDone={(data) => { setRows(data.articles); setEditing(null); }} />}
      {!rows ? <Loading /> : <div className="trendTable"><table>
        <thead><tr><th>Article</th><th>Questions</th><th>Kind</th><th>Used</th><th><span className="visuallyHidden">Action</span></th></tr></thead>
        <tbody>{rows.map((a) => (
          <tr key={a.slug} className={a.active ? undefined : "muted"}>
            <td>{a.title}</td>
            <td>{(a.body.match(/^## /gm) || []).length}</td>
            <td>{SOURCE[a.source]}{a.updated_at && <small> · {dateText(a.updated_at)}</small>}</td>
            <td>{a.active ? "Yes" : "Hidden"}</td>
            <td><button type="button" className="secondary" onClick={() => setEditing(a)}>Edit</button></td>
          </tr>))}</tbody>
      </table></div>}
    </section>
  );
}

// What visitors asked; questions with no matching article are gaps to write about.
function Questions({ onWrite }) {
  const [unanswered, setUnanswered] = useState(false);
  const [data, setData] = useState();
  useEffect(() => { api(`${BASE}/questions/${unanswered ? "?unanswered=1" : ""}`).then(setData).catch((err) => showError("Could not load the questions.", err.message)); }, [unanswered]);
  return (
    <section className="panel" aria-labelledby="assistant-questions">
      <h2 id="assistant-questions">What visitors ask</h2>
      {data && <p className="muted">Last 30 days: {data.last_30_days.questions} questions, {data.last_30_days.unanswered} with no matching article.
        Only the question is kept (no names or addresses), for {data.keep_days} days.</p>}
      <label className="checkRow"><input type="checkbox" checked={unanswered} onChange={(event) => setUnanswered(event.target.checked)} /> Only questions no article answered</label>
      {!data ? <Loading /> : data.questions.length ? <div className="trendTable"><table>
        <thead><tr><th>Asked</th><th>Question</th><th>Answered from</th><th><span className="visuallyHidden">Action</span></th></tr></thead>
        <tbody>{data.questions.map((q) => (
          <tr key={q.id}>
            <td>{dateText(q.asked_at)}</td>
            <td>{q.question}</td>
            <td>{q.answered ? q.articles.join(", ") : <strong className="negative">No article</strong>}</td>
            <td>{!q.answered && <button type="button" className="secondary" onClick={() => onWrite(q.question)}>Write an answer</button>}</td>
          </tr>))}</tbody>
      </table></div> : <p className="muted">No questions yet.</p>}
    </section>
  );
}

// The platform owner's controls for the AI assistants.
export function AssistantAdminPage() {
  const { user } = useAuth();
  const [settings, setSettings] = useState();
  const [error, setError] = useState("");
  const [draft, setDraft] = useState(null);
  const load = useCallback(() => api(`${BASE}/settings/`).then(setSettings).catch((err) => setError(err.message)), []);
  useEffect(() => { if (user?.platform_admin) void load(); }, [user, load]);
  const clearDraft = useCallback(() => setDraft(null), []);
  if (!user?.platform_admin) return <Navigate to="/admin/dashboard" replace />;
  if (error && !settings) return <ErrorState message={error} retry={load} />;
  if (!settings) return <Loading />;
  return (
    <>
      <span className="eyebrow">Platform</span>
      <h1>AI assistants</h1>
      <p className="muted">The website chat answers visitors from the help articles. Each business's assistant reads only that business's records.
        Yours also sees every registered business in general terms and the admin articles.</p>
      <ChatSettings data={settings} onSaved={setSettings} />
      <FundRates rates={settings.fund_rates} />
      <Articles draft={draft} onDraftUsed={clearDraft} />
      <Questions onWrite={(question) => { setDraft({ title: "", body: `## ${question}\n`, active: true }); window.scrollTo?.({ top: 0, behavior: "smooth" }); }} />
    </>
  );
}
