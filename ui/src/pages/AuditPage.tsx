import { PageHeader } from "@/components/ui/misc";
import { AuditLog } from "@/components/settings/AuditLog";

export function AuditPage() {
  return (
    <div>
      <PageHeader title="Audit log" description="Tamper-evident record of every action on the platform. Entries are hash-chained; verify the chain before exporting evidence." />
      <AuditLog />
    </div>
  );
}
