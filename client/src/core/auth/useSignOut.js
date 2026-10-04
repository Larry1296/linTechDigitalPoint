import { useAuth } from "./AuthContext";
import { confirmAction } from "../ui/alerts";

export function useSignOut() {
  const { logout } = useAuth();
  return async () => {
    if (
      !(await confirmAction({
        title: "Sign out?",
        text: "You will need to sign in again to access internal operations.",
        confirmButtonText: "Sign out",
        icon: "question",
      }))
    )
      return;
    await logout();
  };
}
