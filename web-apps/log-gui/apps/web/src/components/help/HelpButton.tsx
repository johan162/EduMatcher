/**
 * The "?" button of the top bar and the help panel it opens (WP-UI08): a list
 * of topics on the left, the chosen topic on the right. Content is data
 * (`HelpTopic[]`, authored in each app's `helpContent.ts`), so adding a topic
 * needs no markup. The file is copied unchanged into pm-log, pm-terminal,
 * pm-dash and pm-book; pm-trader and pm-config have their own token names.
 */

import { useEffect, useState } from "react";
import { HelpCircle, X } from "lucide-react";

export interface HelpBlock {
  heading?: string;
  paragraphs?: string[];
  bullets?: string[];
  /** A glossary: each term in bold, then what it means. */
  terms?: { term: string; text: string }[];
  /** A literal example, in monospace. */
  example?: string;
  /** A callout: the thing to remember, or the usual mistake. */
  note?: string;
}

export interface HelpTopic {
  id: string;
  title: string;
  blocks: HelpBlock[];
}

function TopicBody({ topic }: { topic: HelpTopic }) {
  return (
    <div className="flex flex-col gap-3">
      {topic.blocks.map((b, i) => (
        <div key={i} className="flex flex-col gap-1.5">
          {b.heading && <h4 className="text-sm font-semibold text-fg">{b.heading}</h4>}
          {b.paragraphs?.map((p, j) => (
            <p key={j} className="text-xs leading-relaxed text-fg-subtle">
              {p}
            </p>
          ))}
          {b.terms && (
            <dl className="flex flex-col gap-1.5">
              {b.terms.map((t, j) => (
                <div key={j}>
                  <dt className="text-xs font-semibold text-fg">{t.term}</dt>
                  <dd className="ml-3 text-xs leading-relaxed text-fg-subtle">{t.text}</dd>
                </div>
              ))}
            </dl>
          )}
          {b.bullets && (
            <ul className="ml-4 list-disc space-y-0.5">
              {b.bullets.map((li, j) => (
                <li key={j} className="text-xs leading-relaxed text-fg-subtle">
                  {li}
                </li>
              ))}
            </ul>
          )}
          {b.example && (
            <pre className="overflow-x-auto whitespace-pre-wrap rounded border border-border bg-bg-inset p-2 font-mono text-[11px] leading-relaxed text-fg">
              {b.example}
            </pre>
          )}
          {b.note && (
            <p className="rounded border-l-2 border-accent bg-bg-inset px-2 py-1.5 text-xs leading-relaxed text-fg">
              {b.note}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}

export function HelpButton({ topics }: { topics: HelpTopic[] }) {
  const [open, setOpen] = useState(false);
  const [topicId, setTopicId] = useState(topics[0]!.id);
  const topic = topics.find((t) => t.id === topicId) ?? topics[0]!;

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label="Help"
        aria-expanded={open}
        title="Help"
        className="rounded p-1.5 text-fg-subtle hover:bg-bg-inset hover:text-fg"
      >
        <HelpCircle size={16} />
      </button>

      {open && (
        <aside
          role="dialog"
          aria-label="Help"
          className="fixed bottom-0 right-0 top-12 z-40 flex w-[680px] max-w-[92vw] flex-col border-l border-border bg-bg shadow-2xl"
        >
          <div className="flex items-center justify-between border-b border-border px-4 pb-2 pt-3">
            <h2 className="text-sm font-semibold text-fg">Help</h2>
            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-label="Close help"
              className="text-fg-subtle hover:text-fg"
            >
              <X size={18} />
            </button>
          </div>
          <div className="flex flex-1 overflow-hidden">
            <nav aria-label="Help topics" className="w-44 flex-shrink-0 overflow-auto border-r border-border py-2">
              {topics.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => setTopicId(t.id)}
                  aria-current={t.id === topic.id}
                  className={`block w-full px-3 py-1.5 text-left text-xs ${
                    t.id === topic.id ? "bg-bg-inset text-fg" : "text-fg-subtle hover:bg-bg-inset hover:text-fg"
                  }`}
                >
                  {t.title}
                </button>
              ))}
            </nav>
            <div className="flex-1 overflow-auto p-4">
              <h3 className="mb-2 text-sm font-semibold text-fg">{topic.title}</h3>
              <TopicBody topic={topic} />
            </div>
          </div>
        </aside>
      )}
    </>
  );
}
