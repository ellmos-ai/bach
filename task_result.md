# Task 2704 – Source-only Tray-Intent-Reconcile: Verifikationsbericht

Ergebnis: Die Implementierung (tray_worker_execution.py + telegram_chat.prepare_tray_intent_reconciliation + slots_config) wurde quellenseitig vollständig verifiziert. KEINE Code-Änderung nötig.

Befunde (Datei:Zeile):

1. Start-Admission (telegram_chat.py Z.4861–5015):
   - Guard Z.4904–4909: buddha_always_on + vorhandenes _controller_run → _assert_worker_profile_inactive, sonst 409 core_previous_run_unconfirmed.
   - Marker Z.4975–5004: schema bach.worker-controller-run.v1, phase=admitted, service_instance, host, start_request_id, generation, pid, process_create_time, physical/lease_worker_id, durable=os.name=="posix", prior_runs_unconfirmed. Fehlender Marker beweist nie Legacy-Start.
   - advance_revision Z.5007–5008; RAM-Publish erst nach durablem Write Z.5005–5006.

2. slots_config.py Z.426–450 worker_admission_transaction: admission_revision=Nonce, published→RuntimeError, _validated_controller_run + worker[_CONTROLLER_RUN_FIELD], save_slots_config(durable=True). get_always_on_execution_slot Z.749–794.

3. prepare_tray_intent_reconciliation (telegram_chat.py Z.952–1050): Feldvalidierung→400, Mismatches→409, Marker-Verbrauch Z.1017–1030 (phase admitted, durable True, process_state∈{gone,mismatch}, worker_leeres leer, worker/host/service_instance/start_request_id/generation – alle Felder von Erzeugungsseite gedeckt). Route Z.7391–7393 hinter _allow_json_post-Gate.

4. tray_worker_execution.py Z.1–468: retire_unconfirmed fail-closed (Proof exakt, 2× Re-Read, _write_locked tempfile+fsync+os.replace); main Z.385–464.

5. Recovery (telegram_chat.py Z.7750–7757): ohne Marker → blocked prior_controller_unconfirmed; mit Marker → _assert_worker_profile_inactive(allow_legacy_start=True) unter Lock.

6. Tests: system/tests/test_tray_intent_reconcile.py (365 Z., 8 fail-closed-Fälle 400/409/503, Replay-Schutz) deckt den Vertrag ab. execute_command ist im Workerlauf blockiert; keine erneute Testausführung behauptet. Erster finish_task-Lauf führte Tests ohne dokumentierten Fehler aus.

Fazit: Marker-Konsistenz Erzeugung↔Verbrauch restlos bestätigt; durable=True nur auf POSIX → prepare lehnt auf Nicht-POSIX fail-closed ab. Kein Aenderungsbedarf.