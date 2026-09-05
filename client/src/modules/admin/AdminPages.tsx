import { useEffect, useState } from "react";
import { api } from "../../core/api/client";
import { Empty, ErrorState, Loading } from "../../components/States";
import type { Order } from "../../types";
function useLoad<T>(url: string) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState("");
  const load = () =>
    api<T>(url)
      .then(setData)
      .catch((e) => setError(e.message));
  useEffect(() => {
    void load();
  }, [url]);
  return { data, error, load };
}
export function DashboardPage() {
  const { data, error, load } = useLoad<any>("/api/v1/inventory/dashboard/");
  if (error) return <ErrorState message={error} retry={load} />;
  if (!data) return <Loading />;
  const units = [
    { title: "Shop", href: "/admin-app/pos", metrics: [["Revenue", data.retail.revenue], ["Gross profit", data.retail.profit], ["Sales", data.retail.sales], ["Low stock", data.inventory.low_stock]] },
    { title: "Cyber", href: "/admin-app/cyber", metrics: [["Today's revenue", data.cyber.revenue], ["Gross profit", data.cyber.profit], ["Active jobs", data.cyber.active_jobs], ["Ready jobs", data.cyber.ready_jobs]] },
    { title: "M-Pesa", href: "/admin-app/mpesa", metrics: [["Cash", data.mpesa.cash], ["Float", data.mpesa.float], ["Transactions", data.mpesa.transaction_count], ["Commission", data.mpesa.commission]] },
  ];
  return (
    <>
      <span className="eyebrow">Live business data</span>
      <h1>Dashboard</h1>
      {data.inventory.total_skus === 0 && (
        <div className="callout">
          <div>
            <b>Set up your physical shop</b>
            <p>
              Teach LinTech where the existing shelves and stock are located.
            </p>
          </div>
          <a className="button" href="/admin-app/digital-shop">
            Configure Digital Shop
          </a>
        </div>
      )}
      <div className="callout"><div><b>Total recognized business revenue</b><p>Retail + ecommerce + Cyber sales + recognized M-Pesa commission</p></div><strong>KSh {data.today.revenue}</strong></div>
      <div className="businessUnits">{units.map((unit) => <a href={unit.href} key={unit.title}><h2>{unit.title}</h2><div className="metrics">{unit.metrics.map(([label, value]) => <article key={label}><span>{label}</span><strong>{["Sales", "Low stock", "Active jobs", "Ready jobs", "Transactions"].includes(label as string) ? value : `KSh ${value}`}</strong></article>)}</div></a>)}</div>
    </>
  );
}
type PosProduct = {
  id: number;
  product_name: string;
  variant_name: string;
  sku: string;
  barcode: string;
  product_type: string;
  selling_price: string;
  available: string;
  locations: {
    zone: string;
    stack: string | null;
    level: number | null;
    shelf_code: string;
    shelf_name: string;
    available: string;
  }[];
};
export function PosPage() {
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState<PosProduct[]>([]);
  const [cart, setCart] = useState<{ p: PosProduct; q: number }[]>([]);
  const [result, setResult] = useState<any>();
  const [error, setError] = useState("");
  const search = () =>
    api<PosProduct[]>(
      "/api/v1/commerce/pos/catalog/?q=" + encodeURIComponent(query),
    )
      .then(setRows)
      .catch((e) => setError(e.message));
  useEffect(() => {
    void search();
  }, []);
  const add = (p: PosProduct) =>
    setCart((old) =>
      old.some((x) => x.p.id === p.id)
        ? old.map((x) => (x.p.id === p.id ? { ...x, q: x.q + 1 } : x))
        : [...old, { p, q: 1 }],
    );
  const complete = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = Object.fromEntries(new FormData(e.currentTarget));
    try {
      setResult(
        await api("/api/v1/commerce/pos/complete/", {
          method: "POST",
          body: JSON.stringify({
            ...form,
            items: cart.map((x) => ({ variant_id: x.p.id, quantity: x.q })),
            idempotency_key: crypto.randomUUID(),
          }),
        }),
      );
      setCart([]);
    } catch (err) {
      setError((err as Error).message);
    }
  };
  return (
    <>
      <span className="eyebrow">Counter selling</span>
      <h1>Point of Sale</h1>
      {result && (
        <div className="callout receipt">
          <div>
            <b>Sale complete · {result.receipt_number}</b>
            <p>Total KSh {result.total}</p>
          </div>
          <button onClick={() => window.print()}>Print receipt</button>
        </div>
      )}
      {error && <p className="formError">{error}</p>}
      <div className="posGrid">
        <section>
          <form
            className="search"
            onSubmit={(e) => {
              e.preventDefault();
              search();
            }}
          >
            <input
              autoFocus
              aria-label="Scan barcode or search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Scan barcode, SKU or product"
            />
            <button>Search</button>
          </form>
          <div className="productList">
            {rows.map((p) => (
              <button key={p.id} onClick={() => add(p)}>
                <div>
                  <b>{p.product_name}</b>
                  <small>
                    {p.variant_name} · {p.sku}
                  </small>
                </div>
                <span>KSh {p.selling_price}</span>
                <small>
                  {p.product_type === "SERVICE"
                    ? "Service"
                    : p.available + " available"}
                </small>
                {p.locations.map((l) => (
                  <em key={l.shelf_code}>
                    {l.zone} → {l.stack || "Unassigned stack"} → Level{" "}
                    {l.level || "—"} → {l.shelf_code} — {l.available}
                  </em>
                ))}
              </button>
            ))}
          </div>
        </section>
        <form className="saleCart" onSubmit={complete}>
          <h2>Current sale</h2>
          {!cart.length ? (
            <Empty>Scan or select an item.</Empty>
          ) : (
            cart.map((x) => (
              <article key={x.p.id}>
                <b>{x.p.product_name}</b>
                <input
                  type="number"
                  min="1"
                  value={x.q}
                  onChange={(e) =>
                    setCart((c) =>
                      c.map((y) =>
                        y.p.id === x.p.id ? { ...y, q: +e.target.value } : y,
                      ),
                    )
                  }
                />
                <span>KSh {+x.p.selling_price * x.q}</span>
              </article>
            ))
          )}
          <label>
            Discount
            <input name="discount" type="number" defaultValue="0" />
          </label>
          <label>
            Payment
            <select name="payment_method">
              <option>CASH</option>
              <option>MPESA</option>
              <option>BANK</option>
              <option>OTHER</option>
            </select>
          </label>
          <label>
            Payment reference
            <input name="payment_reference" />
          </label>
          <button disabled={!cart.length}>Complete sale</button>
        </form>
      </div>
    </>
  );
}
export function StaffOrdersPage() {
  const { data, error, load } = useLoad<Order[]>(
    "/api/v1/commerce/staff/orders/",
  );
  if (error) return <ErrorState message={error} retry={load} />;
  if (!data) return <Loading />;
  const complete = async (o: Order) => {
    await api("/api/v1/commerce/staff/orders/" + o.id + "/complete/", {
      method: "POST",
      body: JSON.stringify({
        payment_method: o.payment_method || "CASH",
        idempotency_key: "fulfill:" + o.number,
      }),
    });
    load();
  };
  return (
    <>
      <span className="eyebrow">Ecommerce fulfillment</span>
      <h1>Orders</h1>
      {!data.length ? (
        <Empty>No online orders.</Empty>
      ) : (
        <div className="list">
          {data.map((o) => (
            <article key={o.id}>
              <div>
                <b>{o.number}</b>
                <small>
                  {o.status} · {o.payment_status}
                </small>
                {o.items.map((i) => (
                  <p key={i.id}>
                    {i.product_name} × {i.quantity}
                    {i.pick_locations?.map((a) => (
                      <em key={a.shelf_id}>
                        {" "}
                        · Pick {a.quantity} from {a.zone} →{" "}
                        {a.stack || "Unassigned stack"} → Level {a.level || "—"}{" "}
                        → {a.shelf_code}
                      </em>
                    ))}
                  </p>
                ))}
              </div>
              <strong>KSh {o.total}</strong>
              {!["PAID", "COMPLETED"].includes(o.status) && (
                <button onClick={() => void complete(o)}>
                  Confirm payment & consume reservation
                </button>
              )}
            </article>
          ))}
        </div>
      )}
    </>
  );
}
export function AnalyticsPage() {
  return (
    <>
      <span className="eyebrow">Reporting</span>
      <h1>Analytics</h1>
      <DashboardPage />
    </>
  );
}
