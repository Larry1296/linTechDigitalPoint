import { useEffect, useId, useRef, useState } from "react";

// A PIN typed on the number keys. It is sent by itself the moment it is as long as the person's PIN, so a lock opens
// with no button to press; a wrong PIN clears the field for the next try. Its error shows in place, never as a dialog
// to close, so the next try can be typed at once.
export function PinField({ label = "PIN", length, busy, error, onPin, autoFocus = true }) {
  const id = useId();
  const input = useRef(null);
  const [value, setValue] = useState("");
  useEffect(() => { if (!busy) input.current?.focus(); }, [busy]);
  const change = async (event) => {
    const next = event.target.value.replace(/\D/g, "").slice(0, length || 6);
    setValue(next);
    if (length && next.length === length) {
      const opened = await onPin(next);
      if (!opened) { setValue(""); input.current?.focus(); }
    }
  };
  return <div className="pinField">
    <label htmlFor={id}>{label}</label>
    <input ref={input} id={id} type="password" inputMode="numeric" pattern="[0-9]*" autoComplete="off" autoFocus={autoFocus}
      maxLength={length || 6} value={value} onChange={change} readOnly={busy} aria-describedby={`${id}-hint`} />
    <small id={`${id}-hint`}>{length ? `${length} digits` : "4 to 6 digits"}</small>
    {error && <div role="alert" className="formNotice formNoticeError">{error}</div>}
  </div>;
}
