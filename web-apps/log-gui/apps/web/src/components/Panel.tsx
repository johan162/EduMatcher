import { InfoTip } from "./InfoTip.js";

export function Panel({
  title,
  help,
  children,
}: {
  title: string;
  help?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded border border-border bg-bg-subtle p-4">
      <div className="mb-2 flex items-center gap-1 text-xs font-semibold uppercase tracking-wide text-fg-subtle">
        {title}
        {help && <InfoTip label={title}>{help}</InfoTip>}
      </div>
      {children}
    </div>
  );
}
