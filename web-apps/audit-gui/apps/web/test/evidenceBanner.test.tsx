// @vitest-environment jsdom
/**
 * The evidence banner (design §9.2 item 1): what the snapshot covers, how
 * far its integrity is known, and what it cannot support -- above every
 * workspace, and impossible to fold away while a check has failed.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { useAuthStore } from "@/store/useAuthStore";
import { useExplainStore } from "@/store/useExplainStore";
import { useSnapshotStore } from "@/store/useSnapshotStore";
import { apiError, example, renderApp, signIn, snapshotExample, stubApi, type SnapshotFixture } from "./helpers";

type Finding = Record<string, unknown>;

function gaps(n: number): Finding[] {
  const row = (example("/api/v1/audit/findings") as { findings: Finding[] }).findings[0]!;
  return Array.from({ length: n }, (_, i) => ({ ...row, code: "ESEQ_GAP", episode: i }));
}

function findingsPage(rows: Finding[], hasMore = false) {
  return { ...example("/api/v1/audit/findings"), findings: rows, count: rows.length, has_more: hasMore };
}

/** Render the app with a pinned snapshot whose descriptor is *snapshot*. */
async function show(snapshot: SnapshotFixture, findings: unknown = findingsPage(gaps(2))) {
  const api = stubApi({
    "/api/v1/audit/collections": example("/api/v1/audit/collections"),
    [`/api/v1/audit/snapshots/${snapshot.snapshot_id}`]: snapshot,
    "/api/v1/audit/findings": findings,
  });
  useSnapshotStore.getState().select("world", snapshot.snapshot_id);
  renderApp("/overview");
  const banner = await screen.findByRole("region", { name: "Evidence" });
  return { api, banner };
}

function withManifest(state: "absent" | "verified" | "failed"): SnapshotFixture {
  const s = snapshotExample();
  s.forensics = null;
  s.manifest =
    state === "absent"
      ? {
          state,
          entries: 0,
          head_sha256: null,
          anchored: false,
          problems: [],
          chain_ok: null,
          content_ok: null,
          anchor: null,
          checked_at: s.manifest.checked_at,
        }
      : state === "verified"
        ? { ...s.manifest, state }
        : {
            ...s.manifest,
            state,
            content_ok: false,
            problems: [{ day: "2026-06-15", message: "archive content differs from the manifest entry", kind: "content" }],
          };
  return s;
}

beforeEach(() => {
  useAuthStore.getState().logout();
  useSnapshotStore.getState().clear();
  useExplainStore.setState({ explain: false });
  signIn();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("evidence banner", () => {
  it("shows the extent on the receipt clock, the records and the runs", async () => {
    const { banner } = await show(withManifest("verified"));
    expect(banner.textContent).toContain("2026-06-15 07:00:00.001 UTC – 2026-06-15 15:30:12.874 UTC");
    expect(banner.textContent).toContain("receipt clock");
    expect(banner.textContent).toContain("184,213 records");
    expect(banner.textContent).toContain("1 engine run");
  });

  it("counts recorder gaps with the replay's own ESEQ_GAP findings", async () => {
    const { api, banner } = await show(withManifest("verified"));
    expect(await within(banner).findByText("2 recorder gaps")).toBeTruthy();
    const asked = new URL(api.calls("/api/v1/audit/findings")[0]!.url, "http://gui.test");
    expect(asked.searchParams.get("code")).toBe("ESEQ_GAP");
    expect(asked.searchParams.get("snapshot_id")).toBe("s-3f1c9a07be52d4e6a810");
  });

  it("a count past one page is a lower bound, and zero is a measured zero", async () => {
    const { banner } = await show(withManifest("verified"), findingsPage(gaps(3), true));
    expect(await within(banner).findByText("at least 3 recorder gaps")).toBeTruthy();
    cleanup();
    const again = await show(withManifest("verified"), findingsPage([]));
    expect(await within(again.banner).findByText("no recorder gap")).toBeTruthy();
  });

  it.each([
    ["verified", "checked, unanchored"],
    ["failed", "failed"],
    ["absent", "no manifest"],
  ] as const)("manifest %s reads '%s'", async (state, text) => {
    const { banner } = await show(withManifest(state));
    expect(within(banner).getByTestId("manifest-state").textContent).toBe(text);
  });

  it("a failed manifest names its problems", async () => {
    const { banner } = await show(withManifest("failed"));
    expect(banner.textContent).toContain("2026-06-15: archive content differs from the manifest entry");
  });

  it("can be folded to one line when every check passed", async () => {
    const { banner } = await show(withManifest("verified"));
    fireEvent.click(within(banner).getByRole("button", { name: "Hide details" }));
    expect(within(banner).queryByTestId("manifest-state")).toBeNull();
    fireEvent.click(within(banner).getByRole("button", { name: "Show details" }));
    expect(within(banner).getByTestId("manifest-state")).toBeTruthy();
  });

  it("cannot be folded while the manifest check failed", async () => {
    const { banner } = await show(withManifest("failed"));
    expect(within(banner).queryByRole("button", { name: "Hide details" })).toBeNull();
    expect(banner.textContent).toContain("A check failed");
  });

  it("cannot be folded while an attached forensics check failed", async () => {
    const s = withManifest("verified");
    s.forensics = { ...snapshotExample().forensics!, statuses: { PASS: 3, FAIL: 1 } };
    const { banner } = await show(s);
    expect(banner.textContent).toContain("1 FAIL");
    expect(within(banner).queryByRole("button", { name: "Hide details" })).toBeNull();
  });

  it("lists what the evidence cannot support, with each reason", async () => {
    const s = withManifest("verified");
    s.capabilities["rerun"] = { available: false, reason: "NO_RECORDED_CONFIG", detail: "no config for run 7" };
    const { banner } = await show(s);
    const limits = within(banner).getByTestId("restrictions");
    expect(limits.textContent).toContain("rerun: NO_RECORDED_CONFIG");
    expect(limits.textContent).toContain("sim_context: NOT_ATTACHED");
    expect(limits.textContent).not.toContain("stories");
  });

  it("reports a torn active file", async () => {
    const { banner } = await show(withManifest("verified"));
    expect(banner.textContent).toContain("partial last line (136 bytes) left out");
  });

  it("a 503 counting gaps is an error state, not zero gaps", async () => {
    const { banner } = await show(
      withManifest("verified"),
      apiError(503, "AUDIT_SOURCE_UNAVAILABLE", "audit.log changed after the snapshot", { reason: "SOURCE_CHANGED" }),
    );
    const alert = await within(banner).findByRole("alert");
    expect(alert.textContent).toContain("SOURCE_CHANGED");
    expect(banner.textContent).not.toMatch(/no recorder gap|\b0 recorder gaps/);
  });

  it("Explain says what 'checked, unanchored' proves", async () => {
    useExplainStore.setState({ explain: true });
    const { banner } = await show(withManifest("verified"));
    expect(banner.textContent).toContain("a rewritten chain would not show");
  });
});
