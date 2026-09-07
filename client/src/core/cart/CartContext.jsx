import { createContext, useContext, useEffect, useState } from "react";
import { api } from "../api/client";
const CartContext = createContext(null);
export function CartProvider({ children }) {
  const [cart, setCart] = useState(null);
  const refreshCart = async () => setCart(await api("/api/v1/commerce/cart/"));
  useEffect(() => {
    void refreshCart();
  }, []);
  const count =
    cart?.items.reduce((sum, item) => sum + Number(item.quantity), 0) || 0;
  return (
    <CartContext.Provider value={{ cart, count, refreshCart, setCart }}>
      {children}
    </CartContext.Provider>
  );
}
export function useCart() {
  const value = useContext(CartContext);
  if (!value) throw new Error("CartProvider missing");
  return value;
}
