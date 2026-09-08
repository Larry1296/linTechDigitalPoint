import { useId, useState } from "react";
import { Eye, EyeOff } from "lucide-react";

export function PasswordField({ label = "Password", ...props }) {
  const [visible, setVisible] = useState(false);
  const id = useId();
  return (
    <div className="passwordField">
      <label htmlFor={id}>{label}</label>
      <div className="passwordInput">
        <input {...props} id={id} type={visible ? "text" : "password"} />
        <button
          type="button"
          className="passwordToggle"
          aria-label={`${visible ? "Hide" : "Show"} ${label.toLowerCase()}`}
          aria-controls={id}
          onClick={() => setVisible((current) => !current)}
        >
          {visible ? (
            <EyeOff size={20} aria-hidden="true" />
          ) : (
            <Eye size={20} aria-hidden="true" />
          )}
        </button>
      </div>
    </div>
  );
}
