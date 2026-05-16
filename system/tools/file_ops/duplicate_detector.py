#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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
Tool: c_duplicate_detector
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version c_duplicate_detector

Description:
    [Beschreibung hinzufügen]

Usage:
    python c_duplicate_detector.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

from typing import List, Dict, Optional, Tuple
from datetime import datetime
import json
from pathlib import Path


class DuplicateDetector:
    """
    Erkennt Duplikate bevor neue Tools erstellt werden.
    
    Features:
    - Similarity-Check (Name, Keywords, Description)
    - Pre-Create Validation
    - Usage-Tracking
    - Gap-Analysis
    """
    
    def __init__(self, registry):
        """
        Args:
            registry: ToolRegistry Instance
        """
        self.registry = registry
        self.usage_log = []
        self.usage_log_path = Path(registry.base) / "system/boot/usage_log.json"
        
        # Lade Usage Log
        self._load_usage_log()
    
    def _load_usage_log(self):
        """Lädt Usage Log falls vorhanden."""
        if self.usage_log_path.exists():
            try:
                with open(self.usage_log_path, 'r', encoding='utf-8') as f:
                    self.usage_log = json.load(f)
            except (json.JSONDecodeError, OSError):
                self.usage_log = []
    
    def _save_usage_log(self):
        """Speichert Usage Log."""
        self.usage_log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.usage_log_path, 'w', encoding='utf-8') as f:
            json.dump(self.usage_log, f, indent=2)
    
    def check_duplicate(self, 
                       tool_name: str,
                       description: str = "",
                       keywords: List[str] = None) -> Dict:
        """
        Prüft ob ähnliches Tool bereits existiert.
        
        Args:
            tool_name: Geplanter Tool-Name
            description: Tool-Beschreibung
            keywords: Funktions-Keywords
        
        Returns:
            Dict mit duplicate_found, similar_tools, recommendation
        """
        keywords = keywords or []
        
        result = {
            'duplicate_found': False,
            'exact_match': None,
            'similar_tools': [],
            'similarity_score': 0.0,
            'recommendation': 'OK to create'
        }
        
        # 1. Exakter Name-Match
        existing = self.registry.get(tool_name)
        if existing:
            result['duplicate_found'] = True
            result['exact_match'] = existing
            result['similarity_score'] = 1.0
            result['recommendation'] = f'STOP - Tool "{tool_name}" already exists!'
            return result
        
        # 2. Similarity-Check
        for tool_id, tool in self.registry.tools.items():
            score = self._calculate_similarity(
                tool_name, description, keywords,
                tool['name'], tool.get('description', ''), tool.get('keywords', [])
            )
            
            if score > 0.6:  # 60% Similarity Threshold
                result['similar_tools'].append({
                    **tool,
                    'similarity': score
                })
        
        # Sortiere nach Similarity
        result['similar_tools'].sort(key=lambda x: x['similarity'], reverse=True)
        
        # Best Match
        if result['similar_tools']:
            best_match = result['similar_tools'][0]
            result['similarity_score'] = best_match['similarity']
            
            if best_match['similarity'] > 0.8:
                result['duplicate_found'] = True
                result['recommendation'] = f"WARNING - Very similar to '{best_match['name']}' ({best_match['similarity']*100:.0f}% match)"
            elif best_match['similarity'] > 0.6:
                result['recommendation'] = f"Consider using '{best_match['name']}' instead ({best_match['similarity']*100:.0f}% match)"
        
        return result
    
    def _calculate_similarity(self, 
                             name1: str, desc1: str, kw1: List[str],
                             name2: str, desc2: str, kw2: List[str]) -> float:
        """
        Berechnet Ähnlichkeit zwischen zwei Tools.
        
        Returns:
            Similarity Score 0.0-1.0
        """
        score = 0.0
        
        # Name Similarity (40% weight)
        name_sim = self._string_similarity(name1.lower(), name2.lower())
        score += name_sim * 0.4
        
        # Description Similarity (30% weight)
        if desc1 and desc2:
            desc_sim = self._string_similarity(desc1.lower(), desc2.lower())
            score += desc_sim * 0.3
        
        # Keyword Overlap (30% weight)
        if kw1 and kw2:
            kw1_set = set(k.lower() for k in kw1)
            kw2_set = set(k.lower() for k in kw2)
            
            if kw1_set and kw2_set:
                overlap = len(kw1_set & kw2_set)
                union = len(kw1_set | kw2_set)
                kw_sim = overlap / union if union > 0 else 0
                score += kw_sim * 0.3
        
        return score
    
    def _string_similarity(self, s1: str, s2: str) -> float:
        """Simple String Similarity (Levenshtein-ähnlich)."""
        if not s1 or not s2:
            return 0.0
        
        # Einfacher Word-Overlap
        words1 = set(s1.split())
        words2 = set(s2.split())
        
        if not words1 or not words2:
            return 0.0
        
        overlap = len(words1 & words2)
        union = len(words1 | words2)
        
        return overlap / union if union > 0 else 0.0
    
    def pre_create_check(self,
                        tool_name: str,
                        purpose: str,
                        keywords: List[str] = None) -> str:
        """
        Vollständiger Pre-Create Check mit formatierter Ausgabe.
        
        Args:
            tool_name: Geplanter Tool-Name
            purpose: Was soll das Tool machen?
            keywords: Funktions-Keywords
        
        Returns:
            Formatierte Check-Ergebnis als String
        """
        check = self.check_duplicate(tool_name, purpose, keywords)
        
        output = []
        output.append(f"\n{'='*60}")
        output.append(f"Pre-Create Check: '{tool_name}'")
        output.append(f"{'='*60}")
        output.append(f"Purpose: {purpose}")
        
        if keywords:
            output.append(f"Keywords: {', '.join(keywords)}")
        
        output.append(f"\n--- CHECK RESULTS ---")
        
        if check['exact_match']:
            output.append(f"[DUPLICATE] DUPLICATE FOUND!")
            output.append(f"   Exact match: {check['exact_match']['name']}")
            output.append(f"   Path: {self.registry.get_tool_path(check['exact_match']['name'])}")
            output.append(f"\n   >>> USE EXISTING TOOL INSTEAD <<<")
        
        elif check['similar_tools']:
            output.append(f"[WARNING] Similar tools found:")
            for tool in check['similar_tools'][:3]:
                output.append(f"\n   {tool['name']} ({tool['similarity']*100:.0f}% match)")
                output.append(f"   Description: {tool.get('description', 'N/A')}")
                output.append(f"   Path: {self.registry.get_tool_path(tool['name'])}")
        
        else:
            output.append(f"[OK] No duplicates found")
            output.append(f"   Safe to create!")
        
        output.append(f"\n--- RECOMMENDATION ---")
        output.append(f"{check['recommendation']}")
        output.append(f"{'='*60}\n")
        
        return '\n'.join(output)
    
    def track_usage(self, tool_name: str, context: str = ""):
        """
        Trackt Tool-Nutzung für Analytics.
        
        Args:
            tool_name: Genutztes Tool
            context: Kontext der Nutzung
        """
        entry = {
            'tool': tool_name,
            'timestamp': datetime.now().isoformat(),
            'context': context
        }
        
        self.usage_log.append(entry)
        
        # Speichere nur letzte 1000 Einträge
        if len(self.usage_log) > 1000:
            self.usage_log = self.usage_log[-1000:]
        
        self._save_usage_log()
    
    def get_usage_stats(self) -> Dict:
        """
        Generiert Usage-Statistiken.
        
        Returns:
            Dict mit Stats
        """
        if not self.usage_log:
            return {'total_uses': 0, 'top_tools': []}
        
        # Count per Tool
        tool_counts = {}
        for entry in self.usage_log:
            tool = entry['tool']
            tool_counts[tool] = tool_counts.get(tool, 0) + 1
        
        # Top Tools
        top_tools = sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)
        
        return {
            'total_uses': len(self.usage_log),
            'unique_tools': len(tool_counts),
            'top_tools': top_tools[:10],
            'last_used': self.usage_log[-1] if self.usage_log else None
        }
    
    def gap_analysis(self) -> List[str]:
        """
        Analysiert welche Tool-Kategorien fehlen.
        
        Returns:
            Liste von fehlenden Kategorien/Features
        """
        gaps = []
        
        # Check Coverage
        stats = self.registry.stats
        
        # Data Tools fehlen?
        if stats['by_category'].get('data', 0) == 0:
            gaps.append("Data Tools (MediPlaner, ProFiler, Ampel)")
        
        # JavaScript Tools?
        js_tools = [t for t in self.registry.tools.values() 
                   if 'javascript' in t.get('registry', '')]
        if not js_tools:
            gaps.append("JavaScript Tools")
        
        # Build Tools?
        build_keywords = ['build', 'compile', 'package']
        build_tools = [t for t in self.registry.tools.values()
                      if any(kw in t.get('keywords', []) for kw in build_keywords)]
        if not build_tools:
            gaps.append("Build/Packaging Tools")
        
        return gaps


