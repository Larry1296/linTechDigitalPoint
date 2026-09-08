import { createContext, useContext, useEffect, useState } from "react";
import { api } from "../api/client";
const CartContext = createContext(null);
export function CartProvider({ children }) {
  const [cart, setCart] = useState(null);
  const refreshCart = async () => setCart(await api("/api/v1/commerce/cart/"));
  const addToCart = async (variantId, quantity = 1) => {
    await api("/api/v1/commerce/cart/", {
      method: "POST",
      body: JSON.stringify({ variant_id: variantId, quantity }),
    });
    await refreshCart();
  };
  useEffect(() => {
    void refreshCart();
  }, []);
  const count =
    cart?.items.reduce((sum, item) => sum + Number(item.quantity), 0) || 0;
  return (
    <CartContext.Provider
      value={{ cart, count, refreshCart, setCart, addToCart }}
    >
      {children}
    </CartContext.Provider>
  );
}
export function useCart() {
  const value = useContext(CartContext);
  if (!value) throw new Error("CartProvider missing");
  return value;
}
