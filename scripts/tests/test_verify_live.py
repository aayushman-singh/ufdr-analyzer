import json
import ctypes
import contextvars
from contextlib import contextmanager
from datetime import datetime
import errno
import hashlib
import os
import re
import shutil
import socket
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
import release
import verify_live
from ai.planner import plan_question
from ai.query_pipeline import run_plan
from db_setup import AleappArtifact, Message
from sqlmodel import Session, SQLModel, create_engine


ROOT = Path(__file__).resolve().parents[2]


class _PlatformBoundary:
    def __init__(self, name):
        self._name = contextvars.ContextVar("citespan_test_platform_name", default=name)

    @property
    def name(self):
        return self._name.get()

    @name.setter
    def name(self, value):
        self._name.set(value)


_PLATFORM = _PlatformBoundary(os.name)


@contextmanager
def _platform_context(name):
    token = _PLATFORM._name.set(name)
    try:
        yield
    finally:
        _PLATFORM._name.reset(token)


def test_platform_boundary_keeps_native_pathlib_and_cache_paths():
    native_path_type = type(Path.cwd())
    with _platform_context("posix"):
        assert _PLATFORM.name == "posix"
        assert os.name == "nt"
        cache_path = Path("pytest-root") / ".pytest_cache" / "v" / "cache"
        assert type(cache_path) is native_path_type
        assert cache_path.parts[-3:] == (".pytest_cache", "v", "cache")
    assert _PLATFORM.name == os.name
    assert type(Path("after-success")) is native_path_type


def test_platform_boundary_restores_after_failure():
    with pytest.raises(RuntimeError, match="platform fixture failure"):
        with _platform_context("posix"):
            raise RuntimeError("platform fixture failure")
    assert _PLATFORM.name == os.name
    assert type(Path("after-failure")) is type(Path.cwd())


def test_platform_boundary_is_not_visible_to_concurrent_contexts():
    observed = []
    barrier = threading.Barrier(2)

    def observe_platform():
        barrier.wait()
        observed.append(_PLATFORM.name)

    with _platform_context("posix"):
        worker = threading.Thread(target=observe_platform)
        worker.start()
        barrier.wait()
        worker.join(timeout=5)

    assert observed == [os.name]


class ProcessIdentityAbsent(RuntimeError):
    """The identity query completed and found no current process for the PID."""


class ProcessIdentityReadError(RuntimeError):
    """The identity query did not produce trustworthy process evidence."""


def test_live_verifier_requires_the_project_virtual_environment(monkeypatch):
    monkeypatch.setattr(verify_live.sys, "executable", str(ROOT / "other-python.exe"))
    with pytest.raises(RuntimeError, match="project virtual-environment Python"):
        verify_live._require_project_python()


def test_live_verifier_requires_the_pinned_python_playwright_version(monkeypatch):
    monkeypatch.setattr(verify_live.importlib.metadata, "version", lambda name: "1.62.1")
    with pytest.raises(RuntimeError, match="requires Python Playwright 1.55.0, found 1.62.1"):
        verify_live._require_python_playwright_version()


def test_live_verifier_rejects_missing_python_playwright_metadata(monkeypatch):
    def missing(_name):
        raise verify_live.importlib.metadata.PackageNotFoundError("playwright")

    monkeypatch.setattr(verify_live.importlib.metadata, "version", missing)
    with pytest.raises(RuntimeError, match="requires Python Playwright 1.55.0"):
        verify_live._require_python_playwright_version()


def test_browser_verifier_delegates_host_process_validation(monkeypatch):
    expected = {"native_resource": "restored", "historical_identities": 145}
    calls = []

    def validate():
        calls.append(True)
        return expected

    monkeypatch.setattr(release, "_validate_host_process_evidence", validate)

    assert verify_live._validate_host_process_contract() == expected
    assert calls == [True]


def test_main_stops_at_host_process_guard_before_browser_or_network_side_effects(monkeypatch):
    events = []

    def reject_host_process_evidence():
        events.append("host-process-guard")
        raise RuntimeError("host process evidence failed: bounded failure context")

    monkeypatch.setattr(verify_live, "_validate_host_process_contract", reject_host_process_evidence)
    monkeypatch.setattr(verify_live, "_require_project_python", lambda: events.append("python"))
    monkeypatch.setattr(verify_live, "_require_python_playwright_version", lambda: events.append("playwright-version"))
    monkeypatch.setattr(verify_live, "_run_browser_flow", lambda *args: events.append("browser"))
    monkeypatch.setattr(
        release,
        "_validate_browser_dependency_readiness",
        lambda *_args: events.append("dependency-readiness"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_live.py",
            "--url",
            verify_live.AUTHORIZED_LIVE_ORIGIN,
            "--run-id",
            verify_live.CANONICAL_DEMO_RUN_ID,
            "--deployment-id",
            "citespan-test",
        ],
    )

    with pytest.raises(RuntimeError, match="host process evidence failed: bounded failure context"):
        verify_live.main()

    assert events == ["host-process-guard"]


class _BrowserResourceProbe:
    def __init__(self, name, events, error=None):
        self.name = name
        self.events = events
        self.error = error
        self.close_count = 0

    def close(self):
        self.close_count += 1
        self.events.append(self.name)
        if self.error is not None:
            raise self.error


def test_browser_flow_closes_page_context_and_browser_and_preserves_primary_error():
    events = []
    page = _BrowserResourceProbe("page", events, RuntimeError("page close failed"))
    context = _BrowserResourceProbe("context", events, RuntimeError("context close failed"))
    browser = _BrowserResourceProbe("browser", events)
    primary = RuntimeError("query failed")

    with pytest.raises(RuntimeError, match="primary browser scenario failure: query failed") as raised:
        cleanup = verify_live._close_browser_resources(page, context, browser, "live browser flow")
        verify_live._raise_browser_flow_errors(primary, cleanup)

    assert "page close failed" in str(raised.value)
    assert "context close failed" in str(raised.value)
    assert raised.value.__cause__ is primary
    assert events == ["page", "context", "browser"]
    assert page.close_count == context.close_count == browser.close_count == 1


def test_browser_flow_cleanup_handles_partial_initialization():
    events = []
    context = _BrowserResourceProbe("context", events)

    cleanup = verify_live._close_browser_resources(None, context, None, "live browser flow")

    assert cleanup == []
    assert events == ["context"]
    assert context.close_count == 1


def _remove_owned_fixture(path: Path, label: str) -> None:
    root = path.resolve()

    def normalize_permissions():
        if not path.exists():
            return
        for directory, directory_names, file_names in os.walk(path, topdown=True, followlinks=False):
            directory_path = Path(directory)
            resolved_directory = directory_path.resolve(strict=False)
            if resolved_directory != root and root not in resolved_directory.parents:
                raise RuntimeError(f"{label} cleanup failed: path escapes fixture root {root}: {directory_path}")
            os.chmod(directory_path, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
            for name in sorted(directory_names + file_names):
                candidate = directory_path / name
                resolved = candidate.resolve(strict=False)
                if resolved != root and root not in resolved.parents:
                    raise RuntimeError(f"{label} cleanup failed: path escapes fixture root {root}: {candidate}")
                if candidate.is_symlink():
                    continue
                mode = stat.S_IWRITE | stat.S_IREAD
                if candidate.is_dir():
                    mode |= stat.S_IEXEC
                os.chmod(candidate, mode)

    def cleanup_error(operation, failed_path, exc_info):
        candidate = Path(failed_path).resolve(strict=False)
        error = exc_info[1]
        if candidate != root and root not in candidate.parents:
            raise RuntimeError(
                f"{label} cleanup failed: operation={operation.__name__} path={candidate}: path escapes fixture root {root}"
            ) from error
        if not isinstance(error, OSError) or error.errno not in (errno.EACCES, errno.EPERM, errno.EROFS):
            raise RuntimeError(
                f"{label} cleanup failed: operation={operation.__name__} path={candidate}: {error}"
            ) from error
        print(
            f"{label} cleanup correction: operation={operation.__name__} path={candidate} "
            f"error_type={type(error).__name__} error={error}",
            file=sys.stderr,
            flush=True,
        )
        try:
            mode = stat.S_IWRITE | stat.S_IREAD
            if candidate.is_dir():
                mode |= stat.S_IEXEC
            os.chmod(candidate, mode)
            operation(failed_path)
        except Exception as retry_error:
            raise RuntimeError(
                f"{label} cleanup failed: operation={operation.__name__} path={candidate}: retry failed: {retry_error}"
            ) from retry_error

    try:
        normalize_permissions()
        shutil.rmtree(path, onerror=cleanup_error)
    except Exception as exc:
        raise RuntimeError(f"{label} cleanup failed: operation=rmtree path={path}: {exc}") from exc
    if path.exists():
        raise RuntimeError(f"{label} cleanup failed: operation=rmtree path={path}: path remains")


def _launch_process_tree(argv, *, cwd=None, env=None):
    output_fd, output_name = tempfile.mkstemp(prefix="citespan-process-", suffix=".log")
    os.close(output_fd)
    output_path = Path(output_name)
    output_file = output_path.open("wb")
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if _PLATFORM.name == "nt" else 0
    launch_env = os.environ.copy() if env is None else env.copy()
    launch_env["CITESPAN_TEST_PROCESS_OWNER"] = uuid.uuid4().hex
    expected_cwd = str(Path(cwd or ROOT).resolve())
    effective_argv = [str(item) for item in argv]
    if _PLATFORM.name == "nt":
        child_argv = [
            os.environ.get("COMSPEC", "cmd.exe"),
            "/d",
            "/s",
            "/c",
            *effective_argv,
        ]
        anchor_code = (
            "import os, subprocess, sys; "
            "comspec, disable_extensions, strip_quotes, command_switch, *target = sys.argv[1:]; "
            "assert (disable_extensions, strip_quotes, command_switch) == ('/d', '/s', '/c'), 'invalid cmd contract'; "
            "command = subprocess.list2cmdline(target); "
            "child = subprocess.Popen(f'\"{comspec}\" /d /s /c cd /d \"{os.getcwd()}\" && {command}'); "
            "raise SystemExit(child.wait())"
        )
        effective_argv = [
            sys.executable,
            "-c",
            anchor_code,
            *child_argv,
        ]
    try:
        process = subprocess.Popen(
            effective_argv,
            cwd=cwd,
            env=launch_env,
            stdout=output_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            start_new_session=_PLATFORM.name != "nt",
        )
    except Exception:
        output_file.close()
        output_path.unlink(missing_ok=True)
        raise
    output_file.close()
    process._citespan_output_path = output_path
    process._citespan_owner = {
        "cwd": expected_cwd,
        "argv": [str(item) for item in argv],
        "effective_argv": effective_argv,
        "pid": process.pid,
        "owner_marker": launch_env["CITESPAN_TEST_PROCESS_OWNER"],
        "creation_identity": None,
        "descendant_identities": {},
    }
    while True:
        try:
            creation_identity = _process_metadata(process.pid)
            break
        except RuntimeError as exc:
            if process.poll() is not None:
                output = _read_process_output(process)
                raise RuntimeError(
                    f"process launch failed before identity capture for pid {process.pid}: "
                    f"returncode={process.returncode} error={exc}; process evidence={output[-4000:]}"
                ) from exc
            cleanup_error = None
            try:
                _terminate_unverified_process_tree(process, "process identity capture")
            except RuntimeError as cleanup_exc:
                cleanup_error = cleanup_exc
            evidence = _read_process_output(process, retain=True)
            raise RuntimeError(
                f"process identity capture failed for live pid {process.pid}: {exc}; "
                f"process evidence={evidence[-4000:]}; cleanup={cleanup_error}"
            ) from exc
    process._citespan_owner["creation_identity"] = creation_identity
    return process


def _process_metadata(pid):
    if _PLATFORM.name == "nt":
        command = (
            "$p = Get-CimInstance Win32_Process -Filter 'ProcessId = "
            f"{pid}'; "
            " if ($null -eq $p) { exit 3 }; $p | Select-Object ProcessId,ParentProcessId,"
            "CreationDate,ExecutablePath,CommandLine | ConvertTo-Json -Compress"
        )
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProcessIdentityReadError(
                f"process identity lookup timed out for pid {pid}: timeout={exc.timeout}s "
                f"stdout={getattr(exc, 'stdout', '')[-2000:]} stderr={getattr(exc, 'stderr', '')[-2000:]}"
            ) from exc
        if result.returncode == 3 and not result.stdout.strip() and not result.stderr.strip():
            raise ProcessIdentityAbsent(f"process identity absent for pid {pid}: rc=3")
        if result.returncode != 0:
            raise ProcessIdentityReadError(
                f"process identity lookup failed for pid {pid}: rc={result.returncode} "
                f"stdout={result.stdout[-2000:]} stderr={result.stderr[-2000:]}"
            )
        try:
            metadata = json.loads(result.stdout)
            metadata = {
                "pid": int(metadata["ProcessId"]),
                "parent_pid": int(metadata["ParentProcessId"]),
                "creation": _windows_creation_token(pid),
                "executable": str(metadata.get("ExecutablePath") or ""),
                "command": str(metadata.get("CommandLine") or ""),
                "cwd": _windows_current_working_directory(pid),
            }
            parsed = _windows_command_line_argv(metadata["command"])
            metadata["argv"] = parsed
            metadata["argv_sha256"] = hashlib.sha256("\0".join(parsed).encode("utf-8")).hexdigest()
            metadata["native_command_sha256"] = hashlib.sha256(
                metadata["command"].encode("utf-8")
            ).hexdigest()
            return metadata
        except ProcessIdentityReadError:
            raise
        except (KeyError, TypeError, ValueError, RuntimeError) as exc:
            raise ProcessIdentityReadError(
                f"process identity query returned malformed output for pid {pid}: "
                f"stdout={result.stdout[-2000:]} stderr={result.stderr[-2000:]}"
            ) from exc
    proc_root = Path("/proc") / str(pid)
    if not proc_root.exists():
        raise ProcessIdentityAbsent(f"process identity absent for pid {pid}: proc entry missing")
    try:
        stat_fields = (proc_root / "stat").read_text(encoding="utf-8").split()
        command = (proc_root / "cmdline").read_bytes().replace(b"\x00", b" ").decode(errors="replace").strip()
        metadata = {
            "pid": pid,
            "parent_pid": int(stat_fields[3]),
            "creation": stat_fields[21],
            "executable": str((proc_root / "exe").resolve()),
            "command": command,
            "cwd": str((proc_root / "cwd").resolve()),
        }
        parsed = command.split()
        metadata["argv"] = parsed
        metadata["argv_sha256"] = hashlib.sha256("\0".join(parsed).encode("utf-8")).hexdigest()
        metadata["native_command_sha256"] = hashlib.sha256(command.encode("utf-8")).hexdigest()
        return metadata
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise ProcessIdentityReadError(f"process identity lookup failed for pid {pid}: {exc}") from exc


def _windows_creation_token(pid):
    if _PLATFORM.name != "nt":
        raise RuntimeError("Windows creation token requested on a non-Windows host")

    class FileTime(ctypes.Structure):
        _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.GetProcessTimes.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
    ]
    kernel32.GetProcessTimes.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    handle = kernel32.OpenProcess(0x1000, 0, pid)
    if not handle:
        error = ctypes.get_last_error()
        raise RuntimeError(f"exact process identity read failed for pid {pid}: WinError {error}")
    creation = FileTime()
    exit_time = FileTime()
    kernel_time = FileTime()
    user_time = FileTime()
    try:
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            error = ctypes.get_last_error()
            raise RuntimeError(f"exact process identity read failed for pid {pid}: WinError {error}")
        return str((creation.high << 32) | creation.low)
    finally:
        kernel32.CloseHandle(handle)


def _windows_current_working_directory(pid):
    if _PLATFORM.name != "nt":
        raise RuntimeError("Windows current-directory lookup requested on a non-Windows host")

    class ProcessBasicInformation(ctypes.Structure):
        _fields_ = [("exit_status", ctypes.c_void_p), ("peb", ctypes.c_void_p), ("affinity", ctypes.c_void_p), ("base_priority", ctypes.c_long), ("process_id", ctypes.c_void_p), ("parent_process_id", ctypes.c_void_p)]

    class UnicodeString(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ushort), ("maximum_length", ctypes.c_ushort), ("buffer", ctypes.c_void_p)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    kernel32.ReadProcessMemory.restype = ctypes.c_int
    kernel32.DuplicateHandle.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.DuplicateHandle.restype = ctypes.c_int
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.GetFinalPathNameByHandleW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32]
    kernel32.GetFinalPathNameByHandleW.restype = ctypes.c_uint32
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    ntdll.NtQueryInformationProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)]
    ntdll.NtQueryInformationProcess.restype = ctypes.c_long
    process = kernel32.OpenProcess(0x1050, 0, pid)
    if not process:
        raise RuntimeError(f"actual current cwd read failed for pid {pid}: OpenProcess WinError {ctypes.get_last_error()}")

    def read(address, target):
        count = ctypes.c_size_t()
        if not kernel32.ReadProcessMemory(process, ctypes.c_void_p(address), ctypes.byref(target), ctypes.sizeof(target), ctypes.byref(count)):
            raise RuntimeError(f"actual current cwd read failed for pid {pid}: ReadProcessMemory WinError {ctypes.get_last_error()}")

    try:
        basic = ProcessBasicInformation()
        returned = ctypes.c_ulong()
        status = ntdll.NtQueryInformationProcess(process, 0, ctypes.byref(basic), ctypes.sizeof(basic), ctypes.byref(returned))
        if status != 0 or not basic.peb:
            raise RuntimeError(f"actual current cwd read failed for pid {pid}: NtQueryInformationProcess status={status}")
        pointer_type = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32
        parameters = pointer_type()
        read(int(basic.peb) + (0x20 if ctypes.sizeof(ctypes.c_void_p) == 8 else 0x10), parameters)
        if not parameters.value:
            raise RuntimeError(f"actual current cwd read failed for pid {pid}: process parameters are unavailable")
        directory = UnicodeString()
        read(int(parameters.value) + (0x38 if ctypes.sizeof(ctypes.c_void_p) == 8 else 0x24), directory)
        if not directory.buffer or not directory.length:
            raise RuntimeError(f"actual current cwd read failed for pid {pid}: current directory path is unavailable")
        remote_handle = ctypes.c_void_p()
        read(int(parameters.value) + (0x48 if ctypes.sizeof(ctypes.c_void_p) == 8 else 0x2C), remote_handle)
        if not remote_handle.value:
            raise RuntimeError(f"actual current cwd read failed for pid {pid}: current directory handle is unavailable")
        duplicated = ctypes.c_void_p()
        if not kernel32.DuplicateHandle(process, remote_handle, kernel32.GetCurrentProcess(), ctypes.byref(duplicated), 0, 0, 2):
            raise RuntimeError(f"actual current cwd read failed for pid {pid}: DuplicateHandle WinError {ctypes.get_last_error()}")
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            length = kernel32.GetFinalPathNameByHandleW(duplicated, buffer, len(buffer), 0)
            if not length or length >= len(buffer):
                raise RuntimeError(f"actual current cwd read failed for pid {pid}: GetFinalPathNameByHandleW WinError {ctypes.get_last_error()}")
            value = buffer.value
            return value[4:] if value.startswith("\\\\?\\") else value
        finally:
            kernel32.CloseHandle(duplicated)
    finally:
        kernel32.CloseHandle(process)


def _current_process_tree(root_pid):
    if _PLATFORM.name == "nt":
        command = (
            "Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,CreationDate,"
            "ExecutablePath,CommandLine | ConvertTo-Json -Compress"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"process tree lookup failed: rc={result.returncode} stdout={result.stdout[-2000:]} "
                f"stderr={result.stderr[-2000:]}"
            )
        raw = json.loads(result.stdout)
        rows = raw if isinstance(raw, list) else [raw]
        process_graph = {}
        for row in rows:
            if row.get("ProcessId") is None:
                continue
            pid = int(row["ProcessId"])
            process_graph[pid] = {
                "pid": pid,
                "parent_pid": int(row["ParentProcessId"]),
                "executable": str(row.get("ExecutablePath") or ""),
                "command": str(row.get("CommandLine") or ""),
            }
        selected = []
        pending = [root_pid]
        while pending:
            parent_pid = pending.pop()
            current = process_graph.get(parent_pid)
            if current is None:
                raise RuntimeError(
                    f"process tree lookup failed: selected pid {parent_pid} is missing from the parent graph"
                )
            selected.append(current)
            pending.extend(
                item["pid"] for item in process_graph.values() if item["parent_pid"] == parent_pid
            )
        metadata = {
            item["pid"]: {
                **item,
                "cwd": _windows_current_working_directory(item["pid"]),
                "creation": _windows_creation_token(item["pid"]),
            }
            for item in selected
        }
        for item in metadata.values():
            parsed = _windows_command_line_argv(item["command"])
            item["argv"] = parsed
            item["argv_sha256"] = hashlib.sha256("\0".join(parsed).encode("utf-8")).hexdigest()
            item["native_command_sha256"] = hashlib.sha256(
                item["command"].encode("utf-8")
            ).hexdigest()
    else:
        process_graph = {}
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                pid = int(entry.name)
                stat_fields = (entry / "stat").read_text(encoding="utf-8").split()
                command = (entry / "cmdline").read_bytes().replace(b"\x00", b" ").decode(errors="replace").strip()
                process_graph[pid] = {
                    "pid": pid,
                    "parent_pid": int(stat_fields[3]),
                    "executable": str((entry / "exe").resolve()),
                    "command": command,
                }
            except (FileNotFoundError, OSError, ValueError):
                continue
        selected = []
        pending = [root_pid]
        while pending:
            parent_pid = pending.pop()
            current = process_graph.get(parent_pid)
            if current is None:
                raise RuntimeError(
                    f"process tree lookup failed: selected pid {parent_pid} is missing from the parent graph"
                )
            selected.append(current)
            pending.extend(
                item["pid"] for item in process_graph.values() if item["parent_pid"] == parent_pid
            )
        metadata = {item["pid"]: _process_metadata(item["pid"]) for item in selected}

    tree = []
    pending = [root_pid]
    while pending:
        parent_pid = pending.pop()
        current = metadata[parent_pid]
        current = dict(current)
        tree.append(current)
        children = [item["pid"] for item in metadata.values() if item["parent_pid"] == parent_pid]
        pending.extend(children)
    return tree


def _assert_owned_process_tree(process):
    owner = getattr(process, "_citespan_owner", None)
    if owner is None:
        raise RuntimeError("process cleanup denied: missing launch ownership record")
    current_root = _process_metadata(process.pid)
    recorded_root = owner["creation_identity"]
    _assert_complete_process_identity(recorded_root, "recorded launch root")
    _assert_complete_process_identity(current_root, "current launch root")
    _assert_process_identity_matches(
        recorded_root,
        current_root,
        "process cleanup denied: root identity changed",
    )
    expected_cwd = _canonical_path_identity(owner["cwd"])
    current_cwd = _canonical_path_identity(current_root["cwd"])
    if not current_cwd:
        raise RuntimeError(f"process cleanup denied: root worktree is unavailable; expected={owner['cwd']}")
    if current_cwd != expected_cwd:
        raise RuntimeError(
            f"process cleanup denied: root worktree changed; expected={owner['cwd']} current={current_root['cwd']}"
        )
    if _PLATFORM.name == "nt":
        _assert_windows_owned_command(current_root, owner)
    elif current_root["command"].split()[: len(owner["argv"])] != owner["argv"]:
        raise RuntimeError(
            f"process cleanup denied: root command changed; expected={owner['argv']} current={current_root['command']}"
        )
    tree = _current_process_tree(process.pid)
    if not tree:
        raise RuntimeError(f"process cleanup denied: owned root {process.pid} is not in the current process tree")
    census_root = tree[0]
    _assert_complete_process_identity(census_root, "census launch root")
    _assert_process_identity_matches(
        current_root,
        census_root,
        "process cleanup denied: census root identity changed",
    )
    if census_root["pid"] != process.pid:
        raise RuntimeError(
            f"process cleanup denied: census root PID changed; expected={process.pid} current={census_root['pid']}"
        )
    if census_root["parent_pid"] != recorded_root["parent_pid"]:
        raise RuntimeError(
            "process cleanup denied: census root parent relation changed; "
            f"recorded={recorded_root['parent_pid']} current={census_root['parent_pid']}"
        )
    _assert_owned_tree_graph(tree, expected_cwd, census_root["pid"])
    return _bind_census_parent_generations(tree, census_root["pid"])


_PROCESS_IDENTITY_FIELDS = (
    "pid",
    "creation",
    "executable",
    "command",
    "cwd",
    "argv",
    "argv_sha256",
    "native_command_sha256",
    "parent_pid",
)


def _assert_complete_process_identity(identity, label):
    missing = [field for field in _PROCESS_IDENTITY_FIELDS if field not in identity]
    if missing:
        raise RuntimeError(f"process cleanup denied: {label} is incomplete; missing={missing} identity={identity}")
    if not isinstance(identity["pid"], int) or isinstance(identity["pid"], bool):
        raise RuntimeError(f"process cleanup denied: {label} has invalid PID; identity={identity}")
    if not isinstance(identity["parent_pid"], int) or isinstance(identity["parent_pid"], bool):
        raise RuntimeError(f"process cleanup denied: {label} has invalid parent PID; identity={identity}")
    if not isinstance(identity["creation"], str) or not identity["creation"]:
        raise RuntimeError(f"process cleanup denied: {label} has invalid creation identity; identity={identity}")
    for field in ("executable", "command", "cwd"):
        if not isinstance(identity[field], str) or not identity[field]:
            raise RuntimeError(f"process cleanup denied: {label} has no {field} identity; identity={identity}")
    if not isinstance(identity["argv"], list) or any(not isinstance(item, str) for item in identity["argv"]):
        raise RuntimeError(f"process cleanup denied: {label} has invalid parsed argv; identity={identity}")
    if hashlib.sha256("\0".join(identity["argv"]).encode("utf-8")).hexdigest() != identity["argv_sha256"]:
        raise RuntimeError(f"process cleanup denied: {label} has incoherent parsed argv hash; identity={identity}")
    if hashlib.sha256(identity["command"].encode("utf-8")).hexdigest() != identity["native_command_sha256"]:
        raise RuntimeError(f"process cleanup denied: {label} has incoherent native command hash; identity={identity}")


def _assert_process_identity_matches(expected, actual, label):
    differences = {
        field: {"expected": expected[field], "actual": actual[field]}
        for field in _PROCESS_IDENTITY_FIELDS
        if expected[field] != actual[field]
    }
    if differences:
        raise RuntimeError(f"{label}; differences={differences}")


def _bind_census_parent_generations(tree, root_pid):
    """Attach each retained child edge to the parent generation in this census."""
    by_pid = {item["pid"]: item for item in tree}
    bound = []
    for item in tree:
        identity = dict(item)
        if identity["pid"] != root_pid:
            parent = by_pid.get(identity["parent_pid"])
            if parent is None:
                raise RuntimeError(
                    "process cleanup denied: census child parent is missing; "
                    f"pid={identity['pid']} parent_pid={identity['parent_pid']}"
                )
            if not isinstance(parent.get("creation"), str) or not parent["creation"]:
                raise RuntimeError(
                    "process cleanup denied: census parent generation is missing or malformed; "
                    f"pid={identity['pid']} parent_pid={identity['parent_pid']} "
                    f"parent_creation={parent.get('creation')!r}"
                )
            identity["parent_creation"] = parent["creation"]
        bound.append(identity)
    return bound


