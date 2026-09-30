import { VARIANT_NAME } from "../config";
import type { Variant } from "../lib/types";
import css from "./VariantFilter.module.css";

export default function VariantFilter({
  variants,
  value,
  onChange,
}: {
  variants: Variant[];
  value: Variant;
  onChange: (v: Variant) => void;
}) {
  return (
    <div className={css.bar} data-testid="variant-filter">
      <div className="wrap">
        <span className={css.label} id="variant-label">
          Task variant
        </span>
        <div className={css.seg} role="group" aria-labelledby="variant-label">
          {variants.map((v) => (
            <button
              key={v}
              className={v === value ? css.on : undefined}
              aria-pressed={v === value}
              data-testid={`variant-${v}`}
              onClick={() => onChange(v)}
            >
              {VARIANT_NAME[v]}
            </button>
          ))}
        </div>
        <span className="muted small">Applies to the replay, scaling and accuracy sections below.</span>
      </div>
    </div>
  );
}
