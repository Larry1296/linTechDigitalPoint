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

const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

// A small form in a dialog. Resolves to {name: value} when confirmed, or null when cancelled. Each field is
// {name, label, type: "text" | "number" | "select", options: [[value, label]], required, placeholder, value, min, max}.
// Required fields and numbers are checked before the dialog closes, with the problem shown in the dialog itself.
export async function askForm({ title, text, fields, confirmButtonText = "Save" }) {
  const control = (field, id) => field.type === "select"
    ? `<select id="${id}" class="swal2-select">${field.options.map(([value, name]) => `<option value="${escape(value)}"${value === field.value ? " selected" : ""}>${escape(name)}</option>`).join("")}</select>`
    : `<input id="${id}" class="swal2-input" type="${field.type === "number" ? "number" : "text"}"${field.type === "number" ? ` step="0.01" min="${escape(field.min ?? "0.01")}"${field.max !== undefined ? ` max="${escape(field.max)}"` : ""} inputmode="decimal"` : ' maxlength="240"'} placeholder="${escape(field.placeholder)}" value="${escape(field.value)}">`;
  const html = `${text ? `<p>${escape(text)}</p>` : ""}${fields.map((field, index) =>
    `<label class="swalField" for="swal-field-${index}">${escape(field.label)}${field.required ? "" : " (optional)"}</label>${control(field, `swal-field-${index}`)}`).join("")}`;
  const result = await Swal.fire({
    title, html, showCancelButton: true, confirmButtonText, cancelButtonText: "Cancel", reverseButtons: true, focusConfirm: false,
    didOpen: () => document.getElementById("swal-field-0")?.focus(),
    preConfirm: () => {
      const values = {};
      for (const [index, field] of fields.entries()) {
        const value = String(document.getElementById(`swal-field-${index}`).value ?? "").trim();
        if (field.required && !value) return Swal.showValidationMessage(`Enter ${field.label.toLowerCase()}.`);
        if (field.type === "number" && value && !(Number(value) > 0)) return Swal.showValidationMessage(`${field.label} must be more than zero.`);
        if (field.type === "number" && value && field.max !== undefined && Number(value) > Number(field.max)) return Swal.showValidationMessage(`${field.label} cannot be more than ${field.max}.`);
        values[field.name] = value;
      }
      return values;
    },
  });
  return result.isConfirmed ? result.value : null;
}
