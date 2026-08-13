import { Modal } from "@/components/shared/Modal.js";

interface CancelConfirmProps {
  title: string;
  message: string;
  confirmLabel?: string;
  busy?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}

/** A small destructive-action confirmation (§13.1.3 cancel, §13.1.4 bulk cancel). */
export function CancelConfirm({
  title,
  message,
  confirmLabel = "Confirm",
  busy = false,
  onConfirm,
  onClose,
}: CancelConfirmProps) {
  return (
    <Modal title={title} onClose={onClose}>
      <p className="text-xs text-[#c8c8e0]">{message}</p>
      <div className="mt-4 flex justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          className="rounded border border-[#2a2a45] px-3 py-1.5 text-xs text-[#9090b0] hover:text-[#e8e8f0]"
        >
          Keep order
        </button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={busy}
          className="rounded bg-ask px-3 py-1.5 text-xs font-semibold text-white hover:brightness-110 disabled:opacity-50"
        >
          {confirmLabel}
        </button>
      </div>
    </Modal>
  );
}
