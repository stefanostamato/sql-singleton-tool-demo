export type ThemeMode = 'light' | 'dark' | 'system';

const KEY = 'theme';

/** Returns the stored choice, or 'system' when none is stored. */
export function getTheme(): ThemeMode {
  const stored = localStorage.getItem(KEY);
  return stored === 'light' || stored === 'dark' ? stored : 'system';
}

/** Stores the choice and applies it. 'system' clears both, so the OS preference applies. */
export function setTheme(mode: ThemeMode): void {
  const root = document.documentElement;
  if (mode === 'system') {
    localStorage.removeItem(KEY);
    delete root.dataset.theme;
  } else {
    localStorage.setItem(KEY, mode);
    root.dataset.theme = mode;
  }
}
