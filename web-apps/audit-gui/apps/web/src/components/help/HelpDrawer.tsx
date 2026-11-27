import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { HELP_TOPICS, type HelpTopic } from "./helpContent";

function TopicBody({ topic }: { topic: HelpTopic }) {
  return (
    <div className="flex flex-col gap-3">
      {topic.blocks.map((b, i) => (
        <div key={i} className="flex flex-col gap-1">
          {b.heading && <h3 className="text-xs font-semibold text-fg">{b.heading}</h3>}
          {b.paragraphs?.map((p, j) => (
            <p key={j} className="text-xs leading-relaxed text-fg-soft">
              {p}
            </p>
          ))}
          {b.bullets && (
            <ul className="ml-4 list-disc space-y-0.5">
              {b.bullets.map((li, j) => (
                <li key={j} className="text-xs leading-relaxed text-fg-soft">
                  {li}
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </div>
  );
}

/** Help drawer, as in trader-gui: a right-edge sheet with topics and content. Escape closes. */
export function HelpDrawer({ onClose }: { onClose: () => void }) {
  const [topicId, setTopicId] = useState<string>(HELP_TOPICS[0]!.id);
  const topic = HELP_TOPICS.find((t) => t.id === topicId) ?? HELP_TOPICS[0]!;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <aside
      role="dialog"
      aria-label="Help"
      className="fixed right-0 top-10 bottom-0 z-40 flex w-[680px] max-w-[92vw] flex-col border-l border-line bg-deep shadow-2xl"
    >
      <div className="flex items-center justify-between border-b border-line px-4 pt-3 pb-2">
        <h2 className="text-sm font-semibold text-fg">Help</h2>
        <button type="button" onClick={onClose} aria-label="Close help" className="text-fg-dim hover:text-fg">
          <X size={18} />
        </button>
      </div>

      <div className="flex flex-1 overflow-hidden">
        <nav aria-label="Help topics" className="w-40 flex-shrink-0 overflow-auto border-r border-line py-2">
          {HELP_TOPICS.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setTopicId(t.id)}
              aria-current={t.id === topicId}
              className={`block w-full px-3 py-1.5 text-left text-[11px] ${
                t.id === topicId ? "bg-raised text-fg" : "text-fg-dim hover:bg-raised hover:text-fg"
              }`}
            >
              {t.title}
            </button>
          ))}
        </nav>

        <div className="flex-1 overflow-auto p-4">
          <h2 className="mb-2 text-sm font-semibold text-fg">{topic.title}</h2>
          <TopicBody topic={topic} />
        </div>
      </div>
    </aside>
  );
}
