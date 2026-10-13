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
Database - Connection Management und Migration Runner
=====================================================
Zentrale DB-Verwaltung mit Schema-Datei und Migrationen.
Nutzt bestehende bach.db, fuegt fehlende Tabellen per IF NOT EXISTS hinzu.
"""

import hashlib
import json
import os
import sqlite3
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote

#: Read-only-Befehle (z. B. ``bach update migrations list``) setzen diesen
#: Schalter, damit der App-Start nicht selbst migriert (T-20260926-958264544).
NO_AUTO_MIGRATE_ENV = "BACH_NO_AUTO_MIGRATE"


#: Aufbewahrung der Runner-Sicherungen (nur Muster "<db>.premig-*.bak";
#: manuelle Sicherungen "<db>.pre-*.bak" bleiben unangetastet).
MIGRATION_BACKUP_KEEP = 5
#: Keine neue Sicherung, wenn die juengste für dieselbe Pending-Liste juenger
#: ist -- sonst sichert eine dauerhaft scheiternde Migration bei jedem Start
#: (CLAUDE.md-Lehre: 240 Backups / 123 GB durch einen Hook ohne Guard).
MIGRATION_BACKUP_REUSE_SECONDS = 600


class MigrationSelectionError(ValueError):
    """Eine Dateiauswahl ist nicht eindeutig, nicht verfuegbar oder unsicher."""


@dataclass(frozen=True)
class MigrationSourceSnapshot:
    name: str
    path: Path
    content: bytes
    sha256: str
    identity: tuple
    compiled: object | None = None


@dataclass(frozen=True)
class _CreatedPrivateFileState:
    file_identity: tuple
    size: int
    mtime_ns: int
    ctime_ns: int | None
    mode: int
    nlink: int
    sha256: str


def migration_filenames(migrations_dir) -> list[str]:
    """Kanonische, sortierte Namen der sichtbaren .sql/.py-Migrationen."""
    directory = Path(migrations_dir)
    if not directory.exists():
        return []
    return sorted(
        entry.name for entry in directory.iterdir()
        if entry.suffix in (".sql", ".py") and not entry.name.startswith("_")
    )


def _migration_entry_is_reparse(info) -> bool:
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & reparse)


def validate_migration_request(migrations_dir, available, only=None) -> list[str] | None:
    """Validiert Auswahlstrings und bekannte Eintraege ohne DB-Zugriff oder Mutation."""
    if only is None:
        return None
    if isinstance(only, (str, bytes)) or not isinstance(only, (list, tuple)) or not only:
        raise MigrationSelectionError("--only benötigt mindestens einen vollständigen Dateinamen")
    names = list(available)
    seen = set()
    for name in only:
        if type(name) is not str or not name or name in (".", ".."):
            raise MigrationSelectionError("Migrationsnamen müssen nichtleere Zeichenketten sein")
        if "/" in name or "\\" in name or Path(name).name != name:
            raise MigrationSelectionError("Pfade sind bei --only nicht erlaubt; erwartet wird der exakte Dateiname")
        if name.startswith("_") or Path(name).suffix not in (".sql", ".py"):
            raise MigrationSelectionError(f"Kein kanonischer Migrationsdateiname: {name}")
        if name in seen:
            raise MigrationSelectionError(f"Doppelter Migrationsname: {name}")
        seen.add(name)
        if name not in names:
            raise MigrationSelectionError(f"Unbekannte Migration: {name}")
        path = Path(migrations_dir) / name
        try:
            info = path.lstat()
        except OSError as exc:
            raise MigrationSelectionError(f"Migration nicht lesbar: {name}") from exc
        if _migration_entry_is_reparse(info) or not stat.S_ISREG(info.st_mode):
            raise MigrationSelectionError(f"Migration ist keine reguläre Datei: {name}")
    return list(only)


def read_applied_migration_filenames(db_path) -> set[str]:
    """Liest _migrations strikt readonly; fehlende DB/Tabelle bedeuten keine Buchungen."""
    path = Path(db_path)
    if not path.is_file():
        return set()
    uri = "file:" + quote(path.resolve().as_posix(), safe="/:\\") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    try:
        present = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='_migrations'"
        ).fetchone()
        if not present:
            return set()
        return {str(row[0]) for row in conn.execute("SELECT filename FROM _migrations")}
    finally:
        conn.close()


def select_pending_migration_names(available, applied, only=None) -> tuple[list[str], list[str], list[str]]:
    """Liefert pending, ausgewaehlt und unberuehrt in kanonischer Reihenfolge."""
    available = list(available)
    applied = set(applied)
    requested = None
    if only is not None:
        if isinstance(only, (str, bytes)) or not isinstance(only, (list, tuple)) or not only:
            raise MigrationSelectionError("--only benötigt mindestens einen vollständigen Dateinamen")
        seen = set()
        for name in only:
            if type(name) is not str or not name or "/" in name or "\\" in name or Path(name).name != name:
                raise MigrationSelectionError("Pfade sind bei --only nicht erlaubt; erwartet wird der exakte Dateiname")
            if name.startswith("_") or Path(name).suffix not in (".sql", ".py"):
                raise MigrationSelectionError(f"Kein kanonischer Migrationsdateiname: {name}")
            if name in seen:
                raise MigrationSelectionError(f"Doppelter Migrationsname: {name}")
            if name not in available:
                raise MigrationSelectionError(f"Unbekannte Migration: {name}")
            seen.add(name)
        requested = list(only)
    pending = [name for name in available if name not in applied]
    if requested is not None:
        already = [name for name in requested if name in applied]
        if already:
            raise MigrationSelectionError("Bereits angewandte Migration nicht auswählbar: " + ", ".join(already))
        requested_set = set(requested)
        selected = [name for name in pending if name in requested_set]
    else:
        selected = pending[:]
    selected_set = set(selected)
    untouched = [name for name in pending if name not in selected_set]
    return pending, selected, untouched


def _stat_mtime_ns(info) -> int:
    return getattr(info, "st_mtime_ns", int(info.st_mtime * 1e9))


def _stat_ctime_ns(info) -> int | None:
    # Windows path and open-handle ctime readings can differ for the same file.
    # File identity and a content hash remain the authoritative safety checks.
    if os.name == "nt":
        return None
    return getattr(info, "st_ctime_ns", int(info.st_ctime * 1e9))


def _stat_identity(info) -> tuple:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        _stat_mtime_ns(info),
        _stat_ctime_ns(info),
        stat.S_IMODE(info.st_mode),
        getattr(info, "st_nlink", 1),
    )


def snapshot_migration_sources(migrations_dir, names) -> dict[str, MigrationSourceSnapshot]:
    """Pinnt ausgewählte Quelldateien in Bytes und prüft Identität/Revisionshash."""
    directory = Path(migrations_dir)
    snapshots = {}
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    for name in names:
        path = directory / name
        try:
            before = path.lstat()
            if _migration_entry_is_reparse(before) or not stat.S_ISREG(before.st_mode):
                raise MigrationSelectionError(f"Migration ist keine reguläre Datei: {name}")
            fd = os.open(str(path), os.O_RDONLY | nofollow)
            try:
                opened = os.fstat(fd)
                if _migration_entry_is_reparse(opened) or not stat.S_ISREG(opened.st_mode):
                    raise MigrationSelectionError(f"Migration ist keine reguläre Datei: {name}")
                identity = _stat_identity(opened)
                if _stat_identity(before) != identity or getattr(opened, "st_nlink", 1) != 1:
                    raise MigrationSelectionError(f"Migrationsdatei wurde während der Prüfung geändert: {name}")
                with os.fdopen(fd, "rb", closefd=False) as handle:
                    content = handle.read()
            finally:
                os.close(fd)
            after = path.lstat()
            if _migration_entry_is_reparse(after) or _stat_identity(after) != identity:
                raise MigrationSelectionError(f"Migrationsdatei wurde während der Prüfung geändert: {name}")
            digest = hashlib.sha256(content).hexdigest()
            compiled = None
            if path.suffix == ".py":
                compiled = compile(content, str(path), "exec")
            else:
                content.decode("utf-8")
            snapshots[name] = MigrationSourceSnapshot(name, path, content, digest, identity, compiled)
        except MigrationSelectionError:
            raise
        except Exception as exc:
            raise MigrationSelectionError(f"Migrationsquelle konnte nicht sicher gelesen werden: {name}") from exc
    return snapshots


def verify_migration_source_snapshot(snapshot: MigrationSourceSnapshot) -> None:
    """Bricht vor Dispatch ab, wenn der aktuelle Dateipfad nicht mehr zur gelesenen Quelle passt."""
    path = snapshot.path
    try:
        info = path.lstat()
        if _migration_entry_is_reparse(info) or not stat.S_ISREG(info.st_mode):
            raise MigrationSelectionError(f"Migrationsquelle geändert: {snapshot.name}")
        fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            opened = os.fstat(fd)
            if _migration_entry_is_reparse(opened) or _stat_identity(opened) != snapshot.identity:
                raise MigrationSelectionError(f"Migrationsquelle geändert: {snapshot.name}")
            with os.fdopen(fd, "rb", closefd=False) as handle:
                digest = hashlib.sha256(handle.read()).hexdigest()
        finally:
            os.close(fd)
        after = path.lstat()
        if _migration_entry_is_reparse(after) or _stat_identity(after) != snapshot.identity or digest != snapshot.sha256:
            raise MigrationSelectionError(f"Migrationsquelle geändert: {snapshot.name}")
    except MigrationSelectionError:
        raise
    except Exception as exc:
        raise MigrationSelectionError(f"Migrationsquelle konnte nicht sicher erneut geprüft werden: {snapshot.name}") from exc


def execute_python_migration_snapshot(snapshot: MigrationSourceSnapshot, conn, db_path) -> None:
    """Fuehrt exakt die zuvor geprüften Python-Bytes ueber den bestehenden Dispatcher aus."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(f"mig_{Path(snapshot.name).stem}", snapshot.path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Kann {snapshot.name} nicht laden")
    module = importlib.util.module_from_spec(spec)
    exec(snapshot.compiled, module.__dict__)  # noqa: S102 - executes hash-pinned migration bytes
    dispatch_py_migration(module, conn, db_path)