def _assert_owned_tree_graph(tree, expected_cwd, root_pid):
    by_pid = {}
    for item in tree:
        _assert_complete_process_identity(item, f"census identity pid={item.get('pid')}")
        pid = item["pid"]
        if pid in by_pid:
            raise RuntimeError(f"process cleanup denied: census contains duplicate PID; pid={pid}")
        by_pid[pid] = item
        if _canonical_path_identity(item["cwd"]) != expected_cwd:
            raise RuntimeError(
                f"process cleanup denied: process left the product worktree; pid={pid} "
                f"expected={expected_cwd} current={item['cwd']}"
            )
    if root_pid not in by_pid:
        raise RuntimeError(f"process cleanup denied: census root is missing; pid={root_pid}")

    for pid, item in by_pid.items():
        if pid == root_pid:
            continue
        parent = by_pid.get(item["parent_pid"])
        if parent is not None and _creation_token_is_newer(parent["creation"], item["creation"]):
            raise RuntimeError(
                "process cleanup denied: child creation predates its recorded parent generation; "
                f"pid={pid} child_creation={item['creation']} parent_pid={parent['pid']} "
                f"parent_creation={parent['creation']}"
            )

    validated = {root_pid}
    remaining = set(by_pid) - validated
    while remaining:
        progress = False
        for pid in tuple(remaining):
            parent_pid = by_pid[pid]["parent_pid"]
            if parent_pid in validated:
                if parent_pid == pid:
                    raise RuntimeError(f"process cleanup denied: census contains a self-cycle; pid={pid}")
                validated.add(pid)
                remaining.remove(pid)
                progress = True
        if not progress:
            parent_relations = {pid: by_pid[pid]["parent_pid"] for pid in sorted(remaining)}
            raise RuntimeError(
                "process cleanup denied: census contains a missing or cyclic parent relation; "
                f"remaining={sorted(remaining)} parents={parent_relations}"
            )


def _canonical_path_identity(path):
    value = str(path or "")
    if not value:
        return ""
    if _PLATFORM.name != "nt":
        return value
    return os.path.normcase(os.path.normpath(value)).casefold()


def _windows_command_line_argv(command):
    if _PLATFORM.name != "nt":
        raise RuntimeError("Windows command-line parsing requested on a non-Windows host")
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.CommandLineToArgvW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    count = ctypes.c_int()
    values = shell32.CommandLineToArgvW(command, ctypes.byref(count))
    if not values:
        raise RuntimeError(
            f"Windows command-line parsing failed: WinError {ctypes.get_last_error()}"
        )
    try:
        return [values[index] for index in range(count.value)]
    finally:
        ctypes.windll.kernel32.LocalFree(values)


def _assert_windows_owned_command(current, owner):
    parsed = _windows_command_line_argv(current["command"])
    expected_effective = [str(item) for item in owner["effective_argv"]]
    if len(parsed) < len(expected_effective):
        raise RuntimeError(
            f"process cleanup denied: parsed command is shorter than the launch contract; "
            f"expected_argv={expected_effective} parsed_argv={parsed}"
        )
    if parsed[1:4] != expected_effective[1:4]:
        raise RuntimeError(
            f"process cleanup denied: launch anchor changed; expected_prefix={expected_effective[1:4]} "
            f"parsed_argv={parsed}"
        )
    try:
        command_switch = parsed.index("/c", 1)
    except ValueError as exc:
        raise RuntimeError(
            f"process cleanup denied: parsed command has no /c contract; parsed_argv={parsed}"
        ) from exc
    expected_switch = expected_effective.index("/c", 1)
    if parsed[command_switch - 2 : command_switch + 1] != expected_effective[expected_switch - 2 : expected_switch + 1]:
        raise RuntimeError(
            f"process cleanup denied: cmd launch contract changed; "
            f"expected={expected_effective[expected_switch - 2 : expected_switch + 1]} "
            f"parsed={parsed[command_switch - 2 : command_switch + 1]}"
        )
    if parsed[command_switch + 1 :] != expected_effective[expected_switch + 1 :]:
        raise RuntimeError(
            f"process cleanup denied: parsed target argv changed; "
            f"expected={expected_effective[expected_switch + 1 :]} "
            f"parsed={parsed[command_switch + 1 :]}"
        )


def _read_process_output(process, *, retain=False):
    output_path = getattr(process, "_citespan_output_path", None)
    if output_path is None:
        return ""
    output = output_path.read_text(encoding="utf-8", errors="replace")[-4000:]
    if process.poll() is None:
        return f"{output}\noutput_path_retained={output_path}"
    if retain:
        return f"{output}\noutput_path_retained={output_path}"
    try:
        output_path.unlink(missing_ok=True)
    except OSError as exc:
        raise RuntimeError(f"process output cleanup failed: path={output_path} error={exc}") from exc
    return output


def _terminate_unverified_process_tree(process, label, timeout=15, owned_port=None):
    """Close only the directly owned launch handle before identity capture."""
    owner = getattr(process, "_citespan_owner", None)
    if owner is None or owner.get("creation_identity") is not None:
        raise RuntimeError(f"{label} cleanup denied: launch identity state is not unverified")
    if process.poll() is not None:
        raise RuntimeError(f"{label} cleanup denied: root process {process.pid} already exited")
    if [str(item) for item in process.args] != owner["effective_argv"]:
        raise RuntimeError(
            f"{label} cleanup denied: launch command changed; expected={owner['effective_argv']} actual={process.args}"
        )
    if owner["pid"] != process.pid or not owner["owner_marker"]:
        raise RuntimeError(f"{label} cleanup denied: launch ownership marker is incomplete")
    diagnostics = [
        f"verified direct launch handle pid={process.pid} owner_marker={owner['owner_marker']}; "
        "descendant ownership is unverified"
    ]
    try:
        process.kill()
        process.wait(timeout=timeout)
        if process.poll() is None:
            raise RuntimeError(f"{label} cleanup failed: root process {process.pid} remains")
    except Exception as exc:
        output_path = getattr(process, "_citespan_output_path", None)
        try:
            evidence = _read_process_output(process, retain=True)
        except Exception as output_exc:
            evidence = f"output read failed={output_exc} output_path_retained={output_path}"
        raise RuntimeError(
            f"{label} direct-handle containment failed for pid {process.pid}: {exc}; "
            f"process evidence={evidence[-4000:]} output_path_retained={output_path}"
        ) from exc
    try:
        diagnostics.append(_measure_post_containment_state(process, label, owned_port=owned_port))
    except Exception as exc:
        output_path = getattr(process, "_citespan_output_path", None)
        try:
            evidence = _read_process_output(process, retain=True)
        except Exception as output_exc:
            evidence = f"output read failed={output_exc} output_path_retained={output_path}"
        raise RuntimeError(
            f"{label} post-containment census failed for pid {process.pid}: {exc}; "
            f"owned_port={owned_port!r}; descendant ownership and stop state are unverified; "
            f"process evidence={evidence[-4000:]} output_path_retained={output_path}"
        ) from exc
    return "\n".join(diagnostics)


def _measure_post_containment_state(process, label, *, owned_port=None):
    try:
        current = _process_metadata(process.pid)
    except ProcessIdentityAbsent:
        if process.poll() is None:
            raise RuntimeError(
                f"{label} post-containment census failed: root process reports live but identity is absent "
                f"for pid {process.pid}"
            )
        if owned_port is not None:
            _assert_port_closed(owned_port, label)
        return (
            f"{label} post-containment census root=absent; descendants=unverified; "
            "tree cleanup is not proved"
        )
    except ProcessIdentityReadError as exc:
        raise RuntimeError(
            f"{label} post-containment census failed: root process state is unreadable for pid "
            f"{process.pid}: {exc}"
        ) from exc
    raise RuntimeError(
        f"{label} post-containment census found a potentially related process: "
        f"pid={process.pid} identity={current}; descendant ownership and stop state are unverified"
    )


def _terminate_verified_windows_identity(item, label, timeout):
    if _PLATFORM.name != "nt":
        raise RuntimeError(f"{label} cleanup denied: Windows process handle requested on a non-Windows host")

    class FileTime(ctypes.Structure):
        _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.GetProcessTimes.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
    ]
    kernel32.GetProcessTimes.restype = ctypes.c_int
    kernel32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.TerminateProcess.restype = ctypes.c_int
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    handle = kernel32.OpenProcess(0x101001, 0, int(item["pid"]))
    if not handle:
        raise RuntimeError(
            f"{label} cleanup failed: exact process handle open failed for pid={item['pid']} "
            f"WinError={ctypes.get_last_error()}"
        )
    try:
        creation = FileTime()
        exit_time = FileTime()
        kernel_time = FileTime()
        user_time = FileTime()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            raise RuntimeError(
                f"{label} cleanup failed: exact creation identity read failed for pid={item['pid']} "
                f"WinError={ctypes.get_last_error()}"
            )
        observed_creation = str((creation.high << 32) | creation.low)
        if observed_creation != str(item["creation"]):
            raise RuntimeError(
                f"{label} cleanup denied: process identity changed before handle stop: "
                f"pid={item['pid']} expected_creation={item['creation']} current_creation={observed_creation}"
            )
        if not kernel32.TerminateProcess(handle, 1):
            raise RuntimeError(
                f"{label} cleanup failed: exact process handle termination failed for pid={item['pid']} "
                f"WinError={ctypes.get_last_error()}"
            )
        wait_result = kernel32.WaitForSingleObject(handle, int(timeout * 1000))
        if wait_result != 0:
            raise RuntimeError(
                f"{label} cleanup failed: exact process handle did not exit for pid={item['pid']} "
                f"wait_result={wait_result}"
            )
    finally:
        kernel32.CloseHandle(handle)


def _poll_process_terminal_state(item, label):
    """Read only the native terminal state for one selected identity."""
    pid = item["pid"]
    if _PLATFORM.name != "nt":
        try:
            current = _process_metadata(pid)
        except ProcessIdentityAbsent:
            return {"pid": pid, "state": "verified_absent", "creation": item["creation"]}
        except ProcessIdentityReadError as exc:
            raise RuntimeError(
                f"{label} cleanup failed: cannot prove process identity {pid} is absent: {exc}"
            ) from exc
        if current["creation"] != item["creation"]:
            return {
                "pid": pid,
                "state": "pid_reused_after_exit",
                "creation": item["creation"],
                "current_creation": current["creation"],
                "current_identity": current,
            }
        return {"pid": pid, "state": "live", "creation": item["creation"]}

    class FileTime(ctypes.Structure):
        _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    kernel32.GetExitCodeProcess.restype = ctypes.c_int
    kernel32.GetProcessTimes.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
    ]
    kernel32.GetProcessTimes.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    handle = kernel32.OpenProcess(0x1000, 0, int(pid))
    if not handle:
        error = ctypes.get_last_error()
        if error == 87:
            return {"pid": pid, "state": "verified_absent", "creation": item["creation"]}
        raise RuntimeError(
            f"{label} cleanup failed: terminal handle open failed: pid={pid} WinError={error}"
        )
    try:
        creation = FileTime()
        exit_code = ctypes.c_uint32()
        if not kernel32.GetProcessTimes(
            handle, ctypes.byref(creation), ctypes.byref(FileTime()), ctypes.byref(FileTime()), ctypes.byref(FileTime())
        ):
            raise RuntimeError(
                f"{label} cleanup failed: terminal creation read failed: pid={pid} "
                f"WinError={ctypes.get_last_error()}"
            )
        observed_creation = str((creation.high << 32) | creation.low)
        if observed_creation != str(item["creation"]):
            return {
                "pid": pid,
                "state": "pid_reused_after_exit",
                "creation": item["creation"],
                "current_creation": observed_creation,
            }
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            raise RuntimeError(
                f"{label} cleanup failed: terminal state read failed: pid={pid} "
                f"WinError={ctypes.get_last_error()}"
            )
        if exit_code.value == 259:
            return {"pid": pid, "state": "live", "creation": item["creation"]}
        return {"pid": pid, "state": "verified_exited", "creation": item["creation"]}
    finally:
        kernel32.CloseHandle(handle)


def _stop_verified_process_identities(identities, label, timeout, *, state_map=None, phase_times=None):
    """Stop one leaf-first batch and cache every terminal identity state."""
    terminal_states = []
    state_map = {} if state_map is None else state_map
    phase_times = {} if phase_times is None else phase_times
    deadline = time.monotonic() + timeout
    for item in reversed(list(identities)):
        pid = item["pid"]
        cached = state_map.get(pid)
        if cached is not None and cached["state"] != "live":
            terminal_states.append(cached)
            continue
        identity_started = time.monotonic()
        try:
            current = _process_metadata(pid)
        except ProcessIdentityAbsent:
            state = {"pid": pid, "state": "already_exited", "creation": item["creation"]}
            state_map[pid] = state
            terminal_states.append(state)
            phase_times["identity_read"] = phase_times.get("identity_read", 0.0) + time.monotonic() - identity_started
            continue
        except ProcessIdentityReadError as exc:
            raise RuntimeError(
                f"{label} cleanup failed: cannot revalidate process identity before stop: "
                f"pid={pid} error={exc}"
            ) from exc
        phase_times["identity_read"] = phase_times.get("identity_read", 0.0) + time.monotonic() - identity_started
        for field in (
            "creation",
            "executable",
            "command",
            "cwd",
            "parent_pid",
            "argv",
            "argv_sha256",
            "native_command_sha256",
        ):
            if current.get(field) != item.get(field):
                raise RuntimeError(
                    f"{label} cleanup denied: identity changed before stop: pid={pid} "
                    f"field={field} expected={item.get(field)!r} current={current.get(field)!r}"
                )
        if deadline - time.monotonic() <= 0:
            raise RuntimeError(
                f"{label} cleanup failed: stop deadline exhausted: pid={pid} identity={item}"
            )
        stop_started = time.monotonic()
        if _PLATFORM.name == "nt":
            _terminate_verified_windows_identity(item, label, max(0.0, deadline - time.monotonic()))
        else:
            os.kill(pid, signal.SIGTERM)
        phase_times["stop"] = phase_times.get("stop", 0.0) + time.monotonic() - stop_started
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(
                    f"{label} cleanup failed: terminal poll deadline exhausted: pid={pid} identity={item}"
                )
            poll_started = time.monotonic()
            state = _poll_process_terminal_state(item, label)
            phase_times["terminal_poll"] = phase_times.get("terminal_poll", 0.0) + time.monotonic() - poll_started
            if state["state"] != "live":
                state_map[pid] = state
                terminal_states.append(state)
                break
            time.sleep(min(0.05, remaining))
    return terminal_states


def _validate_recorded_descendant_edges(recorded_by_pid, root_pid, label):
    """Validate retained parent generations before any recorded identity stop."""
    for pid, identity in recorded_by_pid.items():
        if pid == root_pid:
            continue
        parent_pid = identity.get("parent_pid")
        parent_creation = identity.get("parent_creation")
        if type(parent_pid) is not int:
            raise RuntimeError(
                f"{label} cleanup denied: retained parent edge is invalid: "
                f"child_pid={pid} parent_pid={parent_pid!r} "
                f"expected_parent_creation=<valid> observed_parent_creation={parent_creation!r} "
                "cleanup_step=validate_recorded_parent_edge"
            )
        if not isinstance(parent_creation, str) or not parent_creation:
            raise RuntimeError(
                f"{label} cleanup denied: retained parent generation is missing or malformed: "
                f"child_pid={pid} parent_pid={parent_pid} expected_parent_creation=<valid> "
                f"observed_parent_creation={parent_creation!r} "
                "cleanup_step=validate_recorded_parent_edge"
            )
        parent = recorded_by_pid.get(parent_pid)
        if not isinstance(parent, dict):
            raise RuntimeError(
                f"{label} cleanup denied: retained parent identity is unknown: "
                f"child_pid={pid} parent_pid={parent_pid} expected_parent_creation=<recorded-parent> "
                f"observed_parent_creation={parent_creation!r} "
                "cleanup_step=validate_recorded_parent_edge"
            )
        expected_parent_creation = parent.get("creation")
        if parent_creation != expected_parent_creation:
            raise RuntimeError(
                f"{label} cleanup denied: retained parent generation does not match: "
                f"child_pid={pid} parent_pid={parent_pid} "
                f"expected_parent_creation={expected_parent_creation!r} "
                f"observed_parent_creation={parent_creation!r} "
                "cleanup_step=validate_recorded_parent_edge"
            )


def _terminate_process_tree(process, label, timeout=15, owned_port=None):
    if process is None:
        return ""
    diagnostics = []
    try:
        owner = getattr(process, "_citespan_owner", None)
        if owner is None or not isinstance(owner.get("creation_identity"), dict):
            raise RuntimeError(f"{label} cleanup denied: exact root identity was not captured")
        deadline = time.monotonic() + timeout
        recorded_by_pid = {process.pid: dict(owner["creation_identity"])}
        recorded_by_pid.update(
            {
                int(pid): dict(identity)
                for pid, identity in owner.get("descendant_identities", {}).items()
                if int(pid) != process.pid
            }
        )
        state_map = {
            pid: {"pid": pid, "state": "live", "creation": identity["creation"]}
            for pid, identity in recorded_by_pid.items()
        }
        phase_times = {}
        while True:
            census_started = time.monotonic()
            try:
                tree = _assert_owned_process_tree(process)
            except ProcessIdentityAbsent:
                if process.poll() is None:
                    raise
                tree = [
                    item for pid, item in recorded_by_pid.items() if pid != process.pid
                ]
                _validate_recorded_descendant_edges(recorded_by_pid, process.pid, label)
                state_map[process.pid] = {
                    "pid": process.pid,
                    "state": "already_exited",
                    "creation": owner["creation_identity"]["creation"],
                }
            phase_times["census"] = phase_times.get("census", 0.0) + time.monotonic() - census_started
            for item in tree:
                previous = recorded_by_pid.get(item["pid"])
                if previous is not None and previous["creation"] != item["creation"]:
                    raise RuntimeError(
                        f"{label} cleanup denied: descendant PID was reused: "
                        f"pid={item['pid']} recorded={previous} current={item}"
                    )
                recorded_by_pid[item["pid"]] = item
                state_map.setdefault(item["pid"], {"pid": item["pid"], "state": "live", "creation": item["creation"]})
            diagnostics.append(
                "verified owned process tree=" + ",".join(str(item["pid"]) for item in tree)
            )
            descendants = [
                item
                for pid, item in recorded_by_pid.items()
                if pid != process.pid and state_map[pid]["state"] == "live"
            ]
            if descendants:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError(
                        f"{label} cleanup failed: owned descendant drain deadline exhausted; "
                        f"remaining={descendants} phase_times={phase_times}"
                    )
                terminal_states = _stop_verified_process_identities(
                    descendants,
                    label,
                    remaining,
                    state_map=state_map,
                    phase_times=phase_times,
                )
                for state in terminal_states:
                    state_map[state["pid"]] = state
                diagnostics.extend(
                    f"verified terminal state pid={item['pid']} state={item['state']}"
                    for item in terminal_states
                )
                continue
            break
        root_identity = recorded_by_pid[process.pid]
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(
                f"{label} cleanup failed: root stop deadline exhausted; phase_times={phase_times}"
            )
        terminal_states = _stop_verified_process_identities(
            [root_identity], label, remaining, state_map=state_map, phase_times=phase_times
        )
        for state in terminal_states:
            state_map[state["pid"]] = state
        diagnostics.extend(
            f"verified terminal state pid={item['pid']} state={item['state']}"
            for item in terminal_states
        )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(f"{label} cleanup failed: completion deadline exhausted; phase_times={phase_times}")
        process.wait(timeout=remaining)
        if process.poll() is None:
            raise RuntimeError(f"{label} cleanup failed: root process {process.pid} remains")
        if any(state["state"] == "live" for state in state_map.values()):
            raise RuntimeError(f"{label} cleanup failed: live recorded identities remain; phase_times={phase_times}")
        if owned_port is not None:
            _assert_port_closed(owned_port, label)
        output = _read_process_output(process)
        if output:
            diagnostics.append(f"captured output={output}")
        diagnostics.append(f"phase_times={phase_times}")
        return "\n".join(diagnostics)
    except Exception as exc:
        output_path = getattr(process, "_citespan_output_path", None)
        try:
            evidence = _read_process_output(process, retain=True)
        except Exception as output_exc:
            evidence = f"output cleanup error={output_exc} output_path_retained={output_path}"
        raise RuntimeError(
            f"{label} cleanup failed for pid {process.pid}: {exc}; phase_times={locals().get('phase_times', {})}; "
            f"process evidence={evidence[-4000:]} "
            f"output_path={output_path}"
        ) from exc


def _assert_port_closed(port, label):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(1)
        try:
            probe.connect(("127.0.0.1", port))
        except OSError:
            return
    raise RuntimeError(f"{label} cleanup failed: port {port} remains open")


def _assert_frontend_resources_released(frontend_port, label):
    """Require the scoped frontend census to show no owned process or holder."""
    resources = release._enumerate_fresh_frontend_resources()
    product_root = str(ROOT.resolve())
    observer_bootstrap_identity = release._capture_current_gate_test_identity()
    scope = release._fresh_resource_scope(
        resources,
        product_root,
        scoped_ports={frontend_port},
        observer_role="gate_test",
        observer_bootstrap_identity=observer_bootstrap_identity,
    )
    native_module = release._host_path_identity(
        (release.SCRIPT_ROOT / release.HOST_NATIVE_MODULE).resolve()
    )
    processes = scope["relevant_processes"]
    holders = [
        item
        for item in resources.get("holders", [])
        if any(
            isinstance(path, str) and release._host_path_identity(path) == native_module
            for path in item.get("module_paths", [])
        )
    ]
    ports = [
        item
        for item in resources.get("ports", [])
        if item.get("port") == frontend_port
    ]
    if processes or holders or ports:
        raise RuntimeError(
            f"{label} cleanup failed: scoped frontend resources remain: "
            f"processes={processes} native module holders={holders} ports={ports}"
        )


def _close_browser_resources(page, context, browser, label):
    errors = []
    for resource_name, resource in (("page", page), ("context", context), ("browser", browser)):
        if resource is None:
            continue
        try:
            resource.close()
        except Exception as exc:
            errors.append(f"{resource_name}: {exc!r}")
    if errors:
        raise RuntimeError(f"{label} browser cleanup failed: {'; '.join(errors)}")


def _detach_dialog_handler(page, handle_dialog):
    page.remove_listener("dialog", handle_dialog)


def _assert_cors_max_age_zero(headers, header_name="Access-Control-Max-Age"):
    assert headers.get(header_name) == "0"


def _raise_browser_test_errors(primary_error, cleanup_errors):
    if primary_error is not None:
        if cleanup_errors:
            raise RuntimeError(
                f"primary browser scenario failure: {primary_error}; cleanup failures: {'; '.join(cleanup_errors)}"
            ) from primary_error
        raise primary_error
    if cleanup_errors:
        raise RuntimeError("; ".join(cleanup_errors))


def _record_cleanup_failure(cleanup_errors, step, exc):
    cleanup_errors.append(
        f"cleanup step={step} failed: {type(exc).__name__}: {exc}\n"
        f"cause={exc.__cause__!r}\n"
        f"context={exc.__context__!r}\n"
        f"traceback:\n{traceback.format_exc()}"
    )


def test_launch_identity_timeout_closes_only_the_owned_handle(monkeypatch):
    process_holder = {}
    terminate = _terminate_unverified_process_tree

    def timed_out(_pid):
        raise RuntimeError("process identity lookup timed out for pid 123: timeout=10s")

    def capture_and_terminate(process, label, *args, **kwargs):
        process_holder["process"] = process
        return terminate(process, label, *args, **kwargs)

    monkeypatch.setattr(sys.modules[__name__], "_process_metadata", timed_out)
    monkeypatch.setattr(sys.modules[__name__], "_terminate_unverified_process_tree", capture_and_terminate)

    with pytest.raises(RuntimeError, match=r"identity capture[\s\S]*timed out[\s\S]*cleanup"):
        process_holder["process"] = _launch_process_tree(
            [sys.executable, "-c", "import time; time.sleep(60)"]
        )

    process = process_holder["process"]
    assert process.poll() is not None
    assert process._citespan_output_path.exists()


def test_unverified_cleanup_does_not_target_descendants(monkeypatch):
    calls = []
    alive = {"value": True}
    process = SimpleNamespace(
        pid=123,
        args=["expected-command"],
        poll=lambda: 0 if not alive["value"] else None,
        kill=lambda: (calls.append("direct-handle"), alive.__setitem__("value", False)),
        wait=lambda timeout: (calls.append(("wait", timeout)), alive.__setitem__("value", False)),
        _citespan_owner={
            "pid": 123,
            "effective_argv": ["expected-command"],
            "owner_marker": "marker",
            "creation_identity": None,
        },
    )
    monkeypatch.setattr(sys.modules[__name__], "_read_process_output", lambda *_args, **_kwargs: "captured")
    monkeypatch.setattr(
        sys.modules[__name__],
        "_measure_post_containment_state",
        lambda *_args, **_kwargs: "post-containment census root=absent; descendants=unverified",
    )

    _terminate_unverified_process_tree(process, "identity capture")

    assert calls[0] == "direct-handle"
    assert all(call != "taskkill-tree" for call in calls)


def test_unverified_cleanup_fails_when_post_containment_census_is_unreadable(monkeypatch):
    alive = {"value": True}
    process = SimpleNamespace(
        pid=123,
        args=["expected-command"],
        poll=lambda: None if alive["value"] else 0,
        kill=lambda: alive.__setitem__("value", False),
        wait=lambda timeout: None,
        _citespan_owner={
            "pid": 123,
            "effective_argv": ["expected-command"],
            "owner_marker": "marker",
            "creation_identity": None,
        },
    )
    monkeypatch.setattr(sys.modules[__name__], "_read_process_output", lambda *_args, **_kwargs: "captured")
    monkeypatch.setattr(
        sys.modules[__name__],
        "_process_metadata",
        lambda _pid: (_ for _ in ()).throw(RuntimeError("metadata timeout")),
    )

    with pytest.raises(RuntimeError, match=r"post-containment census failed.*metadata timeout"):
        _terminate_unverified_process_tree(process, "identity capture")


def test_unverified_containment_does_not_report_tree_cleanup_success(monkeypatch):
    alive = {"value": True}
    process = SimpleNamespace(
        pid=123,
        args=["expected-command"],
        poll=lambda: None if alive["value"] else 0,
        kill=lambda: alive.__setitem__("value", False),
        wait=lambda timeout: None,
        _citespan_owner={
            "pid": 123,
            "effective_argv": ["expected-command"],
            "owner_marker": "marker",
            "creation_identity": None,
        },
    )
    monkeypatch.setattr(sys.modules[__name__], "_read_process_output", lambda *_args, **_kwargs: "captured")
    monkeypatch.setattr(
        sys.modules[__name__],
        "_measure_post_containment_state",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("descendant ownership and stop state are unverified")
        ),
    )

    with pytest.raises(RuntimeError, match="descendant ownership and stop state are unverified"):
        _terminate_unverified_process_tree(process, "identity capture")


def test_verified_identity_stop_rejects_pid_reuse(monkeypatch):
    identity = {
        "pid": 123,
        "creation": "old",
        "executable": "python.exe",
        "command": "python worker.py",
        "cwd": str(ROOT),
        "parent_pid": 1,
    }
    monkeypatch.setattr(
        sys.modules[__name__],
        "_process_metadata",
        lambda _pid: {**identity, "creation": "replacement"},
    )
    kill_calls = []
    monkeypatch.setattr(os, "kill", lambda *args: kill_calls.append(args))

    with pytest.raises(RuntimeError, match="identity changed before stop"):
        _stop_verified_process_identities([identity], "verified cleanup", 1)
    assert kill_calls == []


def test_verified_identity_stop_records_a_child_that_exited_before_stop(monkeypatch):
    identity = {
        "pid": 124,
        "creation": "child",
        "executable": "python.exe",
        "command": "python child.py",
        "cwd": str(ROOT),
        "parent_pid": 123,
    }
    monkeypatch.setattr(
        sys.modules[__name__],
        "_process_metadata",
        lambda _pid: (_ for _ in ()).throw(ProcessIdentityAbsent("verified absent")),
    )
    monkeypatch.setattr(os, "kill", lambda *_args: pytest.fail("absent PID must not be stopped"))

    terminal_states = _stop_verified_process_identities([identity], "verified cleanup", 1)

    assert terminal_states == [{"pid": 124, "state": "already_exited", "creation": "child"}]


