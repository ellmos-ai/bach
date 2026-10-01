"""Identify Python interpreter flags that bypass the inherited test guard."""
import os
import re
import shlex
from pathlib import Path

_PYTHON_COMMAND = re.compile(
    r'(?:^|[;&|]\s*)(?:"[^"]*python(?:\d+(?:\.\d+)*)?\.exe"|'
    r'[^\s"]*python(?:\d+(?:\.\d+)*)?(?:\.exe)?)\s+'
    r'([^\r\n;&|]*)',
    re.IGNORECASE,
)


def _unguarded_options(arguments):
    index = 0
    while index < len(arguments):
        option = str(arguments[index]).strip('"\'')
        if option == "-" or not option.startswith("-"):
            return False
        if option == "--check-hash-based-pycs":
            index += 2
            continue
        if option.startswith("--"):
            index += 1
            continue
        for offset, flag in enumerate(option[1:], start=1):
            if flag in "eEisIS":
                return True
            if flag in "cm":
                return False
            if flag in "WX":
                # The remainder is this option's value, even when it contains I/S/E.
                if offset == len(option) - 1:
                    index += 1
                break
        index += 1
    return False


def python_without_site_guard(command):
    if isinstance(command, (list, tuple)):
        if not command:
            return False
        executable = os.fsdecode(command[0]).strip('"\'')
        if Path(executable).name.casefold().startswith("python"):
            return _unguarded_options(command[1:])
        rendered = " ".join(os.fsdecode(part) for part in command
                            if isinstance(part, (str, bytes, os.PathLike)))
    elif isinstance(command, (str, bytes)):
        rendered = os.fsdecode(command)
    else:
        return False
    for match in _PYTHON_COMMAND.finditer(rendered):
        try:
            arguments = shlex.split(match.group(1), posix=False)
        except ValueError:
            # An unparseable Python command must not bypass the safety guard.
            return True
        if _unguarded_options(arguments):
            return True
    return False
