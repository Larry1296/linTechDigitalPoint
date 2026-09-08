/** A labeled native control; pass children for selects or custom controls. */
export function FormField({ label, children, ...inputProps }) {
  return (
    <label>
      {label}
      {children || <input {...inputProps} />}
    </label>
  );
}