def test_verified_identity_stop_records_an_absent_root(monkeypatch):
    identity = {
        "pid": 123,
        "creation": "root",
        "executable": "python.exe",
        "command": "python root.py",
        "cwd": str(ROOT),
        "parent_pid": 1,
    }
    monkeypatch.setattr(
        sys.modules[__name__],
        "_process_metadata",
        lambda _pid: (_ for _ in ()).throw(ProcessIdentityAbsent("verified absent")),
    )

    assert _stop_verified_process_identities([identity], "verified cleanup", 1) == [
        {"pid": 123, "state": "already_exited", "creation": "root"}
    ]


def test_verified_identity_stop_rejects_pid_reuse_after_natural_child_exit(monkeypatch):
    identity = {
        "pid": 124,
        "creation": "child",
        "executable": "python.exe",
        "command": "python child.py",
        "cwd": str(ROOT),
        "parent_pid": 123,
    }
    observations = iter(["absent", {**identity, "creation": "replacement"}])
    reads = []

    def metadata(_pid):
        reads.append(_pid)
        observation = next(observations)
        if observation == "absent":
            raise ProcessIdentityAbsent("child exited")
        return observation

    monkeypatch.setattr(sys.modules[__name__], "_process_metadata", metadata)
    monkeypatch.setattr(os, "kill", lambda *_args: pytest.fail("absent PID must not be stopped"))

    assert _stop_verified_process_identities([identity], "verified cleanup", 1) == [
        {"pid": 124, "state": "already_exited", "creation": "child"}
    ]
    assert reads == [124]


def test_verified_identity_stop_records_pid_reuse_after_owned_stop(monkeypatch):
    identity = {
        "pid": 124,
        "creation": "child",
        "executable": "python.exe",
        "command": "python child.py",
        "cwd": str(ROOT),
        "parent_pid": 123,
    }
    replacement = {**identity, "creation": "replacement", "command": "python unrelated.py"}
    observations = iter([identity, replacement, replacement])

    monkeypatch.setattr(sys.modules[__name__], "_process_metadata", lambda _pid: next(observations))
    monkeypatch.setattr(os, "kill", lambda *_args: None)
    monkeypatch.setattr(_PLATFORM, "name", "posix")

    assert _stop_verified_process_identities([identity], "verified cleanup", 1) == [
        {
            "pid": 124,
            "state": "pid_reused_after_exit",
            "creation": "child",
            "current_creation": "replacement",
            "current_identity": replacement,
        }
    ]


def test_verified_identity_stop_rejects_unreadable_post_stop_identity(monkeypatch):
    identity = {
        "pid": 124,
        "creation": "child",
        "executable": "python.exe",
        "command": "python child.py",
        "cwd": str(ROOT),
        "parent_pid": 123,
    }
    observations = iter([identity, ProcessIdentityReadError("access denied")])

    def metadata(_pid):
        observation = next(observations)
        if isinstance(observation, BaseException):
            raise observation
        return observation

    monkeypatch.setattr(sys.modules[__name__], "_process_metadata", metadata)
    monkeypatch.setattr(os, "kill", lambda *_args: None)
    monkeypatch.setattr(_PLATFORM, "name", "posix")

    with pytest.raises(RuntimeError, match="cannot prove process identity 124 is absent: access denied"):
        _stop_verified_process_identities([identity], "verified cleanup", 1)


def test_process_identity_unreadable_query_is_not_absence(monkeypatch):
    result = SimpleNamespace(returncode=5, stdout="", stderr="access denied")
    monkeypatch.setattr(_PLATFORM, "name", "nt")
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: result)

    with pytest.raises(ProcessIdentityReadError, match="access denied"):
        _process_metadata(123)


def test_process_identity_malformed_query_is_not_absence(monkeypatch):
    result = SimpleNamespace(returncode=0, stdout="not-json", stderr="")
    monkeypatch.setattr(_PLATFORM, "name", "nt")
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: result)

    with pytest.raises(ProcessIdentityReadError, match="malformed output"):
        _process_metadata(123)


def test_verified_identity_stop_handles_mixed_natural_exit_and_exact_stops(monkeypatch):
    identities = [
        {
            "pid": 123,
            "creation": "root",
            "executable": "python.exe",
            "command": "python root.py",
            "cwd": str(ROOT),
            "parent_pid": 1,
        },
        {
            "pid": 124,
            "creation": "exited-child",
            "executable": "python.exe",
            "command": "python exited.py",
            "cwd": str(ROOT),
            "parent_pid": 123,
        },
        {
            "pid": 125,
            "creation": "live-child",
            "executable": "python.exe",
            "command": "python live.py",
            "cwd": str(ROOT),
            "parent_pid": 123,
        },
    ]
    active = {123: identities[0], 125: identities[2]}
    calls = []

    def metadata(pid):
        if pid == 124:
            raise ProcessIdentityAbsent("child exited")
        if pid not in active:
            raise ProcessIdentityAbsent("stopped")
        return dict(active[pid])

    def stop(pid, _signal):
        calls.append(pid)
        active.pop(pid)

    monkeypatch.setattr(sys.modules[__name__], "_process_metadata", metadata)
    monkeypatch.setattr(os, "kill", stop)
    monkeypatch.setattr(_PLATFORM, "name", "posix")

    terminal_states = _stop_verified_process_identities(identities, "verified cleanup", 1)

    assert calls == [125, 123]
    assert {item["pid"] for item in terminal_states} == {123, 124, 125}


def test_verified_unchanged_identity_set_is_stopped_and_verified(monkeypatch):
    identities = [
        {
            "pid": 123,
            "creation": "root",
            "executable": "python.exe",
            "command": "python root.py",
            "cwd": str(ROOT),
            "parent_pid": 1,
        },
        {
            "pid": 124,
            "creation": "child",
            "executable": "python.exe",
            "command": "python child.py",
            "cwd": str(ROOT),
            "parent_pid": 123,
        },
    ]
    active = {item["pid"]: item for item in identities}
    calls = []

    def metadata(pid):
        if pid not in active:
            raise ProcessIdentityAbsent("stopped")
        return dict(active[pid])

    def stop(pid, _signal):
        calls.append(pid)
        active.pop(pid)

    monkeypatch.setattr(sys.modules[__name__], "_process_metadata", metadata)
    monkeypatch.setattr(os, "kill", stop)
    monkeypatch.setattr(_PLATFORM, "name", "posix")
    _stop_verified_process_identities(identities, "verified cleanup", 1)
    assert calls == [124, 123]


def test_unverified_process_cleanup_rejects_changed_launch_contract(monkeypatch):
    process = SimpleNamespace(
        pid=123,
        args=["changed-command"],
        poll=lambda: None,
        _citespan_owner={
            "pid": 123,
            "effective_argv": ["expected-command"],
            "owner_marker": "marker",
            "creation_identity": None,
        },
    )

    with pytest.raises(RuntimeError, match="launch command changed"):
        _terminate_unverified_process_tree(process, "identity capture")


def _validation_evidence_diagnostic(path, generation, cursors, state):
    evidence = {
        "path": path,
        "generation": generation,
        "cursors": cursors,
        "api_events": state["api_events"][-8:],
        "api_responses": state["api_responses"][-8:],
        "browser_requests": state["browser_requests"][-8:],
        "browser_responses": state["browser_responses"][-8:],
        "browser_request_failures": state["browser_request_failures"][-8:],
        "browser_errors": state["browser_errors"][-8:],
        "callback_errors": state["callback_errors"][-8:],
    }
    return json.dumps(evidence, default=str, sort_keys=True)


def _checked_event_index(items, predicate, cursor, label, diagnostic):
    matches = [index for index, item in enumerate(items) if index >= cursor and predicate(item)]
    if not matches:
        raise AssertionError(f"missing {label}: {diagnostic()}")
    return matches[0]


class _CloseProbe:
    def __init__(self, name, events, error=None):
        self.name = name
        self.events = events
        self.error = error
        self.close_count = 0

    def close(self):
        self.close_count += 1
        self.events.append(self.name)
        if self.error is not None:
            raise self.error


def test_close_browser_resources_closes_each_initialized_resource_once():
    events = []
    page = _CloseProbe("page", events)
    context = _CloseProbe("context", events)
    browser = _CloseProbe("browser", events)

    _close_browser_resources(page, context, browser, "fixture")

    assert events == ["page", "context", "browser"]
    assert page.close_count == context.close_count == browser.close_count == 1


def test_checked_event_index_rejects_missing_and_out_of_cursor_events_with_context():
    events = [("OPTIONS", "/ingest/validate-path"), ("GET", "/retry")]
    diagnostic = lambda: '{"path": "/retry", "generation": 2}'

    assert _checked_event_index(events, lambda item: item == ("GET", "/retry"), 0, "GET", diagnostic) == 1
    with pytest.raises(AssertionError, match=r'missing GET: \{"path": "/retry", "generation": 2\}'):
        _checked_event_index(events, lambda item: item == ("GET", "/retry"), 2, "GET", diagnostic)


def test_checked_event_index_rejects_out_of_order_preflight_evidence():
    events = [("GET", "/retry"), ("OPTIONS", "/ingest/validate-path")]

    get_index = _checked_event_index(events, lambda item: item == ("GET", "/retry"), 0, "GET", lambda: "ordered evidence")
    options_index = _checked_event_index(
        events,
        lambda item: item == ("OPTIONS", "/ingest/validate-path"),
        0,
        "preflight",
        lambda: "ordered evidence",
    )
    with pytest.raises(AssertionError, match="preflight must precede GET"):
        assert options_index < get_index, "preflight must precede GET"


def test_close_browser_resources_preserves_all_cleanup_failures():
    events = []
    page = _CloseProbe("page", events, RuntimeError("page close failed"))
    context = _CloseProbe("context", events, RuntimeError("context close failed"))
    browser = _CloseProbe("browser", events)

    with pytest.raises(
        RuntimeError,
        match=r"page: RuntimeError\('page close failed'\); context: RuntimeError\('context close failed'\)",
    ):
        _close_browser_resources(page, context, browser, "fixture")

    assert events == ["page", "context", "browser"]
    assert page.close_count == context.close_count == browser.close_count == 1


class _DialogProbe:
    def __init__(self, events, error=None):
        self.events = events
        self.error = error

    def remove_listener(self, event, handler):
        self.events.append(("remove_listener", event, handler))
        if self.error is not None:
            raise self.error

    def close(self):
        self.events.append(("close",))


def test_dialog_handler_detaches_before_browser_resources_close():
    events = []
    handler = object()
    page = _DialogProbe(events)
    context = _CloseProbe("context", events)
    browser = _CloseProbe("browser", events)

    _detach_dialog_handler(page, handler)
    _close_browser_resources(page, context, browser, "fixture")

    assert events == [
        ("remove_listener", "dialog", handler),
        ("close",),
        "context",
        "browser",
    ]


def test_dialog_detachment_failure_preserves_primary_and_cleanup_errors():
    primary_error = RuntimeError("scenario failed")
    page = _DialogProbe([], RuntimeError("remove listener failed"))
    cleanup_errors = []

    try:
        _detach_dialog_handler(page, object())
    except Exception as exc:
        cleanup_errors.append(f"dialog handler detachment failed: {exc!r}")

    with pytest.raises(
        RuntimeError,
        match="primary browser scenario failure: scenario failed; cleanup failures: dialog handler detachment failed",
    ) as raised:
        _raise_browser_test_errors(primary_error, cleanup_errors)

    assert raised.value.__cause__ is primary_error


@pytest.mark.parametrize(
    "step",
    [
        "dialog-detach",
        "browser-resource-close",
        "playwright-stop",
        "process-tree-termination",
        "api-server-cleanup",
        "port-proof",
        "frontend-resource-proof",
    ],
)
def test_each_browser_cleanup_step_preserves_original_traceback(step):
    cleanup_errors = []
    try:
        raise KeyError("parent_pid")
    except KeyError as exc:
        _record_cleanup_failure(cleanup_errors, step, exc)

    with pytest.raises(RuntimeError) as raised:
        _raise_browser_test_errors(None, cleanup_errors)

    message = str(raised.value)
    assert f"cleanup step={step} failed" in message
    assert "KeyError" in message
    assert "parent_pid" in message
    assert "test_each_browser_cleanup_step_preserves_original_traceback" in message


def test_preflight_contract_rejects_cached_or_missing_max_age():
    with pytest.raises(AssertionError):
        _assert_cors_max_age_zero({})
    with pytest.raises(AssertionError):
        _assert_cors_max_age_zero({"Access-Control-Max-Age": "5"})
    _assert_cors_max_age_zero({"Access-Control-Max-Age": "0"})


def test_browser_cleanup_handles_partial_initialization_and_preserves_primary_failure():
    events = []
    context = _CloseProbe("context", events)
    primary_error = RuntimeError("scenario failed")

    with pytest.raises(RuntimeError, match="primary browser scenario failure: scenario failed") as raised:
        _close_browser_resources(None, context, None, "fixture")
        _raise_browser_test_errors(primary_error, ["context cleanup failed"])

    assert raised.value.__cause__ is primary_error
    assert events == ["context"]
    assert context.close_count == 1


def test_live_verifier_failure_returns_one_json_object_and_private_evidence():
    evidence_root = Path(tempfile.mkdtemp(prefix="citespan-verification-test-"))
    try:
        with patch.object(verify_live, "EXTERNAL_PROOF_ROOT", evidence_root):
            try:
                raise RuntimeError("query step failed")
            except RuntimeError as exc:
                evidence = verify_live._record_private_failure(
                    "query", exc, {"url": "https://citespan.example"}
                )
        assert evidence.is_file()
        detail = json.loads(evidence.read_text(encoding="utf-8"))
        assert detail["failed_step"]
        assert detail["traceback"]
    finally:
        _remove_owned_fixture(evidence_root, "verification fixture")


class _FakeLocator:
    def __init__(self, value=None, texts=None, actions=None, action=None):
        self.value = value
        self.texts = texts or []
        self.actions = actions
        self.action = action
        self.filled = None

    def fill(self, value):
        self.filled = value
        if self.actions is not None and self.action is not None:
            self.actions.append((self.action, value))

    def check(self):
        if self.actions is not None and self.action is not None:
            self.actions.append((self.action, True))
        return None

    def click(self):
        if self.actions is not None and self.action is not None:
            self.actions.append((self.action, True))
        return None

    def wait_for(self):
        return None

    def input_value(self):
        return self.value

    def count(self):
        return len(self.texts)

    def all_inner_texts(self):
        return self.texts

    def inner_text(self):
        return "CiteSpan"


def _canonical_query_response():
    return {
        "planner": "stub",
        "rows": [
            {
                "source_table": "aleappartifact",
                "row_id": verify_live.CANONICAL_DEMO_ARTIFACT_ROW_ID,
                "citations": [
                    {
                        "source_table": "aleappartifact",
                        "row_id": verify_live.CANONICAL_DEMO_ARTIFACT_ROW_ID,
                        "column": "category",
                        "snippet": "WhatsApp messages",
                        "matched_value": "WhatsApp",
                        "char_start": 0,
                        "char_end": 8,
                    }
                ],
            },
            {
                "source_table": "message",
                "row_id": verify_live.CANONICAL_DEMO_MESSAGE_ROW_IDS[0],
                "citations": [
                    {
                        "source_table": "message",
                        "row_id": verify_live.CANONICAL_DEMO_MESSAGE_ROW_IDS[0],
                        "column": "content",
                        "snippet": "Can you send the bitcoin wallet address for the transfer?",
                        "matched_value": "bitcoin",
                        "char_start": 17,
                        "char_end": 24,
                    }
                ],
            },
            {
                "source_table": "message",
                "row_id": verify_live.CANONICAL_DEMO_MESSAGE_ROW_IDS[1],
                "citations": [
                    {
                        "source_table": "message",
                        "row_id": verify_live.CANONICAL_DEMO_MESSAGE_ROW_IDS[1],
                        "column": "content",
                        "snippet": "Use the bank transfer reference for the synthetic sample.",
                        "matched_value": "bank",
                        "char_start": 8,
                        "char_end": 12,
                    }
                ],
            },
        ],
    }


class _FakePage:
    def __init__(self):
        self.title_value = "CiteSpan"
        self.actions = []
        self.query_response = _canonical_query_response()
        self.request = _FakeRequest()
        self.url = ""
        self.reset_response_observed = False
        self.reset_response_status = 200
        self.reset_response_body = {
            "run_id": verify_live.CANONICAL_DEMO_RUN_ID,
            "sample": "canonical synthetic UFDR",
            "reset": True,
        }

    def goto(self, url, wait_until):
        self.url = url
        return None

    def wait_for_url(self, pattern, wait_until):
        self.url = pattern
        return None

    def title(self):
        return self.title_value

    def locator(self, selector):
        values = {
            "body": _FakeLocator(),
            "#name": _FakeLocator(actions=self.actions, action=selector),
            "#email": _FakeLocator(actions=self.actions, action=selector),
            "#password": _FakeLocator(actions=self.actions, action=selector),
            "#confirmPassword": _FakeLocator(actions=self.actions, action=selector),
            "#terms": _FakeLocator(actions=self.actions, action=selector),
            "#run-id": _FakeLocator(verify_live.CANONICAL_DEMO_RUN_ID),
            "#question": _FakeLocator(actions=self.actions, action=selector),
            "[data-testid='cited-result-row']": _FakeLocator(texts=["row"]),
        ".cite": _FakeLocator(texts=["WhatsApp", "bitcoin", "bank"]),
            "text=chars ": _FakeLocator(texts=["chars 0-4"]),
        }
        return values.get(selector, _FakeLocator())

    def get_by_role(self, role, name):
        return _FakeLocator(actions=self.actions, action=(role, name))

    def get_by_text(self, text, exact=False):
        if isinstance(text, str) and (
            text == "Cited Results"
            or "planner:" in text
            or "Upload disabled in the synthetic demo" in text
        ):
            return _FakeLocator(texts=["visible"])
        if hasattr(text, "pattern") and "planner:" in text.pattern:
            return _FakeLocator(texts=["visible"])
        return _FakeLocator()

    def screenshot(self, path, full_page):
        Path(path).write_bytes(b"screenshot")

    def on(self, event, callback):
        if event == "response":
            callback(_FakeResponse(self.query_response))

    def expect_response(self, predicate):
        return _FakeResetExpectation(self, predicate)


class _FakeResetExpectation:
    def __init__(self, page, predicate):
        self.page = page
        self.predicate = predicate
        self.value = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        response = _FakeResetResponse(
            self.page.reset_response_status,
            self.page.reset_response_body,
        )
        if not self.predicate(response):
            raise AssertionError("reset response did not match the expected request")
        self.value = response
        self.page.reset_response_observed = True
        return False


class _FakeResponse:
    def __init__(self, payload):
        self.request = type("Request", (), {"method": "POST"})()
        self.url = "https://citespan.example/api/query/plan"
        self._payload = payload

    def json(self):
        return self._payload


class _FakeUploadResponse:
    status = 403

    def text(self):
        return "File upload and path ingestion are disabled in demo mode."


class _FakeResetResponse:
    request = type("Request", (), {"method": "POST"})()
    url = "https://citespan.example/api/demo/reset"

    def __init__(self, status, body):
        self.status = status
        self.body = body

    def json(self):
        return self.body


class _FakeRequest:
    def post(self, url, data):
        return _FakeUploadResponse()

    def get(self, url, params):
        return _FakeUploadResponse()


class _FakeContext:
    def new_page(self):
        return _FakePage()

    def close(self):
        return None


class _FakeBrowser:
    def new_context(self):
        return _FakeContext()

    def close(self):
        return None


class _FakePlaywright:
    class chromium:
        @staticmethod
        def launch(headless):
            return _FakeBrowser()


def test_browser_flow_proves_clean_session_and_cited_evidence(tmp_path):
    page = _FakePage()

    class _PageContext:
        def new_page(self):
            return page

        def close(self):
            return None

    class _PageBrowser:
        def new_context(self):
            return _PageContext()

        def close(self):
            return None

    class _PagePlaywright:
        class chromium:
            @staticmethod
            def launch(headless):
                return _PageBrowser()

    result = verify_live._run_browser_flow(
        _PagePlaywright(),
        "https://citespan.example",
        verify_live.CANONICAL_DEMO_RUN_ID,
        "Show bank transfers",
        tmp_path,
    )

    assert result["query_response"]["planner"] == "stub"
    assert len(result["query_response"]["rows"]) == 3
    assert result["query_response"]["rows"][0]["citations"][0]["matched_value"] == "WhatsApp"
    assert result["upload_status"] == 403
    assert result["ingestion_statuses"] == {
        "/api/ingest/": 403,
        "/api/ingest/validate-path": 403,
        "/api/ingest/aleapp-structure": 403,
    }
    assert (tmp_path / "citespan-home.png").is_file()
    assert (tmp_path / "citespan-upload-disabled.png").is_file()
    assert (tmp_path / "citespan-query-results.png").is_file()
    assert (tmp_path / "citespan-query-plan.png").is_file()
    assert (("button", "Create Account"), True) in page.actions
    assert (("button", "Reset to sample"), True) in page.actions
    assert page.reset_response_observed is True
    assert (("button", "Run query"), True) in page.actions
    assert ("#question", "Show bank transfers") in page.actions


def test_browser_flow_rejects_noncanonical_run_id_before_browser_launch(tmp_path):
    class _BrowserMustNotLaunch:
        class chromium:
            @staticmethod
            def launch(headless):
                raise AssertionError("browser must not launch for a noncanonical run")

    with pytest.raises(RuntimeError, match="canonical synthetic demo run ID"):
        verify_live._run_browser_flow(
            _BrowserMustNotLaunch(),
            "https://citespan.example",
            "not-canonical",
            "Show bank transfers",
            tmp_path,
        )


def test_browser_flow_rejects_noncanonical_reset_response(tmp_path):
    page = _FakePage()
    page.reset_response_body["run_id"] = "not-canonical"

    class _PageContext:
        def new_page(self):
            return page

        def close(self):
            return None

    class _PageBrowser:
        def new_context(self):
            return _PageContext()

        def close(self):
            return None

    class _PagePlaywright:
        class chromium:
            @staticmethod
            def launch(headless):
                return _PageBrowser()

    with pytest.raises(RuntimeError, match="canonical synthetic sample"):
        verify_live._run_browser_flow(
            _PagePlaywright(),
            "https://citespan.example",
            verify_live.CANONICAL_DEMO_RUN_ID,
            "Show bank transfers",
            tmp_path,
        )


def test_browser_flow_stops_on_reset_http_failure(tmp_path):
    page = _FakePage()
    page.reset_response_status = 503

    class _PageContext:
        def new_page(self):
            return page

        def close(self):
            return None

    class _PageBrowser:
        def new_context(self):
            return _PageContext()

        def close(self):
            return None

    class _PagePlaywright:
        class chromium:
            @staticmethod
            def launch(headless):
                return _PageBrowser()

    with pytest.raises(RuntimeError, match="demo reset failed with HTTP 503"):
        verify_live._run_browser_flow(
            _PagePlaywright(),
            "https://citespan.example",
            verify_live.CANONICAL_DEMO_RUN_ID,
            "Show bank transfers",
            tmp_path,
        )


def test_upload_reset_control_has_authenticated_canonical_request_and_error_gate():
    source = (ROOT / "frontend" / "app" / "upload" / "page.tsx").read_text(
        encoding="utf-8"
    )
    start = source.index("const handleResetToSample = async () => {")
    end = source.index("\n\n  return (", start)
    handler = source[start:end]
    assert 'authedFetch("/api/demo/reset"' in handler
    assert 'method: "POST"' in handler
    assert 'credentials: "include"' in handler
    assert 'body.run_id !== "11111111-1111-4111-8111-111111111111"' in handler
    assert 'body.sample !== "canonical synthetic UFDR"' in handler
    assert "body.reset !== true" in handler
    assert 'localStorage.setItem("citespan.demo.run_id", body.run_id)' in handler
    assert handler.index("router.push(\"/query-plan/\")") > handler.index(
        'body.reset !== true'
    )
    assert "setResetError" in handler
    assert "setResetError" in handler[handler.index("} catch"):]
    assert "router.push" not in handler[handler.index("} catch"):]


def test_live_url_validator_accepts_only_the_canonical_origin():
    assert (
        verify_live._validate_live_url("https://citespan.169.58.64.150.nip.io")
        == "https://citespan.169.58.64.150.nip.io"
    )
    assert (
        verify_live._validate_live_url("https://citespan.169.58.64.150.nip.io/")
        == "https://citespan.169.58.64.150.nip.io"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://citespan.169.58.64.150.nip.io",
        "https://citespan.169.58.64.150.nip.io.evil.example",
        "https://citespan.169.58.64.150.nip.io:443",
        "https://user:password@citespan.169.58.64.150.nip.io",
        "https://citespan.169.58.64.150.nip.io/?q=1",
        "https://citespan.169.58.64.150.nip.io/#fragment",
        "https://citespan.169.58.64.150.nip.io/disallowed",
        "https://[malformed",
        "https://citespan.example",
    ],
)
def test_live_url_validator_rejects_unauthorized_targets(url):
    with pytest.raises(verify_live.LiveUrlValidationError):
        verify_live._validate_live_url(url)


def test_live_verification_rejects_non_https_urls_without_proof_side_effects(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "verify_live.py"),
            "--url",
            "http://citespan.169.58.64.150.nip.io",
            "--run-id",
            "demo",
            "--output-dir",
            str(tmp_path / "proof"),
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )

    value = json.loads(result.stdout)
    assert result.returncode != 0
    assert value["complete"] is False
    assert "HTTPS" in value["error"]
    assert not (tmp_path / "proof").exists()


def test_live_verification_rejects_another_https_host_before_proof_activity(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "verify_live.py"),
            "--url",
            "https://example.com",
            "--run-id",
            verify_live.CANONICAL_DEMO_RUN_ID,
            "--deployment-id",
            "citespan-test",
            "--output-dir",
            str(tmp_path / "proof"),
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )

    value = json.loads(result.stdout)
    assert result.returncode != 0
    assert value["complete"] is False
    assert "authorized CiteSpan HTTPS origin" in value["error"]
    assert not (tmp_path / "proof").exists()


def test_live_verification_rejects_noncanonical_run_id_from_cli(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "verify_live.py"),
            "--url",
            "https://citespan.169.58.64.150.nip.io",
            "--run-id",
            "not-canonical",
            "--deployment-id",
            "citespan-test",
            "--output-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )

    value = json.loads(result.stdout)
    assert result.returncode != 0
    assert value["complete"] is False
    assert "canonical synthetic demo run ID" in value["error"]


def test_live_verification_default_output_is_script_relative():
    source = (ROOT / "scripts" / "verify_live.py").read_text(encoding="utf-8")

    assert "EXTERNAL_PROOF_ROOT" in source
    assert "new_context" in source


def test_citation_validation_requires_evidence_spans_and_offsets():
    verify_live._validate_cited_response(_canonical_query_response())


