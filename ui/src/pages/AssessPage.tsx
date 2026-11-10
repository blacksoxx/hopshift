import * as React from "react";
import { BarChart3 } from "lucide-react";
import { api } from "@/api";
import { useTargets } from "@/hooks/useTargets";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field } from "@/components/ui/input";
import { Alert, PageHeader, Skeleton, Spinner } from "@/components/ui/misc";
import { SimpleSelect } from "@/components/ui/select";
import { TierBadge } from "@/components/TargetBadge";
import { DiscoveryUpload } from "@/components/assess/DiscoveryUpload";
import { AssessmentResults } from "@/components/assess/AssessmentResults";
import type { LoadedDiscovery } from "@/components/assess/discovery";
import type { AssessmentResult } from "@/types";

export function AssessPage() {
  const { targets, loading: targetsLoading, error: targetsError, labelOf, specOf } = useTargets();
  const [file, setFile] = React.useState<LoadedDiscovery | null>(null);
  const [cloud, setCloud] = React.useState("");
  const [result, setResult] = React.useState<{ cloud: string; data: AssessmentResult } | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  // Default to the first registered target once the registry has answered.
  React.useEffect(() => {
    if (targets.length > 0 && !targets.some((item) => item.name === cloud)) setCloud(targets[0].name);
  }, [targets, cloud]);

  const target = specOf(cloud);

  async function run() {
    if (!file || !cloud) return;
    setBusy(true);
    setError(null);
    try {
      setResult({ cloud, data: await api.assess(file.payload, cloud) });
    } catch (exc) {
      setError((exc as Error).message || "The assessment failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <PageHeader title="Assess" description="Deterministic readiness report over the whole inventory. No target access, no model; blocked workloads are scored instead of dropped." />

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <Card>
          <CardHeader>
            <CardTitle>Discovery JSON</CardTitle>
            <CardDescription>The export a source collector produced. Parsed in the browser; nothing is stored on the server.</CardDescription>
          </CardHeader>
          <CardContent>
            <DiscoveryUpload
              file={file}
              onChange={(next) => {
                setFile(next);
                setResult(null);
                setError(null);
              }}
            />
          </CardContent>
        </Card>

        <Card className="self-start">
          <CardHeader>
            <CardTitle>Target</CardTitle>
            <CardDescription>Scoring rules differ per target.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {targetsError ? (
              <Alert variant="error" title="Could not load the target registry" testId="assess-targets-error">
                {targetsError}
              </Alert>
            ) : targetsLoading && targets.length === 0 ? (
              <Skeleton className="h-9" />
            ) : (
              <Field
                label="Target"
                htmlFor="assess-cloud"
                hint={
                  target ? (
                    <span className="inline-flex items-center gap-1.5">
                      {target.blurb} <TierBadge tier={target.tier} />
                    </span>
                  ) : undefined
                }
              >
                <SimpleSelect id="assess-cloud" value={cloud} onValueChange={setCloud} options={targets.map((item) => ({ value: item.name, label: item.label }))} placeholder="Choose a target" testId="assess-cloud" />
              </Field>
            )}
            {error ? (
              <Alert variant="error" title="The assessment failed" testId="assess-error">
                {error}
              </Alert>
            ) : null}
            <Button onClick={() => void run()} loading={busy} disabled={!file || !cloud} className="w-full" data-testid="run-assess">
              <BarChart3 /> {busy ? "Scoring…" : "Run assessment"}
            </Button>
            <p className="text-xs text-muted-foreground">Runs synchronously on the server: a few seconds for hundreds of workloads. The result stays on this page until you leave.</p>
          </CardContent>
        </Card>
      </div>

      {busy ? (
        <Card className="mt-4">
          <CardContent className="flex items-center justify-center gap-3 py-8 text-sm text-muted-foreground" data-testid="assess-busy">
            <Spinner /> Scoring {file?.summary.vms ?? 0} workloads for {labelOf(cloud)}…
          </CardContent>
        </Card>
      ) : null}

      {result && !busy ? (
        <div className="mt-6">
          <AssessmentResults result={result.data} cloud={result.cloud} />
        </div>
      ) : null}
    </div>
  );
}
