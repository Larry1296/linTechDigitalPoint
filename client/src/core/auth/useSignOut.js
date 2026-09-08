import { useAuth } from "./AuthContext";
import { useCart } from "../cart/CartContext";
import { confirmAction } from "../ui/alerts";

export function useSignOut() {
  const { logout } = useAuth();
  const { refreshCart } = useCart();
  return async () => {
    if (
      !(await confirmAction({
        title: "Sign out?",
        text: "You will need to sign in again to access your account.",
        confirmButtonText: "Sign out",
        icon: "question",
      }))
    )
      return;
    await logout();
    await refreshCart();
  };
}
