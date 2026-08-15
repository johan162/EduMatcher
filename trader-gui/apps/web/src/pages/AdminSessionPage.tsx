import { useState } from "react";
import { toast } from "sonner";
import { useTransitionSessionMutation } from "@/queries/index.js";
import { useSessionStore } from "@/store/useSessionStore.js";
import { CancelConfirm } from "@/components/orders/CancelConfirm.js";
import { SESSION_PHASE_META, VALID_TRANSITIONS } from "@/lib/sessionState.js";
import { ApiError } from "@/api/apiFetch.js";
import type { SessionState } from "@/types/index.js";

/**
 * Session Control (§15.4) — buttons for each valid next phase transition from
 * the current session state. Each is confirmed, then `POST
 * /admin/session/transition`; the REST response is authoritative
 * (`202`/APPLIED, `409`/TRANSITION_REJECTED with a reason, `503`/ENGINE_TIMEOUT).
 * The resulting phase still arrives app-wide via the `session.state` broadcast.
 */
export function AdminSessionPage() {
  const phase = useSessionStore((s) => s.phase);
  const transition = useTransitionSessionMutation();
  const [target, setTarget] = useState<SessionState | null>(null);

  const nextStates = VALID_TRANSITIONS[phase];

  const doTransition = (toState: SessionState) => {
    transition.mutate(toState, {
      onSuccess: (res) => toast.success(`Session ${res.status}: → ${res.requested_state}`),
      onError: (err) => {
        if (err instanceof ApiError && err.code === "TRANSITION_REJECTED") {
          toast.error(`Transition rejected: ${err.message}`);
          return;
        }
        if (err instanceof ApiError && (err.status === 503 || err.code === "ENGINE_TIMEOUT")) {
          toast(`Transition submitted — awaiting engine confirmation`);
          return;
        }
        toast.error(err instanceof ApiError ? `${err.code}: ${err.message}` : "Transition failed");
      },
    });
  };

  return (
    <div className="flex flex-col gap-4 p-4 max-w-xl">
      <h1 className="text-lg font-semibold text-[#e8e8f0]">Session Control</h1>

      <div className="flex items-center gap-2">
        <span className="text-[11px] uppercase tracking-wide text-[#707090]">Current phase</span>
        <span
          className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ${SESSION_PHASE_META[phase].bgClass} ${SESSION_PHASE_META[phase].textClass}`}
        >
          {SESSION_PHASE_META[phase].label}
        </span>
      </div>

      <section className="flex flex-col gap-2 rounded border border-[#2a2a45] bg-[#0d0d14] p-3">
        <h2 className="text-xs font-semibold text-[#e8e8f0]">Transition to</h2>
        {nextStates.length === 0 ? (
          <p className="text-[11px] text-[#505070]">No transitions available from {phase}.</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {nextStates.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setTarget(s)}
                disabled={transition.isPending}
                className="rounded bg-[#3a3a60] px-3 py-1.5 text-xs font-semibold text-white hover:brightness-110 disabled:opacity-50"
              >
                {SESSION_PHASE_META[s].label}
              </button>
            ))}
          </div>
        )}
        <p className="text-[10px] text-[#505070]">
          Only transitions valid from the current phase are offered. The engine has final say and may
          reject (e.g. sessions disabled).
        </p>
      </section>

      {target && (
        <CancelConfirm
          title="Transition session?"
          message={`Move the venue from ${SESSION_PHASE_META[phase].label} to ${SESSION_PHASE_META[target].label}? This affects every participant.`}
          confirmLabel={`Transition to ${SESSION_PHASE_META[target].label}`}
          busy={transition.isPending}
          onConfirm={() => {
            doTransition(target);
            setTarget(null);
          }}
          onClose={() => setTarget(null)}
        />
      )}
    </div>
  );
}