def test_default_question_executes_canonical_rows_with_transfer_citations(monkeypatch):
    source = (ROOT / "scripts" / "verify_live.py").read_text(encoding="utf-8")
    assert 'default="Show me all messages mentioning a transfer"' in source

    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    run_id = uuid.UUID(verify_live.CANONICAL_DEMO_RUN_ID)
    artifact_id = uuid.UUID(verify_live.CANONICAL_DEMO_ARTIFACT_ROW_ID)
    message_ids = [uuid.UUID(value) for value in verify_live.CANONICAL_DEMO_MESSAGE_ROW_IDS]
    canonical_rows = verify_live.CANONICAL_EVIDENCE_MANIFEST["rows"]
    artifact = canonical_rows[("aleappartifact", verify_live.CANONICAL_DEMO_ARTIFACT_ROW_ID)]["columns"]

    with Session(engine) as session:
        session.add(
            AleappArtifact(
                id=artifact_id,
                run_id=run_id,
                artifact_type="csv",
                filename=artifact["filename"],
                file_path=artifact["file_path"],
                category=artifact["category"],
                row_count=1,
                data=artifact["data"],
            )
        )
        session.add_all(
            [
                Message(
                    id=message_ids[0],
                    run_id=run_id,
                    sender="+15551234567",
                    receiver="+15559876543",
                    timestamp=datetime(2024, 1, 1, 12, 0, 0),
                    content=canonical_rows[("message", verify_live.CANONICAL_DEMO_MESSAGE_ROW_IDS[0])]["columns"]["content"],
                ),
                Message(
                    id=message_ids[1],
                    run_id=run_id,
                    sender="+15559876543",
                    receiver="+15551234567",
                    timestamp=datetime(2024, 1, 1, 13, 0, 0),
                    content=canonical_rows[("message", verify_live.CANONICAL_DEMO_MESSAGE_ROW_IDS[1])]["columns"]["content"],
                ),
            ]
        )
        session.commit()

        plan, planner = plan_question("Show me all messages mentioning a transfer")
        answer = run_plan(
            session,
            plan,
            run_id,
            question="Show me all messages mentioning a transfer",
            planner=planner,
        )
        response = answer.to_dict()

        assert planner == "stub"
        assert {row["source_table"] for row in response["rows"]} == {"message", "aleappartifact"}
        assert {uuid.UUID(row["row_id"]) for row in response["rows"]} == {
            uuid.UUID(verify_live.CANONICAL_DEMO_ARTIFACT_ROW_ID),
            *(uuid.UUID(value) for value in verify_live.CANONICAL_DEMO_MESSAGE_ROW_IDS),
        }
        verify_live._validate_cited_response(response)

        old_plan, old_planner = plan_question("Show me all WhatsApp messages mentioning a bank transfer")
        old_answer = run_plan(session, old_plan, run_id, planner=old_planner)
        assert old_planner == "stub"
        assert [row.source_table for row in old_answer.rows] == ["aleappartifact"]
        assert [uuid.UUID(row.row_id) for row in old_answer.rows] == [
            uuid.UUID(verify_live.CANONICAL_DEMO_ARTIFACT_ROW_ID)
        ]


def test_citation_validation_rejects_results_without_evidence_spans():
    with pytest.raises(RuntimeError, match="evidence spans"):
        verify_live._validate_cited_response(
            {
                "planner": "stub",
                "rows": [
                    {
                        "source_table": "aleappartifact",
                        "row_id": verify_live.CANONICAL_DEMO_ARTIFACT_ROW_ID,
                        "citations": [],
                    }
                ],
            }
        )


def test_live_verification_source_resets_demo_before_query_and_writes_post_conditionally():
    source = (ROOT / "scripts" / "verify_live.py").read_text(encoding="utf-8")

    assert 'get_by_role("button", name="Reset to sample")' in source
    assert "citespan-launch-post.md" in source


def test_live_verification_uses_same_origin_api_and_trailing_slash_query_route():
    source = (ROOT / "scripts" / "verify_live.py").read_text(encoding="utf-8")

    assert "/api/upload/" in source
    assert "/api/ingest/aleapp-structure" in source
    assert "ingestion_statuses" in source
    assert "expected_query_url" in source
    assert "page.url != expected_query_url" in source


def test_frontend_export_keeps_trailing_slash_routes():
    source = (ROOT / "frontend" / "next.config.ts").read_text(encoding="utf-8")

    assert 'output: "export"' in source
    assert "trailingSlash: true" in source


def test_live_verification_uses_only_visible_browser_controls():
    source = (ROOT / "scripts" / "verify_live.py").read_text(encoding="utf-8")

    assert "page.evaluate" not in source
    assert 'get_by_role("button", name="Reset to sample")' in source
    assert 'page.locator("#run-id").fill' not in source


def test_live_verification_validates_the_observed_query_response():
    source = (ROOT / "scripts" / "verify_live.py").read_text(encoding="utf-8")

    assert "query_response" in source
    assert "_validate_cited_response(query_response, run_id)" in source
    assert "visible evidence spans do not match" in source


def test_proof_writer_returns_exact_durable_paths_and_draft(tmp_path):
    screenshot_names = [
        "citespan-home.png",
        "citespan-upload-disabled.png",
        "citespan-query-plan.png",
        "citespan-query-results.png",
    ]
    for name in screenshot_names:
        (tmp_path / name).write_bytes(b"screenshot")
    result = verify_live._write_proof_artifacts(
        tmp_path,
        "https://citespan.example",
        "Show bank transfers",
        screenshot_names,
        _canonical_query_response(),
        "citespan-test",
        ingestion_statuses={
            "/api/ingest/": 403,
            "/api/ingest/validate-path": 403,
            "/api/ingest/aleapp-structure": 403,
        },
    )

    assert result["proof_path"] == str(tmp_path / "citespan-live-proof.md")
    assert result["launch_post_path"] == str(tmp_path / "citespan-launch-post.md")
    assert result["launch_post"] == (tmp_path / "citespan-launch-post.md").read_text()
    proof_text = (tmp_path / "citespan-live-proof.md").read_text()
    launch_post_text = (tmp_path / "citespan-launch-post.md").read_text()
    assert "## Deployment identity" in proof_text
    assert "citespan-test" in proof_text
    assert "citespan-test" not in launch_post_text
    assert all(path.startswith(str(tmp_path)) for path in result["screenshot_paths"])
    assert all(Path(path).is_file() for path in result["screenshot_paths"])
    assert Path(result["proof_path"]).is_file()
    assert Path(result["launch_post_path"]).is_file()


def test_proof_writer_does_not_write_when_proof_is_incomplete(tmp_path):
    observed = {
        "planner": "stub",
        "rows": [
            {
                "source_table": "aleappartifact",
                "row_id": verify_live.CANONICAL_DEMO_ARTIFACT_ROW_ID,
                "citations": [
                    {
                        "source_table": "aleappartifact",
                        "row_id": verify_live.CANONICAL_DEMO_ARTIFACT_ROW_ID,
                        "column": "category",
                        "snippet": "WhatsApp messages",
                        "matched_value": "WhatsApp",
                        "char_start": 0,
                        "char_end": 8,
                    }
                ]
            }
        ],
    }
    with pytest.raises(RuntimeError, match="not complete"):
        verify_live._write_proof_artifacts(
            tmp_path,
            "https://citespan.example",
            "Q",
            [],
            observed,
            "citespan-test",
            complete=False,
        )
    assert not (tmp_path / "citespan-live-proof.md").exists()
    assert not (tmp_path / "citespan-launch-post.md").exists()


def test_proof_writer_rejects_missing_screenshot_files(tmp_path):
    observed = _canonical_query_response()
    with pytest.raises(RuntimeError, match="existing browser screenshots"):
        verify_live._write_proof_artifacts(
            tmp_path,
            "https://citespan.example",
            "Q",
            [
                "citespan-home.png",
                "citespan-upload-disabled.png",
                "citespan-query-plan.png",
                "missing.png",
            ],
            observed,
            "citespan-test",
            ingestion_statuses={
                "/api/ingest/": 403,
                "/api/ingest/validate-path": 403,
                "/api/ingest/aleapp-structure": 403,
            },
        )


def _canonical_artifact_response(**citation_overrides):
    citation = {
        "source_table": "aleappartifact",
        "row_id": verify_live.CANONICAL_DEMO_ARTIFACT_ROW_ID,
        "column": "category",
        "snippet": "WhatsApp messages",
        "matched_value": "WhatsApp",
        "char_start": 0,
        "char_end": 8,
    }
    citation.update(citation_overrides)
    return {
        "planner": "stub",
        "rows": [
            {
                "source_table": "aleappartifact",
                "row_id": verify_live.CANONICAL_DEMO_ARTIFACT_ROW_ID,
                "citations": [citation],
            }
        ],
    }


def test_citation_validation_rejects_internally_consistent_invented_row():
    response = _canonical_artifact_response(
        source_table="message",
        row_id="99999999-9999-4999-8999-999999999999",
        column="content",
        snippet="invented evidence",
        matched_value="invented",
        char_end=8,
    )
    response["rows"][0]["source_table"] = "message"
    response["rows"][0]["row_id"] = "99999999-9999-4999-8999-999999999999"
    with pytest.raises(RuntimeError, match="unknown canonical evidence row"):
        verify_live._validate_cited_response(response)


def test_citation_validation_rejects_altered_canonical_content():
    with pytest.raises(RuntimeError, match="snippet does not equal canonical evidence"):
        verify_live._validate_cited_response(
            _canonical_artifact_response(snippet="WhatsApp altered")
        )


def test_citation_validation_accepts_canonical_artifact_columns_and_compact_uuid():
    artifact_id = verify_live.CANONICAL_DEMO_ARTIFACT_ROW_ID.replace("-", "")
    response = {
        "planner": "stub",
        "rows": [
            {
                "source_table": "aleappartifact",
                "row_id": artifact_id,
                "citations": [
                    {
                        "source_table": "aleappartifact",
                        "row_id": artifact_id,
                        "column": "filename",
                        "snippet": "whatsapp_messages.csv",
                        "matched_value": "whatsapp",
                        "char_start": 0,
                        "char_end": 8,
                    },
                    {
                        "source_table": "aleappartifact",
                        "row_id": artifact_id,
                        "column": "file_path",
                        "snippet": "/synthetic/whatsapp_messages.csv",
                        "matched_value": "whatsapp",
                        "char_start": 11,
                        "char_end": 19,
                    },
                ],
            }
        ],
    }
    response["rows"].extend(_canonical_query_response()["rows"][1:])
    verify_live._validate_cited_response(response)


def test_citation_validation_rejects_wrong_run_or_case_identity():
    with pytest.raises(RuntimeError, match="canonical evidence manifest"):
        verify_live._validate_cited_response(
            _canonical_artifact_response(), expected_run_id="wrong-run"
        )


def test_citation_validation_rejects_invalid_offsets_and_mismatched_snippets():
    with pytest.raises(RuntimeError, match="outside its snippet"):
        verify_live._validate_cited_response(
            _canonical_artifact_response(char_start=20, char_end=21)
        )
    with pytest.raises(RuntimeError, match="does not match its character span"):
        verify_live._validate_cited_response(
            _canonical_artifact_response(matched_value="messages")
        )


def test_citation_validation_fails_closed_when_manifest_is_missing_or_ambiguous(monkeypatch):
    monkeypatch.setattr(verify_live, "CANONICAL_EVIDENCE_MANIFEST", None)
    with pytest.raises(RuntimeError, match="canonical evidence manifest"):
        verify_live._validate_cited_response(_canonical_artifact_response())
    monkeypatch.setattr(
        verify_live,
        "CANONICAL_EVIDENCE_MANIFEST",
        {
            "run_id": verify_live.CANONICAL_DEMO_RUN_ID,
            "case_id": verify_live.CANONICAL_DEMO_RUN_ID,
            "rows": {},
        },
    )
    with pytest.raises(RuntimeError, match="canonical evidence manifest"):
        verify_live._validate_cited_response(_canonical_artifact_response())


def test_citation_validation_rejects_partial_canonical_row_coverage():
    with pytest.raises(RuntimeError, match="every canonical evidence row"):
        verify_live._validate_cited_response(_canonical_artifact_response())


def test_proof_writer_rejects_three_screenshots_even_when_files_exist(tmp_path):
    for name in (
        "citespan-home.png",
        "citespan-upload-disabled.png",
        "citespan-query-results.png",
    ):
        (tmp_path / name).write_bytes(b"screenshot")
    with pytest.raises(RuntimeError, match="four distinct browser screenshots"):
        verify_live._write_proof_artifacts(
            tmp_path,
            "https://citespan.example",
            "Q",
            [
                "citespan-home.png",
                "citespan-upload-disabled.png",
                "citespan-query-results.png",
            ],
            _canonical_query_response(),
            "citespan-test",
            ingestion_statuses={
                "/api/ingest/": 403,
                "/api/ingest/validate-path": 403,
                "/api/ingest/aleapp-structure": 403,
            },
        )

def test_public_home_copy_states_the_verified_hosted_demo_limits():
    source = (ROOT / "frontend" / "app" / "page.tsx").read_text(encoding="utf-8")

    assert "canonical synthetic sample" in source
    assert "natural language" in source
    assert "evidence span" in source
    assert "deterministic, not a live large language" in source
    assert "any file formats" not in source
    assert "interactive timelines" not in source
    assert "visual link analysis" not in source
    assert "automated" not in source


_EVIDENCE_ROOT = Path.home() / ".citespan" / "host-process-evidence"
_LEGACY_NODE_INVENTORY = "recorded-node-identities-942.json"
_LEGACY_LOCK_INVENTORY = "product-frontend-native-lock-932.json"
_NATIVE_MODULE_RELATIVE = Path(
    "frontend/node_modules/lightningcss-win32-x64-msvc/lightningcss.win32-x64-msvc.node"
)
_CURRENT_NODE_OBSERVATION = "legacy-node-current-981.json"
_CURRENT_FAMILY_OBSERVATION = "legacy-family-current-996.json"
_CURRENT_FAMILY_NORMALIZED = "citespan-node-family-current.v1.json"
_CURRENT_FAMILY_PRESENCE = "legacy-family-presence-1004.json"
_CURRENT_FRONTEND_PROCESSES = "current-frontend-processes-1004.json"
_CURRENT_APPROVAL = "citespan-node-current-approval.json"
_OWNER_ACTOR = 7
_OWNER_GOAL = "740d01c7-2dbf-4d74-8480-3f14cf85aa48"
_PARENT_STATES = {
    "readable_current_parent",
    "verified_absent_historical_parent",
    "unreadable_parent",
    "reused_parent",
    "historical_parent_exited_pid_reused",
}


def _legacy_evidence_records(value, label):
    if not isinstance(value, list) or not value:
        raise RuntimeError(
            f"legacy evidence contract invalid {label}: expected a non-empty historical list"
        )
    normalized = []
    for record in value:
        if not isinstance(record, dict):
            raise RuntimeError(f"legacy evidence contract invalid {label}: each item must be an object")
        identity = record.get("identity")
        if not isinstance(identity, dict):
            raise RuntimeError(f"legacy evidence contract invalid {label}: identity object is required")
        pid = identity.get("pid")
        creation = identity.get("creation_token")
        if not isinstance(pid, int) or pid <= 0:
            raise RuntimeError(f"legacy evidence contract invalid {label}: identity.pid is required")
        if not isinstance(creation, str) or not creation:
            raise RuntimeError(
                f"legacy evidence contract invalid {label}: identity.creation_token is required: pid={pid}"
            )
        parent = record.get("parent")
        if isinstance(parent, dict):
            parent_pid = parent.get("pid")
        else:
            parent_pid = parent
        if label == _LEGACY_LOCK_INVENTORY and (not isinstance(parent_pid, int) or parent_pid <= 0):
            raise RuntimeError(
                f"legacy evidence contract missing parent: {label} pid={pid} field=parent"
            )
        normalized.append(
            {
                **record,
                "pid": pid,
                "creation": creation,
                "historical_parent": parent,
            }
        )
        if isinstance(parent_pid, int) and parent_pid > 0:
            normalized[-1]["parent_pid"] = parent_pid
    return normalized


def _current_observation_records(value, label):
    if not isinstance(value, dict) or value.get("schema") != "citespan.node-current-approval.v1":
        raise RuntimeError(
            f"current evidence contract invalid {label}: expected schema=citespan.node-current-approval.v1"
        )
    if value.get("ownership_approved") is not True or value.get("cleanup_approved") is not True:
        raise RuntimeError(
            f"current evidence contract not approved {label}: ownership_approved=true and cleanup_approved=true are required"
        )
    if value.get("actor_id") != _OWNER_ACTOR or value.get("goal_id") != _OWNER_GOAL:
        raise RuntimeError(
            f"current evidence contract approval is not bound to actor {_OWNER_ACTOR} and goal {_OWNER_GOAL}: {label}"
        )
    if _canonical_path_identity(value.get("product_worktree", "")) != _canonical_path_identity(str(ROOT)):
        raise RuntimeError(f"current evidence contract approval has the wrong product worktree: {label}")
    observed_ids = value.get("observed_identity_pids")
    if not isinstance(observed_ids, list) or any(not isinstance(pid, int) or pid <= 0 for pid in observed_ids):
        raise RuntimeError(f"current evidence contract approval needs observed_identity_pids: {label}")
    approved_actions = value.get("approved_actions")
    if not isinstance(approved_actions, list) or not approved_actions or not all(
        isinstance(action, str) and action.strip() for action in approved_actions
    ):
        raise RuntimeError(f"current evidence contract approval needs narrow approved_actions: {label}")
    records = value.get("observations")
    if not isinstance(records, list) or not records:
        raise RuntimeError(f"current evidence contract invalid {label}: observations must be a non-empty list")
    for field in ("protected_processes", "unrelated_exclusions"):
        if not isinstance(value.get(field), list):
            raise RuntimeError(f"current evidence contract missing {field}: {label}")
        for exclusion in value[field]:
            if (
                not isinstance(exclusion, dict)
                or not isinstance(exclusion.get("pid"), int)
                or not isinstance(exclusion.get("reason"), str)
                or not exclusion["reason"].strip()
            ):
                raise RuntimeError(
                    f"current evidence contract invalid {field}: pid and measured reason are required"
                )
            required_identity = (
                "creation", "parent_pid", "cwd", "executable", "argv",
                "argv_sha256", "native_command_sha256",
            )
            missing_identity = [name for name in required_identity if name not in exclusion]
            if missing_identity:
                raise RuntimeError(
                    f"current evidence contract invalid {field}: full observed identity is required "
                    f"pid={exclusion['pid']} fields={missing_identity}"
                )
            if not isinstance(exclusion["argv"], list) or not exclusion["argv"] or not all(
                isinstance(item, str) for item in exclusion["argv"]
            ):
                raise RuntimeError(
                    f"current evidence contract invalid {field}: argv is required: pid={exclusion['pid']}"
                )
            if any(
                not isinstance(exclusion[name], str) or len(exclusion[name]) != 64
                for name in ("argv_sha256", "native_command_sha256")
            ):
                raise RuntimeError(
                    f"current evidence contract invalid {field}: hashes are required: pid={exclusion['pid']}"
                )
    normalized = []
    seen_pids = set()
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("pid"), int) or record["pid"] <= 0:
            raise RuntimeError(f"current evidence contract invalid {label}: each observation needs a positive pid")
        if record["pid"] in seen_pids:
            raise RuntimeError(f"current evidence contract duplicates observation: pid={record['pid']}")
        seen_pids.add(record["pid"])
        if record.get("role") not in {"lightningcss_loader", "related_test_family"}:
            raise RuntimeError(f"current evidence contract invalid {label}: each observation needs a valid role")
        if record.get("script_role") not in {"npm-cli.js", "start-server.js", "postcss.js", "none"}:
            raise RuntimeError(f"current evidence contract invalid script role: pid={record['pid']}")
        for field in (
            "creation",
            "parent_pid",
            "cwd",
            "executable",
            "argv",
            "argv_sha256",
            "native_command_sha256",
            "script_paths",
            "module_paths",
            "parent_observations",
            "files",
            "ports",
            "approval",
            "protected_or_unrelated_state",
        ):
            if field not in record:
                raise RuntimeError(f"current evidence contract missing {field}: pid={record.get('pid')}")
        if not isinstance(record["argv"], list) or not record["argv"] or not all(
            isinstance(item, str) for item in record["argv"]
        ):
            raise RuntimeError(f"current evidence contract invalid argv: pid={record['pid']}")
        if not isinstance(record["argv_sha256"], str) or len(record["argv_sha256"]) != 64:
            raise RuntimeError(f"current evidence contract invalid argv_sha256: pid={record['pid']}")
        if not isinstance(record["native_command_sha256"], str) or len(record["native_command_sha256"]) != 64:
            raise RuntimeError(
                f"current evidence contract invalid native_command_sha256: pid={record['pid']}"
            )
        if not isinstance(record["script_paths"], list) or not isinstance(record["module_paths"], list):
            raise RuntimeError(f"current evidence contract invalid list fields: pid={record['pid']}")
        if not isinstance(record["files"], list) or not isinstance(record["ports"], list):
            raise RuntimeError(
                f"current evidence contract missing required files or ports: pid={record['pid']}"
            )
        if record["role"] == "lightningcss_loader":
            native_path = (ROOT / _NATIVE_MODULE_RELATIVE).resolve()
            native_files = []
            for value in record["files"]:
                candidate_path = Path(value)
                if not candidate_path.is_absolute() and candidate_path.as_posix() == _NATIVE_MODULE_RELATIVE.as_posix():
                    native_files.append(candidate_path)
                elif candidate_path.is_absolute() and _canonical_path_identity(candidate_path) == _canonical_path_identity(native_path):
                    native_files.append(candidate_path)
            if len(native_files) != 1:
                raise RuntimeError(
                    f"current evidence contract loader lacks exactly the native module path: pid={record['pid']}"
                )
        if record["approval"] is not True:
            raise RuntimeError(f"current evidence contract target is not approved: pid={record['pid']}")
        if record.get("snapshot_status") == "incomplete" or record.get("proof_complete") is False:
            raise RuntimeError(
                f"current evidence contract rejects incomplete snapshot: pid={record['pid']}"
            )
        if record["protected_or_unrelated_state"] != "owned_descendant":
            raise RuntimeError(
                f"current evidence contract target is not an approved owned descendant: pid={record['pid']}"
            )
        observations = record["parent_observations"]
        if not isinstance(observations, list) or not observations:
            raise RuntimeError(f"current evidence contract invalid parent observations: pid={record['pid']}")
        for observation in observations:
            if not isinstance(observation, dict) or observation.get("state") not in _PARENT_STATES:
                raise RuntimeError(
                    f"current evidence contract invalid parent state: pid={record['pid']} observation={observation}"
                )
            if observation.get("state") == "historical_parent_exited_pid_reused":
                required = ("current_creation", "child_creation", "current_parent_pid")
                missing = [field for field in required if field not in observation]
                if missing:
                    raise RuntimeError(
                        f"current evidence contract incomplete reused-parent proof: "
                        f"pid={record['pid']} fields={missing}"
                    )
        normalized.append({**record, "current_modules": record["module_paths"]})
    return normalized


def _current_family_records(value, label):
    if not isinstance(value, dict) or value.get("schema") != "citespan.node-family-current.v1":
        raise RuntimeError(
            f"current family evidence contract invalid {label}: expected schema=citespan.node-family-current.v1"
        )
    if value.get("ownership_approved") is not False or value.get("cleanup_approved") is not False:
        raise RuntimeError(
            f"current family evidence must remain observation-only: {label} ownership_approved=false and cleanup_approved=false are required"
        )
    provenance = value.get("source_provenance")
    if not isinstance(provenance, dict) or not provenance:
        raise RuntimeError(
            f"current family evidence must retain source provenance: {label}"
        )
    records = value.get("observations")
    if not isinstance(records, list) or len(records) != 145:
        raise RuntimeError(
            f"current family evidence must contain all 145 measured identities: {label}"
        )
    normalized = []
    seen = set()
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("pid"), int) or record["pid"] <= 0:
            raise RuntimeError(f"current family evidence has an invalid identity: {label}")
        if record["pid"] in seen:
            raise RuntimeError(f"current family evidence duplicates identity: pid={record['pid']}")
        seen.add(record["pid"])
        required = (
            "creation", "parent_pid", "cwd", "executable", "argv", "argv_sha256",
            "native_command_sha256", "module_paths", "role", "family_relation", "files", "ports",
            "parent_observations", "ownership_approved", "cleanup_approved",
        )
        missing = [field for field in required if field not in record]
        if missing:
            raise RuntimeError(
                f"current family evidence is incomplete: pid={record['pid']} fields={missing}"
            )
        if record["ownership_approved"] is not False or record["cleanup_approved"] is not False:
            raise RuntimeError(
                f"current family evidence must preserve false observation approval flags: pid={record['pid']}"
            )
        if not isinstance(record["argv"], list) or not record["argv"] or not all(
            isinstance(item, str) for item in record["argv"]
        ):
            raise RuntimeError(f"current family evidence has invalid argv: pid={record['pid']}")
        for field in ("files", "ports", "parent_observations"):
            if not isinstance(record[field], list):
                raise RuntimeError(f"current family evidence has invalid {field}: pid={record['pid']}")
        normalized.append(record)
    if sum(record.get("role") == "lightningcss_loader" for record in normalized) != 29:
        raise RuntimeError("current family evidence must contain 29 lightningcss loaders")
    if sum(record.get("role") == "related_test_family" for record in normalized) != 116:
        raise RuntimeError("current family evidence must contain 116 related family identities")
    return normalized


def _legacy_family_observation_records(value, label):
    if not isinstance(value, dict) or value.get("schema") != "citespan.read-only-family-observation.v1":
        raise RuntimeError(
            f"legacy family evidence contract invalid {label}: "
            "expected schema=citespan.read-only-family-observation.v1"
        )
    if value.get("ownership_approved") is not False or value.get("cleanup_approved") is not False:
        raise RuntimeError(
            f"legacy family evidence must remain observation-only: {label}"
        )
    records = value.get("observations")
    if not isinstance(records, list) or len(records) != 145:
        raise RuntimeError(
            f"legacy family evidence must contain all 145 measured identities: {label}"
        )
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("pid"), int) or record["pid"] <= 0:
            raise RuntimeError(f"legacy family evidence has an invalid identity: {label}")
    return records


def _legacy_alias(record, field, aliases, *, required=True):
    """Read one measured value from its historical spelling.

    Historical observations are immutable. This function maps their measured
    names to the current internal names and rejects conflicting aliases.
    """
    values = []
    for alias in aliases:
        if alias in record:
            values.append((alias, record[alias]))
    if not values:
        if required:
            raise RuntimeError(
                f"legacy family evidence is missing required measured field: field={field}"
            )
        return None
    first = values[0][1]
    if any(value != first for _, value in values[1:]):
        raise RuntimeError(
            f"legacy family evidence has conflicting aliases: field={field} "
            f"aliases={[alias for alias, _ in values]}"
        )
    return first


def _legacy_identity_value(record, field, aliases, *, required=True):
    identity = record.get("identity")
    nested = identity if isinstance(identity, dict) else {}
    values = []
    for alias in aliases:
        if alias in record:
            values.append((alias, record[alias]))
        if alias in nested:
            values.append((f"identity.{alias}", nested[alias]))
    if not values:
        if required:
            raise RuntimeError(
                f"legacy family evidence is missing required identity field: field={field}"
            )
        return None
    first = values[0][1]
    if any(value != first for _, value in values[1:]):
        raise RuntimeError(
            f"legacy family evidence has conflicting identity aliases: field={field}"
        )
    return first


def _canonical_path_values(values, field, pid):
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise RuntimeError(f"legacy family evidence has invalid {field}: pid={pid}")
    return sorted(values, key=lambda value: _canonical_path_identity(value))


