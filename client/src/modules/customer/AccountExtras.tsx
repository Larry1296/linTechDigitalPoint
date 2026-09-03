import { useEffect, useState } from "react";
import { api } from "../../core/api/client";
import { Empty, ErrorState, Loading } from "../../components/States";
type Address = {
  id: number;
  label: string;
  recipient_name: string;
  phone: string;
  county: string;
  town: string;
  address_line: string;
  is_default: boolean;
};
export function AddressesPage() {
  const [rows, setRows] = useState<Address[]>();
  const [error, setError] = useState("");
  const load = () =>
    api<Address[]>("/api/v1/auth/addresses/")
      .then(setRows)
      .catch((e) => setError(e.message));
  useEffect(() => {
    void load();
  }, []);
  const add = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    await api("/api/v1/auth/addresses/", {
      method: "POST",
      body: JSON.stringify(Object.fromEntries(new FormData(e.currentTarget))),
    });
    (e.target as HTMLFormElement).reset();
    load();
  };
  if (error) return <ErrorState message={error} />;
  if (!rows) return <Loading />;
  return (
    <main>
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
        <label>
          Label
          <input name="label" defaultValue="Home" />
        </label>
        <label>
          Recipient
          <input name="recipient_name" required />
        </label>
        <label>
          Phone
          <input name="phone" required />
        </label>
        <label>
          County
          <input name="county" required />
        </label>
        <label>
          Town
          <input name="town" required />
        </label>
        <label>
          Address
          <input name="address_line" required />
        </label>
        <button>Save address</button>
      </form>
    </main>
  );
}
export function PasswordResetPage() {
  const [message, setMessage] = useState("");
  const submit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const result = await api<{ detail: string }>(
      "/api/v1/auth/password/reset/",
      {
        method: "POST",
        body: JSON.stringify(Object.fromEntries(new FormData(e.currentTarget))),
      },
    );
    setMessage(result.detail);
  };
  return (
    <main className="authPage">
      <form className="formCard" onSubmit={submit}>
        <h1>Reset password</h1>
        <label>
          Email
          <input name="email" type="email" required />
        </label>
        <button>Send reset instructions</button>
        {message && <p>{message}</p>}
      </form>
    </main>
  );
}
