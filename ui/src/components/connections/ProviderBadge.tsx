import { Badge } from "@/components/ui/badge";
import { Hint } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { ConnectionCatalog } from "@/types";
import { NOT_TERRAFORM_READY, providerMeta } from "./providers";

const SIZES = {
  sm: "size-5 rounded text-[9px]",
  md: "size-7 rounded-md text-[10.5px]",
  lg: "size-10 rounded-lg text-sm",
};

/**
 * Monogram tile: brand tint for the providers the UI knows, a neutral tile with a monogram
 * derived from the key for everything else. Decorative: the label next to it carries the meaning.
 */
export function ProviderIcon({ provider, size = "md", className }: { provider: string; size?: keyof typeof SIZES; className?: string }) {
  const meta = providerMeta(provider);
  return (
    <span
      aria-hidden
      data-testid={`provider-icon-${provider}`}
      data-generic={meta.known ? undefined : "true"}
      className={cn("inline-flex shrink-0 select-none items-center justify-center font-semibold leading-none tracking-tight", SIZES[size], meta.tile, className)}
    >
      {meta.short}
    </span>
  );
}

/** Icon plus label. The label comes from the catalog when given (or an explicit `label`), the UI fallback otherwise. */
export function ProviderBadge({ provider, label, catalog, size = "sm", className }: { provider: string; label?: string | null; catalog?: ConnectionCatalog | null; size?: keyof typeof SIZES; className?: string }) {
  const meta = providerMeta(provider, catalog);
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-sm", className)} data-testid={`provider-badge-${provider}`}>
      <ProviderIcon provider={provider} size={size} />
      <span>{label ?? meta.label}</span>
    </span>
  );
}

/** "terraform ready" or "verify only", with the reason on hover. */
export function TerraformBadge({ ready, className }: { ready: boolean; className?: string }) {
  const badge = ready ? (
    <Badge variant="info" className={className} data-testid="terraform-badge">
      terraform ready
    </Badge>
  ) : (
    <Badge variant="outline" className={className} data-testid="terraform-badge">
      verify only
    </Badge>
  );
  return (
    <Hint content={ready ? "Plan and apply receive this connection's credentials as environment variables." : NOT_TERRAFORM_READY}>
      <span tabIndex={0} className="inline-flex rounded-md focus-visible:ring-2 focus-visible:ring-ring">
        {badge}
      </span>
    </Hint>
  );
}
