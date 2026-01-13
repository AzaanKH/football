import * as React from "react"
import { cn } from "../../lib/utils"

const Progress = React.forwardRef(({ className, value, max = 100, ...props }, ref) => (
  <div
    ref={ref}
    className={cn(
      "relative h-4 w-full overflow-hidden rounded-full bg-secondary",
      className
    )}
    {...props}
  >
    <div
      className="h-full bg-primary transition-all duration-500 ease-out"
      style={{ width: `${Math.min(100, Math.max(0, (value / max) * 100))}%` }}
    />
  </div>
))
Progress.displayName = "Progress"

export { Progress }
