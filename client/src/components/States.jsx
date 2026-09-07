export const Loading = () => (
  <div className="state">
    <span className="spinner" />
    Loading…
  </div>
);
export const Empty = ({ children }) => <div className="state">{children}</div>;
export const ErrorState = ({ message, retry }) => (
  <div className="state error">
    <b>Something went wrong</b>
    <span>{message}</span>
    {retry && <button onClick={retry}>Retry</button>}
  </div>
);
