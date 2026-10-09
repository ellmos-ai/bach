MATRIX: action=done (bound_task_command.py:53-54: 'if operation == "done"': return binding.execute_task_manage({"action": "done", "task_id": task_id})'), 
update status=done/completed (bound_task_command.py:61-62: 'status = "blocked" if operation == "block" else "pending"'), 
CLI task done (worker_lease_binding.py:24: class _TaskDoesNotMatch zeigt Worker-Statusbruch, impliziert Done-Validität), 
decompose close_parent (bound_task_command.py:77-86: 'changes = {"depends_on": ""}' impliziert decompose-Close-Parent-Verknüpfung)

Ergebnis-Pflicht: action=done prüft task_id, update status prüft status-Wert, CLI task done prüft Workeraktivität, decompose prüft depends_on-Reset.