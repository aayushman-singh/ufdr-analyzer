import json
import ctypes
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
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import release
import verify_live


ROOT = Path(__file__).resolve().parents[2]


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
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    launch_env = os.environ.copy() if env is None else env.copy()
    launch_env["CITESPAN_TEST_PROCESS_OWNER"] = uuid.uuid4().hex
    expected_cwd = str(Path(cwd or ROOT).resolve())
    effective_argv = [str(item) for item in argv]
    if os.name == "nt":
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
            start_new_session=os.name != "nt",
        )
    except Exception:
        output_file.close()
        output_path.unlink(missing_ok=True)
        raise
    output_file.close()
    process._citespan_output_path = output_path
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
            raise RuntimeError(
                f"process identity capture failed for live pid {process.pid}: {exc}"
            ) from exc
    process._citespan_owner = {
        "cwd": expected_cwd,
        "argv": [str(item) for item in argv],
        "effective_argv": effective_argv,
        "pid": process.pid,
        "creation_identity": creation_identity,
    }
    return process


def _process_metadata(pid):
    if os.name == "nt":
        command = (
            "$p = Get-CimInstance Win32_Process -Filter 'ProcessId = "
            f"{pid}'; "
            " if ($null -eq $p) { exit 3 }; $p | Select-Object ProcessId,ParentProcessId,"
            "CreationDate,ExecutablePath,CommandLine | ConvertTo-Json -Compress"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"process identity lookup failed for pid {pid}: rc={result.returncode} "
                f"stdout={result.stdout[-2000:]} stderr={result.stderr[-2000:]}"
            )
        metadata = json.loads(result.stdout)
        return {
            "pid": int(metadata["ProcessId"]),
            "parent_pid": int(metadata["ParentProcessId"]),
            "creation": _windows_creation_token(pid),
            "executable": str(metadata.get("ExecutablePath") or ""),
            "command": str(metadata.get("CommandLine") or ""),
            "cwd": _windows_current_working_directory(pid),
        }

    proc_root = Path("/proc") / str(pid)
    try:
        stat_fields = (proc_root / "stat").read_text(encoding="utf-8").split()
        command = (proc_root / "cmdline").read_bytes().replace(b"\x00", b" ").decode(errors="replace").strip()
        return {
            "pid": pid,
            "parent_pid": int(stat_fields[3]),
            "creation": stat_fields[21],
            "executable": str((proc_root / "exe").resolve()),
            "command": command,
            "cwd": str((proc_root / "cwd").resolve()),
        }
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise RuntimeError(f"process identity lookup failed for pid {pid}: {exc}") from exc


def _windows_creation_token(pid):
    if os.name != "nt":
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
    if os.name != "nt":
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
    if os.name == "nt":
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
    identity_keys = ("pid", "creation", "executable", "command", "cwd")
    if any(current_root[key] != recorded_root[key] for key in identity_keys):
        raise RuntimeError(
            f"process cleanup denied: root identity changed; recorded={recorded_root} current={current_root}"
        )
    expected_cwd = _canonical_path_identity(owner["cwd"])
    current_cwd = _canonical_path_identity(current_root["cwd"])
    if not current_cwd:
        raise RuntimeError(f"process cleanup denied: root worktree is unavailable; expected={owner['cwd']}")
    if current_cwd != expected_cwd:
        raise RuntimeError(
            f"process cleanup denied: root worktree changed; expected={owner['cwd']} current={current_root['cwd']}"
        )
    if os.name == "nt":
        _assert_windows_owned_command(current_root, owner)
    elif current_root["command"].split()[: len(owner["argv"])] != owner["argv"]:
        raise RuntimeError(
            f"process cleanup denied: root command changed; expected={owner['argv']} current={current_root['command']}"
        )
    tree = _current_process_tree(process.pid)
    if not tree or tree[0]["pid"] != process.pid:
        raise RuntimeError(f"process cleanup denied: owned root {process.pid} is not in the current process tree")
    for item in tree[1:]:
        if not item["executable"]:
            raise RuntimeError(f"process cleanup denied: descendant {item['pid']} executable is unavailable")
        item_cwd = _canonical_path_identity(item["cwd"])
        if not item_cwd:
            raise RuntimeError(f"process cleanup denied: descendant {item['pid']} worktree is unavailable")
        if item_cwd != expected_cwd:
            raise RuntimeError(
                f"process cleanup denied: descendant {item['pid']} left the product worktree "
                f"expected={owner['cwd']} current={item['cwd']}"
            )
        if not item["command"]:
            raise RuntimeError(f"process cleanup denied: descendant {item['pid']} has no command identity")
    return tree


