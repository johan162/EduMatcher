// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAutoPaging } from "../src/lib/useAutoPaging.js";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

const advance = (seconds: number) => act(() => void vi.advanceTimersByTime(seconds * 1000));

describe("auto-advance", () => {
  it("moves to the next page once the dwell elapses", () => {
    const { result } = renderHook(() => useAutoPaging(25, 10, 8));
    expect(result.current.page).toBe(0);

    advance(8);
    expect(result.current.page).toBe(1);
  });

  it("does not advance early", () => {
    const { result } = renderHook(() => useAutoPaging(25, 10, 8));
    advance(7);
    expect(result.current.page).toBe(0);
  });

  it("cycles back to the first page after the last", () => {
    const { result } = renderHook(() => useAutoPaging(25, 10, 5));
    advance(15);
    expect(result.current.page).toBe(0);
  });

  it("stays on a single page rather than cycling it against itself", () => {
    const { result } = renderHook(() => useAutoPaging(5, 10, 5));
    expect(result.current.advancing).toBe(false);

    advance(30);
    expect(result.current.page).toBe(0);
  });
});

describe("pausing", () => {
  it("stops advancing while paused", () => {
    const { result } = renderHook(() => useAutoPaging(25, 10, 5));
    act(() => result.current.setPaused(true));

    advance(30);
    expect(result.current.page).toBe(0);
  });

  it("resumes after unpausing", () => {
    const { result } = renderHook(() => useAutoPaging(25, 10, 5));
    act(() => result.current.setPaused(true));
    advance(30);
    act(() => result.current.setPaused(false));

    advance(5);
    expect(result.current.page).toBe(1);
  });

  it("reports whether the timer is actually running", () => {
    const { result } = renderHook(() => useAutoPaging(25, 10, 5));
    expect(result.current.advancing).toBe(true);

    act(() => result.current.togglePaused());
    expect(result.current.advancing).toBe(false);
  });
});

describe("manual stepping", () => {
  it("steps forward and back", () => {
    const { result } = renderHook(() => useAutoPaging(25, 10, 5));
    act(() => result.current.next());
    expect(result.current.page).toBe(1);

    act(() => result.current.prev());
    expect(result.current.page).toBe(0);
  });

  it("wraps backwards from the first page", () => {
    const { result } = renderHook(() => useAutoPaging(25, 10, 5));
    act(() => result.current.prev());
    expect(result.current.page).toBe(2);
  });

  it("restarts the dwell, so a manual step gets a full page's reading time", () => {
    const { result } = renderHook(() => useAutoPaging(25, 10, 5));
    advance(4);
    act(() => result.current.next()); // page 1, 1s short of an auto-advance

    advance(4);
    expect(result.current.page).toBe(1);

    advance(1);
    expect(result.current.page).toBe(2);
  });
});

describe("shrinking grids", () => {
  it("holds the viewer on the last real page when rows disappear", () => {
    const { result, rerender } = renderHook(({ total }) => useAutoPaging(total, 10, 5), {
      initialProps: { total: 50 },
    });
    act(() => result.current.next());
    act(() => result.current.next());
    expect(result.current.page).toBe(2);

    // A watchlist filter cuts the grid to twelve rows: two pages.
    rerender({ total: 12 });
    expect(result.current.page).toBe(1);
  });

  it("reports the page count for the current row set", () => {
    const { result, rerender } = renderHook(({ total }) => useAutoPaging(total, 10, 5), {
      initialProps: { total: 50 },
    });
    expect(result.current.pages).toBe(5);

    rerender({ total: 12 });
    expect(result.current.pages).toBe(2);
  });
});
