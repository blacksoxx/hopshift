import * as React from "react";
import { FileJson, Upload } from "lucide-react";
import { Alert } from "@/components/ui/misc";
import { cn } from "@/lib/utils";
import { formatBytes } from "@/lib/format";
import { readDiscoveryFile, type LoadedDiscovery } from "./discovery";

/** Drop zone plus hidden file input; parses the discovery JSON in the browser and reports a summary. */
export function DiscoveryUpload({ file, onChange }: { file: LoadedDiscovery | null; onChange: (file: LoadedDiscovery | null) => void }) {
  const [error, setError] = React.useState<string | null>(null);
  const [dragging, setDragging] = React.useState(false);
  const input = React.useRef<HTMLInputElement>(null);

  async function load(selected: File) {
    try {
      onChange(await readDiscoveryFile(selected));
      setError(null);
    } catch (exc) {
      onChange(null);
      setError((exc as Error).message);
    }
  }

  const summary = file?.summary;

  return (
    <div className="space-y-4">
      <div
        role="button"
        tabIndex={0}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            input.current?.click();
          }
        }}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          const dropped = event.dataTransfer.files?.[0];
          if (dropped) void load(dropped);
        }}
        onClick={() => input.current?.click()}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors hover:border-primary/60 hover:bg-accent/40",
          file ? "border-success/50 bg-success/5" : "border-border",
          dragging && "border-primary bg-accent/60",
        )}
        data-testid="dropzone"
      >
        <input
          ref={input}
          type="file"
          accept="application/json,.json"
          className="hidden"
          onChange={(event) => {
            const selected = event.target.files?.[0];
            if (selected) void load(selected);
            event.target.value = "";
          }}
          data-testid="discovery-file"
        />
        {file ? (
          <>
            <FileJson className="size-8 text-success" />
            <div className="text-sm font-medium">{file.name}</div>
            <div className="text-xs text-muted-foreground">{formatBytes(file.size)} · click to replace</div>
          </>
        ) : (
          <>
            <Upload className="size-8 text-muted-foreground" />
            <div className="text-sm font-medium">Drop the discovery JSON here, or click to browse</div>
            <div className="text-xs text-muted-foreground">Only .json files are accepted; nothing is uploaded until you run the assessment</div>
          </>
        )}
      </div>

      {error ? (
        <Alert variant="error" testId="discovery-error">
          {error}
        </Alert>
      ) : null}

      {summary ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4" data-testid="discovery-summary">
          {[
            ["Virtual machines", summary.vms],
            ["Blocked at source", summary.blocked],
            ["Clusters", summary.clusters],
            ["vCenter", summary.vcenter],
          ].map(([label, value]) => (
            <div key={String(label)} className="rounded-lg border border-border bg-muted/40 px-3 py-2">
              <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
              <div className="truncate text-sm font-semibold tabular" title={String(value)}>
                {String(value)}
              </div>
            </div>
          ))}
          <div className="col-span-2 text-xs text-muted-foreground sm:col-span-4">
            Schema {summary.schema} {summary.version}
            {summary.poweredOff > 0 ? ` · ${summary.poweredOff} powered off` : ""}
          </div>
        </div>
      ) : null}
    </div>
  );
}
