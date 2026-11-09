import type { AssessmentResult } from "@/types";

export const RISK_LEVELS = ["safe", "caution", "elevated", "critical"] as const;
export type RiskLevel = (typeof RISK_LEVELS)[number];

function csvCell(value: unknown): string {
  const text = String(value ?? "");
  // RFC 4180: wrap in quotes and double the embedded quotes; backslashes carry no meaning in CSV.
  return /[",\n\r]/.test(text) ? `"${text.split('"').join('""')}"` : text;
}

function mdCell(value: unknown): string {
  return String(value ?? "").replace(/\|/g, "\\|").replace(/\r?\n/g, " ");
}

export function exportFilename(result: AssessmentResult, extension: string): string {
  const day = result.generated_at ? result.generated_at.slice(0, 10) : new Date().toISOString().slice(0, 10);
  return `assessment-${result.target_provider || "cloud"}-${day}.${extension}`;
}

/** One row per resource; list fields joined with "; " so the file opens cleanly in a spreadsheet. */
export function assessmentToCsv(result: AssessmentResult): string {
  const header = ["resource_name", "resource_type", "resource_id", "risk_level", "risk_score", "safe_to_migrate", "reasons", "recommendations", "missing_data"];
  const lines = [header.join(",")];
  for (const resource of result.resources) {
    lines.push(
      [
        resource.resource_name,
        resource.resource_type,
        resource.resource_id,
        resource.risk_level,
        resource.risk_score,
        resource.safe_to_migrate ? "yes" : "no",
        resource.reasons.join("; "),
        resource.recommendations.join("; "),
        resource.missing_data.join("; "),
      ]
        .map(csvCell)
        .join(","),
    );
  }
  return `${lines.join("\n")}\n`;
}

export function assessmentToMarkdown(result: AssessmentResult): string {
  const { summary } = result;
  const lines = [
    "# Migration readiness assessment",
    "",
    `- Source vCenter: ${result.source_vcenter || "unknown"}`,
    `- Target provider: ${result.target_provider}`,
    `- Generated: ${result.generated_at}`,
    "",
    "## Summary",
    "",
    "| Level | Resources |",
    "|---|---:|",
    `| Total | ${summary.total_resources} |`,
    ...RISK_LEVELS.map((level) => `| ${level} | ${summary[level]} |`),
    "",
    "## Resources",
    "",
    "| Resource | Type | Risk | Score | Safe to migrate | Reasons | Recommendations | Missing data |",
    "|---|---|---|---:|---|---|---|---|",
  ];
  for (const resource of result.resources) {
    lines.push(
      `| ${[resource.resource_name, resource.resource_type, resource.risk_level, resource.risk_score, resource.safe_to_migrate ? "yes" : "no", resource.reasons.join("; ") || "–", resource.recommendations.join("; ") || "–", resource.missing_data.join("; ") || "–"].map(mdCell).join(" | ")} |`,
    );
  }
  return `${lines.join("\n")}\n`;
}
