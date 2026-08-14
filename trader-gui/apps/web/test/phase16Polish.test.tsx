// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import type { ConnectionHealth } from "@/hooks/useConnectionHealth";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { Skeleton, TableSkeleton } from "@/components/shared/Skeleton";
import { EmptyState } from "@/components/shared/EmptyState";

// ── ConnectionBanner reads the health hook; drive it from a mutable ref. ──────
const healthRef = vi.hoisted(() => ({
  current: {
    events: "connected",
    marketData: "connected",
    adminMonitor: null,
    overall: "connected",
    lastMarketDataAt: null,
  } as ConnectionHealth,
}));
vi.mock("@/hooks/useConnectionHealth", () => ({
  useConnectionHealth: () => healthRef.current,
}));
// Imported after the mock so it picks up the mocked hook.
import { ConnectionBanner } from "@/components/layout/ConnectionBanner";

function setHealth(overall: ConnectionHealth["overall"]) {
  healthRef.current = { ...healthRef.current, overall };
}

beforeEach(() => cleanup());

describe("ErrorBoundary (§23 phase 16 — no uncaught errors)", () => {
  let errSpy: ReturnType<typeof vi.spyOn>;
  beforeEach(() => {
    // React logs caught render errors to console.error; silence for clean output.
    errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  });
  afterEach(() => errSpy.mockRestore());

  it("renders an inline alert with the error message instead of crashing", () => {
    const Boom = () => {
      throw new Error("kaboom-42");
    };
    render(
      <ErrorBoundary label="Test screen">
        <Boom />
      </ErrorBoundary>,
    );
    const alert = screen.getByRole("alert");
    expect(alert).toBeTruthy();
    expect(alert.textContent).toContain("Test screen hit an error");
    expect(alert.textContent).toContain("kaboom-42");
  });

  it("'Try again' resets the boundary so a recovered subtree renders", () => {
    let shouldThrow = true;
    function Flaky() {
      if (shouldThrow) throw new Error("still broken");
      return <div>all good now</div>;
    }
    render(
      <ErrorBoundary>
        <Flaky />
      </ErrorBoundary>,
    );
    expect(screen.getByRole("alert")).toBeTruthy();

    // Underlying cause fixed → retry should now render the children.
    shouldThrow = false;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(screen.getByText("all good now")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("renders children untouched when nothing throws", () => {
    render(
      <ErrorBoundary>
        <div>healthy child</div>
      </ErrorBoundary>,
    );
    expect(screen.getByText("healthy child")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("ConnectionBanner (§23 phase 16 — graceful degradation)", () => {
  it("renders nothing while fully connected", () => {
    setHealth("connected");
    const { container } = render(<ConnectionBanner />);
    expect(container.firstChild).toBeNull();
  });

  it("shows a paused-data notice while reconnecting", () => {
    setHealth("reconnecting");
    render(<ConnectionBanner />);
    const status = screen.getByRole("status");
    expect(status.textContent).toContain("Reconnecting");
  });

  it("shows a stale-data warning when disconnected", () => {
    setHealth("disconnected");
    render(<ConnectionBanner />);
    const status = screen.getByRole("status");
    expect(status.textContent).toContain("Disconnected");
    expect(status.textContent?.toLowerCase()).toContain("stale");
  });
});

describe("Skeleton / TableSkeleton (§23 phase 16 — loading states)", () => {
  it("TableSkeleton exposes a busy status for assistive tech", () => {
    render(<TableSkeleton rows={3} columns={4} />);
    const status = screen.getByRole("status");
    expect(status.getAttribute("aria-busy")).toBe("true");
    expect(status.textContent).toContain("Loading");
  });

  it("TableSkeleton renders header + requested rows of cells", () => {
    const { container } = render(<TableSkeleton rows={3} columns={4} />);
    // 1 header row + 3 body rows, each 4 pulsing cells = 16 blocks.
    const blocks = container.querySelectorAll(".animate-pulse");
    expect(blocks.length).toBe(16);
  });

  it("Skeleton applies caller sizing and is hidden from the a11y tree", () => {
    const { container } = render(<Skeleton className="h-8 w-24" />);
    const el = container.firstChild as HTMLElement;
    expect(el.className).toContain("h-8");
    expect(el.className).toContain("w-24");
    expect(el.getAttribute("aria-hidden")).toBe("true");
  });
});

describe("EmptyState (§23 phase 16 — empty states)", () => {
  it("shows the title, hint, and an optional action", () => {
    render(
      <EmptyState
        title="No open orders"
        hint="Orders you place will appear here."
        action={<button type="button">Place an order</button>}
      />,
    );
    expect(screen.getByText("No open orders")).toBeTruthy();
    expect(screen.getByText("Orders you place will appear here.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Place an order" })).toBeTruthy();
  });
});
