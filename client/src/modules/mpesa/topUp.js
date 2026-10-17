// Where float or cash added to the agency came from. Each part of the business keeps its own money: the agency's own
// drawer cash turned into float lowers its cash; another part's money (the shop's or cyber's, from the drawer, till or
// bank) goes down by the same amount; money from outside the business is the owner's money put in.
export const TOPUP_SOURCES = [
  ["DRAWER", "The agency's own cash in the drawer"],
  ["OUTSIDE", "Outside the business (owner's pocket, a loan)"],
];

// The choices for a float top-up (with the agency's own drawer cash) or a cash rebalance (without it), with each other
// part's money and how much it has now.
export function sourceChoices(sources, amount, { withDrawer }) {
  const parts = (sources || []).map((source) => [source.value, `${source.label} (${amount(source.available)} there now)`]);
  return [["", "Choose…"], ...(withDrawer ? [TOPUP_SOURCES[0]] : []), ...parts, TOPUP_SOURCES[1]];
}
