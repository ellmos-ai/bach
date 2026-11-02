# SPDX-License-Identifier: MIT
"""
Inject Handler - Injektor-Steuerung und Aufgaben-Zuweisung
==========================================================

--inject status          Zeigt Status aller Injektoren
--inject toggle <name>   Schaltet Injektor an/aus
--inject task <minutes>  Weist Aufgabe zu
--inject decompose <id>  Zerlegt Aufgabe
"""
from pathlib import Path
from .base import BaseHandler


from hub._services.ocean_stack_bridge import deprecated_legacy_bach
@deprecated_legacy_bach("memory-hooker")
class InjectHandler(BaseHandler):
    """Handler fuer --inject"""
    
    def __init__(self, base_path: Path):
        super().__init__(base_path)
    
    @property
    def profile_name(self) -> str:
        return "inject"
    
    @property
    def target_file(self) -> Path:
        return self.base_path / "config.json"
    
    def get_operations(self) -> dict:
        return {
            "status": "Status aller Injektoren",
            "toggle": "Injektor an/aus schalten",
            "task": "Aufgabe fuer X Minuten zuweisen",
            "decompose": "Aufgabe zerlegen"
        }
    
    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        # ────────────────────────────────────────────────────────────
        # Import aus tools/ statt hub/ (BACH v1.1 Struktur)
        # tools/ = Standalone-Utilities, hub/ = CLI-Handler/Router
        # ────────────────────────────────────────────────────────────
        try:
            from tools.injectors import InjectorSystem
            system = InjectorSystem(self.base_path)
        except Exception as e:
            return False, f"Injektor-System nicht verfuegbar: {e}"
        
        if operation == "status" or not operation:
            return True, system.status()
        
        elif operation == "toggle":
            if not args:
                return False, """Usage: --inject toggle <name>

Verfuegbar:
  strategy   Hilfreiche Gedanken bei Trigger-Woertern
  context    Kontext-Hinweise bei Stichworten  
  time       Regelmaessige Zeit-Updates (Timebeat)
  between    Auto-Erinnerung nach Task-Done"""
            
            name = args[0].lower()
            # Kurzformen erlauben
            name_map = {
                "strategy": "strategy_injector",
                "context": "context_injector",
                "time": "time_injector",
                "between": "between_injector",
            }
            full_name = name_map.get(name, f"{name}_injector")
            return system.toggle(full_name)
        
        elif operation == "task":
            minutes = int(args[0]) if args else 5
            return system.assign_task(minutes)
        
        elif operation == "decompose":
            if not args:
                return False, "Usage: --inject decompose <task-id>"
            return system.decompose_task(args[0])
        
        else:
            return False, f"Unbekannte Operation: {operation}\nNutze: --inject status"
