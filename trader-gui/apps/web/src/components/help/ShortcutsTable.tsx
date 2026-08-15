import { SHORTCUTS } from "@/lib/shortcuts.js";

/** The keyboard shortcut reference table (§21), shared by the dialog and drawer. */
export function ShortcutsTable() {
  return (
    <table className="w-full border-collapse text-xs">
      <thead className="text-[#9090b0]">
        <tr>
          <th scope="col" className="px-2 py-1.5 text-left font-medium">Shortcut</th>
          <th scope="col" className="px-2 py-1.5 text-left font-medium">Scope</th>
          <th scope="col" className="px-2 py-1.5 text-left font-medium">Action</th>
        </tr>
      </thead>
      <tbody>
        {SHORTCUTS.map((s) => (
          <tr key={`${s.keys}-${s.action}`} className="border-t border-[#1a1a28]">
            <td className="px-2 py-1 whitespace-nowrap">
              <kbd className="rounded border border-[#2a2a45] bg-[#1a1a28] px-1.5 py-0.5 font-mono text-[10px] text-[#e8e8f0]">
                {s.keys}
              </kbd>
            </td>
            <td className="px-2 py-1 text-[#9090b0]">{s.scope}</td>
            <td className="px-2 py-1 text-[#c8c8e0]">{s.action}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
