import * as React from "react";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cn } from "@/lib/utils";

export const Tabs = TabsPrimitive.Root;

export const TabsList = React.forwardRef<React.ElementRef<typeof TabsPrimitive.List>, React.ComponentPropsWithoutRef<typeof TabsPrimitive.List> & { variant?: "pill" | "underline" }>(
  ({ className, variant = "underline", ...props }, ref) => (
    <TabsPrimitive.List
      ref={ref}
      className={cn(
        variant === "pill"
          ? "inline-flex h-9 items-center gap-1 rounded-lg bg-muted p-1 text-muted-foreground"
          : "flex items-center gap-1 border-b border-border text-muted-foreground",
        className,
      )}
      data-variant={variant}
      {...props}
    />
  ),
);
TabsList.displayName = "TabsList";

export const TabsTrigger = React.forwardRef<React.ElementRef<typeof TabsPrimitive.Trigger>, React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>>(
  ({ className, ...props }, ref) => (
    <TabsPrimitive.Trigger
      ref={ref}
      className={cn(
        "group/tab relative inline-flex items-center gap-1.5 whitespace-nowrap px-3 py-2 text-sm font-medium transition-colors hover:text-foreground disabled:pointer-events-none disabled:opacity-50 data-[state=active]:text-foreground [&_svg]:size-4",
        // underline variant
        "after:absolute after:inset-x-2 after:-bottom-px after:h-0.5 after:rounded-full after:bg-primary after:opacity-0 after:transition-opacity data-[state=active]:after:opacity-100",
        // pill variant overrides
        "[[data-variant=pill]_&]:h-7 [[data-variant=pill]_&]:rounded-md [[data-variant=pill]_&]:px-3 [[data-variant=pill]_&]:py-0 [[data-variant=pill]_&]:text-xs [[data-variant=pill]_&]:after:hidden [[data-variant=pill]_&]:data-[state=active]:bg-card [[data-variant=pill]_&]:data-[state=active]:shadow-sm",
        className,
      )}
      {...props}
    />
  ),
);
TabsTrigger.displayName = "TabsTrigger";

export const TabsContent = React.forwardRef<React.ElementRef<typeof TabsPrimitive.Content>, React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>>(
  ({ className, ...props }, ref) => <TabsPrimitive.Content ref={ref} className={cn("mt-4 outline-none data-[state=active]:animate-[fade-in_0.18s_ease-out]", className)} {...props} />,
);
TabsContent.displayName = "TabsContent";