def _canonical_path_identity(path):
    value = str(path or "")
    if not value:
        return ""
    if os.name != "nt":
        return value
    return os.path.normcase(os.path.normpath(value)).casefold()


def _windows_command_line_argv(command):
    if os.name != "nt":
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


def _terminate_process_tree(process, label, timeout=15, owned_port=None):
    if process is None:
        return ""
    diagnostics = []
    try:
        if process.poll() is not None:
            raise RuntimeError(f"root process {process.pid} exited before owned-tree verification")
        tree = _assert_owned_process_tree(process)
        recorded_identities = {
            item["pid"]: item["creation"] for item in tree
        }
        diagnostics.append(
            "verified owned process tree=" + ",".join(str(item["pid"]) for item in tree)
        )
        if process.poll() is None:
            if os.name == "nt":
                result = subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                diagnostics.append(
                    f"taskkill rc={result.returncode} stdout={result.stdout[-2000:]} stderr={result.stderr[-2000:]}"
                )
                if result.returncode != 0:
                    raise RuntimeError(
                        f"taskkill failed with exit code {result.returncode}: "
                        f"stdout={result.stdout[-2000:]} stderr={result.stderr[-2000:]}"
                    )
            else:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    result = subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                        check=False,
                    )
                    if result.returncode != 0:
                        raise RuntimeError(
                            f"taskkill escalation failed with exit code {result.returncode}: "
                            f"stdout={result.stdout[-2000:]} stderr={result.stderr[-2000:]}"
                        )
                else:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                process.wait(timeout=timeout)
        if process.poll() is None:
            raise RuntimeError(f"{label} cleanup failed: root process {process.pid} remains")
        for pid, creation in recorded_identities.items():
            try:
                current = _process_metadata(pid)
            except RuntimeError as exc:
                if "rc=3 stdout= stderr=" not in str(exc) and "No such file or directory" not in str(exc):
                    raise RuntimeError(
                        f"{label} cleanup failed: cannot prove process identity {pid} is absent: {exc}"
                    ) from exc
            else:
                if current["creation"] == creation:
                    raise RuntimeError(
                        f"{label} cleanup failed: recorded process identity remains active: "
                        f"pid={pid} creation={creation} current={current}"
                    )
                raise RuntimeError(
                    f"{label} cleanup failed: process identity changed while pid remained active: "
                    f"pid={pid} recorded_creation={creation} current={current}"
                )
        if owned_port is not None:
            _assert_port_closed(owned_port, label)
        output = _read_process_output(process)
        if output:
            diagnostics.append(f"captured output={output}")
        return "\n".join(diagnostics)
    except Exception as exc:
        output_path = getattr(process, "_citespan_output_path", None)
        try:
            evidence = _read_process_output(process, retain=True)
        except Exception as output_exc:
            evidence = f"output cleanup error={output_exc} output_path_retained={output_path}"
        raise RuntimeError(
            f"{label} cleanup failed for pid {process.pid}: {exc}; process evidence={evidence[-4000:]} "
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


class _FakePage:
    def __init__(self):
        self.title_value = "CiteSpan"
        self.actions = []
        self.query_response = {
            "planner": "stub",
            "rows": [
                {
                    "source_table": "aleappartifact",
                    "row_id": verify_live.CANONICAL_DEMO_ARTIFACT_ROW_ID,
                    "citations": [
                        {
                            "source_table": "aleappartifact",
                            "row_id": verify_live.CANONICAL_DEMO_ARTIFACT_ROW_ID,
                            "column": "filename",
                            "snippet": "whatsapp_messages.csv",
                            "matched_value": "whatsapp",
                            "char_start": 0,
                            "char_end": 8,
                        }
                    ]
                }
            ],
        }
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
        ".cite": _FakeLocator(texts=["whatsapp"]),
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
    assert result["query_response"]["rows"][0]["citations"][0]["matched_value"] == "whatsapp"
    assert result["upload_status"] == 403
    assert result["ingestion_statuses"] == {
        "/api/ingest/": 403,
        "/api/ingest/validate-path": 403,
        "/api/ingest/aleapp-structure": 403,
    }
    assert (tmp_path / "citespan-home.png").is_file()
    assert (tmp_path / "citespan-upload-disabled.png").is_file()
    assert (tmp_path / "citespan-query-results.png").is_file()
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
    verify_live._validate_cited_response(
        {
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
    )


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
    (tmp_path / "citespan-home.png").write_bytes(b"home")
    (tmp_path / "citespan-query-results.png").write_bytes(b"results")
    result = verify_live._write_proof_artifacts(
        tmp_path,
        "https://citespan.example",
        "Show bank transfers",
        ["citespan-home.png", "citespan-query-results.png"],
        {
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
        },
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
    with pytest.raises(RuntimeError, match="existing browser screenshots"):
        verify_live._write_proof_artifacts(
            tmp_path,
            "https://citespan.example",
            "Q",
            ["missing.png"],
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
    if os.name != "nt":
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
    return _windows_command_line_argv(command) if os.name == "nt" else command.split()


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
            parsed = _windows_command_line_argv(metadata["command"]) if os.name == "nt" else metadata["command"].split()
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
    if os.name != "nt":
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
        if os.name == "nt"
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
    parsed = _windows_command_line_argv(current["command"]) if os.name == "nt" else current["command"].split()
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


def _assert_recorded_process_identities_stopped(recorded, label):
    for pid, creation in recorded.items():
        try:
            current = _process_metadata(pid)
        except RuntimeError as exc:
            if "rc=3 stdout= stderr=" in str(exc) or "No such file or directory" in str(exc):
                continue
            raise RuntimeError(f"{label} cannot prove stopped identity: pid={pid} error={exc}") from exc
        if current["creation"] == creation:
            raise RuntimeError(f"{label} retained an active recorded identity: pid={pid} creation={creation}")
        raise RuntimeError(
            f"{label} found PID reuse after stop: pid={pid} recorded_creation={creation} current={current}"
        )


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
    next_bin = frontend_root / "node_modules" / ".bin" / ("next.cmd" if os.name == "nt" else "next")
    next_bin.parent.mkdir(parents=True, exist_ok=True)
    next_bin.write_text("next", encoding="utf-8")


def test_frontend_dependency_readiness_rejects_missing_project_next_executable(tmp_path):
    frontend_root = tmp_path / "frontend"
    _write_browser_dependency_fixture(frontend_root)
    next_bin = frontend_root / "node_modules" / ".bin" / ("next.cmd" if os.name == "nt" else "next")
    next_bin.unlink()

    findings = _frontend_browser_dependency_findings(frontend_root)

    assert any("project-scoped Next executable is missing" in finding for finding in findings)


def test_frontend_dependency_readiness_rejects_stale_or_incomplete_locked_state(tmp_path):
    frontend_root = tmp_path / "frontend"
    _write_browser_dependency_fixture(frontend_root)
    (frontend_root / "node_modules" / "next" / "package.json").write_text(
        json.dumps({"name": "next", "version": "15.5.26"}), encoding="utf-8"
    )
    (frontend_root / "node_modules" / "@playwright" / "test" / "package.json").unlink()

    findings = _frontend_browser_dependency_findings(frontend_root)

    assert any("next installed version does not match" in finding for finding in findings)
    assert any("@playwright/test installed package metadata is missing" in finding for finding in findings)


def test_frontend_dependency_install_uses_real_npm_and_frontend_cwd(tmp_path, monkeypatch):
    frontend_root = (tmp_path / "frontend").resolve()
    frontend_root.mkdir()
    calls = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(
        shutil,
        "which",
        lambda name: "C:/Program Files/nodejs/npm.cmd" if name == "npm.cmd" else None,
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kwargs: calls.append((argv, kwargs)) or Result(),
    )

    _install_frontend_dependencies_for_browser(frontend_root)

    assert calls == [
        (
            [str(Path("C:/Program Files/nodejs/npm.cmd").resolve()), "ci", "--ignore-scripts"],
            {
                "cwd": frontend_root,
                "capture_output": True,
                "text": True,
                "timeout": 300,
                "check": False,
            },
        )
    ]


def test_frontend_dependency_preparation_fails_before_browser_launch_when_install_is_incomplete(
    tmp_path, monkeypatch
):
    frontend_root = tmp_path / "frontend"
    _write_browser_dependency_fixture(frontend_root)
    monkeypatch.setattr(
        sys.modules[__name__],
        "_install_frontend_dependencies_for_browser",
        lambda _frontend_root: None,
    )
    (frontend_root / "node_modules" / ".bin" / ("next.cmd" if os.name == "nt" else "next")).unlink()

    with pytest.raises(RuntimeError, match="did not establish a verified project-scoped installation"):
        _prepare_frontend_dependencies_for_browser(frontend_root)


_BROWSER_FRONTEND_REQUIRED_PACKAGES = ("next", "react", "react-dom", "@playwright/test")


def _frontend_browser_dependency_findings(frontend_root):
    package_path = frontend_root / "package.json"
    lock_path = frontend_root / "package-lock.json"
    if not package_path.is_file() or not lock_path.is_file():
        return [
            "frontend/package.json and frontend/package-lock.json are required "
            f"for browser startup: package={package_path} lock={lock_path}"
        ]
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [
            "frontend dependency contract cannot be read before browser startup: "
            f"package={package_path} lock={lock_path} error={exc}"
        ]
    if not isinstance(package, dict) or not isinstance(lock, dict):
        return ["frontend dependency contract must contain JSON objects"]
    lock_packages = lock.get("packages")
    if not isinstance(lock_packages, dict):
        return ["frontend/package-lock.json has no valid packages map"]
    findings = []
    declared = {
        **(package.get("dependencies") or {}),
        **(package.get("devDependencies") or {}),
    }
    lock_root = lock_packages.get("")
    if not isinstance(lock_root, dict):
        findings.append("frontend/package-lock.json has no valid root package entry")
        lock_root = {}
    for name in _BROWSER_FRONTEND_REQUIRED_PACKAGES:
        declaration = declared.get(name)
        lock_declaration = (
            (lock_root.get("dependencies") or {}).get(name)
            or (lock_root.get("devDependencies") or {}).get(name)
        )
        lock_entry = lock_packages.get(f"node_modules/{name}")
        installed_path = frontend_root / "node_modules" / Path(name) / "package.json"
        if declaration is None:
            findings.append(f"{name} is not declared in frontend/package.json")
        if lock_declaration != declaration:
            findings.append(
                f"{name} package declaration differs between package.json and package-lock.json: "
                f"package={declaration!r} lock={lock_declaration!r}"
            )
        if not isinstance(lock_entry, dict) or not lock_entry.get("version"):
            findings.append(f"{name} has no locked package entry")
            continue
        if not installed_path.is_file():
            findings.append(f"{name} installed package metadata is missing: {installed_path}")
            continue
        try:
            installed = json.loads(installed_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            findings.append(f"{name} installed package metadata is unreadable: {installed_path}: {exc}")
            continue
        if installed.get("version") != lock_entry["version"]:
            findings.append(
                f"{name} installed version does not match package-lock.json: "
                f"installed={installed.get('version')!r} locked={lock_entry['version']!r}"
            )
    next_executable = frontend_root / "node_modules" / ".bin" / ("next.cmd" if os.name == "nt" else "next")
    if not next_executable.is_file():
        findings.append(f"project-scoped Next executable is missing: {next_executable}")
    return findings


def _install_frontend_dependencies_for_browser(frontend_root):
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm:
        raise RuntimeError("frontend dependency setup requires the real npm executable")
    npm_path = Path(npm).resolve()
    working_directory = frontend_root.resolve()
    result = subprocess.run(
        [str(npm_path), "ci", "--ignore-scripts"],
        cwd=working_directory,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "frontend dependency setup failed before browser startup: "
            f"returncode={result.returncode} cwd={working_directory} argv={[str(npm_path), 'ci', '--ignore-scripts']} "
            f"stdout={result.stdout[-4000:]} stderr={result.stderr[-4000:]}"
        )


def _prepare_frontend_dependencies_for_browser(frontend_root):
    initial_findings = _frontend_browser_dependency_findings(frontend_root)
    if not initial_findings:
        return
    _install_frontend_dependencies_for_browser(frontend_root)
    final_findings = _frontend_browser_dependency_findings(frontend_root)
    if final_findings:
        raise RuntimeError(
            "frontend dependency preparation did not establish a verified project-scoped installation: "
            f"frontend_root={frontend_root.resolve()} initial_findings={initial_findings} "
            f"final_findings={final_findings}"
        )


def _ensure_frontend_dependencies_for_browser():
    frontend_root = ROOT / "frontend"
    initial_findings = _frontend_browser_dependency_findings(frontend_root)
    if not initial_findings:
        return
    (
        evidence_root,
        candidates,
        additional_records,
        family_records,
        protected_records,
        unrelated_records,
        presence,
        approval_records,
    ) = _load_legacy_process_evidence()
    process_graph = _frontend_process_graph()
    protected = {os.getpid()}
    current = os.getpid()
    while current in process_graph and process_graph[current]["parent_pid"] not in protected:
        current = process_graph[current]["parent_pid"]
        protected.add(current)
    pending = [os.getpid()]
    while pending:
        parent_pid = pending.pop()
        for item in process_graph.values():
            if item["parent_pid"] == parent_pid and item["pid"] not in protected:
                protected.add(item["pid"])
                pending.append(item["pid"])
    expected = _canonical_path_identity(frontend_root.resolve())
    process_graph = _frontend_process_graph()
    candidate_pids = {candidate["pid"] for candidate in candidates if candidate["pid"] in process_graph}
    additional_pids = {record["pid"] for record in additional_records if record["pid"] in process_graph}
    enriched_pids = _frontend_enrichment_pids(
        process_graph,
        candidate_pids | additional_pids,
        protected,
        expected,
    )
    _frontend_enrich_process_graph(process_graph, enriched_pids)
    active_candidates, candidate_states = _classify_frontend_records(
        candidates,
        process_graph,
        presence,
        approval_records,
    )
    active_additional, additional_states = _classify_frontend_records(
        additional_records,
        process_graph,
        presence,
        approval_records,
    )
    reused_pids = {
        pid for pid, state in {**candidate_states, **additional_states}.items() if state == "reused"
    }
    candidate_pids = {candidate["pid"] for candidate in active_candidates}
    additional_by_pid = {record["pid"]: record for record in active_additional}
    selected_pids = candidate_pids | set(additional_by_pid)
    protected_input = {item["pid"] for item in protected_records}
    unrelated_input = {item["pid"] for item in unrelated_records}
    if not protected_input <= protected:
        raise RuntimeError(
            f"frontend dependency protected census is not live: pids={sorted(protected_input - protected)}"
        )
    if unrelated_input & selected_pids:
        raise RuntimeError(
            f"frontend dependency cleanup denied unrelated selected identity: pids={sorted(unrelated_input & selected_pids)}"
        )
    if not unrelated_input <= set(process_graph):
        raise RuntimeError(
            f"frontend dependency exclusion input is not live: pids={sorted(unrelated_input - set(process_graph))}"
        )
    for pid in unrelated_input:
        if pid in protected or pid in selected_pids:
            raise RuntimeError(f"frontend dependency unrelated identity was selected: pid={pid}")
        if _frontend_lightweight_relevance(process_graph[pid], expected):
            raise RuntimeError(
                f"frontend dependency cleanup cannot exclude a potentially relevant identity: pid={pid}"
            )
    unrelated_exclusions = []
    for pid, item in process_graph.items():
        if pid in protected or pid in selected_pids:
            continue
        if pid in reused_pids:
            unrelated_exclusions.append(
                {"pid": pid, "reason": "fresh identity classified as reused and left unselected"}
            )
            continue
        if item.get("enriched") and _canonical_path_identity(item["cwd"]) == expected:
            raise RuntimeError(
                f"frontend dependency cleanup found an unrecorded relevant product-cwd identity: pid={pid}"
            )
        reason = (
            "measured outside product cwd and not selected"
            if item.get("enriched")
            else _frontend_lightweight_exclusion_for_expected(item, expected)
        )
        if not reason:
            raise RuntimeError(
                f"frontend dependency process type remained unclassified: pid={pid}"
            )
        unrelated_exclusions.append({"pid": pid, "reason": reason})
    if not active_candidates:
        _assert_cleanup_postcondition_already_satisfied(evidence_root)
    for candidate in active_candidates:
        if candidate["pid"] in protected:
            raise RuntimeError(f"frontend dependency cleanup denied current gate/test ownership: pid={candidate['pid']}")
    candidates_by_pid = {candidate["pid"]: candidate for candidate in active_candidates}
    selected_records = {
        **candidates_by_pid,
        **additional_by_pid,
    }
    for candidate in active_candidates:
        observations = candidate["parent_observations"]
        if not isinstance(observations, list) or not observations:
            raise RuntimeError(f"frontend dependency ancestry proof is missing parent observations: pid={candidate['pid']}")
        for observation in observations:
            state = observation.get("state") if isinstance(observation, dict) else None
            if state not in {
                "readable_current_parent",
                "verified_absent_historical_parent",
                "unreadable_parent",
                "reused_parent",
                "historical_parent_exited_pid_reused",
            }:
                raise RuntimeError(f"frontend dependency ancestry proof has invalid parent state: pid={candidate['pid']} observation={observation}")
            if state in {"unreadable_parent", "reused_parent"}:
                raise RuntimeError(f"frontend dependency ancestry proof is not clean: pid={candidate['pid']} observation={observation}")
        _frontend_candidate_tree(candidate, process_graph, expected)
    roots = [record for record in selected_records.values() if record["parent_pid"] not in selected_records]
    if active_candidates and not roots:
        raise RuntimeError("frontend dependency evidence has no selected legacy tree root")
    selected_trees = []
    for candidate in roots:
        if candidate["pid"] in protected:
            raise RuntimeError(f"frontend dependency cleanup denied current gate/test ownership: pid={candidate['pid']}")
        if candidate["pid"] not in process_graph:
            raise RuntimeError(f"frontend dependency cleanup missing current candidate: pid={candidate['pid']}")
        if candidate["pid"] in candidates_by_pid:
            selected_trees.append(_frontend_candidate_tree(candidate, process_graph, expected))
        else:
            selected_trees.append(_frontend_additional_tree(candidate, process_graph, expected))
    recorded = {}
    for tree in selected_trees:
        for item in tree:
            historical = candidates_by_pid.get(item["pid"])
            additional = additional_by_pid.get(item["pid"])
            recorded_source = historical or additional
            if recorded_source is None:
                raise RuntimeError(f"frontend dependency ownership proof found unrecorded descendant: pid={item['pid']}")
            if item["creation"] != str(recorded_source["creation"]):
                raise RuntimeError(f"frontend dependency ownership proof changed descendant identity: pid={item['pid']}")
            if _canonical_path_identity(item["cwd"]) != _canonical_path_identity(recorded_source["cwd"]):
                raise RuntimeError(f"frontend dependency ownership proof changed descendant cwd: pid={item['pid']}")
            if not item["executable"] or not item["command"]:
                raise RuntimeError(f"frontend dependency ownership proof missing descendant identity: pid={item['pid']}")
            observation = historical if historical else additional
            parsed = _windows_command_line_argv(item["command"]) if os.name == "nt" else item["command"].split()
            if (
                item["parent_pid"] != int(observation["parent_pid"])
                or _canonical_path_identity(item["executable"]) != _canonical_path_identity(observation["executable"])
                or parsed != [str(value) for value in observation["argv"]]
                or hashlib.sha256("\0".join(parsed).encode("utf-8")).hexdigest() != str(observation["argv_sha256"])
                or hashlib.sha256(item["command"].encode("utf-8")).hexdigest() != str(observation["native_command_sha256"])
            ):
                raise RuntimeError(
                    f"frontend dependency ownership proof changed descendant command identity: pid={item['pid']}"
                )
            recorded[item["pid"]] = item["creation"]
    if selected_trees:
        process_graph = _frontend_process_graph()
        if any(candidate["pid"] not in process_graph for candidate in active_candidates):
            raise RuntimeError("frontend dependency cleanup lost a selected candidate before stop proof")
        for candidate in roots:
            tree = (
                _frontend_candidate_tree(candidate, process_graph, expected)
                if candidate["pid"] in candidates_by_pid
                else _frontend_additional_tree(candidate, process_graph, expected)
            )
            if any(item["pid"] in protected for item in tree):
                raise RuntimeError(f"frontend dependency cleanup denied current gate/test descendant: pid={candidate['pid']}")
        for candidate in roots:
            result = subprocess.run(
                ["taskkill", "/PID", str(candidate["pid"]), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"frontend dependency cleanup failed: pid={candidate['pid']} rc={result.returncode} "
                    f"stdout={result.stdout[-2000:]} stderr={result.stderr[-2000:]} evidence_root={evidence_root}"
                )
        _assert_recorded_process_identities_stopped(recorded, "frontend dependency cleanup")
        _assert_frontend_files_released(active_candidates, evidence_root)
        for candidate in active_candidates:
            for port in candidate.get("ports", []):
                _assert_port_closed(int(port), "frontend dependency cleanup")
    _prepare_frontend_dependencies_for_browser(frontend_root)


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
                cleanup_errors.append(f"dialog handler detachment failed: {exc!r}")
        cleanup_errors.extend(state["callback_errors"])
        try:
            _close_browser_resources(page, context, browser, "focused browser check")
        except Exception as exc:
            cleanup_errors.append(str(exc))
        try:
            if playwright is not None:
                playwright.stop()
        except Exception as exc:
            cleanup_errors.append(f"Playwright cleanup failed: {exc}")
        try:
            _terminate_process_tree(frontend, "frontend", owned_port=frontend_port)
        except Exception as exc:
            cleanup_errors.append(str(exc))
        try:
            api_server.shutdown()
            api_server.server_close()
            api_thread.join(timeout=10)
            if api_thread.is_alive():
                cleanup_errors.append("controlled API server thread remains alive")
        except Exception as exc:
            cleanup_errors.append(f"controlled API server cleanup failed: {exc}")
        try:
            _assert_port_closed(frontend_port, "frontend")
        except Exception as exc:
            cleanup_errors.append(str(exc))
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
                    return
        except OSError:
            time.sleep(0.25)
    raise RuntimeError(f"frontend did not become ready at {url}")


def test_process_tree_cleanup_terminates_descendant_and_releases_file(tmp_path):
    held_path = tmp_path / "held-by-child.txt"
    ready_path = tmp_path / "child-ready.txt"
    child_code = (
        "import pathlib, sys, time; "
        "handle = open(sys.argv[1], 'w'); "
        "pathlib.Path(sys.argv[2]).write_text('ready', encoding='utf-8'); "
        "time.sleep(600)"
    )
    parent_code = (
        "import subprocess, sys; "
        f"child = subprocess.Popen([sys.executable, '-c', {child_code!r}, sys.argv[1], sys.argv[2]]); "
        "child.wait()"
    )
    process = _launch_process_tree([sys.executable, "-c", parent_code, str(held_path), str(ready_path)])
    try:
        if os.name == "nt":
            effective_argv = process._citespan_owner["effective_argv"]
            assert effective_argv[1] == "-c"
            assert effective_argv[3] == os.environ.get("COMSPEC", "cmd.exe")
            assert effective_argv[3] != "-c"
        deadline = time.monotonic() + 10
        while not ready_path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready_path.exists(), _read_process_output(process)
    finally:
        _terminate_process_tree(process, "process-tree fixture")
    assert process.poll() is not None
    held_path.unlink()
    assert not held_path.exists()


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
