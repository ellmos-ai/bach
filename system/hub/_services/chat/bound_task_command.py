"""Translate explicit task CLI arguments to the existing fenced tool contract."""


_FIELDS = {
    "--title": "title", "-t": "title", "--description": "description", "-d": "description",
    "--category": "category", "-c": "category", "--priority": "priority", "-p": "priority",
    "--assigned": "assigned_to", "-a": "assigned_to", "--required-model": "required_model",
    "--assigned-slot": "assigned_slot", "--depends-on": "depends_on",
}


def _options(values):
    result = {}
    index = 0
    while index < len(values):
        flag = values[index]
        if "=" in flag:
            flag, value = flag.split("=", 1)
            index += 1
        else:
            if index + 1 >= len(values):
                raise ValueError("Optionswert fehlt")
            value = values[index + 1]
            index += 2
        field = _FIELDS.get(flag)
        if field is None or field in result:
            raise ValueError("Unbekannte oder doppelte Task-Option")
        result[field] = value.strip() if field in {"required_model", "assigned_slot"} else value
    return result


def bound_task_command(operation, arguments, binding):
    if (not isinstance(arguments, list) or any(not isinstance(value, str) for value in arguments)
            or not isinstance(operation, str)):
        raise ValueError("Task-Argumente müssen eine Liste von Texten sein")
    binding.assert_active()
    if operation == "list" and not arguments:
        return binding.execute_task_manage({"action": "list"})
    if operation == "add":
        if not arguments or not arguments[0].strip():
            raise ValueError("Task-Titel fehlt")
        options = _options(arguments[1:])
        if "title" in options:
            raise ValueError("Task-Titel doppelt angegeben")
        return binding.execute_task_manage({"action": "add", "title": arguments[0], **options})
    if not arguments or not arguments[0].isdecimal() or int(arguments[0]) <= 0:
        raise ValueError("Task-ID fehlt")
    task_id = int(arguments[0])
    tail = arguments[1:]
    if operation in {"show", "detail"} and not tail:
        return binding.execute_task_manage({"action": "detail", "task_id": task_id})
    if operation == "done" and not tail:
        return binding.execute_task_manage({"action": "done", "task_id": task_id})
    if operation in {"block", "reopen", "unblock"} and not tail:
        status = "blocked" if operation == "block" else "pending"
        return binding.execute_task_manage({"action": "update", "task_id": task_id, "status": status})
    changes = None
    if operation == "depends":
        if not tail:
            return binding.execute_task_manage({"action": "detail", "task_id": task_id})
        if task_id != binding.task_id:
            raise ValueError("Abhängigkeit gehört nicht zum gebundenen Auftrag")
        if tail == ["--clear"]:
            changes = {"depends_on": ""}
        else:
            if len(tail) == 1 and "=" in tail[0]:
                flag, value = tail[0].split("=", 1)
            elif len(tail) == 2:
                flag, value = tail
            else:
                raise ValueError("Genau eine Abhängigkeitsänderung erforderlich")
            if flag not in {"--on", "--remove"} or not value.isdecimal() or int(value) <= 0:
                raise ValueError("Ungültige Abhängigkeitsänderung")
            target = int(value)
            if target == task_id:
                raise ValueError("Auftrag kann nicht von sich selbst abhängen")
            from hub._services.task_schema import parse_task_dependency_ids
            dependencies, invalid = parse_task_dependency_ids(binding.task_snapshot().get("depends_on"))
            if invalid:
                raise ValueError("Bestehende Abhängigkeiten müssen zuerst geklärt werden")
            dependencies = set(dependencies)
            if flag == "--on":
                dependencies.add(target)
            else:
                dependencies.discard(target)
            changes = {"depends_on": ",".join(str(value) for value in sorted(dependencies))}
    if operation == "edit" and tail:
        changes = _options(tail)
    elif operation in {"priority", "assign"} and len(tail) == 1 and not tail[0].startswith("-"):
        changes = {"priority" if operation == "priority" else "assigned_to": tail[0]}
    if changes:
        return binding.execute_task_manage({"action": "update", "task_id": task_id, **changes})
    raise ValueError("Task-Befehl benötigt einen unterstützten gebundenen Werkzeugaufruf")
