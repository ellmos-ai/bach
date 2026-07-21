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
WebScrapeHandler - Browser-Steuerung (ersetzt Playwright MCP)
==============================================================
bach web-scrape get <url>           HTTP GET, Body zurückgeben
bach web-scrape links <url>         Alle Links einer Seite
bach web-scrape forms <url>         Formular-Felder erkennen
bach web-scrape screenshot <url>    Screenshot (braucht selenium)
bach web-scrape headers <url>       Response-Headers anzeigen

Task: 996
"""
import os
import re
import sys
import socket
import ipaddress
from pathlib import Path
from urllib.parse import urljoin, urlparse
from typing import List, Tuple
from .base import BaseHandler

os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr:
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


class WebScrapeHandler(BaseHandler):
    MAX_REDIRECTS = 5
    MAX_RESPONSE_BYTES = 5 * 1024 * 1024
    REQUEST_TIMEOUT = 20

    def __init__(self, base_path_or_app):
        super().__init__(base_path_or_app)
        self.output_dir = self.base_path / "data" / "cache" / "scrape"

    @property
    def profile_name(self) -> str:
        return "web-scrape"

    @property
    def target_file(self) -> Path:
        return self.output_dir

    def get_operations(self) -> dict:
        return {
            "get": "HTTP GET: get <url>",
            "links": "Links extrahieren: links <url>",
            "forms": "Formulare erkennen: forms <url>",
            "screenshot": "Screenshot: screenshot <url> (braucht selenium)",
            "headers": "Response-Headers: headers <url>",
        }

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        if not args and operation in ('get', 'links', 'forms', 'screenshot', 'headers'):
            return False, f"URL fehlt: bach web-scrape {operation} <url>"

        if dry_run:
            return True, f"[DRY-RUN] {operation} {' '.join(args)}"

        if operation == "get":
            return self._get(args[0])
        elif operation == "links":
            return self._links(args[0])
        elif operation == "forms":
            return self._forms(args[0])
        elif operation == "screenshot":
            return self._screenshot(args[0])
        elif operation == "headers":
            return self._headers(args[0])
        else:
            ops = "\n".join(f"  {k}: {v}" for k, v in self.get_operations().items())
            return False, f"Nutzung:\n{ops}"

    def _request(self, url: str):
        """HTTP GET mit gepinntem DNS-Ziel und geprüften Redirects."""
        try:
            import requests
        except ImportError:
            return None, "requests nicht installiert: pip install requests"

        try:
            headers = {'User-Agent': 'Mozilla/5.0 (BACH WebScrape/1.0)'}
            current_url = url
            redirect_count = 0

            while True:
                hostname, addresses, err = self._resolve_public_target(current_url)
                if not addresses:
                    prefix = "Unsicheres Redirect-Ziel: " if redirect_count else ""
                    return None, prefix + err

                parsed = urlparse(current_url)
                target_ip = addresses[0]
                pinned_host = f"[{target_ip}]" if ":" in target_ip else target_ip
                pinned_netloc = pinned_host
                if parsed.port is not None:
                    pinned_netloc += f":{parsed.port}"
                pinned_url = parsed._replace(netloc=pinned_netloc).geturl()

                host_header = f"[{hostname}]" if ":" in hostname else hostname
                if parsed.port is not None:
                    host_header += f":{parsed.port}"
                request_headers = {**headers, "Host": host_header}

                class PinnedHTTPSAdapter(requests.adapters.HTTPAdapter):
                    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
                        pool_kwargs["assert_hostname"] = hostname
                        pool_kwargs["server_hostname"] = hostname
                        return super().init_poolmanager(
                            connections,
                            maxsize,
                            block=block,
                            **pool_kwargs,
                        )

                with requests.Session() as session:
                    # Environment proxies could resolve or reroute the original host elsewhere.
                    session.trust_env = False
                    if parsed.scheme == "https":
                        session.mount("https://", PinnedHTTPSAdapter())

                    resp = session.get(
                        pinned_url,
                        timeout=self.REQUEST_TIMEOUT,
                        headers=request_headers,
                        allow_redirects=False,
                        verify=True,
                        stream=True,
                    )

                    if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
                        if redirect_count >= self.MAX_REDIRECTS:
                            resp.close()
                            return None, f"Zu viele Redirects (>{self.MAX_REDIRECTS})"
                        next_url = resp.headers.get("Location")
                        if not next_url:
                            resp.close()
                            return None, "Redirect ohne Location-Header"
                        current_url = urljoin(current_url, next_url)
                        redirect_count += 1
                        resp.close()
                        continue

                    try:
                        resp.raise_for_status()
                        self._consume_response_body(resp)
                    except Exception:
                        resp.close()
                        raise
                    # Do not expose the internal IP-pinned transport URL to callers.
                    resp.url = current_url
                    return resp, ""
        except Exception as e:
            return None, str(e)

    def _validate_target_url(self, url: str) -> Tuple[bool, str]:
        _hostname, addresses, err = self._resolve_public_target(url)
        return bool(addresses), err

    def _resolve_public_target(self, url: str) -> Tuple[str, List[str], str]:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return "", [], "Nur http/https URLs sind erlaubt"

        if parsed.username is not None or parsed.password is not None:
            return "", [], "Zugangsdaten in URLs sind nicht erlaubt"

        hostname = (parsed.hostname or "").strip().rstrip(".").lower()
        if not hostname:
            return "", [], "URL ohne Hostname"
        try:
            hostname = hostname.encode("idna").decode("ascii")
        except UnicodeError:
            return "", [], "Ungültiger Hostname"
        if hostname in {"localhost"}:
            return "", [], f"Host {hostname} ist nicht erlaubt"

        try:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except ValueError as exc:
            return "", [], f"Ungültiger Port: {exc}"

        try:
            ip = ipaddress.ip_address(hostname)
        except ValueError:
            ip = None

        if ip is not None:
            if not ip.is_global:
                return "", [], f"Host {hostname} zeigt auf ein nicht-öffentliches Ziel"
            return hostname, [str(ip)], ""

        try:
            resolved = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
        except socket.gaierror as exc:
            return "", [], f"Hostname {hostname} konnte nicht aufgelöst werden: {exc}"

        addresses = set()
        for entry in resolved:
            sockaddr = entry[4]
            if not sockaddr:
                continue
            addr = sockaddr[0]
            try:
                resolved_ip = ipaddress.ip_address(addr)
            except ValueError:
                continue
            addresses.add(resolved_ip)

        if not addresses:
            return "", [], f"Hostname {hostname} liefert keine prüfbaren IP-Adressen"

        for resolved_ip in addresses:
            if not resolved_ip.is_global:
                return "", [], (
                    f"Hostname {hostname} zeigt auf ein nicht-öffentliches Ziel ({resolved_ip})"
                )

        return hostname, sorted(str(address) for address in addresses), ""

    def _consume_response_body(self, resp) -> None:
        content_length = resp.headers.get("Content-Length")
        if content_length:
            try:
                if int(content_length) > self.MAX_RESPONSE_BYTES:
                    resp.close()
                    raise ValueError(
                        f"Antwort zu groß ({content_length} Bytes > {self.MAX_RESPONSE_BYTES})"
                    )
            except ValueError:
                if content_length.isdigit():
                    raise

        chunks = []
        total = 0
        for chunk in resp.iter_content(chunk_size=65536):
            if not chunk:
                continue
            total += len(chunk)
            if total > self.MAX_RESPONSE_BYTES:
                resp.close()
                raise ValueError(
                    f"Antwort zu groß ({total} Bytes > {self.MAX_RESPONSE_BYTES})"
                )
            chunks.append(chunk)

        resp._content = b"".join(chunks)
        resp._content_consumed = True

    def _get(self, url: str) -> Tuple[bool, str]:
        """Simple HTTP GET."""
        resp, err = self._request(url)
        if not resp:
            return False, f"Fehler: {err}"

        body = resp.text
        info = f"URL: {resp.url}\nStatus: {resp.status_code}\nContent-Type: {resp.headers.get('content-type', '?')}\nGröße: {len(body)} Zeichen\n{'=' * 40}\n\n"

        if len(body) > 10000:
            return True, info + body[:10000] + f"\n\n... ({len(body) - 10000} weitere Zeichen)"
        return True, info + body

    def _links(self, url: str) -> Tuple[bool, str]:
        """Alle Links einer Seite extrahieren."""
        resp, err = self._request(url)
        if not resp:
            return False, f"Fehler: {err}"

        # Links mit Regex extrahieren
        links = re.findall(r'<a[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', resp.text, re.IGNORECASE | re.DOTALL)

        if not links:
            return True, f"Keine Links auf {url}"

        # Bereinigen
        from urllib.parse import urljoin
        results = []
        seen = set()
        for href, text in links:
            href = urljoin(url, href)
            text = re.sub(r'<[^>]+>', '', text).strip()[:60]
            if href not in seen and not href.startswith(('javascript:', 'mailto:', '#')):
                seen.add(href)
                results.append(f"  {text or '(kein Text)'}\n    {href}")

        header = f"Links auf {url} ({len(results)} gefunden)\n{'=' * 40}\n"
        return True, header + "\n".join(results[:50])

    def _forms(self, url: str) -> Tuple[bool, str]:
        """Formular-Felder erkennen."""
        resp, err = self._request(url)
        if not resp:
            return False, f"Fehler: {err}"

        forms = re.findall(r'<form[^>]*>(.*?)</form>', resp.text, re.DOTALL | re.IGNORECASE)
        if not forms:
            return True, f"Keine Formulare auf {url}"

        results = []
        for i, form_html in enumerate(forms):
            # Action und Method
            action = re.search(r'action=["\']([^"\']*)["\']', form_html, re.IGNORECASE)
            method = re.search(r'method=["\']([^"\']*)["\']', form_html, re.IGNORECASE)

            fields = []
            # Input-Felder
            for inp in re.finditer(r'<input[^>]+>', form_html, re.IGNORECASE):
                tag = inp.group()
                name = re.search(r'name=["\']([^"\']*)["\']', tag)
                itype = re.search(r'type=["\']([^"\']*)["\']', tag)
                fields.append(f"    input[{itype.group(1) if itype else 'text'}] name={name.group(1) if name else '?'}")

            # Textarea
            for ta in re.finditer(r'<textarea[^>]*name=["\']([^"\']*)["\']', form_html, re.IGNORECASE):
                fields.append(f"    textarea name={ta.group(1)}")

            # Select
            for sel in re.finditer(r'<select[^>]*name=["\']([^"\']*)["\']', form_html, re.IGNORECASE):
                fields.append(f"    select name={sel.group(1)}")

            results.append(
                f"  Form #{i + 1}: action={action.group(1) if action else '?'} method={method.group(1) if method else 'GET'}\n"
                + "\n".join(fields)
            )

        header = f"Formulare auf {url} ({len(forms)} gefunden)\n{'=' * 40}\n"
        return True, header + "\n\n".join(results)

    def _screenshot(self, url: str) -> Tuple[bool, str]:
        """Sicher abgerufene Seite ohne weitere Browser-Netzwerkzugriffe rendern."""
        ok, err = self._validate_target_url(url)
        if not ok:
            return False, f"Unsicheres Screenshot-Ziel: {err}"

        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
        except ImportError:
            return False, "selenium nicht installiert: pip install selenium\nFür Screenshots wird ein Browser-Driver benötigt."

        resp, err = self._request(url)
        if not resp:
            return False, f"Fehler: {err}"

        self.output_dir.mkdir(parents=True, exist_ok=True)
        out_file = self.output_dir / f"screenshot_{hash(url) & 0xFFFFFF:06x}.png"

        driver = None
        try:
            options = Options()
            options.add_argument('--headless')
            options.add_argument('--no-sandbox')
            options.add_argument('--window-size=1280,1024')
            options.add_experimental_option(
                "prefs",
                {"profile.managed_default_content_settings.javascript": 2},
            )
            driver = webdriver.Chrome(options=options)
            driver.execute_cdp_cmd("Network.enable", {})
            driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": ["*"]})
            driver.get("about:blank")
            frame_tree = driver.execute_cdp_cmd("Page.getFrameTree", {})
            driver.execute_cdp_cmd(
                "Page.setDocumentContent",
                {"frameId": frame_tree["frameTree"]["frame"]["id"], "html": resp.text},
            )
            driver.save_screenshot(str(out_file))
            return True, f"Screenshot gespeichert: {out_file}"
        except Exception as e:
            return False, f"Screenshot fehlgeschlagen: {e}"
        finally:
            if driver is not None:
                driver.quit()

    def _headers(self, url: str) -> Tuple[bool, str]:
        """Response-Headers anzeigen."""
        resp, err = self._request(url)
        if not resp:
            return False, f"Fehler: {err}"

        lines = [
            f"Headers für {resp.url}",
            f"Status: {resp.status_code}",
            "=" * 40,
        ]
        for k, v in resp.headers.items():
            lines.append(f"  {k}: {v}")

        return True, "\n".join(lines)
