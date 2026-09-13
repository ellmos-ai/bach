# Dritter Review (Zwei-Modell-Review) — Branch feature/T-20260913-896336887-ocean-heart

**Status:** In Bearbeitung (Prüfung P1, P2, P3 und P4 abgeschlossen)  
**Reviewer:** Gemini (Gemini 3.8 Flash) via Antigravity  
**Datum:** 2026-09-13  
**Arbeitsverzeichnis:** `C:\_Local_DEV\repos\BACH-heart2`

---

## P1: Prüfung clutch-Dateien und prompt_library.py Typen

### Behauptung / Soll:
- `C:\_Local_DEV\repos\clutch\clutch\fahrer.py` und `getriebe.py` existieren.
- `C:\_Local_DEV\repos\clutch\clutch\prompt_library.py` Zeile 20 enthält die Typen `"rolle"` und `"agent"`.

### Befund / Ist:
- **`fahrer.py`:** Existiert (`C:\_Local_DEV\repos\clutch\clutch\fahrer.py`, 463 Zeilen, 19.016 Bytes).
- **`getriebe.py`:** Existiert (`C:\_Local_DEV\repos\clutch\clutch\getriebe.py`, 353 Zeilen, 14.036 Bytes).
- **`prompt_library.py` Zeile 20:**
  ```python
  _ERLAUBTE_TYPEN = {"prompt", "skill", "workflow", "rolle", "agent"}
  ```
  Enthält exakt die Typen `"rolle"` und `"agent"`.

### Ergebnis P1:
**BESTÄTIGT (Soll == Ist)**.

---

## P2: Prüfung _validate_local_endpoint in ellmos-core config.py

### Behauptung / Soll:
- In `C:\_Local_DEV\repos\ellmos-core\src\ellmos_core\config.py`, Funktion `_validate_local_endpoint` (ab ca. Zeile 117):
- Behauptet wird: Erlaubt Loopback, private, link-lokale UND Tailscale `100.64.0.0/10`.

### Befund / Ist:
Code in `ellmos_core/config.py` Zeilen 117–146:
```python
def _validate_local_endpoint(endpoint: str) -> None:
    """Reject public Ollama endpoints when the installation is local-only."""
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RuntimeError("ELLMOS_CORE_OLLAMA_HOST muss eine http(s)-URL mit Host sein.")

    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost"):
        return
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            addresses = {
                ipaddress.ip_address(item[4][0])
                for item in socket.getaddrinfo(host, parsed.port or 80, type=socket.SOCK_STREAM)
            }
        except (OSError, ValueError) as exc:
            raise RuntimeError(
                f"Lokaler Ollama-Host '{host}' ist nicht als lokales Ziel auflösbar."
            ) from exc

    tailscale_range = ipaddress.ip_network("100.64.0.0/10")
    if not addresses or any(
        not (ip.is_private or ip.is_loopback or ip.is_link_local or ip in tailscale_range)
        for ip in addresses
    ):
        raise RuntimeError(
            f"Nur lokale Modelle erlaubt, aber ELLMOS_CORE_OLLAMA_HOST zeigt auf '{host}'."
        )
```

**Was erlaubt die Funktion?**
- URLs mit Schema `http` oder `https` und vorhandenem Hostnamen.
- Hostnamen `localhost` oder solche, die auf `.localhost` enden.
- IP-Adressen (direkt oder via DNS-Auflösung), wenn **jede** aufgelöste IP zu mindestens einer der folgenden Kategorien gehört:
  1. `ip.is_loopback` (Loopback, z. B. `127.0.0.0/8`, `::1`)
  2. `ip.is_private` (Private Netze nach RFC 1918 / RFC 4193, z. B. `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`)
  3. `ip.is_link_local` (Link-lokale Netze, z. B. `169.254.0.0/16`, `fe80::/10`)
  4. `tailscale_range = ipaddress.ip_network("100.64.0.0/10")` (CGNAT / Tailscale-Range)

