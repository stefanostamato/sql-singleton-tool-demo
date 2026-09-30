"""Spend ledger: results/ledger.json with a capped pot per stage of the experiment.

Written atomically after every model turn so a crash never loses recorded spend.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "results" / "ledger.json"
DEFAULT_POTS = {"dev": 1.0, "proof": 2.0, "showcase": 7.0, "p2-base": 3.0, "p2-variants": 3.5}


class Ledger:
    def __init__(self, path: str | Path = DEFAULT_PATH, cap_override: float | None = None) -> None:
        self.path = Path(path)
        self.cap_override = cap_override
        if self.path.exists():
            self.data = json.loads(self.path.read_text())
        else:
            self.data = {
                "pots": {name: {"cap": cap, "spent": 0} for name, cap in DEFAULT_POTS.items()},
                "runs": [],
            }
            self._write()

    def ensure_pot(self, pot: str, cap: float) -> None:
        """Add a pot with this cap if it does not exist. An existing pot is never changed."""
        if pot not in self.data["pots"]:
            self.data["pots"][pot] = {"cap": cap, "spent": 0}
            self._write()

    def cap(self, pot: str) -> float:
        return self.cap_override if self.cap_override is not None else self.data["pots"][pot]["cap"]

    def spent(self, pot: str) -> float:
        return self.data["pots"][pot]["spent"]

    def add(self, pot: str, run_id: str, model: str, delta_usd: float) -> None:
        """Add `delta_usd` to the pot and to this run's entry, then persist."""
        self.data["pots"][pot]["spent"] = round(self.data["pots"][pot]["spent"] + delta_usd, 8)
        entry = next((r for r in self.data["runs"] if r["run_id"] == run_id and r["pot"] == pot and not r["finished_at"]), None)
        if entry is None:
            entry = {"run_id": run_id, "pot": pot, "model": model, "cost_usd": 0, "finished_at": None}
            self.data["runs"].append(entry)
        entry["cost_usd"] = round(entry["cost_usd"] + delta_usd, 8)
        self._write()

    def finish(self, pot: str, run_id: str, model: str) -> None:
        entry = next((r for r in self.data["runs"] if r["run_id"] == run_id and r["pot"] == pot and not r["finished_at"]), None)
        if entry is None:
            entry = {"run_id": run_id, "pot": pot, "model": model, "cost_usd": 0, "finished_at": None}
            self.data["runs"].append(entry)
        entry["finished_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._write()

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".ledger-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(self.data, f, indent=2)
                f.write("\n")
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
