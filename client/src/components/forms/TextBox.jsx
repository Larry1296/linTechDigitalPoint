import { useCallback, useLayoutEffect, useRef } from "react";

// Grows the box to fit what is in it, so every word shows without scrolling. Browsers that size a field to its content
// themselves (CSS field-sizing) do it already; this keeps the others the same.
// Hands the box to a ref passed in from outside, whether a callback or a ref object.
function assignRef(target, node) {
  if (typeof target === "function") target(node);
  else if (target) target.current = node;
}

function useFitHeight(outerRef, value) {
  const ref = useRef(null);
  const fit = useCallback(() => {
    const box = ref.current;
    if (!box) return;
    box.style.height = "auto";
    const edges = box.offsetHeight - box.clientHeight;  // borders
    box.style.height = `${box.scrollHeight + edges}px`;
  }, []);
  useLayoutEffect(fit, [fit, value]);
  // Width changes (a phone turned, a panel opened) rewrap the text.
  useLayoutEffect(() => {
    const box = ref.current;
    if (!box || typeof ResizeObserver === "undefined") return undefined;
    let width = box.clientWidth;
    const watch = new ResizeObserver(() => {
      if (box.clientWidth !== width) { width = box.clientWidth; fit(); }
    });
    watch.observe(box);
    return () => watch.disconnect();
  }, [fit]);
  const setRef = useCallback((node) => {
    ref.current = node;
    assignRef(outerRef, node);
  }, [outerRef]);
  return { setRef, fit };
}

/** A box for several lines (notes, messages): it grows with the text instead of scrolling. */
export function TextArea({ ref, rows = 2, onInput, value, className, ...props }) {
  const { setRef, fit } = useFitHeight(ref, value);
  return <textarea {...props} ref={setRef} rows={rows} value={value} className={["autoGrow", className].filter(Boolean).join(" ")}
    onInput={(event) => { fit(); onInput?.(event); }} />;
}

/**
 * A one-line text box whose text wraps onto more lines when it is long, so it is all visible. It behaves like a text
 * input: Enter submits the form (no new line), and pasted line breaks become spaces. Boxes that need an input's own
 * features (a suggestion list or a pattern) stay inputs.
 */
export function TextBox({ ref, type, list, pattern, onKeyDown, onChange, onInput, value, className, ...props }) {
  const { setRef, fit } = useFitHeight(ref, value);
  if ((type && type !== "text") || list || pattern) {
    return <input {...props} ref={ref} type={type} list={list} pattern={pattern} value={value} className={className}
      onKeyDown={onKeyDown} onChange={onChange} onInput={onInput} />;
  }
  const keyDown = (event) => {
    onKeyDown?.(event);
    if (event.defaultPrevented || event.key !== "Enter" || event.shiftKey || event.nativeEvent?.isComposing) return;
    event.preventDefault();
    // As a text input does: Enter sends the form when it has a submit button, or when this is its only box.
    const form = event.currentTarget.form;
    if (!form) return;
    const submit = form.querySelector("button:not([type=button]):not([type=reset]), input[type=submit]");
    const boxes = form.querySelectorAll("input:not([type=hidden]):not([type=checkbox]):not([type=radio]), textarea, select");
    if (submit?.disabled) return;
    if (submit || boxes.length === 1) form.requestSubmit(submit || undefined);
  };
  const change = (event) => {
    // One line only: line breaks pasted in become spaces.
    if (/[\r\n]/.test(event.target.value)) event.target.value = event.target.value.replace(/\r?\n|\r/g, " ");
    onChange?.(event);
  };
  return <textarea {...props} ref={setRef} rows={1} value={value} data-single-line="true"
    className={["autoGrow", "textBox", className].filter(Boolean).join(" ")}
    onKeyDown={keyDown} onChange={change} onInput={(event) => { fit(); onInput?.(event); }} />;
}
