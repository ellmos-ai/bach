---
name: immune-extended-concepts
metadata:
  version: 1.0.0
  status: active
description: >
  Erweiterte Konzepte fuer das Immune System basierend auf biologischem Modell.
---

# Immune System - Erweiterte Konzepte

> **Ergänzung basierend auf User-Reflektion zum biologischen Immunsystem-Modell**

---

## 🧬 Neue Konzepte: Biologisches Immunsystem-Modell

### 1. Nicht-Registrierte Ordner = "Friedliche Organismen"

```python
ORGANISM_CLASSIFICATION = {
    'registered_active': {
        'status': 'Teil der DNA',
        'behavior': 'Vollständig integriert, wird aktiv genutzt',
        'immune_response': 'Keine - ist Teil des Körpers'
    },
    
    'unregistered_neutral': {
        'status': 'Kommensale (friedlicher Bewohner)',
        'behavior': 'Existiert, wird nicht gelesen, lebt nicht aktiv',
        'immune_response': 'Beobachten, nicht angreifen'
    },
    
    'unregistered_similar': {
        'status': 'Potentielle neue Variante (Gentransfer-Kandidat)',
        'behavior': 'Ähnelt bestehendem Skill - könnte Version sein',
        'immune_response': 'Prüfen → Integration als Variante'
    },
    
    'core_system_modified': {
        'status': 'Potentielle Infektion der Kern-DNA',
        'behavior': 'Registry oder Steuerroutine verändert',
        'immune_response': 'ALARM → Backup → Quarantäne → Prüfung'
    }
}
```

### 2. Automatische Änderungserkennung (User-Änderungs-Sensor)

```python
def detect_user_modifications():
    """
    Erkennt wenn User direkt Dateien verändert hat
    (außerhalb des Claude-Prozesses)
    """
    registered_skills = load_registry().registered_skills
    modifications_found = []
    
    for skill in registered_skills:
        skill_path = get_skill_full_path(skill.path)
        skill_md = f"{skill_path}/SKILL.md"
        
        # Hash-Vergleich mit letztem bekannten Stand
        current_hash = calculate_file_hash(skill_md)
        stored_hash = get_stored_hash(skill.name)
        
        if current_hash != stored_hash:
            # Änderung erkannt!
            modifications_found.append({
                'skill_name': skill.name,
                'path': skill_md,
                'old_hash': stored_hash,
                'new_hash': current_hash,
                'modification_time': get_file_modification_time(skill_md),
                'action_required': 'create_variant_from_change'
            })
    
    return modifications_found

def handle_detected_modification(modification):
    """
    Behandelt erkannte Änderung durch Aufspaltung in zwei Versionen
    """
    skill_name = modification['skill_name']
    
    # 1. Original wiederherstellen aus Backup
    original_content = restore_from_backup(skill_name)
    
    # 2. User-Änderung als neue Variante speichern
    user_modified_content = read_current_file(modification['path'])
    
    # 3. Diff erstellen für Dokumentation
    changes = create_diff(original_content, user_modified_content)
    
    # 4. Original zurückschreiben
    write_file(modification['path'], original_content)
    update_stored_hash(skill_name, calculate_file_hash(modification['path']))
    
    # 5. User-Version als Variante speichern
    variant_metadata = {
        'source': 'user_modification',
        'modification_date': modification['modification_time'],
        'changes_summary': summarize_changes(changes),
        'status': 'untested'
    }
    
    save_as_new_variant(
        skill_name=skill_name,
        content=user_modified_content,
        metadata=variant_metadata,
        variant_suffix='user_modified'
    )
    
    # 6. User informieren
    return {
        'action': 'split_into_two_versions',
        'original_restored': True,
        'new_variant_created': f"{skill_name}_user_modified_untested",
        'message': f"Änderung an {skill_name} erkannt. Original wiederhergestellt, "
                   f"Ihre Änderung als neue Variante gespeichert."
    }
```

### 3. Varianten-Backup-System

