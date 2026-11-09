import * as React from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { motion } from "motion/react";
import { Activity, BarChart3, Cable, ChevronLeft, ChevronRight, LayoutDashboard, ListChecks, LogOut, Menu, Moon, Plus, ScrollText, Search, Settings, ShieldCheck, Sun, UserRound } from "lucide-react";
import { Wordmark, LogoMark } from "@/components/Logo";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/misc";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Hint } from "@/components/ui/tooltip";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { useAuth } from "@/providers/AuthProvider";
import { useTheme } from "@/providers/ThemeProvider";
import { cn, isMac } from "@/lib/utils";
import { CommandPalette } from "./CommandPalette";
import type { Role } from "@/types";

interface NavItem {
  to: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  end?: boolean;
  role?: Role;
}

const NAV: { title: string; items: NavItem[] }[] = [
  { title: "Overview", items: [{ to: "/", label: "Dashboard", icon: LayoutDashboard, end: true }] },
  {
    title: "Migrate",
    items: [
      { to: "/runs", label: "Runs", icon: ListChecks, end: true },
      { to: "/runs/new", label: "New run", icon: Plus, role: "operator" },
      { to: "/assess", label: "Assess", icon: BarChart3 },
    ],
  },
  {
    title: "Platform",
    items: [
      { to: "/connections", label: "Connections", icon: Cable },
      { to: "/audit", label: "Audit log", icon: ScrollText, role: "admin" },
      { to: "/settings", label: "Settings", icon: Settings },
    ],
  },
];

const SIDEBAR_KEY = "vma.sidebar";

export function AppShell() {
  const [collapsed, setCollapsed] = React.useState<boolean>(() => {
    try {
      return localStorage.getItem(SIDEBAR_KEY) === "collapsed";
    } catch {
      return false;
    }
  });
  const [mobileOpen, setMobileOpen] = React.useState(false);
  const [paletteOpen, setPaletteOpen] = React.useState(false);
  const location = useLocation();
  const navigate = useNavigate();

  React.useEffect(() => {
    try {
      localStorage.setItem(SIDEBAR_KEY, collapsed ? "collapsed" : "expanded");
    } catch {
      /* ignore */
    }
  }, [collapsed]);

  React.useEffect(() => setMobileOpen(false), [location.pathname]);

  React.useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing = target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable);
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((open) => !open);
        return;
      }
      if (typing || event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.key === "g") {
        const next = (second: KeyboardEvent) => {
          window.removeEventListener("keydown", next);
          const map: Record<string, string> = { d: "/", r: "/runs", n: "/runs/new", a: "/assess", c: "/connections", s: "/settings" };
          const to = map[second.key];
          if (to) {
            second.preventDefault();
            navigate(to);
          }
        };
        window.addEventListener("keydown", next, { once: true });
        setTimeout(() => window.removeEventListener("keydown", next), 1200);
      }
      if (event.key === "?") setPaletteOpen(true);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [navigate]);

  return (
    <div className="flex h-full min-h-screen bg-background">
      <aside className={cn("sticky top-0 hidden h-screen shrink-0 flex-col border-r border-border bg-sidebar transition-[width] duration-200 md:flex", collapsed ? "w-[64px]" : "w-[240px]")}>
        <SidebarContent collapsed={collapsed} onToggle={() => setCollapsed((value) => !value)} onSearch={() => setPaletteOpen(true)} />
      </aside>

      <Dialog open={mobileOpen} onOpenChange={setMobileOpen}>
        <DialogContent className="left-0 top-0 h-full w-[260px] max-w-none translate-x-0 translate-y-0 rounded-none border-0 border-r p-0 data-[state=open]:animate-[fade-in_0.15s_ease-out]" size="sm">
          <div className="flex h-full flex-col bg-sidebar">
            <SidebarContent collapsed={false} onToggle={() => setMobileOpen(false)} onSearch={() => setPaletteOpen(true)} />
          </div>
        </DialogContent>
      </Dialog>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-12 items-center gap-3 border-b border-border bg-background/80 px-4 backdrop-blur md:px-6">
          <Button variant="ghost" size="icon-sm" className="md:hidden" onClick={() => setMobileOpen(true)} aria-label="Open navigation">
            <Menu />
          </Button>
          <Breadcrumbs />
          <div className="ml-auto flex items-center gap-1.5">
            <Button variant="outline" size="sm" className="hidden h-8 w-56 justify-between text-muted-foreground sm:flex" onClick={() => setPaletteOpen(true)} data-testid="open-palette">
              <span className="flex items-center gap-2">
                <Search className="size-3.5" /> Search or jump to…
              </span>
              <span className="flex items-center gap-0.5">
                <Kbd>{isMac() ? "⌘" : "Ctrl"}</Kbd>
                <Kbd>K</Kbd>
              </span>
            </Button>
            <ThemeButton />
            <UserMenu />
          </div>
        </header>
        <main className="flex-1 px-4 py-6 md:px-8 md:py-7">
          {/* Enter-only transition: exit animations can leave a ghost page behind on rapid hash changes. */}
          <motion.div key={location.pathname} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.16, ease: "easeOut" }} className="mx-auto w-full max-w-[1400px]">
            <Outlet />
          </motion.div>
        </main>
      </div>
      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
    </div>
  );
}

