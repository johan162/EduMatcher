export function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded border border-border bg-bg-subtle p-4">
      <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-fg-subtle">{title}</div>
      {children}
    </div>
  );
}
