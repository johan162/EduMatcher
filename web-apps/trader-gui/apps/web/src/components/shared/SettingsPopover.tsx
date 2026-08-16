import { useState } from "react";
import { Settings } from "lucide-react";
import { useSettingsStore } from "@/store/useSettingsStore.js";

/**
 * Settings popover in the top bar (§20.3). Currently surfaces the single
 * power-user toggle — "Confirm order/quote cancellations" (default on). When
 * off, reversible cancels skip the dialog and use an undo-toast instead;
 * always-confirm exceptions (Flatten All, kill switch, gateway kick) are
 * unaffected.
 */
export function SettingsPopover() {
  const [open, setOpen] = useState(false);
  const confirmCancellations = useSettingsStore((s) => s.confirmCancellations);
  const toggle = useSettingsStore((s) => s.toggleConfirmCancellations);

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label="Settings"
        aria-expanded={open}
        className="text-[#9090b0] hover:text-[#e8e8f0]"
      >
        <Settings size={16} />
      </button>

      {open && (
        <>
          {/* Click-away backdrop */}
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} aria-hidden="true" />
          <div
            role="menu"
            aria-label="Settings"
            className="absolute right-0 top-7 z-50 w-72 rounded border border-[#2a2a45] bg-[#12121a] p-3 shadow-2xl"
          >
            <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-[#707090]">
              Settings
            </h3>
            <label className="flex cursor-pointer items-start gap-2">
              <input
                type="checkbox"
                checked={confirmCancellations}
                onChange={toggle}
                aria-label="Confirm order and quote cancellations"
                className="mt-0.5"
              />
              <span className="flex flex-col">
                <span className="text-xs text-[#e8e8f0]">Confirm cancellations</span>
                <span className="text-[10px] text-[#9090b0]">
                  When off (power-user), single-order cancels fire immediately with an undo-toast.
                  Flatten All and kill switches always confirm.
                </span>
              </span>
            </label>
          </div>
        </>
      )}
    </div>
  );
}
