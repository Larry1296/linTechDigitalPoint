import { isEan13, modulesFor } from "./codes";

// A barcode drawn as SVG, sharp at any print size, with its digits under it.
export function Barcode({ code, height = 46 }) {
  const bits = modulesFor(code);
  const quiet = 9;
  const width = bits.length + quiet * 2;
  const bars = [];
  for (let i = 0; i < bits.length; i += 1) {
    if (bits[i] !== "1") continue;
    let run = 1;
    while (bits[i + run] === "1") run += 1;
    bars.push(<rect key={i} x={quiet + i} y="0" width={run} height={height} />);
    i += run - 1;
  }
  return <svg className="barcodeSvg" viewBox={`0 0 ${width} ${height + 12}`} role="img" aria-label={`Barcode ${code}`} preserveAspectRatio="none">
    <rect width={width} height={height + 12} fill="#fff" />
    <g fill="#000">{bars}</g>
    <text x={width / 2} y={height + 10} textAnchor="middle" fontSize="10" fontFamily="monospace" fill="#000"
      letterSpacing={isEan13(code) ? 1.5 : 0}>{code}</text>
  </svg>;
}