def _canonical_parent_observation(observation, pid):
    if not isinstance(observation, dict):
        raise RuntimeError(f"legacy family evidence has invalid parent observation: pid={pid}")
    identity = observation.get("identity")
    identity = identity if isinstance(identity, dict) else {}
    state = observation.get("state")
    result = {"state": state}
    if state not in _PARENT_STATES:
        raise RuntimeError(f"legacy family evidence has invalid parent state: pid={pid}")
    observed_pid = observation.get("pid", identity.get("pid"))
    if "pid" in observation and "pid" in identity and observation["pid"] != identity["pid"]:
        raise RuntimeError(f"legacy family evidence has conflicting parent values: pid={pid} field=pid")
    if not isinstance(observed_pid, int) or observed_pid <= 0:
        raise RuntimeError(f"legacy family evidence has invalid parent identity: pid={pid}")
    result["pid"] = observed_pid
    if "creation" in observation and "creation_token" in identity and observation["creation"] != identity["creation_token"]:
        raise RuntimeError(f"legacy family evidence has conflicting parent values: pid={pid} field=creation")
    creation = observation.get("creation", identity.get("creation_token"))
    if creation is not None:
        result["creation"] = creation
    measured_fields = {
        "parent_pid": ("parent_pid",),
        "cwd": ("cwd",),
        "executable": ("executable",),
        "argv": ("argv",),
        "argv_sha256": ("parsed_argv_sha256", "argv_sha256"),
        "native_command_sha256": ("command_sha256", "native_command_sha256"),
        "relation": ("relation",),
    }
    for normalized_field, raw_fields in measured_fields.items():
        values = []
        for raw_field in raw_fields:
            if raw_field in observation:
                values.append(observation[raw_field])
            if raw_field in identity:
                values.append(identity[raw_field])
        if values:
            if any(value != values[0] for value in values[1:]):
                raise RuntimeError(
                    f"legacy family evidence has conflicting parent values: pid={pid} field={normalized_field}"
                )
            result[normalized_field] = values[0]
    if "module_paths" in observation:
        result["module_paths"] = _canonical_path_values(observation["module_paths"], "module_paths", pid)
        result["files"] = list(result["module_paths"])
    if "files" in observation:
        result["files"] = _canonical_path_values(observation["files"], "files", pid)
    if "module_paths" in result and result["files"] != result["module_paths"]:
        raise RuntimeError(f"legacy family evidence has conflicting parent values: pid={pid} field=files")
    if "measured_listening_ports" in observation:
        result["ports"] = sorted(observation["measured_listening_ports"])
    elif "ports" in observation:
        result["ports"] = sorted(observation["ports"])
    return result


def _canonical_parent_observations(observations, pid):
    if not isinstance(observations, list) or not observations:
        raise RuntimeError(f"legacy family evidence has no parent observations: pid={pid}")
    canonical = {}
    for observation in observations:
        value = _canonical_parent_observation(observation, pid)
        key = (value["pid"], value.get("creation"), value["state"])
        previous = canonical.get(key)
        if previous is not None and previous != value:
            raise RuntimeError(
                f"legacy family evidence has contradictory parent enrichment: pid={pid} parent={value['pid']}"
            )
        canonical[key] = value
    return canonical


def _legacy_family_record_canonical(record, normalized_record):
    pid = _legacy_identity_value(record, "pid", ("pid",), required=True)
    creation = _legacy_identity_value(record, "creation", ("creation", "creation_token"), required=True)
    if pid != normalized_record["pid"] or creation != normalized_record["creation"]:
        raise RuntimeError(
            f"normalized current family evidence changed immutable observation: pid={pid} field=identity"
        )
    parent_pid = _legacy_alias(record, "parent_pid", ("parent_pid",), required=True)
    if not isinstance(parent_pid, int) or parent_pid <= 0:
        raise RuntimeError(f"legacy family evidence has invalid parent_pid: pid={pid}")
    aliases = {
        "cwd": ("cwd",),
        "executable": ("executable",),
        "argv": ("argv",),
        "argv_sha256": ("parsed_argv_sha256",),
        "native_command_sha256": ("command_sha256",),
        "module_paths": ("module_paths",),
        "ports": ("measured_listening_ports",),
        "parent_observations": ("parent_observations",),
    }
    result = {"pid": pid, "creation": creation, "parent_pid": parent_pid}
    for field, names in aliases.items():
        value = _legacy_alias(record, field, names, required=True)
        if field in {"module_paths", "ports"}:
            if field == "ports":
                if not isinstance(value, list):
                    raise RuntimeError(f"legacy family evidence has invalid ports: pid={pid}")
                value = sorted(value)
            else:
                value = _canonical_path_values(value, field, pid)
        result[field] = value
    result["files"] = list(result["module_paths"])
    result["parent_observations"] = _canonical_parent_observations(result["parent_observations"], pid)
    if not isinstance(result["argv"], list) or not all(isinstance(value, str) for value in result["argv"]):
        raise RuntimeError(f"legacy family evidence has invalid argv: pid={pid}")

    locked = any("lightningcss.win32-x64-msvc.node" in value for value in result["module_paths"])
    result["role"] = "lightningcss_loader" if locked else "related_test_family"
    historical = _legacy_alias(
        record,
        "historically_recorded_node",
        ("historically_recorded_node",),
        required=True,
    )
    if historical is not None and not isinstance(historical, bool):
        raise RuntimeError(f"legacy family evidence has invalid historical node flag: pid={pid}")
    result["family_relation"] = "historical_node" if historical else "additional_cmd_descendant"
    return result


def _assert_legacy_family_matches_normalized(legacy_record, normalized_record):
    actual = _legacy_family_record_canonical(legacy_record, normalized_record)
    expected = {
        "pid": normalized_record["pid"],
        "creation": normalized_record["creation"],
        "parent_pid": normalized_record["parent_pid"],
        "cwd": normalized_record["cwd"],
        "executable": normalized_record["executable"],
        "argv": normalized_record["argv"],
        "argv_sha256": normalized_record["argv_sha256"],
        "native_command_sha256": normalized_record["native_command_sha256"],
        "module_paths": _canonical_path_values(normalized_record["module_paths"], "module_paths", normalized_record["pid"]),
        "files": _canonical_path_values(normalized_record["files"], "files", normalized_record["pid"]),
        "ports": sorted(normalized_record["ports"]),
        "parent_observations": _canonical_parent_observations(
            normalized_record["parent_observations"], normalized_record["pid"]
        ),
    }
    for field, expected_value in expected.items():
        if field == "parent_observations":
            actual_parent = actual[field]
            expected_parent = expected_value
            for key, raw_observation in actual_parent.items():
                normalized_observation = expected_parent.get(key)
                if normalized_observation is None:
                    raise RuntimeError(
                        f"normalized current family evidence changed immutable observation: "
                        f"pid={normalized_record['pid']} field=parent_observations"
                    )
                for measured_field, measured_value in raw_observation.items():
                    if (
                        measured_field in normalized_observation
                        and normalized_observation[measured_field] != measured_value
                    ):
                        raise RuntimeError(
                            f"normalized current family evidence changed immutable observation: "
                            f"pid={normalized_record['pid']} field=parent_observations"
                        )
            for key, normalized_observation in expected_parent.items():
                if key not in actual_parent and normalized_observation.get("pid") != normalized_record["pid"]:
                    raise RuntimeError(
                        f"normalized current family evidence changed immutable observation: "
                        f"pid={normalized_record['pid']} field=parent_observations"
                    )
            continue
        if actual[field] != expected_value:
            raise RuntimeError(
                f"normalized current family evidence changed immutable observation: "
                f"pid={normalized_record['pid']} field={field}"
            )
    if actual["role"] != normalized_record["role"]:
        raise RuntimeError(
            f"normalized current family evidence changed immutable observation: "
            f"pid={normalized_record['pid']} field=role"
        )
    normalized_relation = str(normalized_record["family_relation"]).lower()
    expected_relation = actual["family_relation"]
    if (expected_relation == "historical_node" and not ("historical" in normalized_relation or "node" in normalized_relation)) or (
        expected_relation == "additional_cmd_descendant"
        and not ("cmd" in normalized_relation or "descendant" in normalized_relation)
    ):
        raise RuntimeError(
            f"normalized current family evidence changed immutable observation: "
            f"pid={normalized_record['pid']} field=family_relation"
        )


def _assert_family_source_provenance(legacy_document, normalized_document):
    normalized_provenance = normalized_document.get("source_provenance")
    if not isinstance(normalized_provenance, dict) or not normalized_provenance:
        raise RuntimeError("normalized current family evidence has no source provenance")
    legacy_provenance = legacy_document.get("source_provenance")
    if isinstance(legacy_provenance, dict):
        for field, value in legacy_provenance.items():
            if field in normalized_provenance and normalized_provenance[field] != value:
                raise RuntimeError(
                    f"normalized current family evidence changed source provenance: field={field}"
                )
    for field in ("source_hash", "sha256", "original_source_sha256"):
        if field in legacy_document and normalized_provenance.get(field) != legacy_document[field]:
            raise RuntimeError(
                f"normalized current family evidence changed source provenance: field={field}"
            )


def test_legacy_family_mapping_accepts_measured_aliases_and_self_parent_expansion():
    parent = {
        "state": "readable_current_parent",
        "identity": {
            "pid": 41,
            "creation_token": "parent-token",
            "cwd": "C:/work",
            "executable": "C:/node.exe",
            "argv": ["node", "start-server.js"],
            "parsed_argv_sha256": "a" * 64,
            "command_sha256": "b" * 64,
        },
        "relation": "historical-parent",
    }
    legacy = {
        "pid": 42,
        "identity": {"creation_token": "child-token"},
        "parent_pid": 41,
        "cwd": "C:/work",
        "executable": "C:/node.exe",
        "argv": ["node", "postcss.js"],
        "parsed_argv_sha256": "c" * 64,
        "command_sha256": "d" * 64,
        "module_paths": ["C:/work/lightningcss.win32-x64-msvc.node"],
        "measured_listening_ports": [4100],
        "parent_observations": [parent],
        "historically_recorded_node": True,
    }
    normalized = {
        "pid": 42,
        "creation": "child-token",
        "parent_pid": 41,
        "cwd": "C:/work",
        "executable": "C:/node.exe",
        "argv": ["node", "postcss.js"],
        "argv_sha256": "c" * 64,
        "native_command_sha256": "d" * 64,
        "module_paths": ["C:/work/lightningcss.win32-x64-msvc.node"],
        "files": ["C:/work/lightningcss.win32-x64-msvc.node"],
        "ports": [4100],
        "role": "lightningcss_loader",
        "family_relation": "historical_node_process",
        "parent_observations": [parent, {"state": "readable_current_parent", "pid": 42}],
    }
    _assert_legacy_family_matches_normalized(legacy, normalized)


def test_legacy_family_mapping_rejects_hash_file_and_port_changes():
    base = {
        "pid": 42,
        "identity": {"creation_token": "child-token"},
        "parent_pid": 41,
        "cwd": "C:/work",
        "executable": "C:/node.exe",
        "argv": ["node", "start-server.js"],
        "parsed_argv_sha256": "a" * 64,
        "command_sha256": "b" * 64,
        "module_paths": ["C:/work/module.node"],
        "measured_listening_ports": [4100],
        "parent_observations": [{"state": "verified_absent_historical_parent", "pid": 41}],
        "historically_recorded_node": True,
    }
    normalized = {
        "pid": 42,
        "creation": "child-token",
        "parent_pid": 41,
        "cwd": "C:/work",
        "executable": "C:/node.exe",
        "argv": ["node", "start-server.js"],
        "argv_sha256": "a" * 64,
        "native_command_sha256": "b" * 64,
        "module_paths": ["C:/work/module.node"],
        "files": ["C:/work/module.node"],
        "ports": [4100],
        "role": "related_test_family",
        "family_relation": "historical_node",
        "parent_observations": [{"state": "verified_absent_historical_parent", "pid": 41}],
    }
    for field, value in (("parsed_argv_sha256", "c" * 64), ("command_sha256", "d" * 64)):
        changed = dict(base)
        changed[field] = value
        with pytest.raises(RuntimeError, match="immutable observation"):
            _assert_legacy_family_matches_normalized(changed, normalized)
    changed = dict(base)
    changed["module_paths"] = ["C:/work/other.node"]
    with pytest.raises(RuntimeError, match="immutable observation"):
        _assert_legacy_family_matches_normalized(changed, normalized)
    changed = dict(base)
    changed["measured_listening_ports"] = [4101]
    with pytest.raises(RuntimeError, match="immutable observation"):
        _assert_legacy_family_matches_normalized(changed, normalized)


def test_legacy_family_mapping_rejects_missing_measured_fields_and_guesses():
    base = {
        "pid": 42,
        "identity": {"creation_token": "child-token"},
        "parent_pid": 41,
        "cwd": "C:/work",
        "executable": "C:/node.exe",
        "argv": ["node", "start-server.js"],
        "parsed_argv_sha256": "a" * 64,
        "command_sha256": "b" * 64,
        "module_paths": ["C:/work/module.node"],
        "measured_listening_ports": [4100],
        "parent_observations": [{"state": "verified_absent_historical_parent", "pid": 41}],
        "historically_recorded_node": True,
    }
    for field in ("module_paths", "measured_listening_ports", "historically_recorded_node"):
        changed = dict(base)
        changed.pop(field)
        with pytest.raises(RuntimeError, match="missing required measured field"):
            _legacy_family_record_canonical(changed, {"pid": 42, "creation": "child-token"})


def test_parent_pid_is_distinct_from_observed_parent_pid_and_order_is_ignored():
    first = {
        "state": "readable_current_parent",
        "identity": {
            "pid": 17104,
            "creation_token": "parent-token",
            "cwd": "C:/parent",
            "executable": "C:/node.exe",
            "argv": ["node", "parent.js"],
            "parsed_argv_sha256": "a" * 64,
            "command_sha256": "b" * 64,
        },
        "parent_pid": 32560,
        "relation": "historical-parent",
        "module_paths": ["C:/work/module.node"],
        "measured_listening_ports": [4200],
    }
    enriched = dict(first)
    enriched["identity"] = dict(first["identity"])
    enriched["identity"]["extra"] = "measured-enrichment"
    assert _canonical_parent_observation(first, 42)["pid"] == 17104
    assert _canonical_parent_observation(first, 42)["parent_pid"] == 32560
    assert _canonical_parent_observations([first, enriched], 42) == _canonical_parent_observations([enriched, first], 42)
    expanded = {
        "state": "readable_current_parent",
        "pid": 17104,
        "creation": "parent-token",
        "parent_pid": 32560,
        "cwd": "C:/parent",
        "executable": "C:/node.exe",
        "argv": ["node", "parent.js"],
        "argv_sha256": "a" * 64,
        "native_command_sha256": "b" * 64,
        "module_paths": ["C:/work/module.node"],
        "files": ["C:/work/module.node"],
        "ports": [4200],
        "relation": "historical-parent",
    }
    assert _canonical_parent_observations([first], 42) == _canonical_parent_observations([expanded], 42)

    contradictory = dict(first)
    contradictory["parent_pid"] = 32561
    with pytest.raises(RuntimeError, match="contradictory parent enrichment"):
        _canonical_parent_observations([first, contradictory], 42)


def _validate_additional_descendants(value, label):
    records = value.get("additional_descendants")
    if not isinstance(records, list):
        raise RuntimeError(f"current evidence contract missing additional_descendants: {label}")
    normalized = []
    seen_pids = set()
    for record in records:
        if not isinstance(record, dict):
            raise RuntimeError(f"current evidence contract invalid additional descendant: {label}")
        required = (
            "pid", "creation", "parent_pid", "cwd", "executable", "argv",
            "argv_sha256", "native_command_sha256", "role", "family_relation",
            "protected_or_unrelated_state",
            "files", "ports", "approval",
        )
        missing = [field for field in required if field not in record]
        if missing:
            raise RuntimeError(
                f"current evidence contract missing additional descendant fields: "
                f"pid={record.get('pid')} fields={missing}"
            )
        if not isinstance(record["pid"], int) or record["pid"] <= 0:
            raise RuntimeError("current evidence contract invalid additional descendant pid")
        if record["pid"] in seen_pids:
            raise RuntimeError(f"current evidence contract duplicates additional descendant: pid={record['pid']}")
        seen_pids.add(record["pid"])
        if record["role"] != "related_test_family" or not isinstance(record["family_relation"], str) or not record["family_relation"].strip():
            raise RuntimeError(
                f"current evidence contract invalid additional descendant family relation: pid={record.get('pid')}"
            )
        if record["protected_or_unrelated_state"] != "owned_descendant":
            raise RuntimeError(
                f"current evidence contract invalid additional descendant exclusion state: pid={record.get('pid')}"
            )
        if (
            not isinstance(record["argv_sha256"], str)
            or len(record["argv_sha256"]) != 64
            or not isinstance(record["native_command_sha256"], str)
            or len(record["native_command_sha256"]) != 64
        ):
            raise RuntimeError(f"current evidence contract invalid additional descendant hashes: pid={record['pid']}")
        if record["approval"] is not True:
            raise RuntimeError(f"current evidence contract additional descendant is not approved: pid={record['pid']}")
        if not isinstance(record["argv"], list) or not record["argv"] or not all(
            isinstance(item, str) for item in record["argv"]
        ):
            raise RuntimeError(f"current evidence contract invalid additional descendant argv: pid={record['pid']}")
        if not isinstance(record["files"], list) or not isinstance(record["ports"], list):
            raise RuntimeError(f"current evidence contract missing additional files or ports: pid={record['pid']}")
        if not isinstance(record["parent_observations"], list) or not record["parent_observations"]:
            raise RuntimeError(
                f"current evidence contract missing additional parent observations: pid={record['pid']}"
            )
        normalized.append(record)
    return normalized


def _current_cleanup_observation(value, label):
    if not isinstance(value, dict):
        raise RuntimeError(f"current cleanup evidence invalid {label}: expected an object")
    records = value.get("observations")
    if not isinstance(records, list) or not records:
        raise RuntimeError(f"current cleanup evidence invalid {label}: observations are required")
    normalized = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("pid"), int) or record["pid"] <= 0:
            raise RuntimeError(f"current cleanup evidence invalid {label}: each observation needs a positive pid")
        pid = record["pid"]
        if pid in normalized:
            raise RuntimeError(f"current cleanup evidence duplicates pid={pid}: {label}")
        expected = record.get("expected_creation", record.get("expected_token"))
        current = record.get("current_creation", record.get("current_token"))
        state = record.get("state", record.get("status"))
        if not isinstance(expected, str) or not expected:
            raise RuntimeError(f"current cleanup evidence missing expected token: {label} pid={pid}")
        if state not in {"absent", "reused", "live", "present"}:
            raise RuntimeError(f"current cleanup evidence has an unsafe state: {label} pid={pid} state={state!r}")
        if state == "absent" and current not in (None, ""):
            raise RuntimeError(f"current cleanup evidence records a current token for an absent pid: {label} pid={pid}")
        if state == "reused" and (not isinstance(current, str) or not current or current == expected):
            raise RuntimeError(f"current cleanup evidence does not prove PID reuse: {label} pid={pid}")
        if state in {"live", "present"} and current != expected:
            raise RuntimeError(f"current cleanup evidence does not prove the exact live identity: {label} pid={pid}")
        normalized[pid] = {**record, "expected_creation": expected, "current_creation": current, "state": state}
    return normalized


def _current_frontend_observation(value, label):
    if not isinstance(value, dict):
        raise RuntimeError(f"current frontend evidence invalid {label}: expected an object")
    processes = value.get("product_frontend_processes", value.get("frontend_processes"))
    holders = value.get("native_module_holders")
    read_errors = value.get("read_errors", [])
    ports = value.get("listening_ports", value.get("ports", []))
    if not isinstance(processes, list) or not isinstance(holders, list):
        raise RuntimeError(
            f"current frontend evidence invalid {label}: product_frontend_processes and native_module_holders are required"
        )
    if not isinstance(read_errors, list) or read_errors:
        raise RuntimeError(f"current frontend evidence has read errors: {label} errors={read_errors}")
    if not isinstance(ports, list):
        raise RuntimeError(f"current frontend evidence invalid {label}: listening ports must be a list")
    for item in [*processes, *holders]:
        if not isinstance(item, dict) or not isinstance(item.get("pid"), int) or item["pid"] <= 0:
            raise RuntimeError(f"current frontend evidence has an invalid identity: {label}")
    return {"processes": processes, "holders": holders, "ports": ports}


def _load_current_cleanup_observations(evidence_root):
    documents = {}
    for filename in (_CURRENT_FAMILY_PRESENCE, _CURRENT_FRONTEND_PROCESSES):
        path = evidence_root / filename
        if not path.is_file():
            raise RuntimeError(f"frontend dependency evidence is missing: {path}")
        try:
            documents[filename] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"frontend dependency evidence cannot be read: {path}: {exc}") from exc
    return (
        _current_cleanup_observation(documents[_CURRENT_FAMILY_PRESENCE], _CURRENT_FAMILY_PRESENCE),
        _current_frontend_observation(documents[_CURRENT_FRONTEND_PROCESSES], _CURRENT_FRONTEND_PROCESSES),
    )


def test_current_cleanup_observation_accepts_absence_and_exact_pid_reuse():
    records = _current_cleanup_observation(
        {
            "observations": [
                {"pid": 101, "expected_creation": "old-101", "state": "absent"},
                {
                    "pid": 102,
                    "expected_creation": "old-102",
                    "current_creation": "new-102",
                    "state": "reused",
                },
            ]
        },
        "fixture",
    )
    assert records[101]["state"] == "absent"
    assert records[102]["current_creation"] != records[102]["expected_creation"]


def test_current_cleanup_observation_requires_approval_only_for_exact_live_identity():
    live = _current_cleanup_observation(
        {
            "observations": [
                {
                    "pid": 103,
                    "expected_creation": "old-103",
                    "current_creation": "old-103",
                    "state": "live",
                }
            ]
        },
        "fixture",
    )
    assert [pid for pid, record in live.items() if record["state"] in {"live", "present"}] == [103]
    with pytest.raises(RuntimeError, match="does not prove PID reuse"):
        _current_cleanup_observation(
            {
                "observations": [
                    {
                        "pid": 104,
                        "expected_creation": "old-104",
                        "current_creation": "old-104",
                        "state": "reused",
                    }
                ]
            },
            "fixture",
        )


def test_current_frontend_observation_denies_unapproved_relevant_holder(monkeypatch):
    monkeypatch.setattr(
        sys.modules[__name__],
        "_load_current_cleanup_observations",
        lambda _root: (
            {},
            {
                "processes": [],
                "holders": [{"pid": 105}],
                "ports": [],
            },
        ),
    )
    with pytest.raises(RuntimeError, match="native module holders remain"):
        _assert_cleanup_postcondition_already_satisfied(ROOT)


def test_native_resource_absence_is_a_released_postcondition(tmp_path):
    result = _assert_native_resource_released(tmp_path / "lightningcss.win32-x64-msvc.node", "fixture")

    assert result["state"] == "absent"
    assert result["error"] == "FileNotFoundError/ENOENT"


def test_native_resource_existing_file_is_replaced_and_restored(tmp_path):
    path = tmp_path / "lightningcss.win32-x64-msvc.node"
    original = b"native-module"
    path.write_bytes(original)

    result = _assert_native_resource_released(path, "fixture")

    assert result["state"] == "restored"
    assert path.read_bytes() == original


def _native_stat_with(metadata, **changes):
    fields = {
        name: getattr(metadata, name)
        for name in (
            "st_mode",
            "st_size",
            "st_dev",
            "st_ino",
            "st_mtime_ns",
            "st_ctime_ns",
            "st_atime_ns",
        )
    }
    fields.update(changes)
    return SimpleNamespace(**fields)


def test_native_resource_accepts_access_time_only_change(tmp_path, monkeypatch):
    path = tmp_path / "lightningcss.win32-x64-msvc.node"
    path.write_bytes(b"native-module")
    initial = os.lstat(path)
    changed = _native_stat_with(
        initial,
        st_atime_ns=initial.st_atime_ns + 1_000_000_000,
    )
    real_lstat = os.lstat
    calls = 0

    def lstat(candidate):
        nonlocal calls
        if candidate == path:
            calls += 1
            return (initial, changed, initial)[min(calls - 1, 2)]
        return real_lstat(candidate)

    monkeypatch.setattr(os, "lstat", lstat)

    assert _assert_native_resource_released(path, "fixture")["state"] == "restored"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("st_ino", "increment"),
        ("st_mode", "mode"),
        ("st_size", "increment"),
        ("st_mtime_ns", "increment"),
        ("st_ctime_ns", "increment"),
    ],
)
def test_native_resource_rejects_stable_identity_changes(tmp_path, monkeypatch, field, value):
    path = tmp_path / "lightningcss.win32-x64-msvc.node"
    path.write_bytes(b"native-module")
    initial = os.lstat(path)
    changed_value = (
        stat.S_IFREG | (stat.S_IMODE(initial.st_mode) ^ stat.S_IWRITE)
        if value == "mode"
        else getattr(initial, field) + 1
    )
    changed = _native_stat_with(initial, **{field: changed_value})
    real_lstat = os.lstat
    calls = 0

    def lstat(candidate):
        nonlocal calls
        if candidate == path:
            calls += 1
            return initial if calls == 1 else changed
        return real_lstat(candidate)

    monkeypatch.setattr(os, "lstat", lstat)

    with pytest.raises(RuntimeError, match="changed before replace"):
        _assert_native_resource_released(path, "fixture")
    assert path.read_bytes() == b"native-module"


def test_native_resource_rejects_regular_file_type_change(tmp_path, monkeypatch):
    path = tmp_path / "lightningcss.win32-x64-msvc.node"
    path.write_bytes(b"native-module")
    initial = os.lstat(path)
    changed = _native_stat_with(initial, st_mode=stat.S_IFDIR | stat.S_IMODE(initial.st_mode))
    real_lstat = os.lstat
    calls = 0

    def lstat(candidate):
        nonlocal calls
        if candidate == path:
            calls += 1
            return initial if calls == 1 else changed
        return real_lstat(candidate)

    monkeypatch.setattr(os, "lstat", lstat)

    with pytest.raises(RuntimeError, match="changed before replace"):
        _assert_native_resource_released(path, "fixture")


def test_native_resource_rejects_content_change_before_replace(tmp_path, monkeypatch):
    path = tmp_path / "lightningcss.win32-x64-msvc.node"
    path.write_bytes(b"native-module")
    real_read_bytes = Path.read_bytes
    reads = 0

    def read_bytes(candidate):
        nonlocal reads
        if candidate == path:
            reads += 1
            if reads == 2:
                return b"changed-bytes"
        return real_read_bytes(candidate)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)

    with pytest.raises(RuntimeError, match="content changed before replace"):
        _assert_native_resource_released(path, "fixture")
    assert real_read_bytes(path) == b"native-module"


def test_native_resource_permission_error_fails_loudly(tmp_path, monkeypatch):
    path = tmp_path / "lightningcss.win32-x64-msvc.node"
    path.write_bytes(b"native-module")
    real_read_bytes = Path.read_bytes

    def deny_read(candidate):
        if candidate == path:
            raise PermissionError(errno.EACCES, "permission denied", str(path))
        return real_read_bytes(candidate)

    monkeypatch.setattr(Path, "read_bytes", deny_read)
    with pytest.raises(RuntimeError, match="permission denied"):
        _assert_native_resource_released(path, "fixture")


def test_native_resource_wrong_type_fails_loudly(tmp_path):
    path = tmp_path / "lightningcss.win32-x64-msvc.node"
    path.mkdir()

    with pytest.raises(RuntimeError, match="not a regular file"):
        _assert_native_resource_released(path, "fixture")


def test_native_resource_replacement_failure_fails_loudly(tmp_path, monkeypatch):
    path = tmp_path / "lightningcss.win32-x64-msvc.node"
    path.write_bytes(b"native-module")

    def fail_replace(_source, _target):
        raise OSError(errno.EACCES, "replacement denied")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(RuntimeError, match="replacement operation failed"):
        _assert_native_resource_released(path, "fixture")
    assert path.read_bytes() == b"native-module"


def test_native_resource_restoration_failure_fails_loudly(tmp_path, monkeypatch):
    path = tmp_path / "lightningcss.win32-x64-msvc.node"
    replacement = path.with_name(path.name + ".citespan-release-proof")
    path.write_bytes(b"native-module")
    real_replace = os.replace
    calls = 0

    def replace_then_fail(source, target):
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_replace(source, target)
        raise OSError(errno.EACCES, "restoration denied")

    monkeypatch.setattr(os, "replace", replace_then_fail)
    with pytest.raises(RuntimeError, match="restoration operation failed"):
        _assert_native_resource_released(path, "fixture")
    monkeypatch.undo()
    if replacement.exists():
        real_replace(replacement, path)


