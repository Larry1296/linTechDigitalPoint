import { useAuth } from "../../core/auth/AuthContext";
import { ProductActions } from "../products/ProductActions";
import "./pos.css";
import { ProductSearch } from "../storefront/components/ProductSearch";
import { VariantSummary, stockLimit } from "../products/VariantSummary";
import { AdjustmentReport } from "../inventory/StockAdjustmentPage";
import { FormField } from "../../components/forms/FormField";
import { useEffect, useState } from "react";
import { api } from "../../core/api/client";
import { Empty, ErrorState, Loading } from "../../components/States";
import { confirmAction } from "../../core/ui/alerts";
function useLoad(url) {
  const [data, setData] = useState();
  const [error, setError] = useState("");
  const load = () =>
    api(url)
      .then(setData)
      .catch((e) => setError(e.message));
  useEffect(() => {
    void load();
  }, [url]);
  return { data, error, load };
}
export function DashboardPage() {
  const { data, error, load } = useLoad("/api/v1/inventory/dashboard/");
  if (error) return <ErrorState message={error} retry={load} />;
  if (!data) return <Loading />;
  const units = [
    {
      title: "Shop",
      href: "/admin-app/pos",
      metrics: [
        ["Revenue", data.retail.revenue],
        ["Gross profit", data.retail.profit],
        ["Sales", data.retail.sales],
        ["Low stock", data.inventory.low_stock],
      ],
    },
    {
      title: "Cyber",
      href: "/admin-app/cyber",
      metrics: [
        ["Today's revenue", data.cyber.revenue],
        ["Gross profit", data.cyber.profit],
        ["Active jobs", data.cyber.active_jobs],
        ["Ready jobs", data.cyber.ready_jobs],
      ],
    },
    {
      title: "M-Pesa",
      href: "/admin-app/mpesa",
      metrics: [
        ["Cash", data.mpesa.cash],
        ["Float", data.mpesa.float],
        ["Transactions", data.mpesa.transaction_count],
        ["Commission", data.mpesa.commission],
      ],
    },
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
      <div className="callout">
        <div>
          <b>Total recognized business revenue</b>
          <p>Retail + ecommerce + Cyber sales + recognized M-Pesa commission</p>
        </div>
        <strong>KSh {data.today.revenue}</strong>
      </div>
      <div className="businessUnits">
        {units.map((unit) => (
          <a href={unit.href} key={unit.title}>
            <h2>{unit.title}</h2>
            <div className="metrics">
              {unit.metrics.map(([label, value]) => (
                <article key={label}>
                  <span>{label}</span>
                  <strong>
                    {[
                      "Sales",
                      "Low stock",
                      "Active jobs",
                      "Ready jobs",
                      "Transactions",
                    ].includes(label)
                      ? value
                      : `KSh ${value}`}
                  </strong>
                </article>
              ))}
            </div>
          </a>
        ))}
      </div>
    </>
  );
}
export function PosPage() {
  const { user } = useAuth();
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState([]);
  const [cart, setCart] = useState([]);
  const [result, setResult] = useState();
  const [error, setError] = useState("");
  const search = () =>
    api("/api/v1/commerce/pos/catalog/?q=" + encodeURIComponent(""))
      .then(setRows)
      .catch((e) => setError(e.message));
  useEffect(() => {
    void search();
  }, []);
  const add = (p) => {
    setCart((old) => {
      const current = old.find((x) => x.p.id === p.id);
      if ((current?.q || 0) + 1 > stockLimit(p)) return old;
      return current
        ? old.map((x) => (x.p.id === p.id ? { p, q: x.q + 1 } : x))
        : [...old, { p, q: 1 }];
    });
    setQuery("");
  };
  const groups = Object.groupBy(rows, (p) =>
    p.product_type === "SERVICE"
      ? "Services"
      : p.category_name || "Uncategorised",
  );
  const complete = async (e) => {
    e.preventDefault();
    const form = Object.fromEntries(new FormData(e.currentTarget));
    if (
      !(await confirmAction({
        title: "Complete this sale?",
        text: `Charge KSh ${cart.reduce((sum, item) => sum + Number(item.p.selling_price) * item.q, 0).toFixed(2)} and update stock?`,
        confirmButtonText: "Complete sale",
      }))
    )
      return;
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
      await search();
    } catch (err) {
      setError(err.message);
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
          <ProductSearch
            value={query}
            onChange={setQuery}
            endpoint="/api/v1/commerce/pos/catalog/"
            onSelect={add}
            exactScan
            isDisabled={(p) => stockLimit(p) < 1}
            renderResult={(p) => <VariantSummary row={p} />}
            renderActions={(p) => <ProductActions row={p} user={user} />}
            placeholder="Scan barcode, SKU or search products"
          />
          {!query.trim() &&
            Object.entries(groups)
              .sort(([a], [b]) =>
                a === "Services"
                  ? 1
                  : b === "Services"
                    ? -1
                    : a.localeCompare(b),
              )
              .map(([category, products]) => (
                <section key={category}>
                  <h2>{category}</h2>
                  <div className="posCatalogue">
                    {products.map((p) => (
                      <article key={p.id}>
                        <button
                          disabled={stockLimit(p) < 1}
                          onClick={() => add(p)}
                        >
                          <VariantSummary row={p} />
                        </button>
                        <ProductActions row={p} user={user} />
                      </article>
                    ))}
                  </div>
                </section>
              ))}
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
                  max={
                    Number.isFinite(stockLimit(x.p))
                      ? stockLimit(x.p)
                      : undefined
                  }
                  value={x.q}
                  onChange={(e) =>
                    setCart((c) =>
                      c.map((y) =>
                        y.p.id === x.p.id
                          ? {
                              ...y,
                              q: Math.max(
                                1,
                                Math.min(
                                  stockLimit(y.p),
                                  Number(e.target.value) || 1,
                                ),
                              ),
                            }
                          : y,
                      ),
                    )
                  }
                />
                <span>KSh {+x.p.selling_price * x.q}</span>
              </article>
            ))
          )}
          <FormField
            label="Discount"
            name="discount"
            type="number"
            defaultValue="0"
          />
          <label>
            Payment
            <select name="payment_method">
              <option>CASH</option>
              <option>MPESA</option>
              <option>BANK</option>
              <option>OTHER</option>
            </select>
          </label>
          <FormField label="Payment reference" name="payment_reference" />
          <button disabled={!cart.length}>Complete sale</button>
        </form>
      </div>
    </>
  );
}
export function StaffOrdersPage() {
  const { data, error, load } = useLoad("/api/v1/commerce/staff/orders/");
  if (error) return <ErrorState message={error} retry={load} />;
  if (!data) return <Loading />;
  const complete = async (o) => {
    if (
      !(await confirmAction({
        title: `Complete order ${o.number}?`,
        text: "This confirms payment and consumes the reserved stock.",
        confirmButtonText: "Complete order",
      }))
    )
      return;
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
      <AdjustmentReport />
    </>
  );
}