def _posix_private_file_status(path: Path) -> bool:
    try:
        info = path.lstat()
        return (
            stat.S_ISREG(info.st_mode)
            and not _migration_entry_is_reparse(info)
            and info.st_nlink == 1
            and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o600
        )
    except (OSError, AttributeError):
        return False


def _windows_private_file_status(path: Path) -> bool:
    """Verifies owner SID and a protected, single-user DACL via native Win32 readback."""
    import ctypes
    from ctypes import wintypes

    if os.name != "nt":
        return False
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or _migration_entry_is_reparse(info)
            or getattr(info, "st_nlink", 0) != 1 or not getattr(info, "st_ino", 0)):
        return False
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    HANDLE = wintypes.HANDLE
    DWORD = wintypes.DWORD
    BOOL = wintypes.BOOL

    class SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", DWORD)]
    class TOKEN_USER(ctypes.Structure):
        _fields_ = [("User", SID_AND_ATTRIBUTES)]
    class ACL_SIZE_INFORMATION(ctypes.Structure):
        _fields_ = [("AceCount", DWORD), ("AclBytesInUse", DWORD), ("AclBytesFree", DWORD)]
    class ACE_HEADER(ctypes.Structure):
        _fields_ = [("AceType", ctypes.c_ubyte), ("AceFlags", ctypes.c_ubyte), ("AceSize", wintypes.WORD)]

    token = HANDLE()
    kernel.GetCurrentProcess.restype = HANDLE
    kernel.CloseHandle.argtypes = [HANDLE]; kernel.CloseHandle.restype = BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]; kernel.LocalFree.restype = ctypes.c_void_p
    advapi.OpenProcessToken.argtypes = [HANDLE, DWORD, ctypes.POINTER(HANDLE)]
    advapi.OpenProcessToken.restype = BOOL
    advapi.GetTokenInformation.argtypes = [HANDLE, ctypes.c_int, ctypes.c_void_p, DWORD, ctypes.POINTER(DWORD)]
    advapi.GetTokenInformation.restype = BOOL
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        return False
    try:
        needed = DWORD(0)
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(needed))
        if not needed.value:
            return False
        token_buffer = ctypes.create_string_buffer(needed.value)
        if not advapi.GetTokenInformation(token, 1, token_buffer, needed.value, ctypes.byref(needed)):
            return False
        user = ctypes.cast(token_buffer, ctypes.POINTER(TOKEN_USER)).contents
        user_sid = user.User.Sid
        kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, DWORD, DWORD, ctypes.c_void_p, DWORD, DWORD, HANDLE]
        kernel.CreateFileW.restype = HANDLE
        handle = kernel.CreateFileW(str(path), 0x00020000, 0x00000001 | 0x00000002 | 0x00000004, None, 3, 0x00200000, None)
        if handle == HANDLE(-1).value:
            return False
        try:
            owner = ctypes.c_void_p(); group = ctypes.c_void_p(); dacl = ctypes.c_void_p(); sacl = ctypes.c_void_p(); descriptor = ctypes.c_void_p()
            advapi.GetSecurityInfo.argtypes = [HANDLE, DWORD, DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
            advapi.GetSecurityInfo.restype = DWORD
            status = advapi.GetSecurityInfo(handle, 1, 0x00000005, ctypes.byref(owner), ctypes.byref(group), ctypes.byref(dacl), ctypes.byref(sacl), ctypes.byref(descriptor))
            if status != 0 or not descriptor.value or not dacl.value or not owner.value:
                return False
            try:
                control = wintypes.WORD(); revision = DWORD()
                advapi.GetSecurityDescriptorControl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.WORD), ctypes.POINTER(DWORD)]
                advapi.GetSecurityDescriptorControl.restype = BOOL
                if not advapi.GetSecurityDescriptorControl(descriptor, ctypes.byref(control), ctypes.byref(revision)) or not (control.value & 0x1000):
                    return False
                advapi.EqualSid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]; advapi.EqualSid.restype = BOOL
                if not advapi.EqualSid(owner, user_sid):
                    return False
                acl_size = ACL_SIZE_INFORMATION()
                advapi.GetAclInformation.argtypes = [ctypes.c_void_p, ctypes.c_void_p, DWORD, ctypes.c_int]
                advapi.GetAclInformation.restype = BOOL
                if not advapi.GetAclInformation(dacl, ctypes.byref(acl_size), ctypes.sizeof(acl_size), 2) or acl_size.AceCount != 1:
                    return False
                ace_ptr = ctypes.c_void_p()
                advapi.GetAce.argtypes = [ctypes.c_void_p, DWORD, ctypes.POINTER(ctypes.c_void_p)]
                advapi.GetAce.restype = BOOL
                if not advapi.GetAce(dacl, 0, ctypes.byref(ace_ptr)) or not ace_ptr.value:
                    return False
                header = ctypes.cast(ace_ptr, ctypes.POINTER(ACE_HEADER)).contents
                if header.AceType != 0 or header.AceFlags != 0 or header.AceSize < 8:
                    return False
                base = ace_ptr.value
                mask = ctypes.cast(base + ctypes.sizeof(ACE_HEADER), ctypes.POINTER(DWORD)).contents.value
                sid_in_ace = ctypes.c_void_p(base + ctypes.sizeof(ACE_HEADER) + ctypes.sizeof(DWORD))
                return mask == 0x001F01FF and bool(advapi.EqualSid(sid_in_ace, user_sid))
            finally:
                kernel.LocalFree(descriptor)
        finally:
            kernel.CloseHandle(handle)
    finally:
        kernel.CloseHandle(token)


