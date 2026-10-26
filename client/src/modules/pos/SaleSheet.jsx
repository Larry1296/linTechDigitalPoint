import { useEffect, useRef } from "react";
import { X } from "lucide-react";

const STEPS = [["review", "Review"], ["pay", "Payment"], ["done", "Done"]];

// The checkout window over the whole till: review the sale, take the payment, then the sale is done. It opens only when the
// cashier asks for it, so products can be picked first. While payment is being taken it cannot be closed; the checkout's own
// Cancel or Change items lets it go.
export function SaleSheet({ step, onClose, children }) {
  const panel = useRef(null);
  useEffect(() => {
    const before = document.activeElement;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    panel.current?.focus();
    return () => { document.body.style.overflow = overflow; before?.focus?.(); };
  }, []);
  useEffect(() => {
    if (!onClose) return undefined;
    const close = (event) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [onClose]);
  const at = STEPS.findIndex(([id]) => id === step);

  return <div className="posSheetBackdrop" role="presentation">
    <div className="posSheet" role="dialog" aria-modal="true" aria-labelledby="pos-sheet-title" tabIndex={-1} ref={panel}>
      <header className="posSheetHead">
        <h2 id="pos-sheet-title">Complete the sale</h2>
        <ol className="posSteps" aria-label="Steps">
          {STEPS.map(([id, name], index) => <li key={id} className={index < at ? "passed" : undefined} aria-current={index === at ? "step" : undefined}>
            <span>{name}</span>
          </li>)}
        </ol>
        {onClose && <button type="button" className="posIconButton" onClick={onClose} aria-label={step === "done" ? "Close" : "Back to products"}><X size={20} /></button>}
      </header>
      {children}
    </div>
  </div>;
}
