import { useCallback, useRef, useState } from "react";
import { BrainCircuit, Sparkles } from "lucide-react";
import { api, apiStream } from "../../core/api/client";
import { ChatWidget } from "./ChatWidget";
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
// The conversation stays in this browser tab, one per business, and never mixes businesses.
export function BusinessAssistant({ organization }) {
  const [settings, setSettings] = useState(null);
  const asked = useRef(false);
  const onOpenChange = useCallback((open) => {
    if (!open || asked.current) return;  // the provider settings are loaded once, the first time the chat opens
    asked.current = true;
    api("/api/v1/business-assistant/settings/").then(setSettings).catch(() => setSettings({ providers: [], can_manage: false }));
  }, []);
  async function chooseProvider(provider) {
    try { setSettings(await api("/api/v1/business-assistant/settings/", { method: "PUT", body: JSON.stringify({ provider }) })); } catch { /* keep the current choice */ }
  }
  return (
    <ChatWidget key={organization.id} className="businessAssistant"
      storageKey={`business-assistant-${organization.id}`} historyKey={`business-assistant-questions:${organization.id}`} inputId="business-assistant-input"
      title={`${organization.name} assistant`} subtitle="Ask about your stock, sales, money and the system"
      avatar={<BrainCircuit size={18} />} launcherIcon={<Sparkles size={22} aria-hidden="true" />} launcherLabel="Ask your assistant"
      headerExtra={<ProviderPicker settings={settings} onChange={chooseProvider} />}
      greeting={`Hi! I know ${organization.name}'s records. Ask me about stock, sales trends, profit, expenses or how to do something, and I'll look it up and analyse it for you.`}
      suggestions={SUGGESTIONS} placeholder="Ask about your business…" maxQuestion={MAX_QUESTION} onOpenChange={onOpenChange}
      send={(messages, signal) => apiStream("/api/v1/business-assistant/chat/", { messages }, signal)}
      note="Answers come from your records, but AI can make mistakes. Check important figures in Reports." />
  );
}