# === Helper Functions ===

def create_detector(registry) -> DuplicateDetector:
    """
    Erstellt DuplicateDetector Instance.
    
    Args:
        registry: ToolRegistry Instance
    
    Returns:
        DuplicateDetector Instance
    """
    return DuplicateDetector(registry)


# === CLI Testing ===

if __name__ == "__main__":
    import sys
    from tool_registry import ToolRegistry
    
    registry = ToolRegistry()
    detector = DuplicateDetector(registry)
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "check":
            tool_name = sys.argv[2] if len(sys.argv) > 2 else ""
            purpose = sys.argv[3] if len(sys.argv) > 3 else ""
            
            print(detector.pre_create_check(tool_name, purpose))
        
        elif command == "stats":
            stats = detector.get_usage_stats()
            print("\nUsage Statistics:")
            print(f"Total Uses: {stats['total_uses']}")
            print(f"Unique Tools: {stats['unique_tools']}")
            print(f"\nTop Tools:")
            for tool, count in stats['top_tools']:
                print(f"  {tool}: {count} uses")
        
        elif command == "gaps":
            gaps = detector.gap_analysis()
            print("\nGap Analysis:")
            if gaps:
                for gap in gaps:
                    print(f"  - Missing: {gap}")
            else:
                print("  No gaps detected")
    
    else:
        # Test Duplicate Detection
        test_cases = [
            ("c_encoding_fixer", "Fix encoding errors", ["encoding", "utf-8"]),
            ("new_encoding_tool", "Fix mojibake in files", ["encoding", "fix"]),
            ("method_finder", "Find Python methods", ["python", "analyze"])
        ]
        
        for name, purpose, keywords in test_cases:
            print(detector.pre_create_check(name, purpose, keywords))