def _private_file_status(path) -> bool:
    import ctypes

    path = Path(path)
    if os.name == "nt":
        try:
            return _windows_private_file_status(path)
        except (OSError, AttributeError, TypeError, ValueError, ctypes.ArgumentError):
            return False
    return _posix_private_file_status(path)


def _file_object_identity(info):
    """Returns a stable local file-object key, or None when the host cannot prove one."""
    if not stat.S_ISREG(info.st_mode) or _migration_entry_is_reparse(info):
        return None
    device = getattr(info, "st_dev", None)
    inode = getattr(info, "st_ino", None)
    if type(device) is not int or type(inode) is not int or inode <= 0:
        return None
    return (device, inode)


def _created_state_matches_stat(expected: _CreatedPrivateFileState, info) -> bool:
    return (
        _file_object_identity(info) == expected.file_identity
        and info.st_size == expected.size
        and _stat_mtime_ns(info) == expected.mtime_ns
        and _stat_ctime_ns(info) == expected.ctime_ns
        and stat.S_IMODE(info.st_mode) == expected.mode
        and getattr(info, "st_nlink", 1) == expected.nlink == 1
    )


def _created_private_file_state_from_fd(fd: int) -> _CreatedPrivateFileState | None:
    before = os.fstat(fd)
    identity = _file_object_identity(before)
    if identity is None or getattr(before, "st_nlink", 1) != 1:
        return None
    original_offset = None
    try:
        original_offset = os.lseek(fd, 0, os.SEEK_CUR)
        os.lseek(fd, 0, os.SEEK_SET)
        digest = hashlib.sha256()
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        after = os.fstat(fd)
    finally:
        if original_offset is not None:
            os.lseek(fd, original_offset, os.SEEK_SET)
    if _stat_identity(before) != _stat_identity(after):
        return None
    return _CreatedPrivateFileState(
        file_identity=identity,
        size=after.st_size,
        mtime_ns=_stat_mtime_ns(after),
        ctime_ns=_stat_ctime_ns(after),
        mode=stat.S_IMODE(after.st_mode),
        nlink=getattr(after, "st_nlink", 1),
        sha256=digest.hexdigest(),
    )


def _open_windows_restricted_read_fd(path: Path) -> int:
    """Opens one file object while denying concurrent write and delete handles."""
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    HANDLE = wintypes.HANDLE
    DWORD = wintypes.DWORD
    kernel.CreateFileW.argtypes = [
        ctypes.c_wchar_p, DWORD, DWORD, ctypes.c_void_p, DWORD, DWORD, HANDLE
    ]
    kernel.CreateFileW.restype = HANDLE
    kernel.CloseHandle.argtypes = [HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(
        str(path),
        0x80000000 | 0x00000080,  # GENERIC_READ | FILE_READ_ATTRIBUTES
        0x00000001,  # FILE_SHARE_READ only
        None,
        3,  # OPEN_EXISTING
        0x00200080,  # FILE_FLAG_OPEN_REPARSE_POINT | FILE_ATTRIBUTE_NORMAL
        None,
    )
    if handle == HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return msvcrt.open_osfhandle(handle, os.O_RDONLY)
    except BaseException:
        kernel.CloseHandle(handle)
        raise


def _capture_created_private_file_state(
    path: Path, expected_identity: tuple, *, expected_content: bytes | None = None
) -> _CreatedPrivateFileState | None:
    path = Path(path)
    fd = None
    try:
        before = path.lstat()
        if (_file_object_identity(before) != expected_identity
                or getattr(before, "st_nlink", 1) != 1):
            return None
        if os.name == "nt":
            fd = _open_windows_restricted_read_fd(path)
        else:
            fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        opened = os.fstat(fd)
        state = _created_private_file_state_from_fd(fd)
        after = path.lstat()
        if (state is None
                or state.file_identity != expected_identity
                or not _created_state_matches_stat(state, before)
                or not _created_state_matches_stat(state, opened)
                or not _created_state_matches_stat(state, after)):
            return None
        if expected_content is not None:
            if (state.size != len(expected_content)
                    or state.sha256 != hashlib.sha256(expected_content).hexdigest()):
                return None
        return state
    except (OSError, ValueError, TypeError):
        return None
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


def _cleanup_created_private_file_windows(
    path: Path, expected_state: _CreatedPrivateFileState
) -> bool:
    """Deletes the verified object by handle, without unlinking an open path."""
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    HANDLE = wintypes.HANDLE
    DWORD = wintypes.DWORD
    BOOL = wintypes.BOOL
    kernel.CreateFileW.argtypes = [
        ctypes.c_wchar_p, DWORD, DWORD, ctypes.c_void_p, DWORD, DWORD, HANDLE
    ]
    kernel.CreateFileW.restype = HANDLE
    kernel.CloseHandle.argtypes = [HANDLE]
    kernel.CloseHandle.restype = BOOL
    kernel.SetFileInformationByHandle.argtypes = [
        HANDLE, ctypes.c_int, ctypes.c_void_p, DWORD
    ]
    kernel.SetFileInformationByHandle.restype = BOOL

    before = path.lstat()
    if not _created_state_matches_stat(expected_state, before):
        return False
    # Deny new write/delete handles while the identity, bytes, and ACL are checked.
    handle = kernel.CreateFileW(
        str(path),
        0x00010000 | 0x80000000 | 0x00000080,  # DELETE | GENERIC_READ | READ_ATTRIBUTES
        0x00000001,  # FILE_SHARE_READ only
        None,
        3,  # OPEN_EXISTING
        0x00200000,  # FILE_FLAG_OPEN_REPARSE_POINT
        None,
    )
    if handle == HANDLE(-1).value:
        return False
    fd = None
    raw_handle = handle
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY)
        raw_handle = None  # fd now owns the Windows handle
        opened = os.fstat(fd)
        state = _created_private_file_state_from_fd(fd)
        current = path.lstat()
        if (state != expected_state
                or not _created_state_matches_stat(expected_state, opened)
                or not _created_state_matches_stat(expected_state, current)
                or not _windows_private_file_status(path)):
            return False
        final = path.lstat()
        if not _created_state_matches_stat(expected_state, final):
            return False
        class FILE_DISPOSITION_INFO(ctypes.Structure):
            _fields_ = [("DeleteFile", ctypes.c_ubyte)]
        disposition = FILE_DISPOSITION_INFO(True)
        current_handle = HANDLE(msvcrt.get_osfhandle(fd))
        if not kernel.SetFileInformationByHandle(
            current_handle, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)
        ):
            return False
        os.close(fd)
        fd = None
        return not os.path.lexists(str(path))
    except (OSError, ValueError, TypeError, AttributeError, ctypes.ArgumentError):
        return False
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if raw_handle is not None:
            kernel.CloseHandle(raw_handle)


