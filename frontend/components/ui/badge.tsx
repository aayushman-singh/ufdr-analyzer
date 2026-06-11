import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

// ForensicAI restyle: adds `signal` + severity variants (high/medium/low) used
// by patterns/page.tsx findings and the dashboard stat/case badges. Stock
// variants (default/secondary/destructive/outline) restyle from tokens alone.
const badgeVariants = cva(
  "inline-flex items-center justify-center rounded-md border px-2 py-0.5 text-xs font-medium w-fit whitespace-nowrap shrink-0 [&>svg]:size-3 gap-1 [&>svg]:pointer-events-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive transition-[color,box-shadow] overflow-hidden",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-primary text-primary-foreground [a&]:hover:bg-primary/90",
        signal:
          "border-signal/30 bg-signal/15 text-signal [a&]:hover:bg-signal/25",
        secondary:
          "border-transparent bg-secondary text-secondary-foreground [a&]:hover:bg-secondary/90",
        destructive:
          "border-transparent bg-destructive text-white [a&]:hover:bg-destructive/90",
        outline:
          "text-muted-foreground [a&]:hover:bg-accent [a&]:hover:text-accent-foreground",
        high:
          "border-[var(--severity-high)]/35 bg-[var(--severity-high)]/15 text-[oklch(0.78_0.16_22)]",
        medium:
          "border-[var(--severity-medium)]/32 bg-[var(--severity-medium)]/15 text-[oklch(0.84_0.13_82)]",
        low:
          "border-transparent bg-secondary text-muted-foreground",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

function Badge({
  className,
  variant,
  asChild = false,
  ...props
}: React.ComponentProps<"span"> &
  VariantProps<typeof badgeVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot : "span"

  return (
    <Comp
      data-slot="badge"
      className={cn(badgeVariants({ variant }), className)}
      {...props}
    />
  )
}

export { Badge, badgeVariants }
