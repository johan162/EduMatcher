// @vitest-environment jsdom
/**
 * The Market workspace (AG6, design §9.4, §9.3 drawer, §9.9): the canvas,
 * its table equivalents, the URL-addressable interval and drawer.
 *
 * jsdom cannot paint a canvas, so the ECharts wrapper is replaced by a stub
 * that keeps its props: a test "clicks" a mark or "brushes" an interval by
 * calling the handlers the page gave it, exactly as ECharts would.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import type { HeatmapT, LifelinesT, StoryT } from "@/api/schemas";
import type { EChartProps } from "@/components/market/EChart";
import { END_MARKS } from "@/lib/marks";
import { msToNs, nsToMs } from "@/lib/ns";
import { useAuthStore } from "@/store/useAuthStore";
import { useSnapshotStore } from "@/store/useSnapshotStore";
import { apiError, currentPath, example, history, renderApp, signIn, snapshotExample, stubApi, type ApiStub } from "./helpers";

const chart: { props: EChartProps | null } = { props: null };

vi.mock("@/components/market/EChart", () => ({
  EChart: (props: EChartProps) => {
    chart.props = props;
    return <div data-testid="chart" aria-label={props.ariaLabel} />;
  },
}));

const SID = "s-3f1c9a07be52d4e6a810";
const HEATMAP = "/api/v1/audit/market/{symbol}/heatmap";
const LIFELINES = "/api/v1/audit/market/{symbol}/lifelines";
const STORY = "/api/v1/audit/stories/{entity_kind}/{entity_id}";

/** The contract's lifeline, and two more ending differently. */
function lifelines(): LifelinesT {
  const body = example<LifelinesT>(LIFELINES);
  const first = body.lifelines[0]!;
  body.lifelines = [
    first,
    { ...first, order_id: "b".repeat(32), end: "filled", end_reason: null, filled_qty: 100 },
    { ...first, order_id: "c".repeat(32), gateway: "MM01", end: "cancel.system", end_reason: "QUOTE_REPLACED" },
  ];
  return body;
}

function api(overrides: Record<string, unknown> = {}): ApiStub {
  const story = example<StoryT>(STORY);
  return stubApi({
    "/api/v1/audit/collections": example("/api/v1/audit/collections"),
    [`/api/v1/audit/snapshots/${SID}`]: snapshotExample(),
    "/api/v1/audit/findings": example("/api/v1/audit/findings"),
    "/api/v1/audit/market/AAA/heatmap": example<HeatmapT>(HEATMAP),
    "/api/v1/audit/market/AAA/lifelines": lifelines(),
    "/api/v1/audit/events": example("/api/v1/audit/events"),
    ...Object.fromEntries(lifelines().lifelines.map((l) => [`/api/v1/audit/stories/order/${l.order_id}`, story])),
    ...overrides,
  });
}

/** Click the canvas on lifeline `index`'s first segment (data units, as EChart reports). */
function clickLifeline(index: number) {
  const seg = lifelines().lifelines[index]!.segments[0]!;
  const mid = (nsToMs(seg.start_ns) + nsToMs(seg.end_ns)) / 2;
  chart.props!.onPlotClick(mid, seg.price_ticks!, 1, 0.5);
}

async function open(path = "/market"): Promise<HTMLElement> {
  renderApp(path);
  return screen.findByRole("listbox", { name: "Order lifelines" });
}

function param(name: string): string | null {
  return new URL(currentPath(), "http://gui.test").searchParams.get(name);
}

