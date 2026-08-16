import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";

interface ErrorBoundaryProps {
  children: ReactNode;
  /** Optional label for the region that failed, shown in the fallback. */
  label?: string;
}

interface ErrorBoundaryState {
  error: Error | null;
}

/**
 * Catches render/lifecycle errors in its subtree so one broken screen degrades
 * to an inline message instead of a blank app (§23 phase 16 — "no uncaught
 * errors"). The persistent chrome (top bar, sidebar) stays mounted around it,
 * so the user can navigate away; wrapping this boundary with a `key` that
 * changes on navigation also clears the error automatically. A "Try again"
 * button resets it in place.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  override state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    // Surfaced to the console for classroom debugging; the app stays usable.
    console.error("[error-boundary]", this.props.label ?? "", error, info.componentStack);
  }

  private reset = () => this.setState({ error: null });

  override render(): ReactNode {
    if (this.state.error) {
      return (
        <div
          role="alert"
          className="m-4 flex flex-col items-start gap-3 rounded border border-ask/40 bg-ask/10 p-6"
        >
          <div className="flex items-center gap-2 text-ask">
            <AlertTriangle size={18} />
            <h2 className="text-sm font-semibold">
              {this.props.label ? `${this.props.label} hit an error` : "Something went wrong"}
            </h2>
          </div>
          <p className="text-xs text-[#9090b0]">
            This screen crashed but the rest of the app is still running — switch screens, or try
            again.
          </p>
          <p className="max-w-full overflow-auto rounded bg-[#12121a] px-2 py-1 font-mono text-[10px] text-[#707090]">
            {this.state.error.message || String(this.state.error)}
          </p>
          <button
            type="button"
            onClick={this.reset}
            className="rounded bg-[#3a3a60] px-3 py-1.5 text-xs font-semibold text-white hover:brightness-110"
          >
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
