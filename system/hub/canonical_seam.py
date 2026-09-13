# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Copyright (c) 2026 BACH Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

"""
Identitaetspruefung fuer kanonische Provider-Module
===================================================

Ein Provider-Seam importiert ein Modul beim Namen. Ein Name ist aber kein Beweis:
`import web_scraper` liefert, was gerade unter diesem Namen installiert ist -- nicht
notwendig unser Modul.

Das ist kein theoretischer Fall. Der Name `web-scraper` gehoert auf PyPI seit
2018-08-10 einem fremden Paket (`web_scraper` 1.0, Vahid Vaezian), das denselben
Import-Namen belegt. BACH hat es bis 611c1a1 selbst angefordert
(`requirements-optional.txt`, `web-scraper>=0.1.1`). Die Aufloesung ist seitdem auf
eine gepinnte Git-Quelle umgestellt -- aber das schuetzt nur NEUE Installationen.
Wer das Fremdpaket frueher gezogen hat, traegt es weiter in seiner Umgebung, und
dort importiert der Seam nach wie vor ein fremdes `web_scraper`.

Diese Pruefung schliesst die Luecke zur Laufzeit. Sie folgt demselben Vertrag wie
die Seams selbst (ellmos-homebase-mcp/MODE-CONTRACT.md):

    canonical + Ziel nicht das erwartete  =>  klarer Fehler.
    NIEMALS stiller Rueckfall auf den Altpfad.

Zwei Signale, bewusst unterschiedlich streng:

  1. DIE SCHNITTSTELLE -- verbindlich. Gibt es das erwartete Objekt, nimmt es die
     Parameter an, auf die der Seam sich verlaesst, und hat es die erwarteten
     Operationen? Das ist das Signal, das zaehlt, denn es beschreibt genau das, was
     der Seam gleich benutzt. Es funktioniert unabhaengig davon, WIE das Modul in den
     Pfad kam (pip, editable install, PYTHONPATH-Klon, Vendor-Kopie).

  2. DIE PAKET-HERKUNFT -- nur als Gegenbeweis. Wenn eine Distribution unter dem
     erwarteten Namen existiert UND URLs deklariert UND keine davon auf unser Repo
     zeigt, ist das ein positiver Treffer auf ein Fremdpaket. Fehlen die URLs (oder
     fehlt die Distribution ganz), wird daraus KEIN Fehler: ein Klon auf dem
     PYTHONPATH hat keine Metadaten, und `doc-services` 0.1.0 deklariert keine URLs.
     Aus einer fehlenden Angabe einen Fremdpaket-Verdacht zu machen hiesse, legitime
     Aufbauten zu brechen -- fail-closed heisst laut scheitern, wenn etwas WIRKLICH
     falsch ist, nicht bei jeder Unschaerfe.

Die Fehlermeldung nennt immer beides: was gefunden wurde und wie man es geradezieht.
"""

import importlib
import inspect
from collections import namedtuple

try:  # Python 3.8+
    from importlib import metadata as _metadata
except ImportError:  # pragma: no cover - aeltere Interpreter
    _metadata = None


CanonicalSeam = namedtuple(
    "CanonicalSeam",
    (
        "module",          # Import-Name, z. B. "web_scraper"
        "attribute",       # was der Seam daraus holt, z. B. "WebScraper"
        "distribution",    # Paketname, z. B. "web-scraper"
        "repo_url",        # erwartete Herkunft, z. B. "github.com/ellmos-ai/web-scraper"
        "params",          # Parameter, auf die der Seam sich verlaesst
        "operations",      # Methoden/Attribute, die vorhanden sein muessen
        "env_var",         # Schalter, der den kanonischen Modus waehlt
        "canonical_value",
        "bundled_value",
        "error",           # Ausnahmeklasse dieses Seams
    ),
)


def _missing_params(target, names):
    """Welche der `names` nimmt `target` NICHT als Parameter an?

    Nicht introspizierbare Ziele (C-Extensions) und solche mit **kwargs gelten als
    in Ordnung -- lieber eine Pruefung auslassen als eine falsche Anschuldigung.
    """
    if not names:
        return ()
    try:
        parameters = inspect.signature(target).parameters
    except (TypeError, ValueError):
        return ()
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
        return ()
    return tuple(n for n in names if n not in parameters)


def _declared_urls(distribution_name):
    """URLs, die die installierte Distribution angibt -- leer, wenn sie keine nennt."""
    if _metadata is None:
        return ()
    try:
        meta = _metadata.metadata(distribution_name)
    except Exception:  # noqa: BLE001 - keine Distribution ist kein Fehler, siehe Modulkopf
        return ()
    urls = []
    for key in ("Home-page", "Project-URL"):
        try:
            values = meta.get_all(key) or []
        except Exception:  # noqa: BLE001 - defensive: aeltere Metadata-Backends
            values = []
        urls.extend(v for v in values if v)
    return tuple(urls)


