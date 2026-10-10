import { Fragment } from "react";
import { Link } from "react-router-dom";

// A small, safe Markdown renderer for assistant answers. It builds React elements only (never raw HTML), so text from
// the model or from business records cannot inject markup. Supported: paragraphs, ### headings, bulleted and numbered
// lists (nested by indenting), tables, > callouts, --- dividers, **bold**, *italic*, `code` and links.

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\)|(?<![\w*])\*[^*\s][^*]*\*(?![\w*])|(?<![\w_])_[^_\s][^_]*_(?![\w_]))/g;

// Bold, italic, code and links. Only our own pages (relative) and https links become clickable.
export function inline(text) {
  return text.split(INLINE).map((part, index) => {
    if (!part) return null;
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) return <strong key={index}>{inline(part.slice(2, -2))}</strong>;
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) return <code key={index}>{part.slice(1, -1)}</code>;
    const link = part.match(/^\[([^\]]+)\]\(([^)\s]+)\)$/);
    if (link && link[2].startsWith("/") && !link[2].startsWith("//")) return <Link key={index} to={link[2]}>{link[1]}</Link>;
    if (link && link[2].startsWith("https://")) return <a key={index} href={link[2]} target="_blank" rel="noreferrer">{link[1]}</a>;
    if (link) return <Fragment key={index}>{link[1]}</Fragment>;
    if (/^([*_]).+\1$/.test(part)) return <em key={index}>{part.slice(1, -1)}</em>;
    return <Fragment key={index}>{part}</Fragment>;
  });
}

const cells = (line) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
const isDivider = (line) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line);
const LIST = /^(\s*)(\d+[.)]|[-*•])\s+(.*)$/;
const NUMBER = /^[-−+]?\s*(?:[A-Z]{2,4}\s*)?[\d,.]+\s*%?$|^[\d,.]+\s*(?:units?|%)?$/;

