import { Cable } from "lucide-react";
import { EmptyState, PageHeader } from "@/components/ui/misc";

/** Placeholder: replaced by the connections workstream. */
export function ConnectionsPage() {
  return (
    <div>
      <PageHeader title="Connections" description="Cloud accounts used to plan and apply generated infrastructure." />
      <EmptyState icon={Cable} title="Connections are coming in this build" description="The connections workstream replaces this page." />
    </div>
  );
}
