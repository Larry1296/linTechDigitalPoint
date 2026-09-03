import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { useCart } from "../../core/cart/CartContext";
import { Empty, ErrorState, Loading } from "../../components/States";
import type { Order } from "../../types";
export function AccountPage() {
  const { user } = useAuth();
  const { cart } = useCart();
  return (
    <main>
      <span className="eyebrow">Customer account</span>
      <h1>Hello, {user?.first_name || user?.username}</h1>
      {cart?.items.length ? (
        <section className="panel accountCart">
          <div className="heading">
            <div>
              <span className="eyebrow">Continue where you left off</span>
              <h2>Your shopping cart</h2>
            </div>
            <strong>KSh {cart.total}</strong>
          </div>
          <div className="list">
            {cart.items.map((item) => (
              <article key={item.id}>
                <div>
                  <b>{item.product_name}</b>
                  <small>
                    {item.variant_name} · SKU {item.sku}
                  </small>
                </div>
                <span>Qty {item.quantity}</span>
                <strong>KSh {item.line_total}</strong>
              </article>
            ))}
          </div>
          <div className="cardActions">
            <Link className="button secondary" to="/shop">
              Continue shopping
            </Link>
            <Link className="button" to="/checkout">
              Continue to checkout
            </Link>
          </div>
        </section>
      ) : (
        <section className="callout">
          <div>
            <h2>Ready to shop?</h2>
            <p>Your cart will remain available when you return.</p>
          </div>
          <Link className="button" to="/shop">
            Browse the shop
          </Link>
        </section>
      )}
      <div className="cards">
        <Link className="panel" to="/account/orders">
          <h2>Your orders</h2>
          <p>Track payments and fulfillment.</p>
        </Link>
        <Link className="panel" to="/account/addresses">
          <h2>Addresses</h2>
          <p>Manage delivery details.</p>
        </Link>
      </div>
    </main>
  );
}
export function OrdersPage() {
  const [rows, setRows] = useState<Order[]>();
  const [error, setError] = useState("");
  useEffect(() => {
    api<Order[]>("/api/v1/commerce/orders/")
      .then(setRows)
      .catch((e) => setError(e.message));
  }, []);
  if (error) return <ErrorState message={error} />;
  if (!rows) return <Loading />;
  return (
    <main>
      <h1>Your orders</h1>
      {!rows.length ? (
        <Empty>No orders yet.</Empty>
      ) : (
        <div className="list">
          {rows.map((o) => (
            <Link to={"/account/orders/" + o.id} key={o.id}>
              <b>{o.number}</b>
              <span>{o.status}</span>
              <strong>KSh {o.total}</strong>
            </Link>
          ))}
        </div>
      )}
    </main>
  );
}
export function OrderDetailPage() {
  const { id } = useParams();
  const [row, setRow] = useState<Order>();
  const [error, setError] = useState("");
  useEffect(() => {
    api<Order>("/api/v1/commerce/orders/" + id + "/")
      .then(setRow)
      .catch((e) => setError(e.message));
  }, [id]);
  if (error) return <ErrorState message={error} />;
  if (!row) return <Loading />;
  return (
    <main>
      <span className="eyebrow">Order</span>
      <h1>{row.number}</h1>
      <div className="statusRow">
        <b>{row.status}</b>
        <span>Payment: {row.payment_status}</span>
        <span>Fulfillment: {row.fulfillment_status}</span>
      </div>
      <div className="list">
        {row.items.map((i) => (
          <article key={i.id}>
            <b>{i.product_name}</b>
            <span>
              {i.variant_name} × {i.quantity}
            </span>
            <strong>KSh {i.unit_price}</strong>
          </article>
        ))}
      </div>
      <h2>Total KSh {row.total}</h2>
    </main>
  );
}