def test_cleanup_checks_process_state_before_native_resource(tmp_path, monkeypatch):
    order = []

    def load_observations(_root):
        order.append("process-module-port-checks")
        return ({101: {"state": "absent"}}, {"processes": [], "holders": [], "ports": []})

    def resource_check(_path, label):
        order.append("native-resource-check")
        assert "postcondition" in label
        return {"state": "absent"}

    monkeypatch.setattr(sys.modules[__name__], "_load_current_cleanup_observations", load_observations)
    monkeypatch.setattr(sys.modules[__name__], "_assert_native_resource_released", resource_check)
    result = _assert_cleanup_postcondition_already_satisfied(tmp_path)

    assert order == ["process-module-port-checks", "native-resource-check"]
    assert result["native_resource"]["state"] == "absent"


def _load_legacy_process_evidence():
    """Delegate evidence loading and reconciliation to production release.py."""
    contract = release._load_host_process_contract()
    approval = contract["approval"] or {}
    return (
        contract["root"],
        contract["node_records"],
        contract["additional_records"],
        contract["family_records"],
        approval.get("protected_processes", []),
        approval.get("unrelated_exclusions", []),
        contract["presence"],
        contract["approval_records"],
    )


def _frontend_process_graph():
    if _PLATFORM.name != "nt":
        return {
            pid: {
                "pid": pid,
                "parent_pid": item["parent_pid"],
                "name": "",
                "executable": "",
                "command": "",
            }
            for item in _current_process_tree(os.getpid())
            for pid in (item["pid"],)
        }
    command = (
        "Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine "
        "| ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"frontend dependency parent graph failed: rc={result.returncode} stdout={result.stdout[-2000:]} "
            f"stderr={result.stderr[-2000:]}"
        )
    raw = json.loads(result.stdout)
    rows = raw if isinstance(raw, list) else [raw]
    graph = {}
    for row in rows:
        if row.get("ProcessId") is None or row.get("ParentProcessId") is None:
            continue
        graph[int(row["ProcessId"])] = {
            "pid": int(row["ProcessId"]),
            "parent_pid": int(row["ParentProcessId"]),
            "name": str(row.get("Name") or "").casefold(),
            "executable": str(row.get("ExecutablePath") or ""),
            "command": str(row.get("CommandLine") or ""),
        }
    return graph


def _creation_token_is_newer(current_creation, child_creation):
    """Compare native creation tokens without treating an opaque token as ordered."""
    try:
        current_value = int(str(current_creation), 10)
        child_value = int(str(child_creation), 10)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"frontend dependency parent proof has non-orderable creation tokens: "
            f"current={current_creation!r} child={child_creation!r}"
        ) from exc
    return current_value > child_value


def _frontend_enrich_process_graph(graph, pids):
    """Add native identity only for selected or potentially relevant processes."""
    for pid in sorted(set(pids)):
        if pid == 0:
            raise RuntimeError("frontend dependency process proof must not inspect PID 0")
        if pid not in graph:
            raise RuntimeError(f"frontend dependency process proof is missing live pid={pid}")
        metadata = _process_metadata(pid)
        for field in ("creation", "parent_pid", "cwd", "executable", "command"):
            if field not in metadata or metadata[field] in (None, ""):
                raise RuntimeError(
                    f"frontend dependency relevant identity is incomplete: pid={pid} field={field}"
                )
        graph[pid].update(metadata)
        graph[pid]["enriched"] = True


def _frontend_lightweight_exclusion(item):
    """Return a measured exclusion reason for a clearly unrelated process row."""
    name = str(item.get("name") or "").casefold()
    executable = Path(str(item.get("executable") or "")).name.casefold()
    command = str(item.get("command") or "").casefold()
    node_or_cmd = {"node", "node.exe", "cmd", "cmd.exe", "npm", "npm.cmd", "npm-cli.js"}
    if name in node_or_cmd or executable in node_or_cmd:
        return None
    if any(marker in command for marker in ("node_modules", "npm-cli.js", "start-server.js", "postcss.js")):
        return None
    if not name and not executable and not command:
        return None
    return f"measured process type is not Node or cmd.exe: name={name!r} executable={executable!r}"


def _frontend_lightweight_relevance(item, expected_cwd):
    """Return whether lightweight facts identify the frontend test family."""
    name = str(item.get("name") or "").casefold()
    executable = str(item.get("executable") or "").casefold()
    command = str(item.get("command") or "").casefold()
    node_or_cmd = {"node", "node.exe", "cmd", "cmd.exe", "npm", "npm.cmd", "npm-cli.js"}
    executable_name = Path(executable).name.casefold()
    if name not in node_or_cmd and executable_name not in node_or_cmd:
        return False
    expected = str(expected_cwd).replace("\\", "/").casefold().rstrip("/")
    facts = " ".join((executable, command)).replace("\\", "/")
    return expected in facts or any(
        marker in facts for marker in ("npm-cli.js", "start-server.js", "postcss.js")
    )


def _frontend_lightweight_exclusion_for_expected(item, expected_cwd):
    """Return a measured reason when a process is not relevant to frontend work."""
    if _frontend_lightweight_relevance(item, expected_cwd):
        return None
    return (
        "measured Node/cmd identity is not related to the CiteSpan frontend/test family: "
        f"pid={item.get('pid')} name={item.get('name')!r} "
        f"executable={item.get('executable')!r} command={item.get('command')!r}"
    )


def _frontend_enrichment_pids(graph, explicit_pids, protected_pids, expected_cwd):
    """Select only explicit or lightweight-proven relevant identities for native reads."""
    explicit = set(explicit_pids)
    protected = set(protected_pids)
    return explicit | {
        pid
        for pid, item in graph.items()
        if pid not in explicit
        and pid not in protected
        and _frontend_lightweight_relevance(item, expected_cwd)
    }


def _frontend_current_argv(command):
    return _windows_command_line_argv(command) if _PLATFORM.name == "nt" else command.split()


def _frontend_selection_identity(record, current):
    """Check the full fresh identity before a record can enter cleanup selection."""
    required = (
        "creation",
        "parent_pid",
        "cwd",
        "executable",
        "command",
    )
    missing = [field for field in required if current.get(field) in (None, "")]
    if missing:
        raise RuntimeError(
            f"frontend dependency fresh identity is unreadable: pid={record['pid']} fields={missing}"
        )
    if str(current["creation"]) != str(record["creation"]):
        return "reused"
    current_argv = _frontend_current_argv(current["command"])
    expected_argv = [str(item) for item in record["argv"]]
    mismatches = []
    if int(current["parent_pid"]) != int(record["parent_pid"]):
        mismatches.append("parent_pid")
    if _canonical_path_identity(current["cwd"]) != _canonical_path_identity(record["cwd"]):
        mismatches.append("cwd")
    if _canonical_path_identity(current["executable"]) != _canonical_path_identity(record["executable"]):
        mismatches.append("executable")
    if current_argv != expected_argv:
        mismatches.append("argv")
    if hashlib.sha256("\0".join(current_argv).encode("utf-8")).hexdigest() != str(record["argv_sha256"]):
        mismatches.append("argv_sha256")
    if hashlib.sha256(current["command"].encode("utf-8")).hexdigest() != str(record["native_command_sha256"]):
        mismatches.append("native_command_sha256")
    if mismatches:
        raise RuntimeError(
            f"frontend dependency fresh identity changed before selection: "
            f"pid={record['pid']} fields={mismatches}"
        )
    if record.get("role") not in {"lightningcss_loader", "related_test_family"}:
        raise RuntimeError(f"frontend dependency fresh identity has an invalid role: pid={record['pid']}")
    if not isinstance(record.get("files"), list) or not isinstance(record.get("ports"), list):
        raise RuntimeError(
            f"frontend dependency fresh identity lacks required resource evidence: pid={record['pid']}"
        )
    if record["role"] == "related_test_family":
        if record.get("script_paths") or record.get("argv_role") != current_argv:
            raise RuntimeError(
                f"frontend dependency fresh identity changed normalized related role: pid={record['pid']}"
            )
    elif not any(str(path) in current_argv for path in record.get("script_paths", [])):
        raise RuntimeError(
            f"frontend dependency fresh identity lacks normalized script role: pid={record['pid']}"
        )
    return "exact"


def _frontend_approval_matches(record, approval):
    if not isinstance(approval, dict) or approval.get("approval") is not True:
        return False
    fields = (
        "creation",
        "parent_pid",
        "cwd",
        "executable",
        "argv",
        "argv_sha256",
        "native_command_sha256",
        "role",
        "family_relation",
        "module_paths",
        "files",
        "ports",
        "parent_observations",
    )
    return all(field in approval and approval.get(field) == record.get(field) for field in fields)


def _classify_frontend_records(records, process_graph, presence, approval_records):
    """Return only exact, narrowly approved records and explicit identity states."""
    approval_by_pid = {record["pid"]: record for record in approval_records}
    selected = []
    states = {}
    for record in records:
        pid = record["pid"]
        if pid not in process_graph:
            states[pid] = "absent"
            continue
        try:
            current = _process_metadata(pid)
        except RuntimeError as exc:
            raise RuntimeError(
                f"frontend dependency fresh identity classification failed: pid={pid} error={exc}"
            ) from exc
        state = _frontend_selection_identity(record, current)
        if state == "reused":
            states[pid] = "reused"
            continue
        observed = presence.get(pid)
        if not isinstance(observed, dict) or observed.get("state") not in {"live", "present"}:
            raise RuntimeError(
                f"frontend dependency exact-live identity has conflicting presence evidence: pid={pid}"
            )
        if not _frontend_approval_matches(record, approval_by_pid.get(pid)):
            raise RuntimeError(
                f"frontend dependency exact-live identity lacks narrow approval: pid={pid}"
            )
        states[pid] = "exact-live-approved"
        selected.append(record)
    return selected, states


def _selection_fixture_record(pid=52068):
    command = "node app.js"
    argv = command.split()
    return {
        "pid": pid,
        "creation": "134362896003443842",
        "parent_pid": 1,
        "cwd": str(ROOT / "frontend"),
        "executable": "node.exe",
        "argv": argv,
        "argv_sha256": hashlib.sha256("\0".join(argv).encode()).hexdigest(),
        "native_command_sha256": hashlib.sha256(command.encode()).hexdigest(),
        "role": "related_test_family",
        "family_relation": "measured historical Node family identity",
        "script_paths": [],
        "argv_role": argv,
        "module_paths": ["frontend/node_modules/lightningcss.node"],
        "files": ["frontend/node_modules/lightningcss.node"],
        "ports": [4100],
        "parent_observations": [{"pid": pid, "state": "verified_absent_historical_parent"}],
    }


def _selection_fixture_metadata(record, *, creation=None, executable=None):
    return {
        "pid": record["pid"],
        "parent_pid": record["parent_pid"],
        "creation": creation or record["creation"],
        "cwd": record["cwd"],
        "executable": executable or record["executable"],
        "command": " ".join(record["argv"]),
    }


def test_frontend_selection_classifies_reused_node_pid_without_selecting_dllhost(monkeypatch):
    record = _selection_fixture_record()
    replacement = _selection_fixture_metadata(
        record,
        creation="134363678673069120",
        executable="C:\\Windows\\System32\\dllhost.exe",
    )
    monkeypatch.setattr(sys.modules[__name__], "_process_metadata", lambda _pid: replacement)

    selected, states = _classify_frontend_records(
        [record],
        {record["pid"]: {}},
        {record["pid"]: {"state": "reused"}},
        [],
    )

    assert selected == []
    assert states == {record["pid"]: "reused"}


def test_frontend_selection_rejects_exact_live_identity_without_narrow_approval(monkeypatch):
    record = _selection_fixture_record(52069)
    monkeypatch.setattr(
        sys.modules[__name__], "_process_metadata", lambda _pid: _selection_fixture_metadata(record)
    )

    with pytest.raises(RuntimeError, match="lacks narrow approval"):
        _classify_frontend_records(
            [record],
            {record["pid"]: {}},
            {record["pid"]: {"state": "live"}},
            [],
        )


def test_frontend_selection_fails_loudly_when_fresh_identity_is_unreadable(monkeypatch):
    record = _selection_fixture_record(52070)

    def unreadable(_pid):
        raise RuntimeError("native identity access denied")

    monkeypatch.setattr(sys.modules[__name__], "_process_metadata", unreadable)

    with pytest.raises(RuntimeError, match="fresh identity classification failed"):
        _classify_frontend_records(
            [record],
            {record["pid"]: {}},
            {record["pid"]: {"state": "live"}},
            [],
        )


def test_frontend_selection_accepts_only_a_fully_matched_narrow_approval(monkeypatch):
    record = _selection_fixture_record(52071)
    approval = {**record, "approval": True}
    monkeypatch.setattr(
        sys.modules[__name__], "_process_metadata", lambda _pid: _selection_fixture_metadata(record)
    )

    selected, states = _classify_frontend_records(
        [record],
        {record["pid"]: {}},
        {record["pid"]: {"state": "live"}},
        [approval],
    )

    assert selected == [record]
    assert states == {record["pid"]: "exact-live-approved"}


def test_frontend_pre_stop_identity_change_fails_before_tree_cleanup(monkeypatch):
    record = _selection_fixture_record(52072)
    monkeypatch.setattr(
        sys.modules[__name__],
        "_process_metadata",
        lambda _pid: _selection_fixture_metadata(record, creation="new-identity"),
    )

    with pytest.raises(RuntimeError, match="changed creation identity"):
        _frontend_candidate_tree(record, {}, _canonical_path_identity(record["cwd"]))


def _frontend_current_ancestry(pid, graph, parent_observations):
    ancestry = []
    current = pid
    child_creation = None
    seen = set()
    while current:
        if current in seen:
            raise RuntimeError(f"frontend dependency ownership proof found an ancestry cycle: pid={pid}")
        seen.add(current)
        row = graph.get(current)
        matching = [
            item
            for item in parent_observations
            if isinstance(item, dict) and int(item.get("pid", -1)) == current
        ]
        if row is None:
            if len(matching) == 1 and matching[0].get("state") in {
                "verified_absent_historical_parent",
                "historical_parent_exited_pid_reused",
            }:
                break
            raise RuntimeError(
                f"frontend dependency ownership proof missing current parent: pid={pid} missing={current} "
                f"observations={matching}"
            )
        metadata = _process_metadata(current)
        if current == pid and not matching:
            ancestry.append(metadata)
            child_creation = metadata["creation"]
            current = row["parent_pid"]
            continue
        if len(matching) != 1:
            raise RuntimeError(
                f"frontend dependency parent proof lacks one current observation: pid={pid} parent={current} observations={matching}"
            )
        observation = matching[0]
        if observation.get("state") == "historical_parent_exited_pid_reused":
            required = ("current_creation", "child_creation", "current_parent_pid")
            missing = [field for field in required if field not in observation]
            if missing:
                raise RuntimeError(
                    f"frontend dependency reused-parent proof is incomplete: pid={pid} "
                    f"parent={current} fields={missing}"
                )
            if (
                metadata["creation"] != str(observation.get("current_creation"))
                or str(child_creation) != str(observation.get("child_creation"))
                or metadata["parent_pid"] != int(observation.get("current_parent_pid"))
            ):
                raise RuntimeError(
                    f"frontend dependency reused-parent proof changed current identity: pid={pid} parent={current}"
                )
            if not _creation_token_is_newer(metadata["creation"], child_creation):
                raise RuntimeError(
                    f"frontend dependency reused-parent proof is not newer than traversed child: "
                    f"pid={pid} parent={current} child_creation={child_creation} "
                    f"current_parent_creation={metadata['creation']}"
                )
            break
        if observation.get("state") == "readable_current_parent":
            required = (
                "creation", "parent_pid", "cwd", "executable", "argv",
                "argv_sha256", "native_command_sha256", "relation",
            )
            missing = [field for field in required if field not in observation]
            if missing:
                raise RuntimeError(
                    f"frontend dependency parent proof is incomplete: pid={pid} parent={current} fields={missing}"
                )
            parsed = _windows_command_line_argv(metadata["command"]) if _PLATFORM.name == "nt" else metadata["command"].split()
            if (
                metadata["creation"] != str(observation["creation"])
                or metadata["parent_pid"] != int(observation["parent_pid"])
                or _canonical_path_identity(metadata["cwd"]) != _canonical_path_identity(observation["cwd"])
                or _canonical_path_identity(metadata["executable"]) != _canonical_path_identity(observation["executable"])
                or parsed != [str(item) for item in observation["argv"]]
                or hashlib.sha256("\0".join(parsed).encode("utf-8")).hexdigest() != str(observation["argv_sha256"])
                or hashlib.sha256(metadata["command"].encode("utf-8")).hexdigest() != str(observation["native_command_sha256"])
            ):
                raise RuntimeError(
                    f"frontend dependency parent proof changed full identity or command: pid={pid} parent={current}"
                )
        elif observation.get("state") in {"verified_absent_historical_parent", "unreadable_parent", "reused_parent"}:
            raise RuntimeError(
                f"frontend dependency ancestry proof is not clean: pid={pid} observation={observation}"
            )
        ancestry.append(metadata)
        child_creation = metadata["creation"]
        current = row["parent_pid"]
    return ancestry


def test_frontend_current_ancestry_accepts_verified_absent_parent(monkeypatch):
    monkeypatch.setattr(
        sys.modules[__name__],
        "_process_metadata",
        lambda pid: {
            "pid": pid,
            "parent_pid": 22,
            "creation": "child-token",
            "cwd": str(ROOT / "frontend"),
            "executable": "node.exe",
            "command": "node app.js",
        },
    )
    ancestry = _frontend_current_ancestry(
        11,
        {11: {"pid": 11, "parent_pid": 22}},
        [{"pid": 22, "state": "verified_absent_historical_parent"}],
    )
    assert [item["pid"] for item in ancestry] == [11]


def test_frontend_current_ancestry_rejects_an_older_current_parent_as_reuse(monkeypatch):
    def metadata(pid):
        return {
            "pid": pid,
            "parent_pid": 1,
            "creation": "100" if pid == 11 else "90",
            "cwd": str(ROOT / "frontend"),
            "executable": "node.exe",
            "command": "node app.js",
        }

    monkeypatch.setattr(sys.modules[__name__], "_process_metadata", metadata)
    with pytest.raises(RuntimeError, match="not newer"):
        _frontend_current_ancestry(
            11,
            {11: {"pid": 11, "parent_pid": 22}, 22: {"pid": 22, "parent_pid": 1}},
            [
                {
                    "pid": 22,
                    "state": "historical_parent_exited_pid_reused",
                    "current_creation": "90",
                    "child_creation": "100",
                    "current_parent_pid": 1,
                }
            ],
        )


def test_frontend_current_ancestry_accepts_a_newer_current_parent_as_reuse(monkeypatch):
    def metadata(pid):
        return {
            "pid": pid,
            "parent_pid": 1,
            "creation": "100" if pid == 11 else "110",
            "cwd": str(ROOT / "frontend"),
            "executable": "node.exe",
            "command": "node app.js",
        }

    monkeypatch.setattr(sys.modules[__name__], "_process_metadata", metadata)
    ancestry = _frontend_current_ancestry(
        11,
        {11: {"pid": 11, "parent_pid": 22}, 22: {"pid": 22, "parent_pid": 1}},
        [
            {
                "pid": 22,
                "state": "historical_parent_exited_pid_reused",
                "current_creation": "110",
                "child_creation": "100",
                "current_parent_pid": 1,
            }
        ],
    )
    assert [item["pid"] for item in ancestry] == [11]


def test_frontend_current_ancestry_accepts_equal_readable_parent_identity(monkeypatch):
    metadata_by_pid = {
        11: {
            "pid": 11,
            "parent_pid": 22,
            "creation": "100",
            "cwd": str(ROOT / "frontend"),
            "executable": "node.exe",
            "command": "node app.js",
        },
        22: {
            "pid": 22,
            "parent_pid": 1,
            "creation": "90",
            "cwd": str(ROOT / "frontend"),
            "executable": "cmd.exe",
            "command": "cmd /c node app.js",
        },
    }
    monkeypatch.setattr(sys.modules[__name__], "_process_metadata", metadata_by_pid.__getitem__)
    parent = metadata_by_pid[22]
    parsed = parent["command"].split()
    ancestry = _frontend_current_ancestry(
        11,
        {11: {"pid": 11, "parent_pid": 22}, 22: {"pid": 22, "parent_pid": 1}},
        [
            {
                "pid": 22,
                "state": "readable_current_parent",
                "creation": parent["creation"],
                "parent_pid": parent["parent_pid"],
                "cwd": parent["cwd"],
                "executable": parent["executable"],
                "argv": parsed,
                "argv_sha256": hashlib.sha256("\0".join(parsed).encode()).hexdigest(),
                "native_command_sha256": hashlib.sha256(parent["command"].encode()).hexdigest(),
                "relation": "actual-parent",
            },
            {
                "pid": 1,
                "state": "verified_absent_historical_parent",
            },
        ],
    )
    assert [item["pid"] for item in ancestry] == [11, 22]


def test_frontend_lightweight_unrelated_entries_do_not_require_cwd():
    item = {
        "pid": 50,
        "parent_pid": 1,
        "name": "explorer.exe",
        "executable": r"C:\Windows\explorer.exe",
        "command": "explorer.exe",
    }
    assert _frontend_lightweight_exclusion(item).startswith("measured process type")


def test_frontend_enrichment_selects_relevant_node_and_excludes_protected_cmd(monkeypatch):
    expected = r"C:\work\ufdr-supervisor\frontend"
    graph = {
        11: {
            "pid": 11,
            "name": "node.exe",
            "executable": r"C:\node.exe",
            "command": r"node C:\work\ufdr-supervisor\frontend\app.js",
        },
        12: {
            "pid": 12,
            "name": "cmd.exe",
            "executable": r"C:\Windows\System32\cmd.exe",
            "command": "cmd /c powershell -File gate.ps1",
        },
    }
    native_reads = []
    monkeypatch.setattr(sys.modules[__name__], "_process_metadata", lambda pid: native_reads.append(pid))
    selected = _frontend_enrichment_pids(graph, set(), {12}, expected)
    assert selected == {11}
    assert native_reads == []
    assert _frontend_lightweight_exclusion_for_expected(graph[12], expected).startswith(
        "measured Node/cmd identity"
    )


def test_frontend_enrichment_keeps_unreadable_explicit_identity_loud(monkeypatch):
    graph = {
        11: {
            "pid": 11,
            "name": "node.exe",
            "executable": r"C:\node.exe",
            "command": "node app.js",
        }
    }
    monkeypatch.setattr(
        sys.modules[__name__],
        "_process_metadata",
        lambda pid: {
            "pid": pid,
            "parent_pid": 1,
            "creation": "10",
            "cwd": "",
            "executable": "node.exe",
            "command": "node app.js",
        },
    )
    with pytest.raises(RuntimeError, match="field=cwd"):
        _frontend_enrich_process_graph(graph, _frontend_enrichment_pids(graph, {11}, set(), "C:/frontend"))


def test_frontend_relevant_entries_require_enriched_cwd(monkeypatch):
    graph = {
        11: {
            "pid": 11,
            "parent_pid": 1,
            "name": "node.exe",
            "executable": r"C:\node.exe",
            "command": "node app.js",
        }
    }
    monkeypatch.setattr(
        sys.modules[__name__],
        "_process_metadata",
        lambda pid: {"pid": pid, "parent_pid": 1, "creation": "10", "cwd": "", "executable": "node.exe", "command": "node app.js"},
    )
    with pytest.raises(RuntimeError, match="field=cwd"):
        _frontend_enrich_process_graph(graph, {11})


def test_frontend_process_graph_never_enriches_pid_zero(monkeypatch):
    with pytest.raises(RuntimeError, match="PID 0"):
        _frontend_enrich_process_graph({0: {"pid": 0}}, {0})


def test_frontend_current_ancestry_rejects_a_real_cycle(monkeypatch):
    monkeypatch.setattr(
        sys.modules[__name__],
        "_process_metadata",
        lambda pid: {
            "pid": pid,
            "parent_pid": 11 if pid == 22 else 22,
            "creation": f"token-{pid}",
            "cwd": str(ROOT / "frontend"),
            "executable": "node.exe",
            "command": "node app.js",
        },
    )
    with pytest.raises(RuntimeError, match="ancestry cycle"):
        _frontend_current_ancestry(
            11,
            {
                11: {"pid": 11, "parent_pid": 22},
                22: {"pid": 22, "parent_pid": 11},
            },
            [
                {
                    "pid": 11,
                    "state": "readable_current_parent",
                    "creation": "token-11",
                    "parent_pid": 22,
                    "cwd": str(ROOT / "frontend"),
                    "executable": "node.exe",
                    "argv": ["node", "app.js"],
                    "argv_sha256": hashlib.sha256(b"node\0app.js").hexdigest(),
                    "native_command_sha256": hashlib.sha256(b"node app.js").hexdigest(),
                    "relation": "cycle",
                },
                {
                    "pid": 22,
                    "state": "readable_current_parent",
                    "creation": "token-22",
                    "parent_pid": 11,
                    "cwd": str(ROOT / "frontend"),
                    "executable": "node.exe",
                    "argv": ["node", "app.js"],
                    "argv_sha256": hashlib.sha256(b"node\0app.js").hexdigest(),
                    "native_command_sha256": hashlib.sha256(b"node app.js").hexdigest(),
                    "relation": "cycle",
                },
            ],
        )


def _frontend_loaded_modules(pid):
    if _PLATFORM.name != "nt":
        maps = Path("/proc") / str(pid) / "maps"
        try:
            return [line.rsplit(maxsplit=1)[-1] for line in maps.read_text(encoding="utf-8").splitlines() if "/" in line]
        except (FileNotFoundError, OSError) as exc:
            raise RuntimeError(f"frontend dependency module proof failed: pid={pid}: {exc}") from exc
    command = f"(Get-Process -Id {pid} -Module -ErrorAction Stop).FileName | ConvertTo-Json -Compress"
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"frontend dependency module proof failed: pid={pid} rc={result.returncode} "
            f"stdout={result.stdout[-2000:]} stderr={result.stderr[-2000:]}"
        )
    raw = json.loads(result.stdout) if result.stdout.strip() else []
    return raw if isinstance(raw, list) else [raw]


