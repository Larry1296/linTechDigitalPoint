import { businessCurrency } from "../../core/organization/presentation";
import { label } from "../../core/ui/labels";
import { AdjustmentReport } from "../inventory/StockAdjustmentPage";
import { useEffect, useState } from "react";
import { api } from "../../core/api/client";
import { Empty, ErrorState, Loading } from "../../components/States";
import { confirmAction } from "../../core/ui/alerts";
import { DashboardPage } from "./DashboardPage";
import { useLiveRefresh } from "../../core/data/liveRefresh";
export { DashboardPage };
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
  useLiveRefresh(load);
  return { data, error, load };
}
// The till lives in modules/pos; it is still exported from here for the routes.
export { PosPage } from "../pos/PosPage";
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
      <span className="eyebrow">Sales history</span>
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
                  {label(o.status)} · Payment: {label(o.payment_status).toLowerCase()}
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
              <strong>{businessCurrency()} {o.total}</strong>
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
