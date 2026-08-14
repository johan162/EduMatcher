import { useState } from "react";
import { Modal } from "@/components/shared/Modal.js";

interface ConfirmTypedDialogProps {
  title: string;
  message: string;
  /** The word the operator must type (case-sensitive) to enable Execute. */
  confirmWord?: string;
  confirmLabel?: string;
  busy?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}

/**
 * A high-friction confirmation for truly destructive, market-wide actions
 * (§15.8, §20.3): the operator must type a word (default "CONFIRM") before the
 * Execute button enables. Used for the Global Kill Switch; always shown
 * regardless of power-user mode.
 */
export function ConfirmTypedDialog({
  title,
  message,
  confirmWord = "CONFIRM",
  confirmLabel = "Execute",
  busy = false,
  onConfirm,
  onClose,
}: ConfirmTypedDialogProps) {
  const [typed, setTyped] = useState("");
  const armed = typed === confirmWord;

  return (
    <Modal title={title} onClose={onClose}>
      <p className="text-xs text-[#c8c8e0]">{message}</p>
      <label className="mt-3 flex flex-col gap-1">
        <span className="text-[11px] text-[#9090b0]">
          Type <span className="font-mono font-semibold text-[#e8e8f0]">{confirmWord}</span> to confirm
        </span>
        <input
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          aria-label={`Type ${confirmWord} to confirm`}
          autoFocus
          className="bg-[#1a1a28] border border-[#2a2a45] rounded px-2 py-1 text-xs font-mono focus:outline-none focus:border-[#3a3a60]"
        />
      </label>
      <div className="mt-4 flex justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          className="rounded border border-[#2a2a45] px-3 py-1.5 text-xs text-[#9090b0] hover:text-[#e8e8f0]"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={!armed || busy}
          className="rounded bg-ask px-3 py-1.5 text-xs font-semibold text-white hover:brightness-110 disabled:opacity-40"
        >
          {confirmLabel}
        </button>
      </div>
    </Modal>
  );
}
