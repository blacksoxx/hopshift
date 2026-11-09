import { AlertTriangle, CheckCircle2, ShieldCheck, XCircle } from "lucide-react";
import { api } from "@/api";
import { useAsync } from "@/hooks/useAsync";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, Skeleton, Stat } from "@/components/ui/misc";
import { StatusBadge } from "@/components/StatusBadge";
import type { PostureCheck } from "@/types";

const RANK: Record<PostureCheck["status"], number> = { fail: 0, warn: 1, pass: 2 };

/** Failing checks first, then warnings, then passes; stable within a level. */
export function sortChecks(checks: PostureCheck[]): PostureCheck[] {
  return [...checks].sort((a, b) => RANK[a.status] - RANK[b.status]);
}

export function countChecks(checks: PostureCheck[]): Record<PostureCheck["status"], number> {
  return checks.reduce(
    (acc, check) => {
      acc[check.status] += 1;
      return acc;
    },
    { pass: 0, warn: 0, fail: 0 } as Record<PostureCheck["status"], number>,
  );
}

export function PosturePanel() {
  const posture = useAsync(() => api.posture(), []);
  const checks = sortChecks(posture.data?.checks ?? []);
  const counts = countChecks(checks);

  return (
    <div className="space-y-4">
      <p className="max-w-3xl text-sm text-muted-foreground">
        These are the technical controls this deployment enforces and the evidence they produce, mapped to SOC 2, HIPAA and CIS references. They support an audit; they are not a certification.
      </p>

      {posture.loading && !posture.data ? (
        <div className="grid gap-3 sm:grid-cols-3">
          {Array.from({ length: 3 }).map((_, index) => (
            <Skeleton key={index} className="h-[88px]" />
          ))}
        </div>
      ) : posture.error ? (
        <EmptyState
          icon={ShieldCheck}
          title="Could not load the posture checks"
          description={posture.error}
          action={
            <Button variant="outline" onClick={() => void posture.reload()}>
              Retry
            </Button>
          }
        />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <Stat label="Passing" value={counts.pass} icon={CheckCircle2} tone="success" testId="posture-pass" />
            <Stat label="Warnings" value={counts.warn} icon={AlertTriangle} tone={counts.warn > 0 ? "warning" : "default"} testId="posture-warn" />
            <Stat label="Failing" value={counts.fail} icon={XCircle} tone={counts.fail > 0 ? "danger" : "default"} testId="posture-fail" />
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Controls</CardTitle>
              <CardDescription>Evaluated live on every request; failing controls come first.</CardDescription>
            </CardHeader>
            <CardContent className="px-0 pt-0">
              {checks.length === 0 ? (
                <div className="px-5 pb-5">
                  <EmptyState title="No checks reported" description="This server returned an empty posture list." />
                </div>
              ) : (
                <ul className="divide-y divide-border" data-testid="posture-list">
                  {checks.map((check) => (
                    <li key={check.id} className="flex flex-wrap items-start gap-3 px-5 py-3.5 sm:flex-nowrap" data-testid="posture-check" data-status={check.status}>
                      <StatusBadge status={check.status} className="mt-0.5 w-14 justify-center" />
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-medium">{check.title}</div>
                        <div className="mt-0.5 text-[13px] text-muted-foreground">{check.detail}</div>
                        <div className="mt-1 font-mono text-[11px] text-muted-foreground/70">{check.id}</div>
                      </div>
                      <div className="flex flex-wrap gap-1 sm:max-w-[40%] sm:justify-end">
                        {check.frameworks.map((framework) => (
                          <Badge key={framework} variant="outline" className="font-mono text-[10.5px]">
                            {framework}
                          </Badge>
                        ))}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
