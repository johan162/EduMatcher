import { NewsPanel } from "@/components/news/NewsPanel.js";

/** News screen (WP-E5) — available to all roles. */
export function NewsPage() {
  return (
    <div className="flex flex-col gap-3 p-4">
      <h1 className="text-lg font-semibold text-fg">News</h1>
      <NewsPanel />
    </div>
  );
}
