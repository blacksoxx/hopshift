import * as React from "react";
import { Command } from "cmdk";
import { useNavigate } from "react-router-dom";
import { BarChart3, Cable, LayoutDashboard, ListChecks, Moon, Plus, ScrollText, Search, Settings, Sun } from "lucide-react";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Kbd } from "@/components/ui/misc";
import { StatusBadge } from "@/components/StatusBadge";
import { api } from "@/api";
import { useAuth } from "@/providers/AuthProvider";
import { useTheme } from "@/providers/ThemeProvider";
import { relativeTime, shortId } from "@/lib/format";
import type { RunRecord } from "@/types";

export function CommandPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const navigate = useNavigate();
  const { resolved, toggle } = useTheme();
  const { can } = useAuth();
  const [runs, setRuns] = React.useState<RunRecord[]>([]);

  React.useEffect(() => {
    if (!open) return;
    api.listRuns().then((items) => setRuns(items.slice(0, 12))).catch(() => setRuns([]));
  }, [open]);

  const go = (to: string) => {
    onOpenChange(false);
    navigate(to);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="top-[18%] translate-y-0 overflow-hidden p-0" size="md" aria-describedby={undefined}>
        <DialogTitle className="sr-only">Command palette</DialogTitle>
        <Command label="Command palette" className="[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-muted-foreground">
          <div className="flex items-center gap-2 border-b border-border px-3">
            <Search className="size-4 text-muted-foreground" />
            <Command.Input autoFocus placeholder="Jump to a page or a run…" className="h-11 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground" data-testid="palette-input" />
            <Kbd>esc</Kbd>
          </div>
          <Command.List className="max-h-[360px] overflow-y-auto p-1.5">
            <Command.Empty className="px-3 py-8 text-center text-sm text-muted-foreground">Nothing matches.</Command.Empty>
            <Command.Group heading="Navigate">
              <Item icon={LayoutDashboard} onSelect={() => go("/")} shortcut="g d">Dashboard</Item>
              <Item icon={ListChecks} onSelect={() => go("/runs")} shortcut="g r">Runs</Item>
              {can("operator") ? <Item icon={Plus} onSelect={() => go("/runs/new")} shortcut="g n">New run</Item> : null}
              <Item icon={BarChart3} onSelect={() => go("/assess")} shortcut="g a">Assess an inventory</Item>
              <Item icon={Cable} onSelect={() => go("/connections")} shortcut="g c">Connections</Item>
              {can("admin") ? <Item icon={ScrollText} onSelect={() => go("/audit")}>Audit log</Item> : null}
              <Item icon={Settings} onSelect={() => go("/settings")} shortcut="g s">Settings</Item>
            </Command.Group>
            <Command.Group heading="Appearance">
              <Item icon={resolved === "dark" ? Sun : Moon} onSelect={() => { toggle(); onOpenChange(false); }}>
                Switch to {resolved === "dark" ? "light" : "dark"} theme
              </Item>
            </Command.Group>
            {runs.length > 0 ? (
              <Command.Group heading="Recent runs">
                {runs.map((run) => (
                  <Item key={run.run_id} onSelect={() => go(`/runs/${run.run_id}`)} value={`${run.name ?? ""} ${run.run_id} ${run.cloud} ${run.status}`}>
                    <span className="flex min-w-0 flex-1 items-center gap-2">
                      <span className="truncate">{run.name || run.input_filename}</span>
                      <span className="font-mono text-[11px] text-muted-foreground">{shortId(run.run_id)}</span>
                      <span className="text-[11px] text-muted-foreground">{run.cloud}</span>
                    </span>
                    <span className="ml-auto flex items-center gap-2">
                      <span className="text-[11px] text-muted-foreground">{relativeTime(run.updated_at)}</span>
                      <StatusBadge status={run.executing ? "running" : run.status} />
                    </span>
                  </Item>
                ))}
              </Command.Group>
            ) : null}
          </Command.List>
        </Command>
      </DialogContent>
    </Dialog>
  );
}

function Item({ children, icon: Icon, onSelect, shortcut, value }: { children: React.ReactNode; icon?: React.ComponentType<{ className?: string }>; onSelect: () => void; shortcut?: string; value?: string }) {
  return (
    <Command.Item value={value} onSelect={onSelect} className="flex cursor-default select-none items-center gap-2.5 rounded-md px-3 py-2 text-sm text-foreground/90 outline-none data-[selected=true]:bg-accent data-[selected=true]:text-accent-foreground">
      {Icon ? <Icon className="size-4 shrink-0 text-muted-foreground" /> : null}
      {children}
      {shortcut ? (
        <span className="ml-auto flex items-center gap-1">
          {shortcut.split(" ").map((key) => (
            <Kbd key={key}>{key}</Kbd>
          ))}
        </span>
      ) : null}
    </Command.Item>
  );
}
