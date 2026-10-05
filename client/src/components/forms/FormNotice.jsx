import { useEffect } from "react";
import { showOutcome } from "../../core/ui/outcome";

// Form outcomes sit directly below the submit button, where the person is looking, and also open full screen.
export function FormError({ title, message }) {
  useEffect(() => { if (message) void showOutcome("error", title || "Something went wrong", message); }, [title, message]);
  if (!message) return null;
  return <div role="alert" className="formNotice formNoticeError">{title && <><strong>{title}</strong>{" "}</>}{message}</div>;
}

export function FormSuccess({ message, children }) {
  useEffect(() => { if (message) void showOutcome("success", "Done", message); }, [message]);
  if (!message && !children) return null;
  return <div role="status" className="formNotice formNoticeSuccess">{message}{children}</div>;
}

export function FormInfo({ children }) {
  return <div role="status" className="formNotice formNoticeInfo">{children}</div>;
}
