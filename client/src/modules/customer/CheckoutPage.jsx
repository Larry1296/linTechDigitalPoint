import { ProductImage } from "../storefront/components/ProductImage";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../core/api/client";
import { useCart } from "../../core/cart/CartContext";
import { useAuth } from "../../core/auth/AuthContext";
import { ErrorState, Loading } from "../../components/States";
export function CheckoutPage() {
  const { cart, refreshCart } = useCart();
  const { user } = useAuth();
  const [error, setError] = useState("");
  const nav = useNavigate();
  useEffect(() => {
    document.title = "Checkout | LinTech Digital Point";
    refreshCart().catch((e) => setError(e.message));
  }, []);
  if (error)
    return (
      <main>
        <ErrorState message={error} />
      </main>
    );
  if (!cart) return <Loading />;
  const submit = async (e) => {
    e.preventDefault();
    if (!user) {
      nav("/login?next=" + encodeURIComponent("/checkout"));
      return;
    }
    try {
      const order = await api("/api/v1/commerce/checkout/", {
        method: "POST",
        body: JSON.stringify(Object.fromEntries(new FormData(e.currentTarget))),
      });
      await refreshCart();
      nav("/account/orders/" + order.id);
    } catch (err) {
      setError(err.message);
    }
  };
  return (
    <main>
      <h1>Checkout</h1>
      <div className="checkoutGrid">
        <section className="panel">
          <h2>Order review</h2>
          {cart.items.map((i) => (
            <div key={i.id}>
              <ProductImage product={i} />
              {i.display_name} × {i.quantity}
              <b>KSh {i.line_total}</b>
            </div>
          ))}
          <h3>Total: KSh {cart.total}</h3>
        </section>
        <form className="formCard" onSubmit={submit}>
          <label>
            How would you like your order?
            <select name="fulfillment_method">
              <option value="PICKUP">Collect at LinTech</option>
              <option value="DELIVERY">Delivery</option>
            </select>
          </label>
          <label>
            Payment method
            <select name="payment_method">
              <option value="CASH_ON_PICKUP">Cash on pickup</option>
              <option value="MPESA">M-Pesa</option>
              <option value="BANK">Bank</option>
            </select>
          </label>
          <label>
            Order notes
            <textarea name="notes" />
          </label>
          {!user && (
            <p className="callout">
              Sign in or create an account when you are ready to pay and place
              this order. Your cart will stay saved while you do so.
            </p>
          )}
          {error && <p className="formError">{error}</p>}
          <button disabled={!cart.items.length}>
            {user ? "Place order" : "Sign in to place order"}
          </button>
        </form>
      </div>
    </main>
  );
}
