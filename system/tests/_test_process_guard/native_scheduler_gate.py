"""Test-only bootstrap for one reviewed, isolated scheduler command gate.

The original isolated helper is never passed to Popen unchanged. Unknown helpers
and externally supplied bootstrap strings still meet the normal test guard.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
import subprocess
import sys
import zlib
from pathlib import Path

_DIRECTORY = Path(__file__).resolve().parent

_BOOTSTRAP = r'''
import base64,hashlib,json,os,sys,types,zlib
bundle=json.loads(zlib.decompress(base64.b85decode(PACKED)).decode('utf-8'))
if os.environ.get('BACH_TEST_MODE')!='1' or not os.path.isabs(os.environ.get('BACH_RUNTIME_DIR','')):
    raise SystemExit(86)
if hashlib.sha256(bundle['gate'].encode('utf-8')).hexdigest()!='d6250f2fbd8042f55858ca4a325321c02d240c8c62d56ab1402a4c5410459c13':
    raise SystemExit(86)
for name in ('python_options','native_scheduler_gate','sitecustomize'):
    source=bundle['sources'][name]
    module=types.ModuleType(name)
    module.__file__=source['path']
    if name=='native_scheduler_gate':
        module._SOURCE_BUNDLE=bundle['sources']
    sys.modules[name]=module
    exec(compile(source['text'],source['path'],'exec'),module.__dict__)
guard=sys.modules['sitecustomize']
if (getattr(guard,'_BACH_TEST_GUARD_INSTALLED',False) is not True
        or guard.subprocess.Popen is not guard._GuardedPopen
        or guard.os.kill is not guard._guarded_os_kill):
    raise SystemExit(86)
if sys.argv[1]=='posix':
    if os.getpid()!=os.getpgrp() or os.getpid()!=os.getsid(0):
        raise SystemExit(86)
    original_killpg=os.killpg
    def own_session_killpg(group,sig):
        if group!=os.getpid() or group!=os.getpgrp() or group!=os.getsid(0):
            raise RuntimeError('foreign process group blocked in test gate')
        return original_killpg(group,sig)
    os.killpg=own_session_killpg
exec(compile(bundle['gate'],'<reviewed native scheduler gate>','exec'),{'__name__':'__main__'})
'''


def _gate_shape(command, options):
    """Validate source-pinned code and the exact production constructor shape."""
    if not isinstance(command, (list, tuple)) or not all(type(v) is str for v in command):
        return False
    if len(command) not in (7, 8) or command[0] != sys.executable:
        return False
    if list(command[1:5]) != ['-I', '-S', '-B', '-c']:
        return False
    # Literal reviewed pin, deliberately independent of a mutable provider export.
    if hashlib.sha256(command[5].encode('utf-8')).hexdigest() != (
        'd6250f2fbd8042f55858ca4a325321c02d240c8c62d56ab1402a4c5410459c13'
    ):
        return False
    common = {'cwd', 'env', 'stdin', 'stdout', 'stderr', 'bufsize'}
    if any(options.get(stream) != subprocess.PIPE for stream in ('stdin', 'stdout', 'stderr')):
        return False
    if options.get('bufsize') != 0 or type(options.get('bufsize')) is not int:
        return False
    if options.get('cwd') is not None and not isinstance(options['cwd'], str):
        return False
    if not isinstance(options.get('env'), dict):
        return False
    if os.name == 'nt':
        return (
            len(command) == 7 and command[6] == 'win'
            and set(options) == common | {'creationflags'}
            and options['creationflags'] == subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    if (len(command) != 8 or command[6] != 'posix'
            or set(options) != common | {'start_new_session', 'pass_fds'}
            or options['start_new_session'] is not True):
        return False
    try:
        descriptor = int(command[7])
        return (descriptor >= 3 and str(descriptor) == command[7]
                and options['pass_fds'] == (descriptor,)
                and stat.S_ISFIFO(os.fstat(descriptor).st_mode))
    except (ValueError, OSError):
        return False


def guard_native_gate(command, options):
    """Return a guarded invocation, or None: callers must keep their normal guard.

    This hook belongs only in the real Popen guard, never a general command
    whitelist. The generated bootstrap itself is not an accepted input helper.
    """
    if os.environ.get('BACH_TEST_MODE') != '1' or not _gate_shape(command, options):
        return None
    bundle = {'gate': command[5], 'sources': _SOURCE_BUNDLE}
    packed = base64.b85encode(zlib.compress(json.dumps(bundle).encode('utf-8'), 9))
    source = 'PACKED=' + repr(packed) + '\n' + _BOOTSTRAP
    result = list(command)
    result[5] = source
    return result


# Freeze harness sources at trusted module import, before test-specific patches.
# A gate receives this bundle explicitly, before any untrusted frame is read.
if '_SOURCE_BUNDLE' not in globals():
    _SOURCE_BUNDLE = {
        name: {'path': str(_DIRECTORY / (name + '.py')),
               'text': (_DIRECTORY / (name + '.py')).read_text(encoding='utf-8')}
        for name in ('python_options', 'native_scheduler_gate', 'sitecustomize')
    }
