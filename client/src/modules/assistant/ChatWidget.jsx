import { useCallback, useEffect, useRef, useState } from "react";
import { RotateCcw, Send, X } from "lucide-react";
import { Answer, plainText } from "../platform/answerFormat";
import { CopyButton } from "../platform/CopyButton";
import { useCloseOnOutsideClick, usePromptHistory, useQuestionAtTop } from "./promptHistory";
import "../platform/helpChat.css";

// Reads the server-sent events from a chat endpoint as they arrive.
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

function load(key) {
  try { return JSON.parse(sessionStorage.getItem(key)) || []; } catch { return []; }
}
function save(key, messages) {
  try { sessionStorage.setItem(key, JSON.stringify(messages.filter((m) => !m.pending))); } catch { /* private mode: the chat still works */ }
}

/**
 * A floating chat: a launcher button that opens a panel where questions are asked and answers stream in, each one
 * copyable in a tap. Every chat in the app is this one, set up with its own words and its own server endpoint.
 *
 * - ``send(messages, signal)`` posts the conversation ([{role, content}]) and resolves to the streamed response; it
 *   throws an error with a ``message`` (and ``status``, 429 when asked too quickly) when the server refuses.
 * - The stream's events: ``text`` (more of the answer), ``tool`` (what is being looked up), ``sources``, and
 *   ``refusal``/``error`` (shown in place of the answer).
 * - ``storageKey`` keeps the conversation for this browser tab; ``historyKey`` keeps the questions asked (Up/Down).
 * - ``openEvent`` is a window event name that opens the chat, optionally asking ``detail.question`` straight away.
 */
export function ChatWidget({
  storageKey, historyKey, title, subtitle, avatar, launcherIcon, launcherLabel, greeting, suggestions = [],
  placeholder = "Ask a question…", note, maxQuestion = 1000, inputId, className = "", headerExtra, send,
  tooQuickly = "You're asking quickly. Please wait a moment and try again.", openEvent, onOpenChange,
}) {
  const [open, setOpenState] = useState(false);
  const setOpen = useCallback((value) => { setOpenState(value); onOpenChange?.(value); }, [onOpenChange]);
  const [messages, setMessages] = useState(() => load(storageKey));
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const abort = useRef(null);
  const input = useRef(null);
  const container = useRef(null);
  const close = useCallback(() => setOpen(false), [setOpen]);
  useCloseOnOutsideClick(container, open, close);
  const asked = usePromptHistory(historyKey, draft, setDraft);
  useEffect(() => save(storageKey, messages), [storageKey, messages]);
  const list = useQuestionAtTop(messages, open);
  useEffect(() => { if (open) input.current?.focus(); }, [open]);
  useEffect(() => () => abort.current?.abort(), []);
  const pendingQuestion = useRef(null);
  useEffect(() => {
    if (!openEvent) return undefined;
    const onOpen = (event) => { setOpen(true); pendingQuestion.current = event.detail?.question || null; };
    window.addEventListener(openEvent, onOpen);
    return () => window.removeEventListener(openEvent, onOpen);
  }, [openEvent, setOpen]);
  useEffect(() => {
    if (open && pendingQuestion.current) { const question = pendingQuestion.current; pendingQuestion.current = null; void ask(question); }
  });

  const update = (change) => setMessages((current) => {
    const next = [...current];
    next[next.length - 1] = { ...next.at(-1), ...change(next.at(-1)) };
    return next;
  });

  async function ask(question) {
    const text = question.trim().slice(0, maxQuestion);
    if (!text || busy) return;
    // A question whose reply failed is left out with its reply, so it is not asked again with the new one.
    const history = [...messages.filter((m, i) => m.text && !m.error && !(m.role === "user" && messages[i + 1]?.error)), { role: "user", text }];
    setMessages([...messages, { role: "user", text }, { role: "assistant", text: "", pending: true }]);
    asked.remember(text);
    setDraft("");
    setBusy(true);
    abort.current = new AbortController();
    try {
      const response = await send(history.map((m) => ({ role: m.role, content: m.text })), abort.current.signal);
      for await (const event of readEvents(response)) {
        if (event.type === "text") update((last) => ({ text: last.text + event.text, status: undefined }));
        else if (event.type === "tool") update(() => ({ status: `${event.label}…` }));
        else if (event.type === "sources") update(() => ({ sources: event.items }));
        else if (event.type === "refusal" || event.type === "error") update(() => ({ text: event.message, error: true }));
      }
      update(() => ({ pending: false, status: undefined }));
    } catch (error) {
      if (error.name === "AbortError") return;
      const message = error.status === 429 ? tooQuickly : error.message || "The connection was lost. Please try again.";
      update(() => ({ text: message, error: true, pending: false, status: undefined }));
    } finally {
      setBusy(false);
    }
  }

  const reset = () => { abort.current?.abort(); setMessages([]); setBusy(false); input.current?.focus(); };

  return (
    <div ref={container} className={`helpChat ${className}`.trim()}>
      {open && (
        <section className="helpChatPanel" role="dialog" aria-label={title}
          onKeyDown={(event) => { if (event.key === "Escape") setOpen(false); }}>
          <header>
            <span className="helpChatAvatar" aria-hidden="true">{avatar}</span>
            <div><strong>{title}</strong><small>{subtitle}</small></div>
            {headerExtra}
            {messages.length > 0 && <button type="button" className="helpChatIcon" onClick={reset} aria-label="Start a new conversation"><RotateCcw size={17} /></button>}
            <button type="button" className="helpChatIcon" onClick={() => setOpen(false)} aria-label="Close chat"><X size={19} /></button>
          </header>
          <div className="helpChatMessages" ref={list} aria-live="polite">
            <div className="helpChatMessage assistant"><p>{greeting}</p></div>
            {messages.length === 0 && suggestions.length > 0 && (
              <div className="helpChatSuggestions" aria-label="Suggested questions">
                {suggestions.map((suggestion) => <button type="button" key={suggestion} onClick={() => ask(suggestion)}>{suggestion}</button>)}
              </div>
            )}
            {messages.map((message, index) => (
              <div key={index} className={`helpChatMessage ${message.role}${message.error ? " error" : ""}`}>
                {message.role === "user" ? <p>{message.text}</p>
                  : message.pending && !message.text ? <p className="helpChatTyping" aria-label="The assistant is working"><i /><i /><i /></p>
                  : <Answer text={message.text} />}
                {message.pending && message.status && <small className="businessAssistantStatus">{message.status}</small>}
                {message.sources?.length > 0 && !message.pending && <small className="helpChatSources">From: {message.sources.join(" · ")}</small>}
                {!message.pending && !message.error && message.text && (
                  <CopyButton text={message.role === "user" ? message.text : plainText(message.text)} label={message.role === "user" ? "Copy question" : "Copy answer"} />
                )}
              </div>
            ))}
          </div>
          <form className="helpChatForm" onSubmit={(event) => { event.preventDefault(); ask(draft); }}>
            <label className="srOnly" htmlFor={inputId}>Your question</label>
            <textarea id={inputId} ref={input} rows={1} value={draft} maxLength={maxQuestion} placeholder={placeholder}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (asked.onKeyDown(event)) return;
                if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); ask(draft); }
              }} />
            <button type="submit" disabled={busy || !draft.trim()} aria-label="Send question"><Send size={18} /></button>
          </form>
          {note && <p className="helpChatNote">{note}</p>}
        </section>
      )}
      <button type="button" className="helpChatLauncher" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? <X size={22} aria-hidden="true" /> : launcherIcon}
        <span>{open ? "Close" : launcherLabel}</span>
      </button>
    </div>
  );
}