def _points_elsewhere(seam):
    """Nennt die installierte Distribution eine Herkunft, und ist es nicht unsere?

    Nur ein Gegenbeweis: keine Distribution oder keine URLs heisst NICHT "fremd".
    """
    urls = _declared_urls(seam.distribution)
    # Gross-/Kleinschreibung ignorieren: Hosts sind case-insensitive, und eine
    # Distribution darf `https://GitHub.com/ellmos-ai/...` schreiben, ohne deshalb
    # als fremd zu gelten (Hinweis aus dem Zweitmodell-Review zu PR #43).
    erwartet = seam.repo_url.lower()
    return bool(urls) and not any(erwartet in url.lower() for url in urls)


def _foreign_package_hint(seam):
    """Was der Nutzer tun soll, wenn ein fremdes Paket den Namen belegt."""
    return (
        f"Vermutlich ist ein FREMDES Paket unter dem Namen '{seam.distribution}' "
        f"installiert, das denselben Import-Namen '{seam.module}' belegt. "
        f"Abhilfe: `pip uninstall -y {seam.distribution}` und danach "
        f"`pip install -r requirements.txt` (BACH bezieht das Modul dort als "
        f"gepinnte Git-Quelle). Ersatzweise {seam.env_var}={seam.bundled_value} "
        f"setzen, dann laeuft der BACH-eigene Pfad."
    )


def require_canonical(seam):
    """Importiert `seam.attribute` aus `seam.module` und belegt, dass es unseres ist.

    Rueckgabe: das gepruefte Objekt. Bei jeder Abweichung wird `seam.error`
    ausgeloest -- es gibt bewusst keinen Rueckgabewert, der "geht nicht" bedeutet.
    """
    try:
        module = importlib.import_module(seam.module)
    except Exception as exc:  # noqa: BLE001 - jeder Ladefehler ist "Engine nicht da"
        # Auch hier lohnt der Blick in die Metadaten: ein fremdes Paket kann schon beim
        # Import scheitern, weil es eigene Abhaengigkeiten zieht, die wir nicht haben.
        # Gemessen am echten Fall: `web_scraper` 1.0 importiert `requests` und `bs4`
        # auf Modulebene -- ohne die beiden gibt es einen ModuleNotFoundError, und ohne
        # diesen Zusatz laege die Diagnose auf "Modul fehlt" statt auf "falsches Modul".
        nachsatz = ""
        if _points_elsewhere(seam):
            nachsatz = " " + _foreign_package_hint(seam)
        raise seam.error(
            f"{seam.env_var}={seam.canonical_value} verlangt das Modul "
            f"'{seam.distribution}', das aber nicht ladbar ist "
            f"({type(exc).__name__}: {exc}). "
            f"Es findet KEIN Rueckfall auf den BACH-eigenen Pfad statt. Entweder das "
            f"Modul bereitstellen (`pip install -r requirements.txt`) oder "
            f"{seam.env_var}={seam.bundled_value} setzen." + nachsatz
        ) from exc

    try:
        target = getattr(module, seam.attribute)
    except AttributeError as exc:
        raise seam.error(
            f"{seam.env_var}={seam.canonical_value} verlangt das Modul "
            f"'{seam.distribution}', aber das importierte '{seam.module}' "
            f"(aus {getattr(module, '__file__', 'unbekannt')}) hat kein "
            f"'{seam.attribute}'. Es findet KEIN Rueckfall auf den BACH-eigenen Pfad "
            f"statt. " + _foreign_package_hint(seam)
        ) from exc

    missing_ops = tuple(n for n in seam.operations if not hasattr(target, n))
    missing_params = _missing_params(target, seam.params)
    if missing_ops or missing_params:
        fehlt = []
        if missing_ops:
            fehlt.append("Operationen " + ", ".join(missing_ops))
        if missing_params:
            fehlt.append("Parameter " + ", ".join(missing_params))
        raise seam.error(
            f"{seam.env_var}={seam.canonical_value} verlangt das Modul "
            f"'{seam.distribution}', aber '{seam.module}.{seam.attribute}' "
            f"(aus {getattr(module, '__file__', 'unbekannt')}) hat nicht die "
            f"erwartete Schnittstelle: es fehlen " + " und ".join(fehlt) + ". "
            f"Es findet KEIN Rueckfall auf den BACH-eigenen Pfad statt. "
            + _foreign_package_hint(seam)
        )

    if _points_elsewhere(seam):
        urls = _declared_urls(seam.distribution)
        raise seam.error(
            f"{seam.env_var}={seam.canonical_value} verlangt das Modul "
            f"'{seam.distribution}' aus {seam.repo_url}, aber die installierte "
            f"Distribution nennt eine andere Herkunft: " + "; ".join(urls) + ". "
            f"Es findet KEIN Rueckfall auf den BACH-eigenen Pfad statt. "
            + _foreign_package_hint(seam)
        )

    return target
