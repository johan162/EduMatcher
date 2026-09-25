import { SHORTCUTS } from "@/lib/shortcuts.js";

/** The keyboard shortcut reference table (§21), shared by the dialog and drawer. */
export function ShortcutsTable() {
  return (
    <table className="w-full border-collapse text-xs">
      <thead className="text-fg-dim">
        <tr>
          <th scope="col" className="px-2 py-1.5 text-left font-medium">Shortcut</th>
          <th scope="col" className="px-2 py-1.5 text-left font-medium">Scope</th>
          <th scope="col" className="px-2 py-1.5 text-left font-medium">Action</th>
        </tr>
      </thead>
      <tbody>
        {SHORTCUTS.map((s) => (
          <tr key={`${s.keys}-${s.action}`} className="border-t border-raised">
            <td className="px-2 py-1 whitespace-nowrap">
              <kbd className="rounded border border-line bg-raised px-1.5 py-0.5 font-mono text-[10px] text-fg">
                {s.keys}
              </kbd>
            </td>
            <td className="px-2 py-1 text-fg-dim">{s.scope}</td>
            <td className="px-2 py-1 text-fg-soft">{s.action}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
