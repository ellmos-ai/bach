#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""githubbot-hold: Bei gruenem module-gate nur BOT-EIGENE Gate-Labels entfernen, manuelle Holds erhalten.

Entscheidung (siehe decide()):
  * ``module-gate-fehler`` wird bei gruenem Gate gezielt entfernt (der Marker ist dann veraltet).
  * ``HOLD`` wird nur entfernt, wenn ``HOLD`` zusammen mit ``module-gate-fehler`` vorhanden ist UND das letzte
    ``labeled``/``unlabeled``-Ereignis fuer ``HOLD`` nach vollstaendigem Issue-Events-Readback ein ``labeled`` von
    ``github-actions[bot]`` (Typ Bot) ist. Menschliche, andere oder unklare Herkunft bleibt erhalten.
  * Fehlende, fehlerhafte oder unvollstaendige API-/Ereignisdaten: nichts aendern (fail-closed).

Aufruf im Workflow: Umgebung GITHUB_TOKEN, GITHUB_REPOSITORY, PR_NUMBER.
Trockenlauf ohne Netz: ``--labels-json <datei> --events-json <datei>`` (synthetische Daten); es wird nichts geaendert.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BOT_LOGIN = "github-actions[bot]"
BOT_TYPE = "Bot"
HOLD = "HOLD"
MARKER = "module-gate-fehler"
API = "https://api.github.com"
PER_PAGE = 100
MAX_PAGES = 30


class ApiError(Exception):
    """Lesefehler oder unvollstaendige Daten: Aufrufer behandelt das fail-closed."""


def _same_label(name, wanted):
    return isinstance(name, str) and name.casefold() == wanted.casefold()


def hold_owner(events):
    """Akteur des LETZTEN HOLD-Ereignisses, wenn es ein ``labeled`` ist; sonst None (unklar)."""
    relevant = [e for e in events
                if isinstance(e, dict) and e.get("event") in ("labeled", "unlabeled")
                and isinstance(e.get("label"), dict) and _same_label(e["label"].get("name"), HOLD)]
    if not relevant:
        return None
    last = sorted(relevant, key=lambda e: (str(e.get("created_at") or ""), int(e.get("id") or 0)))[-1]
    if last.get("event") != "labeled":
        return None
    actor = last.get("actor")
    if not isinstance(actor, dict) or not actor.get("login"):
        return None
    return actor


def decide(labels, events):
    """Reine Entscheidung. labels/events = None bedeutet unlesbar oder unvollstaendig.

    Rueckgabe: {"remove": [Labelnamen], "reason": Text}. Alles, was nicht ausdruecklich entfernt wird, bleibt erhalten.
    """
    if labels is None:
        return {"remove": [], "reason": "Labels nicht lesbar: nichts geaendert"}
    names = {str(n) for n in labels}
    has_hold = any(_same_label(n, HOLD) for n in names)
    has_marker = any(_same_label(n, MARKER) for n in names)
    marker = next((n for n in names if _same_label(n, MARKER)), MARKER)
    hold = next((n for n in names if _same_label(n, HOLD)), HOLD)
    if not has_hold:
        if has_marker:
            return {"remove": [marker], "reason": "kein HOLD vorhanden; veralteten Marker entfernt"}
        return {"remove": [], "reason": "keine Gate-Labels vorhanden"}
    if not has_marker:
        return {"remove": [], "reason": "HOLD ohne Bot-Marker: Herkunft nicht als Bot belegt, HOLD erhalten"}
    if events is None:
        return {"remove": [], "reason": "Issue-Events nicht vollstaendig lesbar: nichts geaendert (fail-closed)"}
    actor = hold_owner(events)
    if actor is not None and actor.get("login") == BOT_LOGIN and actor.get("type") == BOT_TYPE:
        return {"remove": [hold, marker], "reason": "letztes HOLD-labeled stammt von github-actions[bot]: HOLD und Marker entfernt"}
    who = "unklar" if actor is None else f"{actor.get('login')}"
    return {"remove": [marker], "reason": f"HOLD-Herkunft nicht der Workflow-Bot ({who}): HOLD erhalten, veralteten Marker entfernt"}


def _request(method, path, token):
    request = urllib.request.Request(API + path, method=method, headers={
        "Authorization": f"token {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
            return response.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise ApiError(type(exc).__name__) from None


def _pages(api, path, token):
    """Liest ALLE Seiten oder wirft ApiError (kein Teilergebnis)."""
    items = []
    for page in range(1, MAX_PAGES + 1):
        status, data = api("GET", f"{path}?per_page={PER_PAGE}&page={page}", token)
        if status != 200 or not isinstance(data, list):
            raise ApiError(f"HTTP {status}")
        items.extend(data)
        if len(data) < PER_PAGE:
            return items
    raise ApiError("zu viele Seiten: Readback unvollstaendig")


def read_labels(api, repo, number, token):
    try:
        return [item["name"] for item in _pages(api, f"/repos/{repo}/issues/{number}/labels", token)]
    except (ApiError, KeyError, TypeError):
        return None


def read_events(api, repo, number, token):
    try:
        return _pages(api, f"/repos/{repo}/issues/{number}/events", token)
    except ApiError:
        return None


def run(api, repo, number, token, dry_run=False, log=print):
    labels = read_labels(api, repo, number, token)
    events = None
    if labels is not None and any(_same_label(n, HOLD) for n in labels) and any(_same_label(n, MARKER) for n in labels):
        events = read_events(api, repo, number, token)
    decision = decide(labels, events)
    log(f"HOLD-Entscheidung: {decision['reason']}")
    for label in decision["remove"]:
        if dry_run:
            log(f"Trockenlauf: wuerde Label '{label}' entfernen")
            continue
        status, _ = api("DELETE", f"/repos/{repo}/issues/{number}/labels/{urllib.parse.quote(label, safe='')}", token)
        if status in (200, 204, 404):
            log(f"Label '{label}' entfernt" if status != 404 else f"Label '{label}' war bereits entfernt")
        else:
            log(f"WARNUNG: Label '{label}' konnte nicht entfernt werden (HTTP {status}); Fork-PR mit lesendem Token?")
    return decision


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--labels-json", help="Trockenlauf: JSON-Liste von Labelnamen (kein Netz, keine Aenderung)")
    parser.add_argument("--events-json", help="Trockenlauf: JSON-Liste von Issue-Events (kein Netz, keine Aenderung)")
    args = parser.parse_args(argv)
    if args.labels_json or args.events_json:
        labels = json.load(open(args.labels_json, encoding="utf-8")) if args.labels_json else None
        events = json.load(open(args.events_json, encoding="utf-8")) if args.events_json else None
        decision = decide(labels, events)
        print(json.dumps(decision, ensure_ascii=False))
        return 0
    token, repo, number = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY"), os.environ.get("PR_NUMBER")
    if not (token and repo and number and number.isdigit()):
        print("HOLD-Entscheidung: Umgebung unvollstaendig: nichts geaendert (fail-closed)")
        return 0
    run(_request, repo, int(number), token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
