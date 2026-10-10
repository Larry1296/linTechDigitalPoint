import { useEffect, useState } from "react";
import { MessageCircle, Sparkles } from "lucide-react";
import { usePlatform } from "./PlatformContext";
import { ChatWidget, readEvents } from "../assistant/ChatWidget";
import { Answer } from "./answerFormat";

const MAX_QUESTION = 1000;
export const SUGGESTIONS = [
  "How do I get started?",
  "How much does it cost?",
  "Can I import my products from Excel?",
  "Does it work with M-Pesa?",
  "Can my staff use it?",
  "Is my business data safe?",
];

export { Answer, readEvents };

// The website's help assistant: a floating button that opens a chat about the platform.
// Anything on the page can open the chat, optionally with a question to ask straight away.
export function openHelpChat(question) {
  window.dispatchEvent(new CustomEvent("help-chat:open", { detail: { question } }));
}

// The public chat endpoint answers with an error body rather than a stream when it refuses.
async function send(messages, signal) {
  const response = await fetch("/api/v1/assistant/chat/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages }),
    signal,
  });
  if (response.ok && response.body) return response;
  const data = await response.json().catch(() => ({}));
  throw Object.assign(new Error(data.detail || "The assistant isn't available right now. Please try again later."), { status: response.status });
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
  if (config && !config.enabled) return null;
  return (
    <ChatWidget
      storageKey="help-chat" historyKey="help-chat-questions" inputId="help-chat-input" openEvent="help-chat:open"
      title={`${platform.name} assistant`} subtitle="Answers about getting started, features and pricing"
      avatar={<Sparkles size={18} />} launcherIcon={<MessageCircle size={22} aria-hidden="true" />} launcherLabel="Ask us anything"
      greeting={config?.greeting || `Hi! I can answer questions about ${platform.name}: how to get started, what it can do for your business, pricing and more. What would you like to know?`}
      suggestions={config?.suggestions?.length ? config.suggestions : SUGGESTIONS}
      maxQuestion={MAX_QUESTION} send={send} tooQuickly="You're sending questions quickly. Please wait a moment and try again."
      note="AI answers can be wrong. For account-specific help, contact the team." />
  );
}
