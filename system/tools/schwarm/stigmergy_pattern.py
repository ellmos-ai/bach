# SPDX-License-Identifier: MIT
"""
stigmergy_pattern.py - Stigmergy-Muster fuer Schwarm-Entscheidungen
=====================================================================
Agenten hinterlassen Pheromone (Bewertungen) zu einer Frage/Aufgabe.
Andere Agenten lesen Pheromone und folgen den staerksten Pfaden.

Wrapper um die bestehende stigmergy_api.py (StigmergyAPI).

Ablauf:
  1. Mehrere Agenten generieren unabhaengig Loesungsansaetze
  2. Jeder Agent bewertet seinen Ansatz und hinterlaesst ein Pheromon
  3. In Folgerunden lesen Agenten bestehende Pheromone und
     verfeinern die vielversprechendsten Ansaetze
  4. Nach allen Runden wird der beste Pfad als Ergebnis gewaehlt

Usage (als Modul):
    from tools.schwarm.stigmergy_pattern import StigmeryPattern
    sp = StigmeryPattern(task="Wie strukturiere ich einen Microservice?")
    result = sp.run()

Usage (CLI):
    python -m tools.schwarm.stigmergy_pattern "Aufgabe" --agents 3 --rounds 2

Ref: BACH v3.8.0-SUGAR
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

from .runner import ClaudeRunner, log_schwarm_run

try:
    from hub.bach_paths import BACH_DB as _DB_PATH
except ImportError:
    _DB_PATH = Path(__file__).parent.parent.parent / "data" / "bach.db"


class StigmergyPattern:
    """Stigmergy-Muster: Indirekte Koordination ueber Pheromon-Markierungen."""

    MODEL_MAP = {
        "haiku": "claude-haiku-4-5-20251001",
        "sonnet": "claude-sonnet-4-6",
        "opus": "claude-opus-4-6",
    }

    def __init__(self, task: str, num_agents: int = 3, rounds: int = 2,
                 evaporation_rate: float = 0.1, model: str = "haiku",
                 timeout: int = 300):
        """
        Initialisiert das Stigmergy-Muster.

        Args:
            task: Die zu bearbeitende Aufgabe/Frage
            num_agents: Anzahl paralleler Agenten (default: 3)
            rounds: Anzahl Iterationsrunden (default: 2)
            evaporation_rate: Verdunstungsrate fuer schwache Pheromone (default: 0.1)
            model: Modell fuer alle Agenten (default: haiku)
            timeout: Timeout pro Aufruf in Sekunden
        """
        self.task = task
        self.num_agents = max(2, num_agents)
        self.rounds = max(1, rounds)
        self.evaporation_rate = max(0.0, min(1.0, evaporation_rate))
        self.model = self.MODEL_MAP.get(model, model)
        self.timeout = timeout
        # Eindeutiger Praefix fuer diese Session
        self.session_id = f"stg_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    def _get_stigmergy_api(self, agent_id: str):
        """Erstellt eine StigmergyAPI-Instanz.

        Importiert lazy, damit das Modul auch ohne DB funktioniert.
        """
        try:
            sys.path.insert(0, str(Path(__file__).parent.parent.parent))
            from hub._services.stigmergy.stigmergy_api import StigmergyAPI
            return StigmergyAPI(str(_DB_PATH), agent_id=agent_id)
        except ImportError:
            return None

    def _generate_approaches(self, round_num: int,
                              existing_pheromones: List[Dict]) -> List[Dict]:
        """Agenten generieren Loesungsansaetze.

        In Runde 1: Unabhaengige Ansaetze.
        In Folgerunden: Pheromone lesen und verfeinern.

        Args:
            round_num: Aktuelle Rundennummer (1-basiert)
            existing_pheromones: Bestehende Pheromone aus vorherigen Runden

        Returns:
            Liste von Agent-Ergebnis-Dicts
        """
        runner = ClaudeRunner(
            model=self.model,
            timeout=self.timeout,
            allowed_tools=[],
        )

        prompts = []
        for i in range(self.num_agents):
            if round_num == 1:
                # Erste Runde: Unabhaengige Ansaetze
                prompt = (
                    f"Du bist Agent {i+1} in einem Schwarm. Bearbeite die folgende "
                    f"Aufgabe und liefere einen eigenstaendigen Loesungsansatz.\n\n"
                    f"Aufgabe: {self.task}\n\n"
                    f"Antworte in folgendem Format:\n"
                    f"ANSATZ: [Kurze Bezeichnung deines Ansatzes]\n"
                    f"BEWERTUNG: [Zahl 1-10, wie vielversprechend dein Ansatz ist]\n"
                    f"LOESUNG:\n[Deine detaillierte Loesung]"
                )
            else:
                # Folgerunden: Pheromone beruecksichtigen
                pheromone_info = ""
                if existing_pheromones:
                    pheromone_lines = []
                    for p in existing_pheromones[:5]:  # Max 5 beste Pheromone
                        meta = p.get("metadata", {})
                        pheromone_lines.append(
                            f"  - {p['path_id']}: Staerke {p['strength']:.2f} "
                            f"(Ansatz: {meta.get('approach', '?')}, "
                            f"Bewertung: {meta.get('self_rating', '?')})"
                        )
                    pheromone_info = (
                        f"\n\nBisherige Erkenntnisse (Pheromone) aus Runde {round_num-1}:\n"
                        + "\n".join(pheromone_lines)
                    )

                prompt = (
                    f"Du bist Agent {i+1} in einem Schwarm (Runde {round_num}). "
                    f"Verfeinere den vielversprechendsten Ansatz oder schlage eine "
                    f"Verbesserung vor.\n\n"
                    f"Aufgabe: {self.task}"
                    f"{pheromone_info}\n\n"
                    f"Antworte in folgendem Format:\n"
                    f"ANSATZ: [Kurze Bezeichnung deines Ansatzes]\n"
                    f"BEWERTUNG: [Zahl 1-10, wie vielversprechend dein Ansatz ist]\n"
                    f"LOESUNG:\n[Deine detaillierte Loesung]"
                )
            prompts.append(prompt)

        print(f"[STIGMERGY] Runde {round_num}: {self.num_agents} Agenten ({self.model})...")
        start = time.time()

        raw_results = runner.run_parallel(prompts, max_workers=self.num_agents)

        elapsed = time.time() - start
        print(f"[STIGMERGY] Runde {round_num} fertig in {elapsed:.1f}s")

        results = []
        for i, result in enumerate(raw_results):
            # Ansatz-Name und Selbstbewertung extrahieren
            approach_name = f"approach_{self.session_id}_r{round_num}_a{i+1}"
            self_rating = 5  # Default

            if result["success"] and result["output"]:
                output = result["output"]
                # Versuche ANSATZ: zu extrahieren
                for line in output.split("\n"):
                    line_stripped = line.strip()
                    if line_stripped.upper().startswith("ANSATZ:"):
                        approach_name = line_stripped[7:].strip()[:50]
                    elif line_stripped.upper().startswith("BEWERTUNG:"):
                        try:
                            rating_str = line_stripped[10:].strip().split()[0]
                            self_rating = int(float(rating_str))
                            self_rating = max(1, min(10, self_rating))
                        except (ValueError, IndexError):
                            pass

            results.append({
                "agent_id": i + 1,
                "round": round_num,
                "approach": approach_name,
                "self_rating": self_rating,
                "success": result["success"],
                "output": result["output"],
                "duration_s": result["duration_s"],
                "tokens_in": result.get("tokens_in", 0),
                "tokens_out": result.get("tokens_out", 0),
                "cost_usd": result.get("cost_usd", 0.0),
            })

            status = "OK" if result["success"] else "FEHLER"
            print(f"  Agent {i+1}: {status} - Ansatz: {approach_name} (Bewertung: {self_rating}/10)")

        return results

    def _deposit_pheromones(self, agent_results: List[Dict]) -> int:
        """Hinterlegt Pheromone fuer die Agenten-Ergebnisse.

        Args:
            agent_results: Ergebnisse der Agenten

        Returns:
            Anzahl erfolgreich hinterlegter Pheromone
        """
        deposited = 0
        for ar in agent_results:
            if not ar["success"]:
                continue

            agent_id_str = f"schwarm_agent_{ar['agent_id']}"
            api = self._get_stigmergy_api(agent_id_str)
            if api is None:
                continue

            # Staerke aus Selbstbewertung berechnen (1-10 -> 0.1-1.0)
            strength = ar["self_rating"] / 10.0

            path_id = f"{self.session_id}_{ar['approach']}"
            metadata = {
                "approach": ar["approach"],
                "self_rating": ar["self_rating"],
                "round": ar["round"],
                "task": self.task[:200],
                "output_preview": ar["output"][:300] if ar["output"] else "",
            }

            if api.deposit(path_id, strength, metadata):
                deposited += 1

        return deposited

    def _read_pheromones(self) -> List[Dict]:
        """Liest alle Pheromone fuer diese Session.

        Returns:
            Liste von Pheromon-Dicts, sortiert nach Staerke
        """
        api = self._get_stigmergy_api("schwarm_reader")
        if api is None:
            return []
        return api.sense(self.session_id)

    def _evaporate(self) -> int:
        """Verdunstung: Schwache Pheromone abschwaechen.

        Returns:
            Anzahl verdunsteter Pheromone
        """
        if self.evaporation_rate <= 0:
            return 0

        api = self._get_stigmergy_api("schwarm_evaporator")
        if api is None:
            return 0
        return api.evaporate(self.evaporation_rate)

    def run(self, dry_run: bool = False) -> Dict:
        """Fuehrt das Stigmergy-Muster aus.

        Args:
            dry_run: Nur Konfiguration anzeigen, keine API-Aufrufe

        Returns:
            Dict mit best_path, result, all_results, stats
        """
        print(f"\n{'=' * 60}")
        print(f"  SCHWARM STIGMERGY")
        print(f"{'=' * 60}")
        print(f"  Aufgabe:          {self.task[:80]}...")
        print(f"  Agenten:          {self.num_agents}")
        print(f"  Runden:           {self.rounds}")
        print(f"  Verdunstung:      {self.evaporation_rate:.1%}")
        print(f"  Modell:           {self.model}")
        print(f"  Session:          {self.session_id}")
        print()

        if dry_run:
            print("[DRY-RUN] Wuerde folgende Phasen durchlaufen:")
            for r in range(1, self.rounds + 1):
                print(f"  Runde {r}: {self.num_agents} Agenten generieren Ansaetze")
                print(f"           Pheromone hinterlegen, Verdunstung anwenden")
            print(f"  Abschluss: Besten Pfad waehlen")
            return {"dry_run": True}

        start_time = time.time()
        total_tokens_in = 0
        total_tokens_out = 0
        total_cost = 0.0
        all_results = []

        # Iterationsrunden
        for round_num in range(1, self.rounds + 1):
            print(f"\n--- Runde {round_num}/{self.rounds} ---")

            # Bestehende Pheromone lesen
            existing = self._read_pheromones()
            if existing:
                print(f"  Bestehende Pheromone: {len(existing)}")

            # Agenten generieren Ansaetze
            agent_results = self._generate_approaches(round_num, existing)
            all_results.extend(agent_results)

            # Kosten akkumulieren
            for ar in agent_results:
                total_tokens_in += ar.get("tokens_in", 0)
                total_tokens_out += ar.get("tokens_out", 0)
                total_cost += ar.get("cost_usd", 0.0)

            # Pheromone hinterlegen
            deposited = self._deposit_pheromones(agent_results)
            print(f"  Pheromone hinterlegt: {deposited}")

            # Verdunstung anwenden (ausser in letzter Runde)
            if round_num < self.rounds:
                evaporated = self._evaporate()
                if evaporated > 0:
                    print(f"  Verdunstete Pheromone: {evaporated}")

        # Besten Pfad bestimmen
        final_pheromones = self._read_pheromones()
        best_path = None
        best_result = None

        if final_pheromones:
            best = final_pheromones[0]
            best_path = best["path_id"]
            best_meta = best.get("metadata", {})

            # Zugehoeriges vollstaendiges Ergebnis finden
            best_approach = best_meta.get("approach", "")
            for ar in reversed(all_results):
                if ar.get("approach") == best_approach and ar.get("success"):
                    best_result = ar["output"]
                    break

            if not best_result:
                best_result = best_meta.get("output_preview", "(Kein Ergebnis)")
        else:
            # Fallback: Bestes Ergebnis nach Selbstbewertung
            successful = [ar for ar in all_results if ar["success"]]
            if successful:
                best_ar = max(successful, key=lambda x: x["self_rating"])
                best_path = best_ar["approach"]
                best_result = best_ar["output"]

        elapsed = time.time() - start_time

        # Kosten-Tracking in DB
        try:
            log_schwarm_run(
                pattern="stigmergy",
                task=self.task[:500],
                tokens_in=total_tokens_in,
                tokens_out=total_tokens_out,
                cost_usd=total_cost,
                workers=self.num_agents,
                duration_ms=int(elapsed * 1000),
                status="completed" if best_result else "failed",
                result_summary=(
                    f"rounds={self.rounds}, agents={self.num_agents}, "
                    f"best_path={best_path or 'none'}, "
                    f"pheromones={len(final_pheromones)}"
                ),
            )
        except Exception:
            pass

        # Ergebnis ausgeben
        print(f"\n{'=' * 60}")
        print(f"  ERGEBNIS")
        print(f"{'=' * 60}")

        if best_result:
            print(f"  Bester Pfad:   {best_path}")
            print(f"  Pheromone:     {len(final_pheromones)} aktiv")
            print(f"  Runden:        {self.rounds}")
            print(f"  Dauer:         {elapsed:.1f}s")
            print(f"  Kosten:        ${total_cost:.4f}")
            print(f"\n  --- BESTE LOESUNG ---")
            for line in best_result.split("\n"):
                print(f"  {line}")
        else:
            print(f"  KEIN ERGEBNIS GEFUNDEN")

        print(f"{'=' * 60}")

        return {
            "success": best_result is not None,
            "best_path": best_path,
            "result": best_result,
            "pheromones": final_pheromones,
            "all_results": all_results,
            "stats": {
                "total_duration_s": elapsed,
                "tokens_in": total_tokens_in,
                "tokens_out": total_tokens_out,
                "cost_usd": total_cost,
                "num_agents": self.num_agents,
                "rounds": self.rounds,
                "model": self.model,
                "session_id": self.session_id,
            },
        }


def main():
    """CLI-Einstieg fuer Stigmergy-Muster."""
    parser = argparse.ArgumentParser(
        description="Schwarm Stigmergy-Muster: Indirekte Koordination ueber Pheromone"
    )
    parser.add_argument("task", nargs="?", help="Die zu bearbeitende Aufgabe")
    parser.add_argument(
        "--agents", "-a", type=int, default=3,
        help="Anzahl Agenten (default: 3)"
    )
    parser.add_argument(
        "--rounds", "-r", type=int, default=2,
        help="Anzahl Runden (default: 2)"
    )
    parser.add_argument(
        "--evaporation", "-e", type=float, default=0.1,
        help="Verdunstungsrate (default: 0.1)"
    )
    parser.add_argument(
        "--model", "-m", default="haiku",
        help="Modell: haiku, sonnet, opus (default: haiku)"
    )
    parser.add_argument(
        "--timeout", type=int, default=300,
        help="Timeout pro Aufruf in Sekunden (default: 300)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Nur Konfiguration anzeigen"
    )

    args = parser.parse_args()

    if not args.task:
        parser.print_help()
        print("\nBeispiel: python -m tools.schwarm.stigmergy_pattern \"Wie strukturiere ich einen Microservice?\"")
        return 1

    pattern = StigmergyPattern(
        task=args.task,
        num_agents=args.agents,
        rounds=args.rounds,
        evaporation_rate=args.evaporation,
        model=args.model,
        timeout=args.timeout,
    )

    result = pattern.run(dry_run=args.dry_run)
    return 0 if result.get("success") or result.get("dry_run") else 1


if __name__ == "__main__":
    sys.exit(main())
