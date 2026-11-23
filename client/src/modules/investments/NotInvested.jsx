// The business's money not invested yet: what its drawer, till and bank should hold, place by place. Shown on the
// dashboard beside the business's money now, and on the Investments page beside the money in the investments.
// Below zero means more was paid out of a place than the app saw come into it, such as money lent after everything
// was put in an investment: it comes back up as that money is repaid or found.
export function NotInvested({ total, places = [], money, className = "", as: Tag = "article", href }) {
  const amount = Number(total || 0);
  const show = (value) => (Number(value) < 0 ? `− ${money(-Number(value))}` : money(value));
  const holding = places.filter((place) => Math.abs(Number(place.amount)) > 0.004);
  const below = amount < -0.004;
  const words = holding.length
    ? holding.map((place) => `${place.label} ${show(place.amount)}`).join(" · ")
    : "Everything is invested: nothing in the drawer, till or bank";
  return (
    <Tag className={`notInvested${below ? " below" : ""}${className ? ` ${className}` : ""}`} {...(href ? { href } : {})}
      aria-label={`Not invested yet: ${show(amount)}`}>
      <span>Not invested yet</span>
      <strong>{show(amount)}</strong>
      <small>{words}</small>
      {below && <small className="notInvestedWhy">Below zero: more was paid out of {holding.length === 1 ? `the ${holding[0].label.toLowerCase()}` : "these places"} than
        the app saw come in, such as money lent after everything was invested. It comes back up as that money is repaid.</small>}
    </Tag>
  );
}
