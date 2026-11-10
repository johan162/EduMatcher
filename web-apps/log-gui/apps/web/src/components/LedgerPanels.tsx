/**
 * Explanation + suggested actions for a WARNING+ row, from the log ledger
 * (docs-design/EduMatcher-Log-Ledger.md §5). Shown in the Explorer drawer
 * below the message; the same text `pm-log-cli explain` prints.
 */

import { useQuery } from "@tanstack/react-query";
import type { LogRow } from "@edumatcher/log-types";
import { LOG_LEVELS } from "@edumatcher/log-types";
import { api } from "../lib/api.js";

/** Plain text with `backtick` spans rendered as code, as the ledger writes commands. */
function LedgerText({ text }: { text: string }) {
  return (
    <>
      {text.split(/`([^`]+)`/).map((part, i) =>
        i % 2 === 1 ? (
          <code key={i} className="rounded bg-bg-inset px-1 font-mono">
            {part}
          </code>
        ) : (
          part
        ),
      )}
    </>
  );
}

function Heading({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-fg-subtle">
      {children}
    </h3>
  );
}

export function LedgerPanels({ row }: { row: LogRow }) {
  const covered =
    LOG_LEVELS.indexOf(row.level) >= LOG_LEVELS.indexOf("WARNING");
  const { data } = useQuery({
    queryKey: ["ledger"],
    queryFn: api.ledger,
    staleTime: Infinity,
    enabled: covered,
  });
  if (!covered || !data) return null;

  if (!data.available) {
    return (
      <p className="mt-3 text-xs text-fg-subtle">
        No explanations available: {data.reason}
      </p>
    );
  }
  const entry = row.tpl ? data.entries[row.tpl] : undefined;
  if (!entry) {
    return (
      <p className="mt-3 text-xs text-fg-subtle">
        No ledger entry for this message{row.tpl ? ` (tpl=${row.tpl})` : ""}.
      </p>
    );
  }
  return (
    <>
      <section aria-label="Explanation" className="mt-3">
        <Heading>Explanation</Heading>
        <p className="text-xs leading-relaxed">
          <LedgerText text={entry.explanation} />
        </p>
      </section>
      <section aria-label="Suggested actions" className="mt-3">
        <Heading>Suggested actions</Heading>
        <ol className="list-decimal space-y-1 pl-5 text-xs leading-relaxed">
          {entry.actions.map((action, i) => (
            <li key={i}>
              <LedgerText text={action} />
            </li>
          ))}
        </ol>
      </section>
    </>
  );
}
