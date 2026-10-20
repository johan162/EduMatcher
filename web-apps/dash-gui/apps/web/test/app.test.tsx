// @vitest-environment jsdom
/**
 * The whole web app, end to end: the real `App` with its real stream hook and
 * stores, talking to a fake bridge socket: the shell, the connection
 * states and the theme (WP-D1's details are in shell.test.tsx).
 */

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ServerFrame } from "@edumatcher/dash-types";
import App from "../src/App.js";
import { useDashStore } from "../src/store/useDashStore.js";
import { usePrefsStore } from "../src/store/usePrefsStore.js";
import appVersion from "../src/version.json";
import { FakeSocket } from "./fake-socket.js";

const hello = (monitor: "UP" | "DOWN"): ServerFrame => ({
  type: "hello",
  version: "1.2.3",
  monitor,
  sessionTz: "Europe/Stockholm",
});

function renderAt(path = "/") {
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
  const socket = FakeSocket.latest();
  socket.open();
  return socket;
}

beforeEach(() => {
  cleanup();
  localStorage.clear();
  FakeSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeSocket);
  useDashStore.setState({ socket: "CONNECTING", monitor: null, bridgeVersion: null, sessionTz: "UTC", snapshot: null, events: [] });
  usePrefsStore.setState({ theme: "dark" });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("shell", () => {
  it("shows the wordmark, the app name and the build version", () => {
    renderAt();
    expect(screen.getByText("pm-dash")).toBeTruthy();
    expect(screen.getByText(`v${appVersion.version}`)).toBeTruthy();
    expect(screen.getByRole("region", { name: "Dashboard" })).toBeTruthy();
  });

  it("connects to the bridge's /ws", () => {
    const socket = renderAt();
    expect(new URL(socket.url).pathname).toBe("/ws");
  });

  it("sends an unknown route to the dashboard", () => {
    renderAt("/no/such/page");
    expect(screen.getByRole("region", { name: "Dashboard" })).toBeTruthy();
  });
});

describe("connection states", () => {
  it("the footer follows pm-monitor's state as the bridge reports it", () => {
    const socket = renderAt();
    socket.deliver(hello("UP"));
    expect(screen.getByText("LIVE")).toBeTruthy();
    expect(screen.getByTestId("monitor-state").textContent).toBe("pm-monitor UP");
    socket.deliver({ type: "monitor_state", monitor: "DOWN" });
    expect(screen.getByTestId("monitor-state").textContent).toBe("pm-monitor DOWN");
  });

  it("keeps the dashboard, dimmed under the banner, while the bridge is unreachable, and reconnects", async () => {
    const socket = renderAt();
    socket.deliver(hello("UP"));

    socket.drop();
    expect(screen.getByRole("alert").textContent).toContain("pm-dash-bridge unreachable");
    expect(screen.getByRole("region", { name: "Dashboard" })).toBeTruthy();
    expect(screen.getByText("OFFLINE")).toBeTruthy();

    await waitFor(() => expect(FakeSocket.instances).toHaveLength(2), { timeout: 3000 });
    const again = FakeSocket.latest();
    again.open();
    again.deliver(hello("UP"));
    expect(screen.getByText("LIVE")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("theme", () => {
  it("toggles between dark and light and remembers the choice", () => {
    renderAt();
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Theme: dark" }));
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(JSON.parse(localStorage.getItem("dash-prefs") ?? "{}").state.theme).toBe("light");
  });
});
