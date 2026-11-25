// Barcodes: matching what a camera or scanner read to a product, and drawing barcodes for labels.

// The same product's code as different readers report it: UPC-A is EAN-13 with a leading 0, and some readers drop it.
export function sameCode(a, b) {
  const x = String(a || "").trim().toLowerCase();
  const y = String(b || "").trim().toLowerCase();
  if (!x || !y) return false;
  return x === y || (/^\d+$/.test(x + y) && (`0${x}` === y || x === `0${y}`));
}

export const matchesCode = (row, code) => sameCode(row.barcode, code) || sameCode(row.sku, code);

const L = ["0001101", "0011001", "0010011", "0111101", "0100011", "0110001", "0101111", "0111011", "0110111", "0001011"];
const G = L.map((bits) => [...bits].map((b) => (b === "1" ? "0" : "1")).reverse().join(""));
const R = L.map((bits) => [...bits].map((b) => (b === "1" ? "0" : "1")).join(""));
const PARITY = ["LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG", "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL"];

export function eanCheck(first12) {
  const total = [...first12].reduce((sum, d, i) => sum + Number(d) * (i % 2 ? 3 : 1), 0);
  return String((10 - (total % 10)) % 10);
}

export const isEan13 = (code) => /^\d{13}$/.test(code) && eanCheck(code.slice(0, 12)) === code[12];

// EAN-13 as a string of modules (1 = bar), 95 long: the shortest common barcode, and the easiest for a laptop camera.
export function ean13Modules(code) {
  const parity = PARITY[Number(code[0])];
  let bits = "101";
  for (let i = 1; i <= 6; i += 1) bits += (parity[i - 1] === "L" ? L : G)[Number(code[i])];
  bits += "01010";
  for (let i = 7; i <= 12; i += 1) bits += R[Number(code[i])];
  return `${bits}101`;
}

// Code 128 (set B) for any other code: letters, digits and signs.
const C128 = ["212222", "222122", "222221", "121223", "121322", "131222", "122213", "122312", "132212", "221213", "221312", "231212", "112232",
  "122132", "122231", "113222", "123122", "123221", "223211", "221132", "221231", "213212", "223112", "312131", "311222", "321122", "321221",
  "312212", "322112", "322211", "212123", "212321", "232121", "111323", "131123", "131321", "112313", "132113", "132311", "211313", "231113",
  "231311", "112133", "112331", "132131", "113123", "113321", "133121", "313121", "211331", "231131", "213113", "213311", "213131", "311123",
  "311321", "331121", "312113", "312311", "332111", "314111", "221411", "431111", "111224", "111422", "121124", "121421", "141122", "141221",
  "112214", "112412", "122114", "122411", "142112", "142211", "241211", "221114", "413111", "241112", "134111", "111242", "121142", "121241",
  "114212", "124112", "124211", "411212", "421112", "421211", "212141", "214121", "412121", "111143", "111341", "131141", "114113", "114311",
  "411113", "411311", "113141", "114131", "311141", "411131", "211412", "211214", "211232", "2331112"];

export function code128Modules(text) {
  const values = [...text].map((ch) => Math.min(94, Math.max(0, ch.charCodeAt(0) - 32)));
  const check = (104 + values.reduce((sum, v, i) => sum + v * (i + 1), 0)) % 103;
  return [104, ...values, check, 106].map((v) => [...C128[v]].map((w, i) => (i % 2 ? "0" : "1").repeat(Number(w))).join("")).join("");
}

export const modulesFor = (code) => (isEan13(code) ? ean13Modules(code) : code128Modules(code));
