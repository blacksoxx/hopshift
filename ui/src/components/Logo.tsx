import { cn } from "@/lib/utils";

/**
 * The hopshift mark: a workload hops from its origin (the dot) over to its destination (the
 * arrowhead). Drawn on a 64-unit grid so the strokes still read at 16px; colours come from the
 * theme tokens so it works on light and dark surfaces. public/favicon.svg is the same drawing.
 */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={cn("size-7", className)} aria-hidden data-testid="logo-mark">
      <rect x="4" y="4" width="56" height="56" rx="14" className="fill-primary" />
      <circle cx="17" cy="45" r="4.5" className="fill-primary-foreground" opacity=".55" />
      <path d="M17 45Q31 11 47 37" fill="none" stroke="currentColor" strokeWidth="5.5" strokeLinecap="round" className="text-primary-foreground" />
      <path d="M37.8 33L47 37l.6-10" fill="none" stroke="currentColor" strokeWidth="5.5" strokeLinecap="round" strokeLinejoin="round" className="text-primary-foreground" />
    </svg>
  );
}

export const TAGLINE = "migrate anything from X to Y";

export function Wordmark({ compact = false, className }: { compact?: boolean; className?: string }) {
  return (
    <div className={cn("flex items-center gap-2.5", className)} data-testid="wordmark">
      <LogoMark />
      {!compact ? (
        <div className="leading-tight">
          <div className="text-[13.5px] font-semibold tracking-tight">hopshift</div>
          <div className="text-[10.5px] tracking-wide text-muted-foreground [font-variant-caps:small-caps]">{TAGLINE}</div>
        </div>
      ) : null}
    </div>
  );
}
