import { Target } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Hint } from "@/components/ui/tooltip";
import { useTargets } from "@/hooks/useTargets";
import { cn } from "@/lib/utils";
import type { SupportTier } from "@/types";

export const TIER_COPY: Record<SupportTier, { label: string; variant: "success" | "info" | "warning"; text: string }> = {
  tested: {
    label: "tested",
    variant: "success",
    text: "Covered by the integration suite on every release: the rendered Terraform passes terraform validate, tflint and the policy checks.",
  },
  validated: {
    label: "validated",
    variant: "info",
    text: "Renders and passes terraform validate and the policy checks; not yet covered end to end by the integration suite.",
  },
  experimental: {
    label: "experimental",
    variant: "warning",
    text: "Provided by a plugin or still maturing. Review the generated output carefully before deploying it.",
  },
};

export function tierCopy(tier: string): (typeof TIER_COPY)[SupportTier] {
  return TIER_COPY[tier as SupportTier] ?? { label: tier, variant: "warning", text: "Unknown tier; treat it as experimental." };
}

/**
 * Support tier of a source or target, with the explanation on hover.
 * `focusable={false}` when the badge sits inside a button (nested focus targets are invalid HTML).
 */
export function TierBadge({ tier, focusable = true, className }: { tier: string; focusable?: boolean; className?: string }) {
  const copy = tierCopy(tier);
  return (
    <Hint content={copy.text}>
      <span tabIndex={focusable ? 0 : undefined} className={cn("inline-flex rounded-md", focusable && "focus-visible:ring-2 focus-visible:ring-ring")} data-testid="tier-badge" data-tier={tier}>
        <Badge variant={copy.variant} className={className}>
          {copy.label}
        </Badge>
      </span>
    </Hint>
  );
}

/** Target name rendered with its registry label (the bare name while the registry loads). */
export function TargetBadge({ name, icon = true, tier = false, className }: { name: string; icon?: boolean; tier?: boolean; className?: string }) {
  const { labelOf, specOf } = useTargets();
  const spec = specOf(name);
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs text-muted-foreground", className)} data-testid="target-badge" data-target={name}>
      {icon ? <Target className="size-3.5 shrink-0" aria-hidden /> : null}
      <span className="truncate">{labelOf(name)}</span>
      {tier && spec ? <TierBadge tier={spec.tier} focusable={false} /> : null}
    </span>
  );
}