def _cleanup_created_private_file(path: Path, expected_state) -> bool:
    """Removes only a still-identical private file with the recorded content hash.

    Replacement objects and in-place changes are preserved. Windows uses a
    restrictive DELETE handle and handle-based disposition; POSIX anchors the
    parent directory while checking object identity, metadata, and file bytes.
    """
    path = Path(path)
    if not isinstance(expected_state, _CreatedPrivateFileState):
        return False
    if os.name == "nt":
        try:
            return _cleanup_created_private_file_windows(path, expected_state)
        except (OSError, ValueError, TypeError, AttributeError):
            return False

    fd = None
    parent_fd = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        if os.open in getattr(os, "supports_dir_fd", set()):
            parent_fd = os.open(str(path.parent), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            before = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            if not _created_state_matches_stat(expected_state, before):
                return False
            fd = os.open(path.name, flags, dir_fd=parent_fd)
            opened = os.fstat(fd)
            state = _created_private_file_state_from_fd(fd)
            current = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            final = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            if (state != expected_state
                    or not _created_state_matches_stat(expected_state, opened)
                    or not _created_state_matches_stat(expected_state, current)
                    or not _created_state_matches_stat(expected_state, final)
                    or not _private_file_status(path)):
                return False
            final_check = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            if not _created_state_matches_stat(expected_state, final_check):
                return False
            os.unlink(path.name, dir_fd=parent_fd)
            return True
        before = path.lstat()
        if not _created_state_matches_stat(expected_state, before):
            return False
        fd = os.open(str(path), flags)
        opened = os.fstat(fd)
        state = _created_private_file_state_from_fd(fd)
        current = path.lstat()
        if (state != expected_state
                or not _created_state_matches_stat(expected_state, opened)
                or not _created_state_matches_stat(expected_state, current)
                or not _private_file_status(path)):
            return False
        final = path.lstat()
        if not _created_state_matches_stat(expected_state, final):
            return False
        path.unlink()
        return True
    except (OSError, ValueError, TypeError):
        return False
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if parent_fd is not None:
            try:
                os.close(parent_fd)
            except OSError:
                pass


def _source_file_fingerprint(path: Path, *, required: bool) -> dict:
    """Hashes one migration source file and proves its identity stayed stable."""
    path = Path(path)
    try:
        before = path.lstat()
    except FileNotFoundError:
        if required:
            raise RuntimeError("Migrationsdatenbank ist nicht verfügbar")
        try:
            path.lstat()
        except FileNotFoundError:
            return {"present": False}
        raise RuntimeError("Migrationsquelle änderte sich während der Prüfung")
    if not stat.S_ISREG(before.st_mode) or _migration_entry_is_reparse(before):
        raise RuntimeError("Migrationsquelle ist keine sichere reguläre Datei")
    if _file_object_identity(before) is None:
        raise RuntimeError("Dateiidentität der Migrationsquelle ist nicht verfügbar")
    fd = None
    try:
        fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        opened = os.fstat(fd)
        if (_file_object_identity(opened) != _file_object_identity(before)
                or _stat_identity(opened) != _stat_identity(before)):
            raise RuntimeError("Migrationsquelle änderte sich beim Öffnen")
        digest = hashlib.sha256()
        with os.fdopen(fd, "rb", closefd=False) as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        after_handle = os.fstat(fd)
        after_path = path.lstat()
        if (_stat_identity(after_handle) != _stat_identity(opened)
                or _stat_identity(after_path) != _stat_identity(opened)):
            raise RuntimeError("Migrationsquelle änderte sich während des Fingerprints")
        return {
            "present": True,
            "device": opened.st_dev,
            "inode": opened.st_ino,
            "size": opened.st_size,
            "mtime_ns": getattr(opened, "st_mtime_ns", int(opened.st_mtime * 1e9)),
            "ctime_ns": getattr(before, "st_ctime_ns", int(before.st_ctime * 1e9)),
            "mode": stat.S_IMODE(opened.st_mode),
            "nlink": getattr(opened, "st_nlink", 1),
            "sha256": digest.hexdigest(),
        }
    finally:
        if fd is not None:
            os.close(fd)


def _migration_source_state(db_path: Path) -> dict:
    db_path = Path(db_path)
    return {
        "db": _source_file_fingerprint(db_path, required=True),
        "wal": _source_file_fingerprint(db_path.with_name(db_path.name + "-wal"), required=False),
    }


def _same_source_state_with_empty_wal_transition(before: dict, after: dict) -> bool:
    """Accept an absent-to-empty WAL sidecar, never a data-bearing WAL change."""
    if before.get("db") != after.get("db"):
        return False
    if before.get("wal") == after.get("wal"):
        return True
    wal = after.get("wal")
    return (
        before.get("wal") == {"present": False}
        and isinstance(wal, dict)
        and wal.get("present") is True
        and wal.get("size") == 0
        and wal.get("sha256") == hashlib.sha256(b"").hexdigest()
    )



def _same_source_state_for_backup_reuse(proof_state: dict, current_state: dict) -> bool:
    """Allow an absent/empty-WAL transition only when the DB identity is exact."""
    if proof_state == current_state:
        return True
    if (not isinstance(proof_state, dict) or not isinstance(current_state, dict)
            or proof_state.get("db") != current_state.get("db")):
        return False
    proof_wal = proof_state.get("wal")
    current_wal = current_state.get("wal")
    empty_digest = hashlib.sha256(b"").hexdigest()

    def is_empty(wal):
        fields = {"present", "device", "inode", "size", "mtime_ns", "ctime_ns", "mode", "nlink", "sha256"}
        return (
            isinstance(wal, dict)
            and set(wal) == fields
            and wal.get("present") is True
            and type(wal.get("device")) is int
            and type(wal.get("inode")) is int
            and wal["inode"] > 0
            and type(wal.get("size")) is int
            and wal["size"] == 0
            and type(wal.get("mtime_ns")) is int
            and type(wal.get("ctime_ns")) is int
            and type(wal.get("mode")) is int
            and type(wal.get("nlink")) is int
            and wal["nlink"] == 1
            and wal.get("sha256") == empty_digest
        )

    return ((proof_wal == {"present": False} and is_empty(current_wal))
            or (current_wal == {"present": False} and is_empty(proof_wal)))

def _migration_source_state_sha256(source_state: dict) -> str:
    payload = json.dumps(source_state, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _create_private_file(path, content: bytes = b""):
    """Creates an exclusive private file and returns its proven object identity."""
    path = Path(path)
    created_identity = None
    created_state = None
    created = False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        HANDLE = wintypes.HANDLE
        DWORD = wintypes.DWORD
        BOOL = wintypes.BOOL
        class SID_AND_ATTRIBUTES(ctypes.Structure):
            _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", DWORD)]
        class TOKEN_USER(ctypes.Structure):
            _fields_ = [("User", SID_AND_ATTRIBUTES)]
        class SECURITY_ATTRIBUTES(ctypes.Structure):
            _fields_ = [("nLength", DWORD), ("lpSecurityDescriptor", ctypes.c_void_p), ("bInheritHandle", BOOL)]
        token = HANDLE()
        kernel.GetCurrentProcess.restype = HANDLE
        kernel.CloseHandle.argtypes = [HANDLE]
        kernel.CloseHandle.restype = BOOL
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        advapi.OpenProcessToken.argtypes = [HANDLE, DWORD, ctypes.POINTER(HANDLE)]
        advapi.OpenProcessToken.restype = BOOL
        advapi.GetTokenInformation.argtypes = [HANDLE, ctypes.c_int, ctypes.c_void_p, DWORD, ctypes.POINTER(DWORD)]
        advapi.GetTokenInformation.restype = BOOL
        if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
            raise ctypes.WinError(ctypes.get_last_error())
        descriptor = ctypes.c_void_p()
        sid_string = ctypes.c_wchar_p()
        written_bytes = b""
        try:
            needed = DWORD(0)
            advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(needed))
            token_buffer = ctypes.create_string_buffer(needed.value)
            if not advapi.GetTokenInformation(token, 1, token_buffer, needed.value, ctypes.byref(needed)):
                raise ctypes.WinError(ctypes.get_last_error())
            user_sid = ctypes.cast(token_buffer, ctypes.POINTER(TOKEN_USER)).contents.User.Sid
            advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
            advapi.ConvertSidToStringSidW.restype = BOOL
            if not advapi.ConvertSidToStringSidW(user_sid, ctypes.byref(sid_string)):
                raise ctypes.WinError(ctypes.get_last_error())
            sddl = f"O:{sid_string.value}D:P(A;;FA;;;{sid_string.value})"
            advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [ctypes.c_wchar_p, DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(DWORD)]
            advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = BOOL
            if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
                raise ctypes.WinError(ctypes.get_last_error())
            attrs = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), descriptor, False)
            kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, DWORD, DWORD, ctypes.POINTER(SECURITY_ATTRIBUTES), DWORD, DWORD, HANDLE]
            kernel.CreateFileW.restype = HANDLE
            handle = kernel.CreateFileW(str(path), 0x40000000 | 0x80000000 | 0x00020000, 0, ctypes.byref(attrs), 1, 0x00000080, None)
            if handle == HANDLE(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            created = True
            try:
                created_identity = _file_object_identity(path.lstat())
                if created_identity is None:
                    raise PermissionError("Windows-Dateiidentität konnte nicht bestätigt werden")
                if not _windows_private_file_status_from_handle(handle, user_sid):
                    raise PermissionError("Windows ACL readback did not prove private file access")
                if content:
                    written = DWORD(0)
                    buffer = ctypes.create_string_buffer(content)
                    kernel.WriteFile.argtypes = [HANDLE, ctypes.c_void_p, DWORD, ctypes.POINTER(DWORD), ctypes.c_void_p]
                    kernel.WriteFile.restype = BOOL
                    write_ok = kernel.WriteFile(handle, buffer, len(content), ctypes.byref(written), None)
                    written_bytes = content[:written.value]
                    if not write_ok or written.value != len(content):
                        raise ctypes.WinError(ctypes.get_last_error())
                    kernel.FlushFileBuffers.argtypes = [HANDLE]
                    kernel.FlushFileBuffers.restype = BOOL
                    if not kernel.FlushFileBuffers(handle):
                        raise ctypes.WinError(ctypes.get_last_error())
            finally:
                kernel.CloseHandle(handle)
            created_state = _capture_created_private_file_state(
                path, created_identity, expected_content=written_bytes
            )
            if created_state is None:
                raise PermissionError("Windows file state could not be bound to its written bytes")
            if not _windows_private_file_status(path):
                raise PermissionError("Windows ACL path readback did not prove private file access")
            return created_state
        except BaseException as exc:
            if created and created_state is None and created_identity is not None:
                created_state = _capture_created_private_file_state(
                    path, created_identity, expected_content=written_bytes
                )
            if created and not _cleanup_created_private_file(path, created_state):
                raise RuntimeError("Eine exklusiv erzeugte Datei blieb wegen nicht bestätigter Identität oder Dateiinhalts erhalten") from exc
            raise
        finally:
            if descriptor.value:
                kernel.LocalFree(descriptor)
            if sid_string:
                kernel.LocalFree(ctypes.cast(sid_string, ctypes.c_void_p))
            kernel.CloseHandle(token)

    fd = None
    written = bytearray()
    created_identity = None
    created_state = None
    created = False
    try:
        fd = os.open(str(path), os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
        opened = os.fstat(fd)
        created_identity = _file_object_identity(opened)
        if created_identity is None or _file_object_identity(path.lstat()) != created_identity:
            raise PermissionError("Dateiidentität konnte nach exklusiver Erstellung nicht bestätigt werden")
        os.fchmod(fd, 0o600)
        view = memoryview(content)
        while view:
            count = os.write(fd, view)
            if count <= 0:
                raise OSError("Datei konnte nicht vollständig geschrieben werden")
            written.extend(view[:count])
            view = view[count:]
        os.fsync(fd)
        os.close(fd)
        fd = None
        created_state = _capture_created_private_file_state(
            path, created_identity, expected_content=bytes(written)
        )
        if created_state is None:
            raise PermissionError("Dateizustand konnte nicht an die geschriebenen Bytes gebunden werden")
        if not _private_file_status(path):
            raise PermissionError("Dateiberechtigungen konnten nicht privat bestätigt werden")
        return created_state
    except BaseException as exc:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
            fd = None
        if created and created_state is None and created_identity is not None:
            created_state = _capture_created_private_file_state(
                path, created_identity, expected_content=bytes(written)
            )
        if created and not _cleanup_created_private_file(path, created_state):
            raise RuntimeError("Eine exklusiv erzeugte Datei blieb wegen nicht bestätigter Identität oder Dateiinhalts erhalten") from exc
        raise

def _windows_private_file_status_from_handle(handle, expected_sid) -> bool:
    """Checks owner and the protected single-user DACL on an already-open handle."""
    import ctypes
    from ctypes import wintypes
    advapi = ctypes.WinDLL("advapi32", use_last_error=True); kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    DWORD=wintypes.DWORD; BOOL=wintypes.BOOL
    class ACL_SIZE_INFORMATION(ctypes.Structure):
        _fields_=[("AceCount",DWORD),("AclBytesInUse",DWORD),("AclBytesFree",DWORD)]
    class ACE_HEADER(ctypes.Structure):
        _fields_=[("AceType",ctypes.c_ubyte),("AceFlags",ctypes.c_ubyte),("AceSize",wintypes.WORD)]
    owner=ctypes.c_void_p(); group=ctypes.c_void_p(); dacl=ctypes.c_void_p(); sacl=ctypes.c_void_p(); descriptor=ctypes.c_void_p()
    advapi.GetSecurityInfo.argtypes=[wintypes.HANDLE,DWORD,DWORD,ctypes.POINTER(ctypes.c_void_p),ctypes.POINTER(ctypes.c_void_p),ctypes.POINTER(ctypes.c_void_p),ctypes.POINTER(ctypes.c_void_p),ctypes.POINTER(ctypes.c_void_p)]; advapi.GetSecurityInfo.restype=DWORD
    if advapi.GetSecurityInfo(handle,1,0x00000005,ctypes.byref(owner),ctypes.byref(group),ctypes.byref(dacl),ctypes.byref(sacl),ctypes.byref(descriptor))!=0 or not descriptor.value or not dacl.value or not owner.value: return False
    try:
        control=wintypes.WORD(); revision=DWORD(); advapi.GetSecurityDescriptorControl.argtypes=[ctypes.c_void_p,ctypes.POINTER(wintypes.WORD),ctypes.POINTER(DWORD)]; advapi.GetSecurityDescriptorControl.restype=BOOL
        if not advapi.GetSecurityDescriptorControl(descriptor,ctypes.byref(control),ctypes.byref(revision)) or not(control.value&0x1000): return False
        advapi.EqualSid.argtypes=[ctypes.c_void_p,ctypes.c_void_p]; advapi.EqualSid.restype=BOOL
        if not advapi.EqualSid(owner,expected_sid): return False
        acl=ACL_SIZE_INFORMATION(); advapi.GetAclInformation.argtypes=[ctypes.c_void_p,ctypes.c_void_p,DWORD,ctypes.c_int]; advapi.GetAclInformation.restype=BOOL
        if not advapi.GetAclInformation(dacl,ctypes.byref(acl),ctypes.sizeof(acl),2) or acl.AceCount!=1: return False
        ace_ptr=ctypes.c_void_p(); advapi.GetAce.argtypes=[ctypes.c_void_p,DWORD,ctypes.POINTER(ctypes.c_void_p)]; advapi.GetAce.restype=BOOL
        if not advapi.GetAce(dacl,0,ctypes.byref(ace_ptr)) or not ace_ptr.value: return False
        header=ctypes.cast(ace_ptr,ctypes.POINTER(ACE_HEADER)).contents
        if header.AceType!=0 or header.AceFlags!=0 or header.AceSize<8: return False
        base=ace_ptr.value; mask=ctypes.cast(base+ctypes.sizeof(ACE_HEADER),ctypes.POINTER(DWORD)).contents.value
        sid=ctypes.c_void_p(base+ctypes.sizeof(ACE_HEADER)+ctypes.sizeof(DWORD))
        return mask==0x001F01FF and bool(advapi.EqualSid(sid,expected_sid))
    finally:
        kernel.LocalFree(descriptor)


def _migration_backups(db_path: Path) -> list:
    candidates = list(db_path.parent.glob(f"{db_path.name}.premig-*.bak"))
    def mtime(path):
        try:
            return path.lstat().st_mtime
        except OSError:
            return 0
    return sorted(candidates, key=mtime, reverse=True)


def _backup_proof_path(backup: Path) -> Path:
    return backup.with_name(backup.name + ".proof.json")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(str(path), flags)
    try:
        with os.fdopen(fd, "rb", closefd=False) as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    finally:
        os.close(fd)
    return digest.hexdigest()


def _quick_check_backup(path: Path) -> bool:
    uri = "file:" + quote(path.resolve().as_posix(), safe="/:\\") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    try:
        result = conn.execute("PRAGMA quick_check").fetchone()
        return bool(result and result[0] == "ok")
    finally:
        conn.close()


def _valid_backup_pair(backup: Path, expected_pending=None, *, expected_source_state=None, quick_check=True) -> bool:
    proof_path = _backup_proof_path(backup)
    if not _private_file_status(backup) or not _private_file_status(proof_path):
        return False
    try:
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        if not isinstance(proof, dict):
            return False
        common = {"schema", "backup_name", "pending", "pending_sha256", "backup_sha256", "created_at"}
        schema = proof.get("schema")
        if schema == "bach.migration-backup-proof.v1":
            if set(proof) != common or expected_source_state is not None:
                return False
        elif schema == "bach.migration-backup-proof.v2":
            if set(proof) != common | {"source_state", "source_state_sha256"}:
                return False
            state = proof.get("source_state")
            if (not isinstance(state, dict) or set(state) != {"db", "wal"}
                    or not isinstance(state.get("db"), dict) or state["db"].get("present") is not True
                    or not isinstance(state.get("wal"), dict) or type(state["wal"].get("present")) is not bool
                    or proof.get("source_state_sha256") != _migration_source_state_sha256(state)
                    or (expected_source_state is not None
                        and not _same_source_state_for_backup_reuse(state, expected_source_state))):
                return False
        else:
            return False
        pending = proof["pending"]
        if (proof["backup_name"] != backup.name
                or not isinstance(pending, list)
                or not all(type(name) is str and Path(name).name == name for name in pending)
                or proof["pending_sha256"] != hashlib.sha256("\n".join(pending).encode("utf-8")).hexdigest()
                or (expected_pending is not None and pending != list(expected_pending))
                or proof["backup_sha256"] != _sha256_file(backup)):
            return False
        return not quick_check or _quick_check_backup(backup)
    except (OSError, ValueError, TypeError, sqlite3.Error, RuntimeError):
        return False

def _delete_runner_backup_pair(backup: Path) -> bool:
    if not _valid_backup_pair(backup, quick_check=True):
        return False
    proof = _backup_proof_path(backup)
    try:
        before_backup = backup.lstat(); before_proof = proof.lstat()
        if not _private_file_status(backup) or not _private_file_status(proof):
            return False
        if _stat_identity(backup.lstat()) != _stat_identity(before_backup) or _stat_identity(proof.lstat()) != _stat_identity(before_proof):
            return False
        backup.unlink()
        proof.unlink()
        return True
    except OSError:
        return False


def backup_before_migration(db_path, pending) -> Path:
    """Creates a private WAL-safe backup bound to the exact source DB/WAL state.

    New backups use a v2 proof with content and filesystem identity fingerprints
    for the database and WAL. Legacy v1 proofs remain readable for retention but
    cannot authorize reuse because they do not bind the source state. Cleanup on
    failure is limited to file objects exclusively created by this invocation.
    """
    import time

    db_path = Path(db_path)
    names = list(pending)
    if (not names or any(type(name) is not str or not name or Path(name).name != name
                         or "/" in name or "\\" in name for name in names)
            or len(names) != len(set(names))):
        raise ValueError("pending muss eindeutige kanonische Migrationsdateinamen enthalten")
    key = hashlib.sha256("\n".join(names).encode("utf-8")).hexdigest()[:8]
    now = time.time()
    source_state = _migration_source_state(db_path)
    for existing in _migration_backups(db_path):
        try:
            mtime = existing.lstat().st_mtime
        except OSError:
            continue
        if (f"-{key}-" in existing.name
                and now - mtime < MIGRATION_BACKUP_REUSE_SECONDS
                and _valid_backup_pair(existing, names, expected_source_state=source_state, quick_check=True)
                and _migration_source_state(db_path) == source_state):
            return existing

    created_artifacts = []
    src = None
    dst = None
    target = None
    try:
        source_uri = "file:" + quote(db_path.resolve().as_posix(), safe="/:\\") + "?mode=ro"
        src = sqlite3.connect(source_uri, uri=True)
        state_after_open = _migration_source_state(db_path)
        if not _same_source_state_with_empty_wal_transition(source_state, state_after_open):
            raise RuntimeError("Datenbank oder WAL änderte sich beim Öffnen der Sicherungsquelle")
        source_state = state_after_open

        stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
        tag = Path(names[0]).stem
        safe_tag = "".join(c if c.isalnum() or c in "-_ ." else "_" for c in tag).replace(" ", "_")
        base = f"{db_path.name}.premig-{safe_tag}-{key}-{stamp}"
        for n in range(1, 100):
            candidate = db_path.with_name(f"{base}.bak" if n == 1 else f"{base}-{n}.bak")
            proof_path = _backup_proof_path(candidate)
            if candidate.exists() or candidate.is_symlink() or proof_path.exists() or proof_path.is_symlink():
                continue
            try:
                identity = _create_private_file(candidate)
                target = candidate
                created_artifacts.append((candidate, identity))
                break
            except FileExistsError:
                continue
        if target is None:
            raise RuntimeError(f"keine freie Sicherungsdatei für {base}")

        dst = sqlite3.connect(str(target))
        src.backup(dst)
        check = dst.execute("PRAGMA quick_check").fetchone()
        dst.close()
        dst = None
        refreshed_state = _capture_created_private_file_state(
            target, identity.file_identity
        )
        if refreshed_state is None:
            raise RuntimeError("Sicherungsdatei änderte sich nach dem SQLite-Backup")
        created_artifacts[-1] = (target, refreshed_state)
        src.close()
        src = None
        source_after = _migration_source_state(db_path)
        if not _same_source_state_with_empty_wal_transition(source_state, source_after):
            raise RuntimeError("Datenbank oder WAL änderte sich während der Sicherung")
        # SQLite may leave its own empty WAL sidecar after read-only backup.
        # Bind the proof to the observed post-backup state, including that file.
        source_state = source_after
        if not check or check[0] != "ok" or not _private_file_status(target) or not _quick_check_backup(target):
            raise RuntimeError("Sicherung konnte nicht mit quick_check und privaten Zugriffsrechten bestätigt werden")
        proof = {
            "schema": "bach.migration-backup-proof.v2",
            "backup_name": target.name,
            "pending": names,
            "pending_sha256": hashlib.sha256("\n".join(names).encode("utf-8")).hexdigest(),
            "backup_sha256": _sha256_file(target),
            "source_state": source_state,
            "source_state_sha256": _migration_source_state_sha256(source_state),
            "created_at": datetime.now().astimezone().isoformat(),
        }
        proof_path = _backup_proof_path(target)
        proof_identity = _create_private_file(proof_path, json.dumps(proof, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        created_artifacts.append((proof_path, proof_identity))
        if not _valid_backup_pair(target, names, expected_source_state=source_state, quick_check=True):
            raise RuntimeError("Sicherungsnachweis konnte nicht rückgelesen werden")
    except BaseException as exc:
        close_failed = False
        for connection in (dst, src):
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    close_failed = True
        dst = None
        src = None
        cleanup_failed = []
        if close_failed:
            cleanup_failed.extend(path.name for path, _identity in created_artifacts)
        else:
            for path, identity in reversed(created_artifacts):
                if not _cleanup_created_private_file(path, identity):
                    cleanup_failed.append(path.name)
        if cleanup_failed:
            raise RuntimeError("Sicherung fehlgeschlagen; mindestens eine exklusiv erzeugte Datei blieb wegen unbestätigter Identität erhalten") from exc
        raise
    finally:
        if dst is not None:
            dst.close()
        if src is not None:
            src.close()

    managed = [path for path in _migration_backups(db_path) if _valid_backup_pair(path, quick_check=True)]
    for old in managed[MIGRATION_BACKUP_KEEP:]:
        _delete_runner_backup_pair(old)
    return target

def dispatch_py_migration(mod, conn, db_path):
    """Ruft den Entry-Point einer .py-Migration auf — gemeinsame Konvention
    für core/db.py UND hub/update.py (Review BACH PR #10, Befund 2).

    Unterstuetzt: run_migration(conn) | run(conn) | migrate(db_path) |
    upgrade(db_path) | main(). migrate/upgrade nur bei genau einem
    Pflichtparameter (z. B. migrate_prompts.py braucht drei — das kann kein
    generischer Runner bedienen und MUSS laut scheitern statt still gebucht
    zu werden).
    """
    import inspect

    def _single_required_param(fn) -> bool:
        required = [
            p for p in inspect.signature(fn).parameters.values()
            if p.default is inspect.Parameter.empty
            and p.kind in (inspect.Parameter.POSITIONAL_ONLY,
                           inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        return len(required) == 1

    if hasattr(mod, "run_migration"):
        mod.run_migration(conn)
    elif hasattr(mod, "run"):
        mod.run(conn)
    elif hasattr(mod, "migrate") and _single_required_param(mod.migrate):
        mod.migrate(str(db_path))
    elif hasattr(mod, "upgrade") and _single_required_param(mod.upgrade):
        mod.upgrade(str(db_path))
    elif hasattr(mod, "main"):
        mod.main()
    else:
        raise RuntimeError(
            "Weder run_migration(conn), run(conn), migrate(db_path), "
            "upgrade(db_path) noch main() generisch aufrufbar — Migration "
            "wird NICHT als angewandt gebucht."
        )


class Database:
    """SQLite-Datenbank mit Connection Management und Migrationen."""

    def __init__(self, db_path: Path, schema_dir: Path):
        self.db_path = db_path
        self.schema_dir = schema_dir
        self._ensure_dir()

    def _ensure_dir(self):
        """Stellt sicher, dass DB-Verzeichnis existiert."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self, readonly: bool = False):
        """Context Manager für DB-Verbindung mit WAL und FK (oder PRAGMA query_only bei readonly=True)."""
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")  # 30 Sekunden in Millisekunden
        if readonly:
            conn.execute("PRAGMA query_only = ON")
            try:
                yield conn
            finally:
                conn.close()
        else:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    @contextmanager
    def connect_readonly(self):
        """Context Manager für strikt schreibgeschuetzte DB-Verbindungen (Gate G08: PRAGMA query_only = ON)."""
        with self.connect(readonly=True) as conn:
            yield conn

    def execute(self, sql: str, params: tuple = ()) -> list:
        """Fuehrt SQL aus und gibt Ergebnis als list[dict] zurueck."""
        with self.connect() as conn:
            cursor = conn.execute(sql, params)
            if sql.strip().upper().startswith("SELECT"):
                return [dict(row) for row in cursor.fetchall()]
            return []

    def execute_one(self, sql: str, params: tuple = ()) -> Optional[dict]:
        """Fuehrt SQL aus und gibt erste Zeile zurueck."""
        results = self.execute(sql, params)
        return results[0] if results else None

    def execute_scalar(self, sql: str, params: tuple = ()):
        """Fuehrt SQL aus und gibt einzelnen Wert zurueck."""
        with self.connect() as conn:
            row = conn.execute(sql, params).fetchone()
            return row[0] if row else None

    def execute_write(self, sql: str, params: tuple = ()) -> int:
        """Fuehrt INSERT/UPDATE/DELETE aus, gibt lastrowid zurueck."""
        with self.connect() as conn:
            cursor = conn.execute(sql, params)
            return cursor.lastrowid

    def is_empty(self) -> bool:
        """True, wenn die DB noch keine Nutzertabellen hat.

        _migrations, telemetry_counters und sqlite-interne Tabellen zaehlen nicht.
        Bestands-DBs duerfen init_schema() NICHT erneut bekommen: schema.sql
        enthaelt CREATE-Statements ohne IF NOT EXISTS und wuerde dort abbrechen.
        """
        if not self.db_path.exists() or self.db_path.stat().st_size == 0:
            return True
        count = self.execute_scalar(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
            "AND name NOT IN ('_migrations', 'telemetry_counters') "
            "AND name NOT LIKE 'sqlite_%'"
        )
        return not count

    def init_schema(self):
        """Erstellt die Tabellen aus schema.sql (nur für frische DBs gedacht).

        schema.sql enthaelt CREATE-Statements ohne IF NOT EXISTS — auf
        Bestands-DBs vorher is_empty() pruefen (siehe core/app.py).
        """
        is_new_db = not self.db_path.exists() or self.db_path.stat().st_size == 0
        schema_file = self.schema_dir / "schema.sql"
        if not schema_file.exists():
            return

        with self.connect() as conn:
            conn.executescript(schema_file.read_text(encoding="utf-8"))
            if is_new_db:
                self._apply_release_language_seed(conn)

    def _release_language_seed_candidates(self) -> list[Path]:
        """Moegliche Pfade für generierte Sprach-Seed-Dateien."""
        return [
            self.schema_dir.parent.parent / "exports" / "translations" / "languages_seed.release.sql",
            self.schema_dir.parent / "exports" / "translations" / "languages_seed.release.sql",
            self.schema_dir / "exports" / "translations" / "languages_seed.release.sql",
        ]

    def _apply_release_language_seed(self, conn: sqlite3.Connection):
        """Importiert generierte Sprach-Seeds bei frischer DB-Erstellung."""
        for seed_file in self._release_language_seed_candidates():
            if not seed_file.exists():
                continue
            conn.executescript(seed_file.read_text(encoding="utf-8"))
            break

    def baseline_migrations(self):
        """Bucht alle vorhandenen Migrationsdateien als angewandt — ohne Ausfuehrung.

        Fuer frische DBs direkt nach init_schema(): schema.sql traegt bereits den
        Endstand, die historischen Migrationen duerfen dort nie laufen (ALTER
        TABLE auf schon vorhandene Spalten wuerde krachen). Entspricht dem
        ueblichen "fake initial"-Muster.
        """
        migrations_dir = self.schema_dir / "migrations"
        if not migrations_dir.exists():
            return
        with self.connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS _migrations (
                    id INTEGER PRIMARY KEY,
                    filename TEXT UNIQUE NOT NULL,
                    applied_at TEXT NOT NULL
                )
            """)
            for mig_file in sorted(migrations_dir.glob("*")):
                if mig_file.suffix not in (".sql", ".py") or mig_file.name.startswith("_"):
                    continue
                conn.execute(
                    "INSERT OR IGNORE INTO _migrations (filename, applied_at) VALUES (?, ?)",
                    (mig_file.name, datetime.now().isoformat())
                )

    #: Markerzeile für reine Daten-Seeds unter den Migrationen (INSERT OR
    #: IGNORE, idempotent). baseline_migrations bucht sie auf frischen DBs nur;
    #: apply_seed_migrations fuehrt sie dort zusaetzlich aus (T-20260926-244294919).
    SEED_MARKER = "-- BACH-SEED: idempotent"

    def apply_seed_migrations(self) -> list:
        """Fuehrt die als Daten-Seed markierten .sql-Migrationen aus.

        Fuer frische DBs nach init_schema(): schema.sql traegt nur Struktur,
        keine Datenzeilen. Ohne diesen Schritt fehlten dort z. B. die
        context_triggers-Seeds (044/046/047) -- BACH bliebe still beim
        Injektor-Altpfad. Jede Seed-Datei muss idempotent sein. Ein
        fehlschlagender Seed wird gemeldet, die DB bleibt nutzbar.
        """
        migrations_dir = self.schema_dir / "migrations"
        applied = []
        if not migrations_dir.exists():
            return applied
        for mig_file in sorted(migrations_dir.glob("*.sql")):
            text = mig_file.read_text(encoding="utf-8")
            if self.SEED_MARKER not in text.splitlines()[:5]:
                continue
            try:
                with self.connect() as conn:
                    conn.executescript(text)
                applied.append(mig_file.name)
            except sqlite3.Error as e:
                print(f"  [WARNUNG] Daten-Seed {mig_file.name} fehlgeschlagen: {e}")
        return applied

    def migration_backlog(self) -> list:
        """Ausstehende Migrationen, die AELTER sind als der juengste gebuchte
        Stand — das Kennzeichen einer Bestands-DB ohne Baseline.

        Eine solche DB darf der App-Start NICHT automatisch scharf migrieren
        (Review PR #10, Befund 1 — empirisch belegt am Produktiv-DB-Vorfall
        2026-09-01): der Rueckstand wird kontrolliert per
        `bach update migrations baseline [--through NNN]` gebucht. Regulaer
        nachgezogene DBs haben nur Migrationen NEUER als der letzte gebuchte
        nummerierte Stand als pending — die laufen weiterhin automatisch.
        """
        migrations_dir = self.schema_dir / "migrations"
        if not migrations_dir.exists():
            return []
        with self.connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS _migrations (
                    id INTEGER PRIMARY KEY,
                    filename TEXT UNIQUE NOT NULL,
                    applied_at TEXT NOT NULL
                )
            """)
            applied = {row[0] for row in
                       conn.execute("SELECT filename FROM _migrations").fetchall()}

        def _num_prefix(name: str):
            prefix = name.split("_", 1)[0]
            return int(prefix) if prefix.isdigit() else None

        applied_nums = [n for n in (_num_prefix(a) for a in applied) if n is not None]
        max_applied = max(applied_nums) if applied_nums else -1

        backlog = []
        for mig_file in sorted(migrations_dir.glob("*")):
            if mig_file.suffix not in (".sql", ".py") or mig_file.name.startswith("_"):
                continue
            if mig_file.name in applied:
                continue
            num = _num_prefix(mig_file.name)
            if num is None:
                # nicht-nummerierte pending zaehlen als Rueckstand, sobald die
                # DB ueberhaupt schon nummerierte Buchungen hat (Bestands-DB)
                if max_applied >= 0:
                    backlog.append(mig_file.name)
            elif num <= max_applied:
                backlog.append(mig_file.name)
            elif max_applied < 0:
                # nicht-leere DB ganz ohne Buchungen: ALLES ist Rueckstand
                backlog.append(mig_file.name)
        return backlog

    def run_migrations(self, only=None):
        """Runs pending migrations, optionally selecting exact canonical filenames.

        The default remains the complete pending chain. Explicit selections are
        validated and pinned before backup or tracking writes, then executed in
        canonical filename order through the existing migration dispatcher.
        """
        migrations_dir = self.schema_dir / "migrations"
        applied_now: list[str] = []
        if not migrations_dir.exists():
            return applied_now, None
        try:
            available = migration_filenames(migrations_dir)
            validate_migration_request(migrations_dir, available, only)
            applied = read_applied_migration_filenames(self.db_path)
            pending, selected, _untouched = select_pending_migration_names(available, applied, only)
            snapshots = snapshot_migration_sources(migrations_dir, selected)
            for source in snapshots.values():
                verify_migration_source_snapshot(source)
        except Exception as exc:  # noqa: BLE001 - fail closed on any preflight failure
            return applied_now, f"Migrationsauswahl vor Änderungen abgewiesen ({type(exc).__name__}): {exc}"
        # Keep the historical runner order: create tracking before the backup,
        # but only after an explicit selection has passed every preflight check.
        try:
            with self.connect() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS _migrations (
                        id INTEGER PRIMARY KEY,
                        filename TEXT UNIQUE NOT NULL,
                        applied_at TEXT NOT NULL
                    )
                """)
        except (OSError, sqlite3.Error) as exc:
            return applied_now, f"Migrations-Tracking konnte nicht vorbereitet werden ({type(exc).__name__}): {exc}"

        if not pending:
            return applied_now, None
        if only is not None and not selected:
            return applied_now, "Keine ausstehenden ausgewählten Migrationen."
        if not selected:
            return applied_now, None

        if self.db_path.exists() and self.db_path.stat().st_size > 0:
            try:
                backup = backup_before_migration(self.db_path, selected)
                print(f"  Sicherung vor Migration: {backup}")
            except Exception as exc:  # noqa: BLE001 - backup must fail closed on any storage/API error
                error = (f"Sicherung vor Migration fehlgeschlagen ({type(exc).__name__}: {exc}) "
                         f"-- keine Migration ausgeführt. Ausgewählt: "
                         + ", ".join(selected[:5]))
                print(f"  [!!] {error}")
                return applied_now, error

        try:
            for source in snapshots.values():
                verify_migration_source_snapshot(source)
        except MigrationSelectionError as exc:
            return applied_now, f"Migrationsquelle vor Ausführung geändert ({type(exc).__name__}): {exc}"

        for name in selected:
            source = snapshots[name]
            print(f"  Migration: {name}")
            try:
                with self.connect() as conn:
                    if source.path.suffix == ".sql":
                        conn.executescript(source.content.decode("utf-8"))
                    else:
                        execute_python_migration_snapshot(source, conn, self.db_path)
                    conn.execute(
                        "INSERT INTO _migrations (filename, applied_at) VALUES (?, ?)",
                        (name, datetime.now().isoformat())
                    )
            except Exception as exc:
                error = (
                    f"Migration {name} fehlgeschlagen: {exc} — Kette gestoppt. "
                    f"Bestands-DB? Rückstand per 'bach update migrations baseline "
                    f"[--through NNN]' buchen, dann neu starten."
                )
                print(f"  [!!] {error}")
                return applied_now, error
            applied_now.append(name)
        return applied_now, None

    def table_exists(self, name: str) -> bool:
        """Prueft ob Tabelle existiert."""
        result = self.execute_scalar(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
            (name,)
        )
        return result > 0

    def tables(self) -> list:
        """Gibt alle Tabellennamen zurueck."""
        rows = self.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        return [r["name"] for r in rows]

    def row_count(self, table: str) -> int:
        """Gibt Zeilenanzahl einer Tabelle zurueck."""
        return self.execute_scalar(f"SELECT COUNT(*) FROM [{table}]") or 0


def get_db_connection(db_path: Path) -> sqlite3.Connection:
    """
    Erstellt SQLite-Connection mit optimalen Einstellungen.

    Fixes BUG-HQ5-B-001: Database Lock durch fehlende Timeouts.

    Args:
        db_path: Pfad zur Datenbank

    Returns:
        Konfigurierte SQLite-Connection

    Settings:
        - 30s Connection-Timeout (für OneDrive-Sync-Konflikte)
        - WAL-Mode (Write-Ahead Logging)
        - Foreign Keys aktiviert
        - 30s Busy-Timeout (für concurrent access)
    """
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")  # 30 Sekunden
    return conn
