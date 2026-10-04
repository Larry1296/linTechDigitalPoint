// Form outcomes sit directly below the submit button, where the person is looking.
export function FormError({ title, message }) {
  if (!message) return null;
  return <div role="alert" className="formNotice formNoticeError">{title && <><strong>{title}</strong>{" "}</>}{message}</div>;
}

export function FormSuccess({ message, children }) {
  if (!message && !children) return null;
  return <div role="status" className="formNotice formNoticeSuccess">{message}{children}</div>;
}

export function FormInfo({ children }) {
  return <div role="status" className="formNotice formNoticeInfo">{children}</div>;
}
