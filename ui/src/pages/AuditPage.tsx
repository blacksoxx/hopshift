import { ScrollText } from "lucide-react";
import { EmptyState, PageHeader } from "@/components/ui/misc";

/** Placeholder: replaced by the admin workstream. */
export function AuditPage() {
  return (
    <div>
      <PageHeader title="Audit log" description="Tamper-evident record of every action on the platform." />
      <EmptyState icon={ScrollText} title="The audit log viewer is coming in this build" description="The admin workstream replaces this page." />
    </div>
  );
}
