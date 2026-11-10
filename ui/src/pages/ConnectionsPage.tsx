import * as React from "react";
import { useParams } from "react-router-dom";
import { Plus } from "lucide-react";
import { api } from "@/api";
import { useAsync } from "@/hooks/useAsync";
import { Button } from "@/components/ui/button";
import { Alert, PageHeader } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { useAuth } from "@/providers/AuthProvider";
import { AddConnectionDialog } from "@/components/connections/AddConnectionDialog";
import { ConnectionDetail } from "@/components/connections/ConnectionDetail";
import { ConnectionList } from "@/components/connections/ConnectionList";
import { DeleteConnectionDialog } from "@/components/connections/DeleteDialog";
import { EditConnectionDialog } from "@/components/connections/EditConnectionDialog";
import { describeApiError } from "@/components/connections/errors";
import { identitySummary } from "@/components/connections/providers";
import type { Connection } from "@/types";

/** `/connections` lists the stored connections; `/connections/:connectionId` shows one. */
export function ConnectionsPage() {
  const { connectionId } = useParams<{ connectionId: string }>();
  if (connectionId) return <ConnectionDetail key={connectionId} connectionId={connectionId} />;
  return <ConnectionsIndex />;
}

function ConnectionsIndex() {
  const { can } = useAuth();
  const { toast } = useToast();
  const meta = useAsync(() => api.meta(), []);
  const catalog = useAsync(() => api.connectionCatalog(), []);
  const connections = useAsync(() => api.listConnections(), [], { pollMs: 30000 });
  const [addOpen, setAddOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<Connection | null>(null);
  const [deleting, setDeleting] = React.useState<Connection | null>(null);
  const [testingId, setTestingId] = React.useState<string | null>(null);

  const secretsAvailable = meta.data ? meta.data.features.secrets : true;
  const connectionsEnabled = meta.data ? meta.data.features.connections : true;
  const items = connections.data ?? [];

  async function test(connection: Connection) {
    setTestingId(connection.id);
    try {
      const check = await api.testConnection(connection.id);
      toast({
        title: check.ok ? `${connection.name} verified` : `${connection.name} failed verification`,
        description: check.ok ? (identitySummary({ provider: connection.provider, last_check: { identity: check.identity } }) ?? check.message) : check.message,
        variant: check.ok ? "success" : "error",
      });
      await connections.reload();
    } catch (exc) {
      const info = describeApiError(exc);
      toast({ title: info.title, description: info.message, variant: "error" });
    } finally {
      setTestingId(null);
    }
  }

  return (
    <div>
      <PageHeader
        title="Connections"
        description="Target accounts hopshift verifies and hands to Terraform for plan and apply."
        actions={
          can("admin") && connectionsEnabled ? (
            <Button onClick={() => setAddOpen(true)} data-testid="add-connection">
              <Plus /> Add connection
            </Button>
          ) : null
        }
      />

      {!connectionsEnabled ? (
        <Alert variant="error" title="The connections service is not available" className="mb-4" testId="connections-disabled">
          This server was started without the connections service; check the server log for the reason.
        </Alert>
      ) : null}

      {connectionsEnabled && !secretsAvailable ? (
        <Alert variant="warning" title="Credentials cannot be stored yet" className="mb-4" testId="secrets-warning">
          Set <code className="font-mono text-[12px]">HOPSHIFT_SECRET_KEY</code> on the server (generate one with <code className="font-mono text-[12px]">vma secrets generate-key</code>) and restart it to add methods that store secrets. Methods that use the
          host's own identity, such as the process environment, a named profile, managed identity, the Azure CLI, application default credentials or clouds.yaml, still work.
        </Alert>
      ) : null}

      <ConnectionList
        connections={items}
        catalog={catalog.data}
        loading={connections.loading}
        error={connections.error}
        onRetry={() => void connections.reload()}
        canTest={can("operator")}
        canManage={can("admin")}
        testingId={testingId}
        onTest={(connection) => void test(connection)}
        onEdit={setEditing}
        onDelete={setDeleting}
        onAdd={connectionsEnabled ? () => setAddOpen(true) : undefined}
      />

      <AddConnectionDialog open={addOpen} onOpenChange={setAddOpen} catalog={catalog.data} secretsAvailable={secretsAvailable} existingNames={items.map((item) => item.name)} onCreated={() => void connections.reload()} />
      <EditConnectionDialog
        connection={editing}
        catalog={catalog.data}
        onOpenChange={(open) => !open && setEditing(null)}
        secretsAvailable={secretsAvailable}
        existingNames={items.map((item) => item.name)}
        onSaved={() => void connections.reload()}
      />
      <DeleteConnectionDialog connection={deleting} onOpenChange={(open) => !open && setDeleting(null)} onDeleted={() => void connections.reload()} />
    </div>
  );
}
