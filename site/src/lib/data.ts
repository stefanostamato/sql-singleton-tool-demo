import { useEffect, useState } from "react";
import { normalizeRow, truthName } from "./normalize";
import type { IndexRow, RawIndexRow, Trace, Truth } from "./types";

const cache = new Map<string, Promise<unknown>>();

function getJson<T>(path: string): Promise<T> {
  let p = cache.get(path);
  if (!p) {
    p = fetch(path).then((r) => {
      if (!r.ok) throw new Error(`${path}: ${r.status}`);
      return r.json();
    });
    // Do not keep failures, so a later retry can succeed.
    p.catch(() => cache.delete(path));
    cache.set(path, p);
  }
  return p as Promise<T>;
}

export const loadIndex = () =>
  getJson<RawIndexRow[]>("data/index.json").then((rows): IndexRow[] => rows.map(normalizeRow));
export const loadTrace = (id: string) => getJson<Trace>(`data/traces/${id}.json`);
export const loadTruth = (name: string) => getJson<Truth>(`data/truth/${name}.json`);

export interface Loaded<T> {
  data: T | null;
  error: string | null;
}

function useLoaded<T>(load: (() => Promise<T>) | null, key: string): Loaded<T> {
  const [state, setState] = useState<{ key: string; data: T | null; error: string | null } | null>(null);
  useEffect(() => {
    if (!load) return;
    let live = true;
    load().then(
      (data) => live && setState({ key, data, error: null }),
      (e) => live && setState({ key, data: null, error: e instanceof Error ? e.message : String(e) }),
    );
    return () => {
      live = false;
    };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  return state && state.key === key ? { data: state.data, error: state.error } : { data: null, error: null };
}

export const useIndex = () => useLoaded(loadIndex, "index");
export const useTrace = (id: string | null) =>
  useLoaded(id ? () => loadTrace(id) : null, id ?? "none");
export const useTruth = (row: IndexRow | null) => {
  const name = row ? truthName(row) : null;
  return useLoaded(name ? () => loadTruth(name) : null, name ?? "none");
};
