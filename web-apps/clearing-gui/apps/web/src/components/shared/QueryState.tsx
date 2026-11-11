import type { ReactNode } from "react";
import { AlertTriangle, Lock } from "lucide-react";
import { ApiError, ContractError, NetworkError, isForbidden } from "@/api/errors";
import { EmptyState } from "./EmptyState";
import { TableSkeleton } from "./Skeleton";

/** The parts of a TanStack query (plain or infinite) this component reads. */
export interface QueryLike<T> {
  isPending: boolean;
  isError: boolean;
  error: unknown;
  data: T | undefined;
  refetch: () => unknown;
}

interface QueryStateProps<T> {
  query: QueryLike<T>;
  /** Whether a successful result has nothing to show. */
  isEmpty?: (data: T) => boolean;
  /** What an empty result means, in words: a true zero, not a failure. */
  emptyTitle?: string;
  emptyHint?: ReactNode;
  skeletonColumns?: number;
  children: (data: T) => ReactNode;
}

/**
 * The four states every clearing view has, rendered the same way everywhere:
 *
 * - loading: a busy table skeleton;
 * - error: a `role="alert"` panel that names the cause -- refused (403, no
 *   retry), unavailable store or other gateway error (with Retry), a reply
 *   that breaks the API contract, or no answer at all;
 * - empty: an explicit "nothing here" message, which is a real zero;
 * - data: `children(data)`.
 *
 * So an unavailable ledger can never be mistaken for "no positions".
 */
export function QueryState<T>({
  query,
  isEmpty,
  emptyTitle = "Nothing to show",
  emptyHint,
  skeletonColumns = 6,
  children,
}: QueryStateProps<T>) {
  if (query.isPending) return <TableSkeleton rows={5} columns={skeletonColumns} />;
  if (query.isError || query.data === undefined) {
    return <ErrorPanel error={query.error} onRetry={() => void query.refetch()} />;
  }
  if (isEmpty?.(query.data)) return <EmptyState title={emptyTitle} hint={emptyHint} />;
  return <>{children(query.data)}</>;
}

/** Why a request failed, in the user's terms. */
export function describeError(error: unknown): string {
  if (isForbidden(error)) return `Not permitted (${error.code}): ${error.message}`;
  if (error instanceof ContractError) {
    return `API contract error on ${error.path}: ${error.message}. The gateway's reply does not match this version of the clearing GUI.`;
  }
  if (error instanceof NetworkError) return "Cannot reach the API gateway. Is pm-api-gwy running?";
  if (error instanceof ApiError) return `${error.code}: ${error.message}`;
  return error instanceof Error ? error.message : "Unknown error";
}

export function ErrorPanel({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const forbidden = isForbidden(error);
  const Icon = forbidden ? Lock : AlertTriangle;
  return (
    <div role="alert" className="flex items-start gap-3 rounded border border-ask/40 bg-ask/10 p-4">
      <Icon size={16} className="mt-0.5 shrink-0 text-ask" aria-hidden="true" />
      <div className="flex flex-col gap-2">
        <p className="text-sm">{describeError(error)}</p>
        {!forbidden && onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="self-start rounded bg-elevated px-3 py-1 text-xs font-semibold hover:brightness-110"
          >
            Retry
          </button>
        )}
      </div>
    </div>
  );
}
