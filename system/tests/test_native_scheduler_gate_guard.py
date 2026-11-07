"""Exercise the native gate with real children and the inherited test guard."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time

import pytest
from ellmos_scheduler import _command_process as native
from tests._test_process_guard.native_scheduler_gate import guard_native_gate


@pytest.fixture
def invocation():
    options = {'cwd': None, 'env': dict(os.environ), 'stdin': subprocess.PIPE,
               'stdout': subprocess.PIPE, 'stderr': subprocess.PIPE, 'bufsize': 0}
    command = [sys.executable, '-I', '-S', '-B', '-c', native._GATE]
    descriptors = ()
    if os.name == 'nt':
        command.append('win')
        options['creationflags'] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        descriptors = os.pipe()
        command.extend(['posix', str(descriptors[1])])
        options.update(start_new_session=True, pass_fds=(descriptors[1],))
    yield command, options
    for descriptor in descriptors:
        os.close(descriptor)


def execute(argv, *, env=None, timeout=8):
    return native.run_command(argv, cwd=None, env=dict(os.environ) if env is None else env,
                              timeout=timeout)


def rejected_frame(invocation, argv):
    command, options = invocation
    frame = json.dumps({'argv': argv, 'detach_on_success': False}).encode()
    process = subprocess.Popen(command, **options)
    error = bytearray()
    blocked = threading.Event()

    def read_error():
        for line in iter(process.stderr.readline, b''):
            error.extend(line)
            if b'blocked' in line:
                blocked.set()

    reader = threading.Thread(target=read_error, daemon=True)
    reader.start()
    process.stdin.write(len(frame).to_bytes(4, 'big') + frame)
    process.stdin.flush()
    observed = blocked.wait(8)
    process.stdin.close()
    process.wait(timeout=8)
    reader.join(timeout=8)
    process.stderr.close()
    process.stdout.close()
    assert observed, bytes(error)
    assert process.returncode != 0
    assert b'blocked' in error


def test_exact_pin_and_direct_bootstrap_stays_blocked(invocation):
    command, options = invocation
    assert hashlib.sha256(native._GATE.encode()).hexdigest() == (
        'd6250f2fbd8042f55858ca4a325321c02d240c8c62d56ab1402a4c5410459c13')
    guarded = guard_native_gate(command, options)
    assert guarded is not None and guarded[1:5] == ['-I', '-S', '-B', '-c']
    assert guarded[5] != native._GATE
    assert guard_native_gate(guarded, options) is None
    with pytest.raises(RuntimeError, match='blocked'):
        subprocess.Popen(guarded, **options)


@pytest.mark.parametrize('change', ['code', 'python', 'flags', 'mode', 'extra', 'shell', 'stdio', 'env', 'ownership'])
def test_changed_invocation_is_rejected(invocation, change):
    command, options = invocation
    command, options = list(command), dict(options)
    if change == 'code':
        command[5] += '\n'
    elif change == 'python':
        command[0] += '.unknown'
    elif change == 'flags':
        command[1] = '-E'
    elif change == 'mode':
        command[6] = 'unknown'
    elif change == 'extra':
        command.append('extra')
    elif change == 'shell':
        options['shell'] = True
    elif change == 'stdio':
        options['stdin'] = subprocess.DEVNULL
    elif change == 'env':
        options['env'] = None
    elif os.name == 'nt':
        options['creationflags'] = subprocess.CREATE_NO_WINDOW
    else:
        options['start_new_session'] = False
    assert guard_native_gate(command, options) is None


def test_mutable_provider_export_is_not_trusted(monkeypatch, tmp_path):
    marker = tmp_path / 'mutated'
    monkeypatch.setattr(native, '_GATE', f"open({str(marker)!r},'w').write('unsafe')")
    with pytest.raises(RuntimeError, match='blocked'):
        execute([sys.executable, '-c', 'pass'])
    assert not marker.exists()


def test_bootstrap_requires_active_inherited_test_mode(invocation, monkeypatch):
    command, options = invocation
    monkeypatch.setenv('BACH_TEST_MODE', '0')
    assert guard_native_gate(command, options) is None


def test_native_legitimate_child_has_guard_even_with_spoofed_env(tmp_path):
    marker = tmp_path / 'guard.txt'
    code = (
        "import os,subprocess,pathlib; "
        "assert os.environ['BACH_TEST_MODE']=='1'; "
        "assert subprocess.Popen.__name__=='_GuardedPopen'; "
        f"pathlib.Path({str(marker)!r}).write_text('guard installed')"
    )
    env = dict(os.environ, BACH_TEST_MODE='0', PYTHONPATH='')
    result = execute([sys.executable, '-c', code], env=env)
    assert marker.read_text() == 'guard installed', result


@pytest.mark.parametrize('flags', ['-I', '-S', '-E', '-IS'])
def test_inner_isolated_python_blocked_before_target(invocation, tmp_path, flags):
    marker = tmp_path / 'forbidden'
    rejected_frame(invocation, [sys.executable, flags, '-c', f"open({str(marker)!r},'w').write('unsafe')"])
    assert not marker.exists()


@pytest.mark.parametrize('argv', [['taskkill', '/PID', '2147483647'],
                                 ['powershell', '-Command', 'Stop-Process -Id 2147483647'],
                                 ['sh', '-c', 'kill -9 2147483647']])
def test_inner_host_control_blocked(invocation, argv):
    rejected_frame(invocation, argv)


def test_nested_environment_escape_is_blocked(invocation, tmp_path):
    marker = tmp_path / 'escaped'
    inner = [sys.executable, '-I', '-c', f"open({str(marker)!r},'w').write('unsafe')"]
    code = f"import subprocess; subprocess.run({inner!r},env={{'BACH_TEST_MODE':'0','PYTHONPATH':''}})"
    rejected_frame(invocation, [sys.executable, '-c', code])
    assert not marker.exists()


def test_unknown_direct_isolated_helper_stays_blocked():
    with pytest.raises(RuntimeError, match='blocked'):
        subprocess.Popen([sys.executable, '-I', '-S', '-c', 'pass'])


def test_malformed_frame_never_launches_target(invocation, tmp_path):
    command, options = invocation
    marker = tmp_path / 'bad-frame'
    payload = json.dumps({'argv': [sys.executable, '-c',
                                  f"open({str(marker)!r},'w').write('unsafe')"],
                          'detach_on_success': False, 'unexpected': True}).encode()
    process = subprocess.Popen(command, **options)
    process.stdin.write(len(payload).to_bytes(4, 'big') + payload)
    process.stdin.flush()
    process.wait(timeout=8)
    for stream in (process.stdin, process.stdout, process.stderr):
        stream.close()
    assert process.returncode != 0
    assert not marker.exists()


def test_native_timeout_cleans_owned_descendant_and_preserves_control(tmp_path):
    import psutil

    marker = tmp_path / 'descendant.json'
    child = ("import os,json,pathlib,time; "
             f"pathlib.Path({str(marker)!r}).write_text(json.dumps(os.getpid())); "
             "time.sleep(30)")
    target = f"import subprocess,time; subprocess.Popen({[sys.executable, '-c', child]!r}); time.sleep(30)"
    control = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            execute([sys.executable, '-c', target], timeout=2)
        assert marker.exists(), 'owned descendant must really start before timeout'
        descendant = json.loads(marker.read_text())
        deadline = time.monotonic() + 5
        def descendant_running():
            try:
                return psutil.Process(descendant).status() != psutil.STATUS_ZOMBIE
            except psutil.NoSuchProcess:
                return False

        while descendant_running() and time.monotonic() < deadline:
            time.sleep(.05)
        assert not descendant_running(), 'native ownership cleanup missed descendant'
        assert control.poll() is None, 'unrelated owned control process was affected'
    finally:
        control.terminate()
        control.wait(timeout=5)
