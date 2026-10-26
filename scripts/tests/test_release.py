import base64
import json
import ctypes
import errno
import stat
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import io
import time
import traceback
import uuid
from pathlib import Path
from pathlib import PurePosixPath
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import release


ROOT = Path(__file__).resolve().parents[2]
PYTHON = str(ROOT / ".venv" / "Scripts" / "python.exe")
_PLATFORM = SimpleNamespace(name=os.name)
_BASH_FIXTURE_ROOT = None
_NATIVE_FIXTURE_ROOT = None
_FIXTURE_ROOT_IDENTITY = None
_BASH_CAPABILITY_IDENTITY = None
_BASH_CAPABILITY_PATH = None
_BASH_CAPABILITY_ROOT = None
EXPECTED_COMMIT = release._git("rev-parse", "HEAD")
SYNTHETIC_OPENROUTER_TOKEN = "sk-or-v1-" + ("1" * 20)
SYNTHETIC_OPENROUTER_SUFFIX = "1" * 20
SYNTHETIC_OPENAI_TOKEN = "openai-" + ("1" * 24)


class BashProcessIdentityAbsent(RuntimeError):
    """The checked Bash identity is verified absent."""


class BashProcessIdentityReadError(RuntimeError):
    """The checked Bash identity could not be read authoritatively."""


class BashProcessHandleTimeout(RuntimeError):
    """The exact Bash process handle did not signal before the finite bound."""


class PidSubclass(int):
    """A non-canonical integer value used to test strict PID boundaries."""


def _mutate_release_hook_argv_zero(identity):
    identity["argv"][0] = "C:/tools/python.exe"
    identity["native_command"] = " ".join(identity["argv"])
    identity["argv_sha256"] = hashlib.sha256("\0".join(identity["argv"]).encode()).hexdigest()
    identity["native_command_sha256"] = hashlib.sha256(
        identity["native_command"].encode()
    ).hexdigest()


@pytest.mark.parametrize(
    "origin",
    [
        "https://github.com/aayushman-singh/ufdr-analyzer.git",
        "https://github.com/aayushman-singh/ufdr-analyzer",
        "git@github.com:aayushman-singh/ufdr-analyzer.git",
    ],
)
def test_repository_origin_normalizes_only_to_authorized_identity(origin):
    assert release._normalize_repository_origin(origin) == "aayushman-singh/ufdr-analyzer"


@pytest.mark.parametrize(
    "origin",
    [
        "https://github.com/other-owner/ufdr-analyzer.git",
        "https://github.com/aayushman-singh/other-repository.git",
        "https://gitlab.com/aayushman-singh/ufdr-analyzer.git",
        "https://user:secret@github.com/aayushman-singh/ufdr-analyzer.git",
        "https://github.com/aayushman-singh/ufdr-analyzer.git?token=secret",
        "C:/other/repository",
    ],
)
def test_repository_origin_rejects_wrong_or_credential_bearing_values(origin):
    with pytest.raises(ValueError, match="repository origin"):
        release._normalize_repository_origin(origin)


def test_deployment_verifies_origin_and_origin_main_before_checkout_or_candidate_mutation():
    command = release._deployment_command(valid_payload())
    origin_check = command.index("verified_origin=")
    fetch = command.index("fetch --prune origin main")
    checkout = command.index("checkout --detach")
    candidate = command.index("candidate_suffix=")
    assert origin_check < fetch < checkout < candidate
    assert "remote.origin.url" in command
    assert "refs/remotes/origin/main" in command
    assert "CITESPAN_ORIGIN_URL" in command


def test_origin_validation_failure_does_not_include_the_remote_value():
    script = release._remote_origin_check_script()
    assert "print(value)" not in script
    with pytest.raises(ValueError):
        release._normalize_repository_origin(
            "https://user:super-secret@github.com/aayushman-singh/ufdr-analyzer.git"
        )


def _git_bash_executable() -> Path:
    """Resolve the Bash installed with the selected Git executable."""
    git_value = shutil.which("git.exe") or shutil.which("git")
    if not git_value:
        raise RuntimeError("supported Git Bash executable is not available: Git executable is not installed")

    git_path = Path(git_value).resolve()
    git_root = git_path.parent.parent
    candidate = git_root / "usr" / "bin" / "bash.exe"
    if not candidate.is_file():
        raise RuntimeError(
            "supported Git Bash executable is not available: "
            f"Git executable={git_path} expected Bash={candidate}"
        )

    try:
        probe = subprocess.run(
            [
                str(candidate),
                "-c",
                "set -Eeuo pipefail; command -v cygpath >/dev/null; test -r \"$(cygpath -w \"$1\")\"",
                "bash",
                str(Path(tempfile.gettempdir()).resolve()),
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "supported Git Bash executable capability check timed out: "
            f"Git executable={git_path} Bash={candidate} timeout={exc.timeout}s"
        ) from exc
    except OSError as exc:
        raise RuntimeError(
            "supported Git Bash executable could not start capability check: "
            f"Git executable={git_path} Bash={candidate} error={exc}"
        ) from exc
    if probe.returncode != 0:
        raise RuntimeError(
            "supported Git Bash executable failed capability check: "
            f"Git executable={git_path} Bash={candidate} returncode={probe.returncode} "
            f"stdout={probe.stdout[-2000:]} stderr={probe.stderr[-2000:]}"
        )
    return candidate


def _git_bash_path() -> Path:
    """Resolve the selected Git Bash path without launching a process."""
    git_value = shutil.which("git.exe") or shutil.which("git")
    if not git_value:
        raise RuntimeError("supported Git Bash executable is not available: Git executable is not installed")
    git_path = Path(git_value).resolve()
    candidate = git_path.parent.parent / "usr" / "bin" / "bash.exe"
    if not candidate.is_file():
        raise RuntimeError(
            "supported Git Bash executable is not available: "
            f"Git executable={git_path} expected Bash={candidate}"
        )
    return candidate


def _windows_creation_token(pid):
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
        raise RuntimeError(
            f"exact Bash fixture identity read failed for pid {pid}: WinError {ctypes.get_last_error()}"
        )
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
            raise RuntimeError(
                f"exact Bash fixture identity read failed for pid {pid}: WinError {ctypes.get_last_error()}"
            )
        return str((creation.high << 32) | creation.low)
    finally:
        kernel32.CloseHandle(handle)


def _windows_creation_token_from_handle(kernel32, handle, pid):
    class FileTime(ctypes.Structure):
        _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]

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
        raise BashProcessIdentityReadError(
            f"exact Bash handle creation read failed for pid {pid}: "
            f"WinError {ctypes.get_last_error()}"
        )
    return str((creation.high << 32) | creation.low)


class _WindowsBashProcessHandle:
    def __init__(self, kernel32, handle, pid, creation):
        self._kernel32 = kernel32
        self._handle = handle
        self.pid = pid
        self.creation = creation

    def terminate_and_wait(self, timeout):
        if not self._kernel32.TerminateProcess(self._handle, 1):
            raise RuntimeError(
                f"exact Bash handle termination failed for pid {self.pid}: "
                f"WinError {ctypes.get_last_error()}"
            )
        wait_result = self._kernel32.WaitForSingleObject(
            self._handle, max(1, int(timeout * 1000))
        )
        if wait_result == 0x102:
            raise BashProcessHandleTimeout(
                f"exact Bash handle wait timed out for pid {self.pid}: timeout={timeout}s"
            )
        if wait_result != 0:
            raise RuntimeError(
                f"exact Bash handle wait failed for pid {self.pid}: result={wait_result} "
                f"WinError {ctypes.get_last_error()}"
            )

    def close(self):
        if self._handle:
            handle = self._handle
            self._handle = None
            if not self._kernel32.CloseHandle(handle):
                raise RuntimeError(
                    f"exact Bash handle close failed for pid {self.pid}: "
                    f"WinError {ctypes.get_last_error()}"
                )


def _open_bash_process_handle(item):
    if _PLATFORM.name != "nt":
        raise RuntimeError("native Bash process handles are only available on Windows")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.GetProcessTimes.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    kernel32.GetProcessTimes.restype = ctypes.c_int
    kernel32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.TerminateProcess.restype = ctypes.c_int
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    rights = 0x0001 | 0x1000 | 0x100000
    handle = kernel32.OpenProcess(rights, 0, item["pid"])
    if not handle:
        error = ctypes.get_last_error()
        if error in (6, 87, 1168):
            raise BashProcessIdentityAbsent(
                f"exact Bash process absent while opening handle for pid {item['pid']}"
            )
        raise BashProcessIdentityReadError(
            f"exact Bash process handle access failed for pid {item['pid']}: WinError {error}"
        )
    try:
        creation = _windows_creation_token_from_handle(kernel32, handle, item["pid"])
        return _WindowsBashProcessHandle(kernel32, handle, item["pid"], creation)
    except BaseException:
        kernel32.CloseHandle(handle)
        raise


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


def _bash_process_metadata(pid):
    if _PLATFORM.name != "nt":
        proc_root = Path("/proc") / str(pid)
        fields = (proc_root / "stat").read_text(encoding="utf-8").split()
        return {
            "pid": pid,
            "parent_pid": int(fields[3]),
            "creation": fields[21],
            "executable": str((proc_root / "exe").resolve()),
            "command": (proc_root / "cmdline").read_bytes().replace(b"\x00", b" ").decode(errors="replace").strip(),
            "cwd": str((proc_root / "cwd").resolve()),
        }
    command = (
        "$p = Get-CimInstance Win32_Process -Filter 'ProcessId = "
        f"{pid}'; if ($null -eq $p) {{ exit 3 }}; $p | Select-Object "
        "ProcessId,ParentProcessId,ExecutablePath,CommandLine | ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        if result.returncode == 3:
            raise BashProcessIdentityAbsent(f"Bash fixture identity absent for pid {pid}")
        raise BashProcessIdentityReadError(
            f"Bash fixture identity lookup failed for pid {pid}: rc={result.returncode} "
            f"stdout={result.stdout[-2000:]} stderr={result.stderr[-2000:]}"
        )
    try:
        value = json.loads(result.stdout)
    except (TypeError, ValueError) as exc:
        raise BashProcessIdentityReadError(
            f"Bash fixture identity lookup returned malformed output for pid {pid}: "
            f"{result.stdout[-2000:]}"
        ) from exc
    if not isinstance(value, dict):
        raise BashProcessIdentityReadError(
            f"Bash fixture identity lookup returned non-object output for pid {pid}"
        )
    required = ("ProcessId", "ParentProcessId", "ExecutablePath", "CommandLine")
    if any(field not in value for field in required):
        raise BashProcessIdentityReadError(
            f"Bash fixture identity lookup omitted required fields for pid {pid}"
        )
    try:
        return {
            "pid": int(value["ProcessId"]),
            "parent_pid": int(value["ParentProcessId"]),
            "creation": _windows_creation_token(pid),
            "executable": str(value.get("ExecutablePath") or ""),
            "command": str(value.get("CommandLine") or ""),
            "cwd": _windows_current_working_directory(pid),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise BashProcessIdentityReadError(
            f"Bash fixture identity lookup returned invalid fields for pid {pid}"
        ) from exc


def _windows_command_line_argv(command):
    if _PLATFORM.name != "nt":
        raise RuntimeError("Windows command-line parsing requested on a non-Windows host")
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.CommandLineToArgvW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    count = ctypes.c_int()
    values = shell32.CommandLineToArgvW(command, ctypes.byref(count))
    if not values:
        raise RuntimeError(f"Windows command-line parsing failed: WinError {ctypes.get_last_error()}")
    try:
        return [values[index] for index in range(count.value)]
    finally:
        ctypes.windll.kernel32.LocalFree(values)


def _bash_pid_exists(pid):
    if _PLATFORM.name != "nt":
        return (Path("/proc") / str(pid)).exists()
    command = f"$p = Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}'; if ($null -eq $p) {{ exit 3 }}"
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 3:
        return False
    raise RuntimeError(
        f"Bash fixture existence lookup failed for pid {pid}: rc={result.returncode} "
        f"stdout={result.stdout[-2000:]} stderr={result.stderr[-2000:]}"
    )


def _bash_process_tree(root_pid, *, terminal_pids=None):
    terminal_pids = set(terminal_pids or ())
    if _PLATFORM.name == "nt":
        command = (
            "Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,"
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
                f"Bash fixture tree lookup failed: rc={result.returncode} stdout={result.stdout[-2000:]} "
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
                    f"Bash fixture tree lookup failed: selected pid {parent_pid} is missing from the parent graph"
                )
            selected.append(current)
            pending.extend(
                item["pid"] for item in process_graph.values() if item["parent_pid"] == parent_pid
            )
        metadata = {}
        for item in selected:
            try:
                metadata[item["pid"]] = {
                    **item,
                    "cwd": _windows_current_working_directory(item["pid"]),
                    "creation": _windows_creation_token(item["pid"]),
                }
            except RuntimeError:
                if item["pid"] in terminal_pids:
                    continue
                raise
    else:
        process_graph = {}
        for entry in Path("/proc").iterdir():
            if entry.name.isdigit():
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
                    f"Bash fixture tree lookup failed: selected pid {parent_pid} is missing from the parent graph"
                )
            selected.append(current)
            pending.extend(
                item["pid"] for item in process_graph.values() if item["parent_pid"] == parent_pid
            )
        metadata = {item["pid"]: _bash_process_metadata(item["pid"]) for item in selected}
    tree = []
    pending = [root_pid]
    while pending:
        parent = pending.pop()
        current = metadata[parent]
        current = dict(current)
        tree.append(current)
        pending.extend(item["pid"] for item in metadata.values() if item["parent_pid"] == parent)
    return tree


def _bash_canonical_path(path):
    value = str(path or "")
    if not value:
        return ""
    return os.path.normcase(os.path.normpath(value)).casefold() if _PLATFORM.name == "nt" else value


def _bash_command_contains_path(command, path):
    normalized_command = str(command or "").replace("/", "\\").casefold()
    normalized_path = _bash_canonical_path(path).replace("/", "\\")
    return re.search(
        rf"(?<![a-z0-9_.\\/-]){re.escape(normalized_path)}(?![a-z0-9_.\\/-])",
        normalized_command,
    ) is not None


def _assert_owned_bash_tree(process):
    owner = process._citespan_bash_owner
    terminal_pids = owner.setdefault("terminal_pids", set())
    for item in owner["tree"]:
        if item["pid"] == process.pid or item["pid"] in terminal_pids:
            continue
        try:
            _bash_process_metadata(item["pid"])
        except BashProcessIdentityAbsent:
            terminal_pids.add(item["pid"])
            continue
        except BashProcessIdentityReadError as exc:
            raise RuntimeError(
                f"owned Bash fixture cleanup denied: identity census unreadable "
                f"pid={item['pid']}: {exc}"
            ) from exc
    current = _bash_process_tree(process.pid, terminal_pids=terminal_pids)
    if not current or current[0]["pid"] != process.pid:
        raise RuntimeError(f"owned Bash fixture cleanup denied: root {process.pid} is not current")
    recorded = {item["pid"]: item for item in owner["tree"]}
    for item in current:
        expected = recorded.get(item["pid"])
        if expected is None or item["creation"] != expected["creation"]:
            raise RuntimeError(
                f"owned Bash fixture cleanup denied: unrecorded or changed process identity current={item}"
            )
        if not item["executable"]:
            raise RuntimeError(f"owned Bash fixture cleanup denied: executable is unavailable current={item}")
        if not item["cwd"]:
            raise RuntimeError(f"owned Bash fixture cleanup denied: worktree is unavailable current={item}")
        if _bash_canonical_path(item["cwd"]) != owner["cwd"]:
            raise RuntimeError(f"owned Bash fixture cleanup denied: worktree changed current={item}")
        if not item["command"]:
            raise RuntimeError(f"owned Bash fixture cleanup denied: missing command identity current={item}")
    root_argv = _windows_command_line_argv(current[0]["command"]) if _PLATFORM.name == "nt" else current[0]["command"].split()
    expected_root_tail = owner["wrapper_argv"]
    if _PLATFORM.name == "nt":
        root_argv = root_argv[1:]
    if root_argv[-len(expected_root_tail) :] != expected_root_tail:
        raise RuntimeError(
            f"owned Bash fixture cleanup denied: root command changed expected={owner['argv']} current={current[0]}"
        )
    if not current[0]["cwd"]:
        raise RuntimeError(f"owned Bash fixture cleanup denied: root worktree is unavailable current={current[0]}")
    if _PLATFORM.name == "nt" and owner["marker"] not in current[0]["command"]:
        raise RuntimeError(f"owned Bash fixture cleanup denied: owner marker is absent current={current[0]}")
    return current


def _assert_bash_identities_stopped(recorded):
    terminal_states = []
    for item in recorded:
        try:
            current = _bash_process_metadata(item["pid"])
        except BashProcessIdentityAbsent:
            terminal_states.append(
                {"pid": item["pid"], "state": "verified_absent", "creation": item["creation"]}
            )
            continue
        except BashProcessIdentityReadError as exc:
            raise RuntimeError(f"owned Bash fixture cleanup failed: cannot prove stopped identity {item}: {exc}") from exc
        if current["creation"] == item["creation"]:
            raise RuntimeError(f"owned Bash fixture cleanup failed: recorded identity remains active: {current}")
        terminal_states.append(
            {
                "pid": item["pid"],
                "state": "pid_reused_after_exit",
                "creation": item["creation"],
                "current_creation": current["creation"],
                "current_identity": {
                    field: current.get(field)
                    for field in ("pid", "creation", "executable", "command", "cwd", "parent_pid")
                },
            }
        )
    return terminal_states


def _stop_verified_bash_identities(recorded, timeout):
    """Stop each revalidated Bash identity without an implicit PID tree walk."""
    terminal_states = []
    for item in reversed(recorded):
        try:
            current = _bash_process_metadata(item["pid"])
        except BashProcessIdentityAbsent:
            terminal_states.append(
                {"pid": item["pid"], "state": "already_exited", "creation": item["creation"]}
            )
            continue
        except BashProcessIdentityReadError as exc:
            raise RuntimeError(
                f"owned Bash fixture cleanup denied: identity census unreadable "
                f"pid={item['pid']}: {exc}"
            ) from exc
        for field in ("creation", "executable", "command", "cwd", "parent_pid"):
            if current.get(field) != item.get(field):
                raise RuntimeError(
                    "owned Bash fixture cleanup denied: identity changed before stop "
                    f"pid={item['pid']} field={field} expected={item.get(field)!r} "
                    f"current={current.get(field)!r}"
                )
        if _PLATFORM.name == "nt":
            try:
                handle = _open_bash_process_handle(item)
            except BashProcessIdentityAbsent:
                try:
                    replacement = _bash_process_metadata(item["pid"])
                except BashProcessIdentityAbsent:
                    terminal_states.append(
                        {"pid": item["pid"], "state": "already_exited", "creation": item["creation"]}
                    )
                    continue
                except BashProcessIdentityReadError as exc:
                    raise RuntimeError(
                        f"owned Bash fixture cleanup denied: post-open absence census unreadable "
                        f"pid={item['pid']}: {exc}"
                    ) from exc
                raise RuntimeError(
                    "owned Bash fixture cleanup denied: PID was reused while opening exact handle "
                    f"recorded={item} current={replacement}"
                )
            try:
                if handle.creation != item["creation"]:
                    raise RuntimeError(
                        "owned Bash fixture cleanup denied: PID was reused before exact handle validation "
                        f"recorded={item} handle_creation={handle.creation}"
                    )
                started_at = time.monotonic()
                try:
                    handle.terminate_and_wait(timeout)
                except BashProcessHandleTimeout as exc:
                    elapsed = time.monotonic() - started_at
                    raise RuntimeError(
                        "owned Bash fixture cleanup failed: exact handle wait timed out "
                        f"pid={item['pid']} timeout={timeout}s elapsed={elapsed:.6f}s "
                        f"recorded={item}"
                    ) from exc
            finally:
                handle.close()
            try:
                current = _bash_process_metadata(item["pid"])
            except BashProcessIdentityAbsent:
                terminal_states.append(
                    {"pid": item["pid"], "state": "stopped_exact_handle", "creation": item["creation"]}
                )
            except BashProcessIdentityReadError as exc:
                raise RuntimeError(
                    f"owned Bash fixture cleanup failed: post-stop identity census unreadable "
                    f"pid={item['pid']}: {exc}"
                ) from exc
            else:
                if current["creation"] == item["creation"]:
                    raise RuntimeError(
                        f"owned Bash fixture cleanup failed: exact process remains active: {current}"
                    )
                terminal_states.append(
                    {
                        "pid": item["pid"],
                        "state": "stopped_exact_handle_pid_reused",
                        "creation": item["creation"],
                        "current_creation": current["creation"],
                    }
                )
        else:
            raise RuntimeError(
                "owned Bash fixture cleanup denied: exact native process handles "
                "are required for verified termination"
            )
    if _PLATFORM.name == "nt":
        return terminal_states
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            _assert_bash_identities_stopped(recorded)
            return terminal_states
        except RuntimeError:
            time.sleep(0.05)
    _assert_bash_identities_stopped(recorded)
    return terminal_states


def test_bash_cleanup_accepts_authoritatively_absent_recorded_child(monkeypatch):
    identity = {
        "pid": 124,
        "creation": "child",
        "executable": "bash.exe",
        "command": "bash child.sh",
        "cwd": str(ROOT),
        "parent_pid": 123,
    }
    monkeypatch.setattr(
        sys.modules[__name__],
        "_bash_process_metadata",
        lambda _pid: (_ for _ in ()).throw(BashProcessIdentityAbsent("verified absent")),
    )
    monkeypatch.setattr(os, "kill", lambda *_args: pytest.fail("absent Bash PID must not be stopped"))

    assert _stop_verified_bash_identities([identity], 1) == [
        {"pid": 124, "state": "already_exited", "creation": "child"}
    ]


def test_bash_cleanup_accepts_authoritatively_absent_recorded_root(monkeypatch):
    identity = {
        "pid": 123,
        "creation": "root",
        "executable": "bash.exe",
        "command": "bash root.sh",
        "cwd": str(ROOT),
        "parent_pid": 1,
    }
    monkeypatch.setattr(
        sys.modules[__name__],
        "_bash_process_metadata",
        lambda _pid: (_ for _ in ()).throw(BashProcessIdentityAbsent("verified absent")),
    )

    assert _stop_verified_bash_identities([identity], 1) == [
        {"pid": 123, "state": "already_exited", "creation": "root"}
    ]


def test_bash_cleanup_rejects_pid_reuse_after_natural_exit(monkeypatch):
    identity = {
        "pid": 124,
        "creation": "child",
        "executable": "bash.exe",
        "command": "bash child.sh",
        "cwd": str(ROOT),
        "parent_pid": 123,
    }
    replacement = {**identity, "creation": "replacement"}
    observations = iter([identity, replacement])

    def metadata(_pid):
        observation = next(observations, replacement)
        if isinstance(observation, BaseException):
            raise observation
        return observation

    monkeypatch.setattr(sys.modules[__name__], "_bash_process_metadata", metadata)
    handle = SimpleNamespace(creation="replacement", close=lambda: None)
    monkeypatch.setattr(sys.modules[__name__], "_open_bash_process_handle", lambda _item: handle)

    with pytest.raises(RuntimeError, match="reused before exact handle validation"):
        _stop_verified_bash_identities([identity], 1)


def test_bash_cleanup_rejects_pid_reuse_after_handle_open_without_stopping_replacement(monkeypatch):
    identity = {
        "pid": 124,
        "creation": "child",
        "executable": "bash.exe",
        "command": "bash child.sh",
        "cwd": str(ROOT),
        "parent_pid": 123,
    }
    replacement = {**identity, "creation": "replacement"}
    stopped = []

    class Handle:
        creation = "child"

        def terminate_and_wait(self, _timeout):
            stopped.append("child")

        def close(self):
            stopped.append("closed")

    observations = iter([identity, replacement])
    monkeypatch.setattr(sys.modules[__name__], "_bash_process_metadata", lambda _pid: next(observations))
    monkeypatch.setattr(sys.modules[__name__], "_open_bash_process_handle", lambda _item: Handle())

    assert _stop_verified_bash_identities([identity], 1) == [
        {
            "pid": 124,
            "state": "stopped_exact_handle_pid_reused",
            "creation": "child",
            "current_creation": "replacement",
        }
    ]
    assert stopped == ["child", "closed"]


def test_bash_cleanup_rejects_unreadable_handle_creation(monkeypatch):
    identity = {
        "pid": 124,
        "creation": "child",
        "executable": "bash.exe",
        "command": "bash child.sh",
        "cwd": str(ROOT),
        "parent_pid": 123,
    }
    monkeypatch.setattr(sys.modules[__name__], "_bash_process_metadata", lambda _pid: identity)
    monkeypatch.setattr(
        sys.modules[__name__],
        "_open_bash_process_handle",
        lambda _item: (_ for _ in ()).throw(BashProcessIdentityReadError("creation time unreadable")),
    )

    with pytest.raises(BashProcessIdentityReadError, match="creation time unreadable"):
        _stop_verified_bash_identities([identity], 1)


def test_bash_cleanup_rejects_handle_access_denial(monkeypatch):
    identity = {
        "pid": 124,
        "creation": "child",
        "executable": "bash.exe",
        "command": "bash child.sh",
        "cwd": str(ROOT),
        "parent_pid": 123,
    }
    monkeypatch.setattr(sys.modules[__name__], "_bash_process_metadata", lambda _pid: identity)
    monkeypatch.setattr(
        sys.modules[__name__],
        "_open_bash_process_handle",
        lambda _item: (_ for _ in ()).throw(BashProcessIdentityReadError("access denied")),
    )

    with pytest.raises(BashProcessIdentityReadError, match="access denied"):
        _stop_verified_bash_identities([identity], 1)


def test_bash_cleanup_closes_handle_after_exact_wait_timeout(monkeypatch):
    identity = {
        "pid": 124,
        "creation": "child",
        "executable": "bash.exe",
        "command": "bash child.sh",
        "cwd": str(ROOT),
        "parent_pid": 123,
    }
    closed = []

    class Handle:
        creation = "child"

        def terminate_and_wait(self, _timeout):
            raise BashProcessHandleTimeout("wait timed out")

        def close(self):
            closed.append(True)

    monkeypatch.setattr(sys.modules[__name__], "_bash_process_metadata", lambda _pid: identity)
    monkeypatch.setattr(sys.modules[__name__], "_open_bash_process_handle", lambda _item: Handle())

    with pytest.raises(RuntimeError, match="exact handle wait timed out"):
        _stop_verified_bash_identities([identity], 1)
    assert closed == [True]


def test_bash_cleanup_terminates_and_verifies_exact_creation_token(monkeypatch):
    identity = {
        "pid": 124,
        "creation": "child",
        "executable": "bash.exe",
        "command": "bash child.sh",
        "cwd": str(ROOT),
        "parent_pid": 123,
    }
    stopped = []

    class Handle:
        creation = "child"

        def terminate_and_wait(self, timeout):
            stopped.append(timeout)

        def close(self):
            stopped.append("closed")

    observations = iter([identity, BashProcessIdentityAbsent("exited")])

    def metadata(_pid):
        observation = next(observations)
        if isinstance(observation, BaseException):
            raise observation
        return observation

    monkeypatch.setattr(sys.modules[__name__], "_bash_process_metadata", metadata)
    monkeypatch.setattr(sys.modules[__name__], "_open_bash_process_handle", lambda _item: Handle())

    assert _stop_verified_bash_identities([identity], 3) == [
        {"pid": 124, "state": "stopped_exact_handle", "creation": "child"}
    ]
    assert stopped == [3, "closed"]


def test_bash_cleanup_rejects_unreadable_census(monkeypatch):
    identity = {
        "pid": 123,
        "creation": "root",
        "executable": "bash.exe",
        "command": "bash root.sh",
        "cwd": str(ROOT),
        "parent_pid": 1,
    }
    monkeypatch.setattr(
        sys.modules[__name__],
        "_bash_process_metadata",
        lambda _pid: (_ for _ in ()).throw(BashProcessIdentityReadError("access denied")),
    )

    with pytest.raises(RuntimeError, match="identity census unreadable.*access denied"):
        _stop_verified_bash_identities([identity], 1)


def test_bash_process_metadata_rejects_malformed_output(monkeypatch):
    result = SimpleNamespace(returncode=0, stdout="not-json", stderr="")
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: result)

    with pytest.raises(BashProcessIdentityReadError, match="malformed output"):
        _bash_process_metadata(123)


def _run_owned_bash_fixture(argv, *, cwd, env, timeout=20):
    """Run one fixture process with a proved, fully reaped owned tree."""
    stdout_fd, stdout_name = tempfile.mkstemp(prefix="citespan-bash-", suffix=".stdout.log")
    stderr_fd, stderr_name = tempfile.mkstemp(prefix="citespan-bash-", suffix=".stderr.log")
    os.close(stdout_fd)
    os.close(stderr_fd)
    stdout_path = Path(stdout_name)
    stderr_path = Path(stderr_name)
    stdout_file = stdout_path.open("wb")
    stderr_file = stderr_path.open("wb")
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if _PLATFORM.name == "nt" else 0
    process = None
    launch_env = env.copy()
    marker = uuid.uuid4().hex
    launch_env["CITESPAN_TEST_PROCESS_OWNER"] = marker
    wrapper_fd, wrapper_name = tempfile.mkstemp(prefix="citespan-bash-wrapper-", suffix=".sh")
    os.close(wrapper_fd)
    wrapper_path = Path(wrapper_name)
    wrapper_path.write_text(
        "#!/usr/bin/env bash\n"
        "owner_marker=\"$1\"; shift\n"
        "if [[ -z \"$owner_marker\" || \"$owner_marker\" != \"$CITESPAN_TEST_PROCESS_OWNER\" ]]; then exit 97; fi\n"
        "IFS= read -r release || exit 98\n"
        "[[ \"$release\" == release ]] || exit 99\n"
        "\"$@\" & child=$!\n"
        "wait \"$child\"\n"
        "status=$?\n"
        "exit \"$status\"\n",
        encoding="utf-8",
    )
    launch_argv = [str(item) for item in argv]
    expected_cwd = _bash_canonical_path(Path(cwd).resolve())
    if _PLATFORM.name == "nt":
        launch_argv = [launch_argv[0], _bash_path(wrapper_path), marker, *launch_argv]
    else:
        launch_argv = [launch_argv[0], str(wrapper_path), marker, *launch_argv]
    try:
        process = subprocess.Popen(
            launch_argv,
            cwd=cwd,
            env=launch_env,
            stdin=subprocess.PIPE,
            stdout=stdout_file,
            stderr=stderr_file,
            creationflags=creationflags,
        start_new_session=_PLATFORM.name != "nt",
        )
        stdout_file.close()
        stderr_file.close()
        tree = _bash_process_tree(process.pid)
        if not tree or tree[0]["pid"] != process.pid:
            raise RuntimeError(f"owned Bash fixture launch failed: root identity was not captured pid={process.pid}")
        process._citespan_bash_owner = {
            "argv": [str(item) for item in argv],
            "cwd": expected_cwd,
            "marker": marker,
            "wrapper": _bash_path(wrapper_path) if _PLATFORM.name == "nt" else str(wrapper_path),
            "wrapper_argv": [
                _bash_path(wrapper_path) if _PLATFORM.name == "nt" else str(wrapper_path),
                marker,
                *[str(item) for item in argv],
            ],
            "tree": tree,
        }
        _assert_owned_bash_tree(process)
        process.stdin.write(b"release\n")
        process.stdin.flush()
        process._citespan_bash_owner["released"] = True
        process._citespan_bash_owner["tree"] = _bash_process_tree(
            process.pid, terminal_pids=process._citespan_bash_owner["terminal_pids"]
        )
        _assert_owned_bash_tree(process)
        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            _assert_owned_bash_tree(process)
            try:
                _stop_verified_bash_identities(process._citespan_bash_owner["tree"], 10)
            except Exception as cleanup_exc:
                raise RuntimeError(
                    f"owned Bash fixture cleanup failed after full tree proof: pid={process.pid} "
                    f"stdout_path={stdout_path} stderr_path={stderr_path}: {cleanup_exc}"
                ) from exc
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired as cleanup_exc:
                raise RuntimeError(
                    f"owned Bash fixture did not terminate: pid={process.pid} "
                    f"stdout_path={stdout_path} stderr_path={stderr_path}"
                ) from cleanup_exc
            _assert_bash_identities_stopped(process._citespan_bash_owner["tree"])
            stdout = stdout_path.read_text(encoding="utf-8", errors="replace")[-4000:]
            stderr = stderr_path.read_text(encoding="utf-8", errors="replace")[-4000:]
            raise RuntimeError(
                f"owned Bash fixture timed out: pid={process.pid} timeout={timeout}s "
                f"stdout={stdout} stderr={stderr} stdout_path={stdout_path} stderr_path={stderr_path}"
            ) from exc
        _assert_bash_identities_stopped(process._citespan_bash_owner["tree"])
        stdout = stdout_path.read_text(encoding="utf-8", errors="replace")
        stderr = stderr_path.read_text(encoding="utf-8", errors="replace")
        stdout_path.unlink()
        stderr_path.unlink()
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)
    except Exception as exc:
        if process is not None and process.poll() is None:
            raise RuntimeError(
                f"owned Bash fixture failed with live process; output paths retained: "
                f"stdout_path={stdout_path} stderr_path={stderr_path}; error={exc}"
            ) from exc
        cleanup_errors = []
        for path in (stdout_path, stderr_path):
            try:
                content = path.read_text(encoding="utf-8", errors="replace")[-4000:]
            except OSError as cleanup_error:
                cleanup_errors.append(f"path={path} read_error={cleanup_error}")
            else:
                cleanup_errors.append(f"path={path} retained_output={content}")
        raise RuntimeError(
            f"owned Bash fixture failed: primary={exc}; output cleanup errors={'; '.join(cleanup_errors)}; "
            f"stdout_path_retained={stdout_path} stderr_path_retained={stderr_path}"
        ) from exc
    finally:
        if not stdout_file.closed:
            stdout_file.close()
        if not stderr_file.closed:
            stderr_file.close()
        if process is not None and process.stdin is not None and not process.stdin.closed:
            process.stdin.close()
        if process is None or process.poll() is not None:
            wrapper_path.unlink(missing_ok=True)


def _bash_path(path: Path) -> str:
    """Convert a native path only when it enters a Bash command."""
    resolved_path = path.resolve()
    if _NATIVE_FIXTURE_ROOT is not None:
        fixture_root = _NATIVE_FIXTURE_ROOT
        if resolved_path == fixture_root or fixture_root in resolved_path.parents:
            relative_path = resolved_path.relative_to(fixture_root)
            return PurePosixPath(
                _BASH_FIXTURE_ROOT, *relative_path.parts
            ).as_posix()
    result = subprocess.run(
        [str(_git_bash_executable()), "-lc", 'cygpath -u "$1"', "bash", str(resolved_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _native_fixture_path(bash_path: str) -> Path:
    """Map a Bash fixture path through the verified session root only."""
    if _BASH_FIXTURE_ROOT is None or _NATIVE_FIXTURE_ROOT is None:
        raise RuntimeError("fixture root is not initialized")
    bash_root = PurePosixPath(_BASH_FIXTURE_ROOT)
    candidate = PurePosixPath(bash_path)
    try:
        relative_path = candidate.relative_to(bash_root)
    except ValueError as exc:
        raise RuntimeError(f"fixture path escapes the verified root: {bash_path}") from exc
    if any(part in {"", ".", ".."} for part in relative_path.parts):
        raise RuntimeError(f"fixture path is not normalized: {bash_path}")
    native_path = (_NATIVE_FIXTURE_ROOT / Path(*relative_path.parts)).resolve(strict=False)
    if native_path != _NATIVE_FIXTURE_ROOT and _NATIVE_FIXTURE_ROOT not in native_path.parents:
        raise RuntimeError(f"fixture path escapes the verified root: {bash_path}")
    return native_path


def _bash_writable_temp_root() -> Path:
    """Return the checked session root for all Bash and Python fixtures."""
    global _BASH_FIXTURE_ROOT, _NATIVE_FIXTURE_ROOT, _FIXTURE_ROOT_IDENTITY

    if _NATIVE_FIXTURE_ROOT is not None:
        _fixture_root_is_valid()
        return _NATIVE_FIXTURE_ROOT

    bash = _git_bash_executable()
    result = subprocess.run(
        [
            str(bash),
            "-lc",
            (
                'set -Eeuo pipefail; '
                'root="$(mktemp -d "/tmp/citespan-release-test-fixtures-XXXXXX")"; '
                'test -d "$root"; '
                'touch "$root/.citespan-write-probe"; '
                'test -r "$root/.citespan-write-probe"; '
                'rm "$root/.citespan-write-probe"; '
                'printf "%s\\n" "$root"'
            ),
            "bash",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
    )
    bash_root = result.stdout.strip()
    if not bash_root.startswith("/tmp/citespan-release-test-fixtures-"):
        raise RuntimeError(f"Git Bash returned an invalid fixture root: {bash_root!r}")

    native_result = subprocess.run(
        [str(bash), "-lc", 'cygpath -w "$1"', "bash", bash_root],
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
    )
    native_root = Path(native_result.stdout.strip()).resolve()
    if native_root == ROOT or ROOT in native_root.parents:
        raise RuntimeError(f"fixture root is inside the source checkout: {native_root}")
    if not native_root.is_dir():
        raise RuntimeError(f"Git Bash fixture root is not a directory: {native_root}")

    _BASH_FIXTURE_ROOT = bash_root
    _NATIVE_FIXTURE_ROOT = native_root
    _FIXTURE_ROOT_IDENTITY = _fixture_root_identity(native_root)
    _assert_fixture_root_access(native_root, bash_root)
    return native_root


def _fixture_root_identity(path: Path):
    try:
        stat_result = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise RuntimeError(f"fixture root identity read failed: path={path} error={exc}") from exc
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if path.is_symlink() or getattr(stat_result, "st_file_attributes", 0) & reparse_flag:
        raise RuntimeError(f"fixture root must not be a symlink or reparse point: {path}")
    return (path.resolve(), stat_result.st_dev, stat_result.st_ino)


def _assert_fixture_root_access(native_root: Path, bash_root: str) -> None:
    global _BASH_CAPABILITY_IDENTITY, _BASH_CAPABILITY_PATH, _BASH_CAPABILITY_ROOT

    identity = _fixture_root_identity(native_root)
    if identity[0] != native_root.resolve():
        raise RuntimeError(f"fixture root resolved to a different path: {native_root}")
    probe = native_root / f".citespan-python-write-probe-{uuid.uuid4().hex}"
    try:
        probe.write_text("probe", encoding="utf-8")
        if probe.read_text(encoding="utf-8") != "probe":
            raise RuntimeError(f"Python fixture root write probe returned unexpected data: {native_root}")
    except OSError as exc:
        raise RuntimeError(f"Python fixture root is not writable: path={native_root} error={exc}") from exc
    finally:
        probe.unlink(missing_ok=True)
    current_bash = _git_bash_path().resolve()
    if (
        _BASH_CAPABILITY_IDENTITY == identity
        and _BASH_CAPABILITY_PATH == current_bash
        and _BASH_CAPABILITY_ROOT == bash_root
    ):
        return
    cached_root_path = (
        _BASH_CAPABILITY_IDENTITY[0]
        if _BASH_CAPABILITY_IDENTITY is not None
        else None
    )
    if cached_root_path == identity[0] and any(
        value is not None
        for value in (
            _BASH_CAPABILITY_IDENTITY,
            _BASH_CAPABILITY_PATH,
            _BASH_CAPABILITY_ROOT,
        )
    ):
        raise RuntimeError(
            "Git Bash fixture root capability cache is no longer valid: "
            f"path={native_root} expected_identity={_BASH_CAPABILITY_IDENTITY} "
            f"observed_identity={identity} expected_bash={_BASH_CAPABILITY_PATH} "
            f"observed_bash={current_bash} expected_bash_root={_BASH_CAPABILITY_ROOT} "
            f"observed_bash_root={bash_root} ownership_context=session fixture root"
        )

    bash = _git_bash_executable()
    if bash.resolve() != current_bash:
        raise RuntimeError(
            "Git Bash fixture root capability check failed: "
            f"step=executable path={native_root} expected_bash={current_bash} "
            f"observed_bash={bash} ownership_context=session fixture root"
        )
    probe_name = f".citespan-bash-write-probe-{uuid.uuid4().hex}"
    probe_path = native_root / probe_name
    try:
        subprocess.run(
            [
                str(bash),
                "-c",
                'set -Eeuo pipefail; test -d "$1"; test -w "$1"; probe="$1/$2"; touch "$probe"; test -r "$probe"; rm "$probe"',
                "bash",
                bash_root,
                probe_name,
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        try:
            probe_path.unlink(missing_ok=True)
        except OSError as cleanup_exc:
            raise RuntimeError(
                "Git Bash fixture root capability check failed: "
                f"step=access path={native_root} expected_identity={identity} "
                f"bash={bash} bash_root={bash_root} probe={probe_name} "
                f"error={exc} cleanup_error={cleanup_exc}"
            ) from exc
        raise RuntimeError(
            "Git Bash fixture root capability check failed: "
            f"step=access path={native_root} expected_identity={identity} "
            f"bash={bash} bash_root={bash_root} probe={probe_name} error={exc}"
        ) from exc
    try:
        probe_path.unlink(missing_ok=True)
    except OSError as exc:
        raise RuntimeError(
            "Git Bash fixture root capability cleanup failed: "
            f"step=access path={native_root} expected_identity={identity} "
            f"bash={bash} bash_root={bash_root} probe={probe_name} error={exc}"
        ) from exc
    _BASH_CAPABILITY_IDENTITY = identity
    _BASH_CAPABILITY_PATH = bash.resolve()
    _BASH_CAPABILITY_ROOT = bash_root


def test_setup_bash_probes_use_non_login_shell_and_keep_failure_boundaries(tmp_path, monkeypatch):
    git_root = tmp_path / "git" / "mingw64"
    git_executable = git_root / "bin" / "git.exe"
    bash = git_root / "usr" / "bin" / "bash.exe"
    git_executable.parent.mkdir(parents=True)
    bash.parent.mkdir(parents=True)
    bash.write_bytes(b"")
    monkeypatch.setattr(shutil, "which", lambda _name: str(git_executable))
    calls = []
    git_bash_executable = _git_bash_executable

    def successful_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", successful_run)
    assert git_bash_executable() == bash
    assert calls[0][0][1] == "-c"
    assert calls[0][1]["timeout"] == 5
    assert calls[0][1]["check"] is False

    fixture_root = tmp_path / "fixture-root"
    fixture_root.mkdir()
    monkeypatch.setattr(sys.modules[__name__], "_git_bash_executable", lambda: bash)
    _assert_fixture_root_access(fixture_root, "/tmp/citespan-release-test-fixtures")
    assert calls[1][0][1] == "-c"
    assert calls[1][1]["timeout"] == 5
    assert calls[1][1]["check"] is True
    assert not (fixture_root / ".citespan-bash-write-probe").exists()

    def timed_out(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("bash capability", 5)

    monkeypatch.setattr(subprocess, "run", timed_out)
    with pytest.raises(RuntimeError, match="capability check timed out"):
        git_bash_executable()


def _fixture_root_is_valid() -> bool:
    if _NATIVE_FIXTURE_ROOT is None or _BASH_FIXTURE_ROOT is None or _FIXTURE_ROOT_IDENTITY is None:
        raise RuntimeError(
            "fixture root validation failed: step=initialized path="
            f"{_NATIVE_FIXTURE_ROOT} expected_identity={_FIXTURE_ROOT_IDENTITY} "
            "observed_identity=uninitialized ownership_context=session fixture root"
        )
    path = _NATIVE_FIXTURE_ROOT
    try:
        observed_identity = _fixture_root_identity(path)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        raise RuntimeError(
            "fixture root validation failed: step=identity path="
            f"{path} expected_identity={_FIXTURE_ROOT_IDENTITY} observed_identity=error:{exc} "
            "ownership_context=session fixture root"
        ) from exc
    if observed_identity != _FIXTURE_ROOT_IDENTITY:
        raise RuntimeError(
            "fixture root validation failed: step=identity path="
            f"{path} expected_identity={_FIXTURE_ROOT_IDENTITY} observed_identity={observed_identity} "
            "ownership_context=session fixture root"
        )
    try:
        _assert_fixture_root_access(path, _BASH_FIXTURE_ROOT)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        raise RuntimeError(
            "fixture root validation failed: step=access path="
            f"{path} expected_identity={_FIXTURE_ROOT_IDENTITY} observed_identity={observed_identity} "
            f"error={exc} ownership_context=session fixture root"
        ) from exc
    return True


def _remove_fixture_path(path: Path, label: str, *, allow_root: bool = False) -> None:
    root = path.resolve()
    fixture_root = _NATIVE_FIXTURE_ROOT.resolve() if _NATIVE_FIXTURE_ROOT is not None else None
    if not allow_root and fixture_root is not None and root == fixture_root:
        raise RuntimeError(f"{label} cleanup denied: individual fixture cannot remove shared root {root}")
    if allow_root:
        if fixture_root is None or _FIXTURE_ROOT_IDENTITY is None or root != fixture_root:
            raise RuntimeError(f"{label} cleanup denied: path is not the owned shared root {root}")
        _fixture_root_is_valid()
        children = sorted(path.iterdir(), key=lambda item: item.name)
        if children:
            raise RuntimeError(
                f"{label} cleanup denied: shared root is not empty path={root} "
                f"known_children={[str(child) for child in children]}"
            )
    elif not _fixture_root_is_valid():
        raise RuntimeError(f"{label} cleanup denied: shared fixture root is unavailable or changed")

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


@pytest.fixture(scope="session", autouse=True)
def _fixture_session():
    try:
        yield
    finally:
        root = _NATIVE_FIXTURE_ROOT
        try:
            if root is not None:
                _remove_fixture_path(root, "session fixture root", allow_root=True)
        finally:
            global _BASH_CAPABILITY_IDENTITY, _BASH_CAPABILITY_PATH, _BASH_CAPABILITY_ROOT
            _BASH_CAPABILITY_IDENTITY = None
            _BASH_CAPABILITY_PATH = None
            _BASH_CAPABILITY_ROOT = None


@pytest.fixture
def bash_tmp_path():
    path = Path(tempfile.mkdtemp(prefix="citespan-release-test-", dir=_bash_writable_temp_root()))
    try:
        yield path
    finally:
        _remove_fixture_path(path, "bash fixture")


def test_fixture_root_missing_fails_without_recreation(monkeypatch):
    parent = Path(tempfile.mkdtemp(prefix="citespan-root-missing-"))
    try:
        root = parent / "missing-root"
        monkeypatch.setattr(sys.modules[__name__], "_NATIVE_FIXTURE_ROOT", root)
        monkeypatch.setattr(sys.modules[__name__], "_BASH_FIXTURE_ROOT", "/tmp/citespan-release-test-fixtures-missing")
        monkeypatch.setattr(sys.modules[__name__], "_FIXTURE_ROOT_IDENTITY", (root.resolve(), 1, 2))

        with pytest.raises(RuntimeError, match=r"step=identity.*missing-root"):
            _bash_writable_temp_root()
        assert not root.exists()
    finally:
        shutil.rmtree(parent)


def test_fixture_root_unreadable_fails_with_access_context(monkeypatch):
    parent = Path(tempfile.mkdtemp(prefix="citespan-root-unreadable-"))
    try:
        root = parent / "unreadable-root"
        root.mkdir()
        identity = _fixture_root_identity(root)
        monkeypatch.setattr(sys.modules[__name__], "_NATIVE_FIXTURE_ROOT", root)
        monkeypatch.setattr(sys.modules[__name__], "_BASH_FIXTURE_ROOT", "/tmp/citespan-release-test-fixtures-unreadable")
        monkeypatch.setattr(sys.modules[__name__], "_FIXTURE_ROOT_IDENTITY", identity)
        monkeypatch.setattr(
            sys.modules[__name__],
            "_assert_fixture_root_access",
            lambda *_args: (_ for _ in ()).throw(PermissionError("read denied")),
        )

        with pytest.raises(RuntimeError, match=r"step=access.*read denied"):
            _fixture_root_is_valid()
    finally:
        shutil.rmtree(parent)


def test_fixture_root_identity_replacement_fails_without_switching(monkeypatch):
    parent = Path(tempfile.mkdtemp(prefix="citespan-root-replaced-"))
    try:
        root = parent / "root"
        root.mkdir()
        identity = _fixture_root_identity(root)
        shutil.rmtree(root)
        root.mkdir()
        monkeypatch.setattr(sys.modules[__name__], "_NATIVE_FIXTURE_ROOT", root)
        monkeypatch.setattr(sys.modules[__name__], "_BASH_FIXTURE_ROOT", "/tmp/citespan-release-test-fixtures-replaced")
        monkeypatch.setattr(sys.modules[__name__], "_FIXTURE_ROOT_IDENTITY", identity)

        with pytest.raises(RuntimeError, match=r"expected_identity=.*observed_identity=.*ownership_context"):
            _fixture_root_is_valid()
    finally:
        shutil.rmtree(parent)


def test_individual_fixture_cleanup_preserves_shared_root(bash_tmp_path):
    root = _bash_writable_temp_root()
    assert root.is_dir()


def test_fixture_root_access_caches_bash_capability_only_for_same_identity_and_mapping(
    tmp_path, monkeypatch
):
    root = tmp_path / "root"
    root.mkdir()
    bash = tmp_path / "bash.exe"
    bash.write_bytes(b"")
    calls = []

    monkeypatch.setattr(sys.modules[__name__], "_git_bash_path", lambda: bash)
    monkeypatch.setattr(sys.modules[__name__], "_git_bash_executable", lambda: bash)

    def successful_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", successful_run)
    _assert_fixture_root_access(root, "/tmp/citespan-release-test-fixtures")
    _assert_fixture_root_access(root, "/tmp/citespan-release-test-fixtures")
    assert len(calls) == 1

    shutil.rmtree(root)
    root.mkdir()
    with pytest.raises(RuntimeError, match="cache is no longer valid"):
        _assert_fixture_root_access(root, "/tmp/citespan-release-test-fixtures")
    assert len(calls) == 1

    replacement_bash = tmp_path / "replacement-bash.exe"
    replacement_bash.write_bytes(b"")
    monkeypatch.setattr(sys.modules[__name__], "_git_bash_path", lambda: replacement_bash)
    with pytest.raises(RuntimeError, match="cache is no longer valid"):
        _assert_fixture_root_access(root, "/tmp/citespan-release-test-fixtures")
    assert len(calls) == 1


def test_fixture_root_rejects_symlink_substitution(tmp_path, monkeypatch):
    target = tmp_path / "target"
    target.mkdir()
    substitute = tmp_path / "substitute"
    try:
        substitute.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"directory symlink is unavailable: {exc}")
    monkeypatch.setattr(sys.modules[__name__], "_NATIVE_FIXTURE_ROOT", substitute)
    monkeypatch.setattr(sys.modules[__name__], "_FIXTURE_ROOT_IDENTITY", (substitute.resolve(), 1, 1))
    monkeypatch.setattr(sys.modules[__name__], "_BASH_FIXTURE_ROOT", "/tmp/citespan-release-test-fixtures-substitute")

    with pytest.raises(RuntimeError, match="symlink or reparse"):
        _fixture_root_identity(substitute)


def test_final_fixture_cleanup_requires_exact_shared_root_ownership(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(sys.modules[__name__], "_NATIVE_FIXTURE_ROOT", root)
    monkeypatch.setattr(sys.modules[__name__], "_FIXTURE_ROOT_IDENTITY", _fixture_root_identity(root))
    monkeypatch.setattr(sys.modules[__name__], "_BASH_FIXTURE_ROOT", "/tmp/citespan-release-test-fixtures-test")
    replacement = tmp_path / "replacement"
    replacement.mkdir()

    with pytest.raises(RuntimeError, match="not the owned shared root"):
        _remove_fixture_path(replacement, "session fixture root", allow_root=True)


def test_final_fixture_cleanup_requires_empty_owned_root(monkeypatch):
    parent = Path(tempfile.mkdtemp(prefix="citespan-root-nonempty-"))
    try:
        root = parent / "root"
        root.mkdir()
        (root / "unexpected-child").mkdir()
        monkeypatch.setattr(sys.modules[__name__], "_NATIVE_FIXTURE_ROOT", root)
        monkeypatch.setattr(sys.modules[__name__], "_FIXTURE_ROOT_IDENTITY", _fixture_root_identity(root))
        monkeypatch.setattr(sys.modules[__name__], "_BASH_FIXTURE_ROOT", "/tmp/citespan-release-test-fixtures-test")
        monkeypatch.setattr(sys.modules[__name__], "_fixture_root_is_valid", lambda: True)

        with pytest.raises(RuntimeError, match="shared root is not empty"):
            _remove_fixture_path(root, "session fixture root", allow_root=True)
    finally:
        shutil.rmtree(parent)


def _rollback_fixture_state(deploy_root: Path, caddy_root: Path) -> str:
    """Build all state required by the extracted rollback function."""
    return f"""    failed_step=forced_failure
    route_active=1
    route_switched=1
    cleanup_failed=0
    cutover_committed=0
    rollback_incomplete=0
    previous_backend_running=1
    previous_static_running=1
    candidate_backend=candidate-backend
    candidate_static=candidate-static
    previous_backend=previous-backend
    previous_static=previous-static
    previous_deployment_id=citespan-previous
    deployment_id=citespan-candidate
    CITESPAN_DEPLOYMENT_ID=citespan-candidate
    previous_frontend=
    compose_override={_bash_path(deploy_root / "override.yml")}
    candidate_metadata={_bash_path(deploy_root / "candidate.json")}
    prior_metadata={_bash_path(deploy_root / ".citespan-deployment.json")}
    demo_marker={_bash_path(deploy_root / ".citespan-demo-marker.json")}
    receipt={_bash_path(deploy_root / ".citespan-authoritative-receipt.json")}
    backup_dir={_bash_path(deploy_root / "backup")}
    deployment_metadata={_bash_path(deploy_root / ".citespan-deployment.json")}
    runtime={_bash_path(deploy_root / ".citespan-runtime.env")}
    caddy_backup={_bash_path(caddy_root / "Caddyfile.backup")}
    compose='docker compose --project-name citespan-candidate'
    recovery_log={_bash_path(deploy_root / "recovery.log")}
    phase_trace={_bash_path(deploy_root / "phase-trace.log")}
    sanitize_probe_output() {{ printf '%s' "$1"; }}
    phase_failure() {{ printf 'phase=%s status=failure exit_code=%s\\n' "$1" "$2" >> "$phase_trace"; }}
    mkdir -p "$backup_dir"
    : > "$phase_trace"
    cp "$deployment_metadata" "$backup_dir/.citespan-deployment.json"
    cp {_bash_path(deploy_root / ".citespan-demo-marker.json")} "$backup_dir/.citespan-demo-marker.json"
    cp {_bash_path(deploy_root / ".citespan-runtime.env")} "$backup_dir/.citespan-runtime.env"
    cp {_bash_path(caddy_root / "Caddyfile")} "$caddy_backup"
    printf 'candidate-route\\n' > {_bash_path(caddy_root / "Caddyfile")}
    printf 'authoritative-data\\n' > {_bash_path(deploy_root / "authoritative-data.txt")}
"""


def _complete_runtime_fixture() -> str:
    return (
        "DEMO_MODE=1\n"
        "CITESPAN_SYNTHETIC_ONLY=1\n"
        "OPENAI_" + "API_KEY=\n"
        "OPENROUTER_" + "API_KEY=\n"
        "NEO4J_" + "PASSWORD=synthetic-neo4j-password\n"
        "SECRET_KEY=previous\n"
        "POSTGRES_PASSWORD=synthetic-postgres-password\n"
        "POSTGRES_USER=ufdr_user\n"
        "POSTGRES_DB=ufdr_analyzer\n"
        "MEILI_MASTER_KEY=synthetic-meili-key\n"
        "MINIO_ROOT_USER=synthetic-minio-user\n"
        "MINIO_ROOT_PASSWORD=synthetic-minio-password\n"
        "MINIO_ACCESS_KEY=synthetic-minio-user\n"
        "MINIO_SECRET_KEY=synthetic-minio-password\n"
    )


def _runtime_text(*codepoints: int) -> str:
    return "".join(chr(codepoint) for codepoint in codepoints)


def test_runtime_validation_accepts_the_complete_rotated_demo_runtime(tmp_path):
    result, _ = _run_runtime_validation(tmp_path, _complete_runtime_fixture())

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("missing_key", sorted(release.REQUIRED_RUNTIME_SECRET_KEYS))
def test_runtime_validation_rejects_each_missing_required_secret(tmp_path, missing_key):
    runtime = _complete_runtime_fixture()
    runtime = "\n".join(
        line for line in runtime.splitlines() if not line.startswith(f"{missing_key}=")
    ) + "\n"

    result, _ = _run_runtime_validation(tmp_path, runtime)

    assert result.returncode != 0
    assert "runtime" in result.stderr.lower()


def test_runtime_validation_rejects_compromised_values_without_echoing_them(tmp_path):
    compromised = _runtime_text(
        99, 111, 109, 112, 114, 111, 109, 105, 115, 101, 100, 45, 114, 117, 110, 116,
        105, 109, 101, 45, 118, 97, 108, 117, 101,
    )
    runtime = _complete_runtime_fixture().replace(
        _runtime_text(
            78, 69, 79, 52, 74, 95, 80, 65, 83, 83, 87, 79, 82, 68, 61, 115, 121, 110,
            116, 104, 101, 116, 105, 99, 45, 110, 101, 111, 52, 106, 45, 112, 97, 115,
            115, 119, 111, 114, 100,
        ),
        _runtime_text(78, 69, 79, 52, 74, 95, 80, 65, 83, 83, 87, 79, 82, 68)
        + "="
        + compromised,
    )

    result, _ = _run_runtime_validation(
        tmp_path, runtime, [hashlib.sha256(compromised.encode()).hexdigest()]
    )

    assert result.returncode != 0
    assert compromised not in result.stderr


@pytest.mark.parametrize(
    "field,value",
    [
        ("OPENAI_API_KEY", _runtime_text(101, 120, 116, 101, 114, 110, 97, 108, 45, 107, 101, 121, 45, 118, 97, 108, 117, 101)),
        ("OPENROUTER_API_KEY", _runtime_text(101, 120, 116, 101, 114, 110, 97, 108, 45, 107, 101, 121, 45, 118, 97, 108, 117, 101)),
        ("SECRET_KEY", _runtime_text(67, 72, 65, 78, 71, 69, 95, 77, 69)),
        ("POSTGRES_PASSWORD", _runtime_text(115, 104, 111, 114, 116)),
        ("MINIO_ROOT_USER", _runtime_text(99, 111, 110, 116, 97, 105, 110, 115, 32, 119, 104, 105, 116, 101, 115, 112, 97, 99, 101)),
    ],
)
def test_runtime_validation_rejects_external_keys_placeholders_and_weak_values(
    tmp_path, field, value
):
    runtime = _complete_runtime_fixture()
    lines = [
        f"{field}={value}" if line.startswith(f"{field}=") else line
        for line in runtime.splitlines()
    ]

    result, _ = _run_runtime_validation(tmp_path, "\n".join(lines) + "\n")

    assert result.returncode != 0
    assert value not in result.stderr


@pytest.mark.skipif(_PLATFORM.name != "posix", reason="runtime permissions are enforced on the remote POSIX host")
def test_runtime_validation_rejects_unsafe_permissions(tmp_path):
    runtime = tmp_path / ".citespan-runtime.env"
    runtime.write_text(_complete_runtime_fixture(), encoding="utf-8")
    runtime.chmod(0o644)

    result = subprocess.run(
        [sys.executable, "-c", release._runtime_validation_script([]), str(runtime)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "permission" in result.stderr.lower()


@pytest.mark.parametrize(
    "extra_line",
    ["EXTRA_KEY=value", "BROKEN_LINE", "SECRET_KEY=one\nSECRET_KEY=two"],
)
def test_runtime_validation_rejects_malformed_or_extra_keys(tmp_path, extra_line):
    result, _ = _run_runtime_validation(
        tmp_path, _complete_runtime_fixture().rstrip("\n") + "\n" + extra_line + "\n"
    )

    assert result.returncode != 0


def test_runtime_validation_rejects_mismatched_minio_aliases(tmp_path):
    runtime = _complete_runtime_fixture().replace(
        "MINIO_ACCESS_KEY=synthetic-minio-user", "MINIO_ACCESS_KEY=other-minio-user"
    )

    result, _ = _run_runtime_validation(tmp_path, runtime)

    assert result.returncode != 0
    assert "mismatched" in result.stderr.lower()


def _fixture_text(*codepoints: int) -> str:
    return "".join(chr(codepoint) for codepoint in codepoints)


def _neo4j_password_key() -> str:
    return _fixture_text(78, 69, 79, 52, 74, 95, 80, 65, 83, 83, 87, 79, 82, 68)


def _neo4j_password_assignment(value: str) -> str:
    return f"{_neo4j_password_key()}={value}"


@pytest.fixture
def tmp_path():
    path = Path(
        tempfile.mkdtemp(prefix="citespan-release-test-", dir=_bash_writable_temp_root())
    )
    try:
        yield path
    finally:
        _remove_fixture_path(path, "fixture")


def valid_payload(**extra):
    payload = {
        "action_key": "citespan-release",
        "intent": {"action_key": "citespan-release", "expected_commit": EXPECTED_COMMIT},
        "live_url": release.AUTHORIZED_LIVE_ORIGIN,
        "demo_run_id": "11111111-1111-4111-8111-111111111111",
        "DEMO_MODE": "1",
    }
    payload.update(extra)
    return payload


def _validated_empty_host_process_evidence():
    return {
        "root": str(release.HOST_PROCESS_EVIDENCE_ROOT),
        "historical_identities": 145,
        "native_resource": "restored",
        "fresh_census": {
            "resources": {
                "processes": [],
                "holders": [],
                "ports": [],
                "read_errors": [],
            }
        },
    }


def test_host_process_evidence_uses_only_the_fixed_private_directory(tmp_path, monkeypatch):
    evidence_root = tmp_path / "host-process-evidence"
    monkeypatch.setattr(release, "HOST_PROCESS_EVIDENCE_ROOT", evidence_root)

    with pytest.raises(RuntimeError, match="host process evidence"):
        release._validate_host_process_evidence()


def test_host_process_evidence_rejects_malformed_historical_input(tmp_path, monkeypatch):
    evidence_root = tmp_path / "host-process-evidence"
    evidence_root.mkdir()
    for filename in release.HOST_PROCESS_EVIDENCE_FILES:
        (evidence_root / filename).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(release, "HOST_PROCESS_EVIDENCE_ROOT", evidence_root)

    with pytest.raises(
        RuntimeError,
        match=r"historical host process evidence invalid recorded-node-identities-942\.json: expected a non-empty list",
    ):
        release._validate_host_process_evidence()


@pytest.mark.parametrize(
    "builder",
    [
        lambda: [{"identity": {"pid": True, "creation_token": "creation"}}],
        lambda: [{"pid": True} for _ in range(145)],
        lambda: {"observations": [{"pid": True}]},
    ],
)
def test_evidence_boundaries_reject_boolean_pids(builder):
    value = builder()
    if isinstance(value, list) and len(value) == 1 and "identity" in value[0]:
        with pytest.raises(RuntimeError, match="pid"):
            release._legacy_evidence_records(value, "recorded-node-identities-942.json")
    elif isinstance(value, list):
        document = {
            "schema": "citespan.read-only-family-observation.v1",
            "ownership_approved": False,
            "cleanup_approved": False,
            "observations": value,
        }
        with pytest.raises(RuntimeError, match="invalid identity"):
            release._legacy_family_observation_records(document, "legacy-family-current-996.json")
    else:
        with pytest.raises(RuntimeError, match="pid"):
            release._current_cleanup_observation(value, "presence.json")


def _current_frontend_evidence(**overrides):
    evidence = {
        "product_frontend_processes": [],
        "native_module_holders": [],
        "read_errors": [],
        "listening_ports": [],
    }
    evidence.update(overrides)
    return evidence


@pytest.mark.parametrize("field", ["read_errors", "listening_ports"])
def test_current_frontend_observation_rejects_missing_measured_fields(field):
    evidence = _current_frontend_evidence()
    del evidence[field]

    with pytest.raises(RuntimeError, match=rf"missing required measured fields=.*{field}"):
        release._current_frontend_observation(evidence, "current-frontend-processes-1004.json")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("read_errors", None),
        ("read_errors", [""]),
        ("read_errors", [None]),
        ("listening_ports", None),
        ("listening_ports", [0]),
        ("listening_ports", [-1]),
        ("listening_ports", ["4100"]),
        ("listening_ports", [True]),
    ],
)
def test_current_frontend_observation_rejects_malformed_measured_fields(field, value):
    with pytest.raises(RuntimeError, match=rf"{field}"):
        release._current_frontend_observation(
            _current_frontend_evidence(**{field: value}),
            "current-frontend-processes-1004.json",
        )


def test_current_frontend_observation_accepts_explicit_empty_measurements():
    assert release._current_frontend_observation(
        _current_frontend_evidence(), "current-frontend-processes-1004.json"
    ) == {"processes": [], "holders": [], "ports": []}


def _full_current_identity(pid=101):
    argv = ["node.exe", "server.js"]
    native_command = "node.exe server.js"
    return {
        "pid": pid,
        "creation": f"creation-{pid}",
        "executable": "C:/node.exe",
        "argv": argv,
        "argv_sha256": hashlib.sha256("\0".join(argv).encode()).hexdigest(),
        "native_command": native_command,
        "native_command_sha256": hashlib.sha256(native_command.encode()).hexdigest(),
        "cwd": "C:/work/frontend",
        "parent_pid": 100,
        "parent_observations": [{"pid": 100, "state": "verified_absent_historical_parent"}],
        "role": "related_test_family",
        "family_relation": release.HISTORICAL_FAMILY_RELATION,
        "read_errors": [],
        "listening_ports": [4100],
        "source_provenance": {"source": "measured-test-input"},
        "module_paths": [],
        "files": [],
        "ports": [4100],
    }


def test_current_frontend_observation_accepts_a_complete_identity_record():
    record = _full_current_identity()
    evidence = _current_frontend_evidence(product_frontend_processes=[record], listening_ports=[4100])

    result = release._current_frontend_observation(evidence, "current-frontend-processes-1004.json")

    assert result["processes"][0]["current_identity"]["creation"] == "creation-101"
    assert result["processes"][0]["current_identity"]["native_command"] == "node.exe server.js"


def test_current_frontend_observation_accepts_a_readable_native_holder_identity():
    record = _full_current_identity()
    native_path = str((release.SCRIPT_ROOT / release.HOST_NATIVE_MODULE).resolve())
    record["files"] = [native_path]
    record["module_paths"] = [native_path]
    evidence = _current_frontend_evidence(native_module_holders=[record], listening_ports=[4100])

    result = release._current_frontend_observation(evidence, "current-frontend-processes-1004.json")

    assert result["holders"][0]["current_identity"]["pid"] == 101
    assert result["holders"][0]["current_identity"]["module_paths"] == [native_path]


@pytest.mark.parametrize(
    "field",
    [
        "pid", "creation", "executable", "argv", "argv_sha256", "native_command",
        "native_command_sha256", "cwd", "parent_pid", "parent_observations",
        "role", "family_relation", "read_errors", "listening_ports", "source_provenance",
    ],
)
def test_current_frontend_observation_rejects_an_incomplete_identity_record(field):
    record = _full_current_identity()
    del record[field]

    with pytest.raises(RuntimeError, match=field):
        release._current_frontend_observation(
            _current_frontend_evidence(product_frontend_processes=[record], listening_ports=[4100]),
            "current-frontend-processes-1004.json",
        )


def test_current_frontend_observation_rejects_raw_hash_disagreement():
    record = _full_current_identity()
    record["native_command_sha256"] = "0" * 64

    with pytest.raises(RuntimeError, match="native_command_sha256"):
        release._current_frontend_observation(
            _current_frontend_evidence(product_frontend_processes=[record], listening_ports=[4100]),
            "current-frontend-processes-1004.json",
        )


@pytest.mark.parametrize("field", ["creation", "executable", "argv", "cwd", "parent_pid", "role", "source_provenance"])
def test_current_frontend_identity_must_match_normalized_family(field):
    record = _full_current_identity()
    family = dict(record)
    if field == "argv":
        record[field] = ["node.exe", "different.js"]
    elif field == "parent_pid":
        record[field] = 999
    elif field == "source_provenance":
        record[field] = {"source": "different"}
    else:
        record[field] = f"different-{field}"

    with pytest.raises(RuntimeError, match=field):
        release._assert_current_identity_matches_family(record, family, "pid=101")


def _fresh_census_contract(count=145, states=None, approval=None):
    states = states or {}
    families = []
    presence = {}
    for pid in range(1, count + 1):
        identity = _full_current_identity(pid)
        identity["creation"] = f"creation-{pid}"
        identity["ports"] = [4100] if pid == 1 else []
        families.append(identity)
        state = states.get(pid, "absent")
        presence[pid] = {"state": state, "expected_creation": identity["creation"]}
        if state == "absent":
            presence[pid]["absence_proof"] = {
                "state": "verified_absent",
                "pid": pid,
                "expected_creation": identity["creation"],
                "native_error": 87,
            }
    return {
        "family_records": families,
        "presence": presence,
        "approval": approval,
    }


def _toolhelp_snapshot(*pids, caller_pid=999):
    rows = [
        {
            "pid": pid,
            "parent_pid": 4,
            "executable": f"C:/Windows/System32/process-{pid}.exe",
            "record_size": 568,
        }
        for pid in pids
    ]
    if caller_pid not in pids:
        rows.append(
            {
                "pid": caller_pid,
                "parent_pid": 4,
                "executable": "C:/Windows/System32/python.exe",
                "record_size": 568,
            }
        )
    return release._validate_toolhelp_process_snapshot(
        rows,
        caller_pid=caller_pid,
        record_size=568,
        expected_record_size=568,
        termination_error=18,
        handle_closed=True,
    )


def test_toolhelp_snapshot_rejects_invalid_structure():
    base = [
        {
            "pid": 1,
            "parent_pid": 4,
            "executable": "node.exe",
            "record_size": 568,
        },
        {
            "pid": 999,
            "parent_pid": 4,
            "executable": "python.exe",
            "record_size": 568,
        },
    ]
    cases = [
        ([], 999, 568, 18, True, "empty"),
        (base, 998, 568, 18, True, "caller PID"),
        (base + [dict(base[0])], 999, 568, 18, True, "duplicate PID"),
        (base, 999, 567, 18, True, "record size"),
        (base, 999, 568, 19, True, "ERROR_NO_MORE_FILES"),
        (base, 999, 568, 18, False, "handle did not close"),
    ]
    for rows, caller_pid, record_size, termination_error, handle_closed, message in cases:
        with pytest.raises(RuntimeError, match=message):
            release._validate_toolhelp_process_snapshot(
                rows,
                caller_pid=caller_pid,
                record_size=record_size,
                expected_record_size=568,
                termination_error=termination_error,
                handle_closed=handle_closed,
            )


def test_toolhelp_snapshot_retains_valid_system_process_sentinel():
    snapshot = release._validate_toolhelp_process_snapshot(
        [
            {
                "pid": 0,
                "parent_pid": 0,
                "executable": "[System Process]",
                "record_size": 568,
            },
            {
                "pid": 999,
                "parent_pid": 4,
                "executable": "python.exe",
                "record_size": 568,
            },
        ],
        caller_pid=999,
        record_size=568,
        expected_record_size=568,
        termination_error=18,
        handle_closed=True,
    )

    assert snapshot.rows[0] == {
        "pid": 0,
        "parent_pid": 0,
        "executable": "[System Process]",
        "record_size": 568,
    }
    assert snapshot.caller_pid == 999


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("parent_pid", 1, "PID 0 has an invalid parent PID"),
        ("executable", "System", "PID 0 has an invalid executable"),
        ("record_size", 567, "invalid record size"),
        ("pid", False, "invalid PID"),
        ("pid", 0.0, "invalid PID"),
        ("parent_pid", False, "invalid parent PID"),
        ("parent_pid", 0.0, "invalid parent PID"),
    ],
)
def test_toolhelp_snapshot_rejects_invalid_pid_zero_metadata(field, value, message):
    row = {
        "pid": 0,
        "parent_pid": 0,
        "executable": "[System Process]",
        "record_size": 568,
    }
    row[field] = value

    with pytest.raises(RuntimeError, match=message):
        release._validate_toolhelp_process_snapshot(
            [row, {"pid": 999, "parent_pid": 4, "executable": "python.exe", "record_size": 568}],
            caller_pid=999,
            record_size=568,
            expected_record_size=568,
            termination_error=18,
            handle_closed=True,
        )


def test_toolhelp_snapshot_rejects_duplicate_pid_zero():
    sentinel = {
        "pid": 0,
        "parent_pid": 0,
        "executable": "[System Process]",
        "record_size": 568,
    }

    with pytest.raises(RuntimeError, match="duplicate PID.*pid=0"):
        release._validate_toolhelp_process_snapshot(
            [sentinel, dict(sentinel), {"pid": 999, "parent_pid": 4, "executable": "python.exe", "record_size": 568}],
            caller_pid=999,
            record_size=568,
            expected_record_size=568,
            termination_error=18,
            handle_closed=True,
        )


def test_fresh_census_uses_snapshot_absence_without_handle_read(monkeypatch):
    contract = _fresh_census_contract(count=1)
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda *_args, **_kwargs: pytest.fail("snapshot absence must not open a process handle"),
    )
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {"processes": [], "holders": [], "ports": [], "read_errors": []},
    )

    result = release._assert_fresh_host_process_census(
        contract,
        process_snapshot=_toolhelp_snapshot(),
    )

    assert result["states"] == {1: "absent"}
    assert result["snapshot_absent_pids"] == [1]
    assert result["toolhelp_snapshot"]["historical_absent_count"] == 1


def test_fresh_census_keeps_present_snapshot_access_denied_fail_closed(monkeypatch):
    contract = _fresh_census_contract(count=1)
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            release._FreshProcessUnreadable("access denied")
        ),
    )

    with pytest.raises(RuntimeError, match="fresh native identity census failed.*access denied"):
        release._assert_fresh_host_process_census(
            contract,
            process_snapshot=_toolhelp_snapshot(1),
        )


def test_fresh_census_rejects_relevant_membership_change_after_resource_collection(monkeypatch):
    contract = _fresh_census_contract(count=1, states={1: "live"}, approval={"approved_actions": ["stop exact pid 1"]})
    contract["family_records"][0]["ports"] = []
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda pid, *_args, **_kwargs: contract["family_records"][pid - 1],
    )
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {"processes": [], "holders": [], "ports": [], "read_errors": []},
    )

    with pytest.raises(RuntimeError, match="relevant historical PID membership changed"):
        release._assert_fresh_host_process_census(
            contract,
            process_snapshot=_toolhelp_snapshot(1),
        )


def test_fresh_census_rejects_present_generation_change_after_resource_collection(monkeypatch):
    contract = _fresh_census_contract(count=1, states={1: "live"}, approval={"approved_actions": ["stop exact pid 1"]})
    contract["family_records"][0]["ports"] = []
    reads = [contract["family_records"][0], {**contract["family_records"][0], "creation": "new-generation"}]
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda *_args, **_kwargs: reads.pop(0),
    )
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {"processes": [{"pid": 1, "parent_pid": 4}], "holders": [], "ports": [], "read_errors": []},
    )

    with pytest.raises(RuntimeError, match="generation changed after resource collection"):
        release._assert_fresh_host_process_census(
            contract,
            process_snapshot=_toolhelp_snapshot(1),
        )


def test_fresh_census_allows_unrelated_pid_churn_with_snapshot(monkeypatch):
    contract = _fresh_census_contract(count=1)
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda *_args, **_kwargs: pytest.fail("absent historical PID must not be read"),
    )
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {
            "processes": [{"pid": 1000, "parent_pid": 4}],
            "holders": [],
            "ports": [],
            "read_errors": [],
        },
    )

    result = release._assert_fresh_host_process_census(
        contract,
        process_snapshot=_toolhelp_snapshot(1000),
    )

    assert result["states"] == {1: "absent"}
    assert result["snapshot_absent_pids"] == [1]


def test_fresh_census_accepts_absent_and_reused_historical_identities(monkeypatch):
    states = {pid: "reused" for pid in (144, 145)}
    contract = _fresh_census_contract(states=states)

    def read(pid, *_args, **_kwargs):
        if pid in states:
            return {**contract["family_records"][pid - 1], "creation": f"replacement-{pid}"}
        raise release._FreshProcessAbsent(f"pid={pid} absent")

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", read)
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {"processes": [], "holders": [], "ports": [], "read_errors": []},
    )

    result = release._assert_fresh_host_process_census(contract)

    assert len(result["states"]) == 145
    assert result["states"][1] == "absent"
    assert result["states"][144] == "reused"
    assert set(result["replacements"]) == {144, 145}


def test_fresh_census_records_exited_exact_object_as_terminal_absence(monkeypatch):
    contract = _fresh_census_contract(count=1, states={1: "absent"})
    family = contract["family_records"][0]
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda _pid, *_args, **_kwargs: {
            "pid": 1,
            "creation": family["creation"],
            "state": "exited",
            "exit_code": 1067,
            "expected_creation": family["creation"],
            "exit_proof": {
                "handle_state": "exited",
                "authoritative_win32_process": "absent",
                "creation": family["creation"],
            },
            "source_provenance": {
                "reader": "native limited process handle",
                "classification": "exited terminal object",
                "authoritative_win32_process": "absent",
            },
        },
    )
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {"processes": [], "holders": [], "ports": [], "read_errors": []},
    )

    result = release._assert_fresh_host_process_census(contract)

    assert result["states"][1] == "absent"
    assert result["terminal_states"][1]["exit_code"] == 1067
    assert result["transition_diagnostics"][1]["terminal_classification"] == (
        "exited_exact_historical_object"
    )


def test_fresh_census_records_exited_replacement_as_terminal_absence(monkeypatch):
    contract = _fresh_census_contract(count=1, states={1: "absent"})
    replacement = {
        "pid": 1,
        "creation": "replacement-1",
        "state": "exited",
        "exit_code": 1067,
        "exit_proof": {
            "handle_state": "exited",
            "authoritative_win32_process": "absent",
            "creation": "replacement-1",
        },
        "source_provenance": {
            "reader": "native limited process handle",
            "classification": "exited terminal object",
            "authoritative_win32_process": "absent",
        },
    }
    monkeypatch.setattr(release, "_read_fresh_native_process_identity", lambda _pid, *_args, **_kwargs: replacement)
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {"processes": [], "holders": [], "ports": [], "read_errors": []},
    )

    result = release._assert_fresh_host_process_census(contract)

    assert result["states"][1] == "absent"
    assert result["terminal_states"][1]["creation"] == "replacement-1"
    assert result["transition_diagnostics"][1]["terminal_classification"] == (
        "exited_replacement_object"
    )


def test_fresh_census_classifies_exited_replacement_followed_by_live_reuse(monkeypatch):
    contract = _fresh_census_contract(count=1, states={1: "absent"})
    replacement = {
        **contract["family_records"][0],
        "creation": "replacement-1",
        "source_provenance": {
            "reader": "native limited process handle",
            "classification": "exited handle followed by live PID reuse",
        },
    }
    monkeypatch.setattr(release, "_read_fresh_native_process_identity", lambda _pid, *_args, **_kwargs: replacement)
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {"processes": [], "holders": [], "ports": [], "read_errors": []},
    )

    result = release._assert_fresh_host_process_census(contract)

    assert result["states"][1] == "reused"
    assert result["replacement_pids"] == [1]


def test_fresh_census_accepts_pid_15064_exited_replacement_shape(monkeypatch):
    contract = _fresh_census_contract(count=1, states={1: "absent"})
    contract["family_records"][0]["pid"] = 15064
    contract["presence"][15064] = contract["presence"].pop(1)
    replacement = {
        "pid": 15064,
        "creation": "134364251048795626",
        "state": "exited",
        "exit_code": 1067,
        "exit_proof": {
            "handle_state": "exited",
            "authoritative_win32_process": "absent",
            "creation": "134364251048795626",
        },
        "source_provenance": {
            "reader": "native limited process handle",
            "classification": "exited terminal object",
            "authoritative_win32_process": "absent",
        },
    }
    monkeypatch.setattr(release, "_read_fresh_native_process_identity", lambda _pid, *_args, **_kwargs: replacement)
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {"processes": [], "holders": [], "ports": [], "read_errors": []},
    )

    result = release._assert_fresh_host_process_census(contract)

    assert result["states"][15064] == "absent"
    assert result["terminal_states"][15064]["exit_code"] == 1067
    assert result["transition_diagnostics"][15064]["terminal_classification"] == (
        "exited_replacement_object"
    )


@pytest.mark.parametrize(
    "error",
    [
        "native exit-state read failed",
        "native creation read failed",
        "exited handle contradicts authoritative Win32_Process row",
    ],
)
def test_fresh_census_preserves_hard_native_lifetime_read_errors(monkeypatch, error):
    contract = _fresh_census_contract(count=1)
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda _pid, *_args, **_kwargs: (_ for _ in ()).throw(release._FreshProcessUnreadable(error)),
    )

    with pytest.raises(RuntimeError, match=f"fresh native identity census failed.*{error}"):
        release._assert_fresh_host_process_census(contract)


@pytest.mark.parametrize(
    ("saved_state", "fresh_state"),
    [("absent", "absent"), ("absent", "reused"), ("reused", "absent"), ("reused", "reused")],
)
def test_fresh_census_accepts_allowed_saved_to_fresh_transitions(monkeypatch, saved_state, fresh_state):
    contract = _fresh_census_contract(count=1, states={1: saved_state})
    if fresh_state == "absent":
        monkeypatch.setattr(
            release,
            "_read_fresh_native_process_identity",
            lambda _pid, *_args, **_kwargs: (_ for _ in ()).throw(release._FreshProcessAbsent("absent")),
        )
    else:
        replacement = {**contract["family_records"][0], "creation": "replacement-1"}
        monkeypatch.setattr(release, "_read_fresh_native_process_identity", lambda _pid, *_args, **_kwargs: replacement)
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {"processes": [], "holders": [], "ports": [], "read_errors": []},
    )

    result = release._assert_fresh_host_process_census(contract)

    assert result["transition_diagnostics"][1] == {
        "saved_state": saved_state,
        "fresh_state": fresh_state,
    }


def test_fresh_census_excludes_reused_replacement_from_resource_selection(monkeypatch):
    contract = _fresh_census_contract(count=1, states={1: "absent"})
    replacement = {**contract["family_records"][0], "creation": "replacement-1"}
    native_path = str((release.SCRIPT_ROOT / release.HOST_NATIVE_MODULE).resolve())
    monkeypatch.setattr(release, "_read_fresh_native_process_identity", lambda _pid, *_args, **_kwargs: replacement)
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {
            "processes": [{"pid": 1, "parent_pid": 100}],
            "holders": [{"pid": 1, "module_paths": [native_path]}],
            "ports": [],
            "read_errors": [],
        },
    )

    result = release._assert_fresh_host_process_census(contract)

    assert result["replacement_pids"] == [1]


def test_fresh_resource_scope_rejects_replacement_between_limited_and_full_reads(monkeypatch):
    root = str(release.ROOT.resolve())
    replacement = {
        "pid": 15008,
        "creation": "replacement-15008",
        "executable": "C:/tools/node.exe",
        "source_provenance": {"reader": "native limited process handle"},
    }
    full_identity = _resource_identity(
        15008,
        cwd="C:/Repo/other-project",
        argv=["node.exe", "C:/Repo/other-project/server.js"],
    )
    read_states = []

    def read(pid, state, *_args, **_kwargs):
        read_states.append((pid, state.expected_creation, state.limited_only))
        return full_identity

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", read)
    with pytest.raises(
        RuntimeError,
        match="identity changed during hydration.*limited_creation='replacement-15008'.*fresh_creation='creation-15008'",
    ):
        release._fresh_resource_scope(
            {
                "processes": [
                    {
                        "pid": 15008,
                        "name": "node.exe",
                        "executable": "C:/tools/node.exe",
                        "parent_pid": 1,
                    }
                ],
                "holders": [],
                "ports": [],
                "read_errors": [],
            },
            root,
            scoped_ports={43123},
            preloaded_identities={15008: replacement},
        )

    assert read_states == [(15008, "replacement-15008", False)]


def test_fresh_resource_scope_hydrates_matching_limited_replacement(monkeypatch):
    root = str(release.ROOT.resolve())
    full_identity = _resource_identity(
        15008,
        cwd="C:/Repo/other-project",
        argv=["node.exe", "C:/Repo/other-project/server.js"],
    )
    replacement = {
        "pid": 15008,
        "creation": full_identity["creation"],
        "executable": "C:/tools/node.exe",
        "source_provenance": {"reader": "native limited process handle"},
    }

    monkeypatch.setattr(
        release, "_read_fresh_native_process_identity", lambda *_args, **_kwargs: full_identity
    )
    result = release._fresh_resource_scope(
        {
            "processes": [
                {
                    "pid": 15008,
                    "name": "node.exe",
                    "executable": "C:/tools/node.exe",
                    "parent_pid": 1,
                }
            ],
            "holders": [],
            "ports": [],
            "read_errors": [],
        },
        root,
        scoped_ports={43123},
        preloaded_identities={15008: replacement},
    )

    assert result["identities"][15008] == full_identity
    assert result["relevant_processes"] == []


def test_fresh_resource_scope_reads_unknown_process_with_product_root_cwd(monkeypatch):
    root = str(release.ROOT.resolve())
    reads = []

    def read(pid, *_args, **_kwargs):
        reads.append(pid)
        raise release._FreshProcessUnreadable("access denied")

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", read)

    with pytest.raises(RuntimeError, match="potentially relevant process identity failed: pid=15012"):
        release._fresh_resource_scope(
            {
                "processes": [
                    {
                        "pid": 15012,
                        "name": "mystery.exe",
                        "executable": "C:/tools/mystery.exe",
                        "cwd": root,
                        "parent_pid": 1,
                    }
                ],
                "holders": [],
                "ports": [],
                "read_errors": [],
            },
            root,
            scoped_ports=set(),
        )

    assert reads == [15012]


def test_fresh_resource_scope_reads_unknown_process_with_product_root_executable(monkeypatch):
    root = str(release.ROOT.resolve())
    reads = []

    def read(pid, *_args, **_kwargs):
        reads.append(pid)
        raise release._FreshProcessUnreadable("access denied")

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", read)

    with pytest.raises(RuntimeError, match="potentially relevant process identity failed: pid=15013"):
        release._fresh_resource_scope(
            {
                "processes": [
                    {
                        "pid": 15013,
                        "name": "mystery.exe",
                        "executable": f"{root}/bin/mystery.exe",
                        "cwd": "C:/other",
                        "parent_pid": 1,
                    }
                ],
                "holders": [],
                "ports": [],
                "read_errors": [],
            },
            root,
            scoped_ports=set(),
        )

    assert reads == [15013]


def test_fresh_resource_scope_reads_unknown_process_with_product_root_command(monkeypatch):
    root = str(release.ROOT.resolve())
    reads = []

    def read(pid, *_args, **_kwargs):
        reads.append(pid)
        raise release._FreshProcessUnreadable("access denied")

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", read)

    with pytest.raises(RuntimeError, match="potentially relevant process identity failed: pid=15016"):
        release._fresh_resource_scope(
            {
                "processes": [
                    {
                        "pid": 15016,
                        "name": "mystery.exe",
                        "executable": "C:/tools/mystery.exe",
                        "cwd": "C:/other",
                        "command": f'mystery.exe "{root}/frontend/server.js"',
                        "parent_pid": 1,
                    }
                ],
                "holders": [],
                "ports": [],
                "read_errors": [],
            },
            root,
            scoped_ports=set(),
        )

    assert reads == [15016]


@pytest.mark.parametrize("relation", ["cwd", "executable", "command", "preloaded_argv"])
def test_fresh_resource_scope_preserves_positive_relation_over_explicit_exclusion(monkeypatch, relation):
    root = str(release.ROOT.resolve())
    pid = 15020
    identity = _resource_identity(pid, cwd="C:/other", executable="C:/tools/mystery.exe")
    item = {
        "pid": pid,
        "name": "mystery.exe",
        "executable": "C:/tools/mystery.exe",
        "cwd": "C:/other",
        "parent_pid": 1,
        "protected_or_unrelated_state": "unrelated",
    }
    if relation == "cwd":
        item["cwd"] = f"{root}/frontend"
    elif relation == "executable":
        item["executable"] = f"{root}/bin/mystery.exe"
    elif relation == "command":
        item["command"] = f'mystery.exe "{root}/frontend/server.js"'
    else:
        identity["argv"] = ["mystery.exe", f"{root}/frontend/server.js"]
        identity["native_command"] = " ".join(identity["argv"])
        identity["argv_sha256"] = hashlib.sha256("\0".join(identity["argv"]).encode()).hexdigest()
        identity["native_command_sha256"] = hashlib.sha256(identity["native_command"].encode()).hexdigest()

    reads = []

    def read(read_pid, *_args, **_kwargs):
        reads.append(read_pid)
        return identity

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", read)
    with pytest.raises(RuntimeError, match="positive product-root relation"):
        release._fresh_resource_scope(
            {"processes": [item], "holders": [], "ports": [], "read_errors": []},
            root,
            scoped_ports=set(),
            preloaded_identities={pid: identity} if relation == "preloaded_argv" else None,
        )

    assert reads == ([] if relation == "preloaded_argv" else [pid])


@pytest.mark.parametrize(
    ("pid", "identity"),
    [
        (
            15017,
            lambda root: _resource_identity(15017, cwd=f"{root}/frontend", argv=["mystery.exe", "worker.js"]),
        ),
        (
            15018,
            lambda root: _resource_identity(
                15018,
                cwd="C:/other",
                argv=["mystery.exe", f"{root}/frontend/server.js"],
            ),
        ),
    ],
)
def test_fresh_resource_scope_preserves_complete_preloaded_product_relation(monkeypatch, pid, identity):
    root = str(release.ROOT.resolve())
    preloaded = identity(root)

    def read(*_args, **_kwargs):
        raise AssertionError("complete positive identity must not be re-read")

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", read)

    with pytest.raises(RuntimeError, match="positive product-root relation"):
        release._fresh_resource_scope(
            {
                "processes": [
                    {
                        "pid": pid,
                        "name": "mystery.exe",
                        "executable": "C:/tools/mystery.exe",
                        "cwd": "C:/other",
                        "parent_pid": 1,
                    }
                ],
                "holders": [],
                "ports": [],
                "read_errors": [],
            },
            root,
            scoped_ports=set(),
            preloaded_identities={pid: preloaded},
        )


def test_fresh_resource_scope_classifies_complete_unknown_product_root_holder(monkeypatch):
    root = str(release.ROOT.resolve())
    native = (release.SCRIPT_ROOT / release.HOST_NATIVE_MODULE).resolve().as_posix()
    identity = _resource_identity(
        15014,
        cwd=root,
        executable="C:/tools/mystery.exe",
        argv=["mystery.exe", "worker.bin"],
    )
    identity["module_paths"] = [native]
    monkeypatch.setattr(release, "_read_fresh_native_process_identity", lambda *_args, **_kwargs: identity)

    result = release._fresh_resource_scope(
        {
            "processes": [
                {
                    "pid": 15014,
                    "name": "mystery.exe",
                    "executable": "C:/tools/mystery.exe",
                    "cwd": root,
                    "parent_pid": 1,
                }
            ],
            "holders": [{"pid": 15014, "module_paths": [native]}],
            "ports": [],
            "read_errors": [],
        },
        root,
        scoped_ports=set(),
    )

    assert [entry["identity"]["pid"] for entry in result["relevant_processes"]] == [15014]


def test_fresh_resource_scope_excludes_unknown_process_outside_product_root(monkeypatch):
    root = str(release.ROOT.resolve())
    replacement = {
        "pid": 15015,
        "creation": "replacement-15015",
        "executable": "C:/tools/mystery.exe",
        "source_provenance": {"reader": "native limited process handle"},
    }
    reads = []

    def read(pid, *_args, **_kwargs):
        reads.append(pid)
        raise AssertionError("outside-scope unknown process must not be opened")

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", read)
    result = release._fresh_resource_scope(
        {
            "processes": [
                {
                    "pid": 15015,
                    "name": "mystery.exe",
                    "executable": "C:/tools/mystery.exe",
                    "cwd": "C:/other",
                    "parent_pid": 1,
                }
            ],
            "holders": [],
            "ports": [],
            "read_errors": [],
        },
        root,
        scoped_ports=set(),
        preloaded_identities={15015: replacement},
    )

    assert reads == []
    assert result["unrelated_exclusions"] == [
        {"pid": 15015, "reason": "outside measured frontend process family"}
    ]
    assert result["relevant_processes"] == []


def test_fresh_resource_scope_excludes_product_root_sibling_without_native_read(monkeypatch):
    root = str(release.ROOT.resolve())
    replacement = {
        "pid": 15019,
        "creation": "replacement-15019",
        "executable": "C:/tools/mystery.exe",
        "source_provenance": {"reader": "native limited process handle"},
    }
    reads = []

    def read(pid, *_args, **_kwargs):
        reads.append(pid)
        raise AssertionError("product-root sibling must not be opened")

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", read)
    sibling = f"{root}-sibling"
    result = release._fresh_resource_scope(
        {
            "processes": [
                {
                    "pid": 15019,
                    "name": "mystery.exe",
                    "executable": "C:/tools/mystery.exe",
                    "cwd": sibling,
                    "command": f'mystery.exe "{sibling}/frontend/server.js"',
                    "parent_pid": 1,
                }
            ],
            "holders": [],
            "ports": [],
            "read_errors": [],
        },
        root,
        scoped_ports=set(),
        preloaded_identities={15019: replacement},
    )

    assert reads == []
    assert result["unrelated_exclusions"] == [
        {"pid": 15019, "reason": "outside measured frontend process family"}
    ]


def test_fresh_resource_scope_excludes_partial_preloaded_noncandidate_without_native_read(monkeypatch):
    root = str(release.ROOT.resolve())
    replacement = {
        "pid": 15011,
        "creation": "replacement-15011",
        "executable": "C:/Program Files/Bitdefender Agent/DiscoverySrv.exe",
        "source_provenance": {"reader": "native limited process handle"},
    }
    reads = []

    def read(pid, *_args, **_kwargs):
        reads.append(pid)
        raise AssertionError("excluded noncandidate must not be opened")

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", read)
    result = release._fresh_resource_scope(
        {
            "processes": [
                {
                    "pid": 15011,
                    "name": "DiscoverySrv.exe",
                    "executable": "C:/Program Files/Bitdefender Agent/DiscoverySrv.exe",
                    "parent_pid": 1,
                }
            ],
            "holders": [],
            "ports": [],
            "read_errors": [],
        },
        root,
        scoped_ports={43123},
        preloaded_identities={15011: replacement},
    )

    assert reads == []
    assert result["unrelated_exclusions"] == [
        {"pid": 15011, "reason": "outside measured frontend process family"}
    ]
    assert result["relevant_processes"] == []


def test_fresh_resource_scope_keeps_partial_preloaded_noncandidate_separate(monkeypatch):
    root = str(release.ROOT.resolve())
    replacement = {
        "pid": 15011,
        "creation": "replacement-15011",
        "executable": "C:/Program Files/Bitdefender Agent/DiscoverySrv.exe",
        "source_provenance": {"reader": "native limited process handle"},
    }
    reads = []

    def read(pid, *_args, **_kwargs):
        reads.append(pid)
        raise AssertionError("excluded noncandidate must not be opened")

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", read)
    result = release._fresh_resource_scope(
        {
            "processes": [
                {
                    "pid": 15011,
                    "name": "DiscoverySrv.exe",
                    "executable": "C:/Program Files/Bitdefender Agent/DiscoverySrv.exe",
                    "parent_pid": 1,
                }
            ],
            "holders": [],
            "ports": [],
            "read_errors": [],
        },
        root,
        scoped_ports={43123},
        preloaded_identities={15011: replacement},
    )

    assert reads == []
    assert result["unrelated_exclusions"] == [
        {"pid": 15011, "reason": "outside measured frontend process family"}
    ]
    assert result["relevant_processes"] == []


def test_fresh_resource_scope_excludes_authoritatively_exited_process(monkeypatch):
    exited = {
        "pid": 15009,
        "creation": "creation-15009",
        "state": "exited",
        "exit_code": 0,
        "exit_proof": {
            "handle_state": "exited",
            "authoritative_win32_process": "absent",
            "creation": "creation-15009",
        },
        "source_provenance": {"authoritative_win32_process": "absent"},
    }
    monkeypatch.setattr(release, "_read_fresh_native_process_identity", lambda *_args, **_kwargs: exited)

    result = release._fresh_resource_scope(
        {
            "processes": [{"pid": 15009, "name": "node.exe", "parent_pid": 1}],
            "holders": [],
            "ports": [],
            "read_errors": [],
        },
        str(release.ROOT.resolve()),
        scoped_ports={43123},
    )

    assert result["terminal_exclusions"] == [
        {"pid": 15009, "reason": "authoritative native exit during census"}
    ]
    assert result["relevant_processes"] == []


def test_fresh_resource_scope_rejects_contradictory_exit_during_census(monkeypatch):
    exited = {
        "pid": 15010,
        "creation": "creation-15010",
        "state": "exited",
        "exit_code": 259,
        "exit_proof": {
            "handle_state": "exited",
            "authoritative_win32_process": "absent",
            "creation": "creation-15010",
        },
        "source_provenance": {"authoritative_win32_process": "absent"},
    }
    monkeypatch.setattr(release, "_read_fresh_native_process_identity", lambda *_args, **_kwargs: exited)

    with pytest.raises(RuntimeError, match="exit evidence is contradictory"):
        release._fresh_resource_scope(
            {
                "processes": [{"pid": 15010, "name": "node.exe", "parent_pid": 1}],
                "holders": [],
                "ports": [],
                "read_errors": [],
            },
            str(release.ROOT.resolve()),
            scoped_ports={43123},
        )


def _absent_resource_scope_fixture(pid=15012):
    return {
        "processes": [
            {
                "pid": pid,
                "name": "node.exe",
                "executable": "C:/node.exe",
                "cwd": "C:/product/frontend",
                "parent_pid": 1,
            }
        ],
        "holders": [],
        "ports": [],
        "read_errors": [],
    }


def test_fresh_resource_scope_excludes_explicitly_absent_candidate_once_and_retains_private_evidence(
    monkeypatch, tmp_path
):
    reads = []

    def read(pid, *_args, **_kwargs):
        reads.append(pid)
        raise release._FreshProcessAbsent("pid=15012 is absent")

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", read)
    monkeypatch.setattr(release, "EXTERNAL_PROOF_ROOT", tmp_path)
    monkeypatch.setattr(release, "_git", lambda *_args: "checkpoint-1655")

    result = release._fresh_resource_scope(
        _absent_resource_scope_fixture(),
        "C:/product",
        scoped_ports={43123},
    )

    assert reads == [15012]
    assert result["terminal_exclusions"] == [
        {"pid": 15012, "reason": "explicit native absence during census"}
    ]
    diagnostic = result["private_diagnostics"][0]
    payload = Path(diagnostic["path"]).read_bytes()
    evidence = json.loads(payload)
    assert diagnostic["digest"] == hashlib.sha256(payload).hexdigest()
    assert evidence["native_absence"] == {
        "pid": 15012,
        "type": "_FreshProcessAbsent",
        "message": "pid=15012 is absent",
    }
    assert evidence["complete_current_identity"] is None
    assert result["relevant_processes"] == []


@pytest.mark.parametrize("resource_field", ["native", "port"])
def test_fresh_resource_scope_blocks_absent_measured_resource_owner(
    monkeypatch, tmp_path, resource_field
):
    resources = _absent_resource_scope_fixture(15013)
    if resource_field == "native":
        native = (release.SCRIPT_ROOT / release.HOST_NATIVE_MODULE).resolve().as_posix()
        resources["holders"] = [{"pid": 15013, "module_paths": [native]}]
    else:
        resources["ports"] = [{"pid": 15013, "port": 43123}]

    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            release._FreshProcessAbsent("pid=15013 is absent")
        ),
    )
    monkeypatch.setattr(release, "EXTERNAL_PROOF_ROOT", tmp_path)
    monkeypatch.setattr(release, "_git", lambda *_args: "checkpoint-1655")

    with pytest.raises(RuntimeError, match="fresh resource owner became absent during census"):
        release._fresh_resource_scope(resources, "C:/product", scoped_ports={43123})


def test_fresh_resource_scope_keeps_generic_unreadable_identity_blocking(monkeypatch):
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            release._FreshProcessUnreadable("access denied")
        ),
    )

    with pytest.raises(RuntimeError, match="potentially relevant process identity failed: pid=15012"):
        release._fresh_resource_scope(
            _absent_resource_scope_fixture(),
            "C:/product",
            scoped_ports={43123},
        )


def test_fresh_census_rejects_unreadable_replacement_identity(monkeypatch):
    contract = _fresh_census_contract(count=1, states={1: "reused"})
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda _pid, *_args, **_kwargs: (_ for _ in ()).throw(release._FreshProcessUnreadable("access denied")),
    )

    with pytest.raises(RuntimeError, match="fresh native identity census failed.*access denied"):
        release._assert_fresh_host_process_census(contract)


def test_fresh_census_rejects_partial_replacement_identity(monkeypatch):
    contract = _fresh_census_contract(count=1, states={1: "absent"})
    replacement = {"pid": 1, "creation": "replacement-1"}
    monkeypatch.setattr(release, "_read_fresh_native_process_identity", lambda _pid, *_args, **_kwargs: replacement)

    with pytest.raises(RuntimeError, match="fresh replacement identity is incomplete"):
        release._assert_fresh_host_process_census(contract)


def test_fresh_census_rejects_expected_creation_mismatch():
    contract = _fresh_census_contract(count=1)
    contract["presence"][1]["expected_creation"] = "wrong-creation"

    with pytest.raises(RuntimeError, match="disagrees with measured family"):
        release._current_cleanup_observation(
            {"observations": [contract["presence"][1] | {"pid": 1}]},
            "presence.json",
            contract["family_records"],
        )


@pytest.mark.parametrize("saved_state", ["absent", "reused"])
def test_fresh_census_denies_exact_live_identity_without_approval(monkeypatch, saved_state):
    contract = _fresh_census_contract(count=1, states={1: saved_state})
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda _pid, *_args, **_kwargs: contract["family_records"][0],
    )

    with pytest.raises(RuntimeError, match="exact-live historical identity is unapproved"):
        release._assert_fresh_host_process_census(contract)


@pytest.mark.parametrize("saved_state", ["absent", "reused"])
def test_fresh_census_accepts_approved_exact_live_identity_after_full_match(monkeypatch, saved_state):
    contract = _fresh_census_contract(
        count=1,
        states={1: saved_state},
        approval={"approved_actions": ["stop exact pid 1"]},
    )
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda _pid, *_args, **_kwargs: contract["family_records"][0],
    )
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {
            "processes": [{"pid": 1, "parent_pid": 100}],
            "holders": [],
            "ports": [{"port": 4100, "pid": 1}],
            "read_errors": [],
        },
    )

    result = release._assert_fresh_host_process_census(contract)

    assert result["states"][1] == "live"


def test_fresh_census_rejects_unreadable_identity(monkeypatch):
    contract = _fresh_census_contract()
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda _pid, *_args, **_kwargs: (_ for _ in ()).throw(release._FreshProcessUnreadable("access denied")),
    )

    with pytest.raises(RuntimeError, match="fresh native identity census failed.*access denied"):
        release._assert_fresh_host_process_census(contract)


def test_fresh_census_rejects_access_denied_for_saved_absent_identity(monkeypatch):
    contract = _fresh_census_contract(count=1, states={1: "absent"})
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda _pid, *_args, **_kwargs: (_ for _ in ()).throw(
            release._FreshProcessUnreadable("pid=1 limited native identity open failed: WinError 5")
        ),
    )
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {
            "processes": [
                {
                    "pid": 1,
                    "name": "SystemSettings.exe",
                    "executable": "C:/Windows/System32/SystemSettings.exe",
                    "command": "SystemSettings.exe",
                    "cwd": "C:/Windows",
                    "parent_pid": 4,
                }
            ],
            "holders": [],
            "ports": [],
            "read_errors": [],
        },
    )

    with pytest.raises(RuntimeError, match="fresh native identity census failed.*WinError 5"):
        release._assert_fresh_host_process_census(contract)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda row, root: row.update(cwd=f"{root}/frontend"),
        lambda row, root: row.update(command=f"SystemSettings.exe {root}/frontend/server.js"),
        lambda row, root: row.update(parent_pid=2),
    ],
)
def test_fresh_census_keeps_access_denied_ambiguous_scope_blocking(monkeypatch, mutate):
    contract = _fresh_census_contract(count=1, states={1: "absent"})
    root = str(release.ROOT.resolve())
    row = {
        "pid": 1,
        "name": "SystemSettings.exe",
        "executable": "C:/Windows/System32/SystemSettings.exe",
        "command": "SystemSettings.exe",
        "cwd": "C:/Windows",
        "parent_pid": 4,
    }
    mutate(row, root)
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda _pid, *_args, **_kwargs: (_ for _ in ()).throw(
            release._FreshProcessUnreadable("pid=1 limited native identity open failed: WinError 5")
        ),
    )
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {"processes": [row], "holders": [], "ports": [], "read_errors": []},
    )

    with pytest.raises(RuntimeError, match="fresh native identity census failed.*WinError 5"):
        release._assert_fresh_host_process_census(contract)


@pytest.mark.parametrize("resource_field", ["scoped_port", "project_module", "relevant_parent"])
def test_fresh_census_keeps_access_denied_resource_conflicts_blocking(monkeypatch, resource_field):
    contract = _fresh_census_contract(count=1, states={1: "absent"})
    root = str(release.ROOT.resolve())
    row = {
        "pid": 1,
        "name": "SystemSettings.exe",
        "executable": "C:/Windows/System32/SystemSettings.exe",
        "command": "SystemSettings.exe",
        "cwd": "C:/Windows",
        "parent_pid": 4,
    }
    resources = {"processes": [row], "holders": [], "ports": [], "read_errors": []}
    if resource_field == "scoped_port":
        resources["ports"] = [{"port": 4100, "pid": 1}]
    elif resource_field == "project_module":
        resources["holders"] = [{"pid": 1, "module_paths": [f"{root}/frontend/module.node"]}]
    else:
        row["parent_pid"] = 2
        resources["processes"].append(
            {
                "pid": 2,
                "name": "node.exe",
                "executable": "C:/tools/node.exe",
                "command": f"node {root}/frontend/server.js",
                "cwd": f"{root}/frontend",
                "parent_pid": 4,
            }
        )
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda _pid, *_args, **_kwargs: (_ for _ in ()).throw(
            release._FreshProcessUnreadable("pid=1 limited native identity open failed: WinError 5")
        ),
    )
    monkeypatch.setattr(release, "_enumerate_fresh_frontend_resources", lambda: resources)

    with pytest.raises(RuntimeError, match="fresh native identity census failed.*WinError 5"):
        release._assert_fresh_host_process_census(contract)


def test_fresh_census_classifies_process_absence_as_terminal_exclusion(monkeypatch, tmp_path):
    reads = []

    def read_absent(pid, *_args, **_kwargs):
        reads.append(pid)
        raise release._FreshProcessAbsent("absent")

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", read_absent)
    monkeypatch.setattr(release, "EXTERNAL_PROOF_ROOT", tmp_path)
    resources = {
        "processes": [
            {
                "pid": 999,
                "name": "node.exe",
                "executable": "C:/node.exe",
                "parent_pid": 1,
                "cwd": str(release.ROOT.resolve() / "frontend"),
                "command": f"node {release.ROOT.resolve()}/frontend/server.js",
            }
        ],
        "holders": [],
        "ports": [],
        "read_errors": [],
    }
    result = release._fresh_resource_scope(
        resources,
        str(release.ROOT.resolve()),
        scoped_ports=set(),
        preloaded_identities={},
        protected_pids=set(),
    )

    assert reads == [999]
    assert result["terminal_exclusions"] == [
        {"pid": 999, "reason": "explicit native absence during census"}
    ]
    diagnostic = result["private_diagnostics"]
    assert len(diagnostic) == 1
    assert diagnostic[0]["pid"] == 999
    assert diagnostic[0]["kind"] == "native_absence"
    assert diagnostic[0]["path"]
    assert diagnostic[0]["digest"]
    evidence = json.loads(Path(diagnostic[0]["path"]).read_text(encoding="utf-8"))
    assert evidence["native_absence"] == {
        "pid": 999,
        "type": "_FreshProcessAbsent",
        "message": "absent",
    }
    assert diagnostic[0]["digest"] == hashlib.sha256(
        Path(diagnostic[0]["path"]).read_bytes()
    ).hexdigest()


def test_fresh_census_rejects_absent_native_holder(monkeypatch):
    contract = _fresh_census_contract()
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda _pid, *_args, **_kwargs: (_ for _ in ()).throw(release._FreshProcessAbsent("absent")),
    )
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {
            "processes": [],
            "holders": [
                {
                    "pid": 999,
                    "module_paths": [str((release.SCRIPT_ROOT / release.HOST_NATIVE_MODULE).resolve())],
                }
            ],
            "ports": [],
            "read_errors": [],
        },
    )

    with pytest.raises(
        RuntimeError,
        match=r"fresh resource census is unstable or unreadable; fresh native module holder identity is unreadable: pid=999",
    ):
        release._assert_fresh_host_process_census(contract)


def test_fresh_census_rejects_absent_scoped_port_owner(monkeypatch):
    contract = _fresh_census_contract()
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda _pid, *_args, **_kwargs: (_ for _ in ()).throw(release._FreshProcessAbsent("absent")),
    )
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {
            "processes": [
                {
                    "pid": 999,
                    "name": "node.exe",
                    "executable": "C:/node.exe",
                    "parent_pid": 1,
                    "cwd": str(release.ROOT.resolve() / "frontend"),
                    "command": f"node {release.ROOT.resolve()}/frontend/server.js",
                }
            ],
            "holders": [],
            "ports": [{"port": 4100, "pid": 999}],
            "read_errors": [],
        },
    )
    monkeypatch.setattr(
        release,
        "_record_private_resource_scope_failure",
        lambda **_kwargs: (Path("private-absence.json"), "absence-digest"),
    )

    with pytest.raises(RuntimeError) as error:
        release._assert_fresh_host_process_census(contract)

    message = str(error.value)
    assert "fresh resource owner became absent during census" in message
    assert "pid=999" in message
    assert "native_holder=False" in message
    assert "scoped_port_owner=True" in message
    assert "private_evidence=" in message
    assert "evidence_digest=" in message


def test_fresh_census_accepts_explicit_empty_resource_measurement(monkeypatch):
    contract = _fresh_census_contract()
    monkeypatch.setattr(release, "_read_fresh_native_process_identity", lambda _pid, *_args, **_kwargs: (_ for _ in ()).throw(release._FreshProcessAbsent("absent")))
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {"processes": [], "holders": [], "ports": [], "read_errors": []},
    )

    assert release._assert_fresh_host_process_census(contract)["resources"] == {
        "processes": [], "holders": [], "ports": [], "read_errors": []
    }


def test_fresh_census_excludes_historical_partial_replacement_before_native_read(monkeypatch):
    contract = _fresh_census_contract(count=1)
    reads = []

    def read(pid, *_args, **_kwargs):
        reads.append(pid)
        if _args and _args[0].expected_creation == contract["family_records"][0]["creation"]:
            raise release._FreshProcessAbsent("historical identity absent")
        raise AssertionError(f"excluded current noncandidate must not be hydrated: pid={pid}")

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", read)
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {
            "processes": [
                {
                    "pid": 1,
                    "name": "DiscoverySrv.exe",
                    "executable": "C:/Program Files/Bitdefender Agent/DiscoverySrv.exe",
                    "parent_pid": 4,
                }
            ],
            "holders": [],
            "ports": [],
            "read_errors": [],
        },
    )

    result = release._assert_fresh_host_process_census(contract)

    assert reads == [1]
    assert result["historical_exclusions"] == [
        {
            "pid": 1,
            "reason": "historical identity not selected by current resource evidence",
            "saved_state": "absent",
        }
    ]


@pytest.mark.parametrize("resource_kind", ["product", "holder", "port"])
def test_fresh_census_keeps_selected_historical_identity_fail_closed(monkeypatch, resource_kind):
    contract = _fresh_census_contract(count=1)
    native_path = str((release.SCRIPT_ROOT / release.HOST_NATIVE_MODULE).resolve())
    row = {
        "pid": 1,
        "name": "node.exe" if resource_kind == "product" else "DiscoverySrv.exe",
        "executable": "C:/tools/node.exe",
        "parent_pid": 4,
    }
    resources = {"processes": [row], "holders": [], "ports": [], "read_errors": []}
    if resource_kind == "product":
        row["cwd"] = str(release.ROOT.resolve() / "frontend")
        row["command"] = f"node {release.ROOT.resolve() / 'frontend' / 'server.js'}"
    elif resource_kind == "holder":
        resources["holders"] = [{"pid": 1, "module_paths": [native_path]}]
    else:
        resources["ports"] = [{"pid": 1, "port": 4100}]

    monkeypatch.setattr(release, "_enumerate_fresh_frontend_resources", lambda: resources)
    def read(pid, state, **_kwargs):
        if state.expected_creation == contract["family_records"][0]["creation"]:
            raise release._FreshProcessAbsent("historical identity absent")
        raise release._FreshProcessUnreadable("WinError 5")

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", read)

    with pytest.raises(RuntimeError, match="potentially relevant process identity failed: pid=1"):
        release._assert_fresh_host_process_census(contract)


def test_fresh_census_records_candidate_absence_with_private_proof(monkeypatch):
    contract = _fresh_census_contract(count=1)
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {
            "processes": [
                {
                    "pid": 1,
                    "name": "node.exe",
                    "executable": "C:/tools/node.exe",
                    "cwd": str(release.ROOT.resolve() / "frontend"),
                    "command": f"node {release.ROOT.resolve() / 'frontend' / 'server.js'}",
                    "parent_pid": 4,
                }
            ],
            "holders": [],
            "ports": [],
            "read_errors": [],
        },
    )
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            release._FreshProcessAbsent("pid=1 is absent")
        ),
    )
    monkeypatch.setattr(
        release,
        "_record_private_resource_scope_failure",
        lambda **_kwargs: (Path("private-absence.json"), "absence-digest"),
    )

    result = release._assert_fresh_host_process_census(contract)

    assert result["states"][1] == "absent"
    assert result["private_diagnostics"] == [
        {"pid": 1, "kind": "native_absence", "path": "private-absence.json", "digest": "absence-digest"}
    ]


def test_fresh_census_rejects_exact_live_identity_without_approval(monkeypatch):
    contract = _fresh_census_contract(states={1: "live"})
    monkeypatch.setattr(release, "_read_fresh_native_process_identity", lambda pid, *_args, **_kwargs: contract["family_records"][pid - 1])

    with pytest.raises(RuntimeError, match="exact-live historical identity is unapproved"):
        release._assert_fresh_host_process_census(contract)


def test_fresh_census_accepts_exact_live_identity_with_narrow_approval(monkeypatch):
    contract = _fresh_census_contract(states={1: "live"}, approval={"approved_actions": ["stop exact pid 1"]})
    def read(pid, *_args, **_kwargs):
        if pid == 1:
            return contract["family_records"][pid - 1]
        raise release._FreshProcessAbsent("absent")

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", read)
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {
            "processes": [{"pid": 1, "parent_pid": 100}],
            "holders": [],
            "ports": [{"port": 4100, "pid": 1}],
            "read_errors": [],
        },
    )

    assert release._assert_fresh_host_process_census(contract)["states"][1] == "live"


def test_fresh_census_binds_exact_live_native_resource_holder(monkeypatch):
    contract = _fresh_census_contract(
        count=1,
        states={1: "live"},
        approval={"approved_actions": ["stop exact pid 1"]},
    )
    native_path = str((release.SCRIPT_ROOT / release.HOST_NATIVE_MODULE).resolve())
    contract["family_records"][0]["files"] = [native_path]
    contract["family_records"][0]["module_paths"] = [native_path]
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda _pid, *_args, **_kwargs: contract["family_records"][0],
    )
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {
            "processes": [{"pid": 1, "parent_pid": 100}],
            "holders": [{"pid": 1, "module_paths": [native_path]}],
            "ports": [{"port": 4100, "pid": 1}],
            "read_errors": [],
        },
    )

    assert release._assert_fresh_host_process_census(contract)["states"][1] == "live"


def test_fresh_census_excludes_protected_gate_process(monkeypatch):
    contract = _fresh_census_contract()
    monkeypatch.setattr(release, "_read_fresh_native_process_identity", lambda _pid, *_args, **_kwargs: (_ for _ in ()).throw(release._FreshProcessAbsent("absent")))
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {
            "processes": [{"pid": 900, "parent_pid": 1, "protected_or_unrelated_state": "protected"}],
            "holders": [],
            "ports": [],
            "read_errors": [],
        },
    )

    assert release._assert_fresh_host_process_census(contract)["states"][1] == "absent"


@pytest.mark.parametrize("resource_field", ["unreadable_holder", "holders", "ports"])
def test_fresh_census_does_not_exempt_reader_pid_from_resources(monkeypatch, resource_field):
    contract = _fresh_census_contract()
    root = str(release.ROOT.resolve())
    native_path = str((release.SCRIPT_ROOT / release.HOST_NATIVE_MODULE).resolve())
    reader_pid = 900
    reader = {
        "pid": reader_pid,
        "name": "node.exe",
        "executable": "C:/tools/node.exe",
        "parent_pid": 1,
        "command": f"node {root}/frontend/server.js",
        "cwd": f"{root}/frontend",
    }

    def read(pid, *_args, **_kwargs):
        if pid <= 145:
            raise release._FreshProcessAbsent("historical identity absent")
        identity = _full_current_identity(pid)
        identity["parent_pid"] = 1
        identity["parent_observations"] = [{"pid": 1, "state": "windows_system_parent"}]
        return identity

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", read)
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {
            "processes": [reader],
            "holders": [
                {"pid": reader_pid, "module_paths": None}
                if resource_field == "unreadable_holder"
                else {"pid": reader_pid, "module_paths": [native_path]}
            ]
            if resource_field in {"unreadable_holder", "holders"}
            else [],
            "ports": [{"port": 4100, "pid": reader_pid}] if resource_field == "ports" else [],
            "read_errors": [],
        },
    )

    expected_error = (
        "native holder modules are unreadable"
        if resource_field == "unreadable_holder"
        else "fresh relevant frontend process"
    )
    with pytest.raises(RuntimeError, match=expected_error):
        release._assert_fresh_host_process_census(contract)


def test_fresh_census_binds_frontend_identity_after_historical_pid_was_absent(monkeypatch):
    contract = _fresh_census_contract(count=1, states={1: "absent"})
    root = str(release.ROOT.resolve())
    current = _full_current_identity(1)
    current["creation"] = "replacement-1"
    current["executable"] = "C:/tools/node.exe"
    current["cwd"] = f"{root}/frontend"
    current["argv"] = ["node.exe", f"{root}/frontend/server.js"]
    current["native_command"] = " ".join(current["argv"])
    current["argv_sha256"] = hashlib.sha256("\0".join(current["argv"]).encode()).hexdigest()
    current["native_command_sha256"] = hashlib.sha256(current["native_command"].encode()).hexdigest()
    reads = []

    def read(pid, *_args, **_kwargs):
        reads.append(pid)
        if pid == 1:
            return current
        raise AssertionError(f"unexpected identity read for pid={pid}")

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", read)
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {
            "processes": [{
                "pid": 1,
                "parent_pid": 100,
                "name": "node.exe",
                "executable": "C:/tools/node.exe",
                "cwd": f"{root}/frontend",
                "command": f"node {root}/frontend/server.js",
            }],
            "holders": [],
            "ports": [],
            "read_errors": [],
        },
    )

    result = release._assert_fresh_host_process_census(contract)

    assert reads == [1]
    assert result["replacement_pids"] == [1]


def test_fresh_census_does_not_make_unrelated_reader_relevant_from_historical_pid(monkeypatch):
    contract = _fresh_census_contract(count=1)
    root = str(release.ROOT.resolve())
    reader = {
        "pid": 1,
        "parent_pid": 100,
        "name": "powershell.exe",
        "executable": "C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
        "command": "powershell -Command Get-CimInstance C:/other",
        "cwd": "C:/other",
    }
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda _pid, *_args, **_kwargs: (_ for _ in ()).throw(release._FreshProcessAbsent("historical identity absent")),
    )
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {"processes": [reader], "holders": [], "ports": [], "read_errors": []},
    )

    result = release._assert_fresh_host_process_census(contract)

    assert result["resources"]["processes"] == [reader]
    assert result["unrelated_exclusions"] == [
        {"pid": 1, "reason": "outside measured frontend process family"}
    ]


def test_fresh_census_excludes_unrelated_python_with_product_root_text(monkeypatch):
    contract = _fresh_census_contract(count=1)
    root = str(release.ROOT.resolve())
    reader = {
        "pid": 2,
        "parent_pid": 100,
        "name": "python.exe",
        "executable": "C:/Python311/python.exe",
        "command": "python -m pytest C:/other/scripts/tests",
        "cwd": "C:/Python311",
    }
    reads = []

    def read(pid, *_args, **_kwargs):
        reads.append(pid)
        if pid == 1:
            raise release._FreshProcessAbsent("historical identity absent")
        raise AssertionError(f"unrelated Python row must not receive a full identity read: pid={pid}")

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", read)
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {"processes": [reader], "holders": [], "ports": [], "read_errors": []},
    )

    result = release._assert_fresh_host_process_census(contract)

    assert reads == [1]
    assert result["unrelated_exclusions"] == [
        {"pid": 2, "reason": "outside measured frontend process family"}
    ]


def test_fresh_census_excludes_readable_process_with_protected_ancestry(monkeypatch):
    contract = _fresh_census_contract(count=1)
    root = str(release.ROOT.resolve())
    protected = _full_current_identity(901)
    protected["executable"] = f"{root}/.venv/Scripts/python.exe"
    protected["cwd"] = root
    protected["argv"] = ["python.exe", "-m", "pytest", "scripts/tests"]
    protected["argv_sha256"] = hashlib.sha256("\0".join(protected["argv"]).encode()).hexdigest()
    protected["native_command"] = "python.exe -m pytest scripts/tests"
    protected["native_command_sha256"] = hashlib.sha256(protected["native_command"].encode()).hexdigest()
    candidate = _full_current_identity(900)
    candidate["executable"] = "C:/tools/node.exe"
    candidate["cwd"] = f"{root}/frontend"
    candidate["argv"] = ["node.exe", f"{root}/frontend/server.js"]
    candidate["argv_sha256"] = hashlib.sha256("\0".join(candidate["argv"]).encode()).hexdigest()
    candidate["native_command"] = f"node.exe {root}/frontend/server.js"
    candidate["native_command_sha256"] = hashlib.sha256(candidate["native_command"].encode()).hexdigest()
    candidate["parent_pid"] = 901
    candidate["parent_observations"] = [
        {
            "pid": 901,
            "state": "readable_current_parent",
            "creation": "creation-901",
            "parent_pid": 1,
            "cwd": root,
            "executable": f"{root}/.venv/Scripts/python.exe",
            "argv": list(protected["argv"]),
            "argv_sha256": protected["argv_sha256"],
            "native_command": "python.exe -m pytest scripts/tests",
            "native_command_sha256": protected["native_command_sha256"],
        }
    ]

    def read(pid, *_args, **_kwargs):
        if pid == 1:
            raise release._FreshProcessAbsent("pid=1 absent")
        if pid == 901:
            return protected
        if pid == 900:
            return candidate
        raise AssertionError(f"unexpected identity read for pid={pid}")

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", read)
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {
            "processes": [
                {
                    "pid": 900,
                    "parent_pid": 901,
                    "name": "node.exe",
                    "executable": "C:/tools/node.exe",
                    "cwd": f"{root}/frontend",
                    "command": f"node {root}/frontend/server.js",
                }
            ],
            "holders": [],
            "ports": [],
            "read_errors": [],
        },
    )

    result = release._assert_fresh_host_process_census(contract)

    assert result["resources"]["processes"][0]["pid"] == 900
    assert result["states"][1] == "absent"


def test_native_parent_observation_records_verified_absence(monkeypatch):
    def absent(_pid, _read_state, _ancestry=None, _read_parent_observation=True):
        raise release._FreshProcessAbsent("parent exited")

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", absent)

    assert release._read_fresh_parent_observation(10, "100", 20, {10}) == [
        {"pid": 20, "state": "verified_absent_parent"}
    ]


def _controlled_parent_identity(pid=20, creation="100", parent_pid=1):
    argv = ["C:/parent.exe", "--worker"]
    command = "C:/parent.exe --worker"
    return {
        "pid": pid,
        "creation": creation,
        "parent_pid": parent_pid,
        "cwd": "C:/work",
        "executable": "C:/parent.exe",
        "argv": argv,
        "argv_sha256": hashlib.sha256("\0".join(argv).encode()).hexdigest(),
        "native_command": command,
        "native_command_sha256": hashlib.sha256(command.encode()).hexdigest(),
        "role": "measured current native process",
        "family_relation": "measured current native process identity",
        "read_errors": [],
        "listening_ports": [],
        "source_provenance": {"reader": "controlled test"},
        "module_paths": [],
        "files": [],
        "ports": [],
    }


def test_native_parent_observation_records_terminal_transitions_without_live_fields(monkeypatch):
    cases = [
        (
            [
                release._FreshProcessAbsent("parent exited"),
            ],
            "verified_absent_parent",
        ),
        (
            [
                {
                    "pid": 20,
                    "creation": "100",
                    "state": "exited",
                    "exit_code": 0,
                    "exit_proof": {
                        "handle_state": "exited",
                        "authoritative_win32_process": "absent",
                        "creation": "100",
                    },
                    "source_provenance": {"authoritative_win32_process": "absent"},
                },
            ],
            "verified_exited_parent",
        ),
        (
            [
                _controlled_parent_identity(creation="100"),
                release._FreshProcessAbsent("parent exited during second read"),
            ],
            "parent_exited_during_observation",
        ),
        (
            [
                _controlled_parent_identity(creation="100"),
                {
                    "pid": 20,
                    "creation": "100",
                    "state": "exited",
                    "exit_code": 0,
                    "exit_proof": {
                        "handle_state": "exited",
                        "authoritative_win32_process": "absent",
                        "creation": "100",
                    },
                    "source_provenance": {"authoritative_win32_process": "absent"},
                },
            ],
            "verified_exited_parent",
        ),
        (
            [
                _controlled_parent_identity(creation="100"),
                _controlled_parent_identity(creation="200"),
            ],
            "historical_parent_exited_pid_reused",
        ),
    ]

    for sequence, expected_state in cases:
        values = iter(sequence)

        def read(_pid, _read_state, _ancestry=None, _read_parent_observation=True):
            value = next(values)
            if isinstance(value, BaseException):
                raise value
            return value

        monkeypatch.setattr(release, "_read_fresh_native_process_identity", read)
        result = release._read_fresh_parent_observation(10, "100", 20, {10})
        assert result[0]["state"] == expected_state
        assert "parent_pid" not in result[0] or expected_state == "historical_parent_exited_pid_reused"


def test_native_parent_observation_rejects_still_active_exit_code(monkeypatch):
    result = {
        "pid": 20,
        "creation": "100",
        "state": "exited",
        "exit_code": 259,
        "exit_proof": {
            "handle_state": "exited",
            "authoritative_win32_process": "absent",
            "creation": "100",
        },
        "source_provenance": {
            "authoritative_win32_process": "absent",
            "native_status": "STILL_ACTIVE",
        },
    }
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda *_args, **_kwargs: result,
    )

    with pytest.raises(
        RuntimeError,
        match="child_pid=10 parent_pid=20 read_stage=first-read .*exit_code=259",
    ) as error:
        release._read_fresh_parent_observation(10, "200", 20, {10})

    assert "native_status" in str(error.value)


def test_native_parent_observation_records_stable_live_parent(monkeypatch):
    first = _controlled_parent_identity(creation="100", parent_pid=7)
    second = _controlled_parent_identity(creation="100", parent_pid=7)
    reads = iter([first, second])
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda *_args, **_kwargs: next(reads),
    )

    result = release._read_fresh_parent_observation(10, "200", 20, {10})

    assert result == [
        {
            "pid": 20,
            "state": "readable_current_parent",
            "creation": "100",
            "parent_pid": 7,
            "cwd": "C:/work",
            "executable": "C:/parent.exe",
            "argv": ["C:/parent.exe", "--worker"],
            "argv_sha256": hashlib.sha256(b"C:/parent.exe\0--worker").hexdigest(),
            "native_command": "C:/parent.exe --worker",
            "native_command_sha256": hashlib.sha256(b"C:/parent.exe --worker").hexdigest(),
            "role": "measured current native process",
            "family_relation": "measured current native process identity",
            "read_errors": [],
            "listening_ports": [],
            "source_provenance": {"reader": "controlled test"},
            "module_paths": [],
            "files": [],
            "ports": [],
            "relation": "current parent of exact child identity",
        }
    ]


def test_native_parent_observation_reports_read_stage_for_unreadable_second_read(monkeypatch):
    def read(pid, *_args, **_kwargs):
        if not hasattr(read, "called"):
            read.called = True
            return _controlled_parent_identity(pid=pid, creation="100")
        raise release._FreshProcessUnreadable("access denied")

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", read)

    with pytest.raises(RuntimeError, match="child_pid=10 parent_pid=20 read_stage=second-read") as error:
        release._read_fresh_parent_observation(10, "200", 20, {10})
    assert "access denied" in str(error.value)


def test_native_parent_observation_rejects_malformed_terminal_shape(monkeypatch):
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda *_args, **_kwargs: {
            "pid": 20,
            "creation": "100",
            "state": "exited",
            "parent_pid": 1,
        },
    )

    with pytest.raises(RuntimeError, match="exited parent lacks authoritative exit code"):
        release._read_fresh_parent_observation(10, "200", 20, {10})


@pytest.mark.parametrize(
    "result",
    [
        {"pid": 20, "creation": "100", "state": "exited", "exit_code": 0},
        {
            "pid": 20,
            "creation": "100",
            "state": "exited",
            "exit_code": 0,
            "exit_proof": {
                "handle_state": "exited",
                "authoritative_win32_process": "present",
                "creation": "100",
            },
            "source_provenance": {"authoritative_win32_process": "present"},
        },
    ],
)
def test_native_parent_observation_rejects_missing_or_contradictory_exit_proof(monkeypatch, result):
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda *_args, **_kwargs: result,
    )

    with pytest.raises(RuntimeError, match="exited parent (lacks authoritative exit proof|proof is incomplete or contradictory|provenance is incomplete or contradictory)"):
        release._read_fresh_parent_observation(10, "200", 20, {10})


def test_native_parent_observation_rejects_cycle_after_stable_live_binding(monkeypatch):
    first = _controlled_parent_identity(creation="100", parent_pid=1)
    second = _controlled_parent_identity(creation="100", parent_pid=10)
    reads = iter([first, second])
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda *_args, **_kwargs: next(reads),
    )

    with pytest.raises(RuntimeError, match="child_pid=10 parent_pid=20 read_stage=second-read"):
        release._read_fresh_parent_observation(10, "200", 20, {10})


def test_native_parent_observation_excludes_newer_pid_reuse(monkeypatch):
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda _pid, _read_state, _ancestry=None, _read_parent_observation=True: {
            "pid": 20,
            "creation": "200",
            "parent_pid": 1,
            "cwd": "C:/replacement",
            "executable": "C:/replacement.exe",
            "argv": ["replacement.exe"],
            "argv_sha256": hashlib.sha256(b"replacement.exe").hexdigest(),
            "native_command": "replacement.exe",
            "native_command_sha256": hashlib.sha256(b"replacement.exe").hexdigest(),
        },
    )

    assert release._read_fresh_parent_observation(10, "100", 20, {10}) == [
        {
            "pid": 20,
            "state": "historical_parent_exited_pid_reused",
            "current_creation": "200",
            "child_creation": "100",
            "current_parent_pid": 20,
        }
    ]


def test_native_parent_observation_rejects_ancestry_cycle(monkeypatch):
    with pytest.raises(RuntimeError, match="ancestry cycle"):
        release._read_fresh_parent_observation(10, "100", 20, {10, 20})


def test_native_parent_reuse_stops_after_limited_identity_read(monkeypatch):
    calls = []

    def read(pid, read_state, _ancestry=None, _read_parent_observation=True):
        calls.append((pid, read_state.limited_only))
        if len(calls) == 1:
            return {"pid": pid, "creation": "100", "executable": "C:/parent.exe"}
        return {"pid": pid, "creation": "200", "executable": "C:/replacement.exe"}

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", read)

    result = release._read_fresh_parent_observation(10, "100", 20, {10})

    assert result[0]["state"] == "historical_parent_exited_pid_reused"
    assert calls == [(20, True), (20, False)]


def _resource_identity(pid, *, cwd, executable="C:/tools/node.exe", argv=None, parent_observations=None):
    argv = argv or [executable, "worker.js"]
    command = " ".join(argv)
    return {
        "pid": pid,
        "creation": f"creation-{pid}",
        "parent_pid": 1,
        "cwd": cwd,
        "executable": executable,
        "native_command": command,
        "argv": argv,
        "argv_sha256": hashlib.sha256("\0".join(argv).encode()).hexdigest(),
        "native_command_sha256": hashlib.sha256(command.encode()).hexdigest(),
        "parent_observations": parent_observations or [{"pid": 1, "state": "verified_absent_historical_parent"}],
        "module_paths": [],
        "files": [],
        "ports": [],
    }


def test_resource_scope_excludes_generic_node_and_includes_exact_product_root():
    root = str(release.ROOT.resolve())
    unrelated = {
        "pid": 700,
        "name": "node.exe",
        "executable": "C:/tools/node.exe",
        "command": "node C:/unrelated/app.js",
    }
    unrelated_identity = _resource_identity(
        700,
        cwd="C:/Repo/Jarvis-feature-campaign/dashboard",
        argv=["node.exe", "C:/Repo/Jarvis-feature-campaign/dashboard/server.js"],
    )
    related = {
        "pid": 701,
        "name": "node.exe",
        "executable": "C:/tools/node.exe",
        "command": f"node {root}/frontend/server.js",
        "cwd": f"{root}/frontend",
    }
    related_identity = _resource_identity(
        701,
        cwd=f"{root}/frontend",
        argv=["node.exe", f"{root}/frontend/server.js"],
    )

    assert release._resource_process_is_relevant(unrelated, root, identity=unrelated_identity) is False
    assert release._resource_process_is_relevant(related, root, identity=related_identity) is True


def test_resource_scope_excludes_pid_42364_shaped_other_checkout():
    root = str(release.ROOT.resolve())
    identity = _resource_identity(
        42364,
        cwd="C:/Repo/Jarvis-feature-campaign/dashboard",
        argv=["node.exe", "C:/Repo/Jarvis-feature-campaign/dashboard/server.js"],
    )
    row = {
        "pid": 42364,
        "name": "node.exe",
        "executable": "C:/tools/node.exe",
        "command": "node C:/Repo/Jarvis-feature-campaign/dashboard/server.js",
        "cwd": "C:/Repo/Jarvis-feature-campaign/dashboard",
    }

    assert release._resource_process_is_relevant(row, root, identity=identity) is False


def test_resource_scope_accepts_checked_cmd_wrapper_relation():
    root = str(release.ROOT.resolve())
    identity = _resource_identity(
        707,
        cwd="C:/other",
        executable="C:/Windows/System32/cmd.exe",
        argv=["cmd.exe", "/c", "node", f"{root}/frontend/server.js"],
        parent_observations=[
            {
                "pid": 708,
                "state": "readable_current_parent",
                "relation": "current parent of exact child identity",
                "cwd": f"{root}/frontend",
                "argv": ["node.exe", f"{root}/frontend/server.js"],
            }
        ],
    )
    row = {"pid": 707, "name": "cmd.exe", "executable": identity["executable"]}

    assert release._resource_process_is_relevant(row, root, identity=identity) is True


def test_fresh_resource_scope_rejects_cmd_parent_text_fragments(monkeypatch, tmp_path):
    root = str(release.ROOT.resolve())
    monkeypatch.setattr(release, "EXTERNAL_PROOF_ROOT", tmp_path)
    parent_argv = [
        r"C:\\Python311\\python.exe",
        "-c",
        "print('subprocess.Popen child.wait invalid cmd contract')",
    ]
    parent_command = " ".join(parent_argv)
    parent = {
        "pid": 919,
        "state": "readable_current_parent",
        "creation": "parent-creation-919",
        "parent_pid": 1,
        "cwd": root,
        "executable": r"C:\\Python311\\python.exe",
        "argv": parent_argv,
        "argv_sha256": hashlib.sha256("\0".join(parent_argv).encode()).hexdigest(),
        "native_command": parent_command,
        "native_command_sha256": hashlib.sha256(parent_command.encode()).hexdigest(),
        "relation": "current parent of exact child identity",
    }
    identity = _resource_identity(
        920,
        cwd=f"{root}/frontend",
        executable=r"C:\\Windows\\System32\\cmd.exe",
        argv=["cmd.exe", "/c", "echo", "sample"],
        parent_observations=[parent],
    )
    identity["parent_pid"] = parent["pid"]
    reads = []
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda pid, *_args, **_kwargs: reads.append(pid),
    )
    with pytest.raises(RuntimeError, match="positive product-root relation"):
        release._fresh_resource_scope(
            {
                "processes": [
                    {
                        "pid": 920,
                        "name": "cmd.exe",
                        "executable": identity["executable"],
                        "cwd": f"{root}/frontend",
                        "parent_pid": 919,
                        "current_identity": identity,
                    }
                ],
                "holders": [],
                "ports": [],
                "read_errors": [],
            },
            root,
            scoped_ports=set(),
            preloaded_identities={920: identity},
        )


    assert reads == []


def test_resource_scope_keeps_cmd_wrapper_fail_closed_without_owned_parent_relation(tmp_path, monkeypatch):
    root = str(release.ROOT.resolve())
    monkeypatch.setattr(release, "EXTERNAL_PROOF_ROOT", tmp_path)
    identity = _resource_identity(
        920,
        cwd=f"{root}/frontend",
        executable=r"C:\\Windows\\System32\\cmd.exe",
        argv=["cmd.exe", "/c", "echo", "sample"],
        parent_observations=[{"pid": 25200, "state": "verified_absent_parent"}],
    )
    identity["parent_pid"] = 25200
    row = {
        "pid": 920,
        "name": "cmd.exe",
        "executable": identity["executable"],
        "cwd": identity["cwd"],
        "parent_pid": 25200,
        "current_identity": identity,
    }

    with pytest.raises(RuntimeError, match="positive product-root relation") as error:
        release._resource_process_is_relevant(row, root, identity=identity)

    message = str(error.value)
    assert "private_evidence=" in message
    assert identity["native_command"] not in message


@pytest.mark.parametrize(
    ("native_holder_module_paths", "scoped_port_records"),
    [(('C:/product/lightningcss.node',), ()), ((), ((4100, 920),))],
)
def test_resource_scope_holders_and_ports_override_checked_cmd_protection(
    native_holder_module_paths, scoped_port_records
):
    root = str(release.ROOT.resolve())
    identity = _resource_identity(
        920,
        cwd=f"{root}/frontend",
        executable=r"C:\\Windows\\System32\\cmd.exe",
        argv=["cmd.exe", "/c", "echo", "sample"],
    )

    assert release._resource_process_is_relevant(
        {"pid": 920, "name": "cmd.exe", "executable": identity["executable"]},
        root,
        identity=identity,
        native_holder_module_paths=native_holder_module_paths,
        scoped_port_records=scoped_port_records,
    ) is True


def test_resource_scope_accepts_current_holder_and_scoped_port_evidence():
    root = str(release.ROOT.resolve())
    native = (release.SCRIPT_ROOT / release.HOST_NATIVE_MODULE).resolve().as_posix()
    holder_identity = _resource_identity(708, cwd="C:/other")
    holder = {
        "pid": 708,
        "name": "service.exe",
        "executable": holder_identity["executable"],
        "module_paths": [native],
    }
    port_identity = _resource_identity(709, cwd="C:/other")
    port_identity["ports"] = [3000]
    port = {"pid": 709, "name": "node.exe", "executable": port_identity["executable"]}

    assert release._resource_process_is_relevant(holder, root, identity=holder_identity) is True
    assert release._resource_process_is_relevant(port, root, identity=port_identity) is True


@pytest.mark.parametrize(
    ("resource_kind", "resources", "expected_relation"),
    [
        (
            "holder",
            lambda pid, native: {
                "processes": [{"pid": pid, "name": "service.exe", "executable": "C:/tools/service.exe", "parent_pid": 1}],
                "holders": [{"pid": pid, "module_paths": [native]}],
                "ports": [],
                "read_errors": [],
            },
            "native_holder_module_paths_by_pid",
        ),
        (
            "port",
            lambda pid, native: {
                "processes": [{"pid": pid, "name": "service.exe", "executable": "C:/tools/service.exe", "parent_pid": 1}],
                "holders": [],
                "ports": [{"port": 4100, "pid": pid}],
                "read_errors": [],
            },
            "scoped_port_records_by_pid",
        ),
    ],
)
def test_resource_scope_carries_selected_resource_relation_into_final_classifier(
    resource_kind, resources, expected_relation, monkeypatch
):
    root = str(release.ROOT.resolve())
    pid = 900
    native = str((release.SCRIPT_ROOT / release.HOST_NATIVE_MODULE).resolve())
    identity = _resource_identity(pid, cwd="C:/other", executable="C:/tools/service.exe")
    monkeypatch.setattr(release, "_read_fresh_native_process_identity", lambda *_args, **_kwargs: identity)

    result = release._fresh_resource_scope(
        resources(pid, native),
        root,
        scoped_ports={4100},
    )

    assert [entry["identity"]["pid"] for entry in result["relevant_processes"]] == [pid]
    assert result[expected_relation][pid]
    if resource_kind == "holder":
        assert result[expected_relation][pid] == (native,)
    else:
        assert result[expected_relation][pid] == ((4100, pid),)


def test_resource_scope_does_not_promote_unrelated_holder_or_unscoped_port():
    root = str(release.ROOT.resolve())
    identity = _resource_identity(901, cwd="C:/other", executable="C:/tools/service.exe")
    row = {"pid": 901, "name": "service.exe", "executable": identity["executable"]}
    unrelated_holder = {"pid": 901, "module_paths": ["C:/other/lightningcss.node"]}
    row["module_paths"] = unrelated_holder["module_paths"]
    unrelated_port_identity = _resource_identity(902, cwd="C:/other", executable="C:/tools/service.exe")
    unrelated_port_identity["ports"] = [43123]
    unrelated_port = {"pid": 902, "name": "service.exe", "executable": unrelated_port_identity["executable"]}

    assert release._resource_process_is_relevant(
        row,
        root,
        identity=identity,
        native_holder_module_paths=(),
        scoped_port_records=(),
    ) is False
    assert release._resource_process_is_relevant(
        unrelated_port,
        root,
        identity=unrelated_port_identity,
        native_holder_module_paths=(),
        scoped_port_records=(),
    ) is False


def test_resource_scope_preserves_generic_positive_relation_inconsistency_error():
    root = str(release.ROOT.resolve())
    identity = _resource_identity(903, cwd="C:/other", executable="C:/tools/service.exe")
    with pytest.raises(RuntimeError, match="positive product-root relation"):
        release._resource_process_is_relevant(
            {"pid": 903, "name": "service.exe", "executable": identity["executable"]},
            root,
            identity=identity,
            positive_product_relation=True,
        )


def test_resource_scope_retains_private_failure_identity_and_digest(tmp_path, monkeypatch):
    root = str(release.ROOT.resolve())
    identity = _resource_identity(
        903,
        cwd="C:/other",
        executable="C:/tools/service.exe",
        argv=["service.exe", "C:/other/service.js"],
    )
    row = {
        "pid": 903,
        "parent_pid": 1,
        "name": "service.exe",
        "executable": identity["executable"],
        "current_identity": identity,
    }
    monkeypatch.setattr(release, "EXTERNAL_PROOF_ROOT", tmp_path)
    monkeypatch.setattr(release, "_git", lambda *_args: "checkpoint-1511")

    with pytest.raises(RuntimeError) as error:
        release._resource_process_is_relevant(
            row,
            root,
            identity=identity,
            positive_product_relation=True,
            protected_relation={"pid": 903, "protected": False},
        )

    message = str(error.value)
    assert "private_evidence=" in message
    assert identity["native_command"] not in message
    evidence_path = Path(message.split("private_evidence=", 1)[1].split(";", 1)[0])
    payload = evidence_path.read_bytes()
    evidence = json.loads(payload)
    assert hashlib.sha256(payload).hexdigest() in message
    assert evidence["raw_process_row"] == row
    assert evidence["complete_current_identity"] == identity
    assert evidence["identity_binding"]["creation"] == identity["creation"]
    assert evidence["identity_binding"]["argv_sha256"] == identity["argv_sha256"]
    assert evidence["identity_binding"]["native_command_sha256"] == identity["native_command_sha256"]
    assert evidence["native_holder_module_paths"] == []
    assert evidence["scoped_port_records"] == []
    assert evidence["selected_relation"]["measured_product_relation"] is True
    assert evidence["protected_relation"] == {"pid": 903, "protected": False}
    assert evidence["source"]["revision"] == "checkpoint-1511"
    assert evidence["source"]["artifact_sha256"]
    source_path = Path(release.__file__).resolve()
    assert source_path.exists()
    assert source_path.name == "release.py"
    assert Path(evidence["source"]["artifact"]).resolve() == source_path
    assert evidence["source"]["artifact_sha256"] == hashlib.sha256(source_path.read_bytes()).hexdigest()
    assert "scripts/scripts" not in evidence["source"]["artifact"].replace("\\", "/")
    assert evidence["original_failure"]["type"] == "RuntimeError"
    assert evidence["original_failure"]["traceback"]
    if os.name != "nt":
        assert evidence_path.stat().st_mode & 0o777 == 0o600


def test_resource_scope_failure_evidence_write_is_fail_closed(monkeypatch):
    root = str(release.ROOT.resolve())
    identity = _resource_identity(904, cwd="C:/other", executable="C:/tools/service.exe")
    monkeypatch.setattr(
        release,
        "_record_private_resource_scope_failure",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("evidence destination denied")),
    )

    with pytest.raises(RuntimeError, match="original_failure=RuntimeError") as error:
        release._resource_process_is_relevant(
            {"pid": 904, "name": "service.exe", "executable": identity["executable"]},
            root,
            identity=identity,
            positive_product_relation=True,
        )

    assert "diagnostic_failure=OSError" in str(error.value)
    assert "evidence destination denied" not in str(error.value)


def test_private_resource_scope_evidence_resolves_the_real_release_source():
    assert release.SCRIPT_ROOT == Path(release.__file__).resolve().parents[1]
    source_path = Path(release.__file__).resolve()
    assert source_path.exists()
    assert source_path.name == "release.py"


def test_resource_scope_excludes_checked_protected_identity_with_product_relation():
    root = str(release.ROOT.resolve())
    identity = _resource_identity(
        904,
        cwd=root,
        executable=f"{root}/.venv/Scripts/python.exe",
        argv=["python.exe", "-m", "pytest", "scripts/tests"],
    )
    assert release._resource_process_is_relevant(
        {"pid": 904, "name": "python.exe", "cwd": root},
        root,
        identity=identity,
    ) is False


def _release_hook_scope_identity(root, *, parent_pid=25200, child_creation="200", parent_creation="100"):
    project_python = str(Path(root) / ".venv" / "Scripts" / "python.exe")
    script = str(Path(release.__file__).resolve())
    parent_argv = [
        "C:/JarvisDeploy/jarvis/.venv/Scripts/python.exe",
        "C:/JarvisDeploy/jarvis/service/worker.py",
    ]
    parent_command = " ".join(parent_argv)
    parent = {
        "pid": parent_pid,
        "state": "readable_current_parent",
        "relation": "current parent of exact child identity",
        "creation": parent_creation,
        "parent_pid": 1,
        "cwd": "C:/JarvisDeploy/jarvis",
        "executable": parent_argv[0],
        "argv": parent_argv,
        "argv_sha256": hashlib.sha256("\0".join(parent_argv).encode()).hexdigest(),
        "native_command": parent_command,
        "native_command_sha256": hashlib.sha256(parent_command.encode()).hexdigest(),
    }
    identity = _resource_identity(
        os.getpid(),
        cwd=root,
        executable=project_python,
        argv=[project_python, script, "prepare"],
        parent_observations=[parent],
    )
    identity["creation"] = child_creation
    identity["parent_pid"] = parent_pid
    return identity


def _release_hook_launcher_child_identity(root):
    identity = _release_hook_scope_identity(root)
    launcher = str(Path(root) / ".venv" / "Scripts" / "python.exe")
    script = str(Path(release.__file__).resolve())
    native_child = "C:/Users/Aayushman/AppData/Local/Programs/Python/Python311/python.exe"
    identity["executable"] = native_child
    identity["argv"][0] = native_child
    identity["native_command"] = " ".join(identity["argv"])
    identity["argv_sha256"] = hashlib.sha256("\0".join(identity["argv"]).encode()).hexdigest()
    identity["native_command_sha256"] = hashlib.sha256(identity["native_command"].encode()).hexdigest()
    parent = identity["parent_observations"][0]
    parent["cwd"] = root
    parent["executable"] = launcher
    parent["argv"] = [launcher, script, "prepare"]
    parent["native_command"] = " ".join(parent["argv"])
    parent["argv_sha256"] = hashlib.sha256("\0".join(parent["argv"]).encode()).hexdigest()
    parent["native_command_sha256"] = hashlib.sha256(parent["native_command"].encode()).hexdigest()
    return identity


def _release_hook_launcher_identity(root, hook):
    launcher = str(Path(root) / ".venv" / "Scripts" / "python.exe")
    script = str(Path(release.__file__).resolve())
    worker_argv = ["C:/JarvisDeploy/jarvis/.venv/Scripts/python.exe", "C:/JarvisDeploy/jarvis/service/worker.py"]
    worker_command = " ".join(worker_argv)
    worker = {
        "pid": 24000,
        "state": "readable_current_parent",
        "relation": "current parent of exact child identity",
        "creation": "50",
        "parent_pid": 1,
        "cwd": "C:/JarvisDeploy/jarvis",
        "executable": worker_argv[0],
        "argv": worker_argv,
        "argv_sha256": hashlib.sha256("\0".join(worker_argv).encode()).hexdigest(),
        "native_command": worker_command,
        "native_command_sha256": hashlib.sha256(worker_command.encode()).hexdigest(),
    }
    argv = [launcher, script, hook["argv"][2]]
    command = " ".join(argv)
    return _resource_identity(
        hook["parent_pid"],
        cwd=root,
        executable=launcher,
        argv=argv,
        parent_observations=[worker],
    ) | {
        "creation": hook["parent_observations"][0]["creation"],
        "parent_pid": worker["pid"],
        "native_command": command,
        "argv_sha256": hashlib.sha256("\0".join(argv).encode()).hexdigest(),
        "native_command_sha256": hashlib.sha256(command.encode()).hexdigest(),
    }


def _replace_release_hook_parent_argv(identity, argv):
    parent = identity["parent_observations"][0]
    parent["argv"] = argv
    parent["native_command"] = " ".join(argv)
    parent["argv_sha256"] = hashlib.sha256("\0".join(argv).encode()).hexdigest()
    parent["native_command_sha256"] = hashlib.sha256(parent["native_command"].encode()).hexdigest()


def _install_controlled_release_hook_binding(monkeypatch, command):
    identity = _release_hook_launcher_child_identity(str(release.ROOT.resolve()))
    identity["argv"][2] = command
    identity["native_command"] = " ".join(identity["argv"])
    identity["argv_sha256"] = hashlib.sha256(
        "\0".join(identity["argv"]).encode()
    ).hexdigest()
    identity["native_command_sha256"] = hashlib.sha256(
        identity["native_command"].encode()
    ).hexdigest()
    _replace_release_hook_parent_argv(
        identity,
        [
            identity["parent_observations"][0]["argv"][0],
            identity["parent_observations"][0]["argv"][1],
            command,
        ],
    )
    identity["release_hook_requested_command"] = command
    binding = release._ReleaseHookBinding(command=command, identity=identity)
    monkeypatch.setattr(
        release,
        "_capture_current_release_hook_binding",
        lambda _command: binding,
    )
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda *_args, **_kwargs: identity,
    )
    return binding


def _scope_resources(identity):
    return {
        "processes": [{
            "pid": identity["pid"],
            "name": "python.exe",
            "executable": identity["executable"],
            "cwd": identity["cwd"],
            "parent_pid": identity["parent_pid"],
            "current_identity": identity,
        }],
        "holders": [],
        "ports": [],
        "read_errors": [],
    }


def _gate_test_scope_identity(root, *, executable=None):
    project_python = executable or str(Path(root) / ".venv" / "Scripts" / "python.exe")
    parent_argv = ["C:/Windows/System32/services.exe"]
    parent_command = parent_argv[0]
    parent = {
        "pid": 25200,
        "state": "readable_current_parent",
        "relation": "current parent of exact child identity",
        "creation": "100",
        "cwd": "C:/Windows/System32",
        "executable": parent_argv[0],
        "argv": parent_argv,
        "argv_sha256": hashlib.sha256("\0".join(parent_argv).encode()).hexdigest(),
        "native_command": parent_command,
        "native_command_sha256": hashlib.sha256(parent_command.encode()).hexdigest(),
    }
    identity = _resource_identity(
        os.getpid(),
        cwd=root,
        executable=project_python,
        argv=[project_python, "-m", "pytest", "scripts/tests", "-q"],
        parent_observations=[parent],
    )
    identity["creation"] = "200"
    identity["parent_pid"] = 25200
    return identity


def test_fresh_resource_scope_accepts_the_complete_current_release_hook_contract(monkeypatch):
    root = str(release.ROOT.resolve())
    identity = _release_hook_scope_identity(root)
    monkeypatch.setattr(release, "_read_fresh_native_process_identity", lambda *_args, **_kwargs: identity)

    result = release._fresh_resource_scope(
        _scope_resources(identity),
        root,
        scoped_ports=set(),
        preloaded_identities={identity["pid"]: identity},
        observer_role="release_hook",
    )

    assert result["relevant_processes"] == []
    assert result["identities"][identity["pid"]] == identity


def test_fresh_resource_scope_accepts_the_configured_launcher_native_child_contract(monkeypatch):
    root = str(release.ROOT.resolve())
    identity = _release_hook_launcher_child_identity(root)
    identity["release_hook_requested_command"] = "prepare"
    monkeypatch.setattr(release, "_read_fresh_native_process_identity", lambda *_args, **_kwargs: identity)

    result = release._fresh_resource_scope(
        _scope_resources(identity),
        root,
        scoped_ports=set(),
        preloaded_identities={identity["pid"]: identity},
        observer_role="release_hook",
        observer_bootstrap_identity=identity,
    )

    assert result["relevant_processes"] == []


def test_fresh_resource_scope_hydrates_the_release_hook_observer_before_classification(monkeypatch):
    root = str(release.ROOT.resolve())
    bootstrap = _release_hook_launcher_child_identity(root)
    bootstrap["release_hook_requested_command"] = "prepare"
    fresh = dict(bootstrap)
    fresh["parent_observations"] = [dict(bootstrap["parent_observations"][0])]
    reads = []

    def read_identity(*_args, **_kwargs):
        reads.append(True)
        return fresh

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", read_identity)

    result = release._fresh_resource_scope(
        _scope_resources(fresh),
        root,
        scoped_ports=set(),
        preloaded_identities={fresh["pid"]: bootstrap},
        observer_role="release_hook",
        observer_bootstrap_identity=bootstrap,
    )

    assert result["relevant_processes"] == []
    assert result["identities"][fresh["pid"]] is fresh
    assert len(reads) == 3


def test_release_hook_bootstrap_captures_the_requested_command(monkeypatch):
    root = str(release.ROOT.resolve())
    identity = _release_hook_launcher_child_identity(root)
    launcher = _release_hook_launcher_identity(root, identity)
    reads = iter((identity, launcher))
    monkeypatch.setattr(release, "_read_fresh_native_process_identity", lambda *_args, **_kwargs: next(reads))

    captured = release._capture_current_release_hook_identity("prepare")

    assert captured["release_hook_requested_command"] == "prepare"
    assert captured["release_hook_launcher_identity"] == launcher


def test_release_hook_bootstrap_rejects_missing_launcher_evidence(monkeypatch):
    root = str(release.ROOT.resolve())
    identity = _release_hook_launcher_child_identity(root)
    identity["parent_observations"] = []
    monkeypatch.setattr(release, "_read_fresh_native_process_identity", lambda *_args, **_kwargs: identity)

    with pytest.raises(RuntimeError, match="field=parent_observations"):
        release._capture_current_release_hook_identity("prepare")


def test_release_hook_launcher_generation_is_protected_only_when_bound(monkeypatch):
    root = str(release.ROOT.resolve())
    hook = _release_hook_launcher_child_identity(root)
    hook["release_hook_requested_command"] = "prepare"
    launcher = _release_hook_launcher_identity(root, hook)
    hook["release_hook_launcher_identity"] = launcher
    resources = _scope_resources(launcher)
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda pid, *_args, **_kwargs: hook if pid == os.getpid() else launcher,
    )

    result = release._fresh_resource_scope(
        resources,
        root,
        scoped_ports=set(),
        preloaded_identities={launcher["pid"]: launcher, hook["pid"]: hook},
        observer_role="release_hook",
        observer_bootstrap_identity=hook,
    )

    assert result["relevant_processes"] == []
    assert any(
        entry["reason"] == "verified exact release-hook launcher generation"
        for entry in result["unrelated_exclusions"]
    )


def test_release_hook_launcher_resource_owner_overrides_launcher_protection(monkeypatch):
    root = str(release.ROOT.resolve())
    hook = _release_hook_launcher_child_identity(root)
    hook["release_hook_requested_command"] = "prepare"
    launcher = _release_hook_launcher_identity(root, hook)
    hook["release_hook_launcher_identity"] = launcher
    resources = _scope_resources(launcher)
    resources["ports"] = [{"port": 4100, "pid": launcher["pid"]}]
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda pid, *_args, **_kwargs: hook if pid == os.getpid() else launcher,
    )

    result = release._fresh_resource_scope(
        resources,
        root,
        scoped_ports={4100},
        preloaded_identities={launcher["pid"]: launcher, hook["pid"]: hook},
        observer_role="release_hook",
        observer_bootstrap_identity=hook,
    )

    assert [entry["identity"]["pid"] for entry in result["relevant_processes"]] == [launcher["pid"]]


@pytest.mark.parametrize("command", ["prepare", "observe", "execute", "verify"])
def test_release_hook_accepts_an_exact_invocation_from_a_non_product_cwd(monkeypatch, command):
    root = str(release.ROOT.resolve())
    identity = _release_hook_launcher_child_identity(root)
    non_product_cwd = "C:/JarvisDeploy/jarvis"
    identity["cwd"] = non_product_cwd
    identity["parent_observations"][0]["cwd"] = non_product_cwd
    identity["argv"][2] = command
    identity["native_command"] = " ".join(identity["argv"])
    identity["argv_sha256"] = hashlib.sha256(
        "\0".join(identity["argv"]).encode()
    ).hexdigest()
    identity["native_command_sha256"] = hashlib.sha256(
        identity["native_command"].encode()
    ).hexdigest()
    _replace_release_hook_parent_argv(
        identity,
        [
            identity["parent_observations"][0]["argv"][0],
            identity["parent_observations"][0]["argv"][1],
            command,
        ],
    )
    launcher = _release_hook_launcher_identity(root, identity)
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda pid, *_args, **_kwargs: identity if pid == os.getpid() else launcher,
    )

    binding = release._capture_current_release_hook_binding(command)

    assert binding.command == command
    assert binding.identity["cwd"] == non_product_cwd
    assert binding.identity["parent_observations"][0]["cwd"] == non_product_cwd


def test_release_hook_rejects_cwd_mutation_during_generation_revalidation(monkeypatch):
    root = str(release.ROOT.resolve())
    identity = _release_hook_launcher_child_identity(root)
    current = dict(identity)
    current["parent_observations"] = [dict(identity["parent_observations"][0])]
    current["cwd"] = "C:/JarvisDeploy/jarvis"
    current["parent_observations"][0]["cwd"] = "C:/JarvisDeploy/jarvis"
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda *_args, **_kwargs: current,
    )

    with pytest.raises(RuntimeError, match=r"field=cwd"):
        release._assert_current_release_hook_generation(
            identity,
            phase="after-classification",
            expected_identity=identity,
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda identity: identity["parent_observations"][0].__setitem__(
            "executable", "C:/copy/python.exe"
        ),
        lambda identity: identity["parent_observations"][0].__setitem__("creation", "300"),
        lambda identity: identity["argv"].__setitem__(2, "verify"),
        lambda identity: identity.__setitem__("argv_sha256", "0" * 64),
    ],
    ids=["copied-launcher", "parent-generation-reuse", "wrong-subcommand", "incoherent-argv-hash"],
)
def test_release_hook_bootstrap_rejects_invalid_launcher_child_contract(monkeypatch, mutate):
    root = str(release.ROOT.resolve())
    identity = _release_hook_launcher_child_identity(root)
    mutate(identity)
    monkeypatch.setattr(release, "_read_fresh_native_process_identity", lambda *_args, **_kwargs: identity)

    with pytest.raises(RuntimeError, match="current release-hook identity"):
        release._capture_current_release_hook_identity("prepare")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda identity: _replace_release_hook_parent_argv(
            identity, [identity["parent_observations"][0]["argv"][0], "-m", "pytest"]
        ),
        lambda identity: _replace_release_hook_parent_argv(
            identity, [identity["parent_observations"][0]["argv"][0], str(Path(release.ROOT) / "scripts" / "other.py"), "prepare"]
        ),
        lambda identity: _replace_release_hook_parent_argv(
            identity, [identity["parent_observations"][0]["argv"][0], identity["parent_observations"][0]["argv"][1], "verify"]
        ),
        lambda identity: identity["parent_observations"][0].__setitem__("native_command", "unrelated"),
        lambda identity: identity["parent_observations"][0].__setitem__("native_command", None),
    ],
    ids=[
        "unrelated-parent-command",
        "parent-script",
        "parent-subcommand",
        "parent-command-hash",
        "missing-parent-command",
    ],
)
def test_release_hook_bootstrap_rejects_unrelated_or_incoherent_launcher_parent(monkeypatch, mutate):
    root = str(release.ROOT.resolve())
    identity = _release_hook_launcher_child_identity(root)
    mutate(identity)
    monkeypatch.setattr(release, "_read_fresh_native_process_identity", lambda *_args, **_kwargs: identity)

    with pytest.raises(RuntimeError, match="current release-hook identity"):
        release._capture_current_release_hook_identity("prepare")


def test_release_hook_rejects_mismatched_parent_subcommand(monkeypatch):
    root = str(release.ROOT.resolve())
    identity = _release_hook_launcher_child_identity(root)
    _replace_release_hook_parent_argv(
        identity,
        [
            identity["parent_observations"][0]["argv"][0],
            identity["parent_observations"][0]["argv"][1],
            "verify",
        ],
    )
    monkeypatch.setattr(
        release, "_read_fresh_native_process_identity", lambda *_args, **_kwargs: identity
    )

    with pytest.raises(RuntimeError, match=r"field=parent\.argv\[2\]"):
        release._capture_current_release_hook_identity("prepare")


def test_fresh_resource_scope_accepts_the_explicit_gate_test_observer(monkeypatch):
    root = str(release.ROOT.resolve())
    identity = _gate_test_scope_identity(root)
    monkeypatch.setattr(release, "_read_fresh_native_process_identity", lambda *_args, **_kwargs: identity)

    result = release._fresh_resource_scope(
        _scope_resources(identity),
        root,
        scoped_ports=set(),
        preloaded_identities={identity["pid"]: identity},
        observer_role="gate_test",
        observer_bootstrap_identity=identity,
    )

    assert result["relevant_processes"] == []


def test_fresh_resource_scope_accepts_the_captured_native_gate_executable(monkeypatch):
    root = str(release.ROOT.resolve())
    native_executable = "C:/Python311/python.exe"
    identity = _gate_test_scope_identity(root, executable=native_executable)
    identity["argv"][0] = str(Path(root) / ".venv" / "Scripts" / "python.exe")
    identity["native_command"] = " ".join(identity["argv"])
    identity["argv_sha256"] = hashlib.sha256("\0".join(identity["argv"]).encode()).hexdigest()
    identity["native_command_sha256"] = hashlib.sha256(identity["native_command"].encode()).hexdigest()
    monkeypatch.setattr(release, "_read_fresh_native_process_identity", lambda *_args, **_kwargs: identity)

    result = release._fresh_resource_scope(
        _scope_resources(identity),
        root,
        scoped_ports=set(),
        preloaded_identities={identity["pid"]: identity},
        observer_role="gate_test",
        observer_bootstrap_identity=identity,
    )

    assert result["relevant_processes"] == []


def test_fresh_resource_scope_rejects_a_copied_interpreter_without_gate_identity(monkeypatch):
    root = str(release.ROOT.resolve())
    bootstrap = _gate_test_scope_identity(root, executable="C:/Python311/python.exe")
    copied = _gate_test_scope_identity(root, executable="C:/copy/python.exe")
    monkeypatch.setattr(release, "_read_fresh_native_process_identity", lambda *_args, **_kwargs: copied)

    with pytest.raises(RuntimeError, match=r"role=gate_test.*field=executable"):
        release._fresh_resource_scope(
            _scope_resources(copied),
            root,
            scoped_ports=set(),
            preloaded_identities={copied["pid"]: copied},
            observer_role="gate_test",
            observer_bootstrap_identity=bootstrap,
        )


def test_fresh_resource_scope_rejects_cross_role_observer(monkeypatch):
    root = str(release.ROOT.resolve())
    identity = _gate_test_scope_identity(root)
    monkeypatch.setattr(release, "_read_fresh_native_process_identity", lambda *_args, **_kwargs: identity)

    with pytest.raises(RuntimeError, match=r"role=release_hook.*field=argv"):
        release._fresh_resource_scope(
            _scope_resources(identity),
            root,
            scoped_ports=set(),
            preloaded_identities={identity["pid"]: identity},
            observer_role="release_hook",
        )


def test_fresh_resource_scope_rejects_arbitrary_same_interpreter_gate_observer(monkeypatch):
    root = str(release.ROOT.resolve())
    identity = _gate_test_scope_identity(root)
    identity["argv"] = [identity["argv"][0], "-c", "print('pytest')"]
    identity["native_command"] = " ".join(identity["argv"])
    identity["argv_sha256"] = hashlib.sha256("\0".join(identity["argv"]).encode()).hexdigest()
    identity["native_command_sha256"] = hashlib.sha256(identity["native_command"].encode()).hexdigest()
    monkeypatch.setattr(release, "_read_fresh_native_process_identity", lambda *_args, **_kwargs: identity)

    with pytest.raises(RuntimeError, match=r"role=gate_test.*field=argv.role"):
        release._fresh_resource_scope(
            _scope_resources(identity),
            root,
            scoped_ports=set(),
            preloaded_identities={identity["pid"]: identity},
            observer_role="gate_test",
        )


def test_fresh_resource_scope_accepts_the_provider_root_relative_release_script(monkeypatch):
    root = str(release.ROOT.resolve())
    identity = _release_hook_scope_identity(root)
    identity["argv"][1] = "scripts/release.py"
    identity["native_command"] = " ".join(identity["argv"])
    identity["argv_sha256"] = hashlib.sha256("\0".join(identity["argv"]).encode()).hexdigest()
    identity["native_command_sha256"] = hashlib.sha256(identity["native_command"].encode()).hexdigest()
    monkeypatch.setattr(release, "_read_fresh_native_process_identity", lambda *_args, **_kwargs: identity)

    result = release._fresh_resource_scope(
        _scope_resources(identity),
        root,
        scoped_ports=set(),
        preloaded_identities={identity["pid"]: identity},
        observer_role="release_hook",
    )

    assert result["relevant_processes"] == []


@pytest.mark.parametrize(
    ("field", "mutate"),
    [
        ("argv[1]", lambda identity: identity["argv"].__setitem__(1, "scripts/other.py")),
        ("argv[2]", lambda identity: identity["argv"].__setitem__(2, "unsupported")),
        ("executable", lambda identity: identity.__setitem__("executable", "C:/tools/python.exe")),
        ("argv[0]", _mutate_release_hook_argv_zero),
        ("cwd", lambda identity: identity.__setitem__("cwd", "")),
        (
            "parent_observations",
            lambda identity: identity["parent_observations"][0].__setitem__("relation", "other"),
        ),
        (
            "parent_observations",
            lambda identity: identity["parent_observations"][0].__setitem__("argv_sha256", "0" * 64),
        ),
        ("argv_sha256", lambda identity: identity.__setitem__("argv_sha256", "0" * 64)),
        (
            "native_command_sha256",
            lambda identity: identity.__setitem__("native_command_sha256", "0" * 64),
        ),
    ],
)
def test_release_hook_rejection_reports_the_exact_mismatched_field(field, mutate):
    root = str(release.ROOT.resolve())
    identity = _release_hook_scope_identity(root)
    mutate(identity)

    with pytest.raises(RuntimeError, match=rf"field={re.escape(field)} context=redacted"):
        release._assert_current_release_hook_generation(identity, phase="before-classification")


@pytest.mark.parametrize("resource_kind", ["module", "port"])
def test_fresh_resource_scope_resource_ownership_overrides_hook_protection(resource_kind, monkeypatch):
    root = str(release.ROOT.resolve())
    identity = _release_hook_scope_identity(root)
    resources = _scope_resources(identity)
    scoped_ports = set()
    monkeypatch.setattr(release, "_read_fresh_native_process_identity", lambda *_args, **_kwargs: identity)
    if resource_kind == "module":
        native_path = str((release.SCRIPT_ROOT / release.HOST_NATIVE_MODULE).resolve())
        resources["holders"] = [{"pid": identity["pid"], "module_paths": [native_path]}]
    else:
        resources["ports"] = [{"port": 4100, "pid": identity["pid"]}]
        scoped_ports = {4100}

    result = release._fresh_resource_scope(
        resources,
        root,
        scoped_ports=scoped_ports,
        preloaded_identities={identity["pid"]: identity},
        observer_role="release_hook",
    )

    assert [entry["identity"]["pid"] for entry in result["relevant_processes"]] == [identity["pid"]]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda identity: identity["parent_observations"][0].update(creation="300"),
        lambda identity: identity.update(parent_pid=25201),
        lambda identity: identity.update(argv=[identity["argv"][0], "-c", "print('sample')"]),
    ],
    ids=["changed-parent-generation", "mismatched-parent", "arbitrary-same-interpreter-command"],
)
def test_fresh_resource_scope_blocks_release_hook_lookalikes(tmp_path, monkeypatch, mutate):
    root = str(release.ROOT.resolve())
    identity = _release_hook_scope_identity(root)
    mutate(identity)
    identity["native_command"] = " ".join(identity["argv"])
    identity["argv_sha256"] = hashlib.sha256("\0".join(identity["argv"]).encode()).hexdigest()
    identity["native_command_sha256"] = hashlib.sha256(identity["native_command"].encode()).hexdigest()
    if identity["parent_observations"][0].get("pid") != identity["parent_pid"]:
        identity["parent_observations"][0]["pid"] = 25200
    monkeypatch.setattr(release, "EXTERNAL_PROOF_ROOT", tmp_path)
    monkeypatch.setattr(release, "_read_fresh_native_process_identity", lambda *_args, **_kwargs: identity)
    with pytest.raises(RuntimeError, match="current census observer identity"):
        release._fresh_resource_scope(
            _scope_resources(identity),
            root,
            scoped_ports=set(),
            preloaded_identities={identity["pid"]: identity},
            observer_role="release_hook",
        )


def test_fresh_resource_scope_rejects_an_incomplete_hook_identity(monkeypatch):
    root = str(release.ROOT.resolve())
    identity = _release_hook_scope_identity(root)
    identity.pop("parent_observations")
    monkeypatch.setattr(release, "_read_fresh_native_process_identity", lambda *_args, **_kwargs: identity)

    with pytest.raises(RuntimeError, match="identity fields=.*parent_observations"):
        release._fresh_resource_scope(
            _scope_resources(identity),
            root,
            scoped_ports=set(),
            preloaded_identities={identity["pid"]: identity},
            observer_role="release_hook",
        )


def test_fresh_resource_scope_rejects_release_hook_generation_change_during_classification(monkeypatch):
    root = str(release.ROOT.resolve())
    identity = _release_hook_scope_identity(root)
    changed = dict(identity)
    changed["creation"] = "300"
    reads = iter((identity, changed))
    monkeypatch.setattr(release, "_read_fresh_native_process_identity", lambda *_args, **_kwargs: next(reads))

    with pytest.raises(RuntimeError, match="identity changed during classification.*phase=after-classification"):
        release._fresh_resource_scope(
            _scope_resources(identity),
            root,
            scoped_ports=set(),
            preloaded_identities={identity["pid"]: identity},
            observer_role="release_hook",
        )


def test_fresh_host_process_census_accepts_the_current_release_hook_observer(monkeypatch):
    root = str(release.ROOT.resolve())
    identity = _release_hook_scope_identity(root)
    monkeypatch.setattr(release, "_read_fresh_native_process_identity", lambda *_args, **_kwargs: identity)
    monkeypatch.setattr(release, "_enumerate_fresh_frontend_resources", lambda: _scope_resources(identity))

    result = release._assert_fresh_host_process_census(_fresh_census_contract(count=0))

    assert result["states"] == {}
    assert result["unrelated_exclusions"] == []


def test_resource_scope_rejects_raw_protection_flag_when_product_relation_is_measured():
    root = str(release.ROOT.resolve())
    identity = _resource_identity(
        905,
        cwd=f"{root}/frontend",
        argv=["node.exe", f"{root}/frontend/server.js"],
    )
    with pytest.raises(RuntimeError, match="protected or unrelated process retains a positive"):
        release._resource_process_is_relevant(
            {
                "pid": 905,
                "name": "node.exe",
                "protected_or_unrelated_state": "protected",
            },
            root,
            identity=identity,
        )


@pytest.mark.parametrize(
    ("native_holder_module_paths", "scoped_port_records"),
    [(("C:/product/lightningcss.node",), ()), ((), ((4100, 906),))],
)
def test_resource_scope_holders_and_ports_override_checked_protection(
    native_holder_module_paths, scoped_port_records
):
    root = str(release.ROOT.resolve())
    identity = _resource_identity(
        906,
        cwd=root,
        executable=f"{root}/.venv/Scripts/python.exe",
        argv=["python.exe", "-m", "pytest", "scripts/tests"],
    )
    assert release._resource_process_is_relevant(
        {"pid": 906, "name": "python.exe", "cwd": root},
        root,
        identity=identity,
        native_holder_module_paths=native_holder_module_paths,
        scoped_port_records=scoped_port_records,
    ) is True


def test_canonical_windows_paths_use_case_and_component_boundaries():
    assert release._canonical_windows_path_identity("C:/Repo/App/./frontend") == release._canonical_windows_path_identity(
        "c:\\repo\\app\\frontend"
    )
    assert release._path_is_within("C:/Repo/App/frontend/server.js", "c:/repo/app")
    assert not release._path_is_within("C:/Repo/App-front/server.js", "c:/repo/app")


def test_resource_scope_denies_unprotected_product_root_python():
    root = str(release.ROOT.resolve())
    with pytest.raises(RuntimeError, match="unprotected product-root process"):
        release._resource_process_is_relevant(
            {
                "pid": 703,
                "name": "python.exe",
                "executable": f"{root}/.venv/Scripts/python.exe",
                "command": f"python {root}/scripts/release.py",
                "cwd": root,
            },
            root,
            identity=_resource_identity(
                703,
                cwd=root,
                executable=f"{root}/.venv/Scripts/python.exe",
                argv=["python.exe", f"{root}/worker.py"],
            ),
        )


def test_resource_scope_includes_frontend_node_with_measured_role():
    root = str(release.ROOT.resolve())
    assert release._resource_process_is_relevant(
        {
            "pid": 704,
            "name": "node.exe",
            "executable": "C:/tools/node.exe",
            "command": f"node {root}/frontend/server.js",
            "cwd": f"{root}/frontend",
        },
        root,
        identity=_resource_identity(
            704,
            cwd=f"{root}/frontend",
            argv=["node.exe", f"{root}/frontend/server.js"],
        ),
    ) is True


def test_resource_scope_excludes_unrelated_node_outside_product_root():
    assert release._resource_process_is_relevant(
        {
            "pid": 705,
            "name": "node.exe",
            "executable": "C:/tools/node.exe",
            "command": "node C:/other/frontend/server.js",
            "cwd": "C:/other/frontend",
        },
        str(release.ROOT.resolve()),
        identity=_resource_identity(
            705,
            cwd="C:/other/frontend",
            argv=["node.exe", "C:/other/frontend/server.js"],
        ),
    ) is False


def test_resource_scope_denies_frontend_node_without_measured_cwd():
    root = str(release.ROOT.resolve())
    incomplete_identity = _resource_identity(
        706,
        cwd=f"{root}/frontend",
        argv=["node.exe", f"{root}/frontend/server.js"],
    )
    incomplete_identity.pop("cwd")
    with pytest.raises(RuntimeError, match="identity fields=\['cwd'\]"):
        release._resource_process_is_relevant(
            {
                "pid": 706,
                "name": "node.exe",
                "executable": "C:/tools/node.exe",
                "command": f"node {root}/frontend/server.js",
            },
            root,
            identity=incomplete_identity,
        )


def test_gate_and_observation_ancestry_is_protected_by_identity():
    root = str(release.ROOT.resolve())
    identity = {
        "executable": "C:/tools/node.exe",
        "cwd": f"{root}/frontend",
        "argv": ["node", "frontend/server.js"],
        "native_command": "node frontend/server.js",
        "parent_observations": [
            {
                "executable": f"{root}/.venv/Scripts/python.exe",
                "cwd": root,
                "native_command": "python -m pytest scripts/tests",
            }
        ],
    }
    assert release._identity_is_protected(identity, root) is True


def test_resource_scope_denies_missing_relevance_fields():
    with pytest.raises(RuntimeError, match="process relevance is unreadable"):
        release._resource_process_is_relevant(
            {"pid": 701, "name": "node.exe", "executable": "C:/tools/node.exe"},
            str(release.ROOT.resolve()),
            identity=None,
        )


@pytest.mark.parametrize("pid", [0, 4])
def test_resource_scope_excludes_system_processes_without_full_fields(pid):
    assert release._resource_process_is_relevant(
        {"pid": pid, "name": "System"}, "C:/product"
    ) is False


@pytest.mark.parametrize("parent_pid", [False, 4.0, PidSubclass(4), None])
def test_fresh_process_row_rejects_malformed_parent_on_system_sentinel(parent_pid):
    with pytest.raises(RuntimeError, match="invalid or missing parent PID"):
        release._fresh_process_row_needs_identity(
            {"pid": 0, "parent_pid": parent_pid},
            product_root="C:/product",
            native_holder_pids=set(),
            scoped_port_owner_pids=set(),
            protected_pids=set(),
        )


@pytest.mark.parametrize("pid", [False, 0.0, 4.0])
def test_resource_scope_rejects_non_integer_sentinel_pids(pid):
    with pytest.raises(RuntimeError, match="invalid"):
        release._resource_process_is_relevant({"pid": pid, "name": "System"}, "C:/product")
    with pytest.raises(RuntimeError, match="invalid PID"):
        release._fresh_process_row_needs_identity(
            {"pid": pid, "name": "System"},
            product_root="C:/product",
            native_holder_pids=set(),
            scoped_port_owner_pids=set(),
            protected_pids=set(),
        )


def test_resource_scope_reads_normalized_current_identity_from_process_row():
    root = str(release.ROOT.resolve())
    identity = _resource_identity(
        710,
        cwd=f"{root}/frontend",
        argv=["node.exe", f"{root}/frontend/server.js"],
    )
    row = {
        "pid": 710,
        "name": "node.exe",
        "current_identity": identity,
    }

    assert release._resource_process_is_relevant(row, root) is True


def test_resource_scope_rejects_conflicting_normalized_identity_pid():
    identity = _resource_identity(712, cwd="C:/other")
    with pytest.raises(RuntimeError, match="conflicting PIDs"):
        release._resource_process_is_relevant(
            {"pid": 711, "name": "node.exe", "current_identity": identity},
            "C:/product",
        )


def test_resource_scope_rejects_uncertain_node_without_ownership_fields():
    with pytest.raises(RuntimeError, match="process relevance is unreadable"):
        release._resource_process_is_relevant(
            {"pid": 701, "name": "node.exe"},
            "C:/product",
            identity=None,
        )


def test_fresh_resource_scope_does_not_open_unsupported_inaccessible_process(monkeypatch):
    opened = []

    def read(pid, *_args, **_kwargs):
        opened.append(pid)
        raise AssertionError("unsupported process must not be opened")

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", read)
    result = release._fresh_resource_scope(
        {
            "processes": [
                {
                    "pid": 15008,
                    "name": "service.exe",
                    "executable": "C:/Windows/System32/service.exe",
                    "parent_pid": 1,
                }
            ],
            "holders": [],
            "ports": [],
            "read_errors": [],
        },
        str(release.ROOT.resolve()),
        scoped_ports={43123},
    )

    assert opened == []
    assert result["unrelated_exclusions"] == [
        {"pid": 15008, "reason": "outside measured frontend process family"}
    ]


def test_fresh_resource_scope_fails_for_inaccessible_frontend_candidate(monkeypatch):
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda _pid, *_args, **_kwargs: (_ for _ in ()).throw(release._FreshProcessUnreadable("WinError 5")),
    )
    with pytest.raises(RuntimeError, match="potentially relevant process identity failed: pid=15008"):
        release._fresh_resource_scope(
            {
                "processes": [
                    {"pid": 15008, "name": "node.exe", "executable": "C:/tools/node.exe", "parent_pid": 1}
                ],
                "holders": [],
                "ports": [],
                "read_errors": [],
            },
            str(release.ROOT.resolve()),
            scoped_ports={43123},
        )


def _protected_relation_parent_identity(*, creation="100", parent_pid=1):
    return {
        "pid": 901,
        "creation": creation,
        "parent_pid": parent_pid,
        "executable": "C:/tools/python.exe",
        "command": None,
        "source_provenance": {"reader": "controlled limited test"},
    }


def _protected_relation_child_identity(*, creation="200", parent_pid=901):
    return {
        "pid": 900,
        "creation": creation,
        "executable": "C:/tools/node.exe",
        "parent_pid": parent_pid,
        "command": None,
        "source_provenance": {"reader": "controlled limited test"},
    }


def _protected_relation_metadata(pid, *, parent_pid, executable, command):
    return {
        "pid": pid,
        "parent_pid": parent_pid,
        "executable": executable,
        "command": command,
    }


def _protected_relation_resources():
    return {
        "processes": [
            {"pid": 900, "name": "node.exe", "executable": "C:/tools/node.exe", "parent_pid": 901}
        ],
        "holders": [],
        "ports": [],
        "read_errors": [],
    }


def _patch_limited_protected_relation(monkeypatch, native_reads, metadata_reads):
    native = {pid: iter(values) for pid, values in native_reads.items()}
    metadata = {pid: iter(values) for pid, values in metadata_reads.items()}

    def read_native(pid, read_state, *_args, **_kwargs):
        assert read_state.limited_only is True
        return next(native[pid])

    def read_metadata(pid):
        return next(metadata[pid])

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", read_native)
    monkeypatch.setattr(release, "_read_current_protected_process_metadata", read_metadata)


def _run_limited_protected_relation(monkeypatch, child_reads=None, parent_reads=None, metadata_reads=None):
    child_reads = child_reads or [_protected_relation_child_identity(), _protected_relation_child_identity()]
    parent_reads = parent_reads or [_protected_relation_parent_identity(), _protected_relation_parent_identity()]
    metadata_reads = metadata_reads or {
        900: [
            _protected_relation_metadata(
                900, parent_pid=901, executable="C:/tools/node.exe", command="node server.js"
            ),
            _protected_relation_metadata(
                900, parent_pid=901, executable="C:/tools/node.exe", command="node server.js"
            ),
        ],
        901: [
            _protected_relation_metadata(
                901, parent_pid=1, executable="C:/tools/python.exe", command="python -m pytest"
            ),
            _protected_relation_metadata(
                901, parent_pid=1, executable="C:/tools/python.exe", command="python -m pytest"
            ),
        ],
    }
    _patch_limited_protected_relation(
        monkeypatch,
        {900: child_reads, 901: parent_reads},
        metadata_reads,
    )
    return release._fresh_resource_scope(
        _protected_relation_resources(),
        str(release.ROOT.resolve()),
        scoped_ports={43123},
        protected_pids={901},
    )


def test_fresh_resource_scope_accepts_limited_protected_ancestry_without_full_read(monkeypatch):
    result = _run_limited_protected_relation(monkeypatch)
    identity = result["identities"][900]
    assert result["unrelated_exclusions"] == [
        {"pid": 900, "reason": "verified protected ancestry"}
    ]
    assert "argv" not in identity
    assert "native_command" not in identity
    assert "module_paths" not in identity
    assert "ports" not in identity


@pytest.mark.parametrize("field", ["pid", "creation", "parent_pid", "executable"])
def test_limited_protected_identity_rejects_missing_native_fields(monkeypatch, field):
    child = _protected_relation_child_identity()
    child.pop(field)
    with pytest.raises(RuntimeError, match="potentially relevant process identity failed"):
        _run_limited_protected_relation(
            monkeypatch,
            child_reads=[child, _protected_relation_child_identity()],
        )


@pytest.mark.parametrize(
    ("child_reads", "parent_reads", "message"),
    [
        (
            [_protected_relation_child_identity(), _protected_relation_child_identity(creation="201")],
            None,
            "creation changed during binding",
        ),
        (
            [_protected_relation_child_identity(), _protected_relation_child_identity(parent_pid=902)],
            None,
            "parent (changed|metadata changed)",
        ),
        (
            [_protected_relation_child_identity(creation="100"), _protected_relation_child_identity(creation="100")],
            [_protected_relation_parent_identity(creation="200"), _protected_relation_parent_identity(creation="200")],
            "child predates parent generation",
        ),
        (
            [_protected_relation_child_identity(), _protected_relation_child_identity()],
            [_protected_relation_parent_identity(), _protected_relation_parent_identity(creation="101")],
            "parent generation changed",
        ),
    ],
)
def test_limited_protected_identity_rejects_generation_and_edge_changes(
    monkeypatch, child_reads, parent_reads, message
):
    with pytest.raises(RuntimeError, match=message):
        _run_limited_protected_relation(
            monkeypatch,
            child_reads=child_reads,
            parent_reads=parent_reads,
        )


def test_limited_protected_identity_rejects_command_metadata_change(monkeypatch):
    metadata = {
        900: [
            _protected_relation_metadata(
                900, parent_pid=901, executable="C:/tools/node.exe", command="node server.js"
            ),
            _protected_relation_metadata(
                900, parent_pid=901, executable="C:/tools/node.exe", command="node changed.js"
            ),
        ],
        901: [
            _protected_relation_metadata(
                901, parent_pid=1, executable="C:/tools/python.exe", command="python -m pytest"
            ),
            _protected_relation_metadata(
                901, parent_pid=1, executable="C:/tools/python.exe", command="python -m pytest"
            ),
        ],
    }
    with pytest.raises(RuntimeError, match="child command identity changed"):
        _run_limited_protected_relation(monkeypatch, metadata_reads=metadata)


def test_limited_protected_identity_rejects_missing_metadata(monkeypatch):
    metadata = {
        900: [
            {"pid": 900, "parent_pid": 901, "executable": "C:/tools/node.exe"},
        ],
        901: [
            _protected_relation_metadata(
                901, parent_pid=1, executable="C:/tools/python.exe", command="python -m pytest"
            ),
            _protected_relation_metadata(
                901, parent_pid=1, executable="C:/tools/python.exe", command="python -m pytest"
            ),
        ],
    }
    with pytest.raises(RuntimeError, match="metadata is incomplete or invalid"):
        _run_limited_protected_relation(monkeypatch, metadata_reads=metadata)


def test_fresh_resource_scope_records_protected_candidate_native_absence(monkeypatch, tmp_path):
    monkeypatch.setattr(release, "EXTERNAL_PROOF_ROOT", tmp_path)
    reads = []

    def read(pid, read_state, *_args, **_kwargs):
        reads.append((pid, read_state.limited_only))
        raise release._FreshProcessAbsent("absent")

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", read)
    result = release._fresh_resource_scope(
        {
            "processes": [{"pid": 900, "name": "node.exe", "executable": "C:/tools/node.exe", "parent_pid": 901}],
            "holders": [],
            "ports": [],
            "read_errors": [],
        },
        str(release.ROOT.resolve()),
        scoped_ports={43123},
        protected_pids={901},
    )

    assert reads == [(900, True)]
    assert result["terminal_exclusions"] == [{"pid": 900, "reason": "explicit native absence during census"}]
    assert result["private_diagnostics"][0]["kind"] == "native_absence"


def test_fresh_resource_scope_binds_protected_service_ancestry_before_classification(monkeypatch):
    opened = []

    def read(pid, *_args, **_kwargs):
        opened.append(("native", pid))
        identities = {
            7476: _full_current_identity(7476),
            8636: _full_current_identity(8636),
            15008: _full_current_identity(15008),
        }
        identities[7476]["executable"] = "C:/Windows/System32/svchost.exe"
        identities[8636]["executable"] = "C:/Python/python.exe"
        identities[15008]["executable"] = "C:/tools/node.exe"
        identities[7476]["parent_pid"] = 1
        identities[7476]["parent_observations"] = [{"pid": 1, "state": "windows_system_parent"}]
        identities[8636]["parent_pid"] = 7476
        identities[8636]["parent_observations"] = [{
            "pid": 7476,
            "state": "readable_current_parent",
            "creation": identities[7476]["creation"],
        }]
        identities[15008]["parent_pid"] = 8636
        identities[15008]["parent_observations"] = [{
            "pid": 8636,
            "state": "readable_current_parent",
            "creation": identities[8636]["creation"],
        }]
        return identities[pid]

    def read_metadata(pid):
        opened.append(("metadata", pid))
        identities = {
            7476: {"pid": 7476, "parent_pid": 1, "executable": "C:/Windows/System32/svchost.exe", "command": "svchost.exe -k service"},
            8636: {"pid": 8636, "parent_pid": 7476, "executable": "C:/Python/python.exe", "command": "python.exe browser.py"},
            15008: {"pid": 15008, "parent_pid": 8636, "executable": "C:/tools/node.exe", "command": "node.exe browser.js"},
        }
        return identities[pid]

    def read_service_metadata():
        opened.append(("service", 7476))
        return {
            "name": "JarvisBrowserService",
            "pid": 7476,
            "path_name": r"C:\\nssm\\nssm.exe install JarvisBrowserService C:\\tools\\service-host.exe",
        }

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", read)
    monkeypatch.setattr(release, "_read_current_protected_process_metadata", read_metadata)
    monkeypatch.setattr(release, "_read_current_protected_service_metadata", read_service_metadata)
    result = release._fresh_resource_scope(
        {
            "processes": [
                {
                    "pid": 7476,
                    "name": "svchost.exe",
                    "executable": "C:/Windows/System32/svchost.exe",
                    "command": "svchost.exe -k service",
                    "parent_pid": 1,
                },
                {
                    "pid": 8636,
                    "name": "python.exe",
                    "executable": "C:/Python/python.exe",
                    "command": "python.exe browser.py",
                    "parent_pid": 7476,
                },
                {
                    "pid": 15008,
                    "name": "node.exe",
                    "executable": "C:/tools/node.exe",
                    "command": "node.exe browser.js",
                    "parent_pid": 8636,
                },
            ],
            "holders": [],
            "ports": [],
            "protected_service": {"pid": 7476, "name": "JarvisBrowserService"},
            "read_errors": [],
        },
        str(release.ROOT.resolve()),
        scoped_ports={43123},
    )

    assert opened == [
        ("native", 7476),
        ("metadata", 7476),
        ("service", 7476),
        ("native", 7476),
        ("native", 8636),
        ("metadata", 8636),
        ("native", 8636),
        ("native", 15008),
        ("metadata", 15008),
        ("native", 15008),
    ]
    assert result["protected_pids"] == {7476, 8636, 15008}
    assert result["identities"][7476]["source_provenance"]["service_path_name"].startswith(
        r"C:\\nssm"
    )


def _protected_service_resources():
    return {
        "processes": [
            {"pid": 7476, "name": "svchost.exe", "executable": "C:/Windows/System32/svchost.exe", "command": "svchost.exe -k service", "parent_pid": 1},
            {"pid": 8636, "name": "python.exe", "executable": "C:/Python/python.exe", "command": "python.exe browser.py", "parent_pid": 7476},
        ],
        "holders": [],
        "ports": [],
        "protected_service": {"pid": 7476, "name": "JarvisBrowserService"},
        "read_errors": [],
    }


def _patch_protected_service_metadata(
    monkeypatch, *, executables=None, service_pid=7476, service_path_name="C:/nssm/nssm.exe install JarvisBrowserService C:/tools/service-host.exe"
):
    executables = executables or {7476: "C:/node.exe", 8636: "C:/node.exe"}

    def read_metadata(pid):
        parents = {7476: 1, 8636: 7476}
        commands = {7476: "svchost.exe -k service", 8636: "python.exe browser.py"}
        return {
            "pid": pid,
            "parent_pid": parents[pid],
            "executable": executables[pid],
            "command": commands[pid],
        }

    monkeypatch.setattr(release, "_read_current_protected_process_metadata", read_metadata)
    monkeypatch.setattr(
        release,
        "_read_current_protected_service_metadata",
        lambda: {
            "name": "JarvisBrowserService",
            "pid": service_pid,
            "path_name": service_path_name,
        },
    )


def test_protected_service_binding_keeps_nssm_path_as_metadata(monkeypatch):
    _patch_protected_service_metadata(monkeypatch)
    identities = {}

    def read(pid, *_args, **_kwargs):
        identity = _full_current_identity(pid)
        identity["executable"] = "C:/node.exe"
        identity["parent_pid"] = 1 if pid == 7476 else 7476
        identities[pid] = identity
        return identity

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", read)
    result = release._fresh_resource_scope(
        _protected_service_resources(),
        str(release.ROOT.resolve()),
        scoped_ports={43123},
    )

    assert result["protected_pids"] == {7476, 8636}
    assert result["identities"][7476]["source_provenance"]["service_path_name"].startswith("C:/nssm")


def test_protected_service_binding_accepts_canonical_executable_paths(monkeypatch):
    _patch_protected_service_metadata(
        monkeypatch,
        executables={7476: r"c:\\NODE.EXE", 8636: r"c:\\NODE.EXE"},
    )

    def read(pid, *_args, **_kwargs):
        identity = _full_current_identity(pid)
        identity["executable"] = "C:/node.exe"
        identity["parent_pid"] = 1 if pid == 7476 else 7476
        return identity

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", read)
    result = release._fresh_resource_scope(
        _protected_service_resources(),
        str(release.ROOT.resolve()),
        scoped_ports={43123},
    )

    assert result["protected_pids"] == {7476, 8636}


def test_protected_service_binding_rejects_changed_process_executable(monkeypatch):
    _patch_protected_service_metadata(
        monkeypatch,
        executables={7476: "C:/different.exe", 8636: "C:/node.exe"},
    )
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
            lambda pid, *_args, **_kwargs: {
            **_full_current_identity(pid),
            "executable": "C:/node.exe",
            "parent_pid": 1 if pid == 7476 else 7476,
        },
    )

    with pytest.raises(RuntimeError, match="native_executable=.*process_executable=.*service_path_name"):
        release._fresh_resource_scope(
            _protected_service_resources(),
            str(release.ROOT.resolve()),
            scoped_ports={43123},
        )


def test_protected_service_binding_rejects_changed_service_pid(monkeypatch):
    _patch_protected_service_metadata(monkeypatch, service_pid=9999)
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
            lambda pid, *_args, **_kwargs: {
            **_full_current_identity(pid),
            "executable": "C:/node.exe",
            "parent_pid": 1 if pid == 7476 else 7476,
        },
    )

    with pytest.raises(RuntimeError, match="protected service root changed during binding"):
        release._fresh_resource_scope(
            _protected_service_resources(),
            str(release.ROOT.resolve()),
            scoped_ports={43123},
        )


def test_protected_service_binding_rejects_missing_in_window_metadata(monkeypatch):
    _patch_protected_service_metadata(monkeypatch)

    def read_metadata(pid):
        return {
            "pid": pid,
            "parent_pid": 1 if pid == 7476 else 7476,
            "executable": "C:/node.exe",
        }

    monkeypatch.setattr(release, "_read_current_protected_process_metadata", read_metadata)
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
            lambda pid, *_args, **_kwargs: {
            **_full_current_identity(pid),
            "executable": "C:/node.exe",
            "parent_pid": 1 if pid == 7476 else 7476,
        },
    )

    with pytest.raises(RuntimeError, match="protected service identity is unreadable"):
        release._fresh_resource_scope(
            _protected_service_resources(),
            str(release.ROOT.resolve()),
            scoped_ports={43123},
        )


def test_protected_service_limited_identity_requires_parent_pid(monkeypatch):
    _patch_protected_service_metadata(monkeypatch)
    def read(pid, *_args, **_kwargs):
        identity = _full_current_identity(pid)
        identity["executable"] = "C:/node.exe"
        identity.pop("parent_pid")
        return identity

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", read)
    with pytest.raises(RuntimeError, match="invalid parent evidence"):
        release._fresh_resource_scope(
            _protected_service_resources(),
            str(release.ROOT.resolve()),
            scoped_ports={43123},
        )


def test_protected_service_limited_identity_rejects_conflicting_parent_pid(monkeypatch):
    _patch_protected_service_metadata(monkeypatch)
    def read(pid, *_args, **_kwargs):
        identity = _full_current_identity(pid)
        identity["executable"] = "C:/node.exe"
        identity["parent_pid"] = 999 if pid == 8636 else 1
        return identity

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", read)
    with pytest.raises(RuntimeError, match="protected service parent relation changed"):
        release._fresh_resource_scope(
            _protected_service_resources(),
            str(release.ROOT.resolve()),
            scoped_ports={43123},
        )


def test_protected_service_limited_identity_rejects_creation_change_between_reads(monkeypatch):
    _patch_protected_service_metadata(monkeypatch)
    calls = {}

    def read(pid, *_args, **_kwargs):
        calls[pid] = calls.get(pid, 0) + 1
        identity = _full_current_identity(pid)
        identity["executable"] = "C:/node.exe"
        if pid == 7476 and calls[pid] == 2:
            identity["creation"] = "changed-service-creation"
        return identity

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", read)
    with pytest.raises(RuntimeError, match="identity changed during binding"):
        release._fresh_resource_scope(
            _protected_service_resources(),
            str(release.ROOT.resolve()),
            scoped_ports={43123},
        )


@pytest.mark.parametrize(
    "resource_field",
    ["holder", "port"],
)
def test_fresh_resource_scope_fails_for_inaccessible_holder_or_port_owner(monkeypatch, resource_field):
    native = (release.SCRIPT_ROOT / release.HOST_NATIVE_MODULE).resolve().as_posix()
    resources = {
        "processes": [
            {
                "pid": 15008,
                "name": "DiscoverySrv.exe",
                "executable": "C:/Program Files/Bitdefender Agent/DiscoverySrv.exe",
                "parent_pid": 1,
            }
        ],
        "holders": [{"pid": 15008, "module_paths": [native]}] if resource_field == "holder" else [],
        "ports": [{"pid": 15008, "port": 43123}] if resource_field == "port" else [],
        "read_errors": [],
    }
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda _pid, *_args, **_kwargs: (_ for _ in ()).throw(release._FreshProcessUnreadable("WinError 5")),
    )

    with pytest.raises(RuntimeError, match="potentially relevant process identity failed: pid=15008"):
        release._fresh_resource_scope(
            resources,
            str(release.ROOT.resolve()),
            scoped_ports={43123},
            preloaded_identities={15008: {"pid": 15008, "creation": "replacement-15008"}},
        )


def test_resource_scope_excludes_unrelated_protected_row_without_executable():
    assert release._resource_process_is_relevant(
        {"pid": 702, "name": "service.exe", "protected_or_unrelated_state": "protected"},
        "C:/product",
        identity=_resource_identity(702, cwd="C:/other"),
    ) is False


def test_resource_scope_ignores_unrelated_native_module_and_ssh_port(monkeypatch):
    contract = _fresh_census_contract()
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda _pid, *_args, **_kwargs: (_ for _ in ()).throw(release._FreshProcessAbsent("absent")),
    )
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {
            "processes": [],
            "holders": [{"pid": 999, "module_paths": ["C:/other/module.node"]}],
            "ports": [{"port": 22, "pid": 999}],
            "read_errors": [],
        },
    )

    result = release._assert_fresh_host_process_census(contract)

    assert result["resources"]["ports"] == [{"port": 22, "pid": 999}]


def test_fresh_census_rejects_scoped_port_without_measured_owner(monkeypatch):
    contract = _fresh_census_contract()
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda _pid, *_args, **_kwargs: (_ for _ in ()).throw(release._FreshProcessAbsent("absent")),
    )
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {
            "processes": [],
            "holders": [],
            "ports": [{"port": 4100, "pid": 999}],
            "read_errors": [],
        },
    )

    with pytest.raises(RuntimeError, match="fresh resource census is unstable or unreadable"):
        release._assert_fresh_host_process_census(contract)


def test_fresh_reader_contract_has_no_shell_process_provider():
    source = release._read_fresh_native_process_identity.__code__.co_names

    assert "Popen" not in source
    assert "run" not in source
    assert "ReadProcessMemory" in source
    assert "NtQueryInformationProcess" in source
    assert "IsWow64Process2" in source


def test_native_reader_closes_full_handle_once_when_architecture_read_fails(monkeypatch):
    class FakeCall:
        def __init__(self, result):
            self.result = result
            self.argtypes = None
            self.restype = None
            self.call_count = 0
            self.calls = []

        def __call__(self, *args):
            self.call_count += 1
            self.calls.append(args)
            if callable(self.result):
                return self.result(*args)
            if isinstance(self.result, list):
                return self.result.pop(0)
            return self.result

    class FakeKernel32:
        def __init__(self):
            self.OpenProcess = FakeCall([123, 456])
            self.CloseHandle = FakeCall(1)
            self.GetProcessTimes = FakeCall(1)
            self.GetExitCodeProcess = FakeCall(
                lambda _handle, status: (setattr(status._obj, "value", 259) or 1)
            )
            self.QueryFullProcessImageNameW = FakeCall(
                lambda _handle, _flags, buffer, _length: (setattr(buffer, "value", "C:/node.exe") or 1)
            )
            self.IsWow64Process2 = FakeCall(0)
            self.ReadProcessMemory = FakeCall(1)
            self.NtQueryInformationProcess = FakeCall(0)

    kernel32 = FakeKernel32()
    monkeypatch.setattr(release.os, "name", "nt")
    monkeypatch.setattr(release.ctypes, "WinDLL", lambda name, **_: kernel32)
    monkeypatch.setattr(release.ctypes, "get_last_error", lambda: 5, raising=False)

    with pytest.raises(release._FreshProcessUnreadable, match="native architecture read failed"):
        release._read_fresh_native_process_identity(
            123, release._NativeReadState(expected_creation="0")
        )

    assert kernel32.CloseHandle.calls == [(123,), (456,)]


def _cleanup_record(state="absent"):
    expected = _full_current_identity(201)
    record = {"pid": 201, "state": state}
    for field in release._CURRENT_IDENTITY_FIELDS:
        record[f"expected_{field}"] = expected[field]
    record["expected_files"] = []
    record["expected_module_paths"] = []
    record["expected_creation"] = expected["creation"]
    if state == "absent":
        record["absence_proof"] = {
            "state": "verified_absent",
            "pid": 201,
            "expected_creation": expected["creation"],
            "native_error": 87,
        }
    else:
        current = _full_current_identity(201)
        current["creation"] = "replacement-201" if state == "reused" else expected["creation"]
        for field in release._CURRENT_IDENTITY_FIELDS:
            record[f"current_{field}"] = current[field]
        record["current_files"] = []
        record["current_module_paths"] = []
        record["current_creation"] = current["creation"]
    return record


def test_current_cleanup_observation_requires_complete_expected_and_explicit_absence():
    record = _cleanup_record()
    del record["expected_executable"]

    with pytest.raises(RuntimeError, match="expected_executable"):
        release._current_cleanup_observation({"observations": [record]}, "presence.json")


def test_current_cleanup_observation_uses_measured_absence_over_historical_source_state():
    record = _cleanup_record()
    record["source_state"] = "pid_reused"

    result = release._current_cleanup_observation({"observations": [record]}, "presence.json")

    assert result[201]["state"] == "absent"
    assert result[201]["source_state"] == "pid_reused"
    assert result[201]["absence_proof"]["native_error"] == 87


@pytest.mark.parametrize(
    "change",
    [
        lambda record: record["absence_proof"].update(native_error=5),
        lambda record: record["absence_proof"].update(pid=999),
        lambda record: record["absence_proof"].update(expected_creation="wrong"),
        lambda record: record.pop("absence_proof"),
    ],
)
def test_current_cleanup_observation_rejects_invalid_absence_proof(change):
    record = _cleanup_record()
    change(record)

    with pytest.raises(RuntimeError, match="absence proof"):
        release._current_cleanup_observation({"observations": [record]}, "presence.json")


def test_current_cleanup_observation_accepts_complete_reused_identity_and_rejects_changed_hash():
    record = _cleanup_record("reused")
    result = release._current_cleanup_observation({"observations": [record]}, "presence.json")
    assert result[201]["current_creation"] == "replacement-201"

    record["current_native_command_sha256"] = "0" * 64
    with pytest.raises(RuntimeError, match="current_native_command_sha256"):
        release._current_cleanup_observation({"observations": [record]}, "presence.json")


def test_prepare_validates_host_process_evidence_before_release_side_effects(monkeypatch):
    events = []
    monkeypatch.setattr(
        release,
        "_validate_host_process_evidence",
        lambda _observer_bootstrap_identity=None: (_ for _ in ()).throw(
            RuntimeError("host process evidence is missing")
        ),
    )
    monkeypatch.setattr(release, "_provider_payload", lambda _payload: events.append("payload"))

    with pytest.raises(RuntimeError, match="host process evidence"):
        release._prepare(valid_payload())
    assert events == []


def test_host_preparation_uses_one_ordered_production_pipeline(monkeypatch):
    events = []

    monkeypatch.setattr(
        release,
        "_validate_host_process_evidence",
        lambda _observer_bootstrap_identity=None: events.append("guard")
        or _validated_empty_host_process_evidence(),
    )
    monkeypatch.setattr(
        release,
        "_prove_host_native_release",
        lambda: events.append("native") or {"state": "restored"},
    )
    monkeypatch.setattr(
        release,
        "_prepare_frontend_dependencies",
        lambda _root=None: events.append("frontend") or {"dependency_findings": []},
    )
    monkeypatch.setattr(release, "_provision_live_verifier", lambda: events.append("python-browser"))
    monkeypatch.setattr(
        release,
        "_validate_browser_dependency_readiness",
        lambda _root=None, *, process=None: events.append("readiness")
        or {"process": process, "dependency_findings": []},
    )

    result = release._prepare_host(Path("C:/frontend"))

    assert events == ["guard", "native", "frontend", "python-browser", "guard", "readiness"]
    assert result["native_release"] == {"state": "restored"}


def test_host_preparation_success_serialization_bounds_private_process_proof(monkeypatch):
    sentinel = "sk-or-v1-" + ("9" * 24)
    process = {
        "root": "C:/private-host-evidence",
        "historical_identities": 145,
        "native_resource": "restored",
        "native_sha256": "a" * 64,
        "fresh_census": {
            "states": [{"pid": 7, "argv": ["node", sentinel]}],
            "identities": [{"pid": 7, "command": sentinel}],
            "replacements": [],
            "terminal_states": [],
            "transition_diagnostics": [],
            "port_owner_identities": [],
            "resources": {
                "processes": [{"pid": 7, "argv": ["node", sentinel]}],
                "holders": [],
                "ports": [],
                "read_errors": [],
            },
        },
    }
    monkeypatch.setattr(
        release, "_validate_host_process_evidence", lambda _observer_bootstrap_identity=None: process
    )
    monkeypatch.setattr(
        release, "_prove_host_native_release", lambda: {"state": "restored"}
    )
    monkeypatch.setattr(
        release,
        "_prepare_frontend_dependencies",
        lambda _root=None: {"dependency_findings": []},
    )
    monkeypatch.setattr(release, "_provision_live_verifier", lambda: None)
    monkeypatch.setattr(
        release,
        "_validate_browser_dependency_readiness",
        lambda _root=None, *, process=None: {
            "process": process,
            "dependency_findings": [],
            "nested_readiness": {"password": sentinel},
        },
    )

    result = release._prepare_host()
    serialized = json.dumps(result, sort_keys=True)

    assert sentinel not in serialized
    assert '"argv"' not in serialized
    assert '"identities"' not in serialized
    assert result["process_before"]["fresh_census"]["identity_count"] == 1
    assert result["proof_reference"]["files"] == list(release.HOST_PROCESS_EVIDENCE_FILES)


def test_main_redacts_nested_success_values_at_stdout_boundary(monkeypatch, capsys):
    sentinel = "fake-runtime-credential"
    _install_controlled_release_hook_binding(monkeypatch, "prepare")
    monkeypatch.setattr(release.sys, "argv", ["release.py", "prepare"])
    monkeypatch.setattr(release.sys, "stdin", io.StringIO("{}"))
    monkeypatch.setattr(release, "_require_project_python", lambda _command: None)
    monkeypatch.setattr(
        release,
        "_prepare",
        lambda _payload, *, observer_command=None, release_hook_binding=None: {
            "complete": True,
            "readiness": {"password": sentinel},
            "processes": [{"argv": [sentinel]}],
        },
    )

    assert release.main() == 0
    output = capsys.readouterr().out
    assert sentinel not in output
    assert '"processes": "<REDACTED>"' in output
    assert '"password": "<REDACTED>"' in output


def test_host_preparation_stops_before_dependent_work_when_guard_fails(monkeypatch):
    events = []

    monkeypatch.setattr(
        release,
        "_validate_host_process_evidence",
        lambda _observer_bootstrap_identity=None: (_ for _ in ()).throw(
            RuntimeError("guard failed")
        ),
    )
    for name in (
        "_prove_host_native_release",
        "_prepare_frontend_dependencies",
        "_provision_live_verifier",
    ):
        monkeypatch.setattr(release, name, lambda *args, _name=name, **kwargs: events.append(_name))

    with pytest.raises(RuntimeError, match="guard failed"):
        release._prepare_host()
    assert events == []


def test_host_preparation_stops_before_dependency_work_when_native_proof_fails(monkeypatch):
    events = []
    monkeypatch.setattr(
        release,
        "_validate_host_process_evidence",
        lambda _observer_bootstrap_identity=None: events.append("guard")
        or {"native_resource": "present"},
    )
    monkeypatch.setattr(
        release,
        "_prove_host_native_release",
        lambda: (_ for _ in ()).throw(RuntimeError("native proof failed")),
    )
    monkeypatch.setattr(
        release,
        "_prepare_frontend_dependencies",
        lambda *args, **kwargs: events.append("frontend"),
    )

    with pytest.raises(RuntimeError, match="native proof failed"):
        release._prepare_host()
    assert events == ["guard"]


def test_family_backed_live_identity_remains_for_narrow_approval_validation():
    record = {
        "pid": 52068,
        "expected_creation": "creation-52068",
        "current_creation": "creation-52068",
        "state": "live",
    }
    family = [{"pid": 52068, "creation": "creation-52068"}]

    result = release._current_cleanup_observation(
        {"observations": [record]}, "presence.json", family
    )

    assert result[52068]["state"] == "live"
    assert result[52068]["expected_identity"] == family[0]


def test_process_evidence_validation_uses_read_only_native_observation(monkeypatch):
    contract = {"root": Path("C:/evidence"), "family_records": [{}], "frontend": {}}
    monkeypatch.setattr(release, "_load_host_process_contract", lambda: contract)
    monkeypatch.setattr(release, "_collect_toolhelp_process_snapshot", lambda: _toolhelp_snapshot())
    monkeypatch.setattr(
        release,
        "_assert_fresh_host_process_census",
        lambda value, *, observer_bootstrap_identity=None, process_snapshot=None: {"states": []},
    )
    monkeypatch.setattr(
        release,
        "_observe_host_native_resource",
        lambda: {"state": "present", "fingerprint": ("fingerprint",), "sha256": "digest"},
    )
    monkeypatch.setattr(
        release,
        "_prove_host_native_release",
        lambda: (_ for _ in ()).throw(AssertionError("validation must not mutate the native resource")),
    )

    result = release._validate_host_process_evidence()

    assert result["native_resource"] == "present"
    assert result["native_fingerprint"] == ("fingerprint",)
    assert result["native_sha256"] == "digest"


def test_execute_validates_host_process_evidence_before_deployment_side_effects(monkeypatch):
    events = []
    monkeypatch.setattr(
        release,
        "_validate_host_process_evidence",
        lambda _observer_bootstrap_identity=None: (_ for _ in ()).throw(
            RuntimeError("host process evidence is missing")
        ),
    )
    monkeypatch.setattr(release, "_provider_payload", lambda _payload: events.append("payload"))
    monkeypatch.setattr(release, "_ssh", lambda _command: events.append("ssh"))

    with pytest.raises(RuntimeError, match="host process evidence"):
        release._execute(valid_payload())
    assert events == []


def test_native_fingerprint_ignores_access_time_only_changes(tmp_path):
    path = tmp_path / "native.node"
    path.write_bytes(b"native-bytes")
    before = os.lstat(path)
    preserved_fields = (
        "st_mode",
        "st_ino",
        "st_dev",
        "st_nlink",
        "st_uid",
        "st_gid",
        "st_size",
        "st_mtime",
        "st_mtime_ns",
        "st_ctime",
        "st_ctime_ns",
        "st_birthtime",
        "st_birthtime_ns",
    )
    after = SimpleNamespace(
        **{
            field: getattr(before, field)
            for field in preserved_fields
            if hasattr(before, field)
        },
        st_atime=before.st_atime + 1,
        st_atime_ns=before.st_atime_ns + 1_000_000_000,
    )

    assert release._native_fingerprint(path, before) == release._native_fingerprint(path, after)


def test_native_release_uses_script_root_when_dependency_root_is_patched(tmp_path, monkeypatch):
    native_path = tmp_path / release.HOST_NATIVE_MODULE
    native_path.parent.mkdir(parents=True)
    native_path.write_bytes(b"native-bytes")
    monkeypatch.setattr(release, "SCRIPT_ROOT", tmp_path)
    monkeypatch.setattr(release, "ROOT", tmp_path / "dependency-fixture")

    assert release._prove_host_native_release() == {"state": "restored"}
    assert native_path.read_bytes() == b"native-bytes"


def test_prepare_rejects_pure_input_before_host_evidence(monkeypatch):
    monkeypatch.setattr(
        release,
        "_validate_host_process_evidence",
        lambda: (_ for _ in ()).throw(RuntimeError("evidence must not run")),
    )

    with pytest.raises(RuntimeError, match="literal credential"):
        release._prepare(
            {
                **valid_payload(),
                "environment": {"OPENROUTER_API_KEY": "literal-target-secret"},
            }
        )


def test_historical_roles_use_measured_flags_paths_and_normalized_family():
    native_path = release.HOST_NATIVE_MODULE.as_posix()
    node_records = [
        {"pid": pid, "creation": f"creation-{pid}", "previously_loaded_native_module": pid <= 29}
        for pid in range(1, 117)
    ]
    lock_records = [
        {
            "pid": pid,
            "creation": f"creation-{pid}",
            "locked_module_loaded": pid <= 29,
            "loaded_module_paths": [native_path] if pid <= 29 else [],
        }
        for pid in range(1, 117)
    ]
    family_records = [
        {
            "pid": pid,
            "creation": f"creation-{pid}",
            "family_relation": release.HISTORICAL_FAMILY_RELATION,
            "role": "lightningcss_loader" if pid <= 29 else "related_test_family",
        }
        for pid in range(1, 117)
    ]
    family_records.extend(
        {
            "pid": pid,
            "creation": f"creation-{pid}",
            "family_relation": release.WRAPPER_FAMILY_RELATION,
            "role": "related_test_family",
        }
        for pid in range(117, 146)
    )

    roles, _ = release._derive_historical_roles(node_records, lock_records, family_records)

    assert {pid for (pid, _), record in roles.items() if record["role"] == "lightningcss_loader"} == set(range(1, 30))
    assert sum(
        record["family_relation"] == release.HISTORICAL_FAMILY_RELATION
        for record in family_records
    ) == 116
    assert sum(
        record["family_relation"] == release.WRAPPER_FAMILY_RELATION
        for record in family_records
    ) == 29


def test_normalized_family_binding_returns_flat_current_identity_and_parent_evidence():
    historical = {
        "pid": 42,
        "creation": "child-token",
        "script_paths": [],
        "argv_role": ["node", "postcss.js"],
    }
    parent_observations = [{"pid": 41, "state": "verified_absent_historical_parent"}]
    current = {
        "pid": 42,
        "creation": "child-token",
        "parent_pid": 41,
        "cwd": "C:/work/frontend",
        "executable": "C:/node.exe",
        "argv": ["node", "postcss.js"],
        "argv_sha256": "a" * 64,
        "native_command_sha256": "b" * 64,
        "module_paths": [],
        "files": [],
        "ports": [],
        "parent_observations": parent_observations,
        "role": "related_test_family",
        "family_relation": release.HISTORICAL_FAMILY_RELATION,
    }

    [bound] = release._bind_normalized_family_records([historical], [current])

    assert "current_observation" not in bound
    assert bound["parent_observations"] == parent_observations
    assert bound["parent_pid"] == 41
    assert bound["current_modules"] == []


def test_current_family_records_joins_the_real_normalized_and_raw_shapes():
    raw_records = []
    normalized_records = []
    for pid in range(1, 146):
        creation = f"creation-{pid}"
        argv = ["node.exe", f"script-{pid}.js"]
        argv_hash = hashlib.sha256("\0".join(argv).encode()).hexdigest()
        parent_observations = [{"pid": 9000 + pid, "state": "verified_absent_historical_parent"}]
        module_paths = [release.HOST_NATIVE_MODULE.as_posix()] if pid <= 29 else []
        raw = {
            "pid": pid,
            "creation": creation,
            "historically_recorded_node": pid <= 116,
            "parent_pid": 9000 + pid,
            "cwd": "C:/work/frontend",
            "executable": "C:/node.exe",
            "argv": argv,
            "parsed_argv_sha256": argv_hash,
            "command_sha256": "a" * 64,
            "module_paths": module_paths,
            "measured_listening_ports": [],
            "parent_observations": parent_observations,
        }
        normalized = {
            "pid": pid,
            "creation": creation,
            "parent_pid": 9000 + pid,
            "cwd": "C:/work/frontend",
            "executable": "C:/node.exe",
            "argv": argv,
            "argv_sha256": argv_hash,
            "native_command_sha256": "a" * 64,
            "module_paths": module_paths,
            "files": module_paths,
            "ports": [],
            "parent_observations": [
                {"pid": pid, "creation": creation, "parent_pid": 9000 + pid, "cwd": "C:/work/frontend", "executable": "C:/node.exe", "argv": argv, "argv_sha256": argv_hash, "native_command_sha256": "a" * 64, "relation": "measured selected family identity", "state": "readable_current_parent"},
                *parent_observations,
            ],
            "role": "lightningcss_loader" if pid <= 29 else "related_test_family",
            "family_relation": release.HISTORICAL_FAMILY_RELATION if pid <= 116 else release.WRAPPER_FAMILY_RELATION,
            "ownership_approved": False,
            "cleanup_approved": False,
        }
        raw_records.append(raw)
        normalized_records.append(normalized)

    value = {
        "schema": "citespan.node-family-current.v1",
        "ownership_approved": False,
        "cleanup_approved": False,
        "source_provenance": {"source_sha256": "source"},
        "observations": normalized_records,
    }
    raw_value = {
        "schema": "citespan.read-only-family-observation.v1",
        "ownership_approved": False,
        "cleanup_approved": False,
        "observations": raw_records,
    }

    result = release._current_family_records(value, "normalized.json", raw_value)

    assert len(result) == 145
    assert "native_command" not in result[0]
    assert result[0]["native_command_sha256"] == "a" * 64


def test_current_family_records_rejects_boolean_pid_before_identity_matching():
    value = {
        "schema": "citespan.node-family-current.v1",
        "ownership_approved": False,
        "cleanup_approved": False,
        "source_provenance": {"source_sha256": release.LEGACY_FAMILY_SOURCE_SHA256},
        "observations": [{"pid": True}, *({"pid": pid} for pid in range(2, 146))],
    }

    with pytest.raises(RuntimeError, match="invalid identity"):
        release._current_family_records(value, "normalized.json")


def _source_bytes_with_expected_hash(monkeypatch, value):
    source = json.dumps(value, separators=(",", ":")).encode("utf-8")
    monkeypatch.setattr(release, "LEGACY_FAMILY_SOURCE_SHA256", hashlib.sha256(source).hexdigest())
    return source


def _legacy_current_fixture():
    return json.loads(
        (release.HOST_PROCESS_EVIDENCE_ROOT / "legacy-node-current-981.json").read_text(
            encoding="utf-8"
        )
    )


def _legacy_current_source():
    return (release.HOST_PROCESS_EVIDENCE_ROOT / "legacy-node-current-981.json").read_bytes()


def test_family_source_hash_uses_raw_bytes_and_normalized_provenance(monkeypatch):
    legacy = {"schema": "citespan.read-only-family-observation.v1", "observations": []}
    normalized = {"source_provenance": {}}
    source = _source_bytes_with_expected_hash(monkeypatch, legacy)
    normalized["source_provenance"]["source_sha256"] = hashlib.sha256(source).hexdigest()

    release._assert_family_source_provenance(legacy, normalized, source)

    with pytest.raises(RuntimeError, match="bytes do not match"):
        release._assert_family_source_provenance(legacy, normalized, source + b" ")


def test_family_source_hash_rejects_mismatched_normalized_provenance(monkeypatch):
    legacy = {"schema": "citespan.read-only-family-observation.v1", "observations": []}
    source = _source_bytes_with_expected_hash(monkeypatch, legacy)
    with pytest.raises(RuntimeError, match="source_sha256"):
        release._assert_family_source_provenance(
            legacy,
            {"source_provenance": {"source_sha256": "0" * 64}},
            source,
        )


def test_legacy_current_accepts_exact_schema_less_observation_without_authority(monkeypatch):
    document = _legacy_current_fixture()
    source = _legacy_current_source()
    assert hashlib.sha256(source).hexdigest() == release.LEGACY_CURRENT_OBSERVATION_SHA256
    records = release._assert_legacy_current_observation(document, source)
    assert len(records) == 116
    assert records[0]["pid"] == document["nodes"][0]["historical_identity"]["pid"]

    with pytest.raises(RuntimeError, match="node-current-approval.v1"):
        release._current_observation_records(document, "citespan-node-current-approval.json")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.pop("ownership_approved"),
        lambda value: value.update({"schema": "unknown"}),
        lambda value: value.update({"ownership_approved": True}),
        lambda value: value.update({"process_stopped": "false"}),
        lambda value: value.update({"extra": True}),
    ],
)
def test_legacy_current_rejects_malformed_or_unknown_shape(monkeypatch, mutate):
    document = _legacy_current_fixture()
    mutate(document)
    source = json.dumps(document, separators=(",", ":")).encode()
    monkeypatch.setattr(release, "LEGACY_CURRENT_OBSERVATION_SHA256", hashlib.sha256(source).hexdigest())
    with pytest.raises(RuntimeError):
        release._assert_legacy_current_observation(document, source)


@pytest.mark.parametrize("field", ["process_stopped", "dependency_installed"])
def test_legacy_current_rejects_true_observation_state(field, monkeypatch):
    document = _legacy_current_fixture()
    document[field] = True
    source = json.dumps(document, separators=(",", ":")).encode()
    monkeypatch.setattr(release, "LEGACY_CURRENT_OBSERVATION_SHA256", hashlib.sha256(source).hexdigest())

    with pytest.raises(RuntimeError, match=f"explicit false state: field={field}"):
        release._assert_legacy_current_observation(document, source)


def test_legacy_current_rejects_altered_raw_bytes(monkeypatch):
    document = _legacy_current_fixture()
    source = _legacy_current_source()
    with pytest.raises(RuntimeError, match="bytes do not match"):
        release._assert_legacy_current_observation(document, source + b" ")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda record: record.pop("historical_identity"),
        lambda record: record.update({"unknown": True}),
        lambda record: record["current_identity"].update({"pid": 999999}),
        lambda record: record["parent_observation"].update({"unknown": True}),
    ],
)
def test_legacy_current_rejects_malformed_nested_observation(monkeypatch, mutate):
    document = _legacy_current_fixture()
    mutate(document["nodes"][1])
    source = json.dumps(document, separators=(",", ":")).encode()
    monkeypatch.setattr(release, "LEGACY_CURRENT_OBSERVATION_SHA256", hashlib.sha256(source).hexdigest())

    with pytest.raises(RuntimeError, match="current node observation"):
        release._assert_legacy_current_observation(document, source)


@pytest.mark.parametrize("field", ["host", "group_id", "kind"])
def test_legacy_current_rejects_changed_identity_continuity_field(monkeypatch, field):
    document = _legacy_current_fixture()
    record = document["nodes"][1]
    if field == "group_id":
        record["current_identity"][field] += 1
    elif field == "kind":
        record["current_identity"][field] = "ancestor"
    else:
        record["current_identity"][field] = "different-host"
    source = json.dumps(document, separators=(",", ":")).encode()
    monkeypatch.setattr(release, "LEGACY_CURRENT_OBSERVATION_SHA256", hashlib.sha256(source).hexdigest())

    expected = rf"identity continuity changed field={field}" if field != "kind" else r"current_identity\.kind"
    with pytest.raises(RuntimeError, match=expected):
        release._assert_legacy_current_observation(document, source)


def test_legacy_current_rejects_parent_identity_pid_mismatch(monkeypatch):
    document = _legacy_current_fixture()
    record = document["nodes"][1]
    record["parent_observation"]["identity"]["pid"] += 1
    source = json.dumps(document, separators=(",", ":")).encode()
    monkeypatch.setattr(release, "LEGACY_CURRENT_OBSERVATION_SHA256", hashlib.sha256(source).hexdigest())

    with pytest.raises(RuntimeError, match=r"parent_observation\.identity\.pid does not match parent_pid"):
        release._assert_legacy_current_observation(document, source)


def test_legacy_current_rejects_failed_parent_pid_mismatch(monkeypatch):
    document = _legacy_current_fixture()
    record = next(
        record
        for record in document["nodes"]
        if record["parent_observation"].get("read_failed") is True
    )
    record["parent_observation"]["pid"] += 1
    source = json.dumps(document, separators=(",", ":")).encode()
    monkeypatch.setattr(release, "LEGACY_CURRENT_OBSERVATION_SHA256", hashlib.sha256(source).hexdigest())

    with pytest.raises(
        RuntimeError,
        match=(
            r"failed parent observation PID does not match outer parent relation: "
            r"child_pid=.*outer_parent_pid=.*observed_failed_read_pid=.*"
        ),
    ):
        release._assert_legacy_current_observation(document, source)


def test_actual_family_source_bytes_bind_to_normalized_provenance():
    root = release.HOST_PROCESS_EVIDENCE_ROOT
    legacy_source = (root / "legacy-family-current-996.json").read_bytes()
    legacy = json.loads(legacy_source)
    normalized = json.loads((root / "citespan-node-family-current.v1.json").read_text(encoding="utf-8"))

    assert hashlib.sha256(legacy_source).hexdigest() == release.LEGACY_FAMILY_SOURCE_SHA256
    release._assert_family_source_provenance(legacy, normalized, legacy_source)

    with pytest.raises(RuntimeError, match="bytes do not match"):
        release._assert_family_source_provenance(legacy, normalized, legacy_source + b" ")

    normalized["source_provenance"]["source_sha256"] = "0" * 64
    with pytest.raises(RuntimeError, match="source_sha256"):
        release._assert_family_source_provenance(legacy, normalized, legacy_source)


def test_saved_host_process_contract_accepts_all_unchanged_inputs_without_side_effects(monkeypatch):
    evidence_root = release.HOST_PROCESS_EVIDENCE_ROOT
    expected_hashes = {
        "legacy-node-current-981.json": "0b99210c848ac97b4cafb56c1b4f58ae96c8f2ed63b56ce49850f759456f14a7",
        "legacy-family-current-996.json": "3baead04ca0457c12b7ab0aebb8b0afc834d5f371aab3cb5c12c844489548cf5",
    }
    for filename, expected in expected_hashes.items():
        assert hashlib.sha256((evidence_root / filename).read_bytes()).hexdigest() == expected

    def forbidden(*args, **kwargs):
        raise AssertionError("saved-evidence validation attempted a side effect")

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", forbidden)
    monkeypatch.setattr(release, "_terminate_host_installer_process", forbidden)
    monkeypatch.setattr(release, "_install_backend_dependencies", forbidden, raising=False)
    monkeypatch.setattr(release, "_execute_release", forbidden, raising=False)
    monkeypatch.setattr(release, "_verify_release", forbidden, raising=False)
    monkeypatch.setattr(sys, "dont_write_bytecode", True)

    result = release._load_host_process_contract()

    assert len(result["node_records"]) == 116
    assert len(result["family_records"]) == 145
    assert result["approval_records"] == []


def test_normalized_family_binding_rejects_missing_parent_evidence():
    historical = {"pid": 42, "creation": "child-token"}
    current = {
        "pid": 42,
        "creation": "child-token",
        "parent_observations": [],
    }

    with pytest.raises(RuntimeError, match="no parent observations"):
        release._bind_normalized_family_records([historical], [current])


def test_historical_roles_reject_cross_source_role_disagreement():
    node_records = [
        {"pid": pid, "creation": f"creation-{pid}", "previously_loaded_native_module": pid == 1}
        for pid in range(1, 117)
    ]
    lock_records = [
        {
            "pid": pid,
            "creation": f"creation-{pid}",
            "locked_module_loaded": pid == 1,
            "loaded_module_paths": [release.HOST_NATIVE_MODULE.as_posix()] if pid == 1 else [],
        }
        for pid in range(1, 117)
    ]
    family_records = [
        {
            "pid": pid,
            "creation": f"creation-{pid}",
            "family_relation": release.HISTORICAL_FAMILY_RELATION,
            "role": "related_test_family",
        }
        for pid in range(1, 117)
    ]
    family_records.extend(
        {
            "pid": pid,
            "creation": f"creation-{pid}",
            "family_relation": release.WRAPPER_FAMILY_RELATION,
            "role": "related_test_family",
        }
        for pid in range(117, 146)
    )

    with pytest.raises(RuntimeError, match="loader role disagrees"):
        release._derive_historical_roles(node_records, lock_records, family_records)


@pytest.mark.parametrize("value", [release.AUTHORIZED_LIVE_ORIGIN, release.AUTHORIZED_LIVE_ORIGIN + "/"])
def test_public_url_accepts_only_the_canonical_authorized_origin(value):
    assert release._public_url(valid_payload(live_url=value)) == release.AUTHORIZED_LIVE_ORIGIN


def test_public_url_derives_the_fixed_authorized_origin_when_provider_omits_url_fields():
    payload = valid_payload()
    for field in ("live_url", "public_url", "deployment_url"):
        payload.pop(field, None)

    assert release._public_url(payload) == release.AUTHORIZED_LIVE_ORIGIN


@pytest.mark.parametrize(
    "value",
    [
        "",
        "http://citespan.169.58.64.150.nip.io",
        "https://citespan.169.58.64.150.nip.io.evil.example",
        "https://user@citespan.169.58.64.150.nip.io",
        "https://citespan.169.58.64.150.nip.io:443",
        "https://citespan.169.58.64.150.nip.io/path",
        "https://citespan.169.58.64.150.nip.io?query=1",
        "https://other.example",
    ],
)
def test_public_url_rejects_unauthorized_origins(value):
    payload = valid_payload()
    payload.pop("live_url")
    if value is not None:
        payload["live_url"] = value

    with pytest.raises(RuntimeError, match="authorized|supply"):
        release._public_url(payload)


def test_public_url_rejects_conflicting_supplied_aliases():
    payload = valid_payload(
        live_url=release.AUTHORIZED_LIVE_ORIGIN,
        public_url="https://other.example",
    )

    with pytest.raises(RuntimeError, match="authorized|conflict"):
        release._public_url(payload)


def run_hook(command: str, payload: dict, **env: str) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    merged.pop("OPENROUTER_API_KEY", None)
    merged.pop("OPENAI_API_KEY", None)
    merged.update(env)
    return subprocess.run(
        [PYTHON, str(ROOT / "scripts" / "release.py"), command],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=merged,
        cwd=ROOT,
    )


def run_hook_in_process(monkeypatch, command: str, payload: dict, **env: str):
    stdout = io.StringIO()
    stderr = io.StringIO()
    observer_identity = _release_hook_scope_identity(str(release.ROOT.resolve()))
    observer_identity["argv"] = [observer_identity["argv"][0], observer_identity["argv"][1], command]
    observer_identity["native_command"] = " ".join(observer_identity["argv"])
    observer_identity["argv_sha256"] = hashlib.sha256(
        "\0".join(observer_identity["argv"]).encode()
    ).hexdigest()
    observer_identity["native_command_sha256"] = hashlib.sha256(
        observer_identity["native_command"].encode()
    ).hexdigest()
    expected_observer_identity = dict(observer_identity)
    expected_observer_identity["release_hook_requested_command"] = command
    merged = os.environ.copy()
    merged.pop("OPENROUTER_API_KEY", None)
    merged.pop("OPENAI_API_KEY", None)
    merged.update(env)
    monkeypatch.setattr(release.sys, "argv", ["release.py", command])
    monkeypatch.setattr(release.sys, "stdin", io.StringIO(json.dumps(payload)))
    monkeypatch.setattr(release.sys, "stdout", stdout)
    monkeypatch.setattr(release.sys, "stderr", stderr)
    monkeypatch.setattr(release, "_require_project_python", lambda _command: None)
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda _pid, _state, *_args, **_kwargs: observer_identity,
    )

    def prepare_host(*_args, observer_bootstrap_identity=None, **_kwargs):
        if command in {"prepare", "execute"}:
            assert observer_bootstrap_identity == expected_observer_identity
        return {"state": "completed"}

    monkeypatch.setattr(release, "_prepare_host", prepare_host)
    with patch.dict(os.environ, merged, clear=True):
        return subprocess.CompletedProcess(
            ["release.py", command], release.main(), stdout.getvalue(), stderr.getvalue()
        )


@pytest.mark.parametrize("command", ["prepare", "observe", "execute", "verify"])
def test_each_hook_emits_json_when_project_python_is_missing(command, capsys):
    private_path = Path("private-failure.json")
    with patch.object(
        release,
        "_require_project_python",
        side_effect=release._MissingProjectPythonPreflight(
            "release blocked: project Python is missing; private-path=/owner/secret command=cmd.exe pid=57564 secret=token "
            "traceback=private traceback"
        ),
    ) as require_python, patch.object(
        release, "_record_private_failure", return_value=private_path
    ), patch.object(sys, "argv", ["release.py", command]):
        assert release.main() == 1

    captured = capsys.readouterr()
    value = json.loads(captured.out)
    assert value["complete"] is False
    assert value["error"] == "release blocked: project Python is missing"
    assert value["failure_code"] == "operation_failed_private_evidence_recorded"
    assert value["private_evidence_status"] == "write_completed"
    assert str(private_path) not in captured.out + captured.err
    assert "private-path=/owner/secret" not in captured.out + captured.err
    assert "command=cmd.exe" not in captured.out + captured.err
    assert "pid=57564" not in captured.out + captured.err
    assert "secret=token" not in captured.out + captured.err
    assert "private traceback" not in captured.out + captured.err
    assert captured.err == "release %s failed; private failure evidence write completed\n" % command
    assert "durab" not in captured.out.lower() + captured.err.lower()
    require_python.assert_called_once_with(command)


@pytest.mark.parametrize("command", ["prepare", "observe", "execute", "verify"])
@pytest.mark.parametrize(
    "evidence_failure",
    [
        OSError("private evidence directory creation failed"),
        TypeError("private evidence serialization failed"),
        PermissionError("private evidence replace failed"),
    ],
)
def test_each_hook_emits_one_safe_json_object_when_private_failure_write_fails(
    command, evidence_failure, monkeypatch, capsys
):
    effects = []
    original_failure = (
        "private-path=/owner/secret command=cmd.exe pid=57564 secret=original-token "
        "traceback=original traceback"
    )
    evidence_failure.args = (
        "private-path=/evidence/secret command=ssh pid=57564 secret=evidence-token "
        "traceback=evidence traceback",
    )
    monkeypatch.setattr(
        release,
        "_require_project_python",
        lambda _command: (_ for _ in ()).throw(RuntimeError(original_failure)),
    )
    monkeypatch.setattr(
        release,
        "_record_private_failure",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(evidence_failure),
    )
    monkeypatch.setattr(release.sys, "argv", ["release.py", command])
    for handler_name in ("_prepare", "_observe", "_execute", "_verify"):
        monkeypatch.setattr(
            release,
            handler_name,
            lambda *_args, _handler=handler_name, **_kwargs: effects.append(_handler),
        )

    assert release.main() == 1
    assert effects == []

    captured = capsys.readouterr()
    output = captured.out.strip().splitlines()
    assert len(output) == 1
    value = json.loads(output[0])
    assert value["complete"] is False
    assert value["status"] == "fail"
    assert value["hook"] == command
    assert value["failure_code"] == "operation_and_private_evidence_persistence_failed"
    assert value["summary"] == "Dependent work stopped. The private evidence write did not complete."
    assert value["private_evidence_status"] == "write_failed"
    assert set(value) == {
        "complete",
        "failure_code",
        "hook",
        "private_evidence_status",
        "status",
        "summary",
    }
    assert captured.err == ""
    assert "private-path=/owner/secret" not in captured.out + captured.err
    assert "private-path=/evidence/secret" not in captured.out + captured.err
    assert "command=cmd.exe" not in captured.out + captured.err
    assert "command=ssh" not in captured.out + captured.err
    assert "pid=57564" not in captured.out + captured.err
    assert "secret=" not in captured.out + captured.err
    assert "traceback=" not in captured.out + captured.err
    assert "evidence_reference" not in value
    assert "evidence_digest" not in value


def test_release_private_failure_write_keeps_private_contents_after_write(tmp_path):
    with patch.object(release, "EXTERNAL_PROOF_ROOT", tmp_path):
        try:
            raise RuntimeError("private command and traceback details")
        except RuntimeError as exc:
            evidence_path = release._record_private_failure(
                "prepare", exc, {"private_state": "kept"}
            )

    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["command"] == "prepare"
    assert evidence["error"] == "private command and traceback details"
    assert evidence["state"] == {"private_state": "kept"}
    assert evidence["traceback"]


def test_prepare_returns_one_contract_object_without_secret_values(monkeypatch):
    result = run_hook_in_process(monkeypatch, "prepare", valid_payload(), DEMO_MODE="1")

    value = json.loads(result.stdout)
    assert result.returncode == 0, result.stderr
    assert value["complete"] is True
    assert value["product_name"] == "CiteSpan"
    assert "api_key" not in result.stdout.lower()


@pytest.mark.parametrize("command", ["prepare", "observe", "execute", "verify"])
def test_main_binds_every_release_hook_before_handler_effects(monkeypatch, command):
    identity = _release_hook_scope_identity(str(release.ROOT.resolve()))
    identity["argv"][2] = command
    identity["native_command"] = " ".join(identity["argv"])
    identity["argv_sha256"] = hashlib.sha256(
        "\0".join(identity["argv"]).encode()
    ).hexdigest()
    identity["native_command_sha256"] = hashlib.sha256(
        identity["native_command"].encode()
    ).hexdigest()
    identity["release_hook_requested_command"] = command
    binding = release._ReleaseHookBinding(command=command, identity=identity)
    calls = []

    monkeypatch.setattr(release, "_require_project_python", lambda _command: None)
    monkeypatch.setattr(release, "_read_input", lambda: valid_payload())
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda *_args, **_kwargs: identity,
    )
    monkeypatch.setattr(
        release, "_capture_current_release_hook_binding", lambda value: binding
    )

    def handler(_payload, *, release_hook_binding):
        calls.append(release_hook_binding)
        return {"complete": True}

    monkeypatch.setattr(release, "_prepare", handler)
    monkeypatch.setattr(release, "_observe", handler)
    monkeypatch.setattr(release, "_execute", handler)
    monkeypatch.setattr(release, "_verify", handler)
    monkeypatch.setattr(release.sys, "argv", ["release.py", command])

    assert release.main() == 0
    assert calls == [binding]


def test_main_stops_before_handler_when_release_hook_identity_is_missing(monkeypatch):
    effects = []
    monkeypatch.setattr(release, "_require_project_python", lambda _command: None)
    monkeypatch.setattr(release, "_read_input", lambda: valid_payload())
    monkeypatch.setattr(
        release,
        "_capture_current_release_hook_binding",
        lambda _command: (_ for _ in ()).throw(RuntimeError("identity missing")),
    )
    monkeypatch.setattr(
        release, "_observe", lambda *_args, **_kwargs: effects.append("observe")
    )
    monkeypatch.setattr(
        release, "_run_live_verifier", lambda *_args, **_kwargs: effects.append("verify")
    )
    monkeypatch.setattr(release.sys, "argv", ["release.py", "observe"])
    monkeypatch.setattr(
        release, "_record_private_failure", lambda *_args, **_kwargs: Path("failure.json")
    )

    assert release.main() == 1
    assert effects == []


def test_observe_rejects_wrong_release_hook_binding_before_ssh(monkeypatch):
    identity = _release_hook_scope_identity(str(release.ROOT.resolve()))
    identity["release_hook_requested_command"] = "prepare"
    binding = release._ReleaseHookBinding(command="observe", identity=identity)
    ssh_calls = []
    monkeypatch.setattr(release, "_ssh", lambda *_args, **_kwargs: ssh_calls.append(True))

    with pytest.raises(RuntimeError, match="command binding"):
        release._observe(valid_payload(), release_hook_binding=binding)

    assert ssh_calls == []


def test_verify_rejects_changed_release_hook_generation_before_live_verification(monkeypatch):
    identity = _release_hook_scope_identity(str(release.ROOT.resolve()))
    identity["release_hook_requested_command"] = "verify"
    binding = release._ReleaseHookBinding(command="verify", identity=identity)
    changed = dict(identity)
    changed["creation"] = "changed-generation"
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda *_args, **_kwargs: changed,
    )
    verifier_calls = []
    monkeypatch.setattr(
        release, "_run_live_verifier", lambda *_args, **_kwargs: verifier_calls.append(True)
    )

    with pytest.raises(RuntimeError, match="changed during classification|does not match"):
        release._verify(
            {**valid_payload(), "observation": {"deployment_id": "citespan-test"}},
            release_hook_binding=binding,
        )

    assert verifier_calls == []


def test_credential_scan_ignores_inert_scanner_source_but_checks_runtime_config():
    inert_source = (
        "SECRET_PATTERNS = (re.compile(r'neo4j_password\\s*[:=]...'),)\n"
        "NEO4J_PASSWORD=%s\\nPOSTGRES_PASSWORD=%s\\n"
    )

    assert release._credential_scan_findings(
        [
            ("scripts/release.py", inert_source),
            (
                "scripts/tests/test_release.py",
                'fixture = "NEO4J_PASSWORD=" + "synthetic-neo4j-password"',
            ),
            (".env", "NEO4J_" + "PASSWORD=real-runtime-secret"),
        ]
    ) == [".env"]


def test_credential_scan_reports_assignment_in_release_scanner_source():
    token = "sk-or-v1-" + ("1" * 20)
    findings = release._credential_scan_findings(
        [("scripts/release.py", f'OPENAI_API_KEY = "{token}"')]
    )

    assert findings == ["scripts/release.py"]


@pytest.mark.parametrize(
    "source",
    [
        'value = "{token}"\n',
        'def value():\n    return "{token}"\n',
        'client("{token}")\n',
    ],
)
def test_credential_scan_rejects_identical_raw_token_in_every_string_context(source):
    token = "sk-or-v1-" + ("A" * 25)

    assert release._credential_scan_findings(
        [("new_module.py", source.format(token=token))]
    ) == ["new_module.py"]


def test_credential_scan_rejects_real_value_on_fixture_named_credential_target():
    token = "sk-or-v1-" + ("1" * 20)
    source = f'openai_api_key_fixture = "{token}"\n'

    assert release._credential_scan_findings([("new_module.py", source)]) == [
        "new_module.py"
    ]


@pytest.mark.parametrize(
    "source",
    [
        'config = {"OPENAI_API_KEY": "test%s"}\n' % ("A" * 25),
        'config_fixture = {"OPENAI_API_KEY": "test%s"}\n' % ("A" * 25),
    ],
)
def test_credential_scan_reports_same_static_mapping_value_regardless_of_container_name(source):
    assert release._credential_scan_findings([("new_module.py", source)]) == [
        "new_module.py"
    ]


def test_credential_scan_reports_same_static_neo4j_value_on_fixture_named_target():
    source = 'fixture_neo4j_password = "test%s"\n' % ("A" * 25)

    assert release._credential_scan_findings([("new_module.py", source)]) == [
        "new_module.py"
    ]


def test_credential_scan_rejects_returned_mapping_credential_value():
    token = "sk-or-v1-" + ("1" * 20)
    source = f'def config():\n    return {{"OPENAI_API_KEY": "{token}"}}\n'

    assert release._credential_scan_findings([("new_module.py", source)]) == [
        "new_module.py"
    ]


def test_credential_scan_rejects_nested_returned_container_credential_value():
    token = "sk-or-v1-" + ("1" * 20)
    source = (
        'def config():\n'
        f'    return {{"settings": [{{"OPENAI_API_KEY": "{token}"}}]}}\n'
    )

    assert release._credential_scan_findings([("new_module.py", source)]) == [
        "new_module.py"
    ]


@pytest.mark.parametrize(
    "source",
    [
        f'config["OPENAI_API_KEY"] = "{SYNTHETIC_OPENROUTER_TOKEN}"\n',
        f'config[OPENAI_API_KEY] = "{SYNTHETIC_OPENROUTER_TOKEN}"\n',
    ],
)
def test_credential_scan_rejects_credential_key_subscript_assignment(source):
    assert release._credential_scan_findings([("new_module.py", source)]) == [
        "new_module.py"
    ]


@pytest.mark.parametrize(
    "name, source",
    [
        (
            "scripts/release.py",
            f'def config():\n    return {{"OPENAI_API_KEY": "{SYNTHETIC_OPENROUTER_TOKEN}"}}\n',
        ),
        (
            "scripts/tests/test_release.py",
            f'config["OPENAI_API_KEY"] = "{SYNTHETIC_OPENROUTER_TOKEN}"\n',
        ),
    ],
)
def test_credential_scan_rejects_credential_forms_in_scanner_and_test_files(name, source):
    assert release._credential_scan_findings([(name, source)]) == [name]


@pytest.mark.parametrize(
    "source",
    [
        'settings = {"neo4j_password": "real-" + "runtime-secret"}',
        f'openrouter_api_key = "sk-or-v1-" + "{SYNTHETIC_OPENROUTER_SUFFIX}"',
        'config.neo4j_password = "real-" + "runtime-secret"',
        'Neo4j_Password = "real-" + "runtime-secret"',
        f'openRouter_Api_Key = "{SYNTHETIC_OPENROUTER_TOKEN}"',
    ],
)
def test_credential_scan_detects_syntax_aware_python_credential_forms(source):
    assert release._credential_scan_findings([("new_module.py", source)]) == ["new_module.py"]


def test_credential_scan_detects_forms_inside_scanner_file():
    source = 'credentials = {"neo4j_password": "real-" + "runtime-secret"}\n'

    assert release._credential_scan_findings([("scripts/release.py", source)]) == [
        "scripts/release.py"
    ]


def test_credential_scan_checks_newly_tracked_python_files():
    with patch.object(
        release,
        "_tracked_text",
        return_value=[
            (
                "newly_tracked.py",
                'config = {"neo4j_password": "real-" + "runtime-secret"}',
            )
        ],
    ):
        assert release._credential_scan_findings(release._release_text()) == [
            "newly_tracked.py"
        ]


def test_credential_scan_has_no_inert_self_finding_in_complete_tracked_candidate():
    assert release._credential_scan_findings(release._release_text()) == []


def test_credential_scan_keeps_scanner_definitions_and_marked_fixtures_inert():
    source = (
        "SECRET_PATTERNS = (re.compile(r'neo4j_password\\s*[:=]...'),)\n"
        "TEST_FIXTURE = {\"neo4j_password\": \"synthetic-\" + \"test-password\"}\n"
    )

    assert release._credential_scan_findings(
        [("scripts/tests/test_release.py", source)]
    ) == []


def test_tracked_scan_rejects_large_renamed_forensic_content(tmp_path):
    suspect = tmp_path / "renamed-export.bin"
    suspect.write_bytes(b"SQLite format 3\x00" + (b"x" * (2 * 1024 * 1024)))
    (tmp_path / ".git").mkdir()
    with patch.object(release, "ROOT", tmp_path), patch.object(
        release.subprocess,
        "run",
        return_value=subprocess.CompletedProcess(["git"], 0, b"renamed-export.bin\0", b""),
    ):
        with pytest.raises(RuntimeError, match="forensic|binary"):
            release._tracked_text()


def test_tracked_scan_requires_a_real_git_checkout(tmp_path):
    with patch.object(release, "ROOT", tmp_path):
        with pytest.raises(RuntimeError, match="exact Git checkout"):
            release._tracked_names()


def test_tracked_scan_uses_git_ls_files_boundary(tmp_path):
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("safe", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    completed = subprocess.CompletedProcess(
        ["git", "ls-files", "-z"], 0, b"tracked.txt\0", b""
    )
    with patch.object(release, "ROOT", tmp_path), patch.object(
        release.subprocess, "run", return_value=completed
    ) as run:
        assert release._tracked_names() == ["tracked.txt"]
    assert run.call_args.args[0] == ["git", "ls-files", "-z"]


def test_canonical_ufdr_name_does_not_exempt_binary_content(tmp_path):
    sample = tmp_path / "demo_synthetic.ufdr"
    sample.write_bytes(b"PK\x03\x04synthetic")
    (tmp_path / ".git").mkdir()
    with patch.object(release, "ROOT", tmp_path), patch.object(
        release.subprocess,
        "run",
        return_value=subprocess.CompletedProcess(
            ["git", "ls-files", "-z"], 0, b"demo_synthetic.ufdr\0", b""
        ),
    ):
        with pytest.raises(RuntimeError, match="forensic|binary"):
            release._tracked_text()


def test_tracked_scan_accepts_reviewed_static_asset_only_with_known_type(tmp_path):
    asset = tmp_path / "frontend" / "public" / "mark.png"
    asset.parent.mkdir(parents=True)
    content = b"\x89PNG\r\n\x1a\nasset"
    asset.write_bytes(content)
    (tmp_path / ".git").mkdir()
    with patch.object(release, "ROOT", tmp_path), patch.object(
        release.subprocess,
        "run",
        return_value=subprocess.CompletedProcess(["git"], 0, b"frontend/public/mark.png\0", b""),
    ), patch.object(
        release,
        "REVIEWED_BINARY_MANIFEST",
        {"frontend/public/mark.png": (hashlib.sha256(content).hexdigest(), "png", "product_ui_asset")},
    ):
        assert release._tracked_text() == []


def test_current_tracked_binary_inventory_has_exact_manifest_coverage():
    tracked_binary_names = []
    for name in release._tracked_names():
        path = release.ROOT / name
        content = path.read_bytes()
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            is_binary = True
        else:
            is_binary = path.suffix.lower() in release.REVIEWED_BINARY_SUFFIXES
        if is_binary:
            tracked_binary_names.append(name)

    manifest_names = set(release.REVIEWED_BINARY_MANIFEST)
    assert set(tracked_binary_names) == manifest_names
    assert not manifest_names - set(release._tracked_names())
    for name in tracked_binary_names:
        path = release.ROOT / name
        record = release._manifest_binary_record(name, path, path.read_bytes()[:4096])
        assert record is not None


@pytest.mark.parametrize("name", ["frontend/app/unreviewed.png", "docs/release-proof/unreviewed.png"])
def test_tracked_scan_rejects_valid_binary_under_broad_prefix_without_exact_review(tmp_path, name):
    asset = tmp_path / name
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"\x89PNG\r\n\x1a\nunreviewed")
    (tmp_path / ".git").mkdir()
    with patch.object(release, "ROOT", tmp_path), patch.object(
        release.subprocess,
        "run",
        return_value=subprocess.CompletedProcess(["git"], 0, f"{name}\0".encode(), b""),
    ), patch.object(release, "REVIEWED_BINARY_MANIFEST", {}):
        with pytest.raises(RuntimeError, match="allowlisted|unreviewed"):
            release._tracked_text()


def test_tracked_scan_rejects_modified_exact_asset(tmp_path):
    asset = tmp_path / "frontend" / "public" / "mark.png"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"\x89PNG\r\n\x1a\nmodified")
    (tmp_path / ".git").mkdir()
    with patch.object(release, "ROOT", tmp_path), patch.object(
        release.subprocess,
        "run",
        return_value=subprocess.CompletedProcess(["git"], 0, b"frontend/public/mark.png\0", b""),
    ), patch.object(
        release,
        "REVIEWED_BINARY_MANIFEST",
        {"frontend/public/mark.png": ("0" * 64, "png", "product_ui_asset")},
    ):
        with pytest.raises(RuntimeError, match="digest mismatch"):
            release._tracked_text()


def test_tracked_scan_rejects_wrong_path_and_wrong_provenance(tmp_path):
    asset = tmp_path / "frontend" / "public" / "renamed.png"
    asset.parent.mkdir(parents=True)
    content = b"\x89PNG\r\n\x1a\nasset"
    asset.write_bytes(content)
    (tmp_path / ".git").mkdir()
    with patch.object(release, "ROOT", tmp_path), patch.object(
        release.subprocess,
        "run",
        return_value=subprocess.CompletedProcess(["git"], 0, b"frontend/public/renamed.png\0", b""),
    ), patch.object(
        release,
        "REVIEWED_BINARY_MANIFEST",
        {"frontend/public/renamed.png": (hashlib.sha256(content).hexdigest(), "png", "unreviewed")},
    ):
        with pytest.raises(RuntimeError, match="provenance"):
            release._tracked_text()

    with patch.object(release, "ROOT", tmp_path), patch.object(
        release.subprocess,
        "run",
        return_value=subprocess.CompletedProcess(["git"], 0, b"frontend/public/renamed.png\0", b""),
    ), patch.object(
        release,
        "REVIEWED_BINARY_MANIFEST",
        {"frontend/public/mark.png": (hashlib.sha256(content).hexdigest(), "png", "product_ui_asset")},
    ):
        with pytest.raises(RuntimeError, match="allowlisted"):
            release._tracked_text()


def test_tracked_scan_rejects_missing_or_ambiguous_manifest_provenance(tmp_path):
    asset = tmp_path / "frontend" / "public" / "mark.png"
    asset.parent.mkdir(parents=True)
    content = b"\x89PNG\r\n\x1a\nasset"
    asset.write_bytes(content)
    (tmp_path / ".git").mkdir()
    with patch.object(release, "ROOT", tmp_path), patch.object(
        release.subprocess,
        "run",
        return_value=subprocess.CompletedProcess(["git"], 0, b"frontend/public/mark.png\0", b""),
    ), patch.object(
        release,
        "REVIEWED_BINARY_MANIFEST",
        {"frontend/public/mark.png": (hashlib.sha256(content).hexdigest(), "png", "")},
    ):
        with pytest.raises(RuntimeError, match="provenance"):
            release._tracked_text()

    with patch.object(release, "ROOT", tmp_path), patch.object(
        release.subprocess,
        "run",
        return_value=subprocess.CompletedProcess(["git"], 0, b"frontend/public/mark.png\0", b""),
    ), patch.object(
        release,
        "REVIEWED_BINARY_MANIFEST",
        {"frontend/public/mark.png": (hashlib.sha256(content).hexdigest(), "png", "product_ui_asset", "duplicate")},
    ):
        with pytest.raises(RuntimeError, match="ambiguous"):
            release._tracked_text()


def test_tracked_scan_rejects_unknown_binary_static_asset(tmp_path):
    asset = tmp_path / "frontend" / "public" / "mark.png"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"not-an-image")
    (tmp_path / ".git").mkdir()
    with patch.object(release, "ROOT", tmp_path), patch.object(
        release.subprocess,
        "run",
        return_value=subprocess.CompletedProcess(["git"], 0, b"frontend/public/mark.png\0", b""),
    ):
        with pytest.raises(RuntimeError, match="unknown type"):
            release._tracked_text()


@pytest.mark.parametrize(
    ("suffix", "signature"),
    [(".ttf", b"\x00\x01\x00\x00"), (".otf", b"OTTO")],
)
def test_tracked_scan_accepts_valid_reviewed_font_formats(tmp_path, suffix, signature):
    asset = tmp_path / "ALEAPP" / "scripts" / "_elements" / "fonts" / f"font{suffix}"
    asset.parent.mkdir(parents=True)
    content = signature + b"font-data"
    asset.write_bytes(content)
    (asset.parents[4] / ".git").mkdir()
    with patch.object(release, "ROOT", tmp_path), patch.object(
        release.subprocess,
        "run",
        return_value=subprocess.CompletedProcess(
            ["git"], 0, f"ALEAPP/scripts/_elements/fonts/font{suffix}\0".encode(), b""
        ),
    ), patch.object(
        release,
        "REVIEWED_BINARY_MANIFEST",
        {str(asset.relative_to(tmp_path)).replace("\\", "/"): (hashlib.sha256(content).hexdigest(), "font", "vendor_ui_asset")},
    ):
        assert release._tracked_text() == []


def test_tracked_scan_rejects_disguised_reviewed_font(tmp_path):
    asset = tmp_path / "ALEAPP" / "scripts" / "_elements" / "fonts" / "font.ttf"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"not-a-font")
    (tmp_path / ".git").mkdir()
    with patch.object(release, "ROOT", tmp_path), patch.object(
        release.subprocess,
        "run",
        return_value=subprocess.CompletedProcess(
            ["git"], 0, b"ALEAPP/scripts/_elements/fonts/font.ttf\0", b""
        ),
    ):
        with pytest.raises(RuntimeError, match="unknown type"):
            release._tracked_text()


def test_prepare_cli_accepts_only_contract_payload_fields(monkeypatch):
    result = run_hook_in_process(
        monkeypatch,
        "prepare",
        {
            "action_key": "citespan-release",
            "intent": {"action_key": "citespan-release", "expected_commit": EXPECTED_COMMIT},
            "live_url": release.AUTHORIZED_LIVE_ORIGIN,
            "DEMO_MODE": "1",
        },
    )

    value = json.loads(result.stdout)
    assert result.returncode == 0, result.stderr
    assert value["complete"] is True
    assert value["release_config"]["route"].startswith("dedicated Caddy")


def test_prepare_ignores_unrelated_supervisor_llm_environment(monkeypatch):
    result = run_hook_in_process(
        monkeypatch,
        "prepare",
        valid_payload(),
        DEMO_MODE="1",
        **{
            "OPENROUTER_API_KEY": "supervisor-" + str("owned-value"),
            "OPENAI_API_KEY": "supervisor-" + str("owned-value"),
        },
    )

    value = json.loads(result.stdout)
    assert result.returncode == 0, result.stderr
    assert value["complete"] is True


def test_prepare_rejects_literal_target_credential():
    result = run_hook(
        "prepare",
        {
            **valid_payload(),
            "environment": {
                "OPENROUTER_" + "API_KEY": "literal-" + str("target-secret")
            },
        },
        DEMO_MODE="1",
    )

    value = json.loads(result.stdout)
    assert result.returncode != 0
    assert value["complete"] is False
    assert "literal credential" in value["error"]


def test_hook_rejects_missing_action_key_loudly():
    result = run_hook("prepare", {}, DEMO_MODE="1")

    value = json.loads(result.stdout)
    assert result.returncode != 0
    assert value["complete"] is False
    assert "action_key" in value["error"]


def test_prepare_reports_script_relative_project_python_and_demo_limits(monkeypatch):
    result = run_hook_in_process(monkeypatch, "prepare", valid_payload(), DEMO_MODE="1")

    value = json.loads(result.stdout)
    assert result.returncode == 0, result.stderr
    assert value["python"].endswith(".venv/Scripts/python.exe")
    assert value["demo_policy"] == {
        "mode": "1",
        "runtime": {"DEMO_MODE": "1", "CITESPAN_SYNTHETIC_ONLY": "1"},
        "upload": False,
        "reset_to_sample": True,
        "sample": "canonical synthetic UFDR",
    }


def test_prepare_enforces_synthetic_demo_mode_when_provider_and_environment_omit_it(
    monkeypatch,
):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    payload = valid_payload()
    payload.pop("DEMO_MODE")

    with patch.object(release, "_provision_live_verifier"):
        value = release._prepare(payload, validate_process_evidence=False)

    assert value["demo_policy"] == {
        "mode": "1",
        "runtime": {"DEMO_MODE": "1", "CITESPAN_SYNTHETIC_ONLY": "1"},
        "upload": False,
        "reset_to_sample": True,
        "sample": "canonical synthetic UFDR",
    }
    assert value["demo_policy"]["runtime"] == {
        "DEMO_MODE": "1",
        "CITESPAN_SYNTHETIC_ONLY": "1",
    }


@pytest.mark.parametrize("disabled", ["0", "false"])
def test_prepare_rejects_explicit_disabled_demo_mode_without_leaking_values(
    disabled,
    monkeypatch,
    capsys,
):
    _install_controlled_release_hook_binding(monkeypatch, "prepare")
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setattr(sys, "argv", ["release.py", "prepare"])
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({**valid_payload(), "DEMO_MODE": disabled})))
    monkeypatch.setattr(release, "_record_private_failure", lambda *args: Path("failure.json"))

    assert release.main() == 1

    captured = capsys.readouterr()
    value = json.loads(captured.out)
    assert value["complete"] is False
    assert "DEMO_MODE" in value["error"]
    assert SYNTHETIC_OPENROUTER_TOKEN not in captured.out + captured.err
    assert SYNTHETIC_OPENAI_TOKEN not in captured.out + captured.err


def test_prepare_rejects_explicit_disabled_environment_demo_mode(monkeypatch):
    payload = valid_payload()
    payload.pop("DEMO_MODE")
    monkeypatch.setenv("DEMO_MODE", "0")

    with pytest.raises(RuntimeError, match="DEMO_MODE"):
        release._prepare(payload, validate_process_evidence=False)


def test_observation_command_requires_demo_mode_in_runtime_and_backend_identity():
    command = release._observation_command()

    assert "DEMO_MODE=1" in command
    assert ".citespan-runtime.env" in command


@pytest.mark.parametrize(
    "field",
    ["demo_mode", "synthetic_only"],
)
def test_verify_rejects_missing_or_contradictory_remote_demo_evidence(field):
    observation = {
        "observed": True,
        "runtime_validated": True,
        "deployment_commit": EXPECTED_COMMIT,
        "live_url": release.AUTHORIZED_LIVE_ORIGIN,
        "deployment_id": "citespan-live",
        "synthetic_only": True,
        "demo_mode": "1",
        "demo_run_id": release.CANONICAL_DEMO_RUN_ID,
        "metadata_marker": release.CANONICAL_DEMO_MARKER,
        "demo_marker": release.CANONICAL_DEMO_MARKER,
    }
    observation[field] = False if field == "synthetic_only" else "0"

    with pytest.raises(RuntimeError, match="synthetic|DEMO_MODE"):
        release._verify({**valid_payload(), "observation": observation})


def test_verify_rejects_missing_remote_demo_mode_evidence():
    observation = {
        "observed": True,
        "runtime_validated": True,
        "deployment_commit": EXPECTED_COMMIT,
        "live_url": release.AUTHORIZED_LIVE_ORIGIN,
        "deployment_id": "citespan-live",
        "synthetic_only": True,
        "demo_run_id": release.CANONICAL_DEMO_RUN_ID,
        "metadata_marker": release.CANONICAL_DEMO_MARKER,
        "demo_marker": release.CANONICAL_DEMO_MARKER,
    }

    with pytest.raises(RuntimeError, match="DEMO_MODE"):
        release._verify({**valid_payload(), "observation": observation})


@pytest.mark.parametrize("demo_mode", ["0", False, 1, "true", None])
def test_observe_rejects_invalid_remote_demo_mode_evidence(demo_mode):
    observed = {
        "deployment_commit": EXPECTED_COMMIT,
        "live_url": release.AUTHORIZED_LIVE_ORIGIN,
        "deployment_id": "citespan-test",
        "backend_port": 18000,
        "frontend_port": 18001,
        "static_container": "citespan-test-static-1",
        "static_content_dir": "/opt/citespan/.citespan-backups/1/static-1",
        "synthetic_only": True,
        "demo_mode": demo_mode,
        "demo_run_id": release.CANONICAL_DEMO_RUN_ID,
        "metadata_marker": release.CANONICAL_DEMO_MARKER,
        "demo_marker": release.CANONICAL_DEMO_MARKER,
    }

    with patch.object(release, "_ssh", return_value=json.dumps(observed)), pytest.raises(
        RuntimeError, match="DEMO_MODE"
    ):
        release._observe(valid_payload())


def test_observe_accepts_the_deployment_provider_payload_without_argv():
    payload = valid_payload()
    with patch.object(release, "_ssh", return_value="NOT_DEPLOYED"):
        value = release._observe(payload)
    assert value["action_key"] == "citespan-release"
    assert value["observed"] is False


def test_execute_fails_closed_without_deployment_evidence():
    with patch.object(release, "_critical_dependency_findings", return_value=[]), patch.object(
        release, "_branding_findings", return_value=[]
    ), patch.object(
        release,
        "_validate_host_process_evidence",
        return_value=_validated_empty_host_process_evidence(),
    ), patch.object(
        release, "_prepare_host", return_value={"state": "completed"}
    ), patch.object(release, "_ssh", return_value="NOT_DEPLOYED"):
        with pytest.raises(RuntimeError, match="deployment did not produce strict remote commit evidence"):
            release._execute(valid_payload())


def test_deployment_command_executes_checked_recovery_and_restores_prior_state(bash_tmp_path):
    command = release._deployment_command(valid_payload())
    start = command.index("rollback() {")
    end = command.index("\ntrap rollback EXIT\n", start)
    rollback_function = command[start:end]

    tmp_path = bash_tmp_path
    deploy_root = tmp_path / "deploy"
    caddy_root = tmp_path / "etc"
    bin_root = tmp_path / "bin"
    for path in (deploy_root, caddy_root, bin_root):
        path.mkdir(parents=True)
    (deploy_root / ".citespan-deployment.json").write_text(
        '{"deployment_id":"citespan-previous"}\n', encoding="utf-8"
    )
    (deploy_root / ".citespan-demo-marker.json").write_text(
        '{"marker":"previous"}\n', encoding="utf-8"
    )
    (deploy_root / ".citespan-runtime.env").write_text(_complete_runtime_fixture(), encoding="utf-8")
    (caddy_root / "Caddyfile").write_text("previous-route\n", encoding="utf-8")
    call_log = tmp_path / "calls.log"
    call_log.touch()
    docker_stub = bin_root / "docker"
    docker_stub.write_text(
            "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$CALL_LOG\"\n"
        "if [ \"$1\" = inspect ] && [ \"$2\" = --format ] && [ \"$4\" = candidate-static ]; then printf 'candidate-static\\t/candidate-static\\ttrue\\trunning\\n'; exit 0; fi\n"
        "case \"$*\" in\n"
        "  'info') exit 0;;\n"
        "  'stop candidate-static') exit 0;;\n"
        "  'rm candidate-static') exit 0;;\n"
        "  *' up -d '*) exit 1;;\n"
        "  *' down '*) exit 1;;\n"
        "  *'inspect'*candidate-static*) echo 'unexpected inspect format' >&2; exit 64;;\n"
        "  *'ps -aq'*candidate-static*) echo candidate-static;;\n"
        "  *'ps -aq'*previous-static*) echo previous-static;;\n"
        "esac\n",
        encoding="utf-8",
    )
    docker_stub.chmod(0o755)
    for name in ("caddy", "systemctl"):
        stub = bin_root / name
        stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        stub.chmod(0o755)

    function = rollback_function.replace("/opt/citespan", _bash_path(deploy_root)).replace(
        "/etc/caddy/Caddyfile", _bash_path(caddy_root / "Caddyfile")
    )
    script = f"""#!/bin/sh
set -Eeuo pipefail
{_rollback_fixture_state(deploy_root, caddy_root)}
{function}
trap rollback EXIT
false
"""
    script_path = tmp_path / "rollback.sh"
    script_path.write_text(script, encoding="utf-8")
    result = subprocess.run(
        [str(_git_bash_executable()), _bash_path(script_path)],
        cwd=ROOT,
        env={**os.environ, "PATH": f"{_bash_path(bin_root)}:{os.environ['PATH']}", "CALL_LOG": _bash_path(call_log)},
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 70
    recovery = (deploy_root / "recovery.log").read_text(encoding="utf-8")
    failure_evidence = (deploy_root / "recovery.log.failure").read_text(encoding="utf-8")
    assert "rollback result: incomplete" in recovery
    assert "recovery incomplete" in failure_evidence
    assert (deploy_root / ".citespan-deployment.json").read_text() == '{"deployment_id":"citespan-previous"}\n'
    runtime_lines = (deploy_root / ".citespan-runtime.env").read_text().splitlines()
    runtime = dict(line.split("=", 1) for line in runtime_lines)
    assert len(runtime_lines) == len(runtime)
    assert runtime["POSTGRES_USER"] == "ufdr_user"
    assert runtime["POSTGRES_DB"] == "ufdr_analyzer"
    assert runtime["MINIO_ACCESS_KEY"] == runtime["MINIO_ROOT_USER"]
    assert runtime["MINIO_SECRET_KEY"] == runtime["MINIO_ROOT_PASSWORD"]
    assert (caddy_root / "Caddyfile").read_text() == "previous-route\n"
    assert (deploy_root / "authoritative-data.txt").read_text() == "authoritative-data\n"
    assert (deploy_root / ".citespan-demo-marker.json").read_text() == '{"marker":"previous"}\n'
    if not call_log.exists():
        raise AssertionError(
            "rollback fixture exited before recording calls\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    calls = call_log.read_text(encoding="utf-8").splitlines()
    assert "start previous-backend" in calls
    assert "start previous-static" in calls
    assert any("compose" in call and "down --remove-orphans" in call for call in calls)
    assert calls.index("start previous-backend") < calls.index("start previous-static")
    assert calls.index("start previous-static") < next(i for i, call in enumerate(calls) if "down --remove-orphans" in call)
    assert any("inspect --format" in call and "candidate-static" in call for call in calls)
    assert calls.index("stop candidate-static") < calls.index("rm candidate-static")
    assert "deployment failed at forced_failure" in failure_evidence
    assert failure_evidence.strip()
    assert result.stdout == ""
    assert result.stderr == ""
    orphan_start = command.index("guarded_orphan_recovery")
    orphan_command = command[orphan_start:]
    assert "|| true" not in orphan_command
    assert (
        'if ps -eo pid=,ppid=,args= >"$process_rows_file" 2>&1; then\n'
        "        process_query_status=0\n"
        "    else\n"
        "        process_query_status=$?"
    ) in orphan_command
    assert '[ "$process_query_status" -eq 0 ] ||' in orphan_command
    assert "docker volume rm" not in command
    assert "tar " not in command
    assert "recovery.log" in command


def test_rollback_survives_closed_output_pipes_and_preserves_authoritative_state(bash_tmp_path):
    command = release._deployment_command(valid_payload())
    start = command.index("rollback() {")
    end = command.index("\ntrap rollback EXIT\n", start)
    rollback_function = command[start:end]
    tmp_path = bash_tmp_path
    deploy_root = tmp_path / "deploy"
    caddy_root = tmp_path / "etc"
    bin_root = tmp_path / "bin"
    for path in (deploy_root, caddy_root, bin_root):
        path.mkdir(parents=True)
    (deploy_root / ".citespan-deployment.json").write_text("prior metadata\n", encoding="utf-8")
    (deploy_root / ".citespan-demo-marker.json").write_text("prior marker\n", encoding="utf-8")
    (deploy_root / ".citespan-runtime.env").write_text(_complete_runtime_fixture(), encoding="utf-8")
    (deploy_root / ".citespan-authoritative-receipt.json").write_text("receipt\n", encoding="utf-8")
    (deploy_root / "authoritative-volume.marker").write_text("volume\n", encoding="utf-8")
    (caddy_root / "Caddyfile").write_text("previous-route\n", encoding="utf-8")
    call_log = tmp_path / "calls.log"
    call_log.touch()
    docker_stub = bin_root / "docker"
    docker_stub.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$CALL_LOG\"\n"
        "if [ \"$1\" = inspect ] && [ \"$2\" = --format ] && [ \"$4\" = candidate-static ]; then if [ -f \"$CANDIDATE_REMOVED\" ]; then echo 'Error: No such object: candidate-static' >&2; exit 1; fi; printf 'candidate-static\\t/candidate-static\\ttrue\\trunning\\n'; exit 0; fi\n"
        "case \"$*\" in\n"
        "  'info') exit 0;;\n"
        "  'stop candidate-static') exit 0;;\n"
        "  'rm candidate-static') touch \"$CANDIDATE_REMOVED\";;\n"
        "  'run '*) touch \"$CANDIDATE_STARTED\";;\n"
        "  *'compose'*'down --remove-orphans'*) exit 0;;\n"
        "esac\n",
        encoding="utf-8",
    )
    docker_stub.chmod(0o755)
    for name in ("caddy", "systemctl"):
        stub = bin_root / name
        stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        stub.chmod(0o755)

    function = rollback_function.replace("/opt/citespan", _bash_path(deploy_root)).replace(
        "/etc/caddy/Caddyfile", _bash_path(caddy_root / "Caddyfile")
    )
    script_path = tmp_path / "closed-pipes.sh"
    script_path.write_text(
        f"#!/usr/bin/env bash\nset -Eeuo pipefail\n{_rollback_fixture_state(deploy_root, caddy_root)}\n"
        f"{function}\ntrap rollback EXIT\ndocker run -d --name candidate-static nginx:1.29-alpine\nsleep 1\nfalse\n",
        encoding="utf-8",
    )
    process = subprocess.Popen(
        [str(_git_bash_executable()), _bash_path(script_path)],
        cwd=ROOT,
        env={
            **os.environ,
            "PATH": f"{_bash_path(bin_root)}:{os.environ['PATH']}",
            "CALL_LOG": _bash_path(call_log),
            "CANDIDATE_REMOVED": _bash_path(tmp_path / "candidate-removed"),
            "CANDIDATE_STARTED": _bash_path(tmp_path / "candidate-started"),
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    candidate_started = tmp_path / "candidate-started"
    deadline = time.monotonic() + 20
    while not candidate_started.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert candidate_started.exists()
    process.stdout.close()
    process.stderr.close()
    result_code = process.wait(timeout=20)

    assert result_code == 1
    recovery = (deploy_root / "recovery.log").read_text(encoding="utf-8")
    assert "rollback result: complete" in recovery
    assert "remove candidate static: ok" in recovery
    failure_evidence = (deploy_root / "recovery.log.failure").read_text(encoding="utf-8")
    assert "deployment failed at forced_failure" in failure_evidence
    assert (deploy_root / ".citespan-authoritative-receipt.json").read_text() == "receipt\n"
    assert (deploy_root / "authoritative-volume.marker").read_text() == "volume\n"
    assert (deploy_root / ".citespan-deployment.json").read_text() == "prior metadata\n"
    calls = call_log.read_text(encoding="utf-8").splitlines()
    assert "stop candidate-static" in calls
    assert "rm candidate-static" in calls
    assert any("down --remove-orphans" in call for call in calls)
    assert not any("citespan-postgres-data" in call or "citespan-meili-data" in call for call in calls)


def test_rollback_sanitizes_failed_cleanup_diagnostics_with_closed_output_pipes(bash_tmp_path):
    command = release._deployment_command(valid_payload())
    start = command.index("rollback() {")
    end = command.index("\ntrap rollback EXIT\n", start)
    rollback_function = command[start:end]
    tmp_path = bash_tmp_path
    deploy_root = tmp_path / "deploy"
    caddy_root = tmp_path / "etc"
    bin_root = tmp_path / "bin"
    for path in (deploy_root, caddy_root, bin_root):
        path.mkdir(parents=True)
    (deploy_root / ".citespan-deployment.json").write_text("prior metadata\n", encoding="utf-8")
    (deploy_root / ".citespan-demo-marker.json").write_text("prior marker\n", encoding="utf-8")
    (deploy_root / ".citespan-runtime.env").write_text(_complete_runtime_fixture(), encoding="utf-8")
    (deploy_root / ".citespan-authoritative-receipt.json").write_text("receipt\n", encoding="utf-8")
    (deploy_root / "authoritative-volume.marker").write_text("volume\n", encoding="utf-8")
    (caddy_root / "Caddyfile").write_text("previous-route\n", encoding="utf-8")
    call_log = tmp_path / "calls.log"
    call_log.touch()
    sentinel = "unlabelled-postgres-secret-sentinel"
    docker_stub = bin_root / "docker"
    docker_stub.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$CALL_LOG\"\n"
        "if [ \"$1\" = inspect ] && [ \"$2\" = --format ] && [ \"$4\" = candidate-static ]; then if [ -f \"$CANDIDATE_REMOVED\" ]; then echo 'Error: No such object: candidate-static' >&2; exit 1; fi; printf 'candidate-static\\t/candidate-static\\ttrue\\trunning\\n'; exit 0; fi\n"
        "case \"$*\" in\n"
        "  'info') exit 0;;\n"
        "  'stop candidate-static') exit 0;;\n"
        "  'rm candidate-static') touch \"$CANDIDATE_REMOVED\";;\n"
        "  *'compose'*'down --remove-orphans'*) printf 'cleanup failed with %s in a longer diagnostic\\n' \"$POSTGRES_PASSWORD\" >&2; exit 23;;\n"
        "esac\n",
        encoding="utf-8",
    )
    docker_stub.chmod(0o755)
    for name in ("caddy", "systemctl"):
        stub = bin_root / name
        stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        stub.chmod(0o755)

    sanitizer = "\n".join(f"    {line}" for line in release._readiness_sanitizer().splitlines())
    fixture = _rollback_fixture_state(deploy_root, caddy_root).replace(
        "    sanitize_probe_output() { printf '%s' \"$1\"; }\n", sanitizer + "\n"
    )
    function = rollback_function.replace("/opt/citespan", _bash_path(deploy_root)).replace(
        "/etc/caddy/Caddyfile", _bash_path(caddy_root / "Caddyfile")
    )
    script_path = tmp_path / "closed-pipes-cleanup-failure.sh"
    script_path.write_text(
        f"#!/usr/bin/env bash\nset -Eeuo pipefail\nset -a\n. {_bash_path(deploy_root / '.citespan-runtime.env')}\nset +a\nPOSTGRES_PASSWORD={sentinel}\nexport POSTGRES_PASSWORD\n"
        f"{fixture}\n{function}\ntrap rollback EXIT\ndocker run -d --name candidate-static nginx:1.29-alpine\nsleep 1\nfalse\n",
        encoding="utf-8",
    )
    process = subprocess.Popen(
        [str(_git_bash_executable()), _bash_path(script_path)],
        cwd=ROOT,
        env={
            **os.environ,
            "PATH": f"{_bash_path(bin_root)}:{os.environ['PATH']}",
            "CALL_LOG": _bash_path(call_log),
            "CANDIDATE_REMOVED": _bash_path(tmp_path / "candidate-removed"),
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    process.stdout.close()
    process.stderr.close()
    result_code = process.wait(timeout=20)

    assert result_code == 70
    recovery = (deploy_root / "recovery.log").read_text(encoding="utf-8")
    failure_evidence = (deploy_root / "recovery.log.failure").read_text(encoding="utf-8")
    assert "remove candidate services identity=citespan-candidate: failed exit_status=23" in recovery
    assert "cause=cleanup failed with [REDACTED] in a longer diagnostic" in recovery
    assert "remove candidate services identity=citespan-candidate" in failure_evidence
    assert "exit_status=23" in failure_evidence
    assert "rollback result: incomplete" in recovery
    assert "recovery incomplete" in failure_evidence
    assert sentinel not in recovery
    assert sentinel not in failure_evidence
    assert (deploy_root / ".citespan-authoritative-receipt.json").read_text() == "receipt\n"
    assert (deploy_root / "authoritative-volume.marker").read_text() == "volume\n"
    assert not list(deploy_root.glob("recovery.log.failure.cleanup.*"))
    calls = call_log.read_text(encoding="utf-8").splitlines()
    assert "stop candidate-static" in calls
    assert "rm candidate-static" in calls
    assert any("down --remove-orphans" in call for call in calls)
    assert not any("dependent-success" in call for call in calls)


def test_content_checks_handle_large_successful_curl_output_without_sigpipe(tmp_path):
    command = release._deployment_command(valid_payload())
    assert 'curl --fail --silent --show-error http://127.0.0.1:$candidate_frontend_port/ >"$candidate_static_body"' in command
    assert 'curl --fail --silent --show-error --tlsv1.2 https://$domain/ >"$public_route_body"' in command
    assert "curl --fail --silent --show-error http://127.0.0.1:$candidate_frontend_port/ | grep" not in command
    script = tmp_path / "content-check.sh"
    script.write_text(
        "#!/usr/bin/env bash\nset -Eeuo pipefail\n"
        "curl() { printf '%*sCiteSpan%*s\\n' 120000 '' 120000 ''; }\n"
        "body=body.html\nif ! curl --fail --silent --show-error https://example.invalid/ >\"$body\"; then exit 1; fi\n"
        "grep -qi CiteSpan \"$body\"\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [str(_git_bash_executable()), _bash_path(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("mode", ["curl-failure", "content-mismatch"])
def test_content_checks_preserve_curl_and_content_failures(tmp_path, mode):
    script = tmp_path / f"content-check-{mode}.sh"
    script.write_text(
        "#!/usr/bin/env bash\nset -Eeuo pipefail\n"
        "curl() { if [ \"$CHECK_MODE\" = curl-failure ]; then return 22; else printf 'unrelated content\\n'; fi; }\n"
        "body=body.html\n"
        "if ! curl --fail --silent --show-error https://example.invalid/ >\"$body\"; then exit 1; fi\n"
        "grep -qi CiteSpan \"$body\"\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [str(_git_bash_executable()), _bash_path(script)],
        cwd=tmp_path,
        env={**os.environ, "CHECK_MODE": mode},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 1


def test_backend_healthcheck_uses_trailing_slash_endpoint():
    dockerfile = (ROOT / "docker/services/Dockerfile.backend").read_text(encoding="utf-8")
    assert "CMD curl -f http://localhost:8000/health/ || exit 1" in dockerfile
    assert "CMD curl -f http://localhost:8000/health || exit 1" not in dockerfile


@pytest.mark.parametrize(
    ("container_state", "expected_returncode", "expected_error"),
    [
        ("stopped", 1, ""),
        ("missing", 1, ""),
        ("stop-fails", 70, "recovery incomplete"),
    ],
)
def test_candidate_static_cleanup_is_idempotent_and_fails_loudly(
    bash_tmp_path, container_state, expected_returncode, expected_error
):
    command = release._deployment_command(valid_payload())
    start = command.index("rollback() {")
    end = command.index("\ntrap rollback EXIT\n", start)
    rollback_function = command[start:end]
    tmp_path = bash_tmp_path
    deploy_root = tmp_path / "deploy"
    caddy_root = tmp_path / "etc"
    bin_root = tmp_path / "bin"
    for path in (deploy_root, caddy_root, bin_root):
        path.mkdir(parents=True)
    (deploy_root / ".citespan-deployment.json").write_text("prior metadata\n", encoding="utf-8")
    (deploy_root / ".citespan-demo-marker.json").write_text("prior marker\n", encoding="utf-8")
    (deploy_root / ".citespan-runtime.env").write_text(_complete_runtime_fixture(), encoding="utf-8")
    (caddy_root / "Caddyfile").write_text("prior route\n", encoding="utf-8")
    call_log = tmp_path / "calls.log"
    call_log.touch()
    docker_stub = bin_root / "docker"
    docker_stub.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$CALL_LOG\"\n"
        "if [ \"$1\" = inspect ] && [ \"$2\" = --format ] && [ \"$4\" = candidate-static ]; then\n"
        "  if [ -f \"$CANDIDATE_REMOVED\" ] || [ \"$CITESPAN_CONTAINER_STATE\" = missing ]; then echo 'Error: No such object: candidate-static' >&2; exit 1; fi\n"
        "  if [ \"$CITESPAN_CONTAINER_STATE\" = stopped ]; then printf 'candidate-static\\t/candidate-static\\tfalse\\texited\\n'; else printf 'candidate-static\\t/candidate-static\\ttrue\\trunning\\n'; fi\n"
        "  exit 0\n"
        "fi\n"
        "case \"$*\" in\n"
        "  'info') exit 0;;\n"
        "  'stop candidate-static') [ \"$CITESPAN_CONTAINER_STATE\" != stop-fails ];;\n"
        "  'rm candidate-static') touch \"$CANDIDATE_REMOVED\";;\n"
        "  'start previous-backend'|'start previous-static') exit 0;;\n"
        "  *'compose'*'down --remove-orphans'*) exit 0;;\n"
        "  *'inspect'*candidate-static*) echo 'unexpected inspect format' >&2; exit 64;;\n"
        "esac\nexit $?\n",
        encoding="utf-8",
    )
    docker_stub.chmod(0o755)
    for name in ("caddy", "systemctl"):
        stub = bin_root / name
        stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        stub.chmod(0o755)
    function = rollback_function.replace("/opt/citespan", _bash_path(deploy_root)).replace(
        "/etc/caddy/Caddyfile", _bash_path(caddy_root / "Caddyfile")
    )
    script_path = tmp_path / "candidate-cleanup.sh"
    script_path.write_text(
        f"#!/usr/bin/env bash\nset -Eeuo pipefail\n{_rollback_fixture_state(deploy_root, caddy_root)}\n"
        f"{function}\ntrap rollback EXIT\nfalse\n",
        encoding="utf-8",
    )

    env = {
        **os.environ,
        "PATH": f"{_bash_path(bin_root)}:{os.environ['PATH']}",
        "CALL_LOG": _bash_path(call_log),
        "CITESPAN_CONTAINER_STATE": container_state,
        "CANDIDATE_REMOVED": _bash_path(tmp_path / "candidate-removed"),
    }
    first = subprocess.run(
        [str(_git_bash_executable()), _bash_path(script_path)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    first_failure_evidence = (deploy_root / "recovery.log.failure").read_text(encoding="utf-8")
    second = subprocess.run(
        [str(_git_bash_executable()), _bash_path(script_path)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert first.returncode == expected_returncode, (
        f"first stderr={first.stderr!r} stdout={first.stdout!r} calls={call_log.read_text()!r}"
    )
    second_expected_returncode = 70 if container_state == "stop-fails" else (1 if expected_error else expected_returncode)
    assert second.returncode == second_expected_returncode, (
        f"second stderr={second.stderr!r} stdout={second.stdout!r}"
    )
    if expected_error:
        assert expected_error in first_failure_evidence
    calls = call_log.read_text(encoding="utf-8").splitlines()
    expected_inspections = 3 if container_state == "stopped" else 2
    assert sum("inspect --format" in call and "candidate-static" in call for call in calls) == expected_inspections, (
        f"calls={calls!r} first stderr={first.stderr!r} second stderr={second.stderr!r}"
    )
    if container_state == "stopped":
        assert calls.count("rm candidate-static") == 1
        assert "stop candidate-static" not in calls
    elif container_state == "missing":
        assert "rm candidate-static" not in calls
    else:
        assert calls.count("stop candidate-static") == 2
        assert "rm candidate-static" not in calls


def test_generated_deployment_command_has_valid_bash_syntax(tmp_path):
    script_path = tmp_path / "generated-deployment.sh"
    script_path.write_text(
        "#!/usr/bin/env bash\n" + release._deployment_command(valid_payload()) + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(_git_bash_executable()), "-n", _bash_path(script_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, f"generated deployment command is invalid:\n{result.stderr}"


@pytest.mark.parametrize("failure", ["pre_cutover", "post_cutover"])
def test_generated_recovery_runs_real_bash_and_preserves_prior_state(bash_tmp_path, failure):
    tmp_path = bash_tmp_path
    deploy_root = tmp_path / "deploy"
    caddy_root = tmp_path / "etc" / "caddy"
    bin_root = tmp_path / "bin"
    for path in (deploy_root, caddy_root, bin_root):
        path.mkdir(parents=True)
    (deploy_root / "frontend" / "out").mkdir(parents=True)
    (deploy_root / ".git").mkdir()
    prior_metadata = json.dumps(
        {
            "deployment_id": "citespan-previous",
            "backend_container": "previous-backend",
            "static_container": "previous-static",
            "runtime_identity": "citespan-previous",
            "backend_identity": "previous-backend",
            "static_identity": "previous-static",
            "commit": EXPECTED_COMMIT,
        "live_url": release.AUTHORIZED_LIVE_ORIGIN,
            "static_content_dir": "/opt/citespan/.citespan-backups/previous/static-content",
            "authoritative_network": "citespan-authoritative-network",
            "authoritative_postgres": "citespan-authoritative-postgres",
            "authoritative_meili": "citespan-authoritative-meili",
            "authoritative_minio": "citespan-authoritative-minio",
            "authoritative_data": True,
            "synthetic_only": True,
            "marker": release.CANONICAL_DEMO_MARKER,
        },
        separators=(",", ":"),
    ) + "\n"
    (deploy_root / ".citespan-deployment.json").write_text(prior_metadata, encoding="utf-8")
    (deploy_root / ".citespan-demo-marker.json").write_text(
        json.dumps(
            {
                "deployment_id": "citespan-previous",
                "run_id": release.CANONICAL_DEMO_RUN_ID,
                "synthetic_only": True,
                "marker": release.CANONICAL_DEMO_MARKER,
            },
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    (deploy_root / ".citespan-runtime.env").write_text(_complete_runtime_fixture(), encoding="utf-8")
    orphan_backup = deploy_root / ".citespan-backups" / Path(release.ORPHAN_BACKUP_DIR).name
    orphan_backup.mkdir(parents=True)
    (deploy_root / ".citespan-authoritative-receipt.json").write_text("receipt\n", encoding="utf-8")
    (orphan_backup / "old-action-evidence.log").write_text("old action\n", encoding="utf-8")
    (deploy_root / "authoritative-data.txt").write_text("prior-data\n", encoding="utf-8")
    (caddy_root / "Caddyfile").write_text("previous-route\n", encoding="utf-8")

    call_log = tmp_path / "calls.log"
    call_log.touch()
    (bin_root / "docker").write_text(
                "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$CALL_LOG\"\n"
                "if [ \"$1\" = inspect ] && [ \"$2\" = --format ] && [ \"$4\" = " + release.ORPHAN_CONTAINER_ID + " ]; then\n"
                "  echo 'Error: No such object: " + release.ORPHAN_CONTAINER_ID + "' >&2\n"
                "  exit 1\n"
                "fi\n"
                "case \"$*\" in\n"
                "  *'inspect -f {{.Id}} candidate-id'*) echo candidate-id ;;\n"
            "  *'inspect -f {{.Name}} candidate-id'*) printf '/%s-backend\\n' \"$CITESPAN_DEPLOYMENT_ID\" ;;\n"
            "  *'inspect -f {{.State.Status}} candidate-id'*) echo running ;;\n"
            "  *'inspect -f {{if .State.Health}}'*) echo none ;;\n"
            "  *'inspect -f {{.State.Running}} '*) echo true ;;\n"
        "  *'inspect -f {{.Name}} '*) container=; for argument do container=$argument; done; printf '/%s\\n' \"$container\" ;;\n"
            f"  'stop {release.ORPHAN_CONTAINER_ID}') exit 0 ;;\n"
            f"  'rm {release.ORPHAN_CONTAINER_ID}') touch \"$ORPHAN_REMOVED\" ;;\n"
            "  *'inspect --format'*'authoritative-postgres'*) printf 'postgres-id\\t/citespan-authoritative-postgres\\tfalse\\texited\\tpostgres:17-alpine\\tcitespan-authoritative-network,\\tvolume:citespan-postgres-data:/var/lib/postgresql/data:true,\\n' ;;\n"
            "  *'inspect --format'*'authoritative-meili'*) printf 'meili-id\\t/citespan-authoritative-meili\\tfalse\\texited\\tgetmeili/meilisearch:v1.15\\tcitespan-authoritative-network,\\tvolume:citespan-meili-data:/meili_data:true,\\n' ;;\n"
            "  *'inspect --format'*'authoritative-minio'*) printf 'minio-id\\t/citespan-authoritative-minio\\tfalse\\texited\\tcitespan-minio-source:RELEASE.2025-10-15T17-29-55Z\\tcitespan-authoritative-network,\\tvolume:citespan-minio-data:/data:true,\\n' ;;\n"
            "  *'inspect '*) printf '%s\\n' '[{\"Id\":\"prior-id\",\"Name\":\"previous\",\"State\":{\"Running\":true},\"Config\":{\"Env\":[\"CITESPAN_SYNTHETIC_ONLY=1\"]}}]' ;;\n"
        "  *'pg_isready'*) exit 0 ;;\n"
        "  *'7700/health'*) printf 'available\\n' ;;\n"
        "  *'9000/minio/health/live'*) exit 0 ;;\n"
        "  *'base64 -d'*) printf 'EMPTY\\n' ;;\n"
        "  *' exec '*) exit 0 ;;\n"
            "  *'network inspect --format'*'citespan-authoritative-network'*) printf 'network-id\\tcitespan-authoritative-network\\tbridge\\tlocal\\t10.0.0.0/24:10.0.0.1,\\n' ;;\n"
            "  *'volume inspect --format'*'citespan-postgres-data'*) printf 'citespan-postgres-data\\tlocal\\t/var/lib/docker/volumes/citespan-postgres-data\\tlocal\\n' ;;\n"
            "  *'volume inspect --format'*'citespan-meili-data'*) printf 'citespan-meili-data\\tlocal\\t/var/lib/docker/volumes/citespan-meili-data\\tlocal\\n' ;;\n"
            "  *'volume inspect --format'*'citespan-minio-data'*) printf 'citespan-minio-data\\tlocal\\t/var/lib/docker/volumes/citespan-minio-data\\tlocal\\n' ;;\n"
            "  *' network inspect '*|*' volume inspect '*) printf 'ok\\n' ;;\n"
        "  *' config --format json'*) printf '%s\\n' \"{\\\"services\\\":{\\\"backend\\\":{\\\"ports\\\":[{\\\"host_ip\\\":\\\"127.0.0.1\\\",\\\"published\\\":${CITESPAN_BACKEND_PORT},\\\"target\\\":8000,\\\"protocol\\\":\\\"tcp\\\"}]}}}\" ;;\n"
        "  *'up -d --no-deps --build backend'*) if [ \"$CITESPAN_FAIL_STEP\" = pre_cutover ]; then printf '%s\\n' \"injected failure: $CITESPAN_FAIL_STEP\" >> \"$CALL_LOG\"; echo \"injected failure: $CITESPAN_FAIL_STEP\" >&2; exit 42; fi ;;\n"
        "  *'ps -q '*) echo candidate-id ;;\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    (bin_root / "git").write_text(
        f"#!/bin/sh\nprintf '%s\\n' \"git $*\" >> \"$CALL_LOG\"\n"
        "checkout_path=\n"
        "if [ \"$1\" = -C ]; then checkout_path=$2; shift 2; fi\n"
        "case \"$1\" in\n"
        "  clone)\n"
        "    [ \"$2\" = --quiet ] && [ \"$3\" = --filter=blob:none ] && [ \"$4\" = --branch ] && "
        f"[ \"$5\" = {release.MINIO_SOURCE_REVISION} ] && [ \"$6\" = --depth ] && [ \"$7\" = 1 ] && "
        f"[ \"$8\" = {release.MINIO_SOURCE_REPOSITORY} ] || exit 64\n"
        "    mkdir -p \"$9\" || exit 64\n"
        "    exit 0\n"
        "    ;;\n"
        "  config) echo git@github.com:aayushman-singh/ufdr-analyzer.git ;;\n"
        f"  rev-parse) case \"$checkout_path\" in */minio) echo {release.MINIO_SOURCE_COMMIT} ;; *) echo {EXPECTED_COMMIT} ;; esac ;;\n"
        "  fetch|checkout) exit 0 ;;\n"
        "  *) exit 64 ;;\n"
        "esac\nexit 0\n",
        encoding="utf-8",
    )
    project_python = _bash_path(Path(PYTHON))
    (bin_root / "python3").write_text(
        f"#!/bin/sh\nprintf '%s\\n' \"python3 $*\" >> \"$CALL_LOG\"\nexec '{project_python}' \"$@\"\n",
        encoding="utf-8",
    )
    for name, body in {
        "getent": "#!/bin/sh\nprintf '%s\\n' \"getent $*\" >> \"$CALL_LOG\"\nprintf '127.0.0.1\\n'\n",
        "ss": "#!/bin/sh\nprintf '%s\\n' \"ss $*\" >> \"$CALL_LOG\"\nprintf 'LISTEN 127.0.0.1:%s\\n' \"$CITESPAN_BACKEND_PORT\"\n",
        "openssl": "#!/bin/sh\nprintf '%s\\n' \"openssl $*\" >> \"$CALL_LOG\"\nprintf 'synthetic-fixture-secret\\n'\n",
    }.items():
        (bin_root / name).write_text(body, encoding="utf-8")
    (bin_root / "curl").write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$CALL_LOG\"\n"
        "output=; previous=; for argument do if [ \"$previous\" = output ]; then output=\"$argument\"; previous=; elif [ \"$argument\" = --output ]; then previous=output; fi; done\n"
        "case \"$*\" in *https://*) if [ \"$CITESPAN_FAIL_STEP\" = post_cutover ]; then printf '%s\\n' \"injected failure: $CITESPAN_FAIL_STEP\" >> \"$CALL_LOG\"; echo \"injected failure: $CITESPAN_FAIL_STEP\" >&2; exit 22; fi;; esac\n"
        "case \"$*\" in */health/*) printf '%s' '{\"status\":\"OK\"}' > \"$output\"; printf '200' ;; *) printf 'CiteSpan\\n' ;; esac\n",
        encoding="utf-8",
    )
    for name in ("caddy", "systemctl"):
        (bin_root / name).write_text(
            "#!/bin/sh\nprintf '%s\\n' \"$0 $*\" >> \"$CALL_LOG\"\nexit 0\n", encoding="utf-8"
        )
    for path in bin_root.iterdir():
        path.chmod(0o755)

    command = release._deployment_command(valid_payload())
    command = command.replace("/opt/citespan", _bash_path(deploy_root)).replace(
        "/etc/caddy/Caddyfile", _bash_path(caddy_root / "Caddyfile")
    )
    bash_tmp_native_root = Path(
        subprocess.run(
            [str(_git_bash_executable()), "-lc", "cygpath -w /tmp"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )
    command = command.replace(
        'route=Path(__import__("os").environ["CITESPAN_ROUTE_FILE"]).read_text()',
        'route=Path(__import__("os").environ["CITESPAN_ROUTE_NATIVE"]).read_text()',
    )
    command = command.replace(
        f'p=Path("{_bash_path(caddy_root / "Caddyfile")}")',
        'p=Path(__import__("os").environ["CITESPAN_CADDY_NATIVE"])',
    )
    script_path = tmp_path / "generated-recovery.sh"
    script_path.write_text(f"#!/usr/bin/env bash\n{command}\n", encoding="utf-8")
    git_bash_bin = _bash_path(_git_bash_executable().parent)
    env = {
        **os.environ,
        "PATH": f"{_bash_path(bin_root)}:{git_bash_bin}:{os.environ['PATH']}",
        "CALL_LOG": _bash_path(call_log),
        "CITESPAN_FAIL_STEP": failure,
        "ORPHAN_REMOVED": _bash_path(tmp_path / "orphan-removed"),
        "CITESPAN_ROUTE_NATIVE": str(bash_tmp_native_root / "citespan-route"),
        "CITESPAN_CADDY_NATIVE": str(caddy_root / "Caddyfile"),
    }
    result = _run_owned_bash_fixture(
        [str(_git_bash_executable()), _bash_path(script_path)],
        cwd=ROOT,
        env=env,
        timeout=20,
    )

    assert result.returncode != 0
    assert (deploy_root / ".citespan-deployment.json").read_text(encoding="utf-8") == prior_metadata
    assert json.loads((deploy_root / ".citespan-demo-marker.json").read_text(encoding="utf-8"))[
        "marker"
    ] == release.CANONICAL_DEMO_MARKER
    assert (deploy_root / "authoritative-data.txt").read_text(encoding="utf-8") == "prior-data\n"
    assert (caddy_root / "Caddyfile").read_text(encoding="utf-8") == "previous-route\n"
    if not call_log.exists():
        raise AssertionError(
            f"{failure} fixture exited before recording calls\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    calls = call_log.read_text(encoding="utf-8").splitlines()
    if not calls:
        raise AssertionError(
            f"{failure} fixture recorded no calls\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    compose_calls = [index for index, call in enumerate(calls) if "compose" in call]
    assert compose_calls, f"{failure} did not invoke Compose\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}\ncalls:\n{calls}"
    assert any(f"pull {release.MINIO_BUILDER_IMAGE}" in call for call in calls), calls
    assert any(f"pull {release.MINIO_RUNTIME_IMAGE}" in call for call in calls), calls
    assert any(f"--tag {release.MINIO_IMAGE}" in call for call in calls), calls
    assert not any("volume rm" in call for call in calls)
    if failure == "pre_cutover":
        up_index = next(index for index, call in enumerate(calls) if "up -d --no-deps --build backend" in call)
        assert compose_calls[0] < up_index
        assert "injected failure: pre_cutover" in result.stderr
        assert "injected failure: pre_cutover" in calls
    else:
        https_calls = [
            index for index, call in enumerate(calls) if release.AUTHORIZED_LIVE_ORIGIN in call
        ]
        assert https_calls, f"{failure} did not reach authorized HTTPS request; calls:\n{calls}\nstderr:\n{result.stderr}"
        https_index = https_calls[0]
        assert compose_calls[0] < https_index
        assert any("down --remove-orphans" in call for call in calls)
        assert "injected failure: post_cutover" in result.stderr or "deployment failed at" in result.stderr
        assert any("injected failure: post_cutover" in call for call in calls)


def test_execute_deploys_to_authorized_host_and_returns_remote_commit():
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        command = kwargs.get("input", b"").decode("utf-8")
        if "deployment_commit" in command:
            return subprocess.CompletedProcess(
                argv,
                0,
                json.dumps(
                    {
                        "deployment_commit": EXPECTED_COMMIT,
        "live_url": release.AUTHORIZED_LIVE_ORIGIN,
                        "deployment_id": "citespan-test",
                        "backend_port": 18000,
                        "frontend_port": 18001,
                        "static_container": "citespan-test-static-1",
                        "static_content_dir": "/opt/citespan/.citespan-backups/1/static-1",
                        "synthetic_only": True,
                        "demo_mode": "1",
                        "runtime_validated": True,
                        "demo_run_id": release.CANONICAL_DEMO_RUN_ID,
                        "metadata_marker": release.CANONICAL_DEMO_MARKER,
                        "demo_marker": release.CANONICAL_DEMO_MARKER,
                    }
                ).encode("utf-8"),
                b"",
            )
        if any("rev-parse" in item for item in argv):
            return subprocess.CompletedProcess(argv, 0, EXPECTED_COMMIT.encode("ascii") + b"\n", b"")
        return subprocess.CompletedProcess(argv, 0, b"deployed\n", b"")

    payload = valid_payload()
    with patch.object(release, "_release_text", return_value=[]), patch.object(
        release, "_history_credential_findings", return_value=[]
    ), patch.object(release, "_history_secret_hashes", return_value=[]), patch.object(
        release, "_git", return_value=EXPECTED_COMMIT
    ), patch.object(
        release, "_critical_dependency_findings", return_value=[]
    ), patch.object(
        release, "_branding_findings", return_value=[]
    ), patch.object(release, "_project_python", return_value="C:/project/.venv/Scripts/python.exe"), patch.object(
        release,
        "_validate_host_process_evidence",
        return_value=_validated_empty_host_process_evidence(),
    ), patch.object(
        release, "_prepare_host", return_value={"state": "completed"}
    ), patch.object(
        release.subprocess, "run", side_effect=fake_run
    ), patch.object(release, "SSH_KEY", Path(__file__)):
        result = release._execute(payload)

    assert result["complete"] is True
    assert result["deployment_commit"] == EXPECTED_COMMIT
    assert result["external_identity"] == "root@169.58.64.150:citespan"
    assert any(any("169.58.64.150" in item for item in argv) for argv, _ in calls)
    assert all("deployment_result" not in json.dumps(argv) for argv, _ in calls)


def test_ssh_uses_path_resolved_executable_and_preserves_authorized_arguments():
    ssh_path = Path(__file__).resolve()
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, b"ok\n", b"")

    with patch.object(release, "SSH_KEY", Path(__file__)), patch.object(
        release.shutil, "which", return_value=str(ssh_path)
    ), patch.object(release.subprocess, "run", side_effect=fake_run):
        assert release._ssh("remote command") == "ok"

    argv = calls[0][0]
    assert argv[0] == str(ssh_path)
    assert argv[1] == "-i"
    assert os.path.normcase(os.path.normpath(argv[2])) == os.path.normcase(
        os.path.normpath(str(Path(__file__).resolve()))
    )
    assert argv[3:] == [
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "root@169.58.64.150",
        "bash",
        "-seuo",
        "pipefail",
    ]
    assert calls[0][1]["input"] == b"remote command"
    assert calls[0][1]["text"] is False
    assert calls[0][1]["cwd"] == release.ROOT
    assert calls[0][1]["capture_output"] is True
    assert calls[0][1]["check"] is False
    assert "everything" not in repr(calls)


def test_ssh_keeps_large_script_in_stdin_and_bounds_argv_length():
    script = "printf '%s' x\n" * 100_000
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, b"remote output\n", b"")

    with patch.object(release, "SSH_KEY", Path(__file__)), patch.object(
        release.shutil, "which", return_value=str(Path(__file__).resolve())
    ), patch.object(release.subprocess, "run", side_effect=fake_run):
        assert release._ssh(script) == "remote output"

    argv, kwargs = calls[0]
    assert len(argv) < 20
    assert all(script not in argument for argument in argv)
    assert kwargs["input"] == script.encode("utf-8")
    assert kwargs["text"] is False


def test_ssh_binary_pipe_preserves_large_multiline_utf8_payload_without_cr_bytes():
    payload = ("first\nsecond\nπ\n" * 7_000).encode("utf-8")
    child = (
        "import sys; data=sys.stdin.buffer.read(); "
        "sys.stdout.buffer.write(data); "
        "sys.stderr.buffer.write(b'child-ok\\n')"
    )
    result = subprocess.run(
        [sys.executable, "-c", child],
        input=payload,
        capture_output=True,
        text=False,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == payload
    assert b"\r" not in result.stdout
    assert result.stderr == b"child-ok\n"


def test_ssh_binary_pipe_preserves_real_child_exit_code_23():
    payload = "printf 'line one\nline two\nπ\n'\n".encode("utf-8")
    child = (
        "import sys; data=sys.stdin.buffer.read(); "
        "assert data == "
        + repr(payload)
        + "; sys.stderr.buffer.write(b'remote failure\\n'); raise SystemExit(23)"
    )
    result = subprocess.run(
        [sys.executable, "-c", child],
        input=payload,
        capture_output=True,
        text=False,
        check=False,
    )

    assert result.returncode == 23
    assert result.stderr == b"remote failure\n"
    assert b"Bash" not in result.stderr


def test_ssh_nonzero_remote_exit_fails_once_with_sanitized_diagnostic():
    script = "printf 'sensitive deployment payload'\n"
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(
            argv, 23, b"stdout contains sensitive deployment payload", script.encode()
        )

    with patch.object(release, "SSH_KEY", Path(__file__)), patch.object(
        release.shutil, "which", return_value=str(Path(__file__).resolve())
    ), patch.object(release.subprocess, "run", side_effect=fake_run), pytest.raises(
        RuntimeError, match=r"remote deployment command failed \(exit code 23\)"
    ) as error:
        release._ssh(script)

    assert len(calls) == 1
    assert script not in str(error.value)
    assert "sensitive deployment payload" not in str(error.value)


def test_ssh_invalid_output_encoding_fails_without_retry_or_payload():
    script = "printf 'sensitive deployment payload'\n"
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 23, b"\xff", b"\xfe")

    with patch.object(release, "SSH_KEY", Path(__file__)), patch.object(
        release.shutil, "which", return_value=str(Path(__file__).resolve())
    ), patch.object(release.subprocess, "run", side_effect=fake_run), pytest.raises(
        RuntimeError, match=r"remote deployment command failed \(exit code 23\)"
    ) as error:
        release._ssh(script)

    assert len(calls) == 1
    assert script not in str(error.value)


def test_ssh_process_creation_error_fails_without_script_or_retry():
    script = "printf 'sensitive deployment payload'\n"
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        raise OSError("process creation failed: " + script)

    with patch.object(release, "SSH_KEY", Path(__file__)), patch.object(
        release.shutil, "which", return_value=str(Path(__file__).resolve())
    ), patch.object(release.subprocess, "run", side_effect=fake_run), pytest.raises(
        RuntimeError, match="remote deployment process could not start"
    ) as error:
        release._ssh(script)

    assert len(calls) == 1
    assert script not in str(error.value)
    assert "sensitive deployment payload" not in str(error.value)


def test_ssh_timeout_captures_partial_output_and_reports_unknown_outcome(tmp_path):
    script = "echo deployment-boundary"
    timeout = subprocess.TimeoutExpired(
        ["ssh"], release.SSH_TIMEOUT_SECONDS, output=b"partial stdout", stderr=b"partial stderr"
    )

    with patch.object(release, "SSH_KEY", Path(__file__)), patch.object(
        release.shutil, "which", return_value=str(Path(__file__).resolve())
    ), patch.object(release.subprocess, "run", side_effect=timeout) as run, patch.object(
        release, "EXTERNAL_PROOF_ROOT", tmp_path
    ), pytest.raises(RuntimeError, match="unknown external outcome") as error:
        release._ssh(script)

    assert run.call_count == 1
    assert run.call_args.kwargs["timeout"] == release.SSH_TIMEOUT_SECONDS
    evidence = list(tmp_path.rglob("ssh-timeout.json"))
    assert len(evidence) == 1
    value = json.loads(evidence[0].read_text(encoding="utf-8"))
    assert value["stdout"] == "partial stdout"
    assert value["stderr"] == "partial stderr"
    assert value["outcome"] == "unknown_external_outcome"
    assert script not in error.value.args[0]


def test_ssh_timeout_redacts_submitted_script_marker_key_and_credentials(tmp_path):
    private_marker = "CITESPAN_" + "PRIVATE_SCRIPT_MARKER"
    openrouter_assignment = "OPENROUTER_" + "API_KEY=" + "sk-or-v1-" + (
        "12345678901234567890"
    )
    neo4j_assignment = "neo4j_" + "password=" + "super-secret-password"
    script = (
        f"printf '{private_marker}'; "
        f"printf '{openrouter_assignment}'; "
        f"printf '{neo4j_assignment}'"
    )
    timeout = subprocess.TimeoutExpired(
        ["ssh"],
        release.SSH_TIMEOUT_SECONDS,
        output=(script + "\n").encode(),
        stderr=(str(Path(__file__).resolve()) + "\n").encode(),
    )

    with patch.object(release, "SSH_KEY", Path(__file__)), patch.object(
        release.shutil, "which", return_value=str(Path(__file__).resolve())
    ), patch.object(release.subprocess, "run", side_effect=timeout), patch.object(
        release, "EXTERNAL_PROOF_ROOT", tmp_path
    ), pytest.raises(RuntimeError, match="unknown external outcome"):
        release._ssh(script)

    evidence = next(tmp_path.rglob("ssh-timeout.json"))
    serialized = evidence.read_text(encoding="utf-8")
    value = json.loads(serialized)
    assert script not in serialized
    assert "CITESPAN_PRIVATE_SCRIPT_MARKER" not in serialized
    assert ("sk-or-v1-" + "12345678901234567890") not in serialized
    assert "super-secret-password" not in serialized
    assert str(Path(__file__).resolve()) not in serialized
    assert value["stdout"] == "<submitted script>\n"
    assert value["stderr"] == "<configured SSH key>\n"


def test_ssh_timeout_records_sanitized_strict_utf8_error_metadata(tmp_path):
    script = "echo CITESPAN_PRIVATE_SCRIPT_MARKER"
    malformed = b"safe stdout " + b"\xff" + b" hidden-secret"
    truncated = b"safe stderr " + b"\xe2\x82"
    timeout = subprocess.TimeoutExpired(
        ["ssh"], release.SSH_TIMEOUT_SECONDS, output=malformed, stderr=truncated
    )

    with patch.object(release, "SSH_KEY", Path(__file__)), patch.object(
        release.shutil, "which", return_value=str(Path(__file__).resolve())
    ), patch.object(release.subprocess, "run", side_effect=timeout), patch.object(
        release, "EXTERNAL_PROOF_ROOT", tmp_path
    ), pytest.raises(RuntimeError, match="unknown external outcome"):
        release._ssh(script)

    value = json.loads(next(tmp_path.rglob("ssh-timeout.json")).read_text(encoding="utf-8"))
    for stream, raw in (("stdout", malformed), ("stderr", truncated)):
        evidence = value[stream]
        assert evidence["type"] == "encoding_error"
        assert evidence["stream"] == stream
        assert evidence["byte_length"] == len(raw)
        assert evidence["sha256"] == hashlib.sha256(raw).hexdigest()
        assert evidence["error"]["offset"] == (12 if stream == "stdout" else 12)
        assert evidence["error"]["reason"]
        assert "\ufffd" not in json.dumps(evidence)
    assert value["stdout"]["safe_prefix"] == "safe stdout "
    assert value["stderr"]["safe_prefix"] == "safe stderr "
    assert "hidden-secret" not in json.dumps(value)
    assert "CITESPAN_PRIVATE_SCRIPT_MARKER" not in json.dumps(value)


@pytest.mark.parametrize("secret_key", sorted(release.REQUIRED_RUNTIME_SECRET_KEYS))
def test_ssh_timeout_redacts_every_required_runtime_secret_in_output_and_echoes(
    tmp_path, secret_key
):
    value = "runtime-" + secret_key.lower().replace("_", "-") + "-" + ("x" * 24)
    assignment = f'"{secret_key}": "{value}"'
    output = (
        f"list=[{{{assignment}}}] nested={{'runtime':{{{assignment}}}}} "
        f"echo={value}\n"
    ).encode()
    timeout = subprocess.TimeoutExpired(
        ["ssh"], release.SSH_TIMEOUT_SECONDS, output=output, stderr=output
    )

    with patch.object(release, "SSH_KEY", Path(__file__)), patch.object(
        release.shutil, "which", return_value=str(Path(__file__).resolve())
    ), patch.object(release.subprocess, "run", side_effect=timeout), patch.object(
        release, "EXTERNAL_PROOF_ROOT", tmp_path
    ), pytest.raises(RuntimeError, match="unknown external outcome"):
        release._ssh("printf 'timeout evidence'")

    serialized = next(tmp_path.rglob("ssh-timeout.json")).read_text(encoding="utf-8")
    assert value not in serialized
    assert secret_key not in serialized


def test_ssh_timeout_redacts_runtime_secret_values_before_unlabelled_echoes(tmp_path):
    values = {
        key: "secret-" + key.lower().replace("_", "-") + "-" + ("z" * 24)
        for key in sorted(release.REQUIRED_RUNTIME_SECRET_KEYS)
    }
    assignments = ", ".join(f'"{key}": "{value}"' for key, value in values.items())
    generic_key = "INTERNAL_" + "SERVICE_" + "TOKEN"
    generic_value = "generic-service-token-" + ("q" * 24)
    output = (
        "{"
        + assignments
        + f', "{generic_key}": "{generic_value}"'
        + "}"
        + "\nunlabelled="
        + " ".join(values.values())
        + f" {generic_value}"
    ).encode()
    timeout = subprocess.TimeoutExpired(
        ["ssh"], release.SSH_TIMEOUT_SECONDS, output=output, stderr=output
    )

    with patch.object(release, "SSH_KEY", Path(__file__)), patch.object(
        release.shutil, "which", return_value=str(Path(__file__).resolve())
    ), patch.object(release.subprocess, "run", side_effect=timeout), patch.object(
        release, "EXTERNAL_PROOF_ROOT", tmp_path
    ), pytest.raises(RuntimeError, match="unknown external outcome"):
        release._ssh("printf 'timeout evidence'")

    serialized = next(tmp_path.rglob("ssh-timeout.json")).read_text(encoding="utf-8")
    for value in values.values():
        assert value not in serialized
    assert generic_value not in serialized


@pytest.mark.parametrize("field_name", [
    "openrouter_api_key",
    "openai_api_key",
    "neo4j_password",
    "INTERNAL_" + "SERVICE_" + "TOKEN",
])
def test_ssh_timeout_redacts_supported_alias_and_generic_json_fields(tmp_path, field_name):
    secret_value = "json-secret-" + field_name.lower().replace("_", "-") + "-" + ("y" * 24)
    output = (
        '{"outer": {"'
        + field_name
        + '": "'
        + secret_value
        + '"}, "echo": "'
        + secret_value
        + '"}'
    ).encode()
    timeout = subprocess.TimeoutExpired(
        ["ssh"], release.SSH_TIMEOUT_SECONDS, output=output, stderr=output
    )

    with patch.object(release, "SSH_KEY", Path(__file__)), patch.object(
        release.shutil, "which", return_value=str(Path(__file__).resolve())
    ), patch.object(release.subprocess, "run", side_effect=timeout), patch.object(
        release, "EXTERNAL_PROOF_ROOT", tmp_path
    ), pytest.raises(RuntimeError, match="unknown external outcome"):
        release._ssh("printf 'timeout evidence'")

    serialized = next(tmp_path.rglob("ssh-timeout.json")).read_text(encoding="utf-8")
    assert secret_value not in serialized
    assert field_name not in serialized


def test_execute_allows_valid_existing_host_state_then_deploys_once():
    payload = valid_payload()
    prepared = {
        "release_ready": True,
        "repository": "aayushman-singh/ufdr-analyzer",
        "product_name": "CiteSpan",
        "demo_policy": "synthetic-only",
    }
    deployed = {
        "action_key": "citespan-release",
        "complete": True,
        "observed": True,
        "runtime_validated": True,
        "deployment_commit": EXPECTED_COMMIT,
        "external_identity": "root@169.58.64.150:citespan",
        "live_url": release.AUTHORIZED_LIVE_ORIGIN,
    }
    with patch.object(release, "_prepare", return_value=prepared), patch.object(
        release, "_deployment_command", return_value="deploy"
    ), patch.object(
        release,
        "_observe",
        return_value=deployed,
    ) as observe, patch.object(release, "_ssh") as ssh:
        result = release._execute(payload)

    assert result["complete"] is True
    assert result["deployment_commit"] == EXPECTED_COMMIT
    assert ssh.call_count == 1
    ssh.assert_called_once_with("deploy")
    assert observe.call_count == 1


@pytest.mark.parametrize(
    "observation",
    [
        {},
        {"state": "not_deployed", "observed": False},
        {
            "action_key": "citespan-release",
            "complete": True,
            "observed": True,
            "state": "not_deployed",
            "external_identity": "root@169.58.64.150:citespan",
            "deployment_commit": EXPECTED_COMMIT,
        },
        {
            "action_key": "citespan-release",
            "complete": True,
            "observed": True,
            "runtime_validated": True,
            "external_identity": "root@169.58.64.150:citespan",
            "deployment_commit": "0" * 40,
        },
    ],
)
def test_execute_fails_after_attempt_when_post_deployment_proof_is_invalid(
    observation, monkeypatch
):
    payload = valid_payload()
    call_order = []
    binding = _install_controlled_release_hook_binding(monkeypatch, "execute")

    def observe_after_deploy(_payload, *, release_hook_binding):
        call_order.append("observe")
        assert release_hook_binding is binding
        return observation

    def deploy_once(command):
        call_order.append("ssh")
        assert command == "deploy"

    with patch.object(
        release, "_prepare", return_value={
            "release_ready": True,
            "repository": "aayushman-singh/ufdr-analyzer",
            "product_name": "CiteSpan",
            "demo_policy": "synthetic-only",
        }
    ), patch.object(release, "_deployment_command", return_value="deploy"), patch.object(
        release, "_observe", side_effect=observe_after_deploy
    ), patch.object(release, "_ssh", side_effect=deploy_once) as ssh, pytest.raises(
        RuntimeError, match="strict remote commit evidence"
    ):
        release._execute(payload, release_hook_binding=binding)

    assert call_order == ["ssh", "observe"]
    ssh.assert_called_once_with("deploy")


def test_deployment_records_boundary_phase_before_and_after_application_candidate():
    command = release._deployment_command(valid_payload())

    assert "release-phase-trace.log" in command
    assert 'phase_start "authoritative-data-readiness"' in command
    assert 'phase_end "authoritative-data-readiness" 0' in command
    assert 'phase_start "application-candidate"' in command
    assert 'phase_end "application-candidate" 0' in command
    assert command.index('phase_end "authoritative-data-readiness" 0') < command.index(
        'phase_start "application-candidate"'
    )


def test_deployment_boundary_failure_keeps_phase_trace_in_rollback_path():
    command = release._deployment_command(valid_payload())

    assert 'phase_failure "$safe_failed_step" "$status"' in command
    assert 'phase_trace="$backup_dir/release-phase-trace.log"' in command
    assert 'phase_start "application-candidate"' in command
    assert 'phase_end "application-candidate" 0' in command
    private_redirect = 'exec >>"$rollback_evidence" 2>&1'
    assert command.index(private_redirect) < command.index(
        'phase_failure "$safe_failed_step" "$status"'
    )
    assert command.index('phase_failure "$safe_failed_step" "$status"') < command.index(
        "record_recovery 'rollback result: complete'"
    )


def test_ssh_uses_windows_standard_openSSH_when_path_lookup_fails():
    standard_path = Path(__file__).resolve()

    with patch.object(release, "SSH_KEY", Path(__file__)), patch.object(
        release.shutil, "which", return_value=None
    ), patch.object(release.os, "name", "nt"), patch.object(
        release, "_windows_ssh_path", return_value=standard_path
    ), patch.object(
        release.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, b"ok\n", b"")
    ) as run:
        assert release._ssh("remote command") == "ok"

    assert run.call_args.args[0][0] == str(standard_path)


def test_ssh_missing_executable_fails_with_controlled_diagnostic():
    with patch.object(release, "SSH_KEY", Path(__file__)), patch.object(
        release.shutil, "which", return_value=None
    ), patch.object(release.os, "name", "posix"), patch.object(
        release.subprocess, "run", side_effect=AssertionError("subprocess must not run")
    ), pytest.raises(RuntimeError, match="OpenSSH is unavailable"):
        release._ssh("remote command")


def test_observe_fails_loudly_when_external_host_cannot_be_observed():
    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 255, b"", b"connection refused")

    payload = valid_payload()
    with patch.object(release.subprocess, "run", side_effect=fake_run), patch.object(
        release, "SSH_KEY", Path(__file__)
    ), patch.object(release, "_history_secret_hashes", return_value=[]), pytest.raises(
        RuntimeError, match="remote deployment command failed"
    ):
        release._observe(payload)


def test_observe_reports_not_deployed_without_claiming_success():
    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, b"NOT_DEPLOYED\n", b"")

    payload = valid_payload()
    with patch.object(release.subprocess, "run", side_effect=fake_run), patch.object(
        release, "SSH_KEY", Path(__file__)
    ):
        result = release._observe(payload)

    assert result == {
        "action_key": "citespan-release",
        "complete": False,
        "observed": False,
        "state": "not_deployed",
        "external_identity": "root@169.58.64.150:citespan",
    }


def test_observe_returns_the_commit_read_from_the_external_host():
    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(
            argv,
            0,
                json.dumps(
                    {
                    "deployment_commit": EXPECTED_COMMIT,
        "live_url": release.AUTHORIZED_LIVE_ORIGIN,
                    "deployment_id": "citespan-test",
                    "backend_port": 18000,
                    "frontend_port": 18001,
                    "static_container": "citespan-test-static-1",
                    "static_content_dir": "/opt/citespan/.citespan-backups/1/static-1",
                    "synthetic_only": True,
                    "demo_mode": "1",
                    "runtime_validated": True,
                    "demo_run_id": release.CANONICAL_DEMO_RUN_ID,
                    "metadata_marker": release.CANONICAL_DEMO_MARKER,
                    "demo_marker": release.CANONICAL_DEMO_MARKER,
                    }
                ).encode("utf-8"),
                b"",
            )

    payload = valid_payload()
    for field in ("live_url", "public_url", "deployment_url"):
        payload.pop(field, None)
    with patch.object(release.subprocess, "run", side_effect=fake_run), patch.object(
        release, "SSH_KEY", Path(__file__)
    ):
        result = release._observe(payload)

    assert result["observed"] is True
    assert result["deployment_commit"] == EXPECTED_COMMIT
    assert "source_commit" not in result


def test_observe_result_reaches_verify_with_runtime_validation(tmp_path):
    for name in ("home.png", "results.png", "proof.md", "post.md"):
        (tmp_path / name).write_bytes(b"proof")
    (tmp_path / "post.md").write_text("Exact draft", encoding="utf-8")
    remote_observation = {
        "deployment_commit": EXPECTED_COMMIT,
        "live_url": release.AUTHORIZED_LIVE_ORIGIN,
        "deployment_id": "citespan-test",
        "backend_port": 18000,
        "frontend_port": 18001,
        "static_container": "citespan-test-static-1",
        "static_content_dir": "/opt/citespan/.citespan-backups/1/static-1",
        "synthetic_only": True,
        "demo_mode": "1",
        "runtime_validated": True,
        "demo_run_id": release.CANONICAL_DEMO_RUN_ID,
        "metadata_marker": release.CANONICAL_DEMO_MARKER,
        "demo_marker": release.CANONICAL_DEMO_MARKER,
    }
    payload = {**valid_payload(), "proof_dir": str(tmp_path)}
    live_result = {
        "complete": True,
        "external_identity": release.AUTHORIZED_LIVE_ORIGIN,
        "live_url": release.AUTHORIZED_LIVE_ORIGIN,
        "steps": ["Open", "Ask", "Confirm"],
        "result": "Cited results returned.",
        "screenshots": ["home.png", "results.png"],
        "screenshot_paths": [str(tmp_path / "home.png"), str(tmp_path / "results.png")],
        "limits": ["Synthetic data only."],
        "proof_path": str(tmp_path / "proof.md"),
        "launch_post_path": str(tmp_path / "post.md"),
        "launch_post": "Exact draft",
    }
    with patch.object(release, "_ssh", return_value=json.dumps(remote_observation)), patch.object(
        release, "_check_payload_secrets"
    ), patch.object(release, "_run_live_verifier", return_value=live_result) as verifier:
        observation = release._observe(payload)
        assert observation["runtime_validated"] is True
        result = release._verify({**payload, "observation": observation})

    assert result["complete"] is True
    verifier.assert_called_once()


@pytest.mark.parametrize("runtime_validated", [None, False, "true", 1, []])
def test_observe_rejects_invalid_remote_runtime_validation(runtime_validated):
    observed = {
        "deployment_commit": EXPECTED_COMMIT,
        "live_url": release.AUTHORIZED_LIVE_ORIGIN,
        "deployment_id": "citespan-test",
        "backend_port": 18000,
        "frontend_port": 18001,
        "static_container": "citespan-test-static-1",
        "static_content_dir": "/opt/citespan/.citespan-backups/1/static-1",
        "synthetic_only": True,
        "demo_mode": "1",
        "runtime_validated": runtime_validated,
        "demo_run_id": release.CANONICAL_DEMO_RUN_ID,
        "metadata_marker": release.CANONICAL_DEMO_MARKER,
        "demo_marker": release.CANONICAL_DEMO_MARKER,
    }
    with patch.object(release, "_ssh", return_value=json.dumps(observed)), pytest.raises(
        RuntimeError, match="runtime validation"
    ):
        release._observe(valid_payload())


def test_observe_rejects_missing_remote_runtime_validation():
    observed = {
        "deployment_commit": EXPECTED_COMMIT,
        "live_url": release.AUTHORIZED_LIVE_ORIGIN,
        "deployment_id": "citespan-test",
        "backend_port": 18000,
        "frontend_port": 18001,
        "static_container": "citespan-test-static-1",
        "static_content_dir": "/opt/citespan/.citespan-backups/1/static-1",
        "synthetic_only": True,
        "demo_mode": "1",
        "demo_run_id": release.CANONICAL_DEMO_RUN_ID,
        "metadata_marker": release.CANONICAL_DEMO_MARKER,
        "demo_marker": release.CANONICAL_DEMO_MARKER,
    }
    with patch.object(release, "_ssh", return_value=json.dumps(observed)), pytest.raises(
        RuntimeError, match="runtime validation"
    ):
        release._observe(valid_payload())


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "live_url",
            "http://citespan.example",
            "observed live URL.*authorized CiteSpan HTTPS origin",
        ),
        ("synthetic_only", False, "synthetic-only"),
        ("metadata_marker", "wrong", "metadata marker"),
        ("demo_marker", "wrong", "demo marker"),
        ("demo_run_id", "wrong", "run ID"),
        ("deployment_id", "", "deployment identity"),
    ],
)
def test_observe_rejects_stale_or_mismatched_remote_identity(field, value, message):
    observed = {
        "deployment_commit": EXPECTED_COMMIT,
        "live_url": release.AUTHORIZED_LIVE_ORIGIN,
        "deployment_id": "citespan-test",
        "backend_port": 18000,
        "frontend_port": 18001,
        "static_container": "citespan-test-static-1",
        "static_content_dir": "/opt/citespan/.citespan-backups/1/static-1",
        "synthetic_only": True,
        "demo_mode": "1",
        "runtime_validated": True,
        "demo_run_id": release.CANONICAL_DEMO_RUN_ID,
        "metadata_marker": release.CANONICAL_DEMO_MARKER,
        "demo_marker": release.CANONICAL_DEMO_MARKER,
    }
    observed[field] = value

    with patch.object(release, "_ssh", return_value=json.dumps(observed)), pytest.raises(
        RuntimeError, match=message
    ):
        release._observe(valid_payload())


def test_verify_uses_provider_observation_and_live_verifier_result(tmp_path):
    screenshot_paths = [tmp_path / "home.png", tmp_path / "results.png"]
    for path in screenshot_paths:
        path.write_bytes(b"screenshot")
    proof_path = tmp_path / "proof.md"
    proof_path.write_text("proof", encoding="utf-8")
    launch_post_path = tmp_path / "post.md"
    launch_post_path.write_text("Exact draft", encoding="utf-8")
    payload = {
        **valid_payload(),
        "observation": {
            "observed": True,
            "runtime_validated": True,
            "deployment_commit": EXPECTED_COMMIT,
            "external_identity": "root@169.58.64.150:citespan",
        "live_url": release.AUTHORIZED_LIVE_ORIGIN,
            "deployment_id": "citespan-test",
            "synthetic_only": True,
            "demo_mode": "1",
            "demo_run_id": release.CANONICAL_DEMO_RUN_ID,
            "metadata_marker": release.CANONICAL_DEMO_MARKER,
            "demo_marker": release.CANONICAL_DEMO_MARKER,
        },
        "demo_run_id": "synthetic-run",
    }
    for field in ("live_url", "public_url", "deployment_url"):
        payload.pop(field, None)
    with patch.object(release, "_check_payload_secrets"), patch.object(
        release,
        "_run_live_verifier",
        return_value={
            "complete": True,
            "external_identity": release.AUTHORIZED_LIVE_ORIGIN,
        "live_url": release.AUTHORIZED_LIVE_ORIGIN,
            "steps": ["Open", "Ask", "Confirm"],
            "result": "Cited results returned.",
            "screenshots": ["home.png", "results.png"],
            "screenshot_paths": [str(path) for path in screenshot_paths],
            "limits": ["Synthetic data only."],
            "proof_path": str(proof_path),
            "launch_post_path": str(launch_post_path),
            "launch_post": "Exact draft",
        },
    ):
        result = release._verify(payload)

    assert result["complete"] is True
    assert result["deployment_commit"] == EXPECTED_COMMIT


def test_live_verifier_uses_external_proof_directory_and_returns_draft(tmp_path):
    verifier_result = {
        "complete": True,
        "external_identity": release.AUTHORIZED_LIVE_ORIGIN,
        "live_url": release.AUTHORIZED_LIVE_ORIGIN,
        "steps": ["Open", "Ask", "Confirm"],
        "result": "Cited results returned.",
        "screenshots": ["home.png", "results.png"],
        "screenshot_paths": [str(tmp_path / "home.png"), str(tmp_path / "results.png")],
        "limits": ["Synthetic data only."],
        "proof_path": str(tmp_path / "proof.md"),
        "launch_post_path": str(tmp_path / "post.md"),
        "launch_post": "Exact draft",
    }
    completed = subprocess.CompletedProcess(
        ["python"], 0, json.dumps(verifier_result), ""
    )
    observation = {
        "observed": True,
        "runtime_validated": True,
        "deployment_commit": EXPECTED_COMMIT,
        "live_url": release.AUTHORIZED_LIVE_ORIGIN,
        "deployment_id": "citespan-observed",
        "synthetic_only": True,
        "demo_mode": "1",
        "demo_run_id": release.CANONICAL_DEMO_RUN_ID,
        "metadata_marker": release.CANONICAL_DEMO_MARKER,
        "demo_marker": release.CANONICAL_DEMO_MARKER,
    }
    payload = {
        **valid_payload(),
        "proof_dir": str(tmp_path),
        "observation": observation,
        "live_url": observation["live_url"],
        "demo_run_id": observation["demo_run_id"],
    }
    calls = []
    call_kwargs = []

    def run_verifier(argv, **kwargs):
        calls.append(argv)
        call_kwargs.append(kwargs)
        return completed

    with patch.object(release, "_project_python", return_value="project-python"), patch.object(
        release.subprocess, "run", side_effect=run_verifier
    ):
        result = release._run_live_verifier(payload)

    assert result["launch_post"] == "Exact draft"
    output_dir = Path(calls[0][calls[0].index("--output-dir") + 1])
    assert output_dir.parent == tmp_path
    assert output_dir != release.ROOT
    assert calls[0][calls[0].index("--url") + 1] == observation["live_url"]
    assert calls[0][calls[0].index("--run-id") + 1] == observation["demo_run_id"]
    assert calls[0][calls[0].index("--deployment-id") + 1] == observation["deployment_id"]
    assert result["launch_post_path"] == str(tmp_path / "post.md")
    assert call_kwargs[0]["stdin"] is subprocess.DEVNULL
    assert call_kwargs[0]["timeout"] == release.LIVE_VERIFIER_TIMEOUT_SECONDS


def test_live_verifier_allocates_a_new_directory_for_each_retry(tmp_path):
    completed = subprocess.CompletedProcess(
        ["python"],
        0,
        json.dumps({"complete": True}),
        "",
    )
    payload = {
        **valid_payload(),
        "proof_dir": str(tmp_path),
        "observation": {"deployment_id": "citespan-retry"},
    }
    calls = []

    def run_verifier(argv, **kwargs):
        calls.append(argv)
        return completed

    with patch.object(release, "_project_python", return_value="project-python"), patch.object(
        release.subprocess, "run", side_effect=run_verifier
    ):
        release._run_live_verifier(payload)
        release._run_live_verifier(payload)

    first = Path(calls[0][calls[0].index("--output-dir") + 1])
    second = Path(calls[1][calls[1].index("--output-dir") + 1])
    assert first != second
    assert first.parent == second.parent == tmp_path


def test_live_verifier_timeout_fails_with_private_bounded_evidence(tmp_path):
    secret = "sk-or-v1-" + ("l" * 30)
    timeout = subprocess.TimeoutExpired(
        ["project-python", "scripts/verify_live.py"],
        release.LIVE_VERIFIER_TIMEOUT_SECONDS,
        output=(secret + " " + "o" * 5000).encode(),
        stderr=(secret + " verifier error").encode(),
    )
    payload = {
        **valid_payload(),
        "proof_dir": str(tmp_path),
        "observation": {"deployment_id": "citespan-timeout"},
    }
    with patch.object(release, "EXTERNAL_PROOF_ROOT", tmp_path), patch.object(
        release, "_project_python", return_value="project-python"
    ), patch.object(release.time, "monotonic", side_effect=[10.0, 10.25]), patch.object(
        release.subprocess, "run", side_effect=timeout
    ), pytest.raises(RuntimeError, match="live verification timed out"):
        release._run_live_verifier(payload)

    evidence = json.loads(next(tmp_path.rglob("timeout.json")).read_text())
    assert evidence["step"] == "live user-flow verification"
    assert evidence["timeout_seconds"] == release.LIVE_VERIFIER_TIMEOUT_SECONDS
    assert evidence["elapsed_seconds"] == pytest.approx(0.25)
    assert evidence["cleanup"]["descendant_state"] == "unverified"
    assert secret not in json.dumps(evidence)
    assert evidence["stdout"].endswith("<TRUNCATED>")


@pytest.mark.parametrize("run_id", [None, "", "not-a-uuid", 123])
def test_live_verifier_rejects_missing_or_invalid_run_id_before_browser_work(tmp_path, run_id):
    payload = {
        **valid_payload(),
        "proof_dir": str(tmp_path),
        "observation": {"deployment_id": "citespan-invalid-run"},
    }
    payload.pop("demo_run_id")
    if run_id is not None:
        payload["demo_run_id"] = run_id
    with patch.object(release.subprocess, "run") as run:
        with pytest.raises(RuntimeError, match="demo run id"):
            release._run_live_verifier(payload)
    run.assert_not_called()


def test_live_verifier_preserves_explicit_permitted_run_id(tmp_path):
    payload = {
        **valid_payload(),
        "proof_dir": str(tmp_path),
        "observation": {"deployment_id": "citespan-valid-run"},
    }
    calls = []
    completed = subprocess.CompletedProcess(["python"], 0, json.dumps({"complete": False}), "")

    def run_verifier(argv, **kwargs):
        calls.append(argv)
        return completed

    with patch.object(release, "_project_python", return_value="project-python"), patch.object(
        release.subprocess, "run", side_effect=run_verifier
    ):
        release._run_live_verifier(payload)

    assert calls[0][calls[0].index("--run-id") + 1] == payload["demo_run_id"]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "live_url",
            "http://citespan.example",
            "observed live URL.*authorized CiteSpan HTTPS origin",
        ),
        (
            "live_url",
            "https://other.example",
            "observed live URL.*authorized CiteSpan HTTPS origin",
        ),
        ("synthetic_only", False, "synthetic-only"),
        ("demo_marker", "wrong", "canonical demo markers"),
        ("metadata_marker", "wrong", "canonical demo markers"),
        ("demo_run_id", "wrong", "canonical demo run ID"),
        ("deployment_id", "", "deployment identity"),
    ],
)
def test_verify_rejects_mismatched_or_stale_observation(field, value, message):
    observation = {
        "observed": True,
        "runtime_validated": True,
        "deployment_commit": EXPECTED_COMMIT,
        "live_url": release.AUTHORIZED_LIVE_ORIGIN,
        "deployment_id": "citespan-test",
        "synthetic_only": True,
        "demo_mode": "1",
        "demo_run_id": release.CANONICAL_DEMO_RUN_ID,
        "metadata_marker": release.CANONICAL_DEMO_MARKER,
        "demo_marker": release.CANONICAL_DEMO_MARKER,
    }
    observation[field] = value
    payload = {**valid_payload(), "observation": observation}
    if field == "live_url" and value == "https://other.example":
        payload["live_url"] = release.AUTHORIZED_LIVE_ORIGIN
    with patch.object(release, "_check_payload_secrets"), pytest.raises(
        RuntimeError, match=message
    ):
        release._verify(payload)


def test_verify_passes_exact_observed_url_and_identity_to_live_verifier(tmp_path):
    observation = {
        "observed": True,
        "runtime_validated": True,
        "deployment_commit": EXPECTED_COMMIT,
            "live_url": release.AUTHORIZED_LIVE_ORIGIN,
        "deployment_id": "citespan-observed",
        "synthetic_only": True,
        "demo_mode": "1",
        "demo_run_id": release.CANONICAL_DEMO_RUN_ID,
        "metadata_marker": release.CANONICAL_DEMO_MARKER,
        "demo_marker": release.CANONICAL_DEMO_MARKER,
    }
    payload = {**valid_payload(), "live_url": release.AUTHORIZED_LIVE_ORIGIN, "observation": observation}
    proof = tmp_path / "proof.md"
    post = tmp_path / "post.md"
    screenshots = [
        tmp_path / "home.png",
        tmp_path / "results.png",
    ]
    for path in screenshots:
        path.write_bytes(b"screenshot")
    proof.write_text("proof", encoding="utf-8")
    post.write_text("Exact draft", encoding="utf-8")
    verifier_result = {
        "complete": True,
        "external_identity": release.AUTHORIZED_LIVE_ORIGIN,
        "live_url": observation["live_url"],
        "steps": ["Open", "Ask", "Confirm"],
        "result": "Cited results returned.",
        "screenshots": [path.name for path in screenshots],
        "screenshot_paths": [str(path) for path in screenshots],
        "limits": ["Synthetic data only."],
        "proof_path": str(proof),
        "launch_post_path": str(post),
        "launch_post": "Exact draft",
    }
    with patch.object(release, "_check_payload_secrets"), patch.object(
        release,
        "_run_live_verifier",
        return_value=verifier_result,
    ) as verifier:
        result = release._verify(payload)
    assert result["complete"] is True
    assert result["deployment_commit"] == EXPECTED_COMMIT
    forwarded = verifier.call_args.args[0]
    assert forwarded["live_url"] == observation["live_url"]
    assert forwarded["demo_run_id"] == observation["demo_run_id"]
    assert forwarded["observation"]["deployment_id"] == observation["deployment_id"]


def test_verify_does_not_infer_expected_commit_from_local_git():
    payload = {
        "action_key": "citespan-release",
        "intent": {"action_key": "citespan-release"},
        "observation": {"deployment_commit": "abc1234"},
        "live_url": release.AUTHORIZED_LIVE_ORIGIN,
        "demo_run_id": "synthetic-run",
    }
    payload["observation"]["observed"] = True
    with patch.object(release, "_check_payload_secrets"), patch.object(
        release, "_run_live_verifier", return_value={"complete": True}
    ), pytest.raises(RuntimeError, match="expected commit was not supplied"):
        release._verify(payload)


def test_verify_accepts_direct_not_deployed_observation_without_live_verifier():
    with patch.object(release, "_ssh", return_value="NOT_DEPLOYED"), patch.object(
        release, "_check_payload_secrets"
    ):
        observation = release._observe(valid_payload())
    payload = {
        **valid_payload(),
        "observation": observation,
    }

    with patch.object(release, "_check_payload_secrets"), patch.object(
        release, "_run_live_verifier", side_effect=AssertionError("must not run")
    ) as verifier:
        result = release._verify(payload)

    assert result == payload["observation"]
    verifier.assert_not_called()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("action_key", "wrong-action"),
        ("action_key", None),
        ("external_identity", "root@other.example:citespan"),
        ("external_identity", None),
        ("complete", True),
        ("observed", True),
        ("state", "deployed"),
        ("state", None),
        ("deployment_commit", EXPECTED_COMMIT),
        ("live_url", release.AUTHORIZED_LIVE_ORIGIN),
        ("deployment_id", "citespan-live"),
        ("screenshots", ["home.png"]),
        ("results", "cited results"),
        ("proof", "proof.md"),
    ],
)
def test_verify_rejects_malformed_or_fake_not_deployed_observation(field, value):
    observation = {
        "action_key": "citespan-release",
        "complete": False,
        "observed": False,
        "state": "not_deployed",
        "external_identity": "root@169.58.64.150:citespan",
    }
    if value is None:
        observation.pop(field, None)
    else:
        observation[field] = value

    with patch.object(release, "_check_payload_secrets"), pytest.raises(
        RuntimeError, match="not_deployed"
    ):
        release._verify({**valid_payload(), "observation": observation})


def test_prepare_derives_authorized_live_url_when_provider_omits_url_fields():
    payload = valid_payload()
    for field in ("live_url", "public_url", "deployment_url"):
        payload.pop(field, None)
    with patch.object(release, "_history_credential_findings", return_value=[]), patch.object(
        release, "_critical_dependency_findings", return_value=[]
    ), patch.object(
        release,
        "_provision_live_verifier",
        side_effect=AssertionError("prepare must not provision dependencies"),
    ):
        result = release._prepare(payload, validate_process_evidence=False)

    assert result["release_config"]["live_url"] == release.AUTHORIZED_LIVE_ORIGIN


def _write_dependency_fixture(
    root: Path,
    *,
    next_version="15.5.27",
    concurrently_version="9.2.1",
    concurrently_shell_quote="1.12.0",
    shell_quote=None,
    tar=None,
    overrides=None,
    integrity=None,
):
    frontend = root / "frontend"
    frontend.mkdir()
    package = {
        "dependencies": {"next": next_version},
        "devDependencies": {"concurrently": f"^{concurrently_version}"},
    }
    if overrides is not None:
        package["overrides"] = overrides
    packages = {"": {"dependencies": {"next": next_version}}}
    metadata = release.AUTHENTIC_REGISTRY_METADATA
    package_records = {
        "next": next_version,
        "eslint-config-next": "15.5.27",
        "shell-quote": shell_quote or "1.12.0",
        "tar": tar or "7.5.22",
    }
    def record(name, version):
        reviewed_version = version if (name, version) in metadata else {
            "next": "15.5.27",
            "eslint-config-next": "15.5.27",
            "shell-quote": "1.12.0",
            "tar": "7.5.22",
        }[name]
        resolved, authentic_integrity = metadata[(name, reviewed_version)]
        return {
            "version": version,
            "resolved": resolved.replace(f"-{reviewed_version}.tgz", f"-{version}.tgz"),
            "integrity": (
                authentic_integrity
                if integrity is None and version == reviewed_version
                else integrity
                if integrity is not None
                else "sha512-" + base64.b64encode(hashlib.sha512(f"{name}:{version}".encode()).digest()).decode()
            ),
        }

    packages["node_modules/concurrently"] = {
        "version": concurrently_version,
        "resolved": f"https://registry.npmjs.org/concurrently/-/concurrently-{concurrently_version}.tgz",
        "integrity": integrity or "sha512-" + base64.b64encode(hashlib.sha512(b"concurrently:9.2.1").digest()).decode(),
        "dependencies": {"shell-quote": concurrently_shell_quote},
    }
    packages["node_modules/next"] = record("next", next_version)
    packages["node_modules/eslint-config-next"] = record("eslint-config-next", package_records["eslint-config-next"])
    if shell_quote is not None:
        packages["node_modules/shell-quote"] = {
            "version": shell_quote,
            **record("shell-quote", shell_quote),
        }
    if tar is not None:
        packages["node_modules/tar"] = {
            "version": tar,
            **record("tar", tar),
        }
    lock = {"packages": packages}
    (frontend / "package.json").write_text(json.dumps(package), encoding="utf-8")
    (frontend / "package-lock.json").write_text(json.dumps(lock), encoding="utf-8")


def _initialize_dependency_fixture_git(root: Path) -> str:
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.invalid"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Release Fixture"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "add", "--all"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "--message", "fixture"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_prepare_accepts_patched_frontend_dependency_set(tmp_path):
    _write_dependency_fixture(
        tmp_path,
        concurrently_shell_quote="^1.12.0",
        shell_quote="1.12.0",
        tar="7.5.22",
        overrides={"shell-quote": "1.12.0"},
    )
    with patch.object(release, "ROOT", tmp_path):
        findings = release._critical_dependency_findings()
    assert findings == []
    assert not any(
        dependency in finding
        for dependency in ("Next", "concurrently", "shell-quote", "tar")
        for finding in findings
    )


def test_dependency_check_accepts_effective_patched_shell_quote_with_lower_override(
    tmp_path,
):
    _write_dependency_fixture(
        tmp_path,
        concurrently_shell_quote="1.9.0",
        shell_quote="1.12.0",
        tar="7.5.22",
        overrides={"shell-quote": "^1.11.0"},
    )
    with patch.object(release, "ROOT", tmp_path):
        findings = release._critical_dependency_findings()

    assert not any("concurrently" in finding for finding in findings)


def test_dependency_check_requires_every_reviewed_package_record(tmp_path):
    _write_dependency_fixture(tmp_path, shell_quote="1.12.0", tar="7.5.22")
    lock_path = tmp_path / "frontend" / "package-lock.json"
    lock = json.loads(lock_path.read_text())
    del lock["packages"]["node_modules/eslint-config-next"]
    lock_path.write_text(json.dumps(lock), encoding="utf-8")

    with patch.object(release, "ROOT", tmp_path):
        findings = release._critical_dependency_findings()

    assert any("eslint-config-next" in finding and "required" in finding for finding in findings)


def test_prepare_detects_vulnerable_next_and_blocks_release(tmp_path):
    _write_dependency_fixture(tmp_path, next_version="15.5.26")
    fixture_commit = _initialize_dependency_fixture_git(tmp_path)
    with patch.object(release, "ROOT", tmp_path), patch.object(
        release, "_history_credential_findings", return_value=[]
    ), patch.object(release, "_branding_findings", return_value=[]
    ):
        findings = release._critical_dependency_findings()
        result = release._prepare(
            valid_payload(intent={"action_key": "citespan-release", "expected_commit": fixture_commit}),
            validate_process_evidence=False,
        )
    assert any("Next" in finding for finding in findings)
    assert result["release_ready"] is False


def test_prepare_detects_vulnerable_transitive_archives_and_blocks_release(tmp_path):
    _write_dependency_fixture(tmp_path, shell_quote="1.10.0", tar="7.5.20")
    fixture_commit = _initialize_dependency_fixture_git(tmp_path)
    with patch.object(release, "ROOT", tmp_path), patch.object(
        release, "_history_credential_findings", return_value=[]
    ), patch.object(release, "_branding_findings", return_value=[]
    ):
        findings = release._critical_dependency_findings()
        result = release._prepare(
            valid_payload(intent={"action_key": "citespan-release", "expected_commit": fixture_commit}),
            validate_process_evidence=False,
        )
    assert any("shell-quote" in finding for finding in findings)
    assert any("tar" in finding for finding in findings)
    assert result["release_ready"] is False


def test_rendered_compose_merge_keeps_only_allocated_loopback_backend_port():
    rendered = {
        "services": {
            "backend": {
                "ports": [
                    {
                        "host_ip": "127.0.0.1",
                        "published": 18042,
                        "target": 8000,
                        "protocol": "tcp",
                    }
                ]
            }
        }
    }

    assert release._validate_rendered_backend_ports(rendered, 18042) is None


@pytest.mark.parametrize(
    "published",
    [
        53217,
        "53217",
    ],
)
def test_rendered_compose_backend_port_accepts_integer_or_canonical_decimal_string(published):
    rendered = {
        "services": {
            "backend": {
                "ports": [
                    {
                        "host_ip": "127.0.0.1",
                        "published": published,
                        "target": 8000,
                        "protocol": "tcp",
                    }
                ]
            }
        }
    }

    assert release._validate_rendered_backend_ports(rendered, 53217) is None


@pytest.mark.parametrize(
    "published",
    [
        True,
        53217.0,
        "",
        "+53217",
        " 53217",
        "53217 ",
        "053217",
        "53217-53218",
        "53217/tcp",
        0,
        65536,
    ],
)
def test_rendered_compose_backend_port_rejects_noncanonical_published_values(published):
    rendered = {
        "services": {
            "backend": {
                "ports": [
                    {
                        "host_ip": "127.0.0.1",
                        "published": published,
                        "target": 8000,
                        "protocol": "tcp",
                    }
                ]
            }
        }
    }

    with pytest.raises(RuntimeError, match="exact allocated loopback backend binding"):
        release._validate_rendered_backend_ports(rendered, 53217)


def test_generated_compose_backend_port_validator_matches_compose_string_shape():
    rendered = {
        "services": {
            "backend": {
                "ports": [
                    {
                        "host_ip": "127.0.0.1",
                        "published": "53217",
                        "target": 8000,
                        "protocol": "tcp",
                    }
                ]
            }
        }
    }
    result = subprocess.run(
        [sys.executable, "-c", release._compose_backend_port_validation_script(), "53217"],
        input=json.dumps(rendered),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "published",
    [
        True,
        53217.0,
        "",
        "+53217",
        " 53217",
        "53217 ",
        "053217",
        "53217-53218",
        "53217/tcp",
        "53218",
        "0",
        "65536",
    ],
)
def test_generated_compose_backend_port_validator_rejects_invalid_published_values(published):
    rendered = {
        "services": {
            "backend": {
                "ports": [
                    {
                        "host_ip": "127.0.0.1",
                        "published": published,
                        "target": 8000,
                        "protocol": "tcp",
                    }
                ]
            }
        }
    }
    result = subprocess.run(
        [sys.executable, "-c", release._compose_backend_port_validation_script(), "53217"],
        input=json.dumps(rendered),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0


@pytest.mark.parametrize(
    "ports",
    [
        [
            {"published": 8000, "target": 8000, "protocol": "tcp"},
            {"host_ip": "127.0.0.1", "published": 18042, "target": 8000, "protocol": "tcp"},
        ],
        [{"host_ip": "0.0.0.0", "published": 18042, "target": 8000, "protocol": "tcp"}],
    ],
)
def test_rendered_compose_merge_rejects_inherited_or_public_backend_ports(ports):
    rendered = {"services": {"backend": {"ports": ports}}}

    with pytest.raises(RuntimeError, match="exact allocated loopback backend binding"):
        release._validate_rendered_backend_ports(rendered, 18042)


def test_prepare_rejects_concurrently_tree_without_patched_shell_quote_override(tmp_path):
    _write_dependency_fixture(
        tmp_path,
        concurrently_shell_quote="1.10.0",
        shell_quote="1.10.0",
        tar="7.5.21",
    )
    with patch.object(release, "ROOT", tmp_path):
        findings = release._critical_dependency_findings()
    assert any("concurrently" in finding for finding in findings)


def test_prepare_rejects_mismatched_lock_integrity_metadata(tmp_path):
    _write_dependency_fixture(
        tmp_path,
        concurrently_shell_quote="^1.11.0",
        shell_quote="1.11.0",
        tar="7.5.21",
        overrides={"shell-quote": "1.11.0"},
        integrity="not-a-sha512-integrity",
    )
    with patch.object(release, "ROOT", tmp_path):
        findings = release._critical_dependency_findings()
    assert any("integrity" in finding for finding in findings)


def test_empty_history_hashes_use_a_valid_noop_branch():
    with patch.object(release, "_history_secret_hashes", return_value=[]):
        command = release._deployment_command(valid_payload())

    assert "for compromised_hash in ; do" not in command
    assert 'if [ "$history_hash_count" -eq 0 ]; then :; fi' in command


def test_live_verifier_provisioning_is_pinned_to_project_python_and_browser_path():
    results = [
        subprocess.CompletedProcess(["python", "-m", "pip"], 0, "installed\n", ""),
        subprocess.CompletedProcess(["python", "-m", "playwright"], 0, "installed\n", ""),
    ]
    with patch.object(release, "_project_python", return_value="C:/project/.venv/Scripts/python.exe"), patch.object(
        release, "_live_verifier_is_usable", side_effect=[False, True]
    ), patch.object(release.subprocess, "run", side_effect=results) as run:
        release._provision_live_verifier()

    assert all(call.kwargs["stdin"] is subprocess.DEVNULL for call in run.call_args_list)
    assert all(
        call.kwargs["timeout"] == release.PLAYWRIGHT_PROVISION_TIMEOUT_SECONDS
        for call in run.call_args_list
    )
    commands = [call.args[0] for call in run.call_args_list]
    assert [
        "C:/project/.venv/Scripts/python.exe",
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-deps",
        "--require-hashes",
        "--only-binary=:all:",
        f"{release.PYTHON_PLAYWRIGHT_WHEEL_URL}#sha256={release.PYTHON_PLAYWRIGHT_WHEEL_SHA256}",
    ] in commands
    assert ["C:/project/.venv/Scripts/python.exe", "-m", "playwright", "install", "chromium"] in commands


def test_python_playwright_provisioning_contract_has_matching_wheel_metadata():
    assert release.PYTHON_PLAYWRIGHT_WHEEL == (
        f"playwright-{release.PYTHON_PLAYWRIGHT_VERSION}-py3-none-win_amd64.whl"
    )
    assert release.PYTHON_PLAYWRIGHT_WHEEL_URL.endswith(
        f"/{release.PYTHON_PLAYWRIGHT_WHEEL}"
    )
    assert len(release.PYTHON_PLAYWRIGHT_WHEEL_SHA256) == 64
    int(release.PYTHON_PLAYWRIGHT_WHEEL_SHA256, 16)


@pytest.mark.parametrize("field", ["PYTHON_PLAYWRIGHT_WHEEL_URL", "PYTHON_PLAYWRIGHT_WHEEL_SHA256"])
def test_python_playwright_provisioning_rejects_invalid_integrity_metadata(field, monkeypatch):
    value = "https://example.invalid/wrong.whl" if field.endswith("URL") else "not-a-sha256"
    monkeypatch.setattr(release, field, value)
    with pytest.raises(RuntimeError, match="Python Playwright"):
        release._validate_python_playwright_contract()


def test_live_verifier_provisioning_rejects_unknown_exit_code_and_records_private_evidence(tmp_path):
    completed = subprocess.CompletedProcess(
        ["python", "-m", "pip"], "unknown", "installer output", "installer error"
    )
    with patch.object(release, "EXTERNAL_PROOF_ROOT", tmp_path), patch.object(
        release, "_project_python", return_value="C:/project/.venv/Scripts/python.exe"
    ), patch.object(release, "_live_verifier_is_usable", return_value=False), patch.object(
        release.subprocess, "run", return_value=completed
    ), pytest.raises(RuntimeError, match="exit code unknown"):
        release._provision_live_verifier()

    evidence = list(tmp_path.rglob("provisioning-failure.json"))
    assert len(evidence) == 1
    value = json.loads(evidence[0].read_text())
    assert value["command"] == [
        "C:/project/.venv/Scripts/python.exe",
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-deps",
        "--require-hashes",
        "--only-binary=:all:",
        f"{release.PYTHON_PLAYWRIGHT_WHEEL_URL}#sha256={release.PYTHON_PLAYWRIGHT_WHEEL_SHA256}",
    ]
    assert value["returncode"] == "unknown"
    assert value["stdout"] == "installer output"
    assert value["stderr"] == "installer error"


def test_live_verifier_provisioning_timeout_fails_with_bounded_redacted_evidence(tmp_path):
    secret = "sk-or-v1-" + ("t" * 30)
    timeout = subprocess.TimeoutExpired(
        ["python", "-m", "pip"],
        release.PLAYWRIGHT_PROVISION_TIMEOUT_SECONDS,
        output=("safe " + secret + " " + "x" * 5000).encode(),
        stderr=("installer " + secret).encode(),
    )
    with patch.object(release, "EXTERNAL_PROOF_ROOT", tmp_path), patch.object(
        release, "_project_python", return_value="C:/project/.venv/Scripts/python.exe"
    ), patch.object(release, "_live_verifier_is_usable", return_value=False), patch.object(
        release.time, "monotonic", side_effect=[20.0, 20.5]
    ), patch.object(release.subprocess, "run", side_effect=timeout), pytest.raises(
        RuntimeError, match="provisioning timed out"
    ):
        release._provision_live_verifier()

    evidence = json.loads(next(tmp_path.rglob("timeout.json")).read_text())
    assert evidence["step"] == "Playwright provisioning"
    assert evidence["argv_category"] == "project Python Playwright installer"
    assert evidence["command"][0] == "C:/project/.venv/Scripts/python.exe"
    assert evidence["command"][1:3] == ["-m", "pip"]
    assert evidence["argument_count"] == 9
    assert evidence["exception_type"] == "TimeoutExpired"
    assert evidence["exception_message"]
    assert evidence["traceback"]
    assert "subprocess.TimeoutExpired" in evidence["traceback"]
    assert evidence["cwd"] == release.ROOT.as_posix()
    assert evidence["timeout_seconds"] == release.PLAYWRIGHT_PROVISION_TIMEOUT_SECONDS
    assert evidence["elapsed_seconds"] == pytest.approx(0.5)
    assert evidence["cleanup"]["descendant_state"] == "unverified"
    assert secret not in json.dumps(evidence)
    assert evidence["stdout"].endswith("<TRUNCATED>")


def test_live_verifier_playwright_probe_timeout_records_rich_redacted_evidence(tmp_path):
    secret = "sk-or-v1-" + ("p" * 30)
    timeout = subprocess.TimeoutExpired(
        ["project-python", "-c", f"print({secret!r})"],
        release.PLAYWRIGHT_PROVISION_TIMEOUT_SECONDS,
        output=(secret + " probe output").encode(),
        stderr=(secret + " probe error").encode(),
    )
    with patch.object(release, "EXTERNAL_PROOF_ROOT", tmp_path), patch.object(
        release, "_project_python", return_value="project-python"
    ), patch.object(release.time, "monotonic", side_effect=[30.0, 30.75]), patch.object(
        release.subprocess, "run", side_effect=timeout
    ), pytest.raises(RuntimeError, match="Playwright usability probe timed out"):
        release._live_verifier_is_usable()

    evidence = json.loads(next(tmp_path.rglob("timeout.json")).read_text())
    assert evidence["step"] == "playwright usability probe"
    assert evidence["timeout_seconds"] == release.PLAYWRIGHT_PROVISION_TIMEOUT_SECONDS
    assert evidence["elapsed_seconds"] == pytest.approx(0.75)
    assert evidence["exception_type"] == "TimeoutExpired"
    assert evidence["traceback"]
    assert evidence["cleanup"]["descendant_state"] == "unverified"
    assert secret not in json.dumps(evidence)


def test_subprocess_timeout_omits_elapsed_time_when_clock_measurement_fails(tmp_path):
    timeout = subprocess.TimeoutExpired(["project-python"], 900, output="partial", stderr="error")
    with patch.object(release, "EXTERNAL_PROOF_ROOT", tmp_path), patch.object(
        release.time, "monotonic", side_effect=OSError("clock unavailable")
    ):
        evidence_path = release._record_private_subprocess_timeout(
            step="bounded operation",
            argv_category="project Python operation",
            command=["project-python"],
            timeout=timeout,
            timeout_seconds=900,
            elapsed_seconds=release._measured_elapsed_seconds(release._monotonic_now()),
        )

    evidence = json.loads(evidence_path.read_text())
    assert "elapsed_seconds" not in evidence
    assert evidence["timeout_seconds"] == 900


def test_subprocess_timeout_redacts_sensitive_argv_values_and_keeps_safe_literals(tmp_path):
    secret = "sk-or-v1-" + ("a" * 30)
    timeout = subprocess.TimeoutExpired(
        ["project-python", "scripts/verify_live.py", "--token", secret, "--run-id", "synthetic"],
        900,
        output="partial",
        stderr="error",
    )
    with patch.object(release, "EXTERNAL_PROOF_ROOT", tmp_path):
        evidence_path = release._record_private_subprocess_timeout(
            step="bounded operation",
            argv_category="project Python operation",
            command=timeout.cmd,
            timeout=timeout,
            timeout_seconds=900,
        )

    evidence = json.loads(evidence_path.read_text())
    assert evidence["command"] == [
        "project-python",
        "scripts/verify_live.py",
        "--token",
        "<REDACTED>",
        "--run-id",
        "synthetic",
    ]
    assert secret not in json.dumps(evidence)


def test_subprocess_timeout_records_census_read_failure_as_unreadable(tmp_path):
    timeout = subprocess.TimeoutExpired(["project-python"], 900, output="partial", stderr="error")
    with patch.object(release, "EXTERNAL_PROOF_ROOT", tmp_path):
        evidence_path = release._record_private_subprocess_timeout(
            step="bounded operation",
            argv_category="project Python operation",
            command=["project-python"],
            timeout=timeout,
            timeout_seconds=900,
            descendant_census={
                "status": "read_failed",
                "read_failure": "OpenProcess failed for pid 1234: secret-token",
            },
        )

    cleanup = json.loads(evidence_path.read_text())["cleanup"]
    assert cleanup["descendant_state"] == "unreadable"
    assert "OpenProcess failed for pid 1234" in cleanup["read_failure"]


def test_subprocess_timeout_reports_only_the_state_observed_by_a_successful_census(tmp_path):
    timeout = subprocess.TimeoutExpired(["project-python"], 900, output="partial", stderr="error")
    with patch.object(release, "EXTERNAL_PROOF_ROOT", tmp_path):
        evidence_path = release._record_private_subprocess_timeout(
            step="bounded operation",
            argv_category="project Python operation",
            command=["project-python"],
            timeout=timeout,
            timeout_seconds=900,
            descendant_census={"status": "measured", "descendant_state": "owned_descendant"},
        )

    cleanup = json.loads(evidence_path.read_text())["cleanup"]
    assert cleanup == {
        "status": "failed closed pending measured descendant ownership handling",
        "descendant_state": "owned_descendant",
    }


def test_registry_integrity_check_rejects_known_package_hash_mismatch(tmp_path):
    _write_dependency_fixture(tmp_path, shell_quote="1.11.0", tar="7.5.22")
    lock_path = tmp_path / "frontend" / "package-lock.json"
    lock = json.loads(lock_path.read_text())
    lock["packages"]["node_modules/shell-quote"]["integrity"] = "sha512-invalid"
    lock_path.write_text(json.dumps(lock))
    with patch.object(release, "ROOT", tmp_path):
        findings = release._critical_dependency_findings()
    assert any("authentic registry integrity" in finding for finding in findings)


def test_deployment_command_pins_commit_and_safe_demo_environment():
    command = release._deployment_command(valid_payload())
    assert f"fetch --prune origin {EXPECTED_COMMIT}" in command
    assert f"checkout --detach --force {EXPECTED_COMMIT}" in command
    assert f"rev-parse HEAD)\" = {EXPECTED_COMMIT}" in command
    assert "DEMO_MODE=1" in command
    assert "OPENROUTER_API_KEY" in command
    assert "OPENAI_API_KEY" in command
    assert "NEO4J_PASSWORD" in release._compose_override(valid_payload())
    assert "docker-compose.demo.yml" in command
    assert "NEO4J_PASSWORD" in command
    assert "POSTGRES_PASSWORD" in command
    assert "MEILI_MASTER_KEY" in command
    assert "MINIO_ROOT_USER" in command
    assert "MINIO_ROOT_PASSWORD" in command
    assert "SECRET_KEY" in command
    assert "--no-deps --build backend" in command
    assert "authoritative_network" in command
    assert "docker network create" in command
    assert "CITESPAN_DEMO_RUN_ID" in command


def test_deployment_command_is_repeatable_and_isolates_only_citespan_resources():
    command = release._deployment_command(valid_payload())

    assert "static_container" in command
    assert "docker container inspect citespan-static" not in command
    assert "docker rm -f citespan-static" not in command
    assert "docker rm -f $deployment_id-static" not in command
    assert "docker ps -q --filter name=^/unrelated" not in command
    assert "--project-name" in command
    assert "CITESPAN_BACKEND_PORT" in command
    assert "CITESPAN_FRONTEND_PORT" in command
    assert "CITESPAN_DEPLOYMENT_ID" in command
    override = release._compose_override(valid_payload())
    assert "ports: !override" in override
    assert "config --format json" in command
    assert "exact allocated loopback backend binding" in command
    seed = release._demo_seed_script()
    encoded_seed = base64.b64encode(seed.encode()).decode()
    assert 'external: true' in override
    assert 'CITESPAN_AUTHORITATIVE_NETWORK' in override
    assert 'CITESPAN_AUTHORITATIVE_POSTGRES' in override
    assert "citespan-backups" in command
    assert "docker volume rm" not in command
    assert encoded_seed in command
    assert '"sample_id": "canonical-v1"' in seed
    assert 'os.environ["CITESPAN_SYNTHETIC_MARKER"]' in seed
    candidate_static_health = (
        'candidate_static_body="$backup_dir/candidate-static.html"; if ! curl --fail --silent --show-error http://127.0.0.1:$candidate_frontend_port/ >"$candidate_static_body"; then exit 1; fi; grep -qi CiteSpan "$candidate_static_body"'
    )
    route_switch = 'CITESPAN_ROUTE_FILE="$route_file"'
    assert command.index(candidate_static_health) < command.index(route_switch)
    phase_order = [
        "failed_step=candidate-static-health",
        "failed_step=route-stage",
        "failed_step=caddy-validate",
        "failed_step=route-reload",
        "failed_step=public-route-check",
        "failed_step=metadata-commit",
    ]
    assert [command.index(marker) for marker in phase_order] == sorted(
        command.index(marker) for marker in phase_order
    )
    metadata_writer = release._metadata_writer_script()
    assert command.count(metadata_writer) == 1
    assert command.index("failed_step=metadata-commit") < command.index(metadata_writer)
    assert 'mv -f "$backup_dir/deployment.json.tmp"' not in command
    assert "citespan-deployment.json" in command


def test_deployment_command_uses_authoritative_data_services():
    command = release._deployment_command(valid_payload())

    assert "authoritative_network" in command
    assert "authoritative_postgres" in command
    assert "CITESPAN_SYNTHETIC_ONLY" in command
    assert "CITESPAN_SYNTHETIC_MARKER" in release._compose_override(valid_payload())
    assert "--no-deps --build backend" in command


def test_minio_build_provenance_pins_official_source_and_base_images():
    definition = release._minio_source_build_definition()

    assert release.MINIO_SOURCE_REPOSITORY == "https://github.com/minio/minio.git"
    assert release.MINIO_SOURCE_REVISION == "RELEASE.2025-10-15T17-29-55Z"
    assert release.MINIO_SOURCE_COMMIT == "9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a"
    assert "FROM " + release.MINIO_BUILDER_IMAGE in definition
    assert "FROM " + release.MINIO_RUNTIME_IMAGE in definition
    assert release.MINIO_BUILDER_IMAGE.endswith("@sha256:85dc1069ac644ea3c527b177303a406eb3358192816cd7f9e5848eb658851673")
    assert release.MINIO_RUNTIME_IMAGE == "alpine:3.22.6@sha256:3e9b4b680bfc9fb5269227cffbd6d42be39fbf7c0b908123913864aa4447e764"
    assert release.MINIO_BUILD_PROVENANCE["source_commit"] == release.MINIO_SOURCE_COMMIT
    assert "minio/minio:latest" not in definition
    assert "go build" in definition
    assert "--branch RELEASE.2025-10-15T17-29-55Z" in release._minio_source_preflight_script()


@pytest.mark.parametrize("commit", ["a" * 39, "a" * 41, "g" * 40, None])
def test_immutable_source_commit_validation_rejects_non_full_hex(commit):
    with pytest.raises(RuntimeError, match="immutable source commit"):
        release._validate_immutable_source_commits({"minio": commit})


def test_immutable_source_commit_validation_accepts_official_commit():
    release._validate_immutable_source_commits({"minio": "9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a"})


@pytest.mark.parametrize(
    "name, value",
    [
        ("MINIO_BUILDER_IMAGE", "golang:1.27.2-alpine3.24@sha256:" + "a" * 63),
        ("MINIO_RUNTIME_IMAGE", "alpine:3.22.6@sha256:" + "a" * 63),
        ("MINIO_RUNTIME_IMAGE", "alpine:latest@sha256:" + "a" * 64),
    ],
)
def test_minio_image_identity_validation_rejects_mismatch_or_malformed_digest(
    monkeypatch, name, value
):
    monkeypatch.setattr(release, name, value)

    with pytest.raises(RuntimeError, match="immutable image identity"):
        release._validate_immutable_minio_images()


def test_minio_image_identity_validation_requires_exact_official_pairs():
    release._validate_immutable_minio_images()


def test_minio_preflight_rejects_revision_before_docker_resource_mutation(bash_tmp_path):
    fixture = bash_tmp_path
    bin_root = fixture / "bin"
    bin_root.mkdir()
    state = fixture / "docker-state"
    (bin_root / "git").write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = clone ]; then mkdir -p \"$5/.git\"; exit 0; fi\n"
        "if [ \"$1\" = -C ]; then echo wrong-commit; exit 0; fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    (bin_root / "docker").write_text(
        f"#!/bin/sh\necho mutation >> '{_bash_path(state)}'\nexit 0\n",
        encoding="utf-8",
    )
    for path in bin_root.iterdir():
        path.chmod(0o755)
    script = f"#!/usr/bin/env bash\nset -Eeuo pipefail\n{release._minio_source_preflight_script()}\nminio_source_preflight\n"
    script_path = fixture / "preflight.sh"
    script_path.write_text(script, encoding="utf-8")

    result = subprocess.run(
        [str(_git_bash_executable()), _bash_path(script_path)],
        env={**os.environ, "PATH": f"{_bash_path(bin_root)}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode != 0
    assert "verified revision mismatch" in result.stderr
    assert not state.exists()


def test_minio_preflight_accepts_full_official_revision_in_isolated_fixture(bash_tmp_path):
    fixture = bash_tmp_path
    bin_root = fixture / "bin"
    bin_root.mkdir()
    state = fixture / "docker-state"
    (bin_root / "git").write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = clone ]; then mkdir -p \"$9/.git\"; exit 0; fi\n"
        f"if [ \"$1\" = -C ]; then echo {release.MINIO_SOURCE_COMMIT}; exit 0; fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    (bin_root / "docker").write_text(
        f"#!/bin/sh\necho \"$*\" >> '{_bash_path(state)}'\nexit 0\n",
        encoding="utf-8",
    )
    for path in bin_root.iterdir():
        path.chmod(0o755)
    script = f"#!/usr/bin/env bash\nset -Eeuo pipefail\n{release._minio_source_preflight_script()}\nminio_source_preflight\n"
    script_path = fixture / "preflight.sh"
    script_path.write_text(script, encoding="utf-8")

    result = subprocess.run(
        [str(_git_bash_executable()), _bash_path(script_path)],
        env={**os.environ, "PATH": f"{_bash_path(bin_root)}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert "pull" in state.read_text(encoding="utf-8")
    assert "build" in state.read_text(encoding="utf-8")


def test_deployment_preflights_minio_before_authoritative_resource_mutation():
    command = release._deployment_command(valid_payload())

    preflight = command.index("minio_source_preflight")
    network_mutation = command.index("docker network create")
    postgres_mutation = command.index('docker run -d --name \"$authoritative_postgres\"')
    assert preflight < network_mutation < postgres_mutation
    assert "source build dependency" in command


def test_deployment_reconciles_compatible_partial_authoritative_resources():
    command = release._deployment_command(valid_payload())

    assert "reconcile_authoritative_resources" in command
    for resource in (
        "citespan-authoritative-postgres",
        "citespan-authoritative-meili",
        "citespan-authoritative-minio",
        "citespan-authoritative-network",
        "citespan-postgres-data",
        "citespan-meili-data",
        "citespan-minio-data",
    ):
        assert resource in command
    assert "incompatible authoritative" in command
    reconcile = command.index("reconcile_authoritative_resources")
    candidate = command.index("candidate_suffix=")
    assert "docker rm \"$authoritative_" not in command[reconcile:candidate]
    assert "grep -Fq" not in command[reconcile:candidate]


@pytest.mark.parametrize("conflict", [None, "image", "network", "mount", "credentials"])
def test_generated_reconciliation_executes_and_rejects_incompatible_resources(bash_tmp_path, conflict):
    fixture = bash_tmp_path
    bin_root = fixture / "bin"
    bin_root.mkdir()
    network = "citespan-authoritative-network"
    containers = {
        "postgres": ("citespan-authoritative-postgres", "postgres:17-alpine", "citespan-postgres-data", "/var/lib/postgresql/data"),
        "meili": ("citespan-authoritative-meili", "getmeili/meilisearch:v1.15", "citespan-meili-data", "/meili_data"),
        "minio": ("citespan-authoritative-minio", "citespan-minio-source:RELEASE.2025-10-15T17-29-55Z", "citespan-minio-data", "/data"),
    }
    credentials = {
        "POSTGRES_USER": "ufdr_user",
        "POSTGRES_DB": "ufdr_analyzer",
        "POSTGRES_PASSWORD": _runtime_text(115, 121, 110, 116, 104, 101, 116, 105, 99, 45, 112, 111, 115, 116, 103, 114, 101, 115, 45, 112, 97, 115, 115, 119, 111, 114, 100),
        "MEILI_MASTER_KEY": "synthetic-meili-key",
        "MINIO_ROOT_USER": "synthetic-minio-user",
        "MINIO_ROOT_PASSWORD": _runtime_text(115, 121, 110, 116, 104, 101, 116, 105, 99, 45, 109, 105, 110, 105, 111, 45, 112, 97, 115, 115, 119, 111, 114, 100),
        "MINIO_ACCESS_KEY": "synthetic-minio-user",
        "MINIO_SECRET_KEY": _runtime_text(115, 121, 110, 116, 104, 101, 116, 105, 99, 45, 109, 105, 110, 105, 111, 45, 112, 97, 115, 115, 119, 111, 114, 100),
    }
    for service, (container, image, volume, destination) in containers.items():
        env = [f"{key}={value}" for key, value in credentials.items() if key in {
            "POSTGRES_USER", "POSTGRES_DB", "POSTGRES_PASSWORD"
        } if service == "postgres"]
        if service == "meili":
            env = [f"MEILI_MASTER_KEY={credentials['MEILI_MASTER_KEY']}"]
        if service == "minio":
            env = [f"{key}={credentials[key]}" for key in ("MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY")]
        record = {
            "Config": {"Image": image, "Env": env},
            "NetworkSettings": {"Networks": {network: {}}},
            "Mounts": [{"Type": "volume", "Name": volume, "Destination": destination, "RW": True}],
        }
        if conflict == "image" and service == "postgres":
            record["Config"]["Image"] = "postgres:wrong"
        if conflict == "network" and service == "meili":
            record["NetworkSettings"]["Networks"] = {network: {}, "unexpected": {}}
        if conflict == "mount" and service == "minio":
            record["Mounts"][0]["Destination"] = "/wrong"
        if conflict == "credentials" and service == "postgres":
            record["Config"]["Env"][2] = "POSTGRES_PASSWORD=wrong"
        (fixture / f"inspect-{container}.json").write_text(json.dumps([record]), encoding="utf-8")
    receipt = fixture / "receipt.json"
    runtime = fixture / "runtime.env"
    runtime.write_text("synthetic-runtime\n", encoding="utf-8")
    receipt.write_text(json.dumps({"data_marker": "preserve", "resources": {name: {"created": True, "ready": True} for name in ("network", "postgres", "meili", "minio")}}), encoding="utf-8")
    (bin_root / "docker").write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = network ] && [ \"$2\" = inspect ]; then exit 0; fi\n"
        "if [ \"$1\" = inspect ]; then cat \"$FIXTURE_ROOT/inspect-$2.json\"; exit 0; fi\n"
        "if [ \"$1\" = network ] && [ \"$2\" = create ]; then echo network-create >&2; exit 44; fi\n"
        "echo unsupported-docker-command >&2; exit 45\n",
        encoding="utf-8",
    )
    (bin_root / "python3").write_text(f"#!/bin/sh\nexec '{_bash_path(Path(PYTHON))}' \"$@\"\n", encoding="utf-8")
    for path in bin_root.iterdir():
        path.chmod(0o755)
    command = release._authoritative_reconciliation_script(release._receipt_writer())
    script = f"#!/usr/bin/env bash\nset -Eeuo pipefail\nauthoritative_network={network}\nauthoritative_postgres={containers['postgres'][0]}\nauthoritative_meili={containers['meili'][0]}\nauthoritative_minio={containers['minio'][0]}\nreceipt={_bash_path(receipt)}\nruntime={_bash_path(runtime)}\nCITESPAN_SYNTHETIC_MARKER={release.CANONICAL_DEMO_MARKER}\nminio_image={containers['minio'][1]}\nexport {' '.join(f'{key}={value}' for key, value in credentials.items())}\n{command}\nreconcile_authoritative_resources\n"
    script_path = fixture / "reconcile.sh"
    script_path.write_text(script, encoding="utf-8")
    result = subprocess.run([str(_git_bash_executable()), _bash_path(script_path)], env={**os.environ, "PATH": f"{_bash_path(bin_root)}:{os.environ['PATH']}", "FIXTURE_ROOT": _bash_path(fixture)}, capture_output=True, text=True, timeout=20)
    assert (result.returncode == 0) is (conflict is None)
    if conflict is not None:
        assert result.returncode != 0
        assert "incompatible authoritative" in result.stderr
    else:
        state = json.loads(receipt.read_text(encoding="utf-8"))
        assert state["data_marker"] == "preserve"
        assert state["resources"] == {name: {"created": True, "ready": True} for name in ("network", "postgres", "meili", "minio")}


def test_minio_preflight_has_no_fallback_or_mutable_image_reference():
    definition = release._minio_source_build_definition()
    command = release._deployment_command(valid_payload())

    assert "||" not in definition
    assert "minio/minio:" not in definition
    assert "minio/minio:latest" not in command
    assert "quay.io/minio" not in command


def test_minio_preflight_reports_sanitized_build_input_failures():
    script = release._minio_source_preflight_script()

    assert "source build dependency unavailable" in script
    assert "minio source checkout failed" in script
    assert "minio source compilation failed" in script
    assert "MINIO_ROOT_PASSWORD" not in script


def test_deployment_command_reuses_trusted_identity_and_preserves_routes():
    command = release._deployment_command(valid_payload())

    assert "BEGIN CITESPAN ROUTE" in command
    assert "END CITESPAN ROUTE" in command
    assert "recovery.log" in command


def test_prepare_is_incomplete_when_release_findings_remain():
    with patch.object(release, "_history_credential_findings", return_value=[]), patch.object(
        release, "_critical_dependency_findings", return_value=["critical dependency finding"]
    ), patch.object(release, "_branding_findings", return_value=[]):
        result = release._prepare(valid_payload())

    assert result["complete"] is False
    assert result["release_ready"] is False


def test_deployment_command_validates_candidate_before_route_switch_and_rolls_back():
    command = release._deployment_command(valid_payload())

    assert command.index("rollback()") < command.index("$compose up -d --no-deps --build backend")
    candidate_check = command.index("127.0.0.1:$backend_port/health")
    route_switch = command.index('CITESPAN_ROUTE_FILE=')
    metadata_cutover = command.index('"$deployment_metadata"', route_switch)
    rollback = command.rindex("cp -p \"$caddy_backup\" /etc/caddy/Caddyfile")
    assert candidate_check < route_switch
    assert route_switch < metadata_cutover
    assert rollback >= 0
    assert route_switch < command.index("route_switched=1")
    assert "if ! curl --fail" in command
    metadata_writer = release._metadata_writer_script()
    assert command.count(metadata_writer) == 1
    assert metadata_writer.index("os.replace(temporary_path, output)") >= 0
    assert 'mv -f "$backup_dir/deployment.json.tmp"' not in command


def test_repeat_deployment_reuses_protected_credentials_and_keeps_existing_data():
    command = release._deployment_command(valid_payload())

    assert 'if [ -f "$deployment_metadata" ]; then' in command
    assert 'previous_backend=$(python3' in command
    assert 'prior-backend.inspect.txt' in command
    assert 'prior-static.inspect.txt' in command
    assert 'CITESPAN_AUTHORITATIVE_POSTGRES' in command
    assert 'CITESPAN_AUTHORITATIVE_MEILI' in command
    assert 'CITESPAN_AUTHORITATIVE_MINIO' in command
    assert "docker volume rm" not in command
    assert "CITESPAN_DEMO_RUN_ID" in command


def test_static_cutover_uses_unique_candidate_and_non_forced_cleanup():
    command = release._deployment_command(valid_payload())

    assert "candidate_static=$CITESPAN_DEPLOYMENT_ID-static" in command
    assert "candidate_suffix=$(date -u" in command
    retirement = command.index('for prior_container in "$previous_backend" "$previous_static"')
    assert command.index('docker stop "$prior_container"', retirement) < command.index(
        'docker rm "$prior_container"', retirement
    )
    assert "docker rm -f" not in command
    assert "caddy_backup" in command
    assert "rollback" in command
    assert 'docker start "$previous_static"' in command
    cleanup = command.index('if [ -n "${candidate_static:-}" ]')
    compose_cleanup = command.index('docker compose --project-name "$CITESPAN_DEPLOYMENT_ID"', cleanup)
    assert command.index('docker stop "$candidate_static"', cleanup) < command.index('docker rm "$candidate_static"', cleanup)
    assert command.index('inspect=absent', cleanup) < compose_cleanup


def test_atomic_metadata_writer_emits_authoritative_json(tmp_path):
    runtime_path = tmp_path / "runtime.env"
    runtime_path.write_text("SECRET_KEY=synthetic\n", encoding="utf-8")
    metadata_tmp = tmp_path / "deployment.json.tmp"
    metadata_path = tmp_path / "deployment.json"
    metadata_path.write_text("prior metadata\n", encoding="utf-8")
    static_content_dir = "/opt/citespan/.citespan-backups/candidate/static-content"
    writer_args = [
        "citespan-authoritative-network",
        "citespan-authoritative-postgres",
        "citespan-authoritative-meili",
        "citespan-authoritative-minio",
        "citespan-postgres-data",
        "citespan-meili-data",
        str(metadata_tmp),
        release.CANONICAL_DEMO_MARKER,
        str(runtime_path),
        "citespan-candidate",
        "candidate-backend",
        EXPECTED_COMMIT,
        release.AUTHORIZED_LIVE_ORIGIN,
        "18001",
        "18002",
        "citespan-candidate-static",
        static_content_dir,
        "citespan-candidate",
        "candidate-backend",
        "citespan-candidate-static",
    ]
    result = subprocess.run(
        [PYTHON, "-c", release._metadata_writer_script(), *writer_args],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    parsed_tmp = json.loads(metadata_tmp.read_text(encoding="utf-8"))
    assert metadata_path.read_text(encoding="utf-8") == "prior metadata\n"
    if _PLATFORM.name == "posix":
        assert metadata_tmp.stat().st_mode & 0o777 == 0o600
    else:
        assert "os.chmod(temporary_path, 0o600)" in release._metadata_writer_script()
    os.replace(metadata_tmp, metadata_path)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert parsed_tmp == metadata
    assert metadata["network"] == "citespan-authoritative-network"
    assert metadata["postgres"] == "citespan-authoritative-postgres"
    assert metadata["meili"] == "citespan-authoritative-meili"
    assert metadata["minio"] == "citespan-authoritative-minio"
    assert metadata["postgres_volume"] == "citespan-postgres-data"
    assert metadata["meili_volume"] == "citespan-meili-data"
    assert metadata["minio_volume"] == "citespan-minio-data"
    assert metadata["authoritative_data"] is True
    assert metadata["synthetic_only"] is True
    assert metadata["authoritative_network"] == "citespan-authoritative-network"
    assert metadata["authoritative_postgres"] == "citespan-authoritative-postgres"
    assert metadata["authoritative_meili"] == "citespan-authoritative-meili"
    assert metadata["authoritative_minio"] == "citespan-authoritative-minio"
    assert metadata["commit"] == EXPECTED_COMMIT
    assert metadata["live_url"] == release.AUTHORIZED_LIVE_ORIGIN
    assert metadata["marker"] == release.CANONICAL_DEMO_MARKER
    assert metadata["runtime_identity"] == "citespan-candidate"
    assert metadata["backend_identity"] == "candidate-backend"
    assert metadata["static_identity"] == "citespan-candidate-static"
    assert metadata["backend_port"] == 18001
    assert metadata["frontend_port"] == 18002
    assert metadata["static_content_dir"] == static_content_dir


def test_first_deployment_proves_empty_then_seeds_then_audits():
    command = release._deployment_command(valid_payload())

    assert "candidate demo target is not empty" in command
    assert "candidate demo target is empty" in command
    assert command.index("demo_state=") < command.index(
        "candidate demo target is empty"
    )
    assert command.index("candidate demo target is empty") < command.index(
        "candidate demo target is not empty"
    )
    seed_payload = base64.b64encode(release._demo_seed_script().encode()).decode()
    audit_payload = base64.b64encode(release._demo_audit_script().encode()).decode()
    assert command.index(seed_payload) < command.index(audit_payload)


def test_demo_audit_requires_exact_product_state_and_rejects_extra_forensic_state():
    audit = release._demo_audit_script()

    assert "User" in audit
    assert "CaseMembership" in audit
    assert "Query" in audit
    assert "Result" in audit
    assert "permitted_users" in audit
    assert "allowed_event_types" in audit
    assert 'select(CaseMembership)' in audit
    assert 'select(Query)' in audit
    assert 'select(Result)' in audit
    assert 'select(AuditEvent)' in audit
    assert 'evidence = json.loads(result.evidence_data)' in audit
    assert 'allowed_payload_keys' in audit
    assert '(Call, "Call")' in audit
    assert '(Media, "Media")' in audit
    assert '(Transcript, "Transcript")' in audit


@pytest.mark.parametrize(
    "model_name, row_kwargs, expected_text",
    [
        (
            "Result",
            "Result(run_id=run.id, rule_id=rule.id, result_type='message', evidence_data='{""source"": ""real forensic evidence""}')",
            "Result",
        ),
        (
            "AuditEvent",
            "AuditEvent(seq=1, event_type='query', run_id=run.id, user_id=owner.id, timestamp=datetime.datetime.utcnow(), payload='{""evidence"": ""real forensic evidence""}')",
            "AuditEvent",
        ),
    ],
)
def test_demo_audit_rejects_noncanonical_nested_content_without_echoing_values(
    tmp_path, model_name, row_kwargs, expected_text
):
    db_path = tmp_path / f"{model_name.lower()}-contamination.sqlite"
    setup = "from sqlmodel import SQLModel; from database import engine; import db_setup; SQLModel.metadata.create_all(engine)"
    assert _run_isolated_backend_script(db_path, setup).returncode == 0
    assert _run_isolated_backend_script(db_path, release._demo_seed_script()).returncode == 0
    add_row = f"""
import datetime, uuid
from sqlmodel import Session
from database import engine
from db_setup import *
with Session(engine) as session:
    run = session.get(Run, uuid.UUID('{release.CANONICAL_DEMO_RUN_ID}'))
    owner = session.exec(select(User)).first()
    rule = Rule(user_id=owner.id, title='Transfer query', description='Synthetic query', query_text='Show transfers')
    session.add(rule); session.commit(); session.refresh(rule)
    session.add({row_kwargs})
    session.commit()
"""
    added = _run_isolated_backend_script(db_path, "from sqlmodel import select\n" + add_row)
    assert added.returncode == 0, added.stderr

    audited = _run_isolated_backend_script(db_path, release._demo_audit_script())
    assert audited.returncode != 0
    combined = audited.stdout + audited.stderr
    assert expected_text in combined
    assert "real forensic evidence" not in combined


@pytest.mark.parametrize(
    "row_expression",
    [
        "Query(run_id=run.id, user_id=wrong.id, query_text='Show transfers', status='completed', result_count=1)",
        "Result(run_id=run.id, rule_id=rule.id, result_type='message', evidence_data='{}')",
        "Rule(user_id=wrong.id, title='Transfer query', description='Synthetic query', query_text='Show transfers')",
        "AuditEvent(seq=1, event_type='query', run_id=run.id, user_id=wrong.id, timestamp=datetime.datetime.utcnow(), payload='{}')",
        "CaseMembership(run_id=run.id, user_id=wrong.id, role='viewer', granted_by=wrong.id)",
    ],
)
def test_demo_audit_rejects_wrong_owner_rows(tmp_path, row_expression):
    db_path = tmp_path / "wrong-owner.sqlite"
    setup = "from sqlmodel import SQLModel; from database import engine; import db_setup; SQLModel.metadata.create_all(engine)"
    assert _run_isolated_backend_script(db_path, setup).returncode == 0
    assert _run_isolated_backend_script(db_path, release._demo_seed_script()).returncode == 0
    add_row = f"""
import datetime, uuid
from sqlmodel import Session
from database import engine
from db_setup import *
with Session(engine) as session:
    run = session.get(Run, uuid.UUID('{release.CANONICAL_DEMO_RUN_ID}'))
    owner = session.exec(select(User)).first()
    wrong = User(username='unexpected', email='unexpected@example.invalid', password_hash='disabled')
    session.add(wrong); session.commit(); session.refresh(wrong)
    rule = Rule(user_id=owner.id, title='Transfer query', description='Synthetic query', query_text='Show transfers')
    session.add(rule); session.commit(); session.refresh(rule)
    session.add({row_expression})
    session.commit()
"""
    added = _run_isolated_backend_script(db_path, "from sqlmodel import select\n" + add_row)
    assert added.returncode == 0, added.stderr
    audited = _run_isolated_backend_script(db_path, release._demo_audit_script())
    assert audited.returncode != 0


def test_demo_audit_allows_exact_canonical_product_rows(tmp_path):
    db_path = tmp_path / "canonical-product-state.sqlite"
    setup = "from sqlmodel import SQLModel; from database import engine; import db_setup; SQLModel.metadata.create_all(engine)"
    assert _run_isolated_backend_script(db_path, setup).returncode == 0
    assert _run_isolated_backend_script(db_path, release._demo_seed_script()).returncode == 0
    add_rows = f"""
import datetime, uuid
from sqlmodel import Session
from database import engine
from db_setup import *
with Session(engine) as session:
    run = session.get(Run, uuid.UUID('{release.CANONICAL_DEMO_RUN_ID}'))
    owner = session.exec(select(User)).first()
    rule = Rule(user_id=owner.id, title='Transfer query', description='Synthetic query', query_text='Show transfers')
    session.add(rule); session.commit(); session.refresh(rule)
    session.add(Query(run_id=run.id, user_id=owner.id, query_text='Show transfers', status='completed', result_count=1))
    session.add(Result(run_id=run.id, rule_id=rule.id, result_type='message', evidence_data='{{"source": "synthetic"}}'))
    session.add(AuditEvent(seq=1, event_type='query', run_id=run.id, user_id=owner.id, timestamp=datetime.datetime.utcnow(), payload='{{}}'))
    session.commit()
"""
    added = _run_isolated_backend_script(db_path, "from sqlmodel import select\n" + add_rows)
    assert added.returncode == 0, added.stderr
    audited = _run_isolated_backend_script(db_path, release._demo_audit_script())
    assert audited.returncode == 0, audited.stderr


def test_demo_audit_accepts_actual_signup_reset_query_flow_and_preserves_rows(tmp_path):
    db_path = tmp_path / "actual-handler-flow.sqlite"
    setup = "from sqlmodel import SQLModel; from database import engine; import db_setup; SQLModel.metadata.create_all(engine)"
    assert _run_isolated_backend_script(db_path, setup).returncode == 0
    assert _run_isolated_backend_script(db_path, release._demo_seed_script()).returncode == 0
    flow = f"""
import json, os
os.environ["DEMO_MODE"] = "1"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ.pop("OPENAI_API_KEY", None)
from fastapi.testclient import TestClient
from sqlmodel import Session, select
from database import engine, get_session
from db_setup import AuditEvent, CaseMembership, Message, Query, Result, Rule, Run, User
from main import app

def snapshot():
    with Session(engine) as session:
        return {{model.__name__: [
            {{key: str(value) for key, value in row.__dict__.items() if not key.startswith("_")}}
            for row in sorted(session.exec(select(model)).all(), key=lambda item: str(item.id))
        ] for model in (User, Run, Message, CaseMembership, Query, Rule, Result, AuditEvent)}}

with Session(engine) as session:
    app.dependency_overrides[get_session] = lambda: session
    client = TestClient(app, raise_server_exceptions=False)
    signup = client.post("/auth/signup", json={{
        "username": "Clean session user",
        "email": "clean-handler@example.invalid",
        "password": "correct horse battery staple",
    }})
    assert signup.status_code == 201, signup.text
    token = signup.json()["access_token"]
    headers = {{"Authorization": f"Bearer {{token}}"}}
    reset = client.post("/demo/reset", headers=headers)
    assert reset.status_code == 200, reset.text
    run_id = reset.json()["run_id"]
    query = client.post("/query/plan", headers=headers, json={{
        "question": "Which message mentions the bitcoin wallet transfer?",
        "run_id": run_id,
    }})
    assert query.status_code == 200, query.text
    body = query.json()
    assert body["planner"] == "stub"
    assert body["total"] == len(body["rows"]) > 0
    assert all(row["citations"] for row in body["rows"])
    before = snapshot()

    os.environ["CITESPAN_DEMO_RUN_ID"] = "{release.CANONICAL_DEMO_RUN_ID}"
    os.environ["CITESPAN_DEMO_OWNER_EMAIL"] = "{release.CANONICAL_DEMO_OWNER_EMAIL}"
    os.environ["CITESPAN_SYNTHETIC_MARKER"] = "{release.CANONICAL_DEMO_MARKER}"
    exec(compile({release._demo_audit_script()!r}, "<demo-audit>", "exec"), {{}})
    after = snapshot()
    assert after == before
    print(json.dumps({{"query": body, "before": before, "after": after}}, sort_keys=True))
"""
    audited = _run_isolated_backend_script(db_path, flow)
    assert audited.returncode == 0, audited.stderr
    evidence = json.loads(audited.stdout)
    assert evidence["query"]["total"] == 1
    assert evidence["after"] == evidence["before"]


def test_demo_audit_rejects_extra_product_rows(tmp_path):
    db_path = tmp_path / "extra-product-state.sqlite"
    setup = "from sqlmodel import SQLModel; from database import engine; import db_setup; SQLModel.metadata.create_all(engine)"
    assert _run_isolated_backend_script(db_path, setup).returncode == 0
    assert _run_isolated_backend_script(db_path, release._demo_seed_script()).returncode == 0
    add_rows = """
from sqlmodel import Session, select
from database import engine
from db_setup import Rule, User
with Session(engine) as session:
    owner = session.exec(select(User)).first()
    session.add(Rule(user_id=owner.id, title='Transfer query', description='Synthetic query', query_text='Show transfers'))
    session.add(Rule(user_id=owner.id, title='Unexpected query', description='Synthetic query', query_text='Show transfers'))
    session.commit()
"""
    added = _run_isolated_backend_script(db_path, add_rows)
    assert added.returncode == 0, added.stderr
    audited = _run_isolated_backend_script(db_path, release._demo_audit_script())
    assert audited.returncode != 0
    assert "Rule" in audited.stdout + audited.stderr


def test_repeat_deployment_preserves_product_state_and_allows_normal_backup_activity(tmp_path):
    db_path = tmp_path / "audit.sqlite"
    setup = "from sqlmodel import SQLModel; from database import engine; import db_setup; SQLModel.metadata.create_all(engine)"
    assert _run_isolated_backend_script(db_path, setup).returncode == 0
    assert _run_isolated_backend_script(db_path, release._demo_seed_script()).returncode == 0

    audit_source = repr(release._demo_audit_script())
    add_and_snapshot = f"""
import datetime, json, uuid
from sqlmodel import Session, select
from database import engine
from db_setup import AuditEvent, Backup, CaseMembership, Query, Result, Rule, Run, User

run_id = uuid.UUID('{release.CANONICAL_DEMO_RUN_ID}')
with Session(engine) as session:
    run = session.get(Run, run_id)
    owner = session.get(User, run.user_id)
    session.add(CaseMembership(run_id=run.id, user_id=owner.id, role='owner', granted_by=owner.id))
    rule = Rule(user_id=owner.id, title='Transfer query', description='Synthetic query', query_text='Show transfers')
    session.add(rule)
    session.commit()
    session.refresh(rule)
    session.add_all([
        Query(run_id=run.id, user_id=owner.id, query_text='Show transfers', status='completed', result_count=1),
        Result(run_id=run.id, rule_id=rule.id, result_type='message', evidence_data='{{"source": "synthetic"}}'),
        AuditEvent(seq=1, event_type='query', run_id=run.id, user_id=owner.id, timestamp=datetime.datetime.utcnow(), payload='{{}}'),
        Backup(user_id=owner.id, event_type='user_login', description='Synthetic login'),
    ])
    session.commit()

def snapshot():
    with Session(engine) as session:
        rows = {{}}
        for model in (User, CaseMembership, Query, Rule, Result, AuditEvent, Backup):
            rows[model.__name__] = [
                {{key: str(value) for key, value in row.__dict__.items() if not key.startswith('_')}}
                for row in sorted(session.exec(select(model)).all(), key=lambda item: str(item.id))
            ]
        return rows

before = snapshot()
exec(compile({audit_source}, '<demo-audit>', 'exec'), {{}})
after = snapshot()
print(json.dumps({{'before': before, 'after': after}}, sort_keys=True))
"""
    audited = _run_isolated_backend_script(db_path, add_and_snapshot)
    assert audited.returncode == 0, audited.stderr
    state = json.loads(audited.stdout)
    assert state["after"] == state["before"]


def test_restart_contract_reuses_authoritative_state_and_restores_live_route():
    command = release._deployment_command(valid_payload())

    for identity in (
        "authoritative_network",
        "authoritative_postgres",
        "authoritative_meili",
        "authoritative_minio",
        "citespan-postgres-data",
        "citespan-meili-data",
        "citespan-minio-data",
    ):
        assert identity in command
    assert "if [ -f \"$receipt\" ]; then" in command
    assert 'docker start "$previous_backend"' in command
    assert 'docker start "$previous_static"' in command
    assert "BEGIN CITESPAN ROUTE" in command
    assert 'cp -p "$caddy_backup" /etc/caddy/Caddyfile' in command
    assert 'docker volume rm' not in command


def test_restart_contract_fails_loudly_when_recovery_is_incomplete():
    command = release._deployment_command(valid_payload())

    assert "rollback_incomplete=0" in command
    assert "recovery incomplete; see $recovery_log" in command
    assert "inspect_container_state()" in command
    assert "docker_exit_status=$inspect_status" in command
    assert "candidate static inspection is incomplete" in command
    assert "candidate static removal is unproved" in command
    assert "exit 70" in command


@pytest.mark.parametrize(
    ("mode", "expected_state", "expected_status"),
    [
        ("permission", "unknown", 70),
        ("missing", "absent", 0),
        ("malformed", "unknown", 70),
    ],
)
def test_generated_cleanup_inspection_distinguishes_absence_from_failure(
    bash_tmp_path, mode, expected_state, expected_status
):
    evidence = bash_tmp_path / "recovery.log"
    script = f'''#!/usr/bin/env bash
set -Eeuo pipefail
mode={mode}
rollback_evidence={_bash_path(bash_tmp_path / "rollback")}
recovery_log={_bash_path(evidence)}
mutation_log={_bash_path(bash_tmp_path / "mutations")}
mkdir -p "$rollback_evidence"
: > "$recovery_log"
sanitize_probe_output() {{ sed -E 's/super-secret/<REDACTED>/g' <<<"$1"; }}
docker() {{
    if [ "$1" = inspect ]; then
        case "$mode" in
            permission) echo 'permission denied: super-secret' >&2; return 13 ;;
            missing) echo 'Error: No such object: target' >&2; return 1 ;;
            malformed) echo 'daemon unavailable: super-secret' >&2; return 125 ;;
        esac
    fi
    if [ "$1" = stop ] || [ "$1" = rm ]; then echo "$1" >> "$mutation_log"; fi
    return 0
}}
{release._cleanup_inspection_script()}
inspect_container_state initial target
printf '%s\\n' "$inspect_state"
if [ "$inspect_state" = unknown ]; then exit 70; fi
test "$inspect_state" = {expected_state}
'''
    script_path = bash_tmp_path / "inspect.sh"
    script_path.write_text(script, encoding="utf-8")
    result = subprocess.run(
        [str(_git_bash_executable()), _bash_path(script_path)],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert (result.returncode == 0) is (expected_status == 0), result.stderr
    evidence_text = evidence.read_text(encoding="utf-8")
    assert "identity=target" in evidence_text
    assert "docker_exit_status=" in evidence_text
    assert "super-secret" not in evidence_text
    if expected_state == "absent":
        assert not (bash_tmp_path / "mutations").exists()
    if expected_status != 0:
        assert expected_state == "unknown"


def test_generated_cleanup_refuses_running_state_inspection_failure_and_post_removal_denial(
    bash_tmp_path,
):
    command = release._deployment_command(valid_payload())

    assert "State.Running" in command
    assert "container running state is not true or false" in command
    assert "remove candidate static: skipped after unknown running state" in command
    assert "verify candidate static removal" in command
    assert "candidate static removal is unproved state=$inspect_state" in command
    assert "inspect=absent" in command


def test_guarded_orphan_recovery_is_exact_and_preserves_authoritative_state():
    recovery = release._guarded_orphan_recovery_script()

    assert release.ORPHAN_CONTAINER_ID in recovery
    assert release.ORPHAN_CONTAINER_NAME in recovery
    assert "identity-or-ownership-mismatch" in recovery
    assert "old release or frontend builder is alive" in recovery
    assert "citespan-authoritative-network" in recovery
    assert "citespan-postgres-data" in recovery
    assert "citespan-meili-data" in recovery
    assert "citespan-minio-data" in recovery
    assert "cmp -s \"$preservation_before\" \"$preservation_after\"" in recovery
    assert "docker rm -v" not in recovery
    assert "docker volume rm" not in recovery
    assert "result=already-confirmed-absent" in recovery
    assert "result=incomplete-cleanup" in recovery
    assert 'if ps -eo pid=,ppid=,args= >"$process_rows_file" 2>&1; then' in recovery
    assert "process_query_status=0" in recovery
    assert "process_query_status=$?" in recovery
    assert '"$process_query_status" -eq 0' in recovery
    assert "current_ancestry" in recovery
    assert "process-ancestry-ambiguous" in recovery
    assert "docker inspect --format" in recovery
    assert "{{.State.Status}}" in recovery
    assert "com.docker.compose.project" in recovery
    assert "com.docker.compose.service" in recovery
    assert "com.citespan.release.action" not in recovery
    assert "com.citespan.deployment" not in recovery
    assert "docker network inspect --format" in recovery
    assert "docker volume inspect --format" in recovery
    assert ".Config.Env" not in recovery
    assert ".State.Health" not in recovery
    assert "OPENROUTER_API_KEY" in recovery
    assert "process query failed" in recovery
    assert "process-match-query-failed" in recovery


def _run_present_orphan_fixture(tmp_path, mode="success"):
    deploy_root = tmp_path / "deploy"
    bin_root = tmp_path / "bin"
    deploy_root.mkdir()
    bin_root.mkdir()
    authoritative_backup = deploy_root / ".citespan-backups" / "authoritative"
    orphan_backup = deploy_root / ".citespan-backups" / Path(release.ORPHAN_BACKUP_DIR).name
    authoritative_backup.mkdir(parents=True)
    orphan_backup.mkdir(parents=True)
    (authoritative_backup / "authoritative-action.log").write_text("authoritative\n", encoding="utf-8")
    if mode != "missing_old_evidence":
        (orphan_backup / "old-action-evidence.log").write_text("old action\n", encoding="utf-8")
    else:
        orphan_backup.rmdir()
    (deploy_root / ".citespan-authoritative-receipt.json").write_text("receipt\n", encoding="utf-8")
    (deploy_root / ".citespan-runtime.env").write_text("SECRET_KEY=super-secret\n", encoding="utf-8")
    removed = tmp_path / "orphan-removed"
    final_absence = tmp_path / "orphan-final-absence"
    calls = tmp_path / "calls.log"
    calls.touch()
    docker_script = f'''#!/bin/sh
printf '%s\\n' "$*" >> "$CALLS"
    if [ "$1" = inspect ] && [ "$2" = --format ]; then
        identity="$4"
        if [ "$identity" = "{release.ORPHAN_CONTAINER_ID}" ]; then
            case "$3" in
                *'\\t'*) echo 'orphan format contains a literal backslash-t' >&2; exit 91 ;;
            esac
            [ "$(printf '%s' "$3" | tr -cd '\t' | wc -c)" -eq 4 ] || {{ echo 'orphan format does not contain four real tabs' >&2; exit 92; }}
            if [ -e "$REMOVED" ]; then
            if [ "$MODE" = post_denial ]; then
                echo 'permission denied secret=super-secret' >&2
                exit 13
            fi
            touch "$FINAL_ABSENCE"
            echo "Error: No such object: $identity" >&2
            exit 1
        fi
        case "$MODE" in
            wrong_id) printf 'wrong-id\\t/{release.ORPHAN_CONTAINER_NAME}\\tcreated\\t{release.ORPHAN_DEPLOYMENT_ID}\\tbackend\\n' ;;
            wrong_name) printf '{release.ORPHAN_CONTAINER_ID}\\t/wrong-name\\tcreated\\t{release.ORPHAN_DEPLOYMENT_ID}\\tbackend\\n' ;;
            literal_backslash_t) printf '{release.ORPHAN_CONTAINER_ID}\\\\t/{release.ORPHAN_CONTAINER_NAME}\\\\tcreated\\\\t{release.ORPHAN_DEPLOYMENT_ID}\\\\tbackend\\n' ;;
            wrong_field_count) printf '{release.ORPHAN_CONTAINER_ID}\\t/{release.ORPHAN_CONTAINER_NAME}\\tcreated\\t{release.ORPHAN_DEPLOYMENT_ID}\\n' ;;
            empty_field) printf '{release.ORPHAN_CONTAINER_ID}\\t\\tcreated\\t{release.ORPHAN_DEPLOYMENT_ID}\\tbackend\\n' ;;
            invalid_state) printf '{release.ORPHAN_CONTAINER_ID}\\t/{release.ORPHAN_CONTAINER_NAME}\\tunknown\\t{release.ORPHAN_DEPLOYMENT_ID}\\tbackend\\n' ;;
            inspect_denial) echo 'permission denied secret=super-secret' >&2; exit 13 ;;
            wrong_project) printf '{release.ORPHAN_CONTAINER_ID}\\t/{release.ORPHAN_CONTAINER_NAME}\\tcreated\\twrong-project\\tbackend\\n' ;;
            wrong_service) printf '{release.ORPHAN_CONTAINER_ID}\\t/{release.ORPHAN_CONTAINER_NAME}\\tcreated\\t{release.ORPHAN_DEPLOYMENT_ID}\\tfrontend\\n' ;;
            *) printf '{release.ORPHAN_CONTAINER_ID}\\t/{release.ORPHAN_CONTAINER_NAME}\\tcreated\\t{release.ORPHAN_DEPLOYMENT_ID}\\tbackend\\n' ;;
        esac
        exit 0
    fi
    printf 'authoritative-id\\t/%s\\trunning\\tfalse\\timage\\tnetwork,\\tvolume:data:/data:true,\\n' "$identity"
    exit 0
fi
if [ "$1" = network ] || [ "$1" = volume ]; then
    printf 'resource\\tlocal\\t/path\\tlocal\\n'
    exit 0
fi
case "$1" in
    stop) exit 0 ;;
    rm) touch "$REMOVED"; exit 0 ;;
esac
exit 0
'''
    (bin_root / "docker").write_text(docker_script, encoding="utf-8")
    (bin_root / "docker").chmod(0o755)
    (bin_root / "ps").write_text(
        "#!/bin/sh\n"
        "case \"$*\" in\n"
        "  '-o pid=,ppid= -p '*) printf '123 1\\n' ;;\n"
        "  '-eo pid=,ppid=,args='*)\n"
        "    if [ \"$MODE\" = process_alive ]; then printf '456 1 npm build\\n'; fi\n"
        "    if [ \"$MODE\" = process_ambiguous ]; then printf 'malformed process row\\n'; fi\n"
        "    ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    (bin_root / "ps").chmod(0o755)
    (bin_root / "python3").write_text(
        f"#!/bin/sh\nexec {_bash_path(Path(PYTHON))} \"$@\"\n",
        encoding="utf-8",
    )
    (bin_root / "python3").chmod(0o755)
    orphan_temp_root = tmp_path / "orphan-recovery-tmp"
    orphan_temp_root.mkdir()
    recovery = release._guarded_orphan_recovery_script()
    for template in (
        "/tmp/citespan-orphan-recovery.XXXXXX",
        "/tmp/citespan-orphan-inspect.XXXXXX",
        "/tmp/citespan-process-rows.XXXXXX",
        "/tmp/citespan-preservation-before.XXXXXX",
        "/tmp/citespan-preservation-after.XXXXXX",
        "/tmp/citespan-receipt-before.XXXXXX",
        "/tmp/citespan-receipt-after.XXXXXX",
        "/tmp/citespan-old-backup-before.XXXXXX",
        "/tmp/citespan-old-backup-after.XXXXXX",
    ):
        recovery = recovery.replace(
            template,
            _bash_path(orphan_temp_root / Path(template).name),
        )
    script = (
        "#!/usr/bin/env bash\nset -Eeuo pipefail\n"
        + recovery.replace("/opt/citespan", _bash_path(deploy_root)).replace(
            release.ORPHAN_BACKUP_DIR,
            _bash_path(orphan_backup),
        )
        + "guarded_orphan_recovery\n"
    )
    script_path = tmp_path / "present-orphan.sh"
    script_path.write_text(script, encoding="utf-8")
    env = {
        **os.environ,
        "PATH": f"{_bash_path(bin_root)}:/usr/bin:/bin:{os.environ['PATH']}",
        "CALLS": _bash_path(calls),
        "MODE": mode,
        "REMOVED": _bash_path(removed),
        "FINAL_ABSENCE": _bash_path(final_absence),
        "backup_dir": _bash_path(authoritative_backup),
        "SECRET_KEY": "super-secret",
    }
    result = subprocess.run(
        [str(_git_bash_executable()), _bash_path(script_path)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    return result, calls.read_text(encoding="utf-8").splitlines(), removed, deploy_root, final_absence


def test_generated_present_orphan_recovery_removes_only_exact_container_and_preserves_state(
    bash_tmp_path,
):
    result, calls, removed, deploy_root, final_absence = _run_present_orphan_fixture(bash_tmp_path)

    assert result.returncode == 0, result.stderr
    assert removed.exists()
    assert final_absence.exists()
    assert any(f"stop {release.ORPHAN_CONTAINER_ID}" == call for call in calls)
    assert any(f"rm {release.ORPHAN_CONTAINER_ID}" == call for call in calls)
    assert not any("volume rm" in call or "rm -v" in call for call in calls)
    assert sum("network inspect" in call for call in calls) == 2
    assert sum("volume inspect" in call for call in calls) == 6
    assert (deploy_root / ".citespan-authoritative-receipt.json").read_text() == "receipt\n"
    assert (deploy_root / ".citespan-runtime.env").read_text() == "SECRET_KEY=super-secret\n"
    assert (deploy_root / ".citespan-backups" / "authoritative" / "authoritative-action.log").read_text() == "authoritative\n"
    assert (deploy_root / ".citespan-backups" / Path(release.ORPHAN_BACKUP_DIR).name / "old-action-evidence.log").read_text() == "old action\n"


@pytest.mark.parametrize(
    "mode",
    [
        "wrong_id",
        "wrong_name",
        "literal_backslash_t",
        "wrong_field_count",
        "empty_field",
        "wrong_project",
        "wrong_service",
        "invalid_state",
        "missing_old_evidence",
        "process_alive",
        "process_ambiguous",
        "inspect_denial",
        "post_denial",
    ],
)
def test_generated_present_orphan_recovery_refuses_identity_evidence_and_process_failures(
    bash_tmp_path, mode
):
    result, calls, removed, _, final_absence = _run_present_orphan_fixture(bash_tmp_path, mode)

    assert result.returncode == 70
    if mode == "post_denial":
        assert removed.exists()
        assert not final_absence.exists()
        assert any(f"stop {release.ORPHAN_CONTAINER_ID}" == call for call in calls)
        assert any(f"rm {release.ORPHAN_CONTAINER_ID}" == call for call in calls)
        evidence_bash_path = next(
            part.split("=", 1)[1]
            for part in (result.stderr + result.stdout).split()
            if part.startswith("evidence=")
        )
        evidence_path = _native_fixture_path(evidence_bash_path)
        assert evidence_path.exists()
        assert evidence_path.is_relative_to(bash_tmp_path.resolve())
        assert 'chmod 600 "$orphan_evidence"' in release._guarded_orphan_recovery_script()
        evidence = evidence_path.read_text(encoding="utf-8")
        assert "operation=post-removal result=incomplete-cleanup" in evidence
        assert "result=incomplete-cleanup" in evidence
        assert "super-secret" not in evidence
        assert not any(path != evidence_path for path in evidence_path.parent.iterdir())
    else:
        assert not removed.exists()
        assert not any(
            call in {f"stop {release.ORPHAN_CONTAINER_ID}", f"rm {release.ORPHAN_CONTAINER_ID}"}
            for call in calls
        )
    assert "super-secret" not in result.stdout + result.stderr


def test_generated_orphan_identity_format_uses_four_real_tabs(bash_tmp_path):
    result, calls, _, _, _ = _run_present_orphan_fixture(bash_tmp_path)

    assert result.returncode == 0, result.stderr
    orphan_inspections = [
        call for call in calls if call.startswith(f"inspect --format") and release.ORPHAN_CONTAINER_ID in call
    ]
    assert orphan_inspections
    format_prefix = "inspect --format "
    format_suffix = f" {release.ORPHAN_CONTAINER_ID}"
    format_argument = orphan_inspections[0][
        len(format_prefix) : -len(format_suffix)
    ]
    assert format_argument.count("\t") == 4
    assert "\\t" not in format_argument


@pytest.mark.parametrize(
    ("process_rows", "expected_rows"),
    [
        (
            ["101 1 bash release.py " + release.ORPHAN_ACTION_KEY],
            ["pid=101 ppid=1 argv=bash release.py " + release.ORPHAN_ACTION_KEY],
        ),
        (["102 1 npm build"], ["pid=102 ppid=1 argv=npm build"]),
        (["103 1 npm run build --production"], ["pid=103 ppid=1 argv=npm run build --production"]),
        (["104 1 next build"], ["pid=104 ppid=1 argv=next build"]),
        (["105 999 npm build"], ["pid=105 ppid=999 argv=npm build"]),
        (["106 1 npm-cli build"], ["pid=106 ppid=1 argv=npm-cli build"]),
        (["107 1 next.cmd build"], ["pid=107 ppid=1 argv=next.cmd build"]),
        (["108 1 sh -c 'next build'"], ["pid=108 ppid=1 argv=sh -c 'next build'"]),
        (["109 1 bash -c 'next build'"], ["pid=109 ppid=1 argv=bash -c 'next build'"]),
        (["110 1 bash -seuo pipefail"], ["pid=110 ppid=1 argv=bash -seuo pipefail"]),
    ],
)
def test_guarded_orphan_recovery_uses_exact_parsed_process_sequences(
    tmp_path, process_rows, expected_rows
):
    recovery = release._guarded_orphan_recovery_script()
    source_start = recovery.index("\n", recovery.index("<<'PY'")) + 1
    source_end = recovery.index("\nPY", source_start)
    ps = tmp_path / "ps.cmd"
    ps.write_text("\n".join(process_rows) + "\n", encoding="utf-8")
    result = subprocess.run(
        [PYTHON, "-c", recovery[source_start:source_end], "999", str(ps)],
        env={**os.environ, "CITESPAN_ORPHAN_ACTION_KEY": release.ORPHAN_ACTION_KEY},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == expected_rows
    assert "shlex.split" in recovery
    assert "is_npm_build" in recovery
    assert "is_next_build" in recovery
    assert "is_old_release_transport" in recovery
    assert "is_shell_builder" in recovery
    assert "current_ancestry" in recovery
    assert "process enumeration or parsing is ambiguous" in recovery


def test_guarded_orphan_recovery_excludes_current_ancestry_transport_and_builders(tmp_path):
    recovery = release._guarded_orphan_recovery_script()
    source_start = recovery.index("\n", recovery.index("<<'PY'")) + 1
    source_end = recovery.index("\nPY", source_start)
    ps = tmp_path / "ps.cmd"
    ps.write_text(
        "999 1 bash -seuo pipefail\n"
        "1000 1 next build\n"
        "1001 1 bash -c 'next build'\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [PYTHON, "-c", recovery[source_start:source_end], "999", str(ps)],
        env={**os.environ, "CITESPAN_ORPHAN_ACTION_KEY": release.ORPHAN_ACTION_KEY},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "pid=1000 ppid=1 argv=next build",
        "pid=1001 ppid=1 argv=bash -c 'next build'",
    ]


def test_guarded_orphan_recovery_accepts_only_bounded_action_key_forms(tmp_path):
    recovery = release._guarded_orphan_recovery_script()
    source_start = recovery.index("\n", recovery.index("<<'PY'")) + 1
    source_end = recovery.index("\nPY", source_start)
    ps = tmp_path / "ps.cmd"
    ps.write_text(
        "101 1 bash release.py " + release.ORPHAN_ACTION_KEY + "\n"
        "102 1 bash -c 'release.py " + release.ORPHAN_ACTION_KEY + "'\n"
        "103 1 bash -c 'echo " + release.ORPHAN_ACTION_KEY + "suffix'\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [PYTHON, "-c", recovery[source_start:source_end], "999", str(ps)],
        env={**os.environ, "CITESPAN_ORPHAN_ACTION_KEY": release.ORPHAN_ACTION_KEY},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "pid=101 ppid=1 argv=bash release.py " + release.ORPHAN_ACTION_KEY,
        "pid=102 ppid=1 argv=bash -c 'release.py " + release.ORPHAN_ACTION_KEY + "'",
    ]


def test_guarded_orphan_recovery_fails_closed_on_process_query_parse_ambiguity(tmp_path):
    recovery = release._guarded_orphan_recovery_script()
    source_start = recovery.index("\n", recovery.index("<<'PY'")) + 1
    source_end = recovery.index("\nPY", source_start)
    ps = tmp_path / "ps.cmd"
    ps.write_text('101 1 "unterminated\n', encoding="utf-8")

    result = subprocess.run(
        [PYTHON, "-c", recovery[source_start:source_end], "999", str(ps)],
        env={**os.environ, "CITESPAN_ORPHAN_ACTION_KEY": release.ORPHAN_ACTION_KEY},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 70
    assert "ambiguous-process-argv" in result.stdout


def test_guarded_orphan_recovery_fails_closed_on_unparseable_shell_command(tmp_path):
    recovery = release._guarded_orphan_recovery_script()
    source_start = recovery.index("\n", recovery.index("<<'PY'")) + 1
    source_end = recovery.index("\nPY", source_start)
    ps = tmp_path / "ps.cmd"
    ps.write_text('101 1 bash -c "\'unterminated"\n', encoding="utf-8")

    result = subprocess.run(
        [PYTHON, "-c", recovery[source_start:source_end], "999", str(ps)],
        env={**os.environ, "CITESPAN_ORPHAN_ACTION_KEY": release.ORPHAN_ACTION_KEY},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 70
    assert "ambiguous-shell-command" in result.stdout


def test_guarded_orphan_recovery_initializes_private_inputs_before_diagnostics():
    recovery = release._guarded_orphan_recovery_script()
    command = release._deployment_command(valid_payload())

    assert release.ORPHAN_BACKUP_DIR in command
    assert 'set -a; . "$runtime"; set +a;' in command
    assert command.index('set -a; . "$runtime"; set +a;') < command.index(
        "guarded_orphan_recovery"
    )
    assert recovery.index(
        f"recovery_receipt={release.DEPLOY_PATH}/.citespan-authoritative-receipt.json"
    ) < recovery.index(
        "ps -eo pid=,ppid=,args="
    )
    assert 'test -f "$recovery_receipt" && test -f "$runtime_file"' in recovery


def test_generated_authoritative_container_format_reports_observed_network_identity(bash_tmp_path):
    recovery = release._guarded_orphan_recovery_script()
    format_function = next(
        line for line in recovery.splitlines() if line.startswith("    inspect_authoritative_container()")
    )
    expected_format = (
        "{{.Id}}\t{{.Name}}\t{{.State.Status}}\t{{.Config.Image}}\t"
        "{{range $network, $_ := .NetworkSettings.Networks}}{{$network}},{{end}}\t"
        "{{range .Mounts}}{{.Type}}:{{.Name}}:{{.Destination}}:{{.RW}},{{end}}"
    )
    script = f'''#!/usr/bin/env bash
set -Eeuo pipefail
docker() {{
    test "$1" = inspect
    test "$2" = --format
    test "$3" = "$EXPECTED_FORMAT"
    printf '%s\\n' "container-id\\tcitespan-authoritative-postgres\\trunning\\tpostgres:17-alpine\\t$FIXTURE_NETWORK,\\tvolume:citespan-postgres-data:/var/lib/postgresql/data:true,"
}}
{format_function}
inspect_authoritative_container citespan-authoritative-postgres
'''
    script_path = bash_tmp_path / "network-format.sh"
    script_path.write_text(script, encoding="utf-8")

    result = subprocess.run(
        [str(_git_bash_executable()), _bash_path(script_path)],
        capture_output=True,
        text=True,
        timeout=20,
        env={**os.environ, "EXPECTED_FORMAT": expected_format, "FIXTURE_NETWORK": "citespan-authoritative-network"},
    )

    assert result.returncode == 0, result.stderr
    assert "citespan-authoritative-network" in result.stdout
    expected_format = (
        "docker inspect --format '{{.Id}}\t{{.Name}}\t{{.State.Status}}\t"
        "{{.Config.Image}}\t{{range $network, $_ := .NetworkSettings.Networks}}"
        "{{$network}},{{end}}\t{{range .Mounts}}"
        "{{.Type}}:{{.Name}}:{{.Destination}}:{{.RW}},{{end}}'"
    )
    assert expected_format in release._guarded_orphan_recovery_script()


def test_demo_audit_preserves_multiple_users_and_product_rows_after_clean_flow(tmp_path):
    db_path = tmp_path / "redeploy-after-clean-flow.sqlite"
    setup = "from sqlmodel import SQLModel; from database import engine; import db_setup; SQLModel.metadata.create_all(engine)"
    assert _run_isolated_backend_script(db_path, setup).returncode == 0
    assert _run_isolated_backend_script(db_path, release._demo_seed_script()).returncode == 0
    add_clean_flow_state = f"""
import datetime, json, uuid
from sqlmodel import Session, select
from database import engine
from db_setup import AuditEvent, CaseMembership, Message, Query, Result, Rule, Run, User
with Session(engine) as session:
    run = session.get(Run, uuid.UUID('{release.CANONICAL_DEMO_RUN_ID}'))
    owner = session.get(User, run.user_id)
    message = session.exec(select(Message).where(Message.run_id == run.id)).first()
    user = User(username='Clean session user', email='clean@example.invalid', password_hash='disabled')
    session.add(user); session.commit(); session.refresh(user)
    session.add(CaseMembership(run_id=run.id, user_id=user.id, role='viewer', granted_by=owner.id))
    rule = Rule(user_id=user.id, title='User query', description='Synthetic query', query_text='Show transfers')
    session.add(rule); session.commit(); session.refresh(rule)
    session.add_all([
        Query(run_id=run.id, user_id=user.id, query_text='Show transfers', status='completed', result_count=1),
        Result(run_id=run.id, rule_id=rule.id, result_type='message', evidence_data=json.dumps({{"source": "synthetic", "evidence_spans": [{{"source_id": str(message.id), "start": 0, "end": 8}}]}})),
        AuditEvent(seq=1, event_type='query', run_id=run.id, user_id=user.id, timestamp=datetime.datetime.utcnow(), payload='{{"action": "query", "result_count": 1}}'),
    ])
    session.commit()
"""
    added = _run_isolated_backend_script(db_path, add_clean_flow_state)
    assert added.returncode == 0, added.stderr
    audited = _run_isolated_backend_script(db_path, release._demo_audit_script())
    assert audited.returncode == 0, audited.stderr


@pytest.mark.parametrize(
    "row_expression",
    [
        "Result(run_id=run.id, rule_id=rule.id, result_type='message', evidence_data='{\\\"unknown\\\": \\\"value\\\"}')",
        "AuditEvent(seq=2, event_type='unknown_action', run_id=run.id, user_id=owner.id, payload='{\\\"action\\\": \\\"unknown_action\\\"}')",
    ],
)
def test_demo_audit_rejects_unknown_product_state_schema(tmp_path, row_expression):
    db_path = tmp_path / "unknown-product-state.sqlite"
    setup = "from sqlmodel import SQLModel; from database import engine; import db_setup; SQLModel.metadata.create_all(engine)"
    assert _run_isolated_backend_script(db_path, setup).returncode == 0
    assert _run_isolated_backend_script(db_path, release._demo_seed_script()).returncode == 0
    add_row = f"""
import uuid
from sqlmodel import Session, select
from database import engine
from db_setup import *
with Session(engine) as session:
    run = session.get(Run, uuid.UUID('{release.CANONICAL_DEMO_RUN_ID}'))
    owner = session.exec(select(User)).first()
    rule = Rule(user_id=owner.id, title='Transfer query', description='Synthetic query', query_text='Show transfers')
    session.add(rule); session.commit(); session.refresh(rule)
    session.add({row_expression})
    session.commit()
"""
    added = _run_isolated_backend_script(db_path, "from sqlmodel import select\n" + add_row)
    assert added.returncode == 0, added.stderr
    audited = _run_isolated_backend_script(db_path, release._demo_audit_script())
    assert audited.returncode != 0
    assert "unverified" in audited.stdout + audited.stderr


def test_demo_audit_rejects_backup_snapshot_reference(tmp_path):
    db_path = tmp_path / "audit.sqlite"
    setup = "from sqlmodel import SQLModel; from database import engine; import db_setup; SQLModel.metadata.create_all(engine)"
    assert _run_isolated_backend_script(db_path, setup).returncode == 0
    assert _run_isolated_backend_script(db_path, release._demo_seed_script()).returncode == 0
    add_snapshot = f"""
from sqlmodel import Session
from database import engine
from db_setup import Backup, User
with Session(engine) as session:
    owner = session.exec(select(User)).first()
    session.add(Backup(user_id=owner.id, event_type='database_snapshot', description='snapshot', snapshot_path='/backups/sample.db'))
    session.commit()
"""
    added = _run_isolated_backend_script(db_path, "from sqlmodel import select\n" + add_snapshot)
    assert added.returncode == 0, added.stderr
    audited = _run_isolated_backend_script(db_path, release._demo_audit_script())
    assert audited.returncode != 0
    assert "Backup snapshot" in audited.stderr or "Backup snapshot" in audited.stdout


def test_static_cutover_records_observed_candidate_identity_and_immutable_content():
    command = release._deployment_command(valid_payload())
    observation = release._observation_command()

    assert "static_container" in command
    assert "static_content_dir" in command
    assert "cp -a" in command
    assert "frontend/out" in command
    assert "static_container" in observation
    assert "docker ps -q --filter name=^/$deployment_id-static$" not in observation


def test_metadata_identity_is_used_for_repeat_execution_and_rollback():
    command = release._deployment_command(valid_payload())

    assert "previous_static=$(python3" in command
    assert 'docker start "$previous_static"' in command
    assert 'for prior_container in "$previous_backend" "$previous_static"' in command
    assert 'docker stop "$prior_container"' in command
    assert 'docker rm "$prior_container"' in command
    assert 'docker rm -f' not in command


def test_repeat_execution_accepts_only_trusted_existing_forensic_target():
    command = release._deployment_command(valid_payload())

    assert 'elif [ "$demo_state" = EXISTING ]; then' in command
    assert 'test -f "$receipt"' in command
    assert "candidate demo target is not empty" in command
    assert command.index("demo_state=") < command.index(
        'elif [ "$demo_state" = EXISTING ]; then'
    )


def test_metadata_writer_and_observer_use_one_canonical_marker_value():
    command = release._deployment_command(valid_payload())
    observation = release._observation_command()

    assert f'"marker":"{release.CANONICAL_DEMO_MARKER}"' in command
    assert f'"marker":"{release.DEMO_MARKER}"' not in command


def test_metadata_writer_uses_verified_deployment_commit():
    command = release._deployment_command(valid_payload())
    observation = release._observation_command()

    assert 'verified_commit=$(git -C /opt/citespan rev-parse HEAD)' in command
    assert 'test "$verified_commit" = ' in command
    assert '"$verified_commit"' in command
    assert '$(git -C {DEPLOY_PATH} rev-parse HEAD)' not in command
    assert f'get("marker") == "{release.CANONICAL_DEMO_MARKER}"' in command
    assert release.CANONICAL_DEMO_MARKER in observation


def test_receipt_writer_and_validator_accept_only_matching_runtime_identity(tmp_path):
    receipt = tmp_path / "receipt.json"
    runtime = tmp_path / "runtime.env"
    runtime.write_text("synthetic-runtime\n", encoding="utf-8")
    values = [
        str(receipt),
        str(runtime),
        release.CANONICAL_DEMO_MARKER,
        "citespan-authoritative-network",
        "citespan-authoritative-postgres",
        "citespan-authoritative-meili",
        "citespan-authoritative-minio",
    ]
    written = subprocess.run(
        [PYTHON, "-c", release._receipt_writer(), *values],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert written.returncode == 0, written.stderr

    validated = subprocess.run(
        [PYTHON, "-c", release._receipt_validate(), *values],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert validated.returncode == 0, validated.stderr

    runtime.write_text("changed-runtime\n", encoding="utf-8")
    mismatched_runtime = subprocess.run(
        [PYTHON, "-c", release._receipt_validate(), *values],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert mismatched_runtime.returncode != 0

    runtime.write_text("synthetic-runtime\n", encoding="utf-8")
    mismatched_marker = subprocess.run(
        [PYTHON, "-c", release._receipt_validate(), *[values[0], values[1], "wrong-marker", *values[3:]]],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert mismatched_marker.returncode != 0

    mismatched_resource = subprocess.run(
        [PYTHON, "-c", release._receipt_validate(), *[values[0], values[1], *values[2:5], "wrong-meili", values[6]]],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert mismatched_resource.returncode != 0


def test_rollback_keeps_previous_static_output_until_metadata_cutover_succeeds():
    command = release._deployment_command(valid_payload())

    remove_previous = command.index('docker rm "$prior_container"')
    metadata_write = command.index('citespan-deployment.json')
    assert metadata_write < remove_previous


@pytest.mark.parametrize(
    "contamination",
    ["Call", "Media", "Transcript", "AleappReport", "Result", "extra Message", "extra AleappArtifact"],
)
def test_demo_audit_rejects_every_forbidden_or_extra_canonical_row(contamination):
    audit = release._demo_audit_script()

    assert contamination.split()[0] in audit
    assert "count" in audit
    assert "exact canonical" in audit


def _run_isolated_backend_script(db_path: Path, script: str, **extra_env) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "DATABASE_URL": f"sqlite:///{db_path.as_posix()}",
            "PYTHONPATH": str(ROOT / "backend"),
            "GRAPH_BACKEND": "postgres",
            "CITESPAN_DEMO_RUN_ID": release.CANONICAL_DEMO_RUN_ID,
            "CITESPAN_DEMO_OWNER_EMAIL": release.CANONICAL_DEMO_OWNER_EMAIL,
            "CITESPAN_SYNTHETIC_MARKER": release.CANONICAL_DEMO_MARKER,
        }
    )
    env.update(extra_env)
    return subprocess.run([PYTHON, "-c", script], cwd=ROOT, env=env, capture_output=True, text=True)


def _isolated_forensic_snapshot(db_path: Path) -> dict:
    snapshot_script = """
import json
from sqlmodel import Session, select
from database import engine
from db_setup import AleappArtifact, AleappReport, Call, Contact, EntityIndex, Media, Message, Transcript
with Session(engine) as session:
    rows = {}
    for model in (Message, Call, Contact, Media, Transcript, EntityIndex, AleappArtifact, AleappReport):
        rows[model.__name__] = [
            {key: str(value) for key, value in row.__dict__.items() if not key.startswith('_')}
            for row in sorted(session.exec(select(model)).all(), key=lambda item: str(item.id))
        ]
    print(json.dumps(rows, sort_keys=True))
"""
    result = _run_isolated_backend_script(db_path, snapshot_script)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_demo_audit_executes_against_isolated_sqlite_and_preserves_legitimate_state(tmp_path):
    db_path = tmp_path / "audit.sqlite"
    setup = "from sqlmodel import SQLModel; from database import engine; import db_setup; SQLModel.metadata.create_all(engine)"
    result = _run_isolated_backend_script(db_path, setup)
    assert result.returncode == 0, result.stderr

    seed = _run_isolated_backend_script(db_path, release._demo_seed_script())
    assert seed.returncode == 0, seed.stderr
    legit = """
import datetime, uuid
from sqlmodel import Session
from database import engine
from db_setup import AuditEvent, CaseMembership, Query, Result, Rule, Run, User
with Session(engine) as session:
    run = session.get(Run, uuid.UUID('11111111-1111-4111-8111-111111111111'))
    owner = session.get(User, run.user_id)
    session.add(CaseMembership(run_id=run.id, user_id=owner.id, role='owner', granted_by=owner.id))
    rule = Rule(user_id=owner.id, title='Transfer query', description='Synthetic query', query_text='Show transfers')
    session.add(rule); session.commit(); session.refresh(rule)
    session.add(Query(run_id=run.id, user_id=owner.id, query_text='Show transfers', status='completed', result_count=1))
    session.add(Result(run_id=run.id, rule_id=rule.id, result_type='message', evidence_data='{"source": "synthetic"}'))
    session.add(AuditEvent(seq=1, event_type='query', run_id=run.id, user_id=owner.id, timestamp=datetime.datetime.utcnow(), payload='{}'))
    session.commit()
"""
    legit_result = _run_isolated_backend_script(db_path, legit)
    assert legit_result.returncode == 0, legit_result.stderr
    audited = _run_isolated_backend_script(db_path, release._demo_audit_script())
    assert audited.returncode == 0, audited.stderr


@pytest.mark.parametrize(
    "contamination_script",
    [
        "session.add(Message(run_id=run.id, sender='x', receiver='y', timestamp=datetime.datetime.utcnow(), content='extra'));",
        "session.add(Call(run_id=run.id, caller='x', receiver='y', timestamp=datetime.datetime.utcnow()));",
        "session.add(Contact(run_id=run.id, name='extra', number='x'));",
        "session.add(Media(run_id=run.id, original_path='/extra', storage_path='/extra'));",
        "session.add(AleappReport(run_id=run.id, report_type='html', filename='extra', file_path='/extra'));",
        "session.add(EntityIndex(run_id=run.id, identifier_hash='extra', identifier_type='phone'));",
        "session.add(Transcript(run_id=run.id, media_id=uuid.uuid4(), model='test', text='extra', transcript_hash='hash'));",
    ],
)
def test_demo_audit_rejects_forensic_rows_without_mutating_them(tmp_path, contamination_script):
    db_path = tmp_path / "audit.sqlite"
    _run_isolated_backend_script(
        db_path,
        "from sqlmodel import SQLModel; from database import engine; import db_setup; SQLModel.metadata.create_all(engine)",
    )
    assert _run_isolated_backend_script(db_path, release._demo_seed_script()).returncode == 0
    add_row = f"""
import datetime, uuid
from sqlmodel import Session
from database import engine
from db_setup import *
with Session(engine) as session:
    run = session.get(Run, uuid.UUID('{release.CANONICAL_DEMO_RUN_ID}'))
    owner = session.exec(select(User)).first()
    {contamination_script}
    session.commit()
"""
    added = _run_isolated_backend_script(db_path, "from sqlmodel import select\n" + add_row)
    assert added.returncode == 0, added.stderr
    before = _isolated_forensic_snapshot(db_path)
    audited = _run_isolated_backend_script(db_path, release._demo_audit_script())
    assert audited.returncode != 0
    assert _isolated_forensic_snapshot(db_path) == before


def test_demo_seed_marks_exact_canonical_synthetic_contents():
    seed = release._demo_seed_script()

    assert "CITESPAN_SYNTHETIC_MARKER" in seed
    assert '"sample_id": "canonical-v1"' in seed
    assert "candidate demo volume already contains the canonical run" in seed
    assert "non-canonical run" not in seed


def test_generated_release_initializes_and_updates_protected_receipt_incrementally():
    command = release._deployment_command(valid_payload())

    assert "CITESPAN_SYNTHETIC_MARKER" in command
    assert command.index(f"receipt={release.DEPLOY_PATH}/.citespan-authoritative-receipt.json") < command.index(
        "authoritative receipt does not own existing network"
    )
    assert "runtime env contains a missing or duplicate key" in command
    assert "runtime env has mismatched MinIO credentials" in command
    assert "resources" in command
    assert "network created" in command
    assert "postgres ready" in command
    assert "meili ready" in command
    assert "minio ready" in command
    assert "{receipt_writer}" not in command
    assert command.count("python3 -c") >= 10
    for name in (
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "NEO4J_PASSWORD",
        "POSTGRES_PASSWORD",
        "MEILI_MASTER_KEY",
        "MINIO_ROOT_USER",
        "MINIO_ROOT_PASSWORD",
        "MINIO_ACCESS_KEY",
        "MINIO_SECRET_KEY",
        "SECRET_KEY",
    ):
        assert name in command
    assert "/minio/health/ready" in command
    assert "NetworkSettings.Networks" in command
    assert "command -v curl" in command
    assert "os.replace(temporary, path)" in command
    assert 'docker inspect -f' in command


def test_receipt_transitions_are_written_and_validated_incrementally(tmp_path):
    receipt = tmp_path / "receipt.json"
    runtime = tmp_path / "runtime.env"
    runtime.write_text("synthetic-runtime\n", encoding="utf-8")
    values = [
        str(receipt),
        str(runtime),
        release.CANONICAL_DEMO_MARKER,
        "citespan-authoritative-network",
        "citespan-authoritative-postgres",
        "citespan-authoritative-meili",
        "citespan-authoritative-minio",
    ]

    def write_and_read(expect_valid, *transition):
        result = subprocess.run(
            [PYTHON, "-c", release._receipt_writer(), *values, *transition],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        data = json.loads(receipt.read_text(encoding="utf-8"))
        checked = subprocess.run(
            [PYTHON, "-c", release._receipt_validate(), *values],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        assert (checked.returncode == 0) is expect_valid, checked.stderr
        return data

    initial = write_and_read(True)
    assert initial["resources"] == {
        name: {"created": False, "ready": False}
        for name in ("network", "postgres", "meili", "minio")
    }
    expected = initial["resources"]
    for resource, state in (("network", "created"), ("postgres", "created"), ("postgres", "ready"), ("meili", "created"), ("meili", "ready"), ("minio", "created"), ("minio", "ready")):
        data = write_and_read(True, resource, state)
        expected[resource][state] = True
        assert data["resources"] == expected

    valid = subprocess.run([PYTHON, "-c", release._receipt_validate(), *values], cwd=ROOT, capture_output=True, text=True)
    assert valid.returncode == 0, valid.stderr
    invalid_values = [str(tmp_path / "invalid-receipt.json"), *values[1:]]
    invalid_transition = subprocess.run(
        [PYTHON, "-c", release._receipt_writer(), *invalid_values, "network", "ready"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert invalid_transition.returncode == 0
    assert subprocess.run(
        [PYTHON, "-c", release._receipt_validate(), *invalid_values],
        cwd=ROOT,
        capture_output=True,
        text=True,
    ).returncode != 0


def test_seeded_existing_target_requires_receipt_backed_canonical_audit_before_resume():
    command = release._deployment_command(valid_payload())

    assert 'elif [ "$demo_state" = EXISTING ]; then' in command
    assert 'test -f "$receipt"' in command
    assert "candidate demo target is not empty" in command
    assert command.index("demo_state=") < command.index("candidate demo target is not empty")
    assert "CITESPAN_SYNTHETIC_MARKER" in command
    assert "docker exec \"$backend_id\" sh -c 'echo " in command


def test_observation_reads_external_metadata_and_requires_synthetic_marker():
    command = release._observation_command()

    assert "citespan-deployment.json" in command
    assert "citespan-demo-marker.json" in command
    assert "synthetic_only" in command
    assert release.CANONICAL_DEMO_MARKER in command
    assert release.CANONICAL_DEMO_RUN_ID in command
    assert "BEGIN CITESPAN ROUTE" in command
    assert "DEPLOY_DOMAIN" not in command


def test_prepare_reports_unscoped_rendered_ai_claims():
    with patch.object(release, "_history_credential_findings", return_value=[]), patch.object(
        release, "_critical_dependency_findings", return_value=[]
    ), patch.object(
        release,
        "_branding_findings",
        return_value=[
            "unscoped public AI claim requires scope expansion: frontend/components/dashboard/data.ts"
        ],
    ):
        result = release._prepare(valid_payload())

    assert result["release_ready"] is False
    assert result["branding_findings"]


@pytest.mark.parametrize(
    "claim",
    [
        "An LLM turns the user question into a query plan.",
        "The large language model generates the hosted query plan.",
        "Generative AI powers the hosted demo planner.",
        "The AI planner is active in the hosted release.",
        "The deterministic planner uses an LLM in the hosted release.",
    ],
)
def test_current_public_documentation_rejects_active_hosted_ai_claims(claim):
    findings = release._hosted_demo_documentation_findings("README.md", claim)

    assert findings == ["active hosted AI claim in current documentation: README.md:1"]


def test_current_public_documentation_accepts_deterministic_hosted_limitations():
    text = (
        "The hosted demo uses a deterministic demo planner. "
        "External LLM behavior is disabled and unavailable in the hosted release."
    )

    assert release._hosted_demo_documentation_findings("README.md", text) == []


def test_current_public_documentation_accepts_deploy_demo_limits():
    text = (
        "The planner is deterministic demo behavior. "
        "It is not a live large language model feature."
    )

    assert release._hosted_demo_documentation_findings("DEPLOY.md", text) == []


@pytest.mark.parametrize(
    "sentence",
    [
        "It is not a live large language model feature.",
        "A live large language model claim is not valid.",
        "External or live LLM behavior is not enabled.",
        "The hosted planner uses deterministic demo behavior and external LLM behavior is unavailable.",
    ],
)
def test_documentation_limitations_have_same_result_when_markdown_wraps(sentence):
    wrapped = sentence.replace(" ", "\n", 2)

    assert release._hosted_demo_documentation_findings("README.md", sentence) == []
    assert release._hosted_demo_documentation_findings("README.md", wrapped) == []


@pytest.mark.parametrize(
    "claim",
    [
        "An LLM turns the user question into a query plan.",
        "An LLM powers the current hosted query.",
        "The AI-powered planner is active in the hosted release.",
    ],
)
def test_active_documentation_claims_have_same_finding_when_markdown_wraps(claim):
    wrapped = claim.replace(" ", "\n", 2)

    unwrapped = release._hosted_demo_documentation_findings("README.md", claim)
    wrapped_findings = release._hosted_demo_documentation_findings("README.md", wrapped)

    assert unwrapped == ["active hosted AI claim in current documentation: README.md:1"]
    assert wrapped_findings == unwrapped


def test_documentation_scans_each_sentence_when_limitation_and_active_claim_conflict():
    text = "LLM behavior is disabled. An LLM powers the current hosted query."

    assert release._hosted_demo_documentation_findings("README.md", text) == [
        "active hosted AI claim in current documentation: README.md:1"
    ]


def test_documentation_does_not_allow_a_limitation_word_to_hide_an_active_claim():
    text = "LLM behavior is disabled but an LLM powers the current hosted query."

    assert release._hosted_demo_documentation_findings("README.md", text) == [
        "active hosted AI claim in current documentation: README.md:1"
    ]


def test_documentation_ignores_unrelated_paragraphs_when_classifying_claims():
    text = "A neutral product description.\n\nThe hosted demo uses a deterministic planner."

    assert release._hosted_demo_documentation_findings("README.md", text) == []


def test_documentation_normalizes_wrapped_list_items_without_merging_items():
    text = "- The hosted planner is deterministic demo behavior and external LLM\n  behavior is unavailable.\n- An LLM powers the current hosted query."

    assert release._hosted_demo_documentation_findings("README.md", text) == [
        "active hosted AI claim in current documentation: README.md:3"
    ]


def test_archived_review_transcript_text_is_excluded_from_hosted_ai_scan():
    text = "An LLM turns the investigator question into a query plan."

    assert release._hosted_demo_documentation_findings("codex/phase-a.md", text) == []


def test_current_approved_public_documentation_has_no_active_hosted_ai_claims():
    findings = []
    for name, text in release._tracked_text():
        findings.extend(release._hosted_demo_documentation_findings(name, text))

    assert findings == []


def test_branding_scan_checks_report_service_legacy_title():
    with patch.object(
        release,
        "_tracked_text",
        return_value=[
            (
                "backend/ingest/services/report_service.py",
                'c.drawString(50, height - 50, "UFDR Report")',
            )
        ],
    ):
        findings = release._branding_findings()

    assert findings == ["old public product name remains in backend/ingest/services/report_service.py"]


def test_branding_scan_allows_ufdr_file_format_reference():
    with patch.object(
        release,
        "_tracked_text",
        return_value=[
            (
                "backend/ingest/services/report_service.py",
                'c.drawString(50, y, "UFDR File: demo_synthetic.ufdr")',
            )
        ],
    ):
        findings = release._branding_findings()

    assert findings == []


def test_branding_scan_rejects_old_names_on_current_backend_and_release_surfaces():
    with patch.object(
        release,
        "_tracked_text",
        return_value=[
            ("backend/server.py", '"UFDR Analyzer is starting"'),
            ("fly.toml", 'description = "UFDR Analyzer demo"'),
            (
                "frontend/electron-builder.json",
                '{"appId": "com.ufdr-analyzer.app", "productName": "UFDR Analyzer"}',
            ),
        ],
    ):
        findings = release._branding_findings()

    assert findings == [
        "old public product name remains in backend/server.py",
        "old public product name remains in fly.toml",
        "frontend/electron-builder.json productName must equal CiteSpan",
    ]


@pytest.mark.parametrize(
    "electron_config",
    [
        '{"appId": "com.ufdr-analyzer.app", "productName": "CiteSpan"}',
        '{\n  "productName": "CiteSpan",\n  "appId": "com.ufdr-analyzer.app"\n}',
    ],
)
def test_branding_scan_accepts_valid_electron_config_formats(electron_config):
    with patch.object(
        release,
        "_tracked_text",
        return_value=[
            ("frontend/electron-builder.json", electron_config),
            (
                "fly.toml",
                'app = "ufdr-analyzer-api"\nCORS_ALLOWED_ORIGINS = "https://ufdr-analyzer.vercel.app"',
            ),
            (
                "backend/server.py",
                "CiteSpan startup script for UFDR forensic-format data",
            ),
        ],
    ):
        findings = release._branding_findings()

    assert findings == []


@pytest.mark.parametrize(
    ("electron_config", "expected"),
    [
        (
            '{"appId": "com.ufdr-analyzer.app", "productName": "CiteSpan"',
            "frontend/electron-builder.json is malformed JSON",
        ),
        (
            '{"appId": "com.ufdr-analyzer.app"}',
            "frontend/electron-builder.json is missing productName",
        ),
        (
            '{"appId": "com.ufdr-analyzer.app", "productName": "UFDR Analyzer"}',
            "frontend/electron-builder.json productName must equal CiteSpan",
        ),
        (
            '{"productName": "CiteSpan"}',
            "frontend/electron-builder.json is missing appId",
        ),
        (
            '{"appId": "com.ufdr-analyzer.app.extra", "productName": "CiteSpan"}',
            "frontend/electron-builder.json appId must equal com.ufdr-analyzer.app",
        ),
    ],
)
def test_branding_scan_validates_electron_config_semantically(electron_config, expected):
    with patch.object(
        release,
        "_tracked_text",
        return_value=[("frontend/electron-builder.json", electron_config)],
    ):
        findings = release._branding_findings()

    assert findings == [expected]


def test_branding_scan_allows_stable_app_id_references_outside_config():
    with patch.object(
        release,
        "_tracked_text",
        return_value=[("frontend/app/page.tsx", 'const appId = "com.ufdr-analyzer.app";')],
    ):
        findings = release._branding_findings()

    assert findings == []


def test_branding_scan_rejects_unreviewed_legacy_identifier_context():
    with patch.object(
        release,
        "_tracked_text",
        return_value=[
            ("fly.toml", 'description = "ufdr-analyzer-api public product"'),
        ],
    ):
        findings = release._branding_findings()

    assert findings == ["old public product name remains in fly.toml"]


@pytest.mark.parametrize("old_name", ["ForensicAI", "forensicai", "ForensicAi"])
def test_branding_scan_rejects_old_brand_case_insensitively(old_name):
    with patch.object(
        release,
        "_tracked_text",
        return_value=[("frontend/app/page.tsx", f"<title>{old_name}</title>")],
    ):
        findings = release._branding_findings()

    assert findings == ["old public product name remains in frontend/app/page.tsx"]


@pytest.mark.parametrize("old_name", ["UFDR Analyzer", "ufdr analyzer", "Ufdr Analyzer"])
def test_branding_scan_rejects_ufdr_analyzer_case_insensitively(old_name):
    with patch.object(
        release,
        "_tracked_text",
        return_value=[("frontend/app/page.tsx", f"<title>{old_name}</title>")],
    ):
        findings = release._branding_findings()

    assert findings == ["old public product name remains in frontend/app/page.tsx"]


@pytest.mark.parametrize("name", ["codex/phase-a.md", "codex/phase-bde.md", "codex/v4-merge-gate.txt"])
def test_branding_scan_ignores_archived_review_transcript(name):
    with patch.object(
        release,
        "_tracked_text",
        return_value=[(name, "UFDR Analyzer — Evidence Report")],
    ):
        findings = release._branding_findings()

    assert findings == []


@pytest.mark.parametrize("name", ["codex/phase-a.md", "codex/phase-bde.md", "codex/v4-merge-gate.txt"])
def test_archived_review_transcripts_are_byte_identical_to_approved_git_blobs(name):
    expected = subprocess.check_output(["git", "show", f"HEAD:{name}"])
    assert (release.ROOT / name).read_bytes() == expected


def test_branding_scan_ignores_unlisted_codex_documentation():
    with patch.object(
        release,
        "_tracked_text",
        return_value=[("codex/new-product-doc.md", "UFDR Analyzer")],
    ):
        findings = release._branding_findings()

    assert findings == []


def test_corrected_product_documentation_passes_branding_scan():
    names = ["codex/phase-a.md", "codex/phase-bde.md", "codex/v4-merge-gate.txt"]
    with patch.object(
        release,
        "_tracked_text",
        return_value=[
            (name, (release.ROOT / name).read_text(encoding="utf-8")) for name in names
        ],
    ):
        findings = release._branding_findings()

    assert findings == []


def test_actual_approved_current_branding_surfaces_pass_branding_scan():
    assert release._branding_findings() == []


def test_branding_scan_allows_ufdr_format_and_repository_identity_in_product_documentation():
    with patch.object(
        release,
        "_tracked_text",
        return_value=[
            (
                "codex/phase-a.md",
                "CiteSpan reads UFDR file-format data from aayushman-singh/ufdr-analyzer.",
            )
        ],
    ):
        findings = release._branding_findings()

    assert findings == []


def test_branding_scan_allows_lowercase_ufdr_report_file_format_reference():
    with patch.object(
        release,
        "_tracked_text",
        return_value=[("codex/v4-merge-gate.txt", "an ingested UFDR report")],
    ):
        findings = release._branding_findings()

    assert findings == []


def test_branding_scan_allows_legitimate_lowercase_ufdr_report_terminology_on_current_surface():
    with patch.object(
        release,
        "_tracked_text",
        return_value=[("backend/ingest/services/report_service.py", "an ingested UFDR report")],
    ):
        findings = release._branding_findings()

    assert findings == []


def test_history_scan_returns_only_compromised_credential_fingerprints():
    secret = "sk-or-v1-" + ("1" * 30)
    completed = subprocess.CompletedProcess(
        ["git"], 0, f"OPENROUTER_API_KEY={secret}\n".encode(), b""
    )
    with patch.object(release.subprocess, "run", return_value=completed):
        findings = release._history_credential_findings()

    assert findings == ["OpenRouter credential in git history"]
    assert secret not in json.dumps(findings)


def test_history_secret_hashes_use_named_value_groups_for_each_provider():
    history = (
        "OPENROUTER_API_KEY=" + "sk-or-v1-" + ("1" * 30) + "\n"
        "OPENAI_API_KEY=" + "openai-" + ("1" * 24) + "\n"
        "NEO4J_" + "PASSWORD=neo4j-secret-1234\n"
    ).encode()
    completed = subprocess.CompletedProcess(["git"], 0, history, b"")
    with patch.object(release.subprocess, "run", return_value=completed):
        findings = release._history_credential_findings()
        hashes = release._history_secret_hashes()

    assert findings == [
        "OpenRouter credential in git history",
        "OpenAI credential in git history",
        "Neo4j credential in git history",
    ]
    assert len(hashes) == 3
    assert all(len(value) == 64 for value in hashes)


def _run_runtime_validation(tmp_path, text, history_hashes=()):
    runtime = tmp_path / ".citespan-runtime.env"
    runtime.write_bytes(text.encode("utf-8"))
    runtime.chmod(0o600)
    return subprocess.run(
        [PYTHON, "-c", release._runtime_validation_script(list(history_hashes)), str(runtime)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    ), runtime


def test_remote_runtime_validation_accepts_complete_protected_runtime(tmp_path):
    result, runtime = _run_runtime_validation(tmp_path, _complete_runtime_fixture())

    assert result.returncode == 0, result.stderr
    assert runtime.read_text(encoding="utf-8") == _complete_runtime_fixture()


@pytest.mark.parametrize(
    "placeholder",
    [
        _fixture_text(67, 72, 65, 78, 71, 69, 95, 77, 69),
        _fixture_text(99, 104, 97, 110, 103, 101, 109, 101),
        _fixture_text(99, 104, 97, 110, 103, 101, 45, 109, 101),
        _fixture_text(82, 69, 80, 76, 65, 67, 69, 95, 87, 73, 84, 72),
        _fixture_text(114, 101, 112, 108, 97, 99, 101, 45, 109, 101),
        _fixture_text(89, 79, 85, 82, 95, 75, 69, 89, 95, 72, 69, 82, 69),
        _fixture_text(89, 79, 85, 82, 95, 83, 69, 67, 82, 69, 84, 95, 75, 69, 89, 95, 72, 69, 82, 69),
        _fixture_text(121, 111, 117, 114, 95, 118, 101, 114, 121, 95, 115, 101, 99, 117, 114, 101, 95, 115, 101, 99, 114, 101, 116, 95, 107, 101, 121, 95, 104, 101, 114, 101),
        _fixture_text(121, 111, 117, 114, 45, 115, 101, 99, 114, 101, 116, 45, 104, 101, 114, 101),
        _fixture_text(80, 76, 65, 67, 69, 72, 79, 76, 68, 69, 82),
        _fixture_text(60, 89, 79, 85, 82, 95, 83, 69, 67, 82, 69, 84, 62),
        _fixture_text(36, 123, 83, 69, 67, 82, 69, 84, 95, 75, 69, 89, 125),
        _fixture_text(123, 123, 83, 69, 67, 82, 69, 84, 95, 75, 69, 89, 125, 125),
    ],
)
def test_remote_runtime_validation_rejects_structured_placeholders_without_leaking_values(
    tmp_path, placeholder
):
    runtime_text = _complete_runtime_fixture().replace(
        _neo4j_password_assignment("synthetic-neo4j-password"),
        _neo4j_password_assignment(placeholder),
    )

    result, _ = _run_runtime_validation(tmp_path, runtime_text)

    assert result.returncode != 0
    assert "NEO4J_PASSWORD" in result.stderr
    assert placeholder not in result.stderr


def test_remote_runtime_validation_accepts_high_entropy_secret(tmp_path):
    secret = _fixture_text(
        102, 52, 99, 55, 98, 54, 97, 57, 100, 49, 101, 50, 102, 56, 99, 48, 98, 53,
        97, 55, 100, 51, 101, 57, 102, 49, 99, 54, 97, 56, 98, 50, 100, 52, 101, 55,
        102, 48, 97, 51, 99, 53, 98, 56, 100, 49, 101, 54, 102, 57, 97, 50, 99, 52,
        101, 55, 98, 48, 100, 51, 102, 54,
    )
    runtime_text = _complete_runtime_fixture().replace(
        _neo4j_password_assignment("synthetic-neo4j-password"),
        _neo4j_password_assignment(secret),
    )

    result, _ = _run_runtime_validation(tmp_path, runtime_text)

    assert result.returncode == 0, result.stderr


def test_prepare_rejects_placeholder_runtime_secret_without_reporting_ready():
    with pytest.raises(RuntimeError, match="NEO4J_PASSWORD") as error:
        release._prepare(
            {
                **valid_payload(),
                "runtime": {
                    _neo4j_password_key(): _fixture_text(
                        67, 72, 65, 78, 71, 69, 95, 77, 69
                    )
                },
            }
        )

    assert _fixture_text(67, 72, 65, 78, 71, 69, 95, 77, 69) not in str(error.value)


@pytest.mark.parametrize(
    "runtime_payload",
    [
        {"intent": {"runtime_config": {_neo4j_password_key(): "CHANGE_ME"}}},
        {
            "intent": {
                "deployment": {
                    "target": {
                        "environment": {_neo4j_password_key(): "ChAnGe-Me"}
                    }
                }
            }
        },
        {
            "intent": {
                "deployment": {
                    "target": {
                        "environment": [_neo4j_password_assignment("{{SECRET}}")]
                    }
                }
            }
        },
        {
            "intent": {
                "runtime_config": {
                    "environment": [_neo4j_password_assignment("<ROTATE_ME>")]
                }
            }
        },
    ],
)
def test_nested_provider_runtime_placeholders_fail_without_leaking_values(runtime_payload):
    placeholder = next(
        value
        for value in ("CHANGE_ME", "ChAnGe-Me", "{{SECRET}}", "<ROTATE_ME>")
        if json.dumps(runtime_payload).find(value) >= 0
    )

    with pytest.raises(RuntimeError, match="runtime configuration") as error:
        release._check_payload_runtime_placeholders({**valid_payload(), **runtime_payload})

    assert placeholder not in str(error.value)
    assert "NEO4J_PASSWORD" in str(error.value)


@pytest.mark.parametrize("required_key", sorted(release.REQUIRED_RUNTIME_SECRET_KEYS))
@pytest.mark.parametrize("transport", ["nested", "assignment"])
def test_nested_provider_runtime_rejects_change_me_for_every_required_secret(
    required_key, transport
):
    if transport == "nested":
        runtime = {required_key: "CHANGE_ME"}
    else:
        runtime = [f"{required_key}=CHANGE_ME"]

    with pytest.raises(RuntimeError, match="runtime configuration"):
        release._check_payload_runtime_placeholders(
            {**valid_payload(), "intent": {"runtime_config": {"environment": runtime}}}
        )


@pytest.mark.parametrize("transport", ["nested", "assignment"])
def test_nested_provider_runtime_accepts_meaningful_values_for_every_required_secret(
    transport,
):
    values = {
        required_key: f"synthetic-{required_key.lower()}-value"
        for required_key in release.REQUIRED_RUNTIME_SECRET_KEYS
    }
    if transport == "nested":
        runtime = values
    else:
        runtime = [f"{key}={value}" for key, value in values.items()]

    release._check_payload_runtime_placeholders(
        {**valid_payload(), "intent": {"runtime_config": {"environment": runtime}}}
    )


def test_nested_provider_runtime_accepts_high_entropy_values_and_unrelated_placeholder_text():
    release._check_payload_runtime_placeholders(
        {
            **valid_payload(),
            "intent": {
                "deployment": {
                    "target": {
                        "environment": {
                            _neo4j_password_key(): "f4c7b6a9d1e2f8c0b5a7d3e9f1c6a8b2",
                            "description": "placeholder text is ordinary metadata",
                        }
                    }
                }
            },
        }
    )


@pytest.mark.parametrize("value", [None, 0, [], ""])
def test_nested_provider_runtime_rejects_malformed_required_secret_values(value):
    with pytest.raises(RuntimeError, match="NEO4J_PASSWORD"):
        release._check_payload_runtime_placeholders(
            {
                **valid_payload(),
                "intent": {"runtime_config": {_neo4j_password_key(): value}},
            }
        )


def test_nested_provider_runtime_cycle_is_traversed_once():
    runtime_config = {}
    runtime_config["self"] = runtime_config
    runtime_config[_neo4j_password_key()] = "synthetic-neo4j-password"

    release._check_payload_runtime_placeholders(
        {**valid_payload(), "intent": {"runtime_config": runtime_config}}
    )


def test_prepare_rejects_nested_provider_placeholder_before_release_ready():
    with pytest.raises(RuntimeError, match="runtime configuration"):
        release._prepare(
            {
                **valid_payload(),
                "intent": {
                    "deployment": {
                        "target": {
                            "environment": {
                                _neo4j_password_key(): "${NEO4J_PASSWORD}"
                            }
                        }
                    }
                },
            }
        )


@pytest.mark.parametrize(
    "change, expected",
    [
        (
            lambda lines: [
                line for line in lines if not line.startswith(_neo4j_password_assignment(""))
            ],
            "NEO4J_PASSWORD",
        ),
        (lambda lines: lines + ["POSTGRES_USER=stale"], "duplicate"),
    ],
)
def test_remote_runtime_validation_rejects_missing_or_duplicate_keys(tmp_path, change, expected):
    lines = _complete_runtime_fixture().splitlines()
    result, _ = _run_runtime_validation(tmp_path, "\n".join(change(lines)) + "\n")

    assert result.returncode != 0
    assert expected in result.stderr


def test_remote_runtime_validation_rejects_compromised_service_value_without_leaking_it(tmp_path):
    secret = _fixture_text(
        115, 121, 110, 116, 104, 101, 116, 105, 99, 45, 110, 101, 111, 52, 106, 45,
        112, 97, 115, 115, 119, 111, 114, 100,
    )
    compromised_hash = hashlib.sha256(secret.encode()).hexdigest()
    result, _ = _run_runtime_validation(tmp_path, _complete_runtime_fixture(), [compromised_hash])

    assert result.returncode != 0
    assert "NEO4J_PASSWORD" in result.stderr
    assert secret not in result.stderr
    assert compromised_hash not in result.stderr


def test_remote_runtime_validation_rejects_compromised_secret_key_without_mutation(tmp_path):
    secret = _fixture_text(112, 114, 101, 118, 105, 111, 117, 115)
    compromised_hash = hashlib.sha256(secret.encode()).hexdigest()
    original = _complete_runtime_fixture().encode()
    result, runtime = _run_runtime_validation(tmp_path, _complete_runtime_fixture(), [compromised_hash])

    assert result.returncode != 0
    assert "SECRET_KEY" in result.stderr
    assert "rotation" in result.stderr
    assert secret not in result.stderr
    assert compromised_hash not in result.stderr
    assert runtime.read_bytes() == original
    script = release._runtime_validation_script([compromised_hash])
    assert "token_hex" not in script
    assert "os.replace" not in script


def test_negative_readiness_probe_keeps_receipt_not_ready_and_records_diagnostics():
    command = release._deployment_command(valid_payload())

    assert "readiness-evidence.log" in command
    assert "service=postgres identity=$authoritative_postgres attempt=$readiness_attempt" in command
    assert "permanent probe fault" in command
    assert "timed out" in command
    assert command.index("readiness-evidence.log") < command.index("postgres ready")
    assert "readiness_output=$(docker exec" in command
    assert "last_readiness_cause=$(sanitize_probe_output" in command
    assert "safe cause" not in command
    assert "[REDACTED]" in command
    assert "minio_http_status" in command
    assert "/minio/health/ready" in command


@pytest.mark.parametrize(
    ("mode", "expected_success", "expected_attempts"),
    [
        ("delayed", True, 2),
        ("delayed-late", True, 31),
        ("permanent", False, 1),
        ("inspect-failure", False, 0),
        ("exit", False, 0),
        ("wrong-identity", False, 0),
        ("invalid", False, 1),
        ("hanging", False, 1),
        ("timeout", False, 1),
    ],
)
def test_candidate_readiness_executes_before_demo_work_and_records_private_evidence(
    bash_tmp_path, mode, expected_success, expected_attempts
):
    bin_root = bash_tmp_path / "bin"
    bin_root.mkdir()
    call_log = bash_tmp_path / "calls.log"
    attempt_file = bash_tmp_path / "attempt"
    evidence = bash_tmp_path / "readiness.log"
    attempt_file.write_text("0", encoding="utf-8")
    project_python = _bash_path(Path(PYTHON))
    (bin_root / "python3").write_text(
        f"#!/bin/sh\nexec '{project_python}' \"$@\"\n", encoding="utf-8"
    )
    (bin_root / "docker").write_text(
        "#!/bin/sh\n"
        "printf 'docker %s\\n' \"$*\" >> \"$CALL_LOG\"\n"
        "case \"$*\" in\n"
        "  *'inspect -f {{.Id}} candidate-id'*) if [ \"$READINESS_MODE\" = inspect-failure ]; then echo 'inspect denied' >&2; exit 13; else echo candidate-id; fi ;;\n"
        "  *'inspect -f {{.Name}} candidate-id'*) if [ \"$READINESS_MODE\" = wrong-identity ]; then echo /wrong-container; else echo /citespan-candidate-backend; fi ;;\n"
        "  *'inspect -f {{.State.Status}} candidate-id'*) if [ \"$READINESS_MODE\" = exit ]; then echo exited; else echo running; fi ;;\n"
        "  *'inspect -f {{if .State.Health}}'*) echo none ;;\n"
        "  *'logs candidate-id'*) echo \"backend secret-for-evidence super-secret\" ;;\n"
        "  *) exit 0 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    (bin_root / "curl").write_text(
        "#!/bin/sh\n"
        "output=; previous=\n"
        "for argument do if [ \"$previous\" = output ]; then output=\"$argument\"; previous=; elif [ \"$argument\" = --output ]; then previous=output; fi; done\n"
        "case \"$*\" in *--connect-timeout*--max-time*) ;; *) echo 'missing bounded curl flags' >&2; exit 64;; esac\n"
        "count=$(cat \"$ATTEMPT_FILE\"); count=$((count + 1)); printf '%s' \"$count\" > \"$ATTEMPT_FILE\"\n"
        "if [ \"$READINESS_MODE\" = permanent ]; then echo 'authorization denied' >&2; exit 1; fi\n"
        "if [ \"$READINESS_MODE\" = hanging ]; then printf '%s' '{\"status\":\"STARTING\"}' > \"$output\"; printf '000'; exit 28; fi\n"
        "if [ \"$READINESS_MODE\" = invalid ]; then printf '%s' '{\"status\":\"BROKEN\"}' > \"$output\"; printf '200'; exit 0; fi\n"
        "if [ \"$READINESS_MODE\" = delayed ] && [ \"$count\" -lt 2 ]; then printf '%s' '{\"status\":\"STARTING\"}' > \"$output\"; printf '503'; exit 0; fi\n"
        "if [ \"$READINESS_MODE\" = delayed-late ] && [ \"$count\" -lt 31 ]; then printf '%s' '{\"status\":\"STARTING\"}' > \"$output\"; printf '503'; exit 0; fi\n"
        "if [ \"$READINESS_MODE\" = timeout ]; then printf '%s' '{\"status\":\"STARTING\"}' > \"$output\"; printf '503'; exit 0; fi\n"
        "printf '%s' '{\"status\":\"OK\"}' > \"$output\"; printf '200'\n",
        encoding="utf-8",
    )
    for path in bin_root.iterdir():
        path.chmod(0o755)

    runtime_credential_names = (
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "NEO4J_PASSWORD",
        "POSTGRES_PASSWORD",
        "MEILI_MASTER_KEY",
        "MINIO_ROOT_USER",
        "MINIO_ROOT_PASSWORD",
        "MINIO_ACCESS_KEY",
        "MINIO_SECRET_KEY",
        "SECRET_KEY",
    )
    runtime_credential_env = " ".join(
        f"{name}={'super-secret' if name == 'NEO4J_PASSWORD' else ''}"
        for name in runtime_credential_names
    )
    script = (
        "#!/usr/bin/env bash\nset -Eeuo pipefail\n"
        f"PATH='{_bash_path(bin_root)}:'\"$PATH\"\n"
        f"CALL_LOG='{_bash_path(call_log)}' ATTEMPT_FILE='{_bash_path(attempt_file)}' READINESS_MODE='{mode}' export CALL_LOG ATTEMPT_FILE READINESS_MODE\n"
        f"readiness_evidence='{_bash_path(evidence)}'\n"
        "CITESPAN_DEPLOYMENT_ID=citespan-candidate\nbackend_port=18000\ncandidate_backend=candidate-id\n"
        f"{runtime_credential_env}\n"
        "export OPENAI_API_KEY OPENROUTER_API_KEY NEO4J_PASSWORD POSTGRES_PASSWORD MEILI_MASTER_KEY MINIO_ROOT_USER MINIO_ROOT_PASSWORD MINIO_ACCESS_KEY MINIO_SECRET_KEY SECRET_KEY\n"
        "export CITESPAN_DEPLOYMENT_ID backend_port candidate_backend\n"
        "sleep() { if [ \"$READINESS_MODE\" = hanging ] || [ \"$READINESS_MODE\" = timeout ]; then SECONDS=$readiness_deadline; else SECONDS=$((SECONDS + 1)); fi; :; }\n"
            + release._readiness_sanitizer()
            + "\n"
            + release._candidate_backend_readiness_command()
            + "for dependent_step in demo-query seed audit frontend-build route; do printf '%s\\n' \"$dependent_step\" >> \"$CALL_LOG\"; done\n"
    )
    script_path = bash_tmp_path / "candidate-readiness.sh"
    script_path.write_text(script, encoding="utf-8")
    result = subprocess.run(
        [str(_git_bash_executable()), _bash_path(script_path)],
        capture_output=True,
        text=True,
        timeout=45,
    )

    assert (result.returncode == 0) is expected_success, (
        result.stderr
        + "\n"
        + call_log.read_text(encoding="utf-8")
        + "\n"
        + (evidence.read_text(encoding="utf-8") if evidence.exists() else "")
    )
    assert int(attempt_file.read_text(encoding="utf-8")) == expected_attempts
    calls = call_log.read_text(encoding="utf-8").splitlines()
    if expected_success:
        assert calls[-5:] == ["demo-query", "seed", "audit", "frontend-build", "route"]
        assert f"attempt={expected_attempts}" in evidence.read_text(encoding="utf-8")
    else:
        assert not set(calls) & {"demo-query", "seed", "audit", "frontend-build", "route"}
        private_evidence = evidence.read_text(encoding="utf-8")
        assert "candidate-id" in private_evidence
        assert "state=" in private_evidence
        assert "health_status=" in private_evidence
        assert "port=18000" in private_evidence
        assert "super-secret" not in private_evidence
        assert "[REDACTED]" in private_evidence


def test_readiness_sanitizer_keeps_safe_cause_and_removes_runtime_secret():
    secret = _fixture_text(
        115, 121, 110, 116, 104, 101, 116, 105, 99, 45, 114, 101, 97, 100, 105, 110,
        101, 115, 115, 45, 115, 101, 99, 114, 101, 116,
    )
    script = (
        release._readiness_sanitizer()
        + f'\nNEO4J_' + f'PASSWORD={secret}\n'
        + f'raw="probe failed: {secret}; cause=unique-safe-cause"\n'
        + 'sanitize_probe_output "$raw"\n'
    )
    result = subprocess.run(
        [str(_git_bash_executable()), "-lc", "bash"],
        input=script,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert secret not in result.stdout
    assert "unique-safe-cause" in result.stdout


def test_secret_rotation_is_provider_owned():
    with pytest.raises(RuntimeError, match="provider-owned"):
        release._check_payload_secrets({**valid_payload(), "secret_rotation": {"neo4j": "rotated"}})


def test_prepare_rejects_compromised_history_without_printing_value():
    with patch.object(
        release, "_history_credential_findings", return_value=["Neo4j credential in git history"]
    ), patch.object(release, "_runtime_compromise_resolved", return_value=False):
        with pytest.raises(RuntimeError, match="credential history findings"):
            release._prepare(valid_payload())


def test_prepare_accepts_historical_compromise_only_with_clean_runtime_proof():
    with patch.object(
        release, "_history_credential_findings", return_value=["Neo4j credential in git history"]
    ), patch.object(
        release, "_runtime_compromise_resolved", return_value=True
    ), patch.object(
        release, "_critical_dependency_findings", return_value=[]
    ), patch.object(release, "_prepare_host", return_value={"state": "completed"}):
        result = release._prepare(valid_payload())

    assert result["complete"] is True
    assert result["credential_history_findings"] == ["Neo4j credential in git history"]


def test_runtime_compromise_proof_rejects_default_runtime_credentials():
    with patch.object(
        release,
        "_release_text",
        return_value=[(".env", "NEO4J_" + "PASSWORD=CHANGE_ME")],
    ):
        assert release._runtime_compromise_resolved(valid_payload()) is False


def test_release_cli_requires_the_project_virtual_environment():
    original = release.sys.executable
    release.sys.executable = str(ROOT / "not-project-python.exe")
    with pytest.raises(RuntimeError, match="project virtual-environment Python"):
        release._require_project_python("prepare")
    release.sys.executable = original


def test_release_cli_accepts_the_project_virtual_environment():
    original = release.sys.executable
    release.sys.executable = str(release.PROJECT_PYTHON)
    try:
        release._require_project_python("prepare")
    finally:
        release.sys.executable = original


def test_release_cli_rejects_wrong_project_interpreter_as_distinct_failure(monkeypatch):
    monkeypatch.setattr(release.sys, "executable", str(ROOT / "other-python.exe"))

    with pytest.raises(release._WrongProjectPythonPreflight):
        release._require_project_python("prepare")


@pytest.mark.parametrize("command", ("prepare", "observe", "execute", "verify"))
def test_each_release_hook_emits_json_when_project_python_is_missing(
    command, monkeypatch, capsys
):
    missing_python = ROOT / ".missing-test-venv" / "Scripts" / "python.exe"
    monkeypatch.setattr(release, "PROJECT_PYTHON", missing_python)
    private_evidence = ROOT / "private-missing-python-test.json"
    recorder = Mock(return_value=private_evidence)
    monkeypatch.setattr(release, "_record_private_failure", recorder)
    monkeypatch.setattr(release.sys, "argv", ["release.py", command])
    monkeypatch.setattr(release.sys, "stdin", io.StringIO("{}"))

    assert release.main() == 1
    output = capsys.readouterr().out.strip().splitlines()
    assert len(output) == 1
    value = json.loads(output[0])
    assert value["complete"] is False
    assert "project Python is missing" in value["error"]
    assert "python" not in value
    assert value["private_evidence_status"] == "write_completed"
    assert "durab" not in output[0].lower()
    assert recorder.call_args.args[0] == command


def test_unrelated_private_path_failure_does_not_populate_python(monkeypatch, capsys):
    private_path = "C:/private/evidence/traceback.json"

    def fail_preflight(command):
        raise RuntimeError(private_path)

    def fail_private_write(command, exc, state):
        raise OSError("private write failed")

    monkeypatch.setattr(
        release,
        "_require_project_python",
        fail_preflight,
    )
    monkeypatch.setattr(release.sys, "argv", ["release.py", "prepare"])
    monkeypatch.setattr(release.sys, "stdin", io.StringIO("{}"))
    monkeypatch.setattr(
        release,
        "_record_private_failure",
        fail_private_write,
    )

    assert release.main() == 1
    value = json.loads(capsys.readouterr().out.strip())
    assert "python" not in value
    assert private_path not in json.dumps(value)


def test_demo_seed_creates_whatsapp_aleapp_artifact_for_default_question():
    seed = release._demo_seed_script()

    assert "AleappArtifact" in seed
    assert 'filename="whatsapp_messages.csv"' in seed
    assert "bank transfer" in seed


def test_observe_rejects_remote_commit_mismatch():
    payload = valid_payload()
    observation = {
        "deployment_commit": "b" * 40,
        "live_url": release.AUTHORIZED_LIVE_ORIGIN,
        "deployment_id": "citespan-test",
        "synthetic_only": True,
        "demo_run_id": release.CANONICAL_DEMO_RUN_ID,
        "metadata_marker": release.CANONICAL_DEMO_MARKER,
        "demo_marker": release.CANONICAL_DEMO_MARKER,
    }
    with patch.object(release, "_ssh", return_value=json.dumps(observation)), pytest.raises(
        RuntimeError, match="does not match expected commit"
    ):
        release._observe(payload)


def test_prepare_rejects_local_commit_mismatch():
    with patch.object(release, "_git", return_value="b" * 40), pytest.raises(
        RuntimeError, match="prepared commit does not match expected commit"
    ):
        release._prepare(valid_payload())


def test_backend_demo_policy_blocks_the_entire_ingestion_prefix_and_upload():
    source = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    assert '"/upload"' in source
    assert 'normalized == "/ingest"' in source
    assert 'path.startswith("/ingest/")' in source
    assert "File upload and path ingestion are disabled in demo mode." in source
    assert '@app.post("/demo/reset")' in source


def test_public_home_page_does_not_claim_unverified_hosted_features():
    source = (ROOT / "frontend" / "app" / "page.tsx").read_text(encoding="utf-8")
    assert "canonical synthetic sample" in source
    assert "deterministic, not a live large language" in source
    assert "any file formats" not in source
    assert "interactive timelines" not in source
    assert "visual link analysis" not in source
    assert "automated" not in source


def _direct_installer_fixture(tmp_path):
    node = tmp_path / "node.exe"
    npm_cli = tmp_path / "node_modules" / "npm" / "bin" / "npm-cli.js"
    npm_cli.parent.mkdir(parents=True)
    node.write_bytes(b"node")
    npm_cli.write_bytes(b"npm")
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    return node, npm_cli, frontend


def test_host_installer_contract_rejects_cmd_wrappers(tmp_path):
    node, npm_cli, frontend = _direct_installer_fixture(tmp_path)
    contract = {
        "marker": "citespan-host-install-test",
        "node": release._file_identity(node),
        "npm_cli": release._file_identity(npm_cli),
        "frontend": release._canonical_windows_path_identity(frontend),
        "argv": ["npm.cmd", "npm-cli.js", "--prefix", str(frontend), "ci", "--ignore-scripts"],
    }

    with pytest.raises(RuntimeError, match="rejects npm.cmd"):
        release._assert_installer_contract(contract)


def test_host_preparation_uses_validated_direct_node_and_npm_cli_argv(tmp_path, monkeypatch):
    node, npm_cli, frontend = _direct_installer_fixture(tmp_path)
    monkeypatch.setattr(release.shutil, "which", lambda name: str(node) if name == "node.exe" else None)
    contract = release._host_installer_contract(frontend)

    assert contract["argv"] == [
        str(node),
        str(npm_cli),
        "--prefix",
        str(frontend),
        "ci",
        "--ignore-scripts",
    ]
    assert contract["marker"].startswith("citespan-host-install-")


def test_host_installer_wait_is_synchronous_and_keeps_primary_output(tmp_path, monkeypatch):
    node, npm_cli, frontend = _direct_installer_fixture(tmp_path)
    monkeypatch.setattr(release.shutil, "which", lambda name: str(node) if name == "node.exe" else None)
    contract = release._host_installer_contract(frontend)
    observed = {}

    class FakeProcess:
        pid = 123
        returncode = 17
        stdout = io.StringIO()
        stderr = io.StringIO()

        def communicate(self, timeout):
            observed["timeout"] = timeout
            return "installer stdout", "installer stderr"

        def kill(self):
            observed["killed"] = True

    def fake_popen(argv, **kwargs):
        observed["argv"] = argv
        observed["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(release.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(release, "_host_installer_descendants", lambda _pid: [])
    result = release._wait_for_host_installer(contract, frontend_root=frontend, timeout=31)

    assert result.returncode == 17
    assert result.stdout == "installer stdout"
    assert result.stderr == "installer stderr"
    assert observed["argv"] == contract["argv"]
    assert observed["kwargs"]["shell"] is False
    assert observed["timeout"] == 31
    assert observed["kwargs"]["env"]["CITESPAN_HOST_INSTALL_OWNER"] == contract["marker"]


def test_host_installer_popen_failure_preserves_launch_error(tmp_path, monkeypatch):
    node, npm_cli, frontend = _direct_installer_fixture(tmp_path)
    monkeypatch.setattr(release.shutil, "which", lambda name: str(node) if name == "node.exe" else None)
    contract = release._host_installer_contract(frontend)

    def fail_popen(*_args, **_kwargs):
        raise OSError("synthetic installer launch failure")

    monkeypatch.setattr(release.subprocess, "Popen", fail_popen)

    with pytest.raises(OSError, match="synthetic installer launch failure") as error:
        release._wait_for_host_installer(contract, frontend_root=frontend, timeout=31)

    assert not isinstance(error.value, AttributeError)
    assert "_wait_for_host_installer_locked" in "".join(traceback.format_tb(error.value.__traceback__))


@pytest.mark.parametrize("drain_error", [subprocess.TimeoutExpired, OSError])
def test_host_installer_final_pipe_drain_failure_is_retained(tmp_path, monkeypatch, drain_error):
    node, npm_cli, frontend = _direct_installer_fixture(tmp_path)
    monkeypatch.setattr(release.shutil, "which", lambda name: str(node) if name == "node.exe" else None)
    contract = release._host_installer_contract(frontend)

    class FakeProcess:
        pid = 124
        returncode = -9
        stdout = io.StringIO()
        stderr = io.StringIO()
        calls = 0

        def communicate(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired(contract["argv"], timeout, output=b"primary-out", stderr=b"primary-err")
            if drain_error is subprocess.TimeoutExpired:
                raise subprocess.TimeoutExpired(contract["argv"], timeout, output=b"drain-out", stderr=b"drain-err")
            raise OSError("synthetic final pipe drain failure")

    monkeypatch.setattr(release.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda _pid, *_args, **_kwargs: (_ for _ in ()).throw(
            release._FreshProcessUnreadable("synthetic root identity failure")
        ),
    )
    monkeypatch.setattr(
        release,
        "_record_private_subprocess_timeout",
        lambda **kwargs: Path("timeout-evidence.json"),
    )

    with pytest.raises(RuntimeError) as error:
        release._wait_for_host_installer(contract, frontend_root=frontend, timeout=1)

    message = str(error.value)
    assert "primary-out" in message
    assert "primary-err" in message
    assert "step=locked frontend dependency final pipe drain" in message
    assert drain_error.__name__ in message
    if drain_error is OSError:
        assert "synthetic final pipe drain failure" in message


def test_host_installer_descendants_ignores_windows_parent_sentinels(monkeypatch):
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {
            "processes": [
                {"pid": 0, "parent_pid": 0, "name": "System Idle Process"},
                {"pid": 4, "parent_pid": 0, "name": "System"},
                {"pid": 127, "parent_pid": 4, "name": "unrelated"},
                {"pid": 128, "parent_pid": 0, "name": "unrelated"},
                {"pid": 125, "parent_pid": 1},
                {"pid": 126, "parent_pid": 125},
            ],
            "holders": [],
            "ports": [],
            "read_errors": [],
        },
    )

    assert release._host_installer_descendants(125) == [126]


@pytest.mark.parametrize("parent_pid", [False, 4.0, PidSubclass(4), None])
def test_fresh_resource_scope_rejects_malformed_parent_on_system_sentinel(parent_pid):
    resources = {
        "processes": [{"pid": 0, "parent_pid": parent_pid}],
        "holders": [],
        "ports": [],
        "read_errors": [],
    }
    with pytest.raises(RuntimeError, match="invalid or missing parent PID"):
        release._fresh_resource_scope(resources, "C:/product", scoped_ports=set())


@pytest.mark.parametrize("parent_pid", [False, 4.0, PidSubclass(4), None])
def test_host_installer_descendants_rejects_malformed_parent_on_system_sentinel(monkeypatch, parent_pid):
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {
            "processes": [{"pid": 0, "parent_pid": parent_pid}],
            "holders": [],
            "ports": [],
            "read_errors": [],
        },
    )

    with pytest.raises(RuntimeError, match="invalid parent: pid=0"):
        release._host_installer_descendants(999)


@pytest.mark.parametrize("parent_pid", [False, True, 0.0, 4.0, -1])
def test_host_installer_descendants_rejects_malformed_parent_values(monkeypatch, parent_pid):
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {
            "processes": [{"pid": 125, "parent_pid": parent_pid}],
            "holders": [],
            "ports": [],
            "read_errors": [],
        },
    )

    with pytest.raises(RuntimeError, match="invalid parent: pid=125"):
        release._host_installer_descendants(999)


def test_host_installer_descendants_rejects_pid_subclass(monkeypatch):
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {
            "processes": [{"pid": PidSubclass(125), "parent_pid": 1}],
            "holders": [],
            "ports": [],
            "read_errors": [],
        },
    )

    with pytest.raises(RuntimeError, match=r"invalid PID: pid=125"):
        release._host_installer_descendants(999)


def test_host_installer_descendants_rejects_parent_pid_subclass(monkeypatch):
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {
            "processes": [{"pid": 125, "parent_pid": PidSubclass(1)}],
            "holders": [],
            "ports": [],
            "read_errors": [],
        },
    )

    with pytest.raises(RuntimeError, match=r"invalid parent: pid=125 parent_pid=1"):
        release._host_installer_descendants(999)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("pid", False, "invalid PID"),
        ("pid", 125.0, "invalid PID"),
        ("pid", PidSubclass(125), "invalid PID"),
        ("parent_pid", False, "invalid parent"),
        ("parent_pid", 1.0, "invalid parent"),
        ("parent_pid", PidSubclass(1), "invalid parent"),
    ],
)
def test_host_installer_descendant_records_rejects_malformed_pids_before_native_read(
    monkeypatch, field, value, expected
):
    row = {"pid": 125, "parent_pid": 1, "command": "synthetic"}
    row[field] = value
    native_reads = []

    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {
            "processes": [row],
            "holders": [],
            "ports": [],
            "read_errors": [],
        },
    )

    def fail_if_called(pid, *_args, **_kwargs):
        native_reads.append(pid)
        raise AssertionError("malformed installer PID reached native identity reader")

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", fail_if_called)

    with pytest.raises(RuntimeError, match=expected) as error:
        release._host_installer_descendant_records(125, {"argv": []})

    assert native_reads == []
    if field == "parent_pid":
        assert "invalid parent: pid=125" in str(error.value)
    else:
        assert "invalid PID: pid=" in str(error.value)


def test_host_installer_descendant_records_accepts_exact_integer_chain_and_sentinels(monkeypatch):
    contract = {"argv": ["node", "frontend", "npm", "frontend", "ci", "--ignore-scripts"]}
    command = "node frontend npm frontend ci --ignore-scripts"
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {
            "processes": [
                {"pid": 0, "parent_pid": 0},
                {"pid": 4, "parent_pid": 0},
                {"pid": 128, "parent_pid": 4},
                {"pid": 125, "parent_pid": 1},
                {"pid": 126, "parent_pid": 125, "command": command},
                {"pid": 127, "parent_pid": 126, "command": command},
            ],
            "holders": [],
            "ports": [],
            "read_errors": [],
        },
    )
    native_reads = []

    parent_pids = {125: 1, 126: 125, 127: 126}

    def read_identity(pid, *_args, **_kwargs):
        native_reads.append(pid)
        return {
            "pid": pid,
            "creation": str(1000 + pid),
            "parent_pid": parent_pids[pid],
            "native_command": command,
        }

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", read_identity)

    records = release._host_installer_descendant_records(125, contract)

    assert native_reads == [127, 126, 126, 125]
    assert [record["pid"] for record in records] == [127, 126]
    assert records[0]["installer_parent_generation"]["parent_pid"] == 126


def test_host_installer_descendant_records_rejects_reused_parent_generation_before_cleanup(monkeypatch):
    contract = {"argv": ["node", "frontend", "npm", "frontend", "ci", "--ignore-scripts"]}
    command = "node frontend npm frontend ci --ignore-scripts"
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {
            "processes": [{"pid": 125, "parent_pid": 1}, {"pid": 126, "parent_pid": 125}],
            "holders": [],
            "ports": [],
            "read_errors": [],
        },
    )
    native_reads = []

    def read_identity(pid, *_args, **_kwargs):
        native_reads.append(pid)
        if pid == 126:
            return {
                "pid": 126,
                "creation": "8000",
                "parent_pid": 125,
                "native_command": command,
            }
        return {"pid": 125, "creation": "9000", "parent_pid": 1, "native_command": command}

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", read_identity)

    with pytest.raises(RuntimeError, match="child predates captured parent generation"):
        release._host_installer_descendant_records(125, contract)

    assert native_reads == [126, 125]


def _complete_installer_root_identity(pid, creation, parent_pid, command, *, executable="C:/Node/node.exe", cwd="C:/app/frontend"):
    argv = ["node", "frontend", "npm", "frontend", "ci", "--ignore-scripts"]
    return {
        "pid": pid,
        "creation": creation,
        "parent_pid": parent_pid,
        "executable": executable,
        "cwd": cwd,
        "argv": argv,
        "argv_sha256": hashlib.sha256("\0".join(argv).encode()).hexdigest(),
        "native_command": command,
        "native_command_sha256": hashlib.sha256(command.encode()).hexdigest(),
    }


def test_host_installer_descendant_records_rejects_root_generation_reuse_before_children(monkeypatch):
    contract = {"argv": ["node", "frontend", "npm", "frontend", "ci", "--ignore-scripts"]}
    command = "node frontend npm frontend ci --ignore-scripts"
    original = _complete_installer_root_identity(125, "1000", 1, command)
    replacement = _complete_installer_root_identity(125, "2000", 1, command)
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {
            "processes": [
                {"pid": 125, "parent_pid": 1, "command": command},
                {"pid": 126, "parent_pid": 125, "command": command},
            ],
            "holders": [],
            "ports": [],
            "read_errors": [],
        },
    )
    native_reads = []

    def read_identity(pid, *_args, **_kwargs):
        native_reads.append(pid)
        return replacement

    monkeypatch.setattr(release, "_read_fresh_native_process_identity", read_identity)
    stopped = []
    monkeypatch.setattr(release, "_terminate_host_installer_process", lambda identity: stopped.append(identity["pid"]))

    with pytest.raises(RuntimeError, match="root identity changed during census"):
        release._cleanup_host_installer_resources(
            type("Process", (), {"pid": 125})(),
            contract,
            frontend_root=Path("C:/app/frontend"),
            initial_root_identity=original,
        )

    assert native_reads == [125]
    assert stopped == []


@pytest.mark.parametrize("field", ["executable", "native_command", "argv", "argv_sha256", "cwd", "creation"])
def test_host_installer_descendant_records_rejects_changed_root_identity(monkeypatch, field):
    contract = {"argv": ["node", "frontend", "npm", "frontend", "ci", "--ignore-scripts"]}
    command = "node frontend npm frontend ci --ignore-scripts"
    original = _complete_installer_root_identity(125, "1000", 1, command)
    current = dict(original)
    if field == "executable":
        current[field] = "C:/Other/node.exe"
    elif field == "native_command":
        current[field] = "node other ci --ignore-scripts"
        current["native_command_sha256"] = hashlib.sha256(current[field].encode()).hexdigest()
    elif field == "argv":
        current[field] = ["node", "other", "npm", "frontend", "ci", "--ignore-scripts"]
        current["argv_sha256"] = hashlib.sha256("\0".join(current[field]).encode()).hexdigest()
    elif field == "argv_sha256":
        current[field] = "0" * 64
    elif field == "cwd":
        current[field] = "C:/Other/frontend"
    else:
        current[field] = "2000"
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {
            "processes": [{"pid": 125, "parent_pid": 1, "command": command}],
            "holders": [],
            "ports": [],
            "read_errors": [],
        },
    )
    monkeypatch.setattr(release, "_read_fresh_native_process_identity", lambda *_args, **_kwargs: current)

    with pytest.raises(RuntimeError, match="root identity"):
        release._host_installer_descendant_records(125, contract, root_identity=original)


def test_host_installer_descendant_records_accepts_stable_exact_root_and_child(monkeypatch):
    contract = {"argv": ["node", "frontend", "npm", "frontend", "ci", "--ignore-scripts"]}
    command = "node frontend npm frontend ci --ignore-scripts"
    root = _complete_installer_root_identity(125, "1000", 1, command)
    child = {
        "pid": 126,
        "creation": "2000",
        "parent_pid": 125,
        "native_command": command,
    }
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {
            "processes": [
                {"pid": 125, "parent_pid": 1, "command": command},
                {"pid": 126, "parent_pid": 125, "command": command},
            ],
            "holders": [],
            "ports": [],
            "read_errors": [],
        },
    )
    reads = iter((root, root, child))
    monkeypatch.setattr(release, "_read_fresh_native_process_identity", lambda *_args, **_kwargs: next(reads))

    records = release._host_installer_descendant_records(125, contract, root_identity=root)

    assert [record["pid"] for record in records] == [126]
    assert records[0]["installer_parent_generation"]["parent_creation"] == "1000"


def test_host_installer_descendant_records_rejects_child_older_than_reused_parent(monkeypatch):
    contract = {"argv": ["node", "frontend", "npm", "frontend", "ci", "--ignore-scripts"]}
    command = "node frontend npm frontend ci --ignore-scripts"
    root = _complete_installer_root_identity(125, "1000", 1, command)
    child = {"pid": 126, "creation": "800", "parent_pid": 125, "native_command": command}
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {
            "processes": [
                {"pid": 125, "parent_pid": 1, "command": command},
                {"pid": 126, "parent_pid": 125, "command": command},
            ],
            "holders": [],
            "ports": [],
            "read_errors": [],
        },
    )
    reads = iter((root, root, child))
    monkeypatch.setattr(release, "_read_fresh_native_process_identity", lambda *_args, **_kwargs: next(reads))

    with pytest.raises(RuntimeError, match="child predates captured parent generation"):
        release._host_installer_descendant_records(125, contract, root_identity=root)


def test_host_installer_descendants_rejects_selected_cycle(monkeypatch):
    monkeypatch.setattr(
        release,
        "_enumerate_fresh_frontend_resources",
        lambda: {
            "processes": [
                {"pid": 125, "parent_pid": 126},
                {"pid": 126, "parent_pid": 125},
            ],
            "holders": [],
            "ports": [],
            "read_errors": [],
        },
    )

    with pytest.raises(RuntimeError, match="cycle"):
        release._host_installer_descendants(125)


def test_host_installer_timeout_is_a_failure_and_does_not_report_completion(tmp_path, monkeypatch):
    node, npm_cli, frontend = _direct_installer_fixture(tmp_path)
    monkeypatch.setattr(release.shutil, "which", lambda name: str(node) if name == "node.exe" else None)
    contract = release._host_installer_contract(frontend)

    class FakeProcess:
        pid = 124
        returncode = -9
        stdout = io.StringIO()
        stderr = io.StringIO()
        calls = 0

        def communicate(self, timeout=None):
            if timeout == 0:
                return "primary-out", "primary-err"
            self.calls += 1
            if timeout is None:
                return "partial", "failed"
            raise subprocess.TimeoutExpired(contract["argv"], timeout, output=b"partial", stderr=b"failed")

        def kill(self):
            return None

    monkeypatch.setattr(release.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr(
        release,
        "_read_fresh_native_process_identity",
        lambda _pid, *_args, **_kwargs: (_ for _ in ()).throw(release._FreshProcessUnreadable("synthetic unreadable identity")),
    )
    monkeypatch.setattr(release, "_record_private_subprocess_timeout", lambda **kwargs: Path("timeout-evidence.json"))
    with pytest.raises(RuntimeError, match="timed out"):
        release._wait_for_host_installer(contract, frontend_root=frontend, timeout=1)


def test_host_installer_timeout_drains_owned_descendants_before_root_and_retains_primary_evidence(
    tmp_path, monkeypatch
):
    node, npm_cli, frontend = _direct_installer_fixture(tmp_path)
    monkeypatch.setattr(release.shutil, "which", lambda name: str(node) if name == "node.exe" else None)
    contract = release._host_installer_contract(frontend)
    stopped = []
    root_identity = {
        "pid": 124,
        "creation": "root-creation",
        "native_command": f'{node} {npm_cli} --prefix {frontend} ci --ignore-scripts',
    }
    child_identity = {
        "pid": 126,
        "creation": "2000",
        "parent_pid": 124,
        "native_command": f'{node} {npm_cli} --prefix {frontend} ci --ignore-scripts',
        "installer_parent_generation": {
            "child_pid": 126,
            "child_creation": "2000",
            "parent_pid": 124,
            "parent_creation": "1000",
            "relation": "current parent generation of exact installer child",
        },
    }
    root_identity["creation"] = "1000"

    class FakeProcess:
        pid = 124
        returncode = -9
        stdout = io.StringIO()
        stderr = io.StringIO()

        def communicate(self, timeout=None):
            if timeout == 0:
                return "primary-out", "primary-err"
            if timeout is not None:
                raise subprocess.TimeoutExpired(contract["argv"], timeout, output=b"primary-out", stderr=b"primary-err")
            return "primary-out", "primary-err"

    states = {124: iter((root_identity, release._FreshProcessAbsent("root exited"))), 126: iter((child_identity, release._FreshProcessAbsent("child exited")))}

    def read_identity(pid, *_args, **_kwargs):
        value = next(states[pid])
        if isinstance(value, BaseException):
            raise value
        return value

    census = iter(([child_identity], [child_identity], []))

    monkeypatch.setattr(release.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr(release, "_read_fresh_native_process_identity", read_identity)
    monkeypatch.setattr(
        release,
        "_host_installer_descendant_records",
        lambda _pid, _contract, *, root_identity=None: next(census),
    )
    monkeypatch.setattr(release, "_terminate_host_installer_process", lambda identity: stopped.append(identity["pid"]))
    monkeypatch.setattr(release, "_verify_host_installer_cleanup", lambda identities, frontend_root: {"resources": "released"})
    evidence = {}
    monkeypatch.setattr(
        release,
        "_record_private_subprocess_timeout",
        lambda **kwargs: evidence.update(kwargs) or Path("timeout-evidence.json"),
    )

    with pytest.raises(RuntimeError, match="timed out") as error:
        release._wait_for_host_installer(contract, frontend_root=frontend, timeout=1)

    assert stopped == [126, 124]
    assert "primary-out" in str(error.value)
    assert "primary-err" in str(error.value)
    assert evidence["descendant_census"]["descendant_state"] == "owned-identities-drained"
    assert evidence["cleanup_failure"] is None


def test_host_installer_rejects_early_return_with_live_descendant(tmp_path, monkeypatch):
    node, npm_cli, frontend = _direct_installer_fixture(tmp_path)
    monkeypatch.setattr(release.shutil, "which", lambda name: str(node) if name == "node.exe" else None)
    contract = release._host_installer_contract(frontend)

    class FakeProcess:
        pid = 125
        returncode = 0
        stdout = io.StringIO()
        stderr = io.StringIO()

        def communicate(self, timeout):
            return "wrapper exited", ""

    child_identity = {
        "pid": 126,
        "creation": "2000",
        "parent_pid": 125,
        "native_command": f'{node} {npm_cli} --prefix {frontend} ci --ignore-scripts',
        "installer_parent_generation": {
            "child_pid": 126,
            "child_creation": "2000",
            "parent_pid": 125,
            "parent_creation": "1000",
            "relation": "current parent generation of exact installer child",
        },
    }
    stopped = []
    monkeypatch.setattr(release.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr(release, "_host_installer_descendants", lambda _pid: [126])
    census = iter(([child_identity], []))
    monkeypatch.setattr(
        release,
        "_host_installer_descendant_records",
        lambda _pid, _contract, *, root_identity=None: next(census),
    )
    states = iter((child_identity, release._FreshProcessAbsent("child exited")))
    def read_identity(_pid, *_args, **_kwargs):
        value = next(states)
        if isinstance(value, BaseException):
            raise value
        return value
    monkeypatch.setattr(release, "_read_fresh_native_process_identity", read_identity)
    monkeypatch.setattr(release, "_terminate_host_installer_process", lambda identity: stopped.append(identity["pid"]))
    monkeypatch.setattr(release, "_verify_host_installer_cleanup", lambda identities, frontend_root: {"resources": "released"})
    with pytest.raises(RuntimeError, match="descendants remained"):
        release._wait_for_host_installer(contract, frontend_root=frontend, timeout=1)
    assert stopped == [126]


def test_host_installer_cleanup_rejects_unreadable_census(tmp_path, monkeypatch):
    node, npm_cli, frontend = _direct_installer_fixture(tmp_path)
    contract = release._host_installer_contract(frontend)
    monkeypatch.setattr(
        release,
        "_host_installer_descendant_records",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("census unreadable")),
    )
    monkeypatch.setattr(release, "_monotonic_now", lambda: 0.0)
    with pytest.raises(RuntimeError, match="census unreadable"):
        release._cleanup_host_installer_resources(
            type("Process", (), {"pid": 124})(), contract, frontend_root=frontend
        )
