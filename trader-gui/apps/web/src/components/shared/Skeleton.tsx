/**
 * Loading skeletons (§23 phase 16). A pulsing placeholder block and a table
 * variant, used to fill data views while their first fetch is in flight so the
 * layout does not jump when rows arrive. Reduced-motion users get a static
 * block via Tailwind's `motion-reduce` variant.
 */

interface SkeletonProps {
  className?: string;
}

/** A single pulsing placeholder block. Size it with `className`. */
export function Skeleton({ className = "" }: SkeletonProps) {
  return (
    <div
      className={`animate-pulse motion-reduce:animate-none rounded bg-[#1a1a28] ${className}`}
      aria-hidden="true"
    />
  );
}

interface TableSkeletonProps {
  /** Number of placeholder rows. */
  rows?: number;
  /** Number of columns per row. */
  columns?: number;
}

/**
 * A table-shaped skeleton: a header strip plus `rows` × `columns` cells.
 * Announced to assistive tech as a busy status so screen-reader users hear
 * "loading" rather than nothing.
 */
export function TableSkeleton({ rows = 8, columns = 5 }: TableSkeletonProps) {
  return (
    <div role="status" aria-busy="true" aria-live="polite" className="flex flex-col gap-1.5">
      <span className="sr-only">Loading…</span>
      <div className="flex gap-2">
        {Array.from({ length: columns }).map((_, c) => (
          <Skeleton key={c} className="h-4 flex-1" />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="flex gap-2">
          {Array.from({ length: columns }).map((_, c) => (
            <Skeleton key={c} className="h-3.5 flex-1" />
          ))}
        </div>
      ))}
    </div>
  );
}
