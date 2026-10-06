// How the customer paid, and what it does to cash and float. The airtime itself always comes out of the float.
export const AIRTIME_PAID_BY = [
  { id: "CASH", label: "Cash", hint: "Cash goes up, float goes down.", effect: (v) => [v, -v] },
  { id: "MPESA_FLOAT", label: "M-Pesa to this agent line", hint: "The payment comes back into the float, so nothing changes.", effect: () => [0, 0] },
  { id: "MPESA_OTHER", label: "M-Pesa to another number", hint: "Paid to your till or phone: the float goes down and that money is no longer in the agency.", effect: (v) => [0, -v] },
];
export const paidByLabel = (id) => AIRTIME_PAID_BY.find((option) => option.id === id)?.label || "";
