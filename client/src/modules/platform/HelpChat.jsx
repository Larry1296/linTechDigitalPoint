import { useCallback, useEffect, useRef, useState } from "react";
import { MessageCircle, RotateCcw, Send, Sparkles, X } from "lucide-react";
import { usePlatform } from "./PlatformContext";
import { useCloseOnOutsideClick, usePromptHistory, useQuestionAtTop } from "../assistant/promptHistory";
import { Answer } from "./answerFormat";
import "./helpChat.css";

const STORAGE_KEY = "help-chat";
const MAX_QUESTION = 1000;
export const SUGGESTIONS = [
  "How do I get started?",
  "How much does it cost?",
  "Can I import my products from Excel?",
  "Does it work with M-Pesa?",
  "Can my staff use it?",
  "Is my business data safe?",
];

function load() {
  try { return JSON.parse(sessionStorage.getItem(STORAGE_KEY)) || []; } catch { return []; }
}
function save(messages) {
  try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify(messages.filter((m) => !m.pending))); } catch { /* private mode: the chat still works */ }
}

export { Answer };

// Reads the server-sent events from the chat endpoint as they arrive.
export async function* readEvents(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const parts = buffer.split("\n\n");
    buffer = parts.pop();
    for (const part of parts) {
      if (part.startsWith("data: ")) {
        try { yield JSON.parse(part.slice(6)); } catch { /* ignore a malformed line */ }
      }
    }
    if (done) return;
  }
}

// The website's help assistant: a floating button that opens a chat about the platform.
// Anything on the page can open the chat, optionally with a question to ask straight away.
export function openHelpChat(question) {
  window.dispatchEvent(new CustomEvent("help-chat:open", { detail: { question } }));
}

