import { AlertTriangle, Boxes, FileCode, ShieldCheck, ShieldOff } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, Stat } from "@/components/ui/misc";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatDateTime } from "@/lib/format";
import { Markdown } from "./Markdown";
import { EventTypeBadge } from "./LogTab";
import type { RunEvent, RunRecord, RunState } from "@/types";

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function OverviewTab({ run, state, events }: { run: RunRecord; state: RunState | null; events: RunEvent[] }) {
  const last = [...events].reverse().find((event) => event.type === "node" || event.type === "end") ?? null;
  const summary = (last?.summary ?? {}) as Record<string, unknown>;
  const values = state?.values;
  const cim = values?.sized_cim ?? values?.cim;
  const validation = values?.validation_result;
  const quarantine = values?.quarantine_queue ?? [];
  const compliance = values?.compliance_result;

  const computeUnits = asNumber(summary.compute_units) ?? cim?.compute_units.length ?? null;
  const quarantined = asNumber(summary.quarantined) ?? (values ? quarantine.length : null);
  const hclFiles = asNumber(summary.hcl_files) ?? (values?.hcl_output ? Object.keys(values.hcl_output).length : null);
  const validationPassed = validation?.passed ?? (typeof summary.validation_passed === "boolean" ? summary.validation_passed : null);
  const validationErrors = validation?.errors?.length ?? asNumber(summary.validation_errors) ?? 0;
  const complianceFailed = compliance?.summary.failed ?? asNumber(summary.compliance_failed);
  const complianceAdvisory = compliance?.summary.advisory ?? asNumber(summary.compliance_advisory);
  const skippedValidation = run.options.skip_validation;

  const errors = validation?.errors ?? [];
  const warnings = validation?.warnings ?? [];
  const latestEvent = events.length > 0 ? events[events.length - 1] : null;

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Compute units" value={computeUnits ?? "–"} hint={cim ? `${cim.clusters.length} cluster${cim.clusters.length === 1 ? "" : "s"}` : "from the canonical model"} icon={Boxes} testId="stat-compute-units" />
        <Stat label="Quarantined" value={quarantined ?? "–"} hint={quarantined ? "blocked VMs, see below" : "nothing held back"} icon={AlertTriangle} tone={quarantined ? "warning" : "default"} testId="stat-quarantined" />
        <Stat label="HCL files" value={hclFiles ?? "–"} hint="generated Terraform" icon={FileCode} testId="stat-hcl-files" />
        <Stat
          label="Validation"
          value={validationPassed === null ? (skippedValidation ? "skipped" : "–") : validationPassed ? "passed" : "failed"}
          hint={validationPassed === null ? (skippedValidation ? "skip_validation is on" : "runs after generation") : validationErrors > 0 ? `${validationErrors} error${validationErrors === 1 ? "" : "s"}` : `${warnings.length} warning${warnings.length === 1 ? "" : "s"}`}
          icon={validationPassed === false ? ShieldOff : ShieldCheck}
          tone={validationPassed === null ? "default" : validationPassed ? "success" : "danger"}
          testId="stat-validation"
        />
        {complianceFailed !== null && complianceFailed !== undefined ? (
          <Stat label="Compliance" value={complianceFailed === 0 ? "clean" : `${complianceFailed} failed`} hint={`${complianceAdvisory ?? 0} advisory`} icon={ShieldCheck} tone={complianceFailed > 0 ? "danger" : complianceAdvisory ? "warning" : "success"} testId="stat-compliance" />
        ) : null}
      </div>

      {errors.length > 0 || warnings.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>Validation</CardTitle>
            <CardDescription>
              {validation?.terraform_validate_passed === false ? "terraform validate failed. " : ""}
              {validation?.tflint_passed === false ? "tflint reported problems. " : ""}
              {validation?.opa_passed === false ? "OPA policies failed. " : ""}
              {errors.length === 0 && warnings.length > 0 ? "Warnings only." : null}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-2 pt-0">
            {errors.map((item, index) => (
              <Alert key={`e${index}`} variant="error">
                <pre className="font-mono text-xs">{item}</pre>
              </Alert>
            ))}
            {warnings.map((item, index) => (
              <Alert key={`w${index}`} variant="warning">
                <pre className="font-mono text-xs">{item}</pre>
              </Alert>
            ))}
          </CardContent>
        </Card>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>Quarantine</CardTitle>
            <CardDescription>VMs the pipeline held back and why.</CardDescription>
          </CardHeader>
          <CardContent className="px-0 pt-0">
            {quarantine.length === 0 ? (
              <div className="px-5 pb-4 text-sm text-muted-foreground">{values ? "No quarantined VMs." : "The quarantine queue is available once the run pauses or ends."}</div>
            ) : (
              <Table data-testid="quarantine-table">
                <TableHeader>
                  <TableRow>
                    <TableHead className="pl-5">VM</TableHead>
                    <TableHead>Stage</TableHead>
                    <TableHead className="pr-5">Reasons</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {quarantine.map((item) => (
                    <TableRow key={`${item.stage}:${item.compute_unit_id}`}>
                      <TableCell className="pl-5 font-medium">{item.compute_unit_name}</TableCell>
                      <TableCell>
                        <Badge variant="outline" className="font-mono text-[11px]">
                          {item.stage}
                        </Badge>
                      </TableCell>
                      <TableCell className="pr-5">
                        <ul className="space-y-0.5 text-xs text-muted-foreground">
                          {item.reasons.map((reason, index) => (
                            <li key={index}>{reason}</li>
                          ))}
                        </ul>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Latest event</CardTitle>
            <CardDescription>{latestEvent ? formatDateTime(latestEvent.ts) : "No events yet."}</CardDescription>
          </CardHeader>
          <CardContent className="pt-0">
            {latestEvent ? (
              <div className="space-y-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <EventTypeBadge type={latestEvent.type} />
                  {latestEvent.node ? <span className="font-mono text-xs text-muted-foreground">{latestEvent.node}</span> : null}
                </div>
                {Object.keys(latestEvent.summary).length > 0 ? (
                  <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
                    {Object.entries(latestEvent.summary).map(([key, value]) => (
                      <SummaryRow key={key} label={key} value={value} />
                    ))}
                  </dl>
                ) : null}
                {latestEvent.messages.length > 0 ? (
                  <ul className="space-y-1 text-xs text-muted-foreground">
                    {latestEvent.messages.slice(-5).map((message, index) => (
                      <li key={index} className="truncate" title={message}>
                        {message}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ) : (
              <div className="text-sm text-muted-foreground">Events appear here as the pipeline runs.</div>
            )}
          </CardContent>
        </Card>
      </div>

      {values?.review_notes ? (
        <Card data-testid="review-notes">
          <CardHeader>
            <CardTitle>Review notes</CardTitle>
            <CardDescription>Written by the reporter for the person approving this migration.</CardDescription>
          </CardHeader>
          <CardContent className="pt-0">
            <Markdown source={values.review_notes} />
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: unknown }) {
  const text = value === null || value === undefined ? "–" : typeof value === "object" ? JSON.stringify(value) : String(value);
  return (
    <>
      <dt className="font-mono text-muted-foreground">{label.replace(/_/g, " ")}</dt>
      <dd className="truncate font-medium tabular" title={text}>
        {text}
      </dd>
    </>
  );
}
