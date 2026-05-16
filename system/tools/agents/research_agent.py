#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Research Agent v2.0.0

Wissenschaftliche Recherche und Literaturanalyse.
Integriert PubMed (NCBI E-Utilities) und Perplexity API.

Usage:
  python research_agent.py search "query"
  python research_agent.py search "query" --max-results 5
  python research_agent.py review --topic "topic" --years 5
  python research_agent.py status
"""

import json
import os
import sys
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass

from portable_base import PortableAgent, BACH_ROOT, BACH_AVAILABLE

SCRIPT_DIR = Path(__file__).parent

# Output: BACH data dir wenn vorhanden, sonst ~/.bach/research/
if BACH_AVAILABLE and (BACH_ROOT / "system" / "data").exists():
    OUTPUT_DIR = BACH_ROOT / "system" / "data" / "research"
else:
    OUTPUT_DIR = Path.home() / ".bach" / "research"
CACHE_DIR = SCRIPT_DIR / "cache"

# NCBI E-Utilities endpoints
PUBMED_SEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_FETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

# Perplexity API
PERPLEXITY_API_URL = "https://api.perplexity.ai/chat/completions"

HTTP_TIMEOUT = 15


class ResearchAgent(PortableAgent):
    """Forschungs-Agent fuer wissenschaftliche Recherche"""

    AGENT_NAME = "ResearchAgent"
    VERSION = "2.0.0"

    def __init__(self, config_path: str = None):
        super().__init__(config_path)
        self._ensure_dirs()
        self.history = self._load_history()

    def _ensure_dirs(self):
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _load_history(self) -> List[Dict]:
        history_file = CACHE_DIR / "search_history.json"
        if history_file.exists():
            try:
                with open(history_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                return []
        return []

    def _save_history(self):
        history_file = CACHE_DIR / "search_history.json"
        with open(history_file, 'w', encoding='utf-8') as f:
            json.dump(self.history[-100:], f, indent=2, ensure_ascii=False)

    # --- PubMed API ---

    def _fetch_pubmed(self, query: str, max_results: int = 10) -> List[Dict]:
        """Sucht PubMed via NCBI E-Utilities und gibt strukturierte Ergebnisse zurueck."""
        # Schritt 1: PMIDs suchen via esearch
        params = urllib.parse.urlencode({
            "db": "pubmed",
            "term": query,
            "retmax": str(max_results),
            "retmode": "xml",
            "sort": "relevance",
        })
        search_url = f"{PUBMED_SEARCH_URL}?{params}"

        try:
            req = urllib.request.Request(search_url, headers={"User-Agent": "BACH-ResearchAgent/2.0"})
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                search_xml = resp.read().decode("utf-8")
        except Exception as e:
            self.logger.warning(f"PubMed search fehlgeschlagen: {e}")
            return []

        root = ET.fromstring(search_xml)
        id_list = root.find("IdList")
        if id_list is None:
            return []
        pmids = [id_el.text for id_el in id_list.findall("Id") if id_el.text]
        if not pmids:
            return []

        # Schritt 2: Details abrufen via efetch
        fetch_params = urllib.parse.urlencode({
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
            "rettype": "abstract",
        })
        fetch_url = f"{PUBMED_FETCH_URL}?{fetch_params}"

        try:
            req = urllib.request.Request(fetch_url, headers={"User-Agent": "BACH-ResearchAgent/2.0"})
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                fetch_xml = resp.read().decode("utf-8")
        except Exception as e:
            self.logger.warning(f"PubMed fetch fehlgeschlagen: {e}")
            return []

        return self._parse_pubmed_articles(fetch_xml)

    def _parse_pubmed_articles(self, xml_data: str) -> List[Dict]:
        """Parst PubMed efetch XML zu strukturierten Artikeldaten."""
        results = []
        try:
            root = ET.fromstring(xml_data)
        except ET.ParseError:
            return []

        for article_el in root.findall(".//PubmedArticle"):
            medline = article_el.find("MedlineCitation")
            if medline is None:
                continue

            pmid_el = medline.find("PMID")
            pmid = pmid_el.text if pmid_el is not None else ""

            art = medline.find("Article")
            if art is None:
                continue

            # Titel
            title_el = art.find("ArticleTitle")
            title = title_el.text if title_el is not None else "Kein Titel"

            # Abstract
            abstract_parts = []
            abstract_el = art.find("Abstract")
            if abstract_el is not None:
                for text_el in abstract_el.findall("AbstractText"):
                    label = text_el.get("Label", "")
                    text = "".join(text_el.itertext())
                    if label:
                        abstract_parts.append(f"{label}: {text}")
                    else:
                        abstract_parts.append(text)
            abstract = " ".join(abstract_parts)

            # Autoren
            authors = []
            author_list = art.find("AuthorList")
            if author_list is not None:
                for author_el in author_list.findall("Author"):
                    last = author_el.find("LastName")
                    init = author_el.find("Initials")
                    if last is not None:
                        name = last.text
                        if init is not None:
                            name += f" {init.text}"
                        authors.append(name)

            # Jahr
            year = ""
            pub_date = art.find(".//PubDate")
            if pub_date is not None:
                year_el = pub_date.find("Year")
                if year_el is not None:
                    year = year_el.text

            # Journal
            journal = ""
            journal_el = art.find("Journal/Title")
            if journal_el is not None:
                journal = journal_el.text

            results.append({
                "pmid": pmid,
                "title": title,
                "authors": authors,
                "year": year,
                "journal": journal,
                "abstract": abstract[:500] if len(abstract) > 500 else abstract,
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            })

        return results

    # --- Perplexity API ---

    def _get_perplexity_key(self) -> Optional[str]:
        """Holt Perplexity API Key aus Env-Variable oder BACH Secrets."""
        key = os.environ.get("PERPLEXITY_API_KEY")
        if key:
            return key
        if BACH_AVAILABLE and self._bach.connected:
            try:
                cfg = self._bach.load_config("secrets")
                return cfg.get("perplexity_api_key")
            except Exception:
                pass
        return None

    def _fetch_perplexity(self, query: str) -> Optional[Dict]:
        """Fragt Perplexity API ab. Gibt None zurueck wenn kein Key vorhanden."""
        api_key = self._get_perplexity_key()
        if not api_key:
            self.logger.info("Perplexity: Kein API-Key, ueberspringe")
            return None

        payload = json.dumps({
            "model": "sonar",
            "messages": [
                {"role": "user", "content": query}
            ],
        }).encode("utf-8")

        req = urllib.request.Request(
            PERPLEXITY_API_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "BACH-ResearchAgent/2.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            choices = data.get("choices", [])
            content = choices[0]["message"]["content"] if choices else ""
            return {
                "source": "perplexity",
                "response": content,
                "model": data.get("model", "sonar"),
            }
        except Exception as e:
            self.logger.warning(f"Perplexity-Abfrage fehlgeschlagen: {e}")
            return None

    # --- Ergebnis-Speicherung ---

    def _save_results(self, query: str, results: Dict):
        """Speichert Recherche-Ergebnisse als JSON."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_query = "".join(c if c.isalnum() or c in " _-" else "" for c in query)[:40].strip()
        filename = f"{ts}_{safe_query.replace(' ', '_')}.json"
        out_path = OUTPUT_DIR / filename

        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        self.logger.info(f"Ergebnisse gespeichert: {out_path}")
        return str(out_path)

    # --- Haupt-Suchmethode ---

    def search(self, query: str, sources: List[str] = None,
               max_results: int = 10) -> Dict:
        """Fuehrt Recherche ueber konfigurierte Quellen durch."""
        sources = sources or ["pubmed", "perplexity"]

        result = {
            "query": query,
            "timestamp": datetime.now().isoformat(),
            "sources_requested": sources,
            "pubmed": [],
            "perplexity": None,
            "total_results": 0,
            "saved_to": None,
        }

        # PubMed
        if "pubmed" in sources:
            self.logger.info(f"PubMed-Suche: '{query}' (max {max_results})")
            articles = self._fetch_pubmed(query, max_results)
            result["pubmed"] = articles
            result["total_results"] += len(articles)

        # Perplexity (optional)
        if "perplexity" in sources:
            pplx = self._fetch_perplexity(query)
            if pplx:
                result["perplexity"] = pplx
                result["total_results"] += 1

        # Ergebnisse speichern
        if result["total_results"] > 0:
            result["saved_to"] = self._save_results(query, result)

        # History
        self.history.append({
            "query": query,
            "timestamp": result["timestamp"],
            "sources": sources,
            "pubmed_count": len(result["pubmed"]),
            "perplexity": result["perplexity"] is not None,
        })
        self._save_history()

        return result

    def create_review_plan(self, topic: str, years: int = 5) -> Dict:
        """Erstellt Literatur-Review Plan"""
        plan = {
            "topic": topic,
            "timeframe": f"Letzte {years} Jahre",
            "created": datetime.now().isoformat(),
            "steps": [
                {
                    "phase": "1. Ueberblick",
                    "tool": "Perplexity",
                    "action": f"Suche: '{topic}' fuer Kontext",
                    "time": "5 min"
                },
                {
                    "phase": "2. Systematische Suche",
                    "tool": "PubMed",
                    "action": "Strukturierte Datenbanksuche",
                    "time": "15 min"
                },
                {
                    "phase": "3. Screening",
                    "tool": "NotebookLM",
                    "action": "Abstracts filtern und clustern",
                    "time": "10 min"
                },
                {
                    "phase": "4. Volltext-Analyse",
                    "tool": "Claude/Gemini",
                    "action": "Schluesselpaper analysieren",
                    "time": "20 min"
                },
                {
                    "phase": "5. Synthese",
                    "tool": "Claude",
                    "action": "Zusammenfassung und Gaps",
                    "time": "10 min"
                }
            ],
            "output_dir": str(OUTPUT_DIR),
        }
        return plan

    def get_status(self) -> Dict:
        """Agent-Status"""
        pplx_available = self._get_perplexity_key() is not None
        return {
            "agent": "Research Agent",
            "version": self.VERSION,
            "status": "active",
            "bach_available": self.bach_available,
            "searches_total": len(self.history),
            "last_search": self.history[-1] if self.history else None,
            "apis": {
                "pubmed": True,
                "perplexity": pplx_available,
            },
            "output_dir": str(OUTPUT_DIR),
            "cache_dir": str(CACHE_DIR),
        }

    # --- PortableAgent Interface ---

    def run(self, **kwargs) -> Any:
        """Hauptfunktion: Recherche durchfuehren."""
        query = kwargs.get("query", "")
        if query:
            return self.search(
                query,
                kwargs.get("sources"),
                kwargs.get("max_results", 10),
            )
        return self.get_status()

    def status(self) -> Dict:
        return self.get_status()

    def config(self) -> Dict:
        return self._config

    def standalone_config_template(self) -> Dict:
        return {
            "agent": self.AGENT_NAME,
            "version": self.VERSION,
            "output_dir": str(OUTPUT_DIR),
            "cache_dir": str(CACHE_DIR),
            "default_sources": ["pubmed", "perplexity"],
            "pubmed_max_results": 10,
        }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Research Agent v2.0.0")
    parser.add_argument("command", choices=["search", "review", "status"])
    parser.add_argument("query", nargs="?")
    parser.add_argument("--topic", help="Review-Thema")
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--max-results", type=int, default=10)
    args = parser.parse_args()

    agent = ResearchAgent()

    if args.command == "search" and args.query:
        result = agent.search(args.query, max_results=args.max_results)
        print(f"\nRECHERCHE: {args.query}")
        print("=" * 60)

        # PubMed-Ergebnisse
        articles = result.get("pubmed", [])
        if articles:
            print(f"\n  PubMed: {len(articles)} Artikel gefunden\n")
            for i, art in enumerate(articles, 1):
                authors_str = ", ".join(art["authors"][:3])
                if len(art["authors"]) > 3:
                    authors_str += " et al."
                print(f"  [{i}] {art['title']}")
                print(f"      {authors_str} ({art['year']})")
                print(f"      {art['journal']}")
                print(f"      {art['url']}")
                if art["abstract"]:
                    preview = art["abstract"][:150]
                    print(f"      {preview}...")
                print()
        else:
            print("\n  PubMed: Keine Ergebnisse\n")

        # Perplexity
        pplx = result.get("perplexity")
        if pplx:
            print(f"  Perplexity ({pplx['model']}):")
            print(f"    {pplx['response'][:300]}")
            print()

        if result.get("saved_to"):
            print(f"  Gespeichert: {result['saved_to']}")

    elif args.command == "review":
        topic = args.topic or args.query or "Thema"
        plan = agent.create_review_plan(topic, args.years)
        print(f"\nREVIEW-PLAN: {topic}")
        print("=" * 60)
        for step in plan["steps"]:
            print(f"\n  {step['phase']}")
            print(f"     Tool: {step['tool']}")
            print(f"     Zeit: {step['time']}")

    elif args.command == "status":
        st = agent.get_status()
        print(f"\nRESEARCH AGENT STATUS")
        print("=" * 60)
        print(f"  Version:    {st['version']}")
        print(f"  BACH:       {'ja' if st['bach_available'] else 'nein'}")
        print(f"  Suchen:     {st['searches_total']}")
        print(f"  PubMed:     {'verfuegbar' if st['apis']['pubmed'] else 'nein'}")
        print(f"  Perplexity: {'verfuegbar' if st['apis']['perplexity'] else 'kein Key'}")
        print(f"  Output:     {st['output_dir']}")


if __name__ == "__main__":
    main()
