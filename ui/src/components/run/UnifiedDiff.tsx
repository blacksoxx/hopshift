import { cn } from "@/lib/utils";

export type DiffLineKind = "add" | "del" | "context" | "hunk" | "meta";

export interface DiffLine {
  kind: DiffLineKind;
  text: string;
  oldNo: number | null;
  newNo: number | null;
}

/** Parse a unified diff (as produced by difflib.unified_diff) into typed lines with line numbers. */
export function parseUnifiedDiff(diff: string): DiffLine[] {
  const lines: DiffLine[] = [];
  let oldNo = 0;
  let newNo = 0;
  if (!diff.trim()) return lines;
  for (const raw of diff.replace(/\n$/, "").split("\n")) {
    if (raw.startsWith("---") || raw.startsWith("+++")) {
      lines.push({ kind: "meta", text: raw, oldNo: null, newNo: null });
      continue;
    }
    const hunk = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(raw);
    if (hunk) {
      oldNo = Number(hunk[1]);
      newNo = Number(hunk[2]);
      lines.push({ kind: "hunk", text: raw, oldNo: null, newNo: null });
      continue;
    }
    if (raw.startsWith("+")) {
      lines.push({ kind: "add", text: raw.slice(1), oldNo: null, newNo: newNo++ });
    } else if (raw.startsWith("-")) {
      lines.push({ kind: "del", text: raw.slice(1), oldNo: oldNo++, newNo: null });
    } else if (raw.startsWith("\\")) {
      lines.push({ kind: "meta", text: raw, oldNo: null, newNo: null });
    } else {
      lines.push({ kind: "context", text: raw.startsWith(" ") ? raw.slice(1) : raw, oldNo: oldNo++, newNo: newNo++ });
    }
  }
  return lines;
}

const ROW: Record<DiffLineKind, string> = {
  add: "bg-success/10 text-foreground",
  del: "bg-destructive/10 text-foreground",
  context: "text-foreground/80",
  hunk: "bg-info/8 text-muted-foreground",
  meta: "text-muted-foreground/70",
};

const SIGN: Record<DiffLineKind, string> = { add: "+", del: "-", context: " ", hunk: "", meta: "" };

export function UnifiedDiff({ diff, className, testId }: { diff: string; className?: string; testId?: string }) {
  const lines = parseUnifiedDiff(diff);
  if (lines.length === 0) return <div className="px-4 py-6 text-center text-sm text-muted-foreground">No differences.</div>;
  return (
    <div data-testid={testId} className={cn("overflow-auto font-mono text-[12px] leading-[1.6]", className)}>
      <table className="w-full border-collapse">
        <tbody>
          {lines.map((line, index) => (
            <tr key={index} className={ROW[line.kind]} data-kind={line.kind}>
              <td className="w-10 select-none pl-3 pr-2 text-right align-top tabular text-muted-foreground/60">{line.oldNo ?? ""}</td>
              <td className="w-10 select-none pr-2 text-right align-top tabular text-muted-foreground/60">{line.newNo ?? ""}</td>
              <td className={cn("w-4 select-none text-center align-top", line.kind === "add" ? "text-success" : line.kind === "del" ? "text-destructive" : "text-muted-foreground/60")}>{SIGN[line.kind]}</td>
              <td className="whitespace-pre pr-4 align-top">{line.text}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
