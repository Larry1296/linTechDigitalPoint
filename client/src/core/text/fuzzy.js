// Forgiving name matching for item search: the words typed need not be spelt exactly. Each typed word must be found
// in the item's text, either as written or with a small slip (a wrong, missing, extra or swapped letter), and the
// closest items come first. server/apps/core/fuzzy.py matches the same way for searches done on the server.
const words = (text) => String(text ?? "").toLowerCase().split(/[^0-9a-z]+/).filter(Boolean);

function distance(a, b) {
  let prev2 = null, prev = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    for (let j = 1; j <= b.length; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost);
      if (prev2 && i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) cur[j] = Math.min(cur[j], prev2[j - 2] + 1);
    }
    prev2 = prev; prev = cur;
  }
  return prev[b.length];
}

const allowed = (word) => (word.length <= 2 ? 0 : word.length <= 5 ? 1 : 2);

function wordScore(word, tokens, joined) {
  if (joined.includes(word)) return 1;
  const most = allowed(word);
  if (!most) return null;
  let best = null;
  for (const token of tokens) {
    // Compare with the whole word and with its start, so a half-typed word with a slip still finds it.
    const d = Math.min(distance(word, token), distance(word, token.slice(0, word.length)));
    if (d <= most && (best === null || d < best)) best = d;
  }
  return best === null ? null : 1 - best / (2 * word.length);
}

/** null when the item does not match; otherwise 0..1, higher is closer. An empty query matches everything. */
export function fuzzyScore(query, ...texts) {
  const typed = words(query);
  if (!typed.length) return 1;
  const tokens = texts.flatMap(words);
  const joined = `${tokens.join(" ")} ${tokens.join("")}`;
  let total = 0;
  for (const word of typed) {
    const score = wordScore(word, tokens, joined);
    if (score === null) return null;
    total += score;
  }
  return total / typed.length;
}