```python
VARIANT_BACKUP_CONFIG = {
    'backup_location': 'Subroutinen/skill-maintenance/_archive/variants/',
    'backup_before': [
        'variant_modification',
        'variant_testing',
        'variant_activation',
        'variant_deprecation'
    ],
    'retention': {
        'active_variants': 'forever',
        'deprecated_variants': '90_days',
        'failed_variants': '30_days'
    }
}

def backup_variant_before_change(skill_name, variant_id, change_type):
    """
    Erstellt Backup einer Variante bevor Änderungen vorgenommen werden
    """
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_filename = f"{variant_id}_{change_type}_{timestamp}.md"
    
    variant_content = read_variant(skill_name, variant_id)
    backup_path = f"{VARIANT_BACKUP_CONFIG['backup_location']}/{skill_name}/{backup_filename}"
    
    # Backup mit Metadaten
    backup_content = f"""# Varianten-Backup

**Backup erstellt**: {datetime.now()}
**Variante**: {variant_id}
**Grund**: Vor {change_type}
**Skill**: {skill_name}

---

{variant_content}
"""
    
    write_file(backup_path, backup_content)
    
    return {
        'backup_path': backup_path,
        'backup_time': timestamp,
        'can_restore': True
    }

def restore_variant_from_backup(skill_name, variant_id, backup_timestamp):
    """
    Stellt Variante aus Backup wieder her
    """
    backup_files = find_backups_for_variant(skill_name, variant_id)
    target_backup = find_backup_by_timestamp(backup_files, backup_timestamp)
    
    if target_backup:
        original_content = extract_content_from_backup(target_backup)
        write_variant(skill_name, variant_id, original_content)
        return {'restored': True, 'from': target_backup}
    
    return {'restored': False, 'error': 'Backup not found'}
```

### 4. Gensequenz-Prüfung (Ähnlichkeitserkennung)

```python
def scan_for_unregistered_potential_variants():
    """
    Durchsucht Filesystem nach Ordnern die Varianten sein könnten
    aber nicht registriert sind (Gentransfer-Kandidaten)
    """
    skills_dir = get_skills_directory()
    registered_names = get_all_registered_skill_names()
    
    candidates = []
    
    # Alle Ordner durchsuchen
    for category_dir in ['Agenten', 'Prozessoren', 'Steuerroutinen', 'Subroutinen']:
        category_path = f"{skills_dir}/{category_dir}"
        
        for folder in list_subdirectories(category_path):
            folder_name = folder.name
            
            if folder_name not in registered_names:
                # Nicht registrierter Ordner gefunden
                
                # Prüfe ob SKILL.md existiert
                has_skill_md = file_exists(f"{folder.path}/SKILL.md")
                
                if has_skill_md:
                    # Prüfe Ähnlichkeit zu registrierten Skills
                    content = read_file(f"{folder.path}/SKILL.md")
                    similarity_results = check_similarity_to_registered(content)
                    
                    if similarity_results['max_similarity'] > 0.6:
                        # Hohe Ähnlichkeit - wahrscheinlich Variante
                        candidates.append({
                            'path': folder.path,
                            'name': folder_name,
                            'similar_to': similarity_results['most_similar_skill'],
                            'similarity': similarity_results['max_similarity'],
                            'recommendation': 'register_as_variant'
                        })
                    else:
                        # Niedriger Ähnlichkeit - neuer Skill?
                        candidates.append({
                            'path': folder.path,
                            'name': folder_name,
                            'similar_to': None,
                            'similarity': similarity_results['max_similarity'],
                            'recommendation': 'consider_new_registration'
                        })
    
    return candidates

def check_similarity_to_registered(content):
    """
    Prüft Ähnlichkeit eines Contents zu allen registrierten Skills
    """
    registered_skills = get_all_registered_skills()
    similarities = []
    
    for skill in registered_skills:
        registered_content = read_skill_content(skill.name)
        similarity = calculate_content_similarity(content, registered_content)
        similarities.append({
            'skill_name': skill.name,
            'similarity': similarity
        })
    
    # Höchste Ähnlichkeit finden
    max_similar = max(similarities, key=lambda x: x['similarity'])
    
    return {
        'max_similarity': max_similar['similarity'],
        'most_similar_skill': max_similar['skill_name'],
        'all_similarities': similarities
    }
```

### 5. Gentransfer-Integration

```python
def integrate_unregistered_as_variant(candidate):
    """
    Integriert unregistrierten Ordner als offizielle Variante
    """
    source_skill = candidate['similar_to']
    new_content = read_file(f"{candidate['path']}/SKILL.md")
    
    # 1. Als Variante registrieren
    variant_metadata = {
        'source': 'gentransfer_integration',
        'original_path': candidate['path'],
        'similarity_to_parent': candidate['similarity'],
        'integration_date': datetime.now().isoformat(),
        'status': 'untested'
    }
    
    variant_id = save_as_new_variant(
        skill_name=source_skill,
        content=new_content,
        metadata=variant_metadata,
        variant_suffix='gentransfer'
    )
    
    # 2. Original-Ordner markieren oder aufräumen
    mark_as_integrated(candidate['path'], variant_id)
    
    # 3. Zum Evolutionsprozess anmelden
    register_for_evolution_testing(source_skill, variant_id)
    
    return {
        'integrated': True,
        'as_variant': variant_id,
        'parent_skill': source_skill,
        'next_step': 'evolution_testing'
    }
```

---

## 🛡️ Kern-System-Schutz (Geschützte DNA)

