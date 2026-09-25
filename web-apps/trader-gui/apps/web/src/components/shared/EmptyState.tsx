import type { LucideIcon } from "lucide-react";
import { Inbox } from "lucide-react";
import type { ReactNode } from "react";

interface EmptyStateProps {
  /** Short headline, e.g. "No open orders". */
  title: string;
  /** Optional secondary line explaining why it's empty or what to do next. */
  hint?: ReactNode;
  /** Icon to show above the title; defaults to an inbox. */
  icon?: LucideIcon;
  /** Optional action (e.g. a Retry button). */
  action?: ReactNode;
}

/**
 * A consistent "nothing here" placeholder (§23 phase 16). Used for genuinely
 * empty result sets so a blank panel reads as intentional rather than broken.
 * Error/degraded states keep their own dedicated messaging.
 */
export function EmptyState({ title, hint, icon: Icon = Inbox, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded border border-line p-8 text-center">
      <Icon size={24} className="text-fg-faint" aria-hidden="true" />
      <p className="text-sm text-fg-dim">{title}</p>
      {hint && <p className="max-w-sm text-xs text-fg-faint">{hint}</p>}
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}
