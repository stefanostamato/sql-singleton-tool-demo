import { useEffect, useState } from "react";
import { getTheme, setTheme } from "../lib/theme";
import css from "./ThemeToggle.module.css";

type Mode = "light" | "dark";

const systemDark = () => window.matchMedia("(prefers-color-scheme: dark)").matches;

function effective(): Mode {
  try {
    const t = getTheme();
    if (t !== "system") return t;
  } catch {
    // storage blocked: fall through to the system preference
  }
  return systemDark() ? "dark" : "light";
}

const icon = {
  width: 15,
  height: 15,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.75,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

export default function ThemeToggle() {
  const [current, setCurrent] = useState<Mode>(effective);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const sync = () => setCurrent(effective());
    const onStorage = (e: StorageEvent) => {
      if (e.key === "theme" || e.key === null) sync();
    };
    mq.addEventListener("change", sync);
    window.addEventListener("storage", onStorage);
    return () => {
      mq.removeEventListener("change", sync);
      window.removeEventListener("storage", onStorage);
    };
  }, []);

  const pick = (mode: Mode) => {
    try {
      setTheme(mode);
    } catch {
      document.documentElement.dataset.theme = mode;
    }
    setCurrent(mode);
  };

  return (
    <div className={css.toggle} role="group" aria-label="Theme">
      <button type="button" className={css.target} aria-pressed={current === "light"} aria-label="Light theme" onClick={() => pick("light")}>
        <svg {...icon}>
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2" />
          <path d="M12 20v2" />
          <path d="m4.93 4.93 1.41 1.41" />
          <path d="m17.66 17.66 1.41 1.41" />
          <path d="M2 12h2" />
          <path d="M20 12h2" />
          <path d="m6.34 17.66-1.41 1.41" />
          <path d="m19.07 4.93-1.41 1.41" />
        </svg>
      </button>
      <button type="button" className={css.target} aria-pressed={current === "dark"} aria-label="Dark theme" onClick={() => pick("dark")}>
        <svg {...icon}>
          <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />
        </svg>
      </button>
    </div>
  );
}
