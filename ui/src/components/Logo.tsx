import { cn } from "@/lib/utils";

export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={cn("size-7", className)} aria-hidden>
      <rect x="4" y="4" width="56" height="56" rx="14" className="fill-primary" />
      <path d="M18 40h10a8 8 0 0 0 0-16h-2a10 10 0 0 0-19 3" fill="none" stroke="currentColor" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" className="text-primary-foreground" opacity=".55" />
      <path d="M30 22h8m0 0-6-6m6 6-6 6" fill="none" stroke="currentColor" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" className="text-primary-foreground" />
      <path d="M42 42h8m0 0-6-6m6 6-6 6" fill="none" stroke="currentColor" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" className="text-primary-foreground" />
    </svg>
  );
}

export function Wordmark({ compact = false, className }: { compact?: boolean; className?: string }) {
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <LogoMark />
      {!compact ? (
        <div className="leading-tight">
          <div className="text-[13.5px] font-semibold tracking-tight">hopshift</div>
          <div className="text-[10.5px] text-muted-foreground">deterministic core · AI at the edges</div>
        </div>
      ) : null}
    </div>
  );
}
