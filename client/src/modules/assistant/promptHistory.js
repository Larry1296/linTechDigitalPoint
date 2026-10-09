import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

const KEEP = 50;

function read(key) {
  try { return JSON.parse(localStorage.getItem(key)) || []; } catch { return []; }
}

function write(key, entries) {
  try { localStorage.setItem(key, JSON.stringify(entries)); } catch { /* private mode: history lasts until the page closes */ }
}

// Up and Down in the question box step through the questions asked before, like a terminal. Up goes back only from
// the first line (and Down forward only from the last), so moving within a long question still works; stepping past
// the newest question brings back what was being typed. History survives "new conversation" and reloads.
export function usePromptHistory(storageKey, draft, setDraft) {
  const [entries, setEntries] = useState(() => read(storageKey));
  const position = useRef(null); // index into entries while browsing; null when editing a fresh question
  const saved = useRef("");

  const remember = useCallback((question) => {
    position.current = null;
    setEntries((current) => {
      const next = current.at(-1) === question ? current : [...current, question].slice(-KEEP);
      write(storageKey, next);
      return next;
    });
  }, [storageKey]);

  const show = (element, text) => {
    setDraft(text);
    // Put the cursor at the end once React has updated the box.
    requestAnimationFrame(() => { element.selectionStart = element.selectionEnd = text.length; });
  };

  const onKeyDown = (event) => {
    if ((event.key !== "ArrowUp" && event.key !== "ArrowDown") || event.shiftKey || event.altKey || event.ctrlKey || event.metaKey) return false;
    const element = event.currentTarget;
    const before = draft.slice(0, element.selectionStart ?? 0);
    const after = draft.slice(element.selectionEnd ?? draft.length);
    if (event.key === "ArrowUp") {
      if (before.includes("\n") || !entries.length) return false;
      if (position.current === null) {
        saved.current = draft;
        position.current = entries.length - 1;
      } else if (position.current > 0) {
        position.current -= 1;
      } else {
        event.preventDefault();
        return true; // already at the oldest question
      }
      event.preventDefault();
      show(element, entries[position.current]);
      return true;
    }
    if (after.includes("\n") || position.current === null) return false;
    event.preventDefault();
    if (position.current < entries.length - 1) {
      position.current += 1;
      show(element, entries[position.current]);
    } else {
      position.current = null;
      show(element, saved.current);
    }
    return true;
  };

  return { remember, onKeyDown };
}

// Closes a chat when the person presses or taps anywhere outside it (the panel and its launcher button).
export function useCloseOnOutsideClick(container, open, close) {
  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (event) => {
      if (container.current && !container.current.contains(event.target)) close();
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [container, open, close]);
}

// Keeps the newest question at the top of the chat with its answer appearing just below it, instead of jumping to the
// end of every answer. Earlier questions and answers stay above, a scroll up away, so they never get mixed up with the
// new one. Room is added below a short answer so the question can still reach the top.
export function useQuestionAtTop(messages, open) {
  const list = useRef(null);
  const asked = useRef(0);
  useLayoutEffect(() => {
    const box = list.current;
    if (!open || !box) { asked.current = 0; return; }
    const questions = box.querySelectorAll(".helpChatMessage.user");
    const question = questions[questions.length - 1];
    const gap = parseFloat(getComputedStyle(box).paddingTop) || 0;
    if (!question) { box.style.paddingBottom = ""; asked.current = 0; return; }
    const top = Math.max(0, question.offsetTop - gap);
    const extra = (parseFloat(box.style.paddingBottom) || gap) - gap;
    const room = top - (box.scrollHeight - extra - box.clientHeight);
    box.style.paddingBottom = `${gap + Math.max(0, room)}px`;
    if (questions.length !== asked.current) {
      box.scrollTo?.({ top, behavior: asked.current ? "smooth" : "auto" });
      asked.current = questions.length;
    }
  }, [messages, open]);
  return list;
}
