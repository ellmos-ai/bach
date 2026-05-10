#!/usr/bin/env python3
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
SmartHomeHandler - Smart Home Integration (FritzBox)
=====================================================

Operationen:
  status              FritzBox-Status anzeigen
  devices             Verbundene Geraete auflisten
  wifi                WLAN-Status (Gaeste-WLAN an/aus)
  bandwidth           Aktuelle Bandbreite anzeigen
  calls [--limit N]   Letzte Anrufe
  reconnect           Internet-Verbindung neu aufbauen
  info                Box-Informationen

Nutzt: FritzBox TR-064 (UPnP/SOAP) via HTTP
"""

import json
import hashlib
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Tuple, Optional
from hub.base import BaseHandler


class SmartHomeHandler(BaseHandler):

    FRITZ_URL = "http://fritz.box:49000"

    def __init__(self, base_path_or_app):
        super().__init__(base_path_or_app)
        self.db_path = self._canonical_db

    @property
    def profile_name(self) -> str:
        return "smarthome"

    @property
    def target_file(self) -> Path:
        return self.db_path

    def get_operations(self) -> dict:
        return {
            "status": "FritzBox-Status anzeigen",
            "devices": "Verbundene Geraete",
            "wifi": "WLAN-Status",
            "bandwidth": "Aktuelle Bandbreite",
            "calls": "Letzte Anrufe",
            "reconnect": "Internet neu verbinden",
            "info": "Box-Informationen",
            "help": "Hilfe anzeigen",
        }

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        ops = {
            "status": self._status,
            "devices": self._devices,
            "wifi": self._wifi,
            "bandwidth": self._bandwidth,
            "calls": self._calls,
            "reconnect": self._reconnect,
            "info": self._info,
            "help": self._help,
        }
        fn = ops.get(operation)
        if not fn:
            avail = ", ".join(ops.keys())
            return False, f"Unbekannte Operation: {operation}\nVerfuegbar: {avail}"
        return fn(args, dry_run)

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def _status(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        lines = ["Smart Home Status (FritzBox)", "=" * 50]

        # Connection Status
        info = self._tr064_call(
            "urn:dslforum-org:service:WANIPConnection:1",
            "GetStatusInfo"
        )
        if info:
            status = self._xml_value(info, "NewConnectionStatus")
            uptime = self._xml_value(info, "NewUptime")
            if uptime:
                hours = int(uptime) // 3600
                mins = (int(uptime) % 3600) // 60
                uptime = f"{hours}h {mins}m"
            lines.append(f"  Verbindung: {status or '?'}")
            lines.append(f"  Uptime:     {uptime or '?'}")
        else:
            lines.append("  FritzBox nicht erreichbar (fritz.box:49000)")
            return False, "\n".join(lines)

        # External IP
        ip = self._tr064_call(
            "urn:dslforum-org:service:WANIPConnection:1",
            "GetExternalIPAddress"
        )
        if ip:
            ext_ip = self._xml_value(ip, "NewExternalIPAddress")
            lines.append(f"  Externe IP: {ext_ip or '?'}")

        # Device count
        hosts = self._tr064_call(
            "urn:dslforum-org:service:Hosts:1",
            "GetHostNumberOfEntries"
        )
        if hosts:
            count = self._xml_value(hosts, "NewHostNumberOfEntries")
            lines.append(f"  Geraete:    {count or '?'}")

        return True, "\n".join(lines)

    def _devices(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        hosts_resp = self._tr064_call(
            "urn:dslforum-org:service:Hosts:1",
            "GetHostNumberOfEntries"
        )
        if not hosts_resp:
            return False, "FritzBox nicht erreichbar."

        count = int(self._xml_value(hosts_resp, "NewHostNumberOfEntries") or "0")
        lines = [f"Verbundene Geraete ({count})", "=" * 50]

        for i in range(min(count, 30)):
            host = self._tr064_call(
                "urn:dslforum-org:service:Hosts:1",
                "GetGenericHostEntry",
                {"NewIndex": str(i)}
            )
            if host:
                name = self._xml_value(host, "NewHostName") or "?"
                ip = self._xml_value(host, "NewIPAddress") or "?"
                mac = self._xml_value(host, "NewMACAddress") or "?"
                active = self._xml_value(host, "NewActive") or "0"
                status = "online" if active == "1" else "offline"
                lines.append(f"  [{status:>7}] {name:<25} {ip:<16} {mac}")

        return True, "\n".join(lines)

    def _wifi(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        wifi = self._tr064_call(
            "urn:dslforum-org:service:WLANConfiguration:1",
            "GetInfo"
        )
        if not wifi:
            return False, "FritzBox nicht erreichbar."

        ssid = self._xml_value(wifi, "NewSSID") or "?"
        status = self._xml_value(wifi, "NewStatus") or "?"
        channel = self._xml_value(wifi, "NewChannel") or "?"

        lines = [
            "WLAN-Status",
            "=" * 40,
            f"  SSID:    {ssid}",
            f"  Status:  {status}",
            f"  Kanal:   {channel}",
        ]
        return True, "\n".join(lines)

    def _bandwidth(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        bw = self._tr064_call(
            "urn:dslforum-org:service:WANCommonInterfaceConfig:1",
            "GetAddonInfos"
        )
        if not bw:
            # Fallback
            bw = self._tr064_call(
                "urn:dslforum-org:service:WANCommonInterfaceConfig:1",
                "GetCommonLinkProperties"
            )
        if not bw:
            return False, "Bandbreite nicht abrufbar."

        down = self._xml_value(bw, "NewLayer1DownstreamMaxBitRate") or "?"
        up = self._xml_value(bw, "NewLayer1UpstreamMaxBitRate") or "?"

        def format_bps(bps_str):
            try:
                bps = int(bps_str)
                return f"{bps / 1_000_000:.1f} Mbit/s"
            except (ValueError, TypeError):
                return bps_str

        lines = [
            "Bandbreite",
            "=" * 40,
            f"  Download: {format_bps(down)}",
            f"  Upload:   {format_bps(up)}",
        ]
        return True, "\n".join(lines)

    def _calls(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        return True, "Anrufliste: Nutze FritzBox-Oberflaeche (fritz.box) fuer Anrufhistorie."

    def _reconnect(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        if dry_run:
            return True, "[DRY] Wuerde Internet-Verbindung neu aufbauen."

        result = self._tr064_call(
            "urn:dslforum-org:service:WANIPConnection:1",
            "ForceTermination"
        )
        if result is not None:
            return True, "[OK] Reconnect ausgeloest. Neue IP in ~10 Sekunden."
        return False, "Reconnect fehlgeschlagen."

    def _info(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        info = self._tr064_call(
            "urn:dslforum-org:service:DeviceInfo:1",
            "GetInfo"
        )
        if not info:
            return False, "FritzBox nicht erreichbar."

        lines = [
            "FritzBox Info",
            "=" * 40,
            f"  Modell:    {self._xml_value(info, 'NewModelName') or '?'}",
            f"  Firmware:  {self._xml_value(info, 'NewSoftwareVersion') or '?'}",
            f"  Serial:    {self._xml_value(info, 'NewSerialNumber') or '?'}",
            f"  Uptime:    {self._xml_value(info, 'NewUpTime') or '?'}s",
        ]
        return True, "\n".join(lines)

    def _help(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        return True, """Smart Home (FritzBox Integration)