```python
PROTECTED_CORE_SYSTEMS = {
    'registry': {
        'path': 'Steuerroutinen/skill-administration-system/skill_registry.json',
        'protection_level': 'critical',
        'backup_frequency': 'on_every_change',
        'immune_response': 'immediate_restoration'
    },
    
    'skill_administration': {
        'path': 'Steuerroutinen/skill-administration-system/SKILL.md',
        'protection_level': 'critical',
        'backup_frequency': 'on_every_change',
        'immune_response': 'immediate_restoration'
    },
    
    'immune_system': {
        'path': 'Prozessoren/evolution-skills/tools/immune_system/SKILL.md',
        'protection_level': 'critical',
        'backup_frequency': 'on_every_change',
        'immune_response': 'immediate_restoration'
    },
    
    'evolution_config': {
        'path': 'Steuerroutinen/self-learning-routines/evolution_config.json',
        'protection_level': 'high',
        'backup_frequency': 'on_every_change',
        'immune_response': 'quarantine_and_review'
    },
    
    'triggers': {
        'path': 'Steuerroutinen/skill-administration-system/triggers.json',
        'protection_level': 'high',
        'backup_frequency': 'on_every_change',
        'immune_response': 'quarantine_and_review'
    }
}

def protect_core_system_file(file_path, operation_type):
    """
    Schützt Kern-Systemdateien vor unautorisierten Änderungen
    """
    config = PROTECTED_CORE_SYSTEMS.get(identify_core_system(file_path))
    
    if not config:
        return {'protected': False, 'allow_operation': True}
    
    # 1. Backup erstellen
    backup_core_file(file_path)
    
    # 2. Änderung prüfen
    if operation_type == 'user_direct_modification':
        # User hat direkt geändert - als neue Variante behandeln
        return handle_core_modification(file_path, config)
    
    elif operation_type == 'evolution_modification':
        # Evolution-System will ändern - nur bei Evolution-Varianten erlaubt
        return {
            'protected': True,
            'allow_operation': False,
            'reason': 'Core systems cannot be modified by evolution'
        }
    
    elif operation_type == 'system_update':
        # Offizielles System-Update
        return {
            'protected': True,
            'allow_operation': True,
            'requires_backup': True
        }

def handle_core_modification(file_path, config):
    """
    Behandelt Änderung an geschützter Datei
    """
    if config['immune_response'] == 'immediate_restoration':
        # Sofort wiederherstellen
        restore_from_backup(file_path)
        return {
            'action': 'restored',
            'message': 'Core system restored from backup. Change was rejected.'
        }
    
    elif config['immune_response'] == 'quarantine_and_review':
        # Änderung isolieren für Review
        quarantine_modified_version(file_path)
        restore_from_backup(file_path)
        return {
            'action': 'quarantined',
            'message': 'Change quarantined for review. Original restored.'
        }
```

---

## 📊 Session-Start Immunprüfung

```python
def run_immune_scan_at_session_start():
    """
    Führt Immunscan bei jedem Session-Start aus
    """
    scan_results = {
        'timestamp': datetime.now().isoformat(),
        'threats_found': [],
        'modifications_detected': [],
        'unregistered_candidates': [],
        'actions_taken': []
    }
    
    # 1. Kern-Systeme prüfen
    for name, config in PROTECTED_CORE_SYSTEMS.items():
        status = verify_core_system_integrity(config['path'])
        if not status['intact']:
            scan_results['threats_found'].append({
                'type': 'core_system_modification',
                'system': name,
                'details': status
            })
            # Sofortige Reaktion
            action = protect_core_system_file(config['path'], 'user_direct_modification')
            scan_results['actions_taken'].append(action)
    
    # 2. Registrierte Skills auf Änderungen prüfen
    modifications = detect_user_modifications()
    for mod in modifications:
        scan_results['modifications_detected'].append(mod)
        action = handle_detected_modification(mod)
        scan_results['actions_taken'].append(action)
    
    # 3. Unregistrierte Ordner scannen
    candidates = scan_for_unregistered_potential_variants()
    scan_results['unregistered_candidates'] = candidates
    
    return scan_results
```

---

## Zusammenfassung: Immunsystem-Ebenen

| Ebene | Funktion | Reaktion |
|-------|----------|----------|
| **Kern-DNA** | Registry, Administration, Immune System | Sofortige Wiederherstellung |
| **Registrierte Skills** | Änderungserkennung | Aufspaltung in Original + Variante |
| **Unregistrierte Ordner** | Ähnlichkeitsprüfung | Integration als Variante oder Ignorieren |
| **Varianten** | Backup vor jeder Änderung | Wiederherstellbarkeit garantieren |

---

*Evolution + Immunsystem = Kontrollierte Verbesserung ohne Selbstzerstörung*