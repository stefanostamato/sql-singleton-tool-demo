import { useState } from "react";
import { useIndex } from "./lib/data";
import { filterVariant, variantsPresent } from "./lib/phase2";
import type { Variant } from "./lib/types";
import VariantFilter from "./components/VariantFilter";
import Hero from "./components/Hero";
import Pipeline from "./components/Pipeline";
import Replay from "./components/Replay";
import Scaling from "./components/Scaling";
import Accuracy from "./components/Accuracy";
import Caveats from "./components/Caveats";
import Footer from "./components/Footer";
import ThemeToggle from "./components/ThemeToggle";

export default function App() {
  const { data: rows, error } = useIndex();
  const [picked, setPicked] = useState<Variant>("base");
  const variants = rows ? variantsPresent(rows) : [];
  const variant = variants.includes(picked) ? picked : (variants[0] ?? "base");
  const shown = rows ? filterVariant(rows, variant) : [];
  return (
    <>
      <nav className="topnav" aria-label="Sections">
        <div className="wrap">
          <a href="#top">Top</a>
          <a href="#pipeline">Pipeline</a>
          <a href="#replay">Replay</a>
          <a href="#scaling">Scaling</a>
          <a href="#accuracy">Accuracy</a>
          <a href="#caveats">Caveats</a>
          <ThemeToggle />
        </div>
      </nav>
      <main>
        {rows ? (
          <>
            <Hero rows={rows} />
            <Pipeline />
            <VariantFilter variants={variants} value={variant} onChange={setPicked} />
            <Replay rows={shown} />
            <Scaling rows={shown} />
            <Accuracy rows={shown} />
            <Caveats rows={rows} />
          </>
        ) : (
          <div className="wrap">
            <p className={error ? "" : "muted"} role={error ? "alert" : undefined}>
              {error ? `Could not load the runs (${error}).` : "Loading runs..."}
            </p>
          </div>
        )}
      </main>
      <Footer />
    </>
  );
}
