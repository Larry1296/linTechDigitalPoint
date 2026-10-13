import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

// A password box, also while its "show password" eye has turned it into plain text.
const isPassword = (element) => element instanceof HTMLInputElement && (element.type === "password" || element.dataset.password === "true");

/** One watcher for the whole app: while a password box has the cursor and Caps Lock is on, a note shows just under it,
 * so a password is never typed in capitals by mistake. Mounted once; nothing is needed on each password field. */
export function CapsLockWarning() {
  const [box, setBox] = useState(null);
  useEffect(() => {
    let input = null;
    let on = false;
    const place = () => {
      if (!input || !on || !document.contains(input)) { setBox(null); return; }
      const rect = input.getBoundingClientRect();
      setBox({ top: rect.bottom + 6, left: rect.left, width: rect.width });
    };
    const read = (event) => {
      if (!isPassword(event.target) || typeof event.getModifierState !== "function") return;
      input = event.target;
      // Pressing Caps Lock itself: its keydown can still report the old state, so take it from the keyup.
      if (event.type === "keydown" && event.key === "CapsLock") return;
      on = event.getModifierState("CapsLock");
      place();
    };
    const leave = (event) => { if (event.target === input) { input = null; place(); } };
    const events = ["keydown", "keyup", "mousedown"];
    events.forEach((type) => document.addEventListener(type, read, true));
    document.addEventListener("focusout", leave, true);
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      events.forEach((type) => document.removeEventListener(type, read, true));
      document.removeEventListener("focusout", leave, true);
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, []);
  if (!box) return null;
  return createPortal(
    <p className="capsLockWarning" role="status" style={{ top: box.top, left: box.left, maxWidth: Math.max(box.width, 200) }}>
      <b>Caps Lock is on.</b> Passwords know capital from small letters.
    </p>,
    document.body,
  );
}