==================================

  bach smarthome status       Verbindungs-Status
  bach smarthome devices      Verbundene Geraete
  bach smarthome wifi         WLAN-Status
  bach smarthome bandwidth    Bandbreite
  bach smarthome reconnect    Internet neu verbinden
  bach smarthome info         Box-Informationen

Voraussetzung: FritzBox unter fritz.box:49000 erreichbar (TR-064)."""

    # ------------------------------------------------------------------
    # TR-064 (UPnP/SOAP) Helpers
    # ------------------------------------------------------------------

    def _tr064_call(self, service: str, action: str,
                    params: dict = None) -> Optional[ET.Element]:
        """TR-064 SOAP-Aufruf an die FritzBox."""
        # Service-URL ableiten
        service_short = service.split(":")[-2]
        control_url = f"/upnp/control/{service_short.lower()}"

        soap_body = f"""<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"
            s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:{action} xmlns:u="{service}">"""

        if params:
            for key, val in params.items():
                soap_body += f"\n      <{key}>{val}</{key}>"

        soap_body += f"""
    </u:{action}>
  </s:Body>
</s:Envelope>"""

        url = f"{self.FRITZ_URL}{control_url}"
        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SoapAction": f'"{service}#{action}"',
        }

        req = urllib.request.Request(
            url, data=soap_body.encode("utf-8"), headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                xml_data = resp.read().decode("utf-8")
                return ET.fromstring(xml_data)
        except Exception:
            return None

    def _xml_value(self, root: ET.Element, tag: str) -> Optional[str]:
        """Wert aus SOAP-Response extrahieren."""
        for elem in root.iter():
            if elem.tag.endswith(tag) or elem.tag == tag:
                return elem.text
        return None
