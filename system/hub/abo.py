# SPDX-License-Identifier: MIT
"""
Abo Handler - Abonnement-Verwaltung (Expert Agent)
==================================================

bach abo scan              Analysiert Steuer-Posten, erkennt Abos
bach abo list              Zeigt alle erkannten Abos
bach abo confirm ID        Bestaetigt Abo-Erkennung
bach abo dismiss ID        Entfernt Fehlererkennung
bach abo costs             Monatliche Kostenaufstellung
bach abo export            Export fuer Haushaltsplanung
bach abo patterns          Bekannte Abo-Muster anzeigen
"""
import sys
import json
import sqlite3
from pathlib import Path
from datetime import datetime
from .base import BaseHandler


class AboHandler(BaseHandler):
    """Handler fuer Abo-Operationen (Expert Agent)"""

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.data_dir = base_path / "data"
        self.user_db = self._canonical_db  # Unified DB seit v1.1.84
        self.patterns_file = base_path / "tools" / "abo" / "abo_patterns.json"
        self.username = "user"  # Default

    @property
    def profile_name(self) -> str:
        return "abo"

    @property
    def target_file(self) -> Path:
        return self.data_dir

    def get_operations(self) -> dict:
        return {
            "scan": "Steuer-Posten analysieren, Abos erkennen",
            "list": "Alle erkannten Abos anzeigen",
            "confirm": "Abo-Erkennung bestaetigen (confirm ID)",
            "dismiss": "Fehlererkennung entfernen (dismiss ID)",
            "costs": "Monatliche Kostenaufstellung",
            "export": "Export fuer Haushaltsplanung",
            "patterns": "Bekannte Abo-Muster anzeigen",
            "init": "Datenbank-Tabellen initialisieren",
            "sync-mail": "Abonnements aus E-Mails synchronisieren"
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if operation == "help":
            return self._show_help()
        elif operation == "init":
            return self._init_db(dry_run)
        elif operation == "scan":
            return self._scan(args, dry_run)
        elif operation == "list":
            return self._list_abos(args)
        elif operation == "confirm":
            return self._confirm(args, dry_run)
        elif operation == "dismiss":
            return self._dismiss(args, dry_run)
        elif operation == "costs":
            return self._costs(args)
        elif operation == "export":
            return self._export(args)
        elif operation == "patterns":
            return self._show_patterns()
        elif operation == "sync-mail":
            return self._sync_mail(args, dry_run)
        else:
            return (False, f"Unbekannte Operation: {operation}\nVerfuegbar: {', '.join(self.get_operations().keys())}")

    def _show_help(self) -> tuple:
        """Zeigt Hilfe an."""
        lines = [
            "=== ABOSERVICE - Abonnement-Verwaltung ===",
            "",
            "Befehle:",
            "  bach abo init           Datenbank initialisieren",
            "  bach abo scan           Steuer-Posten analysieren",
            "  bach abo list           Erkannte Abos anzeigen",
            "  bach abo confirm ID     Abo bestaetigen",
            "  bach abo dismiss ID     Fehlererkennung entfernen",
            "  bach abo costs          Kostenaufstellung",
            "  bach abo export         Export als CSV",
            "  bach abo patterns       Bekannte Muster anzeigen",
            "  bach abo sync-mail      Abos aus E-Mails synchronisieren",
            "",
            "Optionen:",
            "  --jahr YYYY    Steuerjahr (default: aktuelles Jahr)",
            "  --dry-run      Nur simulieren"
        ]
        return (True, "\n".join(lines))

    def _init_db(self, dry_run: bool) -> tuple:
        """Initialisiert Datenbank-Tabellen fuer Aboservice."""
        if dry_run:
            return (True, "[DRY-RUN] Wuerde Abo-Tabellen erstellen")

        try:
            conn = sqlite3.connect(self.user_db)
            try:
                cursor = conn.cursor()

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS abo_subscriptions (
                        id INTEGER PRIMARY KEY,
                        name TEXT NOT NULL,
                        anbieter TEXT NOT NULL,
                        kategorie TEXT,
                        betrag_monatlich REAL,
                        zahlungsintervall TEXT DEFAULT 'monatlich',
                        kuendigungslink TEXT,
                        erkannt_am TEXT,
                        bestaetigt INTEGER DEFAULT 0,
                        aktiv INTEGER DEFAULT 1,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT
                    )
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS abo_payments (
                        id INTEGER PRIMARY KEY,
                        subscription_id INTEGER REFERENCES abo_subscriptions(id),
                        posten_id INTEGER,
                        betrag REAL,
                        datum TEXT,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS abo_patterns (
                        id INTEGER PRIMARY KEY,
                        pattern TEXT NOT NULL,
                        anbieter TEXT NOT NULL,
                        kategorie TEXT,
                        kuendigungslink TEXT,
                        dist_type INTEGER DEFAULT 2
                    )
                """)

                cursor.execute("CREATE INDEX IF NOT EXISTS idx_abo_subs_anbieter ON abo_subscriptions(anbieter)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_abo_subs_aktiv ON abo_subscriptions(aktiv)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_abo_payments_sub ON abo_payments(subscription_id)")

                conn.commit()
            finally:
                conn.close()

            self._load_default_patterns()

            return (True, "[OK] Abo-Tabellen initialisiert")

        except Exception as e:
            return (False, f"[ERROR] DB-Init fehlgeschlagen: {e}")

    def _load_default_patterns(self):
        """Laedt Standard-Abo-Patterns in die Datenbank."""
        patterns = [
            ("netflix", "Netflix", "Streaming", "https:/netflix.com/cancelplan"),
            ("spotify", "Spotify", "Musik", "https:/spotify.com/account"),
            ("microsoft 365", "Microsoft 365", "Software", "https:/account.microsoft.com/services"),
            ("adobe", "Adobe", "Software", "https:/account.adobe.com"),
            ("amazon prime", "Amazon Prime", "Shopping", "https:/amazon.de/prime"),
            ("disney+", "Disney+", "Streaming", "https:/disneyplus.com/account"),
            ("disney plus", "Disney+", "Streaming", "https:/disneyplus.com/account"),
            ("apple", "Apple", "Service", "https:/appleid.apple.com"),
            ("icloud", "Apple iCloud", "Cloud", "https:/appleid.apple.com"),
            ("youtube premium", "YouTube Premium", "Streaming", "https:/youtube.com/paid_memberships"),
            ("dropbox", "Dropbox", "Cloud", "https:/dropbox.com/account"),
            ("google one", "Google One", "Cloud", "https:/one.google.com"),
            ("chatgpt", "OpenAI", "KI", "https:/platform.openai.com/account"),
            ("anthropic", "Anthropic", "KI", "https:/console.anthropic.com"),
            ("claude", "Anthropic", "KI", "https:/console.anthropic.com"),
            ("github", "GitHub", "Entwicklung", "https:/github.com/settings/billing"),
            ("jetbrains", "JetBrains", "Entwicklung", "https:/account.jetbrains.com"),
            ("1password", "1Password", "Sicherheit", "https:/my.1password.com/profile"),
            ("lastpass", "LastPass", "Sicherheit", "https:/lastpass.com/acctindex.php"),
            ("nordvpn", "NordVPN", "VPN", "https:/my.nordaccount.com"),
            ("expressvpn", "ExpressVPN", "VPN", "https:/expressvpn.com/subscriptions"),
        ]

        try:
            conn = sqlite3.connect(self.user_db)
            try:
                cursor = conn.cursor()

                for pattern, anbieter, kategorie, link in patterns:
                    cursor.execute("""
                        INSERT OR IGNORE INTO abo_patterns (pattern, anbieter, kategorie, kuendigungslink, dist_type)
                        VALUES (?, ?, ?, ?, 2)
                    """, (pattern, anbieter, kategorie, link))

                conn.commit()
            finally:
                conn.close()
        except (sqlite3.Error, OSError):
            pass

    def _scan(self, args: list, dry_run: bool) -> tuple:
        """Scannt Steuer-Posten nach Abos."""
        # Jahr extrahieren
        steuerjahr = datetime.now().year
        for i, arg in enumerate(args):
            if arg == "--jahr" and i + 1 < len(args):
                steuerjahr = int(args[i + 1])

        try:
            # Importiere Scanner
            sys.path.insert(0, str(self.base_path / "tools" / "abo"))
            from abo_scanner import AboScanner

            scanner = AboScanner(self.user_db)
            result = scanner.scan(self.username, steuerjahr, dry_run=dry_run)

            output = [
                f"=== ABO-SCAN Steuerjahr {steuerjahr} ===",
                "",
                f"Analysierte Posten:    {result.get('posten_analysiert', 0)}",
                f"Erkannte Abos:         {result.get('abos_erkannt', 0)}",
                f"Neue Abos:             {result.get('abos_neu', 0)}",
                f"Aktualisierte Abos:    {result.get('abos_aktualisiert', 0)}",
                "",
            ]

            if result.get('erkennungen'):
                output.append("--- Erkennungen ---")
                for e in result['erkennungen'][:10]:
                    status = "[NEU]" if e.get('neu') else "[UPD]"
                    output.append(f"  {status} {e['anbieter']}: {e['anzahl']}x, ~{e['durchschnitt']:.2f} EUR/Zahlung")

            if dry_run:
                output.insert(0, "[DRY-RUN]")

            return (True, "\n".join(output))

        except ImportError:
            return (False, "[ERROR] abo_scanner.py nicht gefunden. Fuehre erst 'bach abo init' aus.")
        except Exception as e:
            return (False, f"[ERROR] Scan fehlgeschlagen: {e}")

    def _list_abos(self, args: list) -> tuple:
        """Listet alle erkannten Abos."""
        try:
            conn = sqlite3.connect(self.user_db)
            try:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                nur_aktiv = "--alle" not in args
                nur_bestaetigt = "--bestaetigt" in args

                query = "SELECT * FROM abo_subscriptions WHERE 1=1"
                if nur_aktiv:
                    query += " AND aktiv = 1"
                if nur_bestaetigt:
                    query += " AND bestaetigt = 1"
                query += " ORDER BY betrag_monatlich DESC"

                cursor.execute(query)
                abos = cursor.fetchall()
            finally:
                conn.close()

            if not abos:
                return (True, "Keine Abos gefunden.\n\nFuehre 'bach abo scan' aus um Abos zu erkennen.")

            # Summen berechnen
            summe_monatlich = sum(a['betrag_monatlich'] or 0 for a in abos)
            summe_jaehrlich = summe_monatlich * 12

            output = [
                "=== ABOSERVICE - Erkannte Abonnements ===",
                "",
                f"Monatliche Kosten:  {summe_monatlich:,.2f} EUR",
                f"Jaehrliche Kosten:  {summe_jaehrlich:,.2f} EUR",
                "",
                "-" * 70,
                f"{'ID':<4} | {'Anbieter':<20} | {'Kategorie':<12} | {'Betrag':>10} | {'Status':<10}",
                "-" * 70,
            ]

            for a in abos:
                status = "Bestaetigt" if a['bestaetigt'] else "Erkannt"
                betrag = f"{a['betrag_monatlich']:,.2f}/Mo" if a['betrag_monatlich'] else "-"
                output.append(
                    f"{a['id']:<4} | {a['anbieter'][:20]:<20} | {(a['kategorie'] or '-')[:12]:<12} | {betrag:>10} | {status:<10}"
                )

            output.extend([
                "-" * 70,
                "",
                "Befehle: bach abo confirm ID | bach abo dismiss ID | bach abo costs"
            ])

            return (True, "\n".join(output))

        except sqlite3.OperationalError:
            return (False, "[ERROR] Abo-Tabellen nicht gefunden. Fuehre 'bach abo init' aus.")
        except Exception as e:
            return (False, f"[ERROR] {e}")

    def _confirm(self, args: list, dry_run: bool) -> tuple:
        """Bestaetigt eine Abo-Erkennung."""
        if not args:
            return (False, "Fehler: ID angeben. Beispiel: bach abo confirm 1")

        try:
            abo_id = int(args[0])
        except ValueError:
            return (False, f"Fehler: '{args[0]}' ist keine gueltige ID")

        if dry_run:
            return (True, f"[DRY-RUN] Wuerde Abo {abo_id} bestaetigen")

        try:
            conn = sqlite3.connect(self.user_db)
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE abo_subscriptions SET bestaetigt = 1, updated_at = ? WHERE id = ?",
                    (datetime.now().isoformat(), abo_id)
                )
                if cursor.rowcount == 0:
                    return (False, f"[ERROR] Abo {abo_id} nicht gefunden")
                conn.commit()
                return (True, f"[OK] Abo {abo_id} bestaetigt")
            finally:
                conn.close()
        except Exception as e:
            return (False, f"[ERROR] {e}")

    def _dismiss(self, args: list, dry_run: bool) -> tuple:
        """Entfernt eine Fehlererkennung."""
        if not args:
            return (False, "Fehler: ID angeben. Beispiel: bach abo dismiss 1")

        try:
            abo_id = int(args[0])
        except ValueError:
            return (False, f"Fehler: '{args[0]}' ist keine gueltige ID")

        if dry_run:
            return (True, f"[DRY-RUN] Wuerde Abo {abo_id} deaktivieren")

        try:
            conn = sqlite3.connect(self.user_db)
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE abo_subscriptions SET aktiv = 0, updated_at = ? WHERE id = ?",
                    (datetime.now().isoformat(), abo_id)
                )
                if cursor.rowcount == 0:
                    return (False, f"[ERROR] Abo {abo_id} nicht gefunden")
                conn.commit()
                return (True, f"[OK] Abo {abo_id} deaktiviert (Fehlererkennung)")
            finally:
                conn.close()
        except Exception as e:
            return (False, f"[ERROR] {e}")

    def _costs(self, args: list) -> tuple:
        """Zeigt Kostenaufstellung nach Kategorie."""
        try:
            conn = sqlite3.connect(self.user_db)
            try:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT kategorie,
                           COUNT(*) as anzahl,
                           SUM(betrag_monatlich) as summe
                    FROM abo_subscriptions
                    WHERE aktiv = 1
                    GROUP BY kategorie
                    ORDER BY summe DESC
                """)
                kategorien = cursor.fetchall()

                cursor.execute("SELECT SUM(betrag_monatlich) as total FROM abo_subscriptions WHERE aktiv = 1")
                total = cursor.fetchone()['total'] or 0
            finally:
                conn.close()

            output = [
                "=== ABO-KOSTEN nach Kategorie ===",
                "",
                f"{'Kategorie':<20} | {'Anzahl':>6} | {'Monatlich':>12} | {'Jaehrlich':>12}",
                "-" * 60,
            ]

            for k in kategorien:
                kat = k['kategorie'] or 'Sonstige'
                monatlich = k['summe'] or 0
                jaehrlich = monatlich * 12
                output.append(
                    f"{kat:<20} | {k['anzahl']:>6} | {monatlich:>10,.2f} EUR | {jaehrlich:>10,.2f} EUR"
                )

            output.extend([
                "-" * 60,
                f"{'GESAMT':<20} | {'':<6} | {total:>10,.2f} EUR | {total * 12:>10,.2f} EUR",
                "",
                f"Das sind {total * 12 / 12:.2f} EUR pro Monat bzw. {total * 12:.2f} EUR pro Jahr."
            ])

            return (True, "\n".join(output))

        except sqlite3.OperationalError:
            return (False, "[ERROR] Abo-Tabellen nicht gefunden. Fuehre 'bach abo init' aus.")
        except Exception as e:
            return (False, f"[ERROR] {e}")

    def _export(self, args: list) -> tuple:
        """Exportiert Abos als CSV."""
        try:
            conn = sqlite3.connect(self.user_db)
            try:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT anbieter, kategorie, betrag_monatlich, zahlungsintervall, kuendigungslink, bestaetigt
                    FROM abo_subscriptions
                    WHERE aktiv = 1
                    ORDER BY kategorie, anbieter
                """)
                abos = cursor.fetchall()
            finally:
                conn.close()

            if not abos:
                return (True, "Keine Abos zum Exportieren.")

            # CSV erstellen
            csv_path = self.data_dir / "abo_export.csv"
            with open(csv_path, 'w', encoding='utf-8') as f:
                f.write("Anbieter;Kategorie;Betrag_Monatlich;Intervall;Kuendigungslink;Bestaetigt\n")
                for a in abos:
                    f.write(f"{a['anbieter']};{a['kategorie'] or ''};{a['betrag_monatlich'] or 0:.2f};{a['zahlungsintervall'] or ''};{a['kuendigungslink'] or ''};{'Ja' if a['bestaetigt'] else 'Nein'}\n")

            return (True, f"[OK] Export erstellt: {csv_path}")

        except Exception as e:
            return (False, f"[ERROR] {e}")

    def _sync_mail(self, args: list, dry_run: bool) -> tuple:
        """Synchronisiert Abos aus dem Mail-Service."""
        try:
            # Importiere Sync-Service
            from ._services.mail.mail_abo_sync_service import MailAboSyncService

            service = MailAboSyncService(self.user_db)
            result = service.run_sync(dry_run=dry_run)

            output = [
                "=== MAIL-ABO SYNC ===",
                "",
                f"Gefundene Mail-Abos:    {result['mail_subscriptions_found']}",
                f"Synchronisiert:         {result['synced']}",
                f"Übersprungen (Dup):     {result['skipped']}",
            ]

            if result['errors']:
                output.append("\nFehler:")
                for err in result['errors']:
                    output.append(f"  - {err}")

            if dry_run:
                output.insert(0, "[DRY-RUN]")

            return (True, "\n".join(output))

        except ImportError as e:
            return (False, f"[ERROR] Sync-Service nicht gefunden: {e}")
        except Exception as e:
            return (False, f"[ERROR] Synchronisation fehlgeschlagen: {e}")

    def _show_patterns(self) -> tuple:
        """Zeigt bekannte Abo-Patterns."""
        try:
            conn = sqlite3.connect(self.user_db)
            try:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                cursor.execute("SELECT * FROM abo_patterns ORDER BY kategorie, anbieter")
                patterns = cursor.fetchall()
            finally:
                conn.close()

            if not patterns:
                return (True, "Keine Patterns definiert.\n\nFuehre 'bach abo init' aus.")

            output = [
                "=== BEKANNTE ABO-PATTERNS ===",
                "",
                f"{'Pattern':<20} | {'Anbieter':<20} | {'Kategorie':<12}",
                "-" * 60,
            ]

            for p in patterns:
                output.append(
                    f"{p['pattern'][:20]:<20} | {p['anbieter'][:20]:<20} | {(p['kategorie'] or '-')[:12]:<12}"
                )

            output.extend([
                "-" * 60,
                f"Gesamt: {len(patterns)} Patterns"
            ])

            return (True, "\n".join(output))

        except sqlite3.OperationalError:
            return (False, "[ERROR] Abo-Tabellen nicht gefunden. Fuehre 'bach abo init' aus.")
        except Exception as e:
            return (False, f"[ERROR] {e}")
