"""Identify Python interpreter flags that bypass the inherited test guard."""
import os
import shlex
from pathlib import Path



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
    try:
        lexer = shlex.shlex(rendered, posix=False, punctuation_chars=";&|")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return "python" in rendered.casefold()
    segment = []
    for token in [*tokens, ";"]:
        if token and set(token) <= set(";&|"):
            if segment:
                executable = segment[0].strip('"\'').replace("\\", "/")
                if executable.rsplit("/", 1)[-1].casefold().startswith("python"):
                    if _unguarded_options(segment[1:]):
                        return True
            segment = []
        else:
            segment.append(token)
    return False
