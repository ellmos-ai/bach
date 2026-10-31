"""BACH-Task 2179: Prueft, dass die Gemini-CLI am Google-Konto angemeldet ist.

Akzeptanz (Task #2179): `gemini -p "Antworte nur mit OK"` gibt OK aus.

Wichtig: Der Aufruf laeuft bewusst gegen das ECHTE Benutzer-HOME
(pwd-Eintrag des aktuellen Users) und nicht gegen das ggf. umgeleitete
HOME des Worker-Sandbox. Sonst schlaegt die Pruefung auch nach einem
erfolgreichen Login im GUI-Terminal faelschlich fehl, weil die CLI ihre
Credentials unter $HOME/.gemini sucht.
"""
import os
import pwd
import subprocess


def _txt(x):
    if x is None:
        return ""
    if isinstance(x, bytes):
        return x.decode("utf-8", "replace")
    return x


def _real_home():
    """Echtes Benutzer-HOME, unabhaengig von einer HOME-Umleitung im Sandbox."""
    try:
        return pwd.getpwuid(os.getuid()).pw_dir
    except Exception:
        return os.path.expanduser("~")


def _env():
    env = os.environ.copy()
    env["HOME"] = _real_home()
    env["NO_BROWSER"] = "true"
    return env


AUTH_HINT = (
    "Gemini ist NICHT angemeldet. Der Google-OAuth-Login ist interaktiv und "
    "kann nur vom Benutzer durchgefuehrt werden:\n"
    "  1) Im GUI-Terminal auf dem Mac (oder per SSH) `gemini` starten\n"
    "  2) Google-Konto im Browser autorisieren\n"
    "  3) Gemini beenden (/quit) und diesen Test erneut ausfuehren\n"
    "Nach erfolgreichem Login existiert eine der Dateien\n"
    "  $HOME/.gemini/oauth_creds.json  oder  $HOME/.gemini/settings.json\n"
)


def test_gemini_cli_ok_login():
    env = _env()
    home = env["HOME"]

    # 1) CLI erreichbar (Version, kein Login noetig)
    try:
        v = subprocess.run(
            ["gemini", "--version"], capture_output=True, text=True,
            timeout=30, env=env,
        )
    except FileNotFoundError:
        assert False, "gemini CLI nicht im PATH installiert (erwartet: @google/gemini-cli)."
    except subprocess.TimeoutExpired as e:
        assert False, (
            "gemini --version hing 30s ohne Antwort.\nOUT:\n"
            + _txt(e.stdout) + "\nERR:\n" + _txt(e.stderr)
        )
    assert v.returncode == 0, (
        f"gemini --version rc={v.returncode}\nOUT:\n{_txt(v.stdout)}\nERR:\n{_txt(v.stderr)}"
    )
    version = (_txt(v.stdout) + _txt(v.stderr)).strip()

    # 2) Auth-Status im echten HOME explizit melden (Diagnose, kein Secret-Inhalt)
    auth_files = [
        os.path.join(home, ".gemini", "oauth_creds.json"),
        os.path.join(home, ".gemini", "settings.json"),
        os.path.join(home, ".gemini", "google_accounts.json"),
    ]
    present = [p for p in auth_files if os.path.exists(p)]

    # 3) Akzeptanzkriterium: Ping gegen das Google-Konto
    try:
        p = subprocess.run(
            ["gemini", "-p", "Antworte nur mit OK"], capture_output=True, text=True,
            timeout=90, env=env,
        )
    except subprocess.TimeoutExpired as e:
        assert False, (
            "gemini -p hing 90s ohne Antwort (vermutlich noch offener OAuth-Login).\n"
            f"HOME={home}  vorhandene Auth-Dateien={present}\n"
            "--STDOUT--\n" + _txt(e.stdout) + "\n--STDERR--\n" + _txt(e.stderr)
        )

    out = (_txt(p.stdout) + "\n" + _txt(p.stderr)).strip()
    if p.returncode != 0:
        assert False, (
            f"gemini -p rc={p.returncode}\n"
            f"gemini-Version: {version or 'unbekannt'}\n"
            f"HOME={home}  vorhandene Auth-Dateien={present}\n"
            f"AUSGABE:\n{out}\n\n{AUTH_HINT}"
        )
    assert "OK" in out, f"Erwartet 'OK', bekam: {out!r}"
