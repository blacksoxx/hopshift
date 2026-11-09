import * as React from "react";
import * as ProgressPrimitive from "@radix-ui/react-progress";
import * as SeparatorPrimitive from "@radix-ui/react-separator";
import * as PopoverPrimitive from "@radix-ui/react-popover";
import { AlertTriangle, CheckCircle2, Info, Loader2, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";

export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("animate-[pulse-soft_1.6s_ease-in-out_infinite] rounded-md bg-muted", className)} {...props} />;
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("size-4 animate-spin text-muted-foreground", className)} aria-label="Loading" />;
}

export const Separator = React.forwardRef<React.ElementRef<typeof SeparatorPrimitive.Root>, React.ComponentPropsWithoutRef<typeof SeparatorPrimitive.Root>>(
  ({ className, orientation = "horizontal", decorative = true, ...props }, ref) => (
    <SeparatorPrimitive.Root ref={ref} decorative={decorative} orientation={orientation} className={cn("shrink-0 bg-border", orientation === "horizontal" ? "h-px w-full" : "h-full w-px", className)} {...props} />
  ),
);
Separator.displayName = "Separator";

export const Progress = React.forwardRef<React.ElementRef<typeof ProgressPrimitive.Root>, React.ComponentPropsWithoutRef<typeof ProgressPrimitive.Root> & { indicatorClassName?: string }>(
  ({ className, value, indicatorClassName, ...props }, ref) => (
    <ProgressPrimitive.Root ref={ref} className={cn("relative h-1.5 w-full overflow-hidden rounded-full bg-muted", className)} {...props}>
      <ProgressPrimitive.Indicator className={cn("h-full w-full flex-1 bg-primary transition-transform duration-300", indicatorClassName)} style={{ transform: `translateX(-${100 - (value ?? 0)}%)` }} />
    </ProgressPrimitive.Root>
  ),
);
Progress.displayName = "Progress";

export function Kbd({ children, className }: { children: React.ReactNode; className?: string }) {
  return <kbd className={cn("inline-flex h-5 min-w-5 items-center justify-center rounded border border-border bg-muted px-1.5 font-mono text-[10.5px] font-medium text-muted-foreground", className)}>{children}</kbd>;
}

const ALERT_STYLES = {
  info: { icon: Info, className: "border-info/30 bg-info/8 text-foreground [&_svg]:text-info" },
  success: { icon: CheckCircle2, className: "border-success/30 bg-success/8 text-foreground [&_svg]:text-success" },
  warning: { icon: AlertTriangle, className: "border-warning/40 bg-warning/10 text-foreground [&_svg]:text-warning" },
  error: { icon: XCircle, className: "border-destructive/30 bg-destructive/8 text-foreground [&_svg]:text-destructive" },
};

export function Alert({ variant = "info", title, children, className, action, testId }: { variant?: keyof typeof ALERT_STYLES; title?: React.ReactNode; children?: React.ReactNode; className?: string; action?: React.ReactNode; testId?: string }) {
  const { icon: Icon, className: styles } = ALERT_STYLES[variant];
  return (
    <div role="alert" data-testid={testId} className={cn("flex items-start gap-3 rounded-lg border px-3.5 py-3 text-sm", styles, className)}>
      <Icon className="mt-0.5 size-4 shrink-0" />
      <div className="min-w-0 flex-1 space-y-0.5">
        {title ? <div className="font-medium">{title}</div> : null}
        {children ? <div className="text-[13px] text-muted-foreground [&_pre]:whitespace-pre-wrap [&_pre]:break-words">{children}</div> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

export function EmptyState({ icon: Icon, title, description, action, className, testId }: { icon?: React.ComponentType<{ className?: string }>; title: React.ReactNode; description?: React.ReactNode; action?: React.ReactNode; className?: string; testId?: string }) {
  return (
    <div data-testid={testId} className={cn("flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border px-6 py-12 text-center", className)}>
      {Icon ? (
        <div className="mb-1 flex size-10 items-center justify-center rounded-full bg-muted text-muted-foreground">
          <Icon className="size-5" />
        </div>
      ) : null}
      <div className="text-sm font-medium">{title}</div>
      {description ? <div className="max-w-sm text-balance text-sm text-muted-foreground">{description}</div> : null}
      {action ? <div className="mt-3">{action}</div> : null}
    </div>
  );
}

export function PageHeader({ title, description, actions, eyebrow, className }: { title: React.ReactNode; description?: React.ReactNode; actions?: React.ReactNode; eyebrow?: React.ReactNode; className?: string }) {
  return (
    <div className={cn("mb-6 flex flex-wrap items-end justify-between gap-4", className)}>
      <div className="min-w-0 space-y-1">
        {eyebrow ? <div className="text-xs font-medium uppercase tracking-wider text-muted-foreground">{eyebrow}</div> : null}
        <h1 className="truncate text-xl font-semibold tracking-tight">{title}</h1>
        {description ? <p className="max-w-2xl text-sm text-muted-foreground">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function Stat({ label, value, hint, icon: Icon, tone, className, testId }: { label: React.ReactNode; value: React.ReactNode; hint?: React.ReactNode; icon?: React.ComponentType<{ className?: string }>; tone?: "default" | "success" | "warning" | "danger" | "info"; className?: string; testId?: string }) {
  const toneClass = { default: "text-foreground", success: "text-success", warning: "text-warning", danger: "text-destructive", info: "text-info" }[tone ?? "default"];
  return (
    <div data-testid={testId} className={cn("surface flex items-start justify-between gap-3 px-4 py-3.5", className)}>
      <div className="min-w-0">
        <div className="text-xs font-medium text-muted-foreground">{label}</div>
        <div className={cn("mt-1 text-2xl font-semibold tracking-tight tabular", toneClass)}>{value}</div>
        {hint ? <div className="mt-0.5 text-xs text-muted-foreground">{hint}</div> : null}
      </div>
      {Icon ? <Icon className="size-4 shrink-0 text-muted-foreground/70" /> : null}
    </div>
  );
}

export const Popover = PopoverPrimitive.Root;
export const PopoverTrigger = PopoverPrimitive.Trigger;
export const PopoverContent = React.forwardRef<React.ElementRef<typeof PopoverPrimitive.Content>, React.ComponentPropsWithoutRef<typeof PopoverPrimitive.Content>>(
  ({ className, align = "center", sideOffset = 6, ...props }, ref) => (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Content ref={ref} align={align} sideOffset={sideOffset} className={cn("z-50 w-72 rounded-lg border border-border bg-popover p-4 text-popover-foreground shadow-xl outline-none data-[state=open]:animate-[fade-in_0.12s_ease-out]", className)} {...props} />
    </PopoverPrimitive.Portal>
  ),
);
PopoverContent.displayName = "PopoverContent";

export function CodeBlock({ children, className, testId }: { children: React.ReactNode; className?: string; testId?: string }) {
  return (
    <pre data-testid={testId} className={cn("overflow-auto rounded-lg border border-border bg-muted/50 p-3 font-mono text-[12.5px] leading-relaxed", className)}>
      {children}
    </pre>
  );
}

export function Pill({ children, className }: { children: React.ReactNode; className?: string }) {
  return <span className={cn("inline-flex items-center rounded-full bg-muted px-2 py-0.5 font-mono text-[11px] text-muted-foreground", className)}>{children}</span>;
}