beforeEach(() => {
  useAuthStore.getState().logout();
  signIn();
  useSnapshotStore.getState().select("world", SID);
  chart.props = null;
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("market canvas", () => {
  it("opens on the snapshot's first symbol and draws the canvas from both read models", async () => {
    const stub = api();
    await open();
    expect(param("symbol")).toBe("AAA");
    expect(screen.getByTestId("chart")).toBeTruthy();
    expect(stub.calls("/api/v1/audit/market/AAA/heatmap")).toHaveLength(1);
    expect(stub.calls("/api/v1/audit/market/AAA/lifelines")).toHaveLength(1);
    const trades = new URL(stub.calls("/api/v1/audit/events")[0]!.url, "http://gui.test");
    expect(trades.searchParams.get("topic")).toBe("trade.executed");
    expect(trades.searchParams.get("symbol")).toBe("AAA");
  });

  it("every end-reason marker has a text equivalent, in the list and the legend", async () => {
    api();
    const list = await open();
    const rows = within(list).getAllByRole("option").map((o) => o.textContent ?? "");
    expect(rows[0]).toContain("× owner cancel");
    expect(rows[1]).toContain("● filled");
    expect(rows[2]).toContain("⊗ system cancel: QUOTE_REPLACED");
    const legend = screen.getByRole("list", { name: "Legend" }).textContent ?? "";
    for (const mark of Object.values(END_MARKS)) expect(legend).toContain(`${mark.glyph} ${mark.text}`);
  });

  it("clicking a lifeline on the canvas opens its story, then its raw lines", async () => {
    const stub = api();
    await open();
    const id = lifelines().lifelines[0]!.order_id;
    clickLifeline(0);
    await waitFor(() => expect(param("order")).toBe(id));
    expect(param("tab")).toBe("story");
    const drawer = await screen.findByRole("dialog", { name: /Order 2aeb1046/ });
    expect(await within(drawer).findByText(/submits a sell stop for 30 AAPL/)).toBeTruthy();
    const asked = new URL(stub.calls(`/api/v1/audit/stories/order/${id}`)[0]!.url, "http://gui.test");
    expect(asked.searchParams.get("run_id")).toBe("0");
    expect(asked.searchParams.get("snapshot_id")).toBe(SID);

    fireEvent.click(within(drawer).getByRole("tab", { name: "Raw evidence" }));
    expect(param("tab")).toBe("raw");
    const raw = await within(drawer).findByRole("table", { name: "Raw evidence" });
    expect(raw.textContent).toContain("trade.executed");
    expect(raw.textContent).toContain("audit.log:413");
    const byOrder = stub.calls("/api/v1/audit/events").map((r) => new URL(r.url, "http://gui.test").searchParams);
    expect(byOrder.some((q) => q.get("order_id") === id)).toBe(true);
  });

  it("the Checks tab says when the order's episodes carry no finding", async () => {
    api();
    await open();
    clickLifeline(0);
    const drawer = await screen.findByRole("dialog");
    fireEvent.click(within(drawer).getByRole("tab", { name: "Checks" }));
    expect(await within(drawer).findByText("No finding on this order's episodes.")).toBeTruthy();
  });

  it("brushing sets the interval in the URL, and asks each read model once", async () => {
    const stub = api();
    await open();
    const heatmap = example<HeatmapT>(HEATMAP);
    const a = nsToMs(heatmap.from_ns) + 100;
    const b = nsToMs(heatmap.to_ns) - 100;
    chart.props!.onBrush(a, b);
    await waitFor(() => expect(param("from")).toBe(msToNs(a)));
    expect(param("to")).toBe(msToNs(b));
    await waitFor(() => expect(stub.calls("/api/v1/audit/market/AAA/heatmap")).toHaveLength(2));
    const second = new URL(stub.calls("/api/v1/audit/market/AAA/heatmap")[1]!.url, "http://gui.test");
    expect(second.searchParams.get("from")).toBe(msToNs(a));
    expect(stub.calls("/api/v1/audit/market/AAA/lifelines")).toHaveLength(2);
    // Settled: no further request for the same interval.
    await new Promise((r) => setTimeout(r, 300));
    expect(stub.calls("/api/v1/audit/market/AAA/heatmap")).toHaveLength(2);
  });

  it("the keyboard moves between marks, and Enter opens one", async () => {
    api();
    const list = await open();
    const options = within(list).getAllByRole("option");
    options[0]!.focus();
    fireEvent.keyDown(list, { key: "ArrowDown" });
    expect(document.activeElement).toBe(options[1]);
    fireEvent.keyDown(list, { key: "End" });
    expect(document.activeElement).toBe(options[2]);
    fireEvent.keyDown(list, { key: "Home" });
    expect(document.activeElement).toBe(options[0]);
    fireEvent.keyDown(list, { key: "ArrowUp" });
    expect(document.activeElement).toBe(options[0]);
    fireEvent.keyDown(list, { key: "End" });
    fireEvent.keyDown(list, { key: "Enter" });
    await waitFor(() => expect(param("order")).toBe("c".repeat(32)));
  });

  it("Back and Forward restore the drawer and the interval", async () => {
    api();
    await open();
    clickLifeline(0);
    await screen.findByRole("dialog");
    const heatmap = example<HeatmapT>(HEATMAP);
    chart.props!.onBrush(nsToMs(heatmap.from_ns) + 1, nsToMs(heatmap.to_ns) - 1);
    await waitFor(() => expect(param("from")).not.toBeNull());

    history(-1);
    expect(param("from")).toBeNull();
    expect(screen.getByRole("dialog")).toBeTruthy();
    history(-1);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    history(1);
    expect(await screen.findByRole("dialog")).toBeTruthy();
    history(1);
    expect(param("from")).not.toBeNull();
  });

  it("closing the drawer is a step Back can undo", async () => {
    api();
    await open();
    clickLifeline(0);
    const drawer = await screen.findByRole("dialog");
    fireEvent.click(within(drawer).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    history(-1);
    expect(await screen.findByRole("dialog")).toBeTruthy();
  });

  it("lists each mask with its reason (the table equivalent of the hatching)", async () => {
    api();
    await open();
    const masks = await screen.findByRole("list", { name: "Evidence masks" });
    expect(masks.textContent).toContain("Halt (ADMIN_SYMBOL)");
    expect(masks.textContent).toContain("the book observed while halted is kept");
  });

  it("states the observation cadence the bins follow", async () => {
    api();
    await open();
    expect(await screen.findByText(/34 book observations, median every 1\.000 s/)).toBeTruthy();
  });

  it("a heatmap the evidence cannot support is an error with its reason; lifelines still show", async () => {
    api({
      "/api/v1/audit/market/AAA/heatmap": apiError(409, "CAPABILITY_UNAVAILABLE", "no book.AAA observation was recorded", {
        reason: "NO_BOOK_OBSERVATIONS",
      }),
    });
    const list = await open();
    expect((await screen.findByRole("alert")).textContent).toContain("NO_BOOK_OBSERVATIONS");
    expect(within(list).getAllByRole("option")).toHaveLength(3);
  });

  it("aggregated lifelines say so, and point at zooming in", async () => {
    const body = lifelines();
    body.aggregated = true;
    body.segments = 6000;
    body.lifelines = [];
    body.levels = [
      { side: "BUY", state: "book", price_ticks: 24500, orders: 12, segments: 40, max_displayed_qty: 100, from_ns: body.from_ns, to_ns: body.to_ns, ends: { "cancel.owner": 12 } },
    ];
    api({ "/api/v1/audit/market/AAA/lifelines": body });
    renderApp("/market");
    expect(await screen.findByText(/6,000 segments exceed the 5,000 shown/)).toBeTruthy();
    expect(screen.getByRole("table", { name: "Lifelines per level" }).textContent).toContain("2.4500");
  });

  it("the symbol picker switches symbol and keeps the URL the source of truth", async () => {
    api({
      "/api/v1/audit/market/BBB/heatmap": { ...example<HeatmapT>(HEATMAP), symbol: "BBB", tick_decimals: 4 },
      "/api/v1/audit/market/BBB/lifelines": lifelines(),
    });
    await open();
    fireEvent.change(screen.getByLabelText("Symbol"), { target: { value: "BBB" } });
    await waitFor(() => expect(param("symbol")).toBe("BBB"));
    history(-1);
    expect(param("symbol")).toBe("AAA");
  });

  it("after the list shrinks, the keyboard can still enter it", async () => {
    const one = { ...lifelines(), lifelines: lifelines().lifelines.slice(0, 1) };
    api({
      "/api/v1/audit/market/AAA/lifelines": (url: URL) => (url.searchParams.get("from") ? one : lifelines()),
    });
    const list = await open();
    within(list).getAllByRole("option")[0]!.focus();
    fireEvent.keyDown(list, { key: "End" });
    const heatmap = example<HeatmapT>(HEATMAP);
    chart.props!.onBrush(nsToMs(heatmap.from_ns) + 1, nsToMs(heatmap.to_ns) - 1);
    await waitFor(() => expect(within(list).getAllByRole("option")).toHaveLength(1));
    expect(within(list).getByRole("option").getAttribute("tabindex")).toBe("0");
  });

  it("switching symbol never shows the previous symbol's marks while loading", async () => {
    api({
      "/api/v1/audit/market/BBB/heatmap": () => new Promise(() => {}),
      "/api/v1/audit/market/BBB/lifelines": () => new Promise(() => {}),
    });
    await open();
    fireEvent.change(screen.getByLabelText("Symbol"), { target: { value: "BBB" } });
    await waitFor(() => expect(screen.queryByRole("listbox", { name: "Order lifelines" })).toBeNull());
    expect(screen.queryByText("Updating…")).toBeNull();
  });

  it("a malformed run in the URL is not sent to the API", async () => {
    const id = lifelines().lifelines[0]!.order_id;
    const stub = api();
    renderApp(`/market?symbol=AAA&order=${id}&run=abc`);
    await screen.findByRole("dialog");
    const asked = new URL(stub.calls(`/api/v1/audit/stories/order/${id}`)[0]!.url, "http://gui.test");
    expect(asked.searchParams.has("run_id")).toBe(false);
  });

  it("without a pinned snapshot it asks for one", () => {
    useSnapshotStore.getState().clear();
    api();
    renderApp("/market");
    expect(screen.getByText("No snapshot pinned")).toBeTruthy();
  });
});
