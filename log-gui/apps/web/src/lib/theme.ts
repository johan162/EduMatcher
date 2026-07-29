/** Dark default, light supported (design §7.5). */

export type ThemePreference = "dark" | "light";

const STORAGE_KEY = "log-ui-theme";

export function getStoredTheme(): ThemePreference {
  const raw = localStorage.getItem(STORAGE_KEY);
  return raw === "light" || raw === "dark" ? raw : "dark";
}

export function applyTheme(pref: ThemePreference): void {
  localStorage.setItem(STORAGE_KEY, pref);
  document.documentElement.classList.toggle("dark", pref === "dark");
}

export function cycleTheme(current: ThemePreference): ThemePreference {
  return current === "dark" ? "light" : "dark";
}
