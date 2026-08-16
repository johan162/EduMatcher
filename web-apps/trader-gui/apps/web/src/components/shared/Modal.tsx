import { useEffect, type ReactNode } from "react";
import { X } from "lucide-react";

interface ModalProps {
  title: string;
  onClose: () => void;
  children: ReactNode;
  /** Width class override; defaults to a compact dialog. */
  widthClass?: string;
}

/**
 * Minimal centered modal dialog with a dimmed backdrop, an accessible label,
 * a close button, and Escape-to-close. Matches the hand-rolled overlay style
 * used elsewhere (e.g. SymbolDetailPanel) rather than pulling in a component kit.
 */
export function Modal({ title, onClose, children, widthClass = "w-[420px]" }: ModalProps) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-label={title}
        className={`${widthClass} max-w-[92vw] rounded border border-[#2a2a45] bg-[#0d0d14] p-4 shadow-2xl`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-[#e8e8f0]">{title}</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="text-[#9090b0] hover:text-[#e8e8f0]">
            <X size={16} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
