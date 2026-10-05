"""BACH20-05: seiteneffektfreier Read-only-Planer ueber Rueckfluss-Kandidaten.

Contract (task #1353 / planning item #1189):

  * PURE functions only - no environment, database, filesystem, logging,
    session, sync, backup or scheduler access, and no imports from hub
    modules. This module never mutates anything.
  * Exactly ONE result object per ``plane()`` call: status ``KANDIDAT``
    (one attested candidate) or ``NO_OP`` or ``BLOCKED``, with a reason
    of exactly one sentence (Ausgabevertrag "GENAU 1 Satz").
  * Output only - no submission/push (register rule R5), and no fallback
    archival while tasks #1340/#1341 are open (register rule R4).

Data provenance: read-only snapshot of the candidate register
``system/tasks/hub/BACH20-03-KANDIDATENREGISTER.md`` (Zwischenstand
2026-09-28; the register itself is input of tasks #1187/#1188). Only
register facts are copied into ``KANDIDATEN`` below - no content of
``BACH20-03-ID-VERTRAG.md`` is referenced here.

Register rules (section 5):
  R1  without green transfer tests  => BLOCKED
  R2  max 1 candidate per day (``heute_bereits_umgeschaltet`` => NO_OP)
  R3  NO_OP / BLOCKED is an allowed outcome
  R4  #1340/#1341 open              => no fallback archival
  R5  no submission / push

Disqualification policy: only the explicit disqualifications recorded in
the register are applied - unknown facts (``None`` flags) never
disqualify a candidate on their own. Rule R1 is a planning gate: a
candidate is only plannable when green transfer tests are affirmed
(``transfertests_gruen is True``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

REGISTER_SOURCE = "system/tasks/hub/BACH20-03-KANDIDATENREGISTER.md"
REGISTER_SNAPSHOT = "2026-09-28"

STATUS_KANDIDAT = "KANDIDAT"
STATUS_NO_OP = "NO_OP"
STATUS_BLOCKED = "BLOCKED"
GUELTIGE_STATUS = (STATUS_KANDIDAT, STATUS_NO_OP, STATUS_BLOCKED)

ROLLE_KANDIDAT = "kandidat"
ROLLE_HINTERLEGT = "hinterlegt"
ROLLE_GESPERRT = "gesperrt"
ROLLE_BEOBACHTET = "beobachtet"
NICHT_PLANBARE_ROLLEN = (ROLLE_HINTERLEGT, ROLLE_GESPERRT, ROLLE_BEOBACHTET)

# R4: keine Fallback-Archivierung, solange diese Tasks offen sind.
FALLBACK_ARCHIV_GESPERRT_WEGEN = ("#1340", "#1341")


@dataclass(frozen=True)
class Kandidat:
    """Read-only snapshot row of the Rueckfluss candidate register."""

    name: str
    prio: int                     # register priority number P (lower = earlier)
    score: int                    # register Sigma value
    pin: str                      # pin hash, or "" if not pinned
    rolle: str = ROLLE_KANDIDAT
    sperr_vermerk: str = ""       # lock/owner-work reference, e.g. "#1341"
    gates_rot: Tuple[str, ...] = ()
    offene_gegenproben: Tuple[str, ...] = ()
    drift_ist: str = ""
    drift_erwartet: str = ""
    datenvertrag_vorhanden: Optional[bool] = None   # None: register silent
    transfertests_gruen: Optional[bool] = None      # None: not affirmed
    pin_unklar: bool = False
    belege: Tuple[str, ...] = ()


@dataclass(frozen=True)
class PlanErgebnis:
    """Exactly one result object per ``plane()`` call (Ausgabevertrag)."""

    status: str                   # KANDIDAT | NO_OP | BLOCKED
    kandidat: Optional[str]       # name iff status == KANDIDAT
    begruendung: str              # exactly one sentence, ends with "."
    belege: Tuple[str, ...] = ()
    datum: Optional[str] = None   # caller-supplied label, never read from OS
    register_quelle: str = REGISTER_SOURCE
    register_stand: str = REGISTER_SNAPSHOT

    def __post_init__(self) -> None:
        if self.status not in GUELTIGE_STATUS:
            raise ValueError(f"unbekannter status: {self.status!r}")
        if not self.begruendung.endswith(".") or self.begruendung.count(".") != 1:
            raise ValueError("begruendung muss genau ein Satz sein")
        if self.status == STATUS_KANDIDAT and not self.kandidat:
            raise ValueError("status KANDIDAT braucht einen kandidat-Namen")
        if self.status != STATUS_KANDIDAT and self.kandidat is not None:
            raise ValueError("status NO_OP/BLOCKED erwartet kandidat=None")


def disqualifiziere(kandidat: Kandidat) -> List[str]:
    """Return all disqualification reasons the register records.

    Categories (register sections 4/5): gesperrt/hinterlegt/beobachtet
    role, lock/owner work (sperr_vermerk), drift, missing data contract,
    red gates, open Gegenproben, unclear pin, and R1 (affirmed absence of
    green transfer tests). Unknown facts never add a reason.
    """
    gruende: List[str] = []
    if kandidat.rolle == ROLLE_GESPERRT:
        suffix = f":{kandidat.sperr_vermerk}" if kandidat.sperr_vermerk else ""
        gruende.append(f"rolle_gesperrt{suffix}")
    elif kandidat.rolle in (ROLLE_HINTERLEGT, ROLLE_BEOBACHTET):
        gruende.append(f"rolle_{kandidat.rolle}")
    if kandidat.drift_ist or kandidat.drift_erwartet:
        gruende.append(f"drift:{kandidat.drift_ist}!={kandidat.drift_erwartet}")
    if kandidat.datenvertrag_vorhanden is False:
        gruende.append("datenvertrag_fehlt")
    for gate in kandidat.gates_rot:
        gruende.append(f"gate_rot:{gate}")
    for probe in kandidat.offene_gegenproben:
        gruende.append(f"gegenprobe_offen:{probe}")
    if kandidat.pin_unklar:
        gruende.append("pin_unklar")
    if kandidat.transfertests_gruen is False:
        gruende.append("R1:keine_gruenen_transfertests")
    return gruende


# --- Read-only register snapshot (Zwischenstand 2026-09-28) -----------------
KANDIDATEN: Tuple[Kandidat, ...] = (
    Kandidat(
        name="ellmos-scheduler",
        prio=1, score=26, pin="296b6f5",
        transfertests_gruen=True,
        offene_gegenproben=(
            "windows-gegenprobe stufe 2",
            "windows-gegenprobe stufe 3",
            "windows-gegenprobe stufe 5",
            "windows-gegenprobe stufe 7",
        ),
        belege=(
            "register: P1 sigma=26 pin=296b6f5",
            "register: Voraussetzung Gegenprobe-Stichtag (section 7) offen",
        ),
    ),
    Kandidat(
        name="memoryhooker",
        prio=2, score=25, pin="94611c25",
        datenvertrag_vorhanden=True,
        transfertests_gruen=True,
        belege=(
            "register: P2 'keine weiteren' Voraussetzungen",
            "register: Stufe 6 abgeschlossen, 51 Waechter-Tests",
            "register: Seam + Rollback vorhanden",
        ),
    ),
    Kandidat(
        name="ellmos-tests",
        prio=3, score=24, pin="",
        transfertests_gruen=True,
        pin_unklar=True,
        belege=(
            "register: P3 checkout-basiert",
            "register: Pin-/Checkout-Frage unklar",
        ),
    ),
    Kandidat(
        name="workflowhooker",
        prio=4, score=23, pin="",
        transfertests_gruen=True,
        offene_gegenproben=("multi-host-gegenprobe",),
        belege=("register: P4 Multi-Host-Gegenprobe offen",),
    ),
    Kandidat(
        name="sqlite-transit-sync",
        prio=5, score=22, pin="",
        rolle=ROLLE_HINTERLEGT,
        datenvertrag_vorhanden=False,
        transfertests_gruen=False,
        offene_gegenproben=("multi-host-nachlauf",),
        belege=(
            "register: P5 Datenvertrag DBSyncManager verifizieren",
            "register: Multi-Host-Nachlauf offen",
        ),
    ),
    Kandidat(
        name="assistant-core",
        prio=6, score=20, pin="",
        rolle=ROLLE_GESPERRT,
        sperr_vermerk="#1341",
        belege=("register: gesperrt, Vermerk #1341 (Ownerarbeit)",),
    ),
    Kandidat(
        name="ellmos-agent_registry",
        prio=7, score=18, pin="",
        rolle=ROLLE_GESPERRT,
        sperr_vermerk="neuevaluierung",
        datenvertrag_vorhanden=False,
        belege=("register: Neuevaluierung, keine Ist-Daten",),
    ),
    Kandidat(
        name="accounts-core",
        prio=8, score=15, pin="",
        rolle=ROLLE_GESPERRT,
        drift_ist="0166805",
        drift_erwartet="9e0d0e9",
        belege=("register: Drift 0166805 vs 9e0d0e9",),
    ),
    Kandidat(
        name="agent-launcher",
        prio=9, score=12, pin="",
        rolle=ROLLE_BEOBACHTET,
        transfertests_gruen=False,
        gates_rot=("OC-B",),
        belege=(
            "register: beobachtet (Nebenfluss)",
            "register: OC-B nicht gruen, nur isolierte Tests, kein Lifecycle",
        ),
    ),
)


def plane(
    kandidaten: Iterable[Kandidat] = KANDIDATEN,
    heute_bereits_umgeschaltet: bool = False,
    datum: Optional[str] = None,
) -> PlanErgebnis:
    """Plan exactly one switch candidate, read-only and side-effect free.

    Returns exactly one ``PlanErgebnis``: KANDIDAT with the highest-prio
    undisqualified candidate that has affirmed green transfer tests (R1),
    NO_OP when the daily limit R2 was already used, or BLOCKED with one
    sentence naming the reason (R3 allows NO_OP/BLOCKED outcomes).
    R4 (no fallback archival) and R5 (no submission/push) are invariants
    of this planner and are attested in the ``belege``.
    """
    if heute_bereits_umgeschaltet:
        return PlanErgebnis(
            status=STATUS_NO_OP,
            kandidat=None,
            begruendung=(
                "Heute wurde bereits ein Kandidat umgeschaltet, daher greift "
                "das Tageslimit R2 und es wird kein weiterer Kandidat geplant."
            ),
            belege=("register R2: max 1 Kandidat pro Tag",),
            datum=datum,
        )

    liste = tuple(kandidaten)
    frei: List[Kandidat] = []
    blockiert: List[str] = []
    for eintrag in liste:
        gruende = disqualifiziere(eintrag)
        if not gruende and eintrag.transfertests_gruen is True:
            frei.append(eintrag)
        else:
            if not gruende:
                gruende = ["R1:transfertests_gruen_nicht_belegt"]
            blockiert.append(f"{eintrag.name} [{'; '.join(gruende)}]")

    if not frei:
        return PlanErgebnis(
            status=STATUS_BLOCKED,
            kandidat=None,
            begruendung=(
                f"Kein planbarer Kandidat, da alle {len(liste)} "
                "Registerkandidaten disqualifiziert oder ohne belegt gruene "
                "Transfertests sind (R1, Details in den Belegen)."
            ),
            belege=tuple(blockiert) or ("kandidatenliste leer",),
            datum=datum,
        )

    frei.sort(key=lambda k: (k.prio, -k.score, k.name))
    wahl = frei[0]
    vorgeschaltet = [k.name for k in liste if k.prio < wahl.prio]
    vorspann = (
        f" nach Disqualifikation der hoeherprioren {', '.join(vorgeschaltet)}"
        if vorgeschaltet else ""
    )
    begruendung = (
        f"Kandidat {wahl.name} mit Register-Prio P{wahl.prio} und Sigma "
        f"{wahl.score} ist frei von Register-Disqualifikationen und hat "
        f"gruene Transfertests (R1){vorspann}."
    )
    belege = (
        wahl.belege
        + (
            f"sigma={wahl.score}",
            f"pin={wahl.pin or 'kein-pin'}",
            "R1: transfertests gruen belegt",
            "R2: tageslimit nicht ausgeschoepft",
            "R4: fallback-archivierung gesperrt "
            f"({'/'.join(FALLBACK_ARCHIV_GESPERRT_WEGEN)} offen)",
            "R5: kein submission, kein push",
            f"quelle={REGISTER_SOURCE} stand={REGISTER_SNAPSHOT}",
        )
        + tuple(f"uebergangen: {eintrag}" for eintrag in blockiert)
    )
    return PlanErgebnis(
        status=STATUS_KANDIDAT,
        kandidat=wahl.name,
        begruendung=begruendung,
        belege=belege,
        datum=datum,
    )
