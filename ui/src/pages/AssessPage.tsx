import * as React from "react";
import { BarChart3 } from "lucide-react";
import { api } from "@/api";
import { useAsync } from "@/hooks/useAsync";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field } from "@/components/ui/input";
import { Alert, PageHeader, Spinner } from "@/components/ui/misc";
import { SimpleSelect } from "@/components/ui/select";
import { DiscoveryUpload } from "@/components/assess/DiscoveryUpload";
import { AssessmentResults } from "@/components/assess/AssessmentResults";
import type { LoadedDiscovery } from "@/components/assess/discovery";
import type { AssessmentResult } from "@/types";

const FALLBACK_CLOUDS = ["aws", "azure", "gcp", "openstack"];

export function AssessPage() {
  const meta = useAsync(() => api.meta(), []);
  const [file, setFile] = React.useState<LoadedDiscovery | null>(null);
  const [cloud, setCloud] = React.useState("aws");
  const [result, setResult] = React.useState<{ cloud: string; data: AssessmentResult } | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const clouds = meta.data?.clouds ?? FALLBACK_CLOUDS;

  async function run() {
    if (!file) return;
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
      <PageHeader title="Assess" description="Deterministic readiness report over the whole inventory. No cloud access, no model; blocked VMs are scored instead of dropped." />

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <Card>
          <CardHeader>
            <CardTitle>Discovery JSON</CardTitle>
            <CardDescription>Output of the vSphere discovery playbook. Parsed in the browser; nothing is stored on the server.</CardDescription>
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
            <CardDescription>Scoring rules differ per provider.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Field label="Target cloud" htmlFor="assess-cloud">
              <SimpleSelect id="assess-cloud" value={cloud} onValueChange={setCloud} options={clouds.map((item) => ({ value: item, label: item.toUpperCase() }))} testId="assess-cloud" />
            </Field>
            {error ? (
              <Alert variant="error" title="The assessment failed" testId="assess-error">
                {error}
              </Alert>
            ) : null}
            <Button onClick={() => void run()} loading={busy} disabled={!file} className="w-full" data-testid="run-assess">
              <BarChart3 /> {busy ? "Scoring…" : "Run assessment"}
            </Button>
            <p className="text-xs text-muted-foreground">Runs synchronously on the server: a few seconds for hundreds of VMs. The result stays on this page until you leave.</p>
          </CardContent>
        </Card>
      </div>

      {busy ? (
        <Card className="mt-4">
          <CardContent className="flex items-center justify-center gap-3 py-8 text-sm text-muted-foreground" data-testid="assess-busy">
            <Spinner /> Scoring {file?.summary.vms ?? 0} virtual machines for {cloud.toUpperCase()}…
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