// Blocks from the text: each is a heading, paragraph, list, table, callout, note or divider.
export function parse(text) {
  const lines = text.replace(/\r/g, "").split("\n");
  const blocks = [];
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    const trimmed = line.trim();
    if (!trimmed) { blocks.push({ kind: "gap" }); continue; }
    const heading = trimmed.match(/^#{1,4}\s+(.*)$/);
    if (heading) { blocks.push({ kind: "heading", text: heading[1].replace(/\s*#+$/, "") }); continue; }
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) { blocks.push({ kind: "divider" }); continue; }
    if (trimmed.startsWith("|") && isDivider(lines[i + 1] || "")) {
      const head = cells(trimmed);
      const rows = [];
      i += 2;
      while (i < lines.length && lines[i].trim().startsWith("|")) { rows.push(cells(lines[i])); i += 1; }
      i -= 1;
      blocks.push({ kind: "table", head, rows });
      continue;
    }
    if (trimmed.startsWith(">")) {
      const last = blocks.at(-1);
      const content = trimmed.replace(/^>\s?/, "");
      if (last?.kind === "callout") last.lines.push(content);
      else blocks.push({ kind: "callout", lines: [content] });
      continue;
    }
    // A whole line in _italics_ is a side note (e.g. how the answer was produced).
    if (/^_\(?[^_]+\)?_$/.test(trimmed)) { blocks.push({ kind: "note", text: trimmed.slice(1, -1).replace(/^\((.*)\)$/, "$1") }); continue; }
    const item = line.match(LIST);
    if (item) {
      const depth = Math.min(Math.floor(item[1].replace(/\t/g, "  ").length / 2), 2);
      const ordered = /\d/.test(item[2]);
      const last = blocks.at(-1);
      if (last?.kind === "list") last.items.push({ depth, ordered, text: item[3] });
      else blocks.push({ kind: "list", items: [{ depth, ordered, text: item[3] }] });
      continue;
    }
    const last = blocks.at(-1);
    // A line straight after a list item, indented, continues that item.
    if (last?.kind === "list" && /^\s{2,}\S/.test(line)) { last.items.at(-1).text += ` ${trimmed}`; continue; }
    if (last?.kind === "paragraph") last.lines.push(trimmed);
    else blocks.push({ kind: "paragraph", lines: [trimmed] });
  }
  return blocks.filter((block) => block.kind !== "gap");
}

// Items at depth 0 with their nested children, as nested lists.
function List({ items }) {
  const tree = [];
  for (const item of items) {
    let level = tree;
    for (let d = 0; d < item.depth && level.length; d += 1) level = level.at(-1).children;
    level.push({ ...item, children: [] });
  }
  const render = (nodes, key) => {
    const Tag = nodes[0]?.ordered ? "ol" : "ul";
    return <Tag key={key}>{nodes.map((node, index) => <li key={index}>{inline(node.text)}{node.children.length > 0 && render(node.children, "sub")}</li>)}</Tag>;
  };
  return render(tree, "list");
}

function Table({ head, rows }) {
  // Columns whose cells are all numbers or money line up on the right.
  const numeric = head.map((_, col) => rows.length > 0 && rows.every((row) => !row[col] || NUMBER.test(row[col].replace(/\*\*/g, ""))));
  return (
    <div className="answerTable" role="region" aria-label={head.join(", ")} tabIndex={0}>
      <table>
        <thead><tr>{head.map((cell, col) => <th key={col} className={numeric[col] ? "num" : undefined}>{inline(cell)}</th>)}</tr></thead>
        <tbody>{rows.map((row, r) => <tr key={r}>{head.map((_, col) => <td key={col} className={numeric[col] ? "num" : undefined}>{inline(row[col] || "")}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

// An assistant answer. The first paragraph is the direct answer, so it stands out.
export function Answer({ text }) {
  const blocks = parse(text);
  const leadIndex = blocks.findIndex((block) => block.kind === "paragraph");
  return blocks.map((block, index) => {
    switch (block.kind) {
      case "heading": return <h4 key={index} className="answerHeading">{inline(block.text)}</h4>;
      case "divider": return <hr key={index} className="answerDivider" />;
      case "table": return <Table key={index} head={block.head} rows={block.rows} />;
      case "callout": return <div key={index} className="answerCallout">{block.lines.map((line, n) => <p key={n}>{inline(line)}</p>)}</div>;
      case "note": return <p key={index} className="answerNote">{inline(block.text)}</p>;
      case "list": return <List key={index} items={block.items} />;
      default: return <p key={index} className={index === leadIndex && index === 0 ? "answerLead" : undefined}>{inline(block.lines.join(" "))}</p>;
    }
  });
}

// Inline marks dropped: what the words read as on screen.
const plainInline = (text) => text.split(INLINE).map((part) => {
  if (part.startsWith("**") && part.endsWith("**") && part.length > 4) return plainInline(part.slice(2, -2));
  if (part.startsWith("`") && part.endsWith("`") && part.length > 2) return part.slice(1, -1);
  const link = part.match(/^\[([^\]]+)\]\(([^)\s]+)\)$/);
  if (link) return link[1];
  if (/^([*_]).+\1$/.test(part)) return part.slice(1, -1);
  return part;
}).join("");

// An answer as plain text, for copying: the same blocks as on screen, without Markdown marks, so it pastes cleanly
// into WhatsApp, an SMS or a document.
export function plainText(text) {
  return parse(text).map((block) => {
    switch (block.kind) {
      case "heading": return plainInline(block.text).toUpperCase();
      case "divider": return "";
      case "table": return [block.head, ...block.rows].map((row) => row.map(plainInline).join(" | ")).join("\n");
      case "callout": return block.lines.map(plainInline).join("\n");
      case "note": return plainInline(block.text);
      case "list": {
        const numbers = [];
        return block.items.map((item) => {
          numbers.length = item.depth + 1;
          numbers[item.depth] = (numbers[item.depth] || 0) + 1;
          return `${"  ".repeat(item.depth)}${item.ordered ? `${numbers[item.depth]}.` : "•"} ${plainInline(item.text)}`;
        }).join("\n");
      }
      default: return plainInline(block.lines.join(" "));
    }
  }).filter(Boolean).join("\n\n");
}
