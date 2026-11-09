import * as React from "react";
import * as ToastPrimitive from "@radix-ui/react-toast";
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";

export type ToastVariant = "default" | "success" | "error" | "warning";

export interface ToastOptions {
  title: React.ReactNode;
  description?: React.ReactNode;
  variant?: ToastVariant;
  duration?: number;
}

interface ToastItem extends ToastOptions {
  id: number;
}

interface ToastContextValue {
  toast: (options: ToastOptions) => void;
}

const ToastContext = React.createContext<ToastContextValue | null>(null);

const ICONS: Record<ToastVariant, React.ComponentType<{ className?: string }>> = {
  default: Info,
  success: CheckCircle2,
  error: XCircle,
  warning: AlertTriangle,
};

const COLORS: Record<ToastVariant, string> = {
  default: "text-info",
  success: "text-success",
  error: "text-destructive",
  warning: "text-warning",
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = React.useState<ToastItem[]>([]);
  const counter = React.useRef(0);

  const toast = React.useCallback((options: ToastOptions) => {
    counter.current += 1;
    const id = counter.current;
    setItems((current) => [...current.slice(-4), { id, ...options }]);
  }, []);

  const dismiss = (id: number) => setItems((current) => current.filter((item) => item.id !== id));

  return (
    <ToastContext.Provider value={{ toast }}>
      <ToastPrimitive.Provider swipeDirection="right" duration={4500}>
        {children}
        {items.map((item) => {
          const variant = item.variant ?? "default";
          const Icon = ICONS[variant];
          return (
            <ToastPrimitive.Root
              key={item.id}
              duration={item.duration}
              onOpenChange={(open) => !open && dismiss(item.id)}
              className={cn(
                "group pointer-events-auto relative flex w-full items-start gap-3 rounded-lg border border-border bg-popover p-4 pr-8 shadow-xl",
                "data-[state=open]:animate-[fade-in_0.18s_ease-out] data-[swipe=move]:translate-x-[var(--radix-toast-swipe-move-x)] data-[swipe=end]:translate-x-full data-[swipe=end]:opacity-0 data-[state=closed]:opacity-0 transition-opacity",
              )}
              data-testid="toast"
            >
              <Icon className={cn("mt-0.5 size-4 shrink-0", COLORS[variant])} />
              <div className="min-w-0 flex-1 space-y-0.5">
                <ToastPrimitive.Title className="text-sm font-medium leading-tight">{item.title}</ToastPrimitive.Title>
                {item.description ? <ToastPrimitive.Description className="text-xs text-muted-foreground break-words">{item.description}</ToastPrimitive.Description> : null}
              </div>
              <ToastPrimitive.Close className="absolute right-2 top-2 rounded-md p-1 text-muted-foreground opacity-60 hover:opacity-100">
                <X className="size-3.5" />
              </ToastPrimitive.Close>
            </ToastPrimitive.Root>
          );
        })}
        <ToastPrimitive.Viewport className="fixed bottom-4 right-4 z-[100] flex w-[360px] max-w-[calc(100vw-2rem)] flex-col gap-2 outline-none" />
      </ToastPrimitive.Provider>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const context = React.useContext(ToastContext);
  if (!context) throw new Error("useToast must be used within ToastProvider");
  return context;
}
