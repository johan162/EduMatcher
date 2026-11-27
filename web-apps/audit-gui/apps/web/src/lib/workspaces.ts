/**
 * The seven workspaces (design §9.1), grouped by the reviewer's workflow
 * rather than by data type. `built` is false for those this release does
 * not ship yet: their page says so rather than showing an empty screen.
 */
import {
  ClipboardList,
  Compass,
  FolderSearch,
  LayoutDashboard,
  LineChart,
  ShieldCheck,
  Users,
  type LucideIcon,
} from "lucide-react";

export interface Workspace {
  path: string;
  name: string;
  /** The question the workspace answers, from the design. */
  question: string;
  built: boolean;
  Icon: LucideIcon;
}

export interface WorkspaceGroup {
  group: "Triage" | "Investigate" | "Trust" | "Conclude";
  items: Workspace[];
}

export const WORKSPACE_GROUPS: WorkspaceGroup[] = [
  {
    group: "Triage",
    items: [
      { path: "/overview", name: "Overview", question: "Where should I look first?", built: true, Icon: LayoutDashboard },
      { path: "/findings", name: "Findings", question: "What is inconsistent or deserves review?", built: false, Icon: ClipboardList },
    ],
  },
  {
    group: "Investigate",
    items: [
      {
        path: "/market",
        name: "Market",
        question: "What formed this symbol's market, and what happened just before and after this moment?",
        built: false,
        Icon: LineChart,
      },
      { path: "/participants", name: "Participants", question: "How did this gateway behave?", built: false, Icon: Users },
      { path: "/explorer", name: "Explorer", question: "Which records match, and what is their story?", built: false, Icon: Compass },
    ],
  },
  {
    group: "Trust",
    items: [
      { path: "/integrity", name: "Integrity & Coverage", question: "What can I trust or reproduce?", built: false, Icon: ShieldCheck },
    ],
  },
  {
    group: "Conclude",
    items: [
      {
        path: "/investigations",
        name: "Investigations",
        question: "How do I resume, share or present this review?",
        built: false,
        Icon: FolderSearch,
      },
    ],
  },
];

export const WORKSPACES: Workspace[] = WORKSPACE_GROUPS.flatMap((g) => g.items);
