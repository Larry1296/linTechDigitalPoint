import { FormField } from "../../components/forms/FormField";
import { useEffect, useState } from "react";
import { api } from "../../core/api/client";
import { Empty, ErrorState, Loading } from "../../components/States";
export function AddressesPage() {
  const [rows, setRows] = useState();
  const [error, setError] = useState("");
  const load = () =>
    api("/api/v1/auth/addresses/")
      .then(setRows)
      .catch((e) => setError(e.message));
  useEffect(() => {
    void load();
  }, []);
  const add = async (e) => {
    e.preventDefault();
    await api("/api/v1/auth/addresses/", {
      method: "POST",
      body: JSON.stringify(Object.fromEntries(new FormData(e.currentTarget))),
    });
    e.target.reset();
    load();
  };
  if (error) return <ErrorState message={error} />;
  if (!rows) return <Loading />;
  return (
    <>
      <h1>Addresses</h1>
      {!rows.length && <Empty>No saved addresses.</Empty>}
      <div className="list">
        {rows.map((a) => (
          <article key={a.id}>
            <b>{a.label}</b>
            <span>
              {a.recipient_name} · {a.phone}
            </span>
            <span>
              {a.address_line}, {a.town}, {a.county}
            </span>
          </article>
        ))}
      </div>
      <form className="formCard" onSubmit={add}>
        <h2>Add address</h2>
        <FormField label="Label" name="label" defaultValue="Home" />
        <FormField label="Recipient" name="recipient_name" required />
        <FormField label="Phone" name="phone" required />
        <FormField label="County" name="county" required />
        <FormField label="Town" name="town" required />
        <FormField label="Address" name="address_line" required />
        <button>Save address</button>
      </form>
    </>
  );
}
export function PasswordResetPage() {
  const [message, setMessage] = useState("");
  const submit = async (e) => {
    e.preventDefault();
    const result = await api("/api/v1/auth/password/reset/", {
      method: "POST",
      body: JSON.stringify(Object.fromEntries(new FormData(e.currentTarget))),
    });
    setMessage(result.detail);
  };
  return (
    <main className="authPage">
      <form className="formCard" onSubmit={submit}>
        <h1>Reset password</h1>
        <FormField label="Email" name="email" type="email" required />
        <button>Send reset instructions</button>
        {message && <p>{message}</p>}
      </form>
    </main>
  );
}
