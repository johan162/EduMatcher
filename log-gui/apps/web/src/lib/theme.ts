/** Dark default, light supported, system option (design §7.5). */

export type ThemePreference = "dark" | "light" | "system";

const STORAGE_KEY = "log-ui-theme";

export function getStoredTheme(): ThemePreference {
  const raw = localStorage.getItem(STORAGE_KEY);
  return raw === "light" || raw === "dark" || raw === "system" ? raw : "dark";
}

export function applyTheme(pref: ThemePreference): void {
  localStorage.setItem(STORAGE_KEY, pref);
  const wantsDark =
    pref === "dark" || (pref === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", wantsDark);
}

export function cycleTheme(current: ThemePreference): ThemePreference {
  if (current === "dark") return "light";
  if (current === "light") return "system";
  return "dark";
}
