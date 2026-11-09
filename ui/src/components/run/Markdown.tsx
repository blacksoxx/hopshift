import * as React from "react";
import { cn } from "@/lib/utils";

export type MarkdownBlock =
  | { kind: "heading"; level: number; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "list"; ordered: boolean; items: string[] }
  | { kind: "code"; text: string };

const LIST_ITEM = /^\s*([-*+]|\d+[.)])\s+(.*)$/;
const HEADING = /^(#{1,6})\s+(.*)$/;

/** Split markdown into the handful of block types review notes use. */
export function parseMarkdown(source: string): MarkdownBlock[] {
  const blocks: MarkdownBlock[] = [];
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (line.trim() === "") {
      index += 1;
      continue;
    }
    if (line.startsWith("```")) {
      const buffer: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].startsWith("```")) buffer.push(lines[index++]);
      index += 1;
      blocks.push({ kind: "code", text: buffer.join("\n") });
      continue;
    }
    const heading = HEADING.exec(line);
    if (heading) {
      blocks.push({ kind: "heading", level: heading[1].length, text: heading[2].trim() });
      index += 1;
      continue;
    }
    const bullet = LIST_ITEM.exec(line);
    if (bullet) {
      const ordered = /\d/.test(bullet[1]);
      const items: string[] = [];
      while (index < lines.length) {
        const match = LIST_ITEM.exec(lines[index]);
        if (!match) break;
        items.push(match[2]);
        index += 1;
        // continuation lines indented under the item
        while (index < lines.length && /^\s{2,}\S/.test(lines[index]) && !LIST_ITEM.test(lines[index])) {
          items[items.length - 1] += ` ${lines[index].trim()}`;
          index += 1;
        }
      }
      blocks.push({ kind: "list", ordered, items });
      continue;
    }
    const buffer: string[] = [];
    while (index < lines.length && lines[index].trim() !== "" && !HEADING.test(lines[index]) && !LIST_ITEM.test(lines[index]) && !lines[index].startsWith("```")) {
      buffer.push(lines[index]);
      index += 1;
    }
    const raw = buffer.join("\n").trim();
    // Reporters paste JSON straight into the notes; keep it readable instead of joining the lines.
    if (/^[[{]/.test(raw) && /[\]}]$/.test(raw) && isJson(raw)) blocks.push({ kind: "code", text: raw });
    else blocks.push({ kind: "paragraph", text: buffer.map((line) => line.trim()).join(" ") });
  }
  return blocks;
}

function isJson(text: string): boolean {
  try {
    JSON.parse(text);
    return true;
  } catch {
    return false;
  }
}

/**
 * Inline code, bold and italic; everything else is text (raw HTML is never interpreted).
 * Underscores are not treated as emphasis: identifiers like `validation_result` are far more
 * common in review notes than `_italic_`.
 */
export function renderInline(text: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*\s][^*]*\*)/g;
  let last = 0;
  let key = 0;
  for (const match of text.matchAll(pattern)) {
    const start = match.index ?? 0;
    if (start > last) nodes.push(text.slice(last, start));
    const token = match[0];
    if (token.startsWith("`")) {
      nodes.push(
        <code key={key++} className="rounded bg-muted px-1 py-0.5 font-mono text-[0.9em]">
          {token.slice(1, -1)}
        </code>,
      );
    } else if (token.startsWith("**")) {
      nodes.push(<strong key={key++}>{token.slice(2, -2)}</strong>);
    } else {
      nodes.push(<em key={key++}>{token.slice(1, -1)}</em>);
    }
    last = start + token.length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

const HEADING_CLASS: Record<number, string> = {
  1: "text-base font-semibold",
  2: "text-[15px] font-semibold",
  3: "text-sm font-semibold",
};

export function Markdown({ source, className }: { source: string; className?: string }) {
  const blocks = React.useMemo(() => parseMarkdown(source), [source]);
  return (
    <div className={cn("space-y-2.5 text-sm leading-relaxed", className)}>
      {blocks.map((block, index) => {
        switch (block.kind) {
          case "heading": {
            const Tag = `h${Math.min(block.level + 2, 6)}` as "h3" | "h4" | "h5" | "h6";
            return (
              <Tag key={index} className={cn("mt-4 first:mt-0", HEADING_CLASS[block.level] ?? "text-sm font-medium")}>
                {renderInline(block.text)}
              </Tag>
            );
          }
          case "list":
            return block.ordered ? (
              <ol key={index} className="list-decimal space-y-1 pl-5">
                {block.items.map((item, i) => (
                  <li key={i}>{renderInline(item)}</li>
                ))}
              </ol>
            ) : (
              <ul key={index} className="list-disc space-y-1 pl-5">
                {block.items.map((item, i) => (
                  <li key={i}>{renderInline(item)}</li>
                ))}
              </ul>
            );
          case "code":
            return (
              <pre key={index} className="overflow-auto rounded-md border border-border bg-muted/50 p-3 font-mono text-[12.5px]">
                {block.text}
              </pre>
            );
          default:
            return <p key={index}>{renderInline(block.text)}</p>;
        }
      })}
    </div>
  );
}
