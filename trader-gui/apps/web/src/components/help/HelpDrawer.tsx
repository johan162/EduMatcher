import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { useUiStore } from "@/store/useUiStore.js";
import { HELP_TOPICS, SHORTCUTS_TOPIC_ID, type HelpTopic } from "./helpContent.js";
import { ShortcutsTable } from "./ShortcutsTable.js";

function TopicBody({ topic }: { topic: HelpTopic }) {
  if (topic.id === SHORTCUTS_TOPIC_ID) return <ShortcutsTable />;
  return (
    <div className="flex flex-col gap-3">
      {topic.blocks.map((b, i) => (
        <div key={i} className="flex flex-col gap-1">
          {b.heading && <h3 className="text-xs font-semibold text-[#e8e8f0]">{b.heading}</h3>}
          {b.paragraphs?.map((p, j) => (
            <p key={j} className="text-[11px] leading-relaxed text-[#c8c8e0]">
              {p}
            </p>
          ))}
          {b.bullets && (
            <ul className="ml-4 list-disc space-y-0.5">
              {b.bullets.map((li, j) => (
                <li key={j} className="text-[11px] leading-relaxed text-[#c8c8e0]">
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

/**
 * Help drawer (§19.1) — a right-edge sheet with a topic list and a content
 * pane. Toggled by Ctrl+/ or the top-bar "?" button; Escape closes. Content is
 * the static topic tree (§19.1.1); the Keyboard Shortcuts topic renders the
 * shared reference table.
 */
export function HelpDrawer() {
  const close = useUiStore((s) => s.closeHelp);
  const [topicId, setTopicId] = useState<string>(HELP_TOPICS[0]!.id);
  const topic = HELP_TOPICS.find((t) => t.id === topicId) ?? HELP_TOPICS[0]!;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [close]);

  return (
    <aside
      role="dialog"
      aria-label="Help"
      className="fixed right-0 top-10 bottom-0 z-40 flex w-[480px] max-w-[92vw] flex-col border-l border-[#2a2a45] bg-[#0d0d14] shadow-2xl animate-fade-in"
    >
      <div className="flex items-center justify-between border-b border-[#2a2a45] px-4 pt-3 pb-2">
        <h2 className="text-sm font-semibold text-[#e8e8f0]">Help</h2>
        <button
          type="button"
          onClick={close}
          aria-label="Close help"
          className="text-[#9090b0] hover:text-[#e8e8f0]"
        >
          <X size={18} />
        </button>
      </div>

      <div className="flex flex-1 overflow-hidden">
        <nav aria-label="Help topics" className="w-40 flex-shrink-0 overflow-auto border-r border-[#2a2a45] py-2">
          {HELP_TOPICS.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setTopicId(t.id)}
              aria-current={t.id === topicId}
              className={`block w-full px-3 py-1.5 text-left text-[11px] ${
                t.id === topicId
                  ? "bg-[#1a1a28] text-[#e8e8f0]"
                  : "text-[#9090b0] hover:bg-[#1a1a28] hover:text-[#e8e8f0]"
              }`}
            >
              {t.title}
            </button>
          ))}
        </nav>

        <div className="flex-1 overflow-auto p-4">
          <h2 className="mb-2 text-sm font-semibold text-[#e8e8f0]">{topic.title}</h2>
          <TopicBody topic={topic} />
        </div>
      </div>
    </aside>
  );
}
