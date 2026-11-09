import * as React from "react";
import { api } from "@/api";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Alert } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import type { Connection } from "@/types";
import { describeApiError } from "./errors";

export function DeleteConnectionDialog({ connection, onOpenChange, onDeleted }: { connection: Connection | null; onOpenChange: (open: boolean) => void; onDeleted: (connection: Connection) => void }) {
  const { toast } = useToast();
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    setError(null);
    setBusy(false);
  }, [connection?.id]);

  async function remove() {
    if (!connection) return;
    setBusy(true);
    setError(null);
    try {
      await api.deleteConnection(connection.id);
      toast({ title: "Connection deleted", description: connection.name, variant: "success" });
      onDeleted(connection);
      onOpenChange(false);
    } catch (exc) {
      setError(describeApiError(exc).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={connection !== null} onOpenChange={(open) => !open && !busy && onOpenChange(false)}>
      <DialogContent size="sm">
        <DialogHeader>
          <DialogTitle>Delete this connection?</DialogTitle>
          <DialogDescription>
            <span className="font-medium text-foreground">{connection?.name}</span> and its stored credentials will be removed. Runs that reference it keep their history but can no longer plan or apply with it. This cannot be undone.
          </DialogDescription>
        </DialogHeader>
        {error ? (
          <Alert variant="error" className="mt-4" testId="delete-error">
            {error}
          </Alert>
        ) : null}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            Keep it
          </Button>
          <Button variant="destructive" onClick={() => void remove()} loading={busy} data-testid="confirm-delete-connection">
            Delete connection
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
