import * as React from "react";
import { Check, Copy, ExternalLink, Hourglass, RefreshCw } from "lucide-react";
import { api } from "@/api";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Alert, Spinner } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import type { Connection, DeviceFlowStart } from "@/types";
import { describeApiError } from "./errors";

type Phase = "starting" | "pending" | "complete" | "expired" | "error";

/** Polling never runs faster than this, whatever the server suggests. */
export const MIN_POLL_SECONDS = 2;

function formatCountdown(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(seconds % 60).padStart(2, "0")}`;
}

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

/**
 * Starts a device authorization, shows the code and link, and polls until the flow ends.
 * Rendered inside DeviceFlowDialog; exported on its own so it can be tested without the portal.
 */
export function DeviceFlowPanel({ connectionId, onComplete, onClose }: { connectionId: string; onComplete?: () => void | Promise<void>; onClose?: () => void }) {
  const { toast } = useToast();
  const [attempt, setAttempt] = React.useState(0);
  const [phase, setPhase] = React.useState<Phase>("starting");
  const [flow, setFlow] = React.useState<DeviceFlowStart | null>(null);
  const [message, setMessage] = React.useState("");
  const [secondsLeft, setSecondsLeft] = React.useState(0);
  const [copied, setCopied] = React.useState<"code" | "url" | null>(null);
  const onCompleteRef = React.useRef(onComplete);
  onCompleteRef.current = onComplete;
  const toastRef = React.useRef(toast);
  toastRef.current = toast;

  React.useEffect(() => {
    let cancelled = false;
    let pollTimer: ReturnType<typeof setTimeout> | undefined;
    let tick: ReturnType<typeof setInterval> | undefined;
    setPhase("starting");
    setFlow(null);
    setMessage("");
    setCopied(null);

    const finish = (status: Phase, text: string) => {
      clearTimeout(pollTimer);
      clearInterval(tick);
      setPhase(status);
      setMessage(text);
      if (status === "complete") {
        toastRef.current({ title: "Signed in", description: text || "The connection was verified with the new sign-in.", variant: "success" });
        void onCompleteRef.current?.();
      }
    };

    void (async () => {
      let started: DeviceFlowStart;
      try {
        started = await api.deviceStart(connectionId);
      } catch (exc) {
        if (!cancelled) finish("error", describeApiError(exc).message || "Could not start the sign-in.");
        return;
      }
      if (cancelled) return;
      setFlow(started);
      setPhase("pending");

      const expiresAt = Date.now() + Math.max(0, started.expires_in) * 1000;
      setSecondsLeft(Math.max(0, Math.round(started.expires_in)));
      tick = setInterval(() => {
        const left = Math.max(0, Math.round((expiresAt - Date.now()) / 1000));
        setSecondsLeft(left);
        if (left <= 0) finish("expired", "The code expired before the sign-in completed.");
      }, 1000);

      const suggested = typeof started.interval === "number" && Number.isFinite(started.interval) ? started.interval : 5;
      const intervalMs = Math.max(suggested, MIN_POLL_SECONDS) * 1000;
      const poll = async () => {
        if (cancelled) return;
        try {
          const result = await api.devicePoll(connectionId, started.flow_id);
          if (cancelled) return;
          if (result.status === "pending") {
            pollTimer = setTimeout(() => void poll(), intervalMs);
            return;
          }
          if (result.status === "complete") {
            finish("complete", result.message);
            return;
          }
          // The API answers with a generic sentence; the provider's own (sanitised) message is
          // recorded on the connection's last check, so fetch it to show the actual reason.
          let detail = "";
          try {
            const refreshed = await api.getConnection(connectionId);
            detail = refreshed.last_check?.message ?? "";
          } catch {
            /* the generic message is still shown */
          }
          const text = detail || result.message;
          if (result.status === "expired") finish("expired", text || "The code expired; start again.");
          else finish("error", text || "The sign-in failed.");
        } catch (exc) {
          if (!cancelled) finish("error", describeApiError(exc).message);
        }
      };
      pollTimer = setTimeout(() => void poll(), intervalMs);
    })();

    return () => {
      cancelled = true;
      clearTimeout(pollTimer);
      clearInterval(tick);
    };
  }, [connectionId, attempt]);

  async function copy(kind: "code" | "url", text: string) {
    const ok = await copyText(text);
    setCopied(ok ? kind : null);
    toast(ok ? { title: "Copied", description: kind === "code" ? "The code is on your clipboard." : "The link is on your clipboard.", variant: "success" } : { title: "Could not copy", description: "Select the text and copy it manually.", variant: "warning" });
    if (ok) setTimeout(() => setCopied(null), 1500);
  }

  const openUrl = flow?.verification_uri_complete || flow?.verification_uri;

  return (
    <div className="space-y-4" data-testid="device-flow" data-phase={phase}>
      {phase === "starting" ? (
        <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
          <Spinner /> Contacting the identity provider…
        </div>
      ) : null}

      {phase === "pending" && flow ? (
        <>
          <div className="space-y-2 text-center">
            <div className="text-xs font-medium uppercase tracking-wider text-muted-foreground">Enter this code on the sign-in page</div>
            <div className="flex items-center justify-center gap-2">
              <code className="select-all rounded-lg border border-border bg-muted/50 px-4 py-2.5 font-mono text-2xl font-semibold tracking-[0.18em]" data-testid="device-code">
                {flow.user_code}
              </code>
              <Button variant="outline" size="icon" aria-label="Copy code" onClick={() => void copy("code", flow.user_code)} data-testid="copy-code">
                {copied === "code" ? <Check className="text-success" /> : <Copy />}
              </Button>
            </div>
          </div>
          <div className="flex items-center justify-between gap-2 rounded-md border border-border px-3 py-2 text-sm">
            <a href={flow.verification_uri} target="_blank" rel="noreferrer noopener" className="min-w-0 truncate font-mono text-[12.5px] text-primary hover:underline" data-testid="device-url">
              {flow.verification_uri}
            </a>
            <Button variant="ghost" size="icon-sm" aria-label="Copy link" onClick={() => void copy("url", flow.verification_uri)} data-testid="copy-url">
              {copied === "url" ? <Check className="text-success" /> : <Copy />}
            </Button>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Button asChild>
              <a href={openUrl} target="_blank" rel="noreferrer noopener" data-testid="device-open">
                <ExternalLink /> Open sign-in page
              </a>
            </Button>
            <div className="flex items-center gap-3 text-xs text-muted-foreground">
              <span className="inline-flex items-center gap-1.5">
                <Spinner className="size-3.5" /> Waiting for approval
              </span>
              <span className="inline-flex items-center gap-1 tabular" data-testid="device-countdown">
                <Hourglass className="size-3.5" /> {formatCountdown(secondsLeft)}
              </span>
            </div>
          </div>
        </>
      ) : null}

      {phase === "complete" ? (
        <Alert variant="success" title="Signed in" testId="device-complete">
          {message || "The connection was verified with the new sign-in."}
        </Alert>
      ) : null}

      {phase === "expired" ? (
        <Alert variant="warning" title="The code expired" testId="device-expired">
          {message || "Start the sign-in again to get a new code."}
        </Alert>
      ) : null}

      {phase === "error" ? (
        <Alert variant="error" title="Sign-in failed" testId="device-error">
          <p className="break-words">{message || "The identity provider rejected the request."}</p>
        </Alert>
      ) : null}

      <DialogFooter className="mt-2">
        {phase === "expired" || phase === "error" ? (
          <Button variant="outline" onClick={() => setAttempt((current) => current + 1)} data-testid="device-retry">
            <RefreshCw /> {phase === "expired" ? "Start again" : "Try again"}
          </Button>
        ) : null}
        <Button variant={phase === "complete" ? "default" : "ghost"} onClick={onClose} data-testid="device-close">
          {phase === "complete" ? "Done" : phase === "pending" ? "Cancel" : "Close"}
        </Button>
      </DialogFooter>
    </div>
  );
}

const DESCRIPTIONS: Record<string, string> = {
  sso: "IAM Identity Center device authorization. Approve the request in your browser; the access token is stored encrypted and usually lasts about eight hours.",
  device_code: "Microsoft Entra ID device-code sign-in. The credential stays in the server's memory until it restarts, so you may need to sign in again later.",
};

export function DeviceFlowDialog({ connection, open, onOpenChange, onComplete }: { connection: Connection; open: boolean; onOpenChange: (open: boolean) => void; onComplete?: () => void | Promise<void> }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="md">
        <DialogHeader>
          <DialogTitle>Sign in to {connection.name}</DialogTitle>
          <DialogDescription>{DESCRIPTIONS[connection.auth_method] ?? "Approve the sign-in in your browser; the platform polls until it completes."}</DialogDescription>
        </DialogHeader>
        <div className="mt-4">{open ? <DeviceFlowPanel connectionId={connection.id} onComplete={onComplete} onClose={() => onOpenChange(false)} /> : null}</div>
      </DialogContent>
    </Dialog>
  );
}