function SidebarContent({ collapsed, onToggle, onSearch }: { collapsed: boolean; onToggle: () => void; onSearch: () => void }) {
  const { can, status } = useAuth();
  return (
    <>
      <div className={cn("flex h-12 items-center border-b border-border", collapsed ? "justify-center px-0" : "px-4")}>
        {collapsed ? <LogoMark /> : <Wordmark />}
      </div>
      <nav className="flex-1 space-y-5 overflow-y-auto px-2.5 py-4" aria-label="Primary">
        {NAV.map((group) => {
          const items = group.items.filter((item) => !item.role || can(item.role));
          if (items.length === 0) return null;
          return (
            <div key={group.title}>
              {!collapsed ? <div className="mb-1.5 px-2.5 text-[10.5px] font-semibold uppercase tracking-wider text-muted-foreground/80">{group.title}</div> : null}
              <ul className="space-y-0.5">
                {items.map((item) => (
                  <li key={item.to}>
                    <Hint content={collapsed ? item.label : null} side="right">
                      <NavLink
                        to={item.to}
                        end={item.end}
                        className={({ isActive }) =>
                          cn(
                            "group flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13.5px] font-medium text-muted-foreground transition-colors hover:bg-accent/70 hover:text-foreground",
                            isActive && "bg-accent text-accent-foreground",
                            collapsed && "justify-center px-0",
                          )
                        }
                        data-testid={`nav-${item.label.toLowerCase().replace(/\s+/g, "-")}`}
                      >
                        <item.icon className="size-4 shrink-0" />
                        {!collapsed ? <span className="truncate">{item.label}</span> : null}
                      </NavLink>
                    </Hint>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </nav>
      <div className={cn("border-t border-border p-2.5", collapsed ? "flex flex-col items-center gap-1" : "space-y-1")}>
        {!collapsed && status?.auth_mode === "disabled" ? (
          <div className="mb-1 flex items-center gap-1.5 rounded-md bg-warning/10 px-2 py-1 text-[11px] text-warning">
            <ShieldCheck className="size-3.5" /> auth disabled
          </div>
        ) : null}
        <Button variant="ghost" size={collapsed ? "icon-sm" : "sm"} className={cn("text-muted-foreground", !collapsed && "w-full justify-start")} onClick={onSearch}>
          <Search /> {!collapsed ? "Search" : null}
        </Button>
        <Button variant="ghost" size={collapsed ? "icon-sm" : "sm"} className={cn("text-muted-foreground", !collapsed && "w-full justify-start")} onClick={onToggle} aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} data-testid="sidebar-toggle">
          {collapsed ? <ChevronRight /> : <ChevronLeft />} {!collapsed ? "Collapse" : null}
        </Button>
      </div>
    </>
  );
}

const LABELS: Record<string, string> = { runs: "Runs", new: "New run", assess: "Assess", connections: "Connections", settings: "Settings", audit: "Audit log" };

function Breadcrumbs() {
  const { pathname } = useLocation();
  const parts = pathname.split("/").filter(Boolean);
  if (parts.length === 0) return <div className="text-sm font-medium">Dashboard</div>;
  return (
    <nav className="flex min-w-0 items-center gap-1.5 text-sm" aria-label="Breadcrumb">
      {parts.map((part, index) => {
        const to = `/${parts.slice(0, index + 1).join("/")}`;
        const last = index === parts.length - 1;
        const label = LABELS[part] ?? (part.length > 24 ? `${part.slice(0, 10)}…${part.slice(-8)}` : part);
        return (
          <React.Fragment key={to}>
            {index > 0 ? <span className="text-muted-foreground/60">/</span> : null}
            {last ? (
              <span className="truncate font-medium">{label}</span>
            ) : (
              <NavLink to={to} className="truncate text-muted-foreground hover:text-foreground">
                {label}
              </NavLink>
            )}
          </React.Fragment>
        );
      })}
    </nav>
  );
}

function ThemeButton() {
  const { resolved, toggle } = useTheme();
  return (
    <Hint content={resolved === "dark" ? "Switch to light" : "Switch to dark"}>
      <Button variant="ghost" size="icon-sm" onClick={toggle} aria-label="Toggle theme" data-testid="theme-toggle">
        {resolved === "dark" ? <Sun /> : <Moon />}
      </Button>
    </Hint>
  );
}

function UserMenu() {
  const { user, logout, status } = useAuth();
  const navigate = useNavigate();
  if (!user) return null;
  const initials = (user.name || user.username).split(/\s+/).map((part) => part[0]).join("").slice(0, 2).toUpperCase();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button className="ml-1 flex size-8 items-center justify-center rounded-full bg-primary/15 text-xs font-semibold text-primary ring-offset-background transition hover:bg-primary/25 focus-visible:ring-2 focus-visible:ring-ring" aria-label="Account menu" data-testid="user-menu">
          {initials}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel>
          <div className="text-sm font-medium text-foreground">{user.name || user.username}</div>
          <div className="text-xs font-normal text-muted-foreground capitalize">{user.role} · {user.auth_kind}</div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => navigate("/settings/profile")}>
          <UserRound /> Profile & security
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => navigate("/settings/posture")}>
          <Activity /> Security posture
        </DropdownMenuItem>
        {status?.auth_mode !== "disabled" ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => void logout()} data-testid="logout">
              <LogOut /> Sign out
            </DropdownMenuItem>
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