export function HelpChat() {
  const platform = usePlatform();
  // The platform owner can switch the chat off and set its greeting and suggestions (AI assistants page).
  const [config, setConfig] = useState(null);
  useEffect(() => {
    let live = true;
    fetch("/api/v1/assistant/config/").then((r) => (r.ok ? r.json() : null)).then((data) => { if (live && data) setConfig(data); }).catch(() => {});
    return () => { live = false; };
  }, []);
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState(load);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const abort = useRef(null);
  const input = useRef(null);
  const container = useRef(null);
  const close = useCallback(() => setOpen(false), []);
  useCloseOnOutsideClick(container, open, close);
  const asked = usePromptHistory("help-chat-questions", draft, setDraft);
  useEffect(() => save(messages), [messages]);
  const list = useQuestionAtTop(messages, open);
  useEffect(() => { if (open) input.current?.focus(); }, [open]);
  useEffect(() => () => abort.current?.abort(), []);
  const pendingQuestion = useRef(null);
  useEffect(() => {
    const onOpen = (event) => { setOpen(true); pendingQuestion.current = event.detail?.question || null; };
    window.addEventListener("help-chat:open", onOpen);
    return () => window.removeEventListener("help-chat:open", onOpen);
  }, []);
  useEffect(() => {
    if (open && pendingQuestion.current) { const question = pendingQuestion.current; pendingQuestion.current = null; void ask(question); }
  });

  const update = (change) => setMessages((current) => {
    const next = [...current];
    next[next.length - 1] = { ...next.at(-1), ...change(next.at(-1)) };
    return next;
  });

  async function ask(question) {
    const text = question.trim().slice(0, MAX_QUESTION);
    if (!text || busy) return;
    const history = [...messages.filter((m) => !m.error && m.text), { role: "user", text }];
    setMessages([...messages, { role: "user", text }, { role: "assistant", text: "", pending: true }]);
    asked.remember(text);
    setDraft("");
    setBusy(true);
    abort.current = new AbortController();
    try {
      const response = await fetch("/api/v1/assistant/chat/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: history.map((m) => ({ role: m.role, content: m.text })) }),
        signal: abort.current.signal,
      });
      if (!response.ok || !response.body) {
        const data = await response.json().catch(() => ({}));
        const message = response.status === 429 ? "You're sending questions quickly. Please wait a moment and try again."
          : data.detail || "The assistant isn't available right now. Please try again later.";
        update(() => ({ text: message, error: true, pending: false }));
        return;
      }
      for await (const event of readEvents(response)) {
        if (event.type === "text") update((last) => ({ text: last.text + event.text }));
        else if (event.type === "sources") update(() => ({ sources: event.items }));
        else if (event.type === "refusal" || event.type === "error") update(() => ({ text: event.message, error: true }));
      }
      update(() => ({ pending: false }));
    } catch (error) {
      if (error.name !== "AbortError") update(() => ({ text: "The connection was lost. Please try again.", error: true, pending: false }));
    } finally {
      setBusy(false);
    }
  }

  const reset = () => { abort.current?.abort(); setMessages([]); setBusy(false); input.current?.focus(); };
  if (config && !config.enabled) return null;
  const greeting = config?.greeting || `Hi! I can answer questions about ${platform.name}: how to get started, what it can do for your business, pricing and more. What would you like to know?`;
  const suggestions = config?.suggestions?.length ? config.suggestions : SUGGESTIONS;

  return (
    <div ref={container} className="helpChat">
      {open && (
        <section className="helpChatPanel" role="dialog" aria-label={`${platform.name} assistant`}
          onKeyDown={(event) => { if (event.key === "Escape") setOpen(false); }}>
          <header>
            <span className="helpChatAvatar" aria-hidden="true"><Sparkles size={18} /></span>
            <div><strong>{platform.name} assistant</strong><small>Answers about getting started, features and pricing</small></div>
            {messages.length > 0 && <button type="button" className="helpChatIcon" onClick={reset} aria-label="Start a new conversation"><RotateCcw size={17} /></button>}
            <button type="button" className="helpChatIcon" onClick={() => setOpen(false)} aria-label="Close chat"><X size={19} /></button>
          </header>
          <div className="helpChatMessages" ref={list} aria-live="polite">
            <div className="helpChatMessage assistant"><p>{greeting}</p></div>
            {messages.length === 0 && (
              <div className="helpChatSuggestions" aria-label="Suggested questions">
                {suggestions.map((suggestion) => <button type="button" key={suggestion} onClick={() => ask(suggestion)}>{suggestion}</button>)}
              </div>
            )}
            {messages.map((message, index) => (
              <div key={index} className={`helpChatMessage ${message.role}${message.error ? " error" : ""}`}>
                {message.role === "user" ? <p>{message.text}</p>
                  : message.pending && !message.text ? <p className="helpChatTyping" aria-label="The assistant is typing"><i /><i /><i /></p>
                  : <Answer text={message.text} />}
                {message.sources?.length > 0 && !message.pending && <small className="helpChatSources">From: {message.sources.join(" · ")}</small>}
              </div>
            ))}
          </div>
          <form className="helpChatForm" onSubmit={(event) => { event.preventDefault(); ask(draft); }}>
            <label className="srOnly" htmlFor="help-chat-input">Your question</label>
            <textarea id="help-chat-input" ref={input} rows={1} value={draft} maxLength={MAX_QUESTION} placeholder="Ask a question…"
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (asked.onKeyDown(event)) return;
                if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); ask(draft); }
              }} />
            <button type="submit" disabled={busy || !draft.trim()} aria-label="Send question"><Send size={18} /></button>
          </form>
          <p className="helpChatNote">AI answers can be wrong. For account-specific help, contact the team.</p>
        </section>
      )}
      <button type="button" className="helpChatLauncher" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? <X size={22} aria-hidden="true" /> : <MessageCircle size={22} aria-hidden="true" />}
        <span>{open ? "Close" : "Ask us anything"}</span>
      </button>
    </div>
  );
}