def _frontend_candidate_tree(candidate, graph, expected_cwd):
    current_record = candidate
    current = _process_metadata(candidate["pid"])
    if current["creation"] != str(current_record["creation"]):
        raise RuntimeError(f"frontend dependency ownership proof changed creation identity: pid={candidate['pid']}")
    if current["parent_pid"] != int(current_record["parent_pid"]):
        raise RuntimeError(f"frontend dependency ownership proof changed parent: pid={candidate['pid']}")
    if not current["executable"] or _canonical_path_identity(current["executable"]) != _canonical_path_identity(current_record["executable"]):
        raise RuntimeError(f"frontend dependency ownership proof changed executable: pid={candidate['pid']}")
    if not current["command"] or hashlib.sha256(current["command"].encode("utf-8")).hexdigest() != str(current_record["native_command_sha256"]):
        raise RuntimeError(f"frontend dependency ownership proof changed native command hash: pid={candidate['pid']}")
    if _canonical_path_identity(current["cwd"]) != _canonical_path_identity(current_record["cwd"]):
        raise RuntimeError(f"frontend dependency ownership proof changed cwd: pid={candidate['pid']}")
    if _canonical_path_identity(current["cwd"]) != expected_cwd:
        raise RuntimeError(f"frontend dependency ownership proof is outside frontend worktree: pid={candidate['pid']}")
    current_argv = (
        _windows_command_line_argv(current["command"])
        if _PLATFORM.name == "nt"
        else current["command"].split()
    )
    if current_argv != [str(item) for item in current_record["argv"]]:
        raise RuntimeError(
            f"frontend dependency ownership proof changed structured argv: pid={candidate['pid']}"
        )
    argv_hash = hashlib.sha256("\0".join(current_argv).encode("utf-8")).hexdigest()
    if argv_hash != str(current_record["argv_sha256"]):
        raise RuntimeError(f"frontend dependency ownership proof changed parsed argv hash: pid={candidate['pid']}")
    if candidate["role"] == "related_test_family":
        if current_record["script_paths"]:
            raise RuntimeError(f"frontend dependency related role has an invented script path: pid={candidate['pid']}")
        if current_record.get("argv_role") != current_argv:
            raise RuntimeError(f"frontend dependency related role argv relation changed: pid={candidate['pid']}")
        if not current_record.get("family_relation"):
            raise RuntimeError(f"frontend dependency related role lacks family relation: pid={candidate['pid']}")
    elif not any(str(path) in current_argv for path in current_record["script_paths"]):
        raise RuntimeError(f"frontend dependency ownership proof missing current script role: pid={candidate['pid']}")
    ancestry = _frontend_current_ancestry(
        candidate["pid"], graph, current_record["parent_observations"]
    )
    historical_ancestry = [int(item) if isinstance(item, int) else int(item["pid"]) for item in candidate.get("ancestry", [])]
    if [item["pid"] for item in ancestry[: len(historical_ancestry)]] != historical_ancestry:
        raise RuntimeError(f"frontend dependency ownership proof changed ancestry: pid={candidate['pid']}")
    if candidate["role"] == "lightningcss_loader":
        loaded_modules = _frontend_loaded_modules(candidate["pid"])
        native_path = (ROOT / _NATIVE_MODULE_RELATIVE).resolve()
        if not any(_canonical_path_identity(item) == _canonical_path_identity(native_path) for item in loaded_modules):
            raise RuntimeError(f"frontend dependency ownership proof missing current lightningcss module: pid={candidate['pid']}")
        if not any(_canonical_path_identity(item) == _canonical_path_identity(native_path) for item in current_record["current_modules"]):
            raise RuntimeError(f"frontend dependency evidence missing current lightningcss role: pid={candidate['pid']}")
    tree = _current_process_tree(candidate["pid"])
    if not tree or tree[0]["pid"] != candidate["pid"]:
        raise RuntimeError(f"frontend dependency ownership proof missing selected root: pid={candidate['pid']}")
    return tree


def _refresh_owned_process_tree(process):
    """Capture the exact live descendant set at a lifecycle synchronization point."""
    owner = getattr(process, "_citespan_owner", None)
    if owner is None:
        raise RuntimeError("process ownership refresh denied: missing launch ownership record")
    if not isinstance(owner.get("owner_marker"), str) or not owner["owner_marker"]:
        raise RuntimeError("process ownership refresh denied: launch ownership marker is incomplete")
    tree = _assert_owned_process_tree(process)
    captured = owner.get("descendant_identities")
    if not isinstance(captured, dict):
        raise RuntimeError("process ownership refresh denied: recorded ownership map is incomplete")
    candidate_identities = {}
    by_pid = {item["pid"]: item for item in tree}
    for item in tree:
        identity = dict(item)
        identity["launch_marker"] = owner["owner_marker"]
        parent_pid = item["parent_pid"]
        if item["pid"] != process.pid:
            parent = by_pid.get(parent_pid)
            if parent is None:
                raise RuntimeError(
                    "process ownership refresh denied: descendant parent is not in the validated census; "
                    f"pid={item['pid']} parent_pid={parent_pid}"
                )
            identity["parent_creation"] = parent["creation"]
        previous = captured.get(item["pid"])
        if previous is not None:
            _assert_complete_process_identity(previous, f"recorded identity pid={item['pid']}")
            _assert_process_identity_matches(
                previous,
                item,
                f"process ownership refresh denied: recorded identity changed for pid={item['pid']}",
            )
        candidate_identities[item["pid"]] = identity
    if process.pid not in candidate_identities:
        raise RuntimeError(f"process ownership refresh failed: root pid {process.pid} was not captured")
    captured.update(candidate_identities)
    return tuple(captured.values())


def _frontend_additional_tree(record, graph, expected_cwd):
    current = _process_metadata(record["pid"])
    if current["creation"] != str(record["creation"]):
        raise RuntimeError(f"frontend dependency ownership proof changed additional identity: pid={record['pid']}")
    if current["parent_pid"] != int(record["parent_pid"]):
        raise RuntimeError(f"frontend dependency ownership proof changed additional parent: pid={record['pid']}")
    if _canonical_path_identity(current["cwd"]) != _canonical_path_identity(record["cwd"]):
        raise RuntimeError(f"frontend dependency ownership proof changed additional cwd: pid={record['pid']}")
    if _canonical_path_identity(current["cwd"]) != expected_cwd:
        raise RuntimeError(f"frontend dependency additional identity is outside frontend worktree: pid={record['pid']}")
    if _canonical_path_identity(current["executable"]) != _canonical_path_identity(record["executable"]):
        raise RuntimeError(f"frontend dependency ownership proof changed additional executable: pid={record['pid']}")
    parsed = _windows_command_line_argv(current["command"]) if _PLATFORM.name == "nt" else current["command"].split()
    if parsed != [str(item) for item in record["argv"]]:
        raise RuntimeError(f"frontend dependency ownership proof changed additional argv: pid={record['pid']}")
    if hashlib.sha256("\0".join(parsed).encode("utf-8")).hexdigest() != str(record["argv_sha256"]):
        raise RuntimeError(f"frontend dependency ownership proof changed additional argv hash: pid={record['pid']}")
    if hashlib.sha256(current["command"].encode("utf-8")).hexdigest() != str(record["native_command_sha256"]):
        raise RuntimeError(f"frontend dependency ownership proof changed additional command hash: pid={record['pid']}")
    _frontend_current_ancestry(record["pid"], graph, record["parent_observations"])
    tree = _current_process_tree(record["pid"])
    if not tree or tree[0]["pid"] != record["pid"]:
        raise RuntimeError(f"frontend dependency ownership proof missing selected additional root: pid={record['pid']}")
    return tree


def _assert_recorded_process_identities_stopped(
    recorded, label, *, allow_pid_reuse_after_stop=frozenset()
):
    if isinstance(recorded, dict):
        expected = recorded.items()
    else:
        expected = ((item["pid"], item["creation"]) for item in recorded)
    terminal_states = []
    for pid, creation in expected:
        try:
            current = _process_metadata(pid)
        except ProcessIdentityAbsent:
            terminal_states.append({"pid": pid, "state": "verified_absent", "creation": creation})
            continue
        except ProcessIdentityReadError as exc:
            raise RuntimeError(f"{label} cannot prove stopped identity: pid={pid} error={exc}") from exc
        if current["creation"] == creation:
            raise RuntimeError(f"{label} retained an active recorded identity: pid={pid} creation={creation}")
        if pid not in allow_pid_reuse_after_stop:
            raise RuntimeError(
                f"{label} found PID reuse before stop: pid={pid} recorded_creation={creation} current={current}"
            )
        terminal_states.append(
            {
                "pid": pid,
                "state": "pid_reused_after_exit",
                "creation": creation,
                "current_creation": current["creation"],
                "current_identity": {
                    field: current.get(field)
                    for field in ("pid", "creation", "executable", "command", "cwd", "parent_pid")
                },
            }
        )
    return terminal_states


def _native_resource_error(path, label, error):
    return RuntimeError(f"{label} native resource proof failed: path={path} error={error}")


def _assert_native_resource_released(path, label):
    path = Path(path)
    try:
        initial = os.lstat(path)
    except FileNotFoundError as exc:
        if exc.errno != errno.ENOENT:
            raise _native_resource_error(path, label, exc) from exc
        return {"state": "absent", "path": str(path), "error": "FileNotFoundError/ENOENT"}
    except OSError as exc:
        raise _native_resource_error(path, label, exc) from exc
    if stat.S_ISLNK(initial.st_mode):
        raise _native_resource_error(path, label, "resource is a symbolic link")
    if not stat.S_ISREG(initial.st_mode):
        raise _native_resource_error(path, label, "resource is not a regular file")
    replacement = path.with_name(path.name + ".citespan-release-proof")
    if replacement.exists() or replacement.is_symlink():
        raise _native_resource_error(path, label, f"replacement path already exists: {replacement}")
    try:
        initial_fingerprint = release._native_fingerprint(path, initial)
        original = path.read_bytes()
        original_digest = hashlib.sha256(original).hexdigest()
        before_replace = os.lstat(path)
        before_fingerprint = release._native_fingerprint(path, before_replace)
        before_bytes = path.read_bytes()
        before_digest = hashlib.sha256(before_bytes).hexdigest()
        if before_fingerprint != initial_fingerprint:
            raise RuntimeError("native resource changed before replace")
        if before_bytes != original or before_digest != original_digest:
            raise RuntimeError("native resource content changed before replace")
    except (OSError, RuntimeError) as exc:
        raise _native_resource_error(path, label, exc) from exc
    try:
        os.replace(path, replacement)
    except OSError as exc:
        raise _native_resource_error(path, label, f"replacement operation failed: {exc}") from exc

    try:
        if not replacement.is_file() or replacement.read_bytes() != original:
            raise RuntimeError("replacement bytes or path differ")
    except (OSError, RuntimeError) as exc:
        try:
            os.replace(replacement, path)
        except OSError as restore_error:
            raise _native_resource_error(
                path,
                label,
                f"validation after replacement failed: {exc}; restoration operation failed: {restore_error}",
            ) from exc
        raise _native_resource_error(path, label, f"validation after replacement failed: {exc}") from exc

    try:
        os.replace(replacement, path)
    except OSError as exc:
        raise _native_resource_error(path, label, f"restoration operation failed: {exc}") from exc

    try:
        restored = os.lstat(path)
        restored_fingerprint = release._native_fingerprint(path, restored)
        restored_bytes = path.read_bytes()
        restored_digest = hashlib.sha256(restored_bytes).hexdigest()
        if (
            not stat.S_ISREG(restored.st_mode)
            or restored_fingerprint != initial_fingerprint
            or restored_bytes != original
            or restored_digest != original_digest
        ):
            raise RuntimeError("restored byte, path, or stable metadata mismatch")
    except (OSError, RuntimeError) as exc:
        raise _native_resource_error(path, label, f"restored byte/path mismatch: {exc}") from exc
    return {"state": "restored", "path": str(path), "bytes": len(original)}


def _assert_frontend_files_released(candidates, evidence_root):
    for candidate in candidates:
        files = candidate.get("files")
        ports = candidate.get("ports")
        if not isinstance(files, list):
            raise RuntimeError(
                f"frontend dependency evidence missing released-file facts: pid={candidate['pid']} field=files"
            )
        if not isinstance(ports, list):
            raise RuntimeError(
                f"frontend dependency evidence missing released-port facts: pid={candidate['pid']} field=ports"
            )
        for value in files:
            path = Path(value)
            if not path.is_absolute() and path.as_posix() == _NATIVE_MODULE_RELATIVE.as_posix():
                path = ROOT / path
            else:
                path = path if path.is_absolute() else evidence_root / path
            path = path.absolute()
            native_path = (ROOT / _NATIVE_MODULE_RELATIVE).absolute()
            if path == ROOT or ROOT in path.parents:
                if path != native_path:
                    raise RuntimeError(f"frontend dependency release proof path is not the exact native module: pid={candidate['pid']} path={path}")
            if not path.exists() and path != native_path:
                continue
            if path == native_path:
                _assert_native_resource_released(
                    path,
                    f"frontend dependency release proof pid={candidate.get('pid', 'none')}",
                )
            else:
                try:
                    handle = os.open(path, os.O_RDONLY)
                except OSError as exc:
                    raise RuntimeError(
                        f"frontend dependency release proof cannot open file: "
                        f"pid={candidate.get('pid', 'none')} path={path} error={exc}"
                    ) from exc
                else:
                    os.close(handle)


def _assert_cleanup_postcondition_already_satisfied(evidence_root):
    presence, frontend = _load_current_cleanup_observations(evidence_root)
    live = [pid for pid, record in presence.items() if record["state"] in {"live", "present"}]
    if live:
        raise RuntimeError(
            "frontend dependency cleanup postcondition is not satisfied: "
            f"exact historical identities remain live={live}"
        )
    if frontend["processes"]:
        raise RuntimeError(
            "frontend dependency cleanup postcondition is not satisfied: "
            f"relevant product processes remain={frontend['processes']}"
        )
    if frontend["holders"]:
        raise RuntimeError(
            "frontend dependency cleanup postcondition is not satisfied: "
            f"native module holders remain={frontend['holders']}"
        )
    if frontend["ports"]:
        raise RuntimeError(
            "frontend dependency cleanup postcondition is not satisfied: "
            f"measured ports remain={frontend['ports']}"
        )
    native_resource = _assert_native_resource_released(
        ROOT / _NATIVE_MODULE_RELATIVE,
        "frontend dependency cleanup postcondition",
    )
    return {
        "historical_processes": "absent_or_reused",
        "current_frontend": "released",
        "native_resource": native_resource,
    }


def _write_browser_dependency_fixture(frontend_root):
    dependencies = {"next": "15.5.27", "react": "19.1.0", "react-dom": "19.1.0"}
    dev_dependencies = {"@playwright/test": "1.62.1"}
    versions = {**dependencies, **dev_dependencies}
    package = {"dependencies": dependencies, "devDependencies": dev_dependencies}
    lock_packages = {
        "": {"dependencies": dependencies, "devDependencies": dev_dependencies}
    }
    for name, version in versions.items():
        lock_packages[f"node_modules/{name}"] = {"version": version}
        installed_path = frontend_root / "node_modules" / Path(name) / "package.json"
        installed_path.parent.mkdir(parents=True, exist_ok=True)
        installed_path.write_text(json.dumps({"name": name, "version": version}), encoding="utf-8")
    (frontend_root / "package.json").write_text(json.dumps(package), encoding="utf-8")
    (frontend_root / "package-lock.json").write_text(
        json.dumps({"lockfileVersion": 3, "packages": lock_packages}), encoding="utf-8"
    )
    next_bin = frontend_root / "node_modules" / ".bin" / ("next.cmd" if _PLATFORM.name == "nt" else "next")
    next_bin.parent.mkdir(parents=True, exist_ok=True)
    next_bin.write_text("next", encoding="utf-8")


def test_frontend_dependency_readiness_rejects_missing_project_next_executable(tmp_path):
    frontend_root = tmp_path / "frontend"
    _write_browser_dependency_fixture(frontend_root)
    next_bin = frontend_root / "node_modules" / ".bin" / ("next.cmd" if _PLATFORM.name == "nt" else "next")
    next_bin.unlink()

    findings = release._browser_dependency_findings(frontend_root)

    assert any("project-scoped Next executable is missing" in finding for finding in findings)


def test_frontend_dependency_readiness_rejects_stale_or_incomplete_locked_state(tmp_path):
    frontend_root = tmp_path / "frontend"
    _write_browser_dependency_fixture(frontend_root)
    (frontend_root / "node_modules" / "next" / "package.json").write_text(
        json.dumps({"name": "next", "version": "15.5.26"}), encoding="utf-8"
    )
    (frontend_root / "node_modules" / "@playwright" / "test" / "package.json").unlink()

    findings = release._browser_dependency_findings(frontend_root)

    assert any("next installed version does not match" in finding for finding in findings)
    assert any("@playwright/test installed package metadata is missing" in finding for finding in findings)


def test_frontend_dependency_readiness_does_not_install_or_mutate(tmp_path, monkeypatch):
    frontend_root = (tmp_path / "frontend").resolve()
    _write_browser_dependency_fixture(frontend_root)
    next_executable = frontend_root / "node_modules" / ".bin" / (
        "next.cmd" if _PLATFORM.name == "nt" else "next"
    )
    next_executable.unlink()
    calls = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: calls.append((args, kwargs)) or Result(),
    )

    before = (frontend_root / "package.json").read_bytes()
    findings = release._browser_dependency_findings(frontend_root)

    assert findings
    assert calls == []
    assert (frontend_root / "package.json").read_bytes() == before


def test_frontend_dependency_preparation_fails_before_browser_launch_when_install_is_incomplete(
    tmp_path, monkeypatch
):
    frontend_root = tmp_path / "frontend"
    _write_browser_dependency_fixture(frontend_root)
    monkeypatch.setattr(
        release,
        "_validate_host_process_evidence",
        lambda: {"native_resource": "present"},
    )
    (frontend_root / "node_modules" / ".bin" / ("next.cmd" if _PLATFORM.name == "nt" else "next")).unlink()

    with pytest.raises(RuntimeError, match="browser dependency readiness failed"):
        release._validate_browser_dependency_readiness(frontend_root)


_BROWSER_FRONTEND_REQUIRED_PACKAGES = ("next", "react", "react-dom", "@playwright/test")


def _ensure_frontend_dependencies_for_browser():
    return release._validate_browser_dependency_readiness(
        ROOT / "frontend", process={"state": "contract_fixture"}
    )


def test_browser_fixture_uses_completed_dependencies_without_running_an_installer(monkeypatch):
    calls = []
    monkeypatch.setattr(
        release,
        "_validate_browser_dependency_readiness",
        lambda frontend_root, *, process: calls.append((frontend_root, process))
        or {"dependency_findings": []},
    )
    monkeypatch.setattr(
        release,
        "_prepare_host",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("browser fixture must not prepare or install dependencies")
        ),
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("browser fixture must not invoke a subprocess installer")
        ),
    )

    result = _ensure_frontend_dependencies_for_browser()

    assert result == {"dependency_findings": []}
    assert calls == [(ROOT / "frontend", {"state": "contract_fixture"})]


def test_upload_validation_real_browser_is_fail_closed_and_file_scoped():
    class DelayedApi(BaseHTTPRequestHandler):
        state = None
        allowed_methods = "GET, POST, OPTIONS"
        allowed_headers = "Authorization, Content-Type"

        def log_message(self, format, *args):
            return

        def _cors_headers(self):
            return {
                "Access-Control-Allow-Origin": self.state["frontend_origin"],
                "Access-Control-Allow-Methods": self.allowed_methods,
                "Access-Control-Allow-Headers": self.allowed_headers,
                "Access-Control-Max-Age": "0",
                "Vary": "Origin",
            }

        def _json(self, status, payload, logical_path=None):
            body = json.dumps(payload).encode("utf-8")
            headers = self._cors_headers()
            self.state["api_responses"].append(
                {
                    "method": self.command,
                    "path": urlsplit(self.path).path,
                    "logical_path": logical_path,
                    "status": status,
                    "headers": headers,
                }
            )
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            parsed = urlsplit(self.path)
            if parsed.path not in {"/ingest/validate-path", "/ingest/"}:
                self._json(404, {"error": "not found"})
                return
            self.state["options_requests"].append(
                {
                    "path": parsed.path,
                    "origin": self.headers.get("Origin"),
                    "requested_method": self.headers.get("Access-Control-Request-Method"),
                    "requested_headers": self.headers.get("Access-Control-Request-Headers"),
                }
            )
            self.state["api_events"].append(("OPTIONS", parsed.path))
            self._json(204, {})

        def do_GET(self):
            parsed = urlsplit(self.path)
            if parsed.path != "/ingest/validate-path":
                self._json(404, {"error": "not found"})
                return
            path = parse_qs(parsed.query).get("file_path", [""])[0]
            self.state["validation_requests"].append(path)
            self.state["api_events"].append(("GET", path))
            if path == "/network-error":
                self.close_connection = True
                self.connection.close()
                return
            if path == "/stale-old":
                self.state["stale_started"].set()
                if not self.state["stale_release"].wait(timeout=10):
                    self._json(500, {"error": "stale response was not released"}, logical_path=path)
                    return
            if path == "/http-failure" or (path == "/retry" and self.state["retry_count"] == 0):
                if path == "/retry":
                    self.state["retry_count"] += 1
                self._json(503, {"error": "validation service failed"}, logical_path=path)
                return
            if path == "/retry":
                self.state["retry_count"] += 1
            responses = {
                "/malformed-size": {"valid": True, "file_path": path, "file_size_gb": "1", "readable": True},
                "/malformed-readable": {"valid": True, "file_path": path, "file_size_gb": 1, "readable": False},
                "/pending": {"valid": True, "file_path": path},
            }
            self._json(
                200,
                responses.get(
                    path,
                    {"valid": True, "file_path": path, "file_size_gb": 1, "readable": True},
                ),
                logical_path=path,
            )

        def do_POST(self):
            parsed = urlsplit(self.path)
            if parsed.path != "/ingest/":
                self._json(404, {"error": "not found"})
                return
            self.state["ingest_requests"] += 1
            self._json(
                200,
                {
                    "status": "success",
                    "filename": "synthetic.ufdr",
                    "file_path": "/retry",
                    "processing_time": "0 seconds",
                },
            )

    state = {
        "validation_requests": [],
        "options_requests": [],
        "api_events": [],
        "api_responses": [],
        "browser_requests": [],
        "browser_responses": [],
        "browser_request_failures": [],
        "browser_errors": [],
        "callback_errors": [],
        "ingest_requests": 0,
        "retry_count": 0,
        "stale_started": threading.Event(),
        "stale_release": threading.Event(),
    }
    DelayedApi.state = state
    api_server = ThreadingHTTPServer(("127.0.0.1", 0), DelayedApi)
    api_thread = threading.Thread(target=api_server.serve_forever, daemon=True)
    api_thread.start()
    frontend_port = _unused_tcp_port()
    state["frontend_origin"] = f"http://127.0.0.1:{frontend_port}"
    frontend_env = os.environ.copy()
    frontend_env.update(
        {
            "NEXT_PUBLIC_API_URL": f"http://127.0.0.1:{api_server.server_port}",
            "NEXT_PUBLIC_DEMO_MODE": "0",
            "NEXT_TELEMETRY_DISABLED": "1",
        }
    )
    frontend = None
    playwright = None
    browser = None
    context = None
    page = None
    handle_dialog = None
    primary_error = None
    try:
        npm = shutil.which("npm.cmd") or shutil.which("npm")
        if not npm:
            raise RuntimeError("focused browser check requires npm")
        _ensure_frontend_dependencies_for_browser()
        frontend = _launch_process_tree(
            [npm, "run", "dev", "--", "--hostname", "127.0.0.1", "--port", str(frontend_port)],
            cwd=ROOT / "frontend",
            env=frontend_env,
        )
        _wait_for_http(f"http://127.0.0.1:{frontend_port}/upload", frontend)
        executable = _installed_browser_executable()
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("focused browser check requires Python Playwright") from exc

        playwright = sync_playwright().start()
        try:
            browser = playwright.chromium.launch(headless=True, executable_path=executable)
            context = browser.new_context()
            context.add_init_script("window.localStorage.setItem('ufdr.access_token', 'synthetic-test-token')")
            page = context.new_page()
            page.on(
                "request",
                lambda request: state["browser_requests"].append(
                    {"method": request.method, "url": request.url}
                ),
            )
            page.on(
                "response",
                lambda response: state["browser_responses"].append(
                    {
                        "method": response.request.method,
                        "url": response.url,
                        "status": response.status,
                        "headers": response.headers,
                    }
                ),
            )
            page.on(
                "requestfailed",
                lambda request: state["browser_request_failures"].append(
                    {"method": request.method, "url": request.url, "failure": request.failure}
                ),
            )
            page.on("console", lambda message: state["browser_errors"].append(f"console:{message.type}:{message.text}"))
            page.on("pageerror", lambda error: state["browser_errors"].append(f"pageerror:{error}"))

            def handle_dialog(dialog):
                try:
                    dialog.accept()
                except BaseException as exc:
                    state["callback_errors"].append(f"dialog callback failed: {exc!r}")
                    raise

            page.on("dialog", handle_dialog)

            page.goto(f"http://127.0.0.1:{frontend_port}/upload", wait_until="networkidle")
            page.wait_for_timeout(3000)
            page.get_by_text("Process UFDR File", exact=True).wait_for(state="visible")
            file_path = page.locator('input[placeholder="/data/ufdr/case-001.ufdr"]')
            start_analysis = page.get_by_role("button", name="Start Analysis")

            def validation_cursors(path):
                return {
                    "validation_requests": len(state["validation_requests"]),
                    "options_requests": len(state["options_requests"]),
                    "api_events": len(state["api_events"]),
                    "api_responses": len(state["api_responses"]),
                    "browser_requests": len(state["browser_requests"]),
                    "browser_responses": len(state["browser_responses"]),
                    "browser_request_failures": len(state["browser_request_failures"]),
                    "path_occurrences": {
                        "validation_requests": sum(item == path for item in state["validation_requests"]),
                        "api_events": sum(item == ("GET", path) for item in state["api_events"]),
                        "api_responses": sum(
                            item.get("logical_path") == path for item in state["api_responses"]
                        ),
                        "browser_requests": sum(
                            item["method"] == "GET"
                            and parse_qs(urlsplit(item["url"]).query).get("file_path") == [path]
                            for item in state["browser_requests"]
                        ),
                        "browser_responses": sum(
                            item["method"] == "GET"
                            and urlsplit(item["url"]).path == "/ingest/validate-path"
                            and parse_qs(urlsplit(item["url"]).query).get("file_path") == [path]
                            for item in state["browser_responses"]
                        ),
                        "browser_request_failures": sum(
                            item["method"] == "GET"
                            and parse_qs(urlsplit(item["url"]).query).get("file_path") == [path]
                            for item in state["browser_request_failures"]
                        ),
                    },
                }

            def wait_for_validation(path, cursors):
                generation = cursors["path_occurrences"]["validation_requests"] + 1

                def diagnostic():
                    return _validation_evidence_diagnostic(path, generation, cursors, state)

                def browser_path(item):
                    return (
                        item["method"] == "GET"
                        and urlsplit(item["url"]).path == "/ingest/validate-path"
                        and parse_qs(urlsplit(item["url"]).query).get("file_path") == [path]
                    )

                browser_request_index = None
                options_event_index = None
                get_event_index = None
                preflight_response_index = None
                api_response_index = None
                browser_response_index = None
                browser_failure_index = None
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    browser_requests = [
                        (index, item)
                        for index, item in enumerate(state["browser_requests"])
                        if index >= cursors["browser_requests"] and browser_path(item)
                    ]
                    if browser_requests:
                        browser_request_index = browser_requests[0][0]
                    options = [
                        (index, item)
                        for index, item in enumerate(state["api_events"])
                        if index >= cursors["api_events"] and item == ("OPTIONS", "/ingest/validate-path")
                    ]
                    if options:
                        options_event_index = options[0][0]
                    gets = [
                        (index, item)
                        for index, item in enumerate(state["api_events"])
                        if index >= cursors["api_events"] and item == ("GET", path)
                    ]
                    if gets:
                        get_event_index = gets[0][0]
                    preflight_responses = [
                        (index, item)
                        for index, item in enumerate(state["api_responses"])
                        if index >= cursors["api_responses"]
                        and item["method"] == "OPTIONS"
                        and item["path"] == "/ingest/validate-path"
                    ]
                    if preflight_responses:
                        preflight_response_index = preflight_responses[0][0]
                    api_responses = [
                        (index, item)
                        for index, item in enumerate(state["api_responses"])
                        if index >= cursors["api_responses"]
                        and item["method"] == "GET"
                        and item.get("logical_path") == path
                    ]
                    if api_responses:
                        api_response_index = api_responses[0][0]
                    browser_responses = [
                        (index, item)
                        for index, item in enumerate(state["browser_responses"])
                        if index >= cursors["browser_responses"] and browser_path(item)
                    ]
                    if browser_responses:
                        browser_response_index = browser_responses[0][0]
                    failures = [
                        (index, item)
                        for index, item in enumerate(state["browser_request_failures"])
                        if index >= cursors["browser_request_failures"] and browser_path(item)
                    ]
                    if failures:
                        browser_failure_index = failures[0][0]

                    server_receipt_ready = (
                        browser_request_index is not None
                        and options_event_index is not None
                        and get_event_index is not None
                        and options_event_index < get_event_index
                        and preflight_response_index is not None
                    )
                    terminal_ready = (
                        path == "/network-error"
                        and browser_failure_index is not None
                        or path == "/stale-old"
                        and state["stale_started"].is_set()
                        or path != "/network-error"
                        and path != "/stale-old"
                        and browser_response_index is not None
                        and api_response_index is not None
                    )
                    if server_receipt_ready and terminal_ready:
                        break
                    page.wait_for_timeout(100)
                assert browser_request_index is not None, diagnostic()
                assert options_event_index is not None, diagnostic()
                assert get_event_index is not None, diagnostic()
                assert options_event_index < get_event_index, diagnostic()
                assert preflight_response_index is not None, diagnostic()
                options = [
                    item
                    for index, item in enumerate(state["options_requests"])
                    if index >= cursors["options_requests"] and item["path"] == "/ingest/validate-path"
                ]
                assert options, diagnostic()
                assert options[0]["origin"] == state["frontend_origin"]
                assert options[0]["requested_method"] == "GET"
                assert options[0]["requested_headers"].lower() == "authorization"
                preflight = state["api_responses"][preflight_response_index]
                assert preflight["status"] == 204
                assert preflight["headers"]["Access-Control-Allow-Origin"] == state["frontend_origin"]
                assert preflight["headers"]["Access-Control-Allow-Methods"] == "GET, POST, OPTIONS"
                assert preflight["headers"]["Access-Control-Allow-Headers"] == "Authorization, Content-Type"
                _assert_cors_max_age_zero(preflight["headers"])
                assert preflight["headers"]["Vary"] == "Origin"
                responses = [
                    item
                    for index, item in enumerate(state["browser_responses"])
                    if index >= cursors["browser_responses"] and browser_path(item)
                ]
                assert responses or path in {"/network-error", "/stale-old"}, diagnostic()
                for response in responses:
                    assert response["headers"]["access-control-allow-origin"] == state["frontend_origin"]
                    _assert_cors_max_age_zero(response["headers"], "access-control-max-age")
                    assert response["headers"]["vary"] == "Origin"

                if path == "/network-error":
                    assert browser_failure_index is not None, diagnostic()
                elif path == "/stale-old":
                    assert state["stale_started"].is_set(), diagnostic()
                else:
                    assert browser_response_index is not None, diagnostic()
                    assert api_response_index is not None, diagnostic()

            def trigger_validation(path):
                cursors = validation_cursors(path)
                file_path.fill(path)
                file_path.press("Tab")
                wait_for_validation(path, cursors)

            for invalid_path in ("/network-error", "/http-failure", "/malformed-size", "/malformed-readable", "/pending"):
                trigger_validation(invalid_path)
                page.wait_for_timeout(1500)
                page.get_by_text("File validation failed", exact=True).wait_for(state="visible")
                assert start_analysis.is_disabled(), invalid_path
                assert state["ingest_requests"] == 0, invalid_path

            assert any(
                parse_qs(urlsplit(item["url"]).query).get("file_path") == ["/network-error"]
                for item in state["browser_request_failures"]
            )

            stale_old_cursors = validation_cursors("/stale-old")
            file_path.fill("/stale-old")
            file_path.press("Tab")
            stale_deadline = time.monotonic() + 15
            while not state["stale_started"].is_set() and time.monotonic() < stale_deadline:
                page.wait_for_timeout(100)
            assert state["stale_started"].is_set(), {
                "input_value": file_path.input_value(),
                "validation_requests": state["validation_requests"],
                "browser_requests": state["browser_requests"][-5:],
                "errors": state["browser_errors"],
            }
            wait_for_validation("/stale-old", stale_old_cursors)
            trigger_validation("/stale-new")
            page.get_by_text("Path: /stale-new", exact=True).wait_for(state="visible")
            state["stale_release"].set()
            late_response_deadline = time.monotonic() + 10
            while time.monotonic() < late_response_deadline:
                if any(
                    item.get("logical_path") == "/stale-old"
                    for item in state["api_responses"]
                ):
                    break
                page.wait_for_timeout(100)
            late_response_index = _checked_event_index(
                state["api_responses"],
                lambda item: item.get("logical_path") == "/stale-old",
                stale_old_cursors["api_responses"],
                "late stale-old response",
                lambda: _validation_evidence_diagnostic("/stale-old", 1, stale_old_cursors, state),
            )
            assert state["api_responses"][late_response_index]["status"] == 200
            assert page.get_by_text("Path: /stale-new", exact=True).is_visible()
            assert state["ingest_requests"] == 0

            trigger_validation("/retry")
            page.get_by_text("File validation failed", exact=True).wait_for(state="visible")
            assert start_analysis.is_disabled()
            retry_cursors = validation_cursors("/retry")
            page.get_by_role("button", name="Retry validation").click()
            wait_for_validation("/retry", retry_cursors)
            page.get_by_text("Path: /retry", exact=True).wait_for(state="visible")
            start_analysis.click()
            page.get_by_text("Analysis Complete", exact=True).wait_for(state="visible")
            assert state["ingest_requests"] == 1
            assert any(item["path"] == "/ingest/" for item in state["options_requests"])
            assert any(item["method"] == "POST" and item["url"].endswith("/ingest/") for item in state["browser_requests"])
            ingest_responses = [
                item
                for item in state["browser_responses"]
                if item["method"] == "POST" and urlsplit(item["url"]).path == "/ingest/"
            ]
            assert ingest_responses
            assert ingest_responses[-1]["headers"]["access-control-allow-origin"] == state["frontend_origin"]
            _assert_cors_max_age_zero(ingest_responses[-1]["headers"], "access-control-max-age")
            assert ingest_responses[-1]["headers"]["vary"] == "Origin"
            assert all(
                response["headers"]["Access-Control-Allow-Origin"] == state["frontend_origin"]
                and response["headers"]["Access-Control-Allow-Methods"] == "GET, POST, OPTIONS"
                and response["headers"]["Access-Control-Allow-Headers"] == "Authorization, Content-Type"
                and response["headers"].get("Access-Control-Max-Age") == "0"
                and response["headers"]["Vary"] == "Origin"
                for response in state["api_responses"]
            )
            assert not any(evidence.startswith("pageerror:") for evidence in state["browser_errors"]), state["browser_errors"]
        except BaseException as exc:
            primary_error = exc
    except BaseException as exc:
        primary_error = exc
    finally:
        cleanup_errors = []
        if page is not None and handle_dialog is not None:
            try:
                _detach_dialog_handler(page, handle_dialog)
            except Exception as exc:
                _record_cleanup_failure(cleanup_errors, "dialog-detach", exc)
        cleanup_errors.extend(state["callback_errors"])
        try:
            _close_browser_resources(page, context, browser, "focused browser check")
        except Exception as exc:
            _record_cleanup_failure(cleanup_errors, "browser-resource-close", exc)
        try:
            if playwright is not None:
                playwright.stop()
        except Exception as exc:
            _record_cleanup_failure(cleanup_errors, "playwright-stop", exc)
        try:
            _terminate_process_tree(frontend, "frontend", owned_port=frontend_port)
        except Exception as exc:
            _record_cleanup_failure(cleanup_errors, "process-tree-termination", exc)
        try:
            api_server.shutdown()
            api_server.server_close()
            api_thread.join(timeout=10)
            if api_thread.is_alive():
                cleanup_errors.append("controlled API server thread remains alive")
        except Exception as exc:
            _record_cleanup_failure(cleanup_errors, "api-server-cleanup", exc)
        try:
            _assert_port_closed(frontend_port, "frontend")
        except Exception as exc:
            _record_cleanup_failure(cleanup_errors, "port-proof", exc)
        try:
            _assert_frontend_resources_released(frontend_port, "focused browser check")
        except Exception as exc:
            _record_cleanup_failure(cleanup_errors, "frontend-resource-proof", exc)
        _raise_browser_test_errors(primary_error, cleanup_errors)


