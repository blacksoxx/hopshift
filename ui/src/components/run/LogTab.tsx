import * as React from "react";
import { ArrowDownToLine, Copy, Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { formatTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { RunEvent } from "@/types";

const TYPE_VARIANT: Record<RunEvent["type"], "secondary" | "warning" | "info" | "danger" | "success" | "muted"> = {
  start: "secondary",
  node: "secondary",
  paused: "warning",
  patch: "info",
  resume: "info",
  rerun: "info",
  error: "danger",
  end: "success",
  cancelled: "muted",
};

export function EventTypeBadge({ type, className }: { type: RunEvent["type"]; className?: string }) {
  return (
    <Badge variant={TYPE_VARIANT[type] ?? "secondary"} className={cn("font-mono text-[10.5px] uppercase tracking-wide", className)}>
      {type}
    </Badge>
  );
}

export function eventText(event: RunEvent): string {
  return event.messages.length > 0 ? event.messages.join(" | ") : Object.keys(event.summary).length > 0 ? JSON.stringify(event.summary) : "";
}

export function formatEventLine(event: RunEvent): string {
  return `${event.ts}  [${event.type}]${event.node ? ` ${event.node}` : ""}  ${eventText(event)}`.trimEnd();
}

export function LogTab({ events }: { events: RunEvent[] }) {
  const { toast } = useToast();
  const [filter, setFilter] = React.useState("");
  const [autoScroll, setAutoScroll] = React.useState(true);
  const container = React.useRef<HTMLDivElement>(null);

  const needle = filter.trim().toLowerCase();
  const visible = React.useMemo(
    () => (needle ? events.filter((event) => `${event.type} ${event.node ?? ""} ${eventText(event)}`.toLowerCase().includes(needle)) : events),
    [events, needle],
  );

  React.useEffect(() => {
    if (!autoScroll || !container.current) return;
    container.current.scrollTop = container.current.scrollHeight;
  }, [visible.length, autoScroll]);

  async function copyAll() {
    try {
      await navigator.clipboard.writeText(visible.map(formatEventLine).join("\n"));
      toast({ title: "Log copied", description: `${visible.length} event${visible.length === 1 ? "" : "s"} on the clipboard.`, variant: "success" });
    } catch (exc) {
      toast({ title: "Could not copy", description: (exc as Error).message, variant: "error" });
    }
  }

  return (
    <div className="surface overflow-hidden">
      <div className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-2.5">
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Filter events…" className="h-8 pl-8 text-xs" data-testid="log-filter" />
        </div>
        <span className="text-xs text-muted-foreground">
          {visible.length === events.length ? `${events.length} event${events.length === 1 ? "" : "s"}` : `${visible.length} of ${events.length} events`}
        </span>
        <div className="ml-auto flex items-center gap-3">
          <div className="flex items-center gap-2">
            <Switch id="log-autoscroll" checked={autoScroll} onCheckedChange={setAutoScroll} data-testid="log-autoscroll" />
            <Label htmlFor="log-autoscroll" className="flex cursor-pointer items-center gap-1 text-xs font-normal text-muted-foreground">
              <ArrowDownToLine className="size-3.5" /> Auto-scroll
            </Label>
          </div>
          <Button variant="outline" size="sm" onClick={() => void copyAll()} disabled={visible.length === 0} data-testid="log-copy">
            <Copy /> Copy all
          </Button>
        </div>
      </div>
      <div ref={container} className="max-h-[60vh] min-h-[200px] overflow-auto font-mono text-[12px] leading-relaxed" data-testid="log">
        {visible.length === 0 ? (
          <div className="px-4 py-10 text-center font-sans text-sm text-muted-foreground">{events.length === 0 ? "No events yet." : "No events match the filter."}</div>
        ) : (
          <ol className="divide-y divide-border/60">
            {visible.map((event, index) => {
              const text = eventText(event);
              return (
                <li key={`${event.ts}-${index}`} className={cn("grid grid-cols-[auto_auto_1fr] items-start gap-x-3 px-4 py-1.5 sm:grid-cols-[88px_120px_auto_1fr]", event.type === "error" && "bg-destructive/5")} data-testid="log-event">
                  <span className="tabular text-muted-foreground" title={event.ts}>
                    {formatTime(event.ts)}
                  </span>
                  <span className="hidden truncate text-muted-foreground sm:block" title={event.node ?? undefined}>
                    {event.node ?? ""}
                  </span>
                  <EventTypeBadge type={event.type} className="h-5 py-0" />
                  <span className={cn("col-span-3 min-w-0 whitespace-pre-wrap break-words sm:col-span-1", event.type === "error" && "text-destructive")}>
                    {event.messages.length > 0 ? (
                      <ul className="space-y-0.5">
                        {event.messages.map((message, i) => (
                          <li key={i}>{message}</li>
                        ))}
                      </ul>
                    ) : (
                      <span className="text-muted-foreground">{text}</span>
                    )}
                  </span>
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </div>
  );
}
