import { Settings } from "lucide-react";
import { EmptyState, PageHeader } from "@/components/ui/misc";

/** Placeholder: replaced by the admin workstream. */
export function SettingsPage() {
  return (
    <div>
      <PageHeader title="Settings" description="Platform configuration, users, tokens and security posture." />
      <EmptyState icon={Settings} title="Settings are coming in this build" description="The admin workstream replaces this page." />
    </div>
  );
}