def _unused_tcp_port():
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_http(url, process):
    from urllib.request import urlopen

    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = _read_process_output(process)
            raise RuntimeError(f"frontend failed to start: {output[-4000:]}")
        try:
            with urlopen(url, timeout=2) as response:
                if response.status == 200:
                    _refresh_owned_process_tree(process)
                    return
        except OSError:
            time.sleep(0.25)
    raise RuntimeError(f"frontend did not become ready at {url}")


def _owned_tree_test_identity(pid, creation, *, parent_pid, command=None, cwd="C:/work"):
    command = command or f"python process-{pid}"
    argv = command.split()
    return {
        "pid": pid,
        "creation": creation,
        "executable": "python.exe",
        "command": command,
        "cwd": cwd,
        "argv": argv,
        "argv_sha256": hashlib.sha256("\0".join(argv).encode("utf-8")).hexdigest(),
        "native_command_sha256": hashlib.sha256(command.encode("utf-8")).hexdigest(),
        "parent_pid": parent_pid,
    }


def _owned_tree_test_process(root, marker="launch-marker", descendants=None):
    return SimpleNamespace(
        pid=root["pid"],
        _citespan_owner={
            "cwd": root["cwd"],
            "argv": root["argv"],
            "effective_argv": root["argv"],
            "pid": root["pid"],
            "owner_marker": marker,
            "creation_identity": root,
            "descendant_identities": descendants or {},
        },
    )


def _disable_platform_launch_contract_for_owned_tree_test(monkeypatch):
    monkeypatch.setattr(sys.modules[__name__], "_assert_windows_owned_command", lambda *_args: None)


def test_owned_tree_refresh_rejects_root_reuse_before_recording(monkeypatch):
    original_root = _owned_tree_test_identity(10, "original-root", parent_pid=1, command="python launch")
    reused_root = _owned_tree_test_identity(10, "reused-root", parent_pid=1, command="python replacement")
    unrelated_child = _owned_tree_test_identity(11, "foreign-child", parent_pid=10, command="python foreign")
    process = _owned_tree_test_process(
        original_root,
        descendants={99: {"pid": 99, "creation": "preserved"}},
    )
    before = dict(process._citespan_owner["descendant_identities"])

    _disable_platform_launch_contract_for_owned_tree_test(monkeypatch)
    monkeypatch.setattr(sys.modules[__name__], "_process_metadata", lambda _pid: original_root)
    monkeypatch.setattr(
        sys.modules[__name__],
        "_current_process_tree",
        lambda _pid: [reused_root, unrelated_child],
    )

    with pytest.raises(RuntimeError, match="census root identity changed"):
        _refresh_owned_process_tree(process)

    assert process._citespan_owner["descendant_identities"] == before


def test_owned_tree_capture_retains_parent_generation_for_root_exit_cleanup(monkeypatch):
    root = _owned_tree_test_identity(10, "9000", parent_pid=1, command="python launch")
    child = _owned_tree_test_identity(11, "10000", parent_pid=10, command="python child")
    process = _owned_tree_test_process(root)

    _disable_platform_launch_contract_for_owned_tree_test(monkeypatch)
    monkeypatch.setattr(sys.modules[__name__], "_process_metadata", lambda _pid: root)
    monkeypatch.setattr(sys.modules[__name__], "_current_process_tree", lambda _pid: [root, child])

    captured = _assert_owned_process_tree(process)

    assert captured[1]["parent_creation"] == "9000"


def test_owned_tree_refresh_records_only_a_valid_coherent_snapshot(monkeypatch):
    root = _owned_tree_test_identity(10, "9000", parent_pid=1, command="python launch")
    child = _owned_tree_test_identity(11, "10000", parent_pid=10, command="python child")
    process = _owned_tree_test_process(root)
    _disable_platform_launch_contract_for_owned_tree_test(monkeypatch)
    monkeypatch.setattr(sys.modules[__name__], "_process_metadata", lambda _pid: root)
    monkeypatch.setattr(sys.modules[__name__], "_current_process_tree", lambda _pid: [root, child])

    captured = _refresh_owned_process_tree(process)

    assert [item["pid"] for item in captured] == [10, 11]
    assert process._citespan_owner["descendant_identities"][11]["parent_creation"] == "9000"
    assert all(item["launch_marker"] == "launch-marker" for item in captured)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("executable", "other.exe", "root identity changed"),
        ("command", "python changed", "root identity changed"),
        ("cwd", "C:/other", "root identity changed"),
        ("parent_pid", 77, "root identity changed"),
    ],
)
def test_owned_tree_refresh_rejects_changed_root_identity(monkeypatch, field, value, message):
    root = _owned_tree_test_identity(10, "root", parent_pid=1, command="python launch")
    changed = dict(root)
    changed[field] = value
    if field == "command":
        changed["argv"] = changed["command"].split()
        changed["argv_sha256"] = hashlib.sha256("\0".join(changed["argv"]).encode("utf-8")).hexdigest()
        changed["native_command_sha256"] = hashlib.sha256(changed["command"].encode("utf-8")).hexdigest()
    process = _owned_tree_test_process(root)
    _disable_platform_launch_contract_for_owned_tree_test(monkeypatch)
    monkeypatch.setattr(sys.modules[__name__], "_process_metadata", lambda _pid: root)
    monkeypatch.setattr(sys.modules[__name__], "_current_process_tree", lambda _pid: [changed])

    with pytest.raises(RuntimeError, match=message):
        _refresh_owned_process_tree(process)
    assert process._citespan_owner["descendant_identities"] == {}


def test_owned_tree_refresh_rejects_changed_child_parent_without_mutation(monkeypatch):
    root = _owned_tree_test_identity(10, "root", parent_pid=1, command="python launch")
    child = _owned_tree_test_identity(11, "child", parent_pid=99, command="python child")
    process = _owned_tree_test_process(root, descendants={12: {"pid": 12, "creation": "keep"}})
    before = dict(process._citespan_owner["descendant_identities"])
    _disable_platform_launch_contract_for_owned_tree_test(monkeypatch)
    monkeypatch.setattr(sys.modules[__name__], "_process_metadata", lambda _pid: root)
    monkeypatch.setattr(sys.modules[__name__], "_current_process_tree", lambda _pid: [root, child])

    with pytest.raises(RuntimeError, match="missing or cyclic parent relation"):
        _refresh_owned_process_tree(process)
    assert process._citespan_owner["descendant_identities"] == before


def test_owned_tree_refresh_rejects_child_older_than_reused_parent_without_mutation(monkeypatch):
    root = _owned_tree_test_identity(10, "9000", parent_pid=1, command="python launch")
    old_child = _owned_tree_test_identity(11, "8000", parent_pid=10, command="python child")
    process = _owned_tree_test_process(root, descendants={12: {"pid": 12, "creation": "keep"}})
    before = dict(process._citespan_owner["descendant_identities"])
    _disable_platform_launch_contract_for_owned_tree_test(monkeypatch)
    monkeypatch.setattr(sys.modules[__name__], "_process_metadata", lambda _pid: root)
    monkeypatch.setattr(sys.modules[__name__], "_current_process_tree", lambda _pid: [root, old_child])

    with pytest.raises(RuntimeError, match="child creation predates its recorded parent generation"):
        _refresh_owned_process_tree(process)

    assert process._citespan_owner["descendant_identities"] == before


def test_owned_tree_refresh_rejects_child_pid_reuse_without_mutation(monkeypatch):
    root = _owned_tree_test_identity(10, "9000", parent_pid=1, command="python launch")
    child = _owned_tree_test_identity(11, "11000", parent_pid=10, command="python child")
    previous_child = _owned_tree_test_identity(11, "10000", parent_pid=10, command="python child")
    process = _owned_tree_test_process(root, descendants={11: previous_child})
    _disable_platform_launch_contract_for_owned_tree_test(monkeypatch)
    monkeypatch.setattr(sys.modules[__name__], "_process_metadata", lambda _pid: root)
    monkeypatch.setattr(sys.modules[__name__], "_current_process_tree", lambda _pid: [root, child])

    with pytest.raises(RuntimeError, match="recorded identity changed for pid=11"):
        _refresh_owned_process_tree(process)
    assert process._citespan_owner["descendant_identities"][11] == previous_child


@pytest.mark.parametrize("field", ["argv_sha256", "native_command_sha256"])
def test_owned_tree_refresh_rejects_incoherent_root_hash(monkeypatch, field):
    root = _owned_tree_test_identity(10, "root", parent_pid=1, command="python launch")
    changed = dict(root)
    changed[field] = "not-the-measured-hash"
    process = _owned_tree_test_process(root)
    _disable_platform_launch_contract_for_owned_tree_test(monkeypatch)
    monkeypatch.setattr(sys.modules[__name__], "_process_metadata", lambda _pid: root)
    monkeypatch.setattr(sys.modules[__name__], "_current_process_tree", lambda _pid: [changed])

    with pytest.raises(RuntimeError, match="incoherent"):
        _refresh_owned_process_tree(process)
    assert process._citespan_owner["descendant_identities"] == {}


def test_owned_tree_refresh_requires_the_launch_marker(monkeypatch):
    root = _owned_tree_test_identity(10, "root", parent_pid=1, command="python launch")
    process = _owned_tree_test_process(root, marker="")

    with pytest.raises(RuntimeError, match="launch ownership marker is incomplete"):
        _refresh_owned_process_tree(process)
    assert process._citespan_owner["descendant_identities"] == {}


def test_process_tree_cleanup_uses_controlled_terminal_identity_state(monkeypatch):
    root = {"pid": 10, "creation": "root", "executable": "node.exe", "command": "node", "cwd": "C:/work"}
    child = {"pid": 11, "creation": "child", "executable": "node.exe", "command": "node child", "cwd": "C:/work"}
    process = SimpleNamespace(
        pid=10,
        args=["node"],
        _citespan_owner={"creation_identity": root},
        poll=lambda: 0,
        wait=lambda timeout: None,
    )
    trees = [[root, child], [root]]
    stopped = []

    def owned_tree(_process):
        if trees:
            return trees.pop(0)
        raise ProcessIdentityAbsent("root already exited")

    def stop(identities, _label, _timeout, **_kwargs):
        stopped.extend(item["pid"] for item in identities)
        return [{"pid": item["pid"], "state": "already_exited"} for item in identities]

    monkeypatch.setattr(sys.modules[__name__], "_assert_owned_process_tree", owned_tree)
    monkeypatch.setattr(sys.modules[__name__], "_stop_verified_process_identities", stop)
    monkeypatch.setattr(sys.modules[__name__], "_assert_recorded_process_identities_stopped", lambda *_args: [])
    monkeypatch.setattr(sys.modules[__name__], "_read_process_output", lambda *_args, **_kwargs: "")

    _terminate_process_tree(process, "controlled process-tree fixture")

    assert stopped == [11, 10]


def test_process_tree_cleanup_drains_a_late_owned_descendant(monkeypatch):
    root = {"pid": 10, "creation": "root"}
    first_child = {"pid": 11, "creation": "first"}
    late_child = {"pid": 12, "creation": "late"}
    trees = [[root, first_child], [root, late_child], [root]]
    stopped = []
    waited = {"value": False}

    class Process:
        pid = 10
        _citespan_owner = {"creation_identity": root}

        def poll(self):
            return 0 if waited["value"] else None

        def wait(self, timeout):
            waited["value"] = True

    monkeypatch.setattr(sys.modules[__name__], "_assert_owned_process_tree", lambda _process: trees.pop(0))

    def stop(identities, _label, _timeout, **_kwargs):
        stopped.extend(item["pid"] for item in identities)
        if any(item["pid"] == 10 for item in identities):
            waited["value"] = True
        return [{"pid": item["pid"], "state": "stopped"} for item in identities]

    monkeypatch.setattr(sys.modules[__name__], "_stop_verified_process_identities", stop)
    monkeypatch.setattr(sys.modules[__name__], "_assert_recorded_process_identities_stopped", lambda *_args: [])
    monkeypatch.setattr(sys.modules[__name__], "_read_process_output", lambda *_args, **_kwargs: "")

    _terminate_process_tree(Process(), "late descendant fixture")

    assert stopped == [11, 12, 10]


def test_process_tree_cleanup_uses_recorded_descendants_after_root_exit(monkeypatch):
    root = {"pid": 10, "creation": "root"}
    child = {
        "pid": 11,
        "creation": "child",
        "parent_pid": 10,
        "parent_creation": "root",
    }
    owner = {
        "creation_identity": root,
        "owner_marker": "launch-marker",
        "descendant_identities": {11: {**child, "launch_marker": "launch-marker"}},
    }
    stopped = []

    class Process:
        pid = 10
        _citespan_owner = owner

        def poll(self):
            return 0

        def wait(self, timeout):
            return None

    def stopped_identities(identities, _label, _timeout, **_kwargs):
        stopped.extend(item["pid"] for item in identities)
        return [{"pid": item["pid"], "state": "already_exited"} for item in identities]

    monkeypatch.setattr(
        sys.modules[__name__],
        "_assert_owned_process_tree",
        lambda _process: (_ for _ in ()).throw(ProcessIdentityAbsent("root exited")),
    )
    monkeypatch.setattr(sys.modules[__name__], "_stop_verified_process_identities", stopped_identities)
    monkeypatch.setattr(sys.modules[__name__], "_read_process_output", lambda *_args, **_kwargs: "")

    _terminate_process_tree(Process(), "recorded descendant fixture")

    assert stopped == [11, 10]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("parent_creation", None, "missing or malformed"),
        ("parent_creation", "reused-root", "does not match"),
    ],
)
def test_process_tree_cleanup_rejects_invalid_recorded_parent_generation_before_stop(
    monkeypatch, field, value, message
):
    root = {"pid": 10, "creation": "root"}
    child = {
        "pid": 11,
        "creation": "child",
        "parent_pid": 10,
        "parent_creation": "root",
    }
    child[field] = value
    owner = {
        "creation_identity": root,
        "owner_marker": "launch-marker",
        "descendant_identities": {11: {**child, "launch_marker": "launch-marker"}},
    }
    stopped = []

    class Process:
        pid = 10
        _citespan_owner = owner

        def poll(self):
            return 0

        def wait(self, timeout):
            raise AssertionError("root wait must not run after validation failure")

    def stop(identities, _label, _timeout, **_kwargs):
        stopped.extend(item["pid"] for item in identities)
        raise AssertionError("stop must not run after validation failure")

    monkeypatch.setattr(
        sys.modules[__name__],
        "_assert_owned_process_tree",
        lambda _process: (_ for _ in ()).throw(ProcessIdentityAbsent("root exited")),
    )
    monkeypatch.setattr(sys.modules[__name__], "_stop_verified_process_identities", stop)

    with pytest.raises(RuntimeError, match=message):
        _terminate_process_tree(Process(), "invalid recorded edge fixture")

    assert stopped == []
    assert owner["descendant_identities"] == {11: {**child, "launch_marker": "launch-marker"}}


def test_process_tree_cleanup_does_not_bind_recorded_child_to_reused_parent_generation(monkeypatch):
    root = {"pid": 10, "creation": "root"}
    replacement_parent = {
        "pid": 12,
        "creation": "new-parent",
        "parent_pid": 10,
        "parent_creation": "root",
    }
    child = {
        "pid": 11,
        "creation": "child",
        "parent_pid": 12,
        "parent_creation": "old-parent",
    }
    owner = {
        "creation_identity": root,
        "owner_marker": "launch-marker",
        "descendant_identities": {
            12: {**replacement_parent, "launch_marker": "launch-marker"},
            11: {**child, "launch_marker": "launch-marker"},
        },
    }
    stopped = []

    class Process:
        pid = 10
        _citespan_owner = owner

        def poll(self):
            return 0

        def wait(self, timeout):
            raise AssertionError("root wait must not run after validation failure")

    monkeypatch.setattr(
        sys.modules[__name__],
        "_assert_owned_process_tree",
        lambda _process: (_ for _ in ()).throw(ProcessIdentityAbsent("root exited")),
    )
    monkeypatch.setattr(
        sys.modules[__name__],
        "_stop_verified_process_identities",
        lambda identities, *_args, **_kwargs: stopped.extend(item["pid"] for item in identities),
    )

    with pytest.raises(RuntimeError, match="does not match"):
        _terminate_process_tree(Process(), "reused parent fixture")

    assert stopped == []
    assert owner["descendant_identities"] == {
        12: {**replacement_parent, "launch_marker": "launch-marker"},
        11: {**child, "launch_marker": "launch-marker"},
    }


def test_process_tree_cleanup_stops_a_seven_level_chain_leaf_first(monkeypatch):
    identities = [
        {
            "pid": pid,
            "creation": f"creation-{pid}",
            "executable": "node.exe",
            "command": f"node level-{pid}",
            "cwd": "C:/work",
            "parent_pid": pid - 1 if pid > 10 else 1,
        }
        for pid in range(10, 18)
    ]
    trees = [identities, [identities[0]]]
    stopped = []
    waited = {"value": False}

    class Process:
        pid = 10
        _citespan_owner = {"creation_identity": identities[0]}

        def poll(self):
            return 0 if waited["value"] else None

        def wait(self, timeout):
            waited["value"] = True

    monkeypatch.setattr(sys.modules[__name__], "_assert_owned_process_tree", lambda _process: trees.pop(0))

    def metadata(pid):
        return dict(identities[pid - 10])

    def stop(item, _label, _timeout):
        stopped.append(item["pid"])
        if item["pid"] == 10:
            waited["value"] = True

    monkeypatch.setattr(sys.modules[__name__], "_process_metadata", metadata)
    monkeypatch.setattr(sys.modules[__name__], "_terminate_verified_windows_identity", stop)
    monkeypatch.setattr(
        sys.modules[__name__],
        "_poll_process_terminal_state",
        lambda item, _label: {"pid": item["pid"], "state": "verified_exited", "creation": item["creation"]},
    )
    monkeypatch.setattr(sys.modules[__name__], "_read_process_output", lambda *_args, **_kwargs: "")

    _terminate_process_tree(Process(), "seven-level fixture")

    assert stopped == [17, 16, 15, 14, 13, 12, 11, 10]


def test_process_tree_cleanup_reports_deadline_exhaustion_from_census_cost(monkeypatch):
    root = {"pid": 10, "creation": "root"}
    child = {"pid": 11, "creation": "child"}

    def slow_census(_process):
        return [root, child]

    monkeypatch.setattr(sys.modules[__name__], "_assert_owned_process_tree", slow_census)
    monkeypatch.setattr(sys.modules[__name__], "_read_process_output", lambda *_args, **_kwargs: "")
    monotonic_values = iter((0.0, 0.0, 2.0, 2.0))
    monkeypatch.setattr(time, "monotonic", lambda: next(monotonic_values))
    process = SimpleNamespace(
        pid=10,
        _citespan_owner={"creation_identity": root},
        poll=lambda: None,
    )

    with pytest.raises(RuntimeError, match=r"deadline exhausted.*phase_times=.*census"):
        _terminate_process_tree(process, "census deadline fixture", timeout=0.001)


def test_frontend_resource_postcondition_rejects_a_native_holder(monkeypatch):
    native = (release.SCRIPT_ROOT / release.HOST_NATIVE_MODULE).resolve().as_posix()
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {
            "processes": [],
            "holders": [{"pid": 12, "module_paths": [native]}],
            "ports": [],
            "read_errors": [],
        },
    )

    with pytest.raises(RuntimeError, match="native module holder"):
        _assert_frontend_resources_released(43123, "resource fixture")


def test_frontend_resource_postcondition_accepts_empty_scoped_census(monkeypatch):
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {"processes": [], "holders": [], "ports": [], "read_errors": []},
    )

    _assert_frontend_resources_released(43123, "resource fixture")


def _installed_browser_executable():
    candidates = [
        os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE"),
        shutil.which("msedge.exe"),
        shutil.which("chrome.exe"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise RuntimeError("focused browser check requires an installed Chrome or Edge executable")
