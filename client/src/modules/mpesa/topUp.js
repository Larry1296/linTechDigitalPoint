// Where a float top-up's money came from, and what it does: drawer cash turned into float lowers the cash by the same
// amount; money from outside the agency (the owner's M-Pesa, the bank) only adds float.
export const TOPUP_SOURCES = [
  ["DRAWER", "Cash from the agency drawer"],
  ["OUTSIDE", "Money from outside the agency (owner, bank)"],
];
