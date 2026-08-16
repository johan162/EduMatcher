import { describe, expect, it } from "vitest";
import { clampPage, pageCount, pageSlice, shouldAutoPage, wrapPage } from "../src/lib/paging.js";

describe("pageCount", () => {
  it("counts a partial final page", () => {
    expect(pageCount(23, 10)).toBe(3);
  });

  it("divides exactly without adding an empty page", () => {
    expect(pageCount(20, 10)).toBe(2);
  });

  it("reports one page for an empty grid, so page 1/1 never reads as 1/0", () => {
    expect(pageCount(0, 10)).toBe(1);
  });

  it("does not divide by zero before the viewport has been measured", () => {
    expect(pageCount(50, 0)).toBe(1);
  });
});

describe("wrapPage", () => {
  it("wraps past the last page back to the first, for unattended cycling", () => {
    expect(wrapPage(3, 25, 10)).toBe(0);
  });

  it("wraps backwards from the first page to the last", () => {
    expect(wrapPage(-1, 25, 10)).toBe(2);
  });

  it("leaves an in-range page alone", () => {
    expect(wrapPage(1, 25, 10)).toBe(1);
  });
});

describe("clampPage", () => {
  it("holds the viewer on the last page when the grid shrinks", () => {
    // Wrapping here would throw them back to page 1 mid-read.
    expect(clampPage(5, 12, 10)).toBe(1);
  });

  it("never goes negative", () => {
    expect(clampPage(-3, 50, 10)).toBe(0);
  });
});

describe("pageSlice", () => {
  const items = Array.from({ length: 25 }, (_, i) => i);

  it("returns the requested window", () => {
    expect(pageSlice(items, 1, 10)).toEqual([10, 11, 12, 13, 14, 15, 16, 17, 18, 19]);
  });

  it("returns the short remainder on the final page", () => {
    expect(pageSlice(items, 2, 10)).toEqual([20, 21, 22, 23, 24]);
  });

  it("clamps an out-of-range page rather than returning nothing", () => {
    expect(pageSlice(items, 99, 10)).toEqual([20, 21, 22, 23, 24]);
  });

  it("returns everything when the page size is not yet known", () => {
    expect(pageSlice(items, 0, 0)).toHaveLength(25);
  });
});

describe("shouldAutoPage", () => {
  it("advances when there is more than one page", () => {
    expect(shouldAutoPage(25, 10)).toBe(true);
  });

  it("stays put when everything fits on one page", () => {
    // Design §8.6: a small watchlist all fits, so cycling would be motion
    // without information.
    expect(shouldAutoPage(5, 10)).toBe(false);
  });

  it("stays put on an empty grid", () => {
    expect(shouldAutoPage(0, 10)).toBe(false);
  });
});
