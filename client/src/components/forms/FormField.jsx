import { TextBox } from "./TextBox";

/** A labeled control; pass children for selects or custom controls. A text box grows to show all its text. */
export function FormField({ label, children, ...inputProps }) {
  return (
    <label>
      {label}
      {children || <TextBox {...inputProps} />}
    </label>
  );
}