**Was verbietet die Funktion?**
- Nicht-`http(s)`-Schemata oder URLs ohne Hostnamen.
- Hostnamen, die sich nicht auflösen lassen (`socket.gaierror` / `OSError`).
- Öffentliche / externe IP-Adressen (sobald mindestens eine aufgelöste IP nicht privat, Loopback, link-lokal oder im Tailscale-Bereich liegt).
- Leere Adressmengen.

### Ergebnis P2:
**BESTÄTIGT (Soll == Ist)**. Die Behauptung ist exakt zutreffend.

---

## P3: Prüfung System-Inventardateien und "network"-Block

### Behauptung / Soll:
- In `C:\Users\User\OneDrive\.SYNC\_inventory\systems\`: Vier Dateien mit Größen zwischen 14 KB und 143 KB.
- `mac-studio.json` ist die kleinste Datei.
- Der Block `"network"` steht NICHT in allen vier Dateien.

### Befund / Ist:
Dateigrößen der vier primären System-Dateien:
1. `mac-studio.json`: **14.471 Bytes** (~14,1 KB) — **kleinste Datei**
2. `surface.json`: **44.344 Bytes** (~43,3 KB)
3. `laptop.json`: **81.332 Bytes** (~79,4 KB)
4. `workstation.json`: **143.391 Bytes** (~140,0 KB) — **größte Datei**

Spanne: exakt 14 KB bis 143 KB; `mac-studio.json` ist eindeutig die kleinste.

Vorhandensein des Top-Level-Blocks `"network"`:
- `mac-studio.json`: **VORHANDEN** (Zeilen 439–460, enthält u. a. `tailscale_ip`, `ports`, `ports_offen`).
- `surface.json`: **NICHT VORHANDEN**.
- `laptop.json`: **NICHT VORHANDEN**.
- `workstation.json`: **NICHT VORHANDEN** (Netzwerkangaben nur sporadisch als `reachable_via` im `system`-Objekt).

Der Block `"network"` steht somit nur in 1 von 4 Dateien und **NICHT** in allen vieren.

### Ergebnis P3:
**BESTÄTIGT (Soll == Ist)**.

---

## P4: Prüfung fackel.py und Funktion frei()

### Behauptung / Soll:
- In `C:\_Local_DEV\repos\BACH-heart2\system\hub\_services\fackel.py`, Funktion `frei()`:
- Behauptet wird: Gibt bei nicht messbarer Kapazität `float(FACKELN)` zurück, also volle zehn Fackeln (fail-open).

### Befund / Ist:
Code in `fackel.py` Zeilen 36, 181–196:
```python
#: Zehn, ueberall. Siehe Modul-Docstring.
FACKELN = 10
...
def fackel_bytes() -> int:
    """Groesse einer Fackel; 0 heisst: hier ist nichts messbar."""
    return kapazitaet_bytes() // FACKELN


def frei(fuer_modell: str = "") -> float:
    """Freie Fackeln.

    Mit ``fuer_modell`` aus Sicht dieses Bewerbers - sein eigenes, bereits
    geladenes Modell belegt ihn nicht. Nicht messbar (kein Ollama, kein
    Metal) ergibt volle Freiheit statt Blockade: Die harte Grenze zieht
    Ollama selbst, wir entscheiden nur, wer fragen darf.
    """
    f = fackel_bytes()
    if not f:
        return float(FACKELN)
    ...
```
Wenn die Kapazität nicht messbar ist (weder gesetzte Umgebungsvariable, noch sysctl, noch Metal, noch laufende Modelle in Ollama), ergibt `kapazitaet_bytes()` 0, womit `fackel_bytes()` ebenfalls 0 zurückgibt. In diesem Fall (`if not f:`) gibt `frei()` exakt `float(FACKELN)` (also `10.0`, volle zehn Fackeln) zurück. Auch `passt()` winkt bei `not fackel_bytes()` mit `return True` direkt durch. Das Verhalten ist explizit als fail-open implementiert und dokumentiert ("volle Freiheit statt Blockade").

### Ergebnis P4:
**BESTÄTIGT (Soll == Ist)**.
