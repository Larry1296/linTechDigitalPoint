import { useCallback, useEffect, useRef, useState } from "react";
import { BrainCircuit, RotateCcw, Send, Sparkles, X } from "lucide-react";
import { api, apiStream } from "../../core/api/client";
import { Answer, readEvents } from "../platform/HelpChat";
import { useCloseOnOutsideClick, usePromptHistory, useQuestionAtTop } from "./promptHistory";
import "../platform/helpChat.css";
import "./businessAssistant.css";

const MAX_QUESTION = 2000;
export const SUGGESTIONS = [
  "How are my sales trending over the last 90 days?",
  "What is running low and how much should I reorder?",
  "Which products bring in most of my revenue?",
  "What stock has not sold in the last 60 days?",
  "Give me a profit and loss summary for this month.",
  "What are my busiest days and hours?",
];

// The conversation stays in this browser tab, one per business, and never mixes businesses.
const storageKey = (organization) => `business-assistant-${organization.id}`;
function load(organization) {
  try { return JSON.parse(sessionStorage.getItem(storageKey(organization))) || []; } catch { return []; }
}
function save(organization, messages) {
  try { sessionStorage.setItem(storageKey(organization), JSON.stringify(messages.filter((m) => !m.pending))); } catch { /* private mode: the chat still works */ }
}

// Chooses the AI provider for this business. Only owners and admins can change it.
function ProviderPicker({ settings, onChange }) {
  if (!settings?.can_manage) return null;
  const options = settings.providers.filter((p) => p.available);
  if (options.length < 2) return null;
  return (
    <label className="businessAssistantProvider">
      <span className="srOnly">AI provider</span>
      <select value={settings.provider || ""} onChange={(event) => onChange(event.target.value)} aria-label="AI provider">
        {options.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
      </select>
    </label>
  );
}

// Each business's own assistant: answers questions about its stock, sales, money and how to use the system.
export function BusinessAssistant({ organization }) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState(() => load(organization));
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [settings, setSettings] = useState(null);
  const abort = useRef(null);
  const input = useRef(null);
  const container = useRef(null);
  const close = useCallback(() => setOpen(false), []);
  useCloseOnOutsideClick(container, open, close);
  const asked = usePromptHistory(`business-assistant-questions:${organization.id}`, draft, setDraft);
  useEffect(() => save(organization, messages), [organization, messages]);
  const list = useQuestionAtTop(messages, open);
  useEffect(() => { if (open) input.current?.focus(); }, [open]);
  useEffect(() => () => abort.current?.abort(), []);
  useEffect(() => {
    if (!open || settings) return;
    api("/api/v1/business-assistant/settings/").then(setSettings).catch(() => setSettings({ providers: [], can_manage: false }));
  }, [open, settings]);

  const update = (change) => setMessages((current) => {
    const next = [...current];
    next[next.length - 1] = { ...next.at(-1), ...change(next.at(-1)) };
    return next;
  });

  async function chooseProvider(provider) {
    try { setSettings(await api("/api/v1/business-assistant/settings/", { method: "PUT", body: JSON.stringify({ provider }) })); } catch { /* keep the current choice */ }
  }

  async function ask(question) {
    const text = question.trim().slice(0, MAX_QUESTION);
    if (!text || busy) return;
    // A question whose reply failed is left out with its reply, so it is not asked again with the new one.
    const history = [...messages.filter((m, i) => m.text && !m.error && !(m.role === "user" && messages[i + 1]?.error)), { role: "user", text }];
    setMessages([...messages, { role: "user", text }, { role: "assistant", text: "", pending: true }]);
    asked.remember(text);
    setDraft("");
    setBusy(true);
    abort.current = new AbortController();
    try {
      const response = await apiStream("/api/v1/business-assistant/chat/", { messages: history.map((m) => ({ role: m.role, content: m.text })) }, abort.current.signal);
      for await (const event of readEvents(response)) {
        if (event.type === "text") update((last) => ({ text: last.text + event.text, status: undefined }));
        else if (event.type === "tool") update(() => ({ status: `${event.label}…` }));
        else if (event.type === "refusal" || event.type === "error") update(() => ({ text: event.message, error: true }));
      }
      update(() => ({ pending: false, status: undefined }));
    } catch (error) {
      if (error.name === "AbortError") return;
      const message = error.status === 429 ? "You're asking quickly. Please wait a moment and try again."
        : error.message || "The connection was lost. Please try again.";
      update(() => ({ text: message, error: true, pending: false, status: undefined }));
    } finally {
      setBusy(false);
    }
  }

  const reset = () => { abort.current?.abort(); setMessages([]); setBusy(false); input.current?.focus(); };

  return (
    <div ref={container} className="helpChat businessAssistant">
      {open && (
        <section className="helpChatPanel" role="dialog" aria-label={`${organization.name} assistant`}
          onKeyDown={(event) => { if (event.key === "Escape") setOpen(false); }}>
          <header>
            <span className="helpChatAvatar" aria-hidden="true"><BrainCircuit size={18} /></span>
            <div><strong>{organization.name} assistant</strong><small>Ask about your stock, sales, money and the system</small></div>
            <ProviderPicker settings={settings} onChange={chooseProvider} />
            {messages.length > 0 && <button type="button" className="helpChatIcon" onClick={reset} aria-label="Start a new conversation"><RotateCcw size={17} /></button>}
            <button type="button" className="helpChatIcon" onClick={() => setOpen(false)} aria-label="Close assistant"><X size={19} /></button>
          </header>
          <div className="helpChatMessages" ref={list} aria-live="polite">
            <div className="helpChatMessage assistant"><p>Hi! I know {organization.name}'s records. Ask me about stock, sales trends, profit, expenses or how to do something, and I'll look it up and analyse it for you.</p></div>
            {messages.length === 0 && (
              <div className="helpChatSuggestions" aria-label="Suggested questions">
                {SUGGESTIONS.map((suggestion) => <button type="button" key={suggestion} onClick={() => ask(suggestion)}>{suggestion}</button>)}
              </div>
            )}
            {messages.map((message, index) => (
              <div key={index} className={`helpChatMessage ${message.role}${message.error ? " error" : ""}`}>
                {message.role === "user" ? <p>{message.text}</p>
                  : message.pending && !message.text ? <p className="helpChatTyping" aria-label="The assistant is working"><i /><i /><i /></p>
                  : <Answer text={message.text} />}
                {message.pending && message.status && <small className="businessAssistantStatus">{message.status}</small>}
              </div>
            ))}
          </div>
          <form className="helpChatForm" onSubmit={(event) => { event.preventDefault(); ask(draft); }}>
            <label className="srOnly" htmlFor="business-assistant-input">Your question</label>
            <textarea id="business-assistant-input" ref={input} rows={1} value={draft} maxLength={MAX_QUESTION} placeholder="Ask about your business…"
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (asked.onKeyDown(event)) return;
                if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); ask(draft); }
              }} />
            <button type="submit" disabled={busy || !draft.trim()} aria-label="Send question"><Send size={18} /></button>
          </form>
          <p className="helpChatNote">Answers come from your records, but AI can make mistakes. Check important figures in Reports.</p>
        </section>
      )}
      <button type="button" className="helpChatLauncher" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? <X size={22} aria-hidden="true" /> : <Sparkles size={22} aria-hidden="true" />}
        <span>{open ? "Close" : "Ask your assistant"}</span>
      </button>
    </div>
  );
}
