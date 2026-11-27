import { NavLink } from "react-router-dom";
import { WORKSPACE_GROUPS } from "@/lib/workspaces";

/** The workspaces, in their workflow groups (design §9.1). */
export function Sidebar() {
  return (
    <nav aria-label="Workspaces" className="w-56 shrink-0 overflow-y-auto border-r border-line bg-panel py-3">
      {WORKSPACE_GROUPS.map(({ group, items }) => (
        <ul key={group} role="group" aria-label={group} className="mb-3 space-y-0.5 px-2">
          <li aria-hidden="true" className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-wide text-fg-mute">
            {group}
          </li>
          {items.map(({ path, name, Icon, built }) => (
            <li key={path}>
              <NavLink
                to={path}
                className={({ isActive }) =>
                  `flex items-center gap-2 rounded px-3 py-1.5 text-sm ${
                    isActive ? "bg-accent text-accent-fg" : built ? "text-fg-dim hover:bg-raised hover:text-fg" : "text-fg-faint hover:bg-raised"
                  }`
                }
              >
                <Icon size={14} aria-hidden="true" />
                {name}
              </NavLink>
            </li>
          ))}
        </ul>
      ))}
    </nav>
  );
}
