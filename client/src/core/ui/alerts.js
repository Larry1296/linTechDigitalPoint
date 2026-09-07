import Swal from "sweetalert2";
import "sweetalert2/dist/sweetalert2.min.css";

export async function confirmAction({
  title,
  text,
  confirmButtonText = "Confirm",
  icon = "warning",
}) {
  const result = await Swal.fire({
    title,
    text,
    icon,
    showCancelButton: true,
    confirmButtonText,
    cancelButtonText: "Cancel",
    reverseButtons: true,
    focusCancel: true,
  });
  return result.isConfirmed;
}

export function showSuccess(title, text) {
  return Swal.fire({ title, text, icon: "success", confirmButtonText: "Done" });
}

export function showError(title, text) {
  return Swal.fire({ title, text, icon: "error", confirmButtonText: "Close" });
}
