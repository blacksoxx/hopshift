import * as React from "react";
import { Check, Copy } from "lucide-react";
import { Button, type ButtonProps } from "@/components/ui/button";

/** Copies `text` to the clipboard and shows a short confirmation on the button itself. */
export function CopyButton({ text, label = "Copy", testId, ...props }: { text: string; label?: string; testId?: string } & Omit<ButtonProps, "onClick" | "children">) {
  const [copied, setCopied] = React.useState(false);
  React.useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 1800);
    return () => clearTimeout(timer);
  }, [copied]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      /* clipboard blocked: the value stays visible for manual selection */
    }
  }

  return (
    <Button type="button" variant="outline" size="sm" onClick={() => void copy()} data-testid={testId} {...props}>
      {copied ? <Check className="text-success" /> : <Copy />} {copied ? "Copied" : label}
    </Button>
  );
}
