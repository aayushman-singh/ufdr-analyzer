"""CiteSpan release hooks for the Jarvis DeploymentProvider contract.

Each command reads one JSON object from standard input and writes one JSON
object to standard output. Errors are logged to standard error and return a
non-zero exit code. No secret value is printed.
"""

from __future__ import annotations

import argparse
import ast
import base64
import codecs
import ctypes
import errno
import hashlib
import json
import ntpath
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import sysconfig
import tempfile
import time
import traceback
import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
# Host evidence stays bound to the script-relative checkout. Dependency tests
# may patch ROOT without changing this contract.
SCRIPT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
PYTHON_PLAYWRIGHT_VERSION = "1.55.0"
PYTHON_PLAYWRIGHT_WHEEL = "playwright-1.55.0-py3-none-win_amd64.whl"
PYTHON_PLAYWRIGHT_WHEEL_SHA256 = (
    "7eb5956473ca1951abb51537e6a0da55257bb2e25fc37c2b75af094a5c93736c"
)
PYTHON_PLAYWRIGHT_WHEEL_URL = (
    "https://files.pythonhosted.org/packages/46/4f/"
    "9ba607fa94bb9cee3d4beb1c7b32c16efbfc9d69d5037fa85d10cafc618b/"
    "playwright-1.55.0-py3-none-win_amd64.whl"
)
PLAYWRIGHT_BROWSERS_PATH = ROOT / ".venv" / "playwright-browsers"
AUTHENTIC_REGISTRY_METADATA = {
    ("next", "15.5.27"): (
        "https://registry.npmjs.org/next/-/next-15.5.27.tgz",
        "sha512-F82CrlPZ8GRxBH9RIIoR3qU1t5RT3dv1K8moe8SjlDEquiFipvEI13R1Om90TaUOEwShkWCMlg8+gvTNzfMhvg==",
    ),
    ("eslint-config-next", "15.5.27"): (
        "https://registry.npmjs.org/eslint-config-next/-/eslint-config-next-15.5.27.tgz",
        "sha512-SlpZ5Ch1bM+GNHxahIoCy5OVgbpIHzHoGQDjHo6vEhxvYMukWYVo++AEh9RWYaIxH1i38PO7ArzSdmTruswOew==",
    ),
    ("shell-quote", "1.12.0"): (
        "https://registry.npmjs.org/shell-quote/-/shell-quote-1.12.0.tgz",
        "sha512-PcByqNyT/38F2kDNi006HAMRJaULuBzq/FOsw3qdZvX/GA9W/jamDaRskgHjubHiftXK5sIFxLNkvrXUwcof6Q==",
    ),
    ("tar", "7.5.22"): (
        "https://registry.npmjs.org/tar/-/tar-7.5.22.tgz",
        "sha512-MFO/QzvtAOmJbkhOaCTvbGcFN9L9b+JunIsDwaKljSOdcLMea3NJ1k9Usz/rjdfSXTq4dfzfeS7W4p4YOAAHeA==",
    ),
}
SSH_KEY = Path.home() / ".ssh" / "everything"
SSH_TIMEOUT_SECONDS = 1800
PLAYWRIGHT_PROVISION_TIMEOUT_SECONDS = 900
LIVE_VERIFIER_TIMEOUT_SECONDS = 900
SUBPROCESS_DIAGNOSTIC_LIMIT = 4096
HOST_INSTALLER_CLEANUP_TIMEOUT_SECONDS = 30
LEGACY_FAMILY_SOURCE_SHA256 = "3baead04ca0457c12b7ab0aebb8b0afc834d5f371aab3cb5c12c844489548cf5"
DEPLOY_HOST = "root@169.58.64.150"
DEPLOY_PATH = "/opt/citespan"
DEPLOY_REPOSITORY = "https://github.com/aayushman-singh/ufdr-analyzer.git"
DEMO_COMPOSE = "docker-compose.demo.yml"
DEPLOY_DOMAIN = "citespan.169.58.64.150.nip.io"
AUTHORIZED_LIVE_ORIGIN = f"https://{DEPLOY_DOMAIN}"
DEPLOYMENT_METADATA = f"{DEPLOY_PATH}/.citespan-deployment.json"
DEMO_MARKER = f"{DEPLOY_PATH}/.citespan-demo-marker.json"
EXTERNAL_PROOF_ROOT = Path.home() / ".citespan" / "release-proof"
HOST_PROCESS_EVIDENCE_ROOT = Path.home() / ".citespan" / "host-process-evidence"
HOST_PROCESS_EVIDENCE_FILES = (
    "recorded-node-identities-942.json",
    "product-frontend-native-lock-932.json",
    "legacy-node-current-981.json",
    "legacy-family-current-996.json",
    "citespan-node-family-current.v1.json",
    "legacy-family-presence-1004.json",
    "current-frontend-processes-1004.json",
)
HOST_PROCESS_APPROVAL = "citespan-node-current-approval.json"
HISTORICAL_FAMILY_RELATION = "measured historical Node family identity"
WRAPPER_FAMILY_RELATION = (
    "current cmd.exe wrapper descendant of the exact observed historical Node family"
)
HOST_NATIVE_MODULE = Path(
    "frontend/node_modules/lightningcss-win32-x64-msvc/lightningcss.win32-x64-msvc.node"
)
HOST_PARENT_STATES = {
    "readable_current_parent",
    "verified_absent_parent",
    "verified_absent_historical_parent",
    "verified_exited_parent",
    "parent_exited_during_observation",
    "windows_system_parent",
    "unreadable_parent",
    "reused_parent",
    "historical_parent_exited_pid_reused",
}
_LEGACY_NODE_INVENTORY = HOST_PROCESS_EVIDENCE_FILES[0]
_LEGACY_LOCK_INVENTORY = HOST_PROCESS_EVIDENCE_FILES[1]
_OWNER_ACTOR = 7
_OWNER_GOAL = "740d01c7-2dbf-4d74-8480-3f14cf85aa48"
MINIO_SOURCE_REPOSITORY = "https://github.com/minio/minio.git"
MINIO_SOURCE_REVISION = "RELEASE.2025-10-15T17-29-55Z"
MINIO_SOURCE_COMMIT = "9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a"
MINIO_BUILDER_IMAGE = "golang:1.27.2-alpine3.24@sha256:85dc1069ac644ea3c527b177303a406eb3358192816cd7f9e5848eb658851673"
MINIO_RUNTIME_IMAGE = "alpine:3.22.6@sha256:3e9b4b680bfc9fb5269227cffbd6d42be39fbf7c0b908123913864aa4447e764"
MINIO_IMAGE = "citespan-minio-source:RELEASE.2025-10-15T17-29-55Z"
MINIO_BUILD_PROVENANCE = {
    "source_repository": MINIO_SOURCE_REPOSITORY,
    "source_tag": MINIO_SOURCE_REVISION,
    "source_commit": MINIO_SOURCE_COMMIT,
    "builder_image": MINIO_BUILDER_IMAGE,
    "runtime_image": MINIO_RUNTIME_IMAGE,
    "builder_provenance": "Docker Official Image golang:1.27.2-alpine3.24 index digest verified 2026-10-09",
    "runtime_provenance": (
        "Docker Official Image alpine:3.22.6 linux/amd64 manifest digest "
        "sha256:3e9b4b680bfc9fb5269227cffbd6d42be39fbf7c0b908123913864aa4447e764 "
        "verified from https://github.com/docker-library/repo-info/blob/master/repos/alpine/remote/3.22.6.md"
    ),
}
IMMUTABLE_SOURCE_COMMITS = {"MINIO_SOURCE_COMMIT": MINIO_SOURCE_COMMIT}
IMMUTABLE_MINIO_IMAGES = {
    "MINIO_BUILDER_IMAGE": MINIO_BUILDER_IMAGE,
    "MINIO_RUNTIME_IMAGE": MINIO_RUNTIME_IMAGE,
}


def _is_positive_pid(value: object) -> bool:
    return type(value) is int and value > 0


def _is_process_pid(value: object) -> bool:
    """Accept only positive integer PIDs and the two Windows sentinels."""
    return type(value) is int and (value > 0 or value in (0, 4))


def _is_parent_pid(value: object) -> bool:
    """Accept a measured positive parent PID or a Windows system sentinel."""
    return _is_process_pid(value)


def _canonical_windows_path_identity(value: object) -> str:
    if not isinstance(value, (str, Path)):
        raise RuntimeError("release blocked: host process evidence contains an invalid path")
    path = ntpath.normpath(str(value).replace("/", "\\"))
    if path.startswith("\\\\"):
        prefix = "//"
        path = path[2:]
    else:
        prefix = ""
    normalized = path.replace("\\", "/")
    return f"{prefix}{normalized}".casefold().rstrip("/")


def _host_path_identity(value: object) -> str:
    return _canonical_windows_path_identity(value)


def _path_is_within(path: object, root: object) -> bool:
    candidate = _canonical_windows_path_identity(path)
    boundary = _canonical_windows_path_identity(root)
    return candidate == boundary or candidate.startswith(f"{boundary}/")


def _command_contains_path(command: str, target: object) -> bool:
    target_identity = _canonical_windows_path_identity(target)
    for token in re.findall(r'"([^"]+)"|([^\s]+)', command):
        value = next(part for part in token if part)
        value = value.rstrip(",;")
        if _canonical_windows_path_identity(value) == target_identity:
            return True
    return False


def _read_host_evidence(root: Path, filename: str) -> Any:
    path = root / filename
    if not path.is_file() or path.is_symlink():
        raise RuntimeError(f"release blocked: host process evidence is missing or unsafe: {filename}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"release blocked: host process evidence cannot be read: {filename}") from exc
    return value


def _historical_evidence_error(filename: str, detail: str) -> RuntimeError:
    safe_filename = Path(str(filename)).name
    return RuntimeError(
        f"historical host process evidence invalid {safe_filename}: {detail}"
    )








def _native_fingerprint(path: Path, metadata: os.stat_result) -> tuple[object, ...]:
    """Return native-file identity fields that do not include access time."""
    return (
        _host_path_identity(path),
        stat.S_IFMT(metadata.st_mode),
        stat.S_IMODE(metadata.st_mode),
        metadata.st_size,
        getattr(metadata, "st_dev", None),
        getattr(metadata, "st_ino", None),
        getattr(metadata, "st_mtime_ns", None),
        getattr(metadata, "st_ctime_ns", None),
    )


def _native_snapshot(path: Path) -> tuple[tuple[object, ...], str]:
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise RuntimeError("release blocked: native resource state cannot be read") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError("release blocked: native resource is not a regular file")
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise RuntimeError("release blocked: native resource content cannot be read") from exc
    return _native_fingerprint(path, metadata), digest


def _prove_host_native_release() -> dict[str, str]:
    path = (SCRIPT_ROOT / HOST_NATIVE_MODULE).absolute()
    try:
        initial = os.lstat(path)
    except FileNotFoundError as exc:
        if exc.errno == errno.ENOENT:
            return {"state": "absent"}
        raise RuntimeError("release blocked: native resource state is ambiguous") from exc
    except OSError as exc:
        raise RuntimeError("release blocked: native resource state cannot be read") from exc
    if stat.S_ISLNK(initial.st_mode) or not stat.S_ISREG(initial.st_mode):
        raise RuntimeError("release blocked: native resource is not a regular file")
    replacement = path.with_name(path.name + ".citespan-release-proof")
    if replacement.exists() or replacement.is_symlink():
        raise RuntimeError("release blocked: native resource proof path already exists")
    try:
        initial_fingerprint = _native_fingerprint(path, initial)
        original = path.read_bytes()
        if _native_fingerprint(path, os.lstat(path)) != initial_fingerprint:
            raise RuntimeError("native resource changed before proof")
        os.replace(path, replacement)
        os.replace(replacement, path)
        restored_fingerprint, restored_digest = _native_snapshot(path)
        if (
            restored_fingerprint != initial_fingerprint
            or restored_digest != hashlib.sha256(original).hexdigest()
        ):
            raise RuntimeError("native resource bytes or identity changed during proof")
    except (OSError, RuntimeError) as exc:
        if replacement.exists() and not path.exists():
            os.replace(replacement, path)
        raise RuntimeError("release blocked: native resource reversible proof failed") from exc
    return {"state": "restored"}


def _observe_host_native_resource() -> dict[str, Any]:
    """Read the native resource state without changing the host."""
    path = (SCRIPT_ROOT / HOST_NATIVE_MODULE).absolute()
    try:
        metadata = os.lstat(path)
    except FileNotFoundError as exc:
        if exc.errno == errno.ENOENT:
            return {"state": "absent"}
        raise RuntimeError("release blocked: native resource state is ambiguous") from exc
    except OSError as exc:
        raise RuntimeError("release blocked: native resource state cannot be read") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError("release blocked: native resource is not a regular file")
    fingerprint, digest = _native_snapshot(path)
    return {"state": "present", "fingerprint": fingerprint, "sha256": digest}


def _legacy_evidence_records(value, label):
    safe_label = Path(str(label)).name
    if not isinstance(value, list) or not value:
        raise _historical_evidence_error(safe_label, "expected a non-empty list")
    normalized = []
    seen = set()
    for record in value:
        if not isinstance(record, dict):
            raise _historical_evidence_error(safe_label, "each item must be an object")
        identity = record.get("identity")
        if not isinstance(identity, dict):
            raise _historical_evidence_error(safe_label, "identity object is required")
        pid = identity.get("pid")
        creation = identity.get("creation_token")
        if not _is_positive_pid(pid):
            raise _historical_evidence_error(safe_label, "identity.pid is required")
        if not isinstance(creation, str) or not creation:
            raise _historical_evidence_error(
                safe_label, f"identity.creation_token is required: pid={pid}"
            )
        key = (pid, creation)
        if key in seen:
            raise _historical_evidence_error(
                safe_label, f"duplicate identity: pid={pid}"
            )
        seen.add(key)
        parent = record.get("parent")
        if isinstance(parent, dict):
            parent_pid = parent.get("pid")
        else:
            parent_pid = parent
        if label == _LEGACY_LOCK_INVENTORY and not _is_positive_pid(parent_pid):
            raise _historical_evidence_error(
                safe_label, f"parent is required: pid={pid} field=parent"
            )
        normalized.append(
            {
                **record,
                "pid": pid,
                "creation": creation,
                "historical_parent": parent,
            }
        )
        if _is_positive_pid(parent_pid):
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
    if _host_path_identity(value.get("product_worktree", "")) != _host_path_identity(str(SCRIPT_ROOT)):
        raise RuntimeError(f"current evidence contract approval has the wrong product worktree: {label}")
    observed_ids = value.get("observed_identity_pids")
    if not isinstance(observed_ids, list) or any(not _is_positive_pid(pid) for pid in observed_ids):
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
                or not _is_positive_pid(exclusion.get("pid"))
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
        if not isinstance(record, dict) or not _is_positive_pid(record.get("pid")):
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
            native_path = (SCRIPT_ROOT / HOST_NATIVE_MODULE).resolve()
            native_files = []
            for value in record["files"]:
                candidate_path = Path(value)
                if not candidate_path.is_absolute() and candidate_path.as_posix() == HOST_NATIVE_MODULE.as_posix():
                    native_files.append(candidate_path)
                elif candidate_path.is_absolute() and _host_path_identity(candidate_path) == _host_path_identity(native_path):
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
            if not isinstance(observation, dict) or observation.get("state") not in HOST_PARENT_STATES:
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

def _current_family_records(value, label, raw_value=None):
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
    raw_by_identity = None
    if raw_value is not None:
        raw_records = _legacy_family_observation_records(raw_value, "legacy-family-current-996.json")
        raw_by_identity = {}
        for raw_record in raw_records:
            raw_identity = (
                _legacy_identity_value(raw_record, "pid", ("pid",), required=True),
                _legacy_identity_value(raw_record, "creation", ("creation", "creation_token"), required=True),
            )
            if raw_identity in raw_by_identity:
                raise RuntimeError(
                    f"current family evidence duplicates raw identity: pid={raw_identity[0]}"
                )
            raw_by_identity[raw_identity] = raw_record
    normalized = []
    seen = set()
    for record in records:
        if not isinstance(record, dict) or not _is_positive_pid(record.get("pid")):
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
        expected_argv_hash = hashlib.sha256("\0".join(record["argv"]).encode("utf-8")).hexdigest()
        if record["argv_sha256"] != expected_argv_hash:
            raise RuntimeError(
                f"current family evidence hash mismatch: pid={record['pid']} field=argv_sha256"
            )
        if not isinstance(record["native_command_sha256"], str) or re.fullmatch(
            r"[0-9a-f]{64}", record["native_command_sha256"]
        ) is None:
            raise RuntimeError(
                f"current family evidence has invalid native command hash: pid={record['pid']}"
            )
        if not _is_parent_pid(record["parent_pid"]):
            raise RuntimeError(f"current family evidence has invalid parent pid: pid={record['pid']}")
        if any(
            not isinstance(port, int) or isinstance(port, bool) or port <= 0
            for port in record["ports"]
        ):
            raise RuntimeError(f"current family evidence has invalid ports: pid={record['pid']}")
        for field in ("files", "ports"):
            if not isinstance(record[field], list):
                raise RuntimeError(f"current family evidence has invalid {field}: pid={record['pid']}")
        if not isinstance(record["parent_observations"], list) or not record["parent_observations"]:
            raise RuntimeError(
                f"current family evidence has incomplete parent observations: pid={record['pid']}"
            )
        if raw_by_identity is not None:
            raw = raw_by_identity.get((record["pid"], record["creation"]))
            if raw is None:
                raise RuntimeError(
                    f"current family evidence has no immutable raw counterpart: pid={record['pid']}"
                )
            raw_canonical = _legacy_family_record_canonical(raw, record)
            _assert_legacy_family_matches_normalized(raw, record)
            for field in (
                "pid", "creation", "parent_pid", "cwd", "executable", "argv", "argv_sha256",
                "native_command_sha256", "module_paths", "files", "ports",
            ):
                actual = record[field]
                if field in {"module_paths", "files"}:
                    actual = _canonical_path_values(actual, field, record["pid"])
                if field == "ports":
                    actual = sorted(actual)
                if actual != raw_canonical[field]:
                    raise RuntimeError(
                        f"current family evidence disagrees with immutable raw observation: "
                        f"pid={record['pid']} field={field}"
                    )
            if record["role"] != raw_canonical["role"]:
                raise RuntimeError(
                    f"current family evidence disagrees with immutable raw observation: pid={record['pid']} field=role"
                )
            if record["family_relation"] != raw_canonical["family_relation"]:
                raise RuntimeError(
                    f"current family evidence disagrees with immutable raw observation: pid={record['pid']} field=family_relation"
                )
        normalized.append(record)
    if sum(record.get("role") == "lightningcss_loader" for record in normalized) != 29:
        raise RuntimeError("current family evidence must contain 29 lightningcss loaders")
    if sum(record.get("role") == "related_test_family" for record in normalized) != 116:
        raise RuntimeError("current family evidence must contain 116 related family identities")
    if sum(record["family_relation"] == HISTORICAL_FAMILY_RELATION for record in normalized) != 116:
        raise RuntimeError(
            "current family evidence must contain 116 measured historical Node family identities"
        )
    if sum(record["family_relation"] == WRAPPER_FAMILY_RELATION for record in normalized) != 29:
        raise RuntimeError(
            "current family evidence must contain 29 current cmd.exe wrapper descendants"
        )
    if any(
        record["family_relation"] not in {HISTORICAL_FAMILY_RELATION, WRAPPER_FAMILY_RELATION}
        for record in normalized
    ):
        raise RuntimeError("current family evidence contains an unknown family relation")
    return normalized


def _bind_normalized_family_records(historical_records, family_records):
    """Bind normalized current identities to historical candidates by exact identity."""
    family_by_identity = {
        (record["pid"], record["creation"]): record for record in family_records
    }
    bound = []
    for historical in historical_records:
        identity = (historical["pid"], historical["creation"])
        current = family_by_identity.get(identity)
        if current is None:
            raise RuntimeError(
                "release blocked: normalized family evidence is missing historical identity: "
                f"pid={historical['pid']} creation={historical['creation']}"
            )
        if not current["parent_observations"]:
            raise RuntimeError(
                "release blocked: normalized family evidence has no parent observations: "
                f"pid={historical['pid']}"
            )
        bound.append(
            {
                **historical,
                "creation": current["creation"],
                "parent_pid": current["parent_pid"],
                "cwd": current["cwd"],
                "executable": current["executable"],
                "argv": list(current["argv"]),
                "argv_sha256": current["argv_sha256"],
                "native_command_sha256": current["native_command_sha256"],
                "module_paths": list(current["module_paths"]),
                "files": list(current["files"]),
                "ports": list(current["ports"]),
                "parent_observations": list(current["parent_observations"]),
                "role": current["role"],
                "family_relation": current["family_relation"],
                "current_modules": list(current["module_paths"]),
            }
        )
    return bound

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
        if not isinstance(record, dict) or not _is_positive_pid(record.get("pid")):
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
    return sorted(values, key=lambda value: _host_path_identity(value))

def _canonical_parent_observation(observation, pid):
    if not isinstance(observation, dict):
        raise RuntimeError(f"legacy family evidence has invalid parent observation: pid={pid}")
    identity = observation.get("identity")
    identity = identity if isinstance(identity, dict) else {}
    state = observation.get("state")
    result = {"state": state}
    if state not in HOST_PARENT_STATES:
        raise RuntimeError(f"legacy family evidence has invalid parent state: pid={pid}")
    observed_pid = observation.get("pid", identity.get("pid"))
    if "pid" in observation and "pid" in identity and observation["pid"] != identity["pid"]:
        raise RuntimeError(f"legacy family evidence has conflicting parent values: pid={pid} field=pid")
    if not _is_positive_pid(observed_pid):
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
    if not _is_parent_pid(parent_pid):
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
    result["family_relation"] = (
        HISTORICAL_FAMILY_RELATION if historical else WRAPPER_FAMILY_RELATION
    )
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
    expected_relation = actual["family_relation"]
    if normalized_record["family_relation"] != expected_relation:
        raise RuntimeError(
            f"normalized current family evidence changed immutable observation: "
            f"pid={normalized_record['pid']} field=family_relation"
        )

def _assert_family_source_provenance(legacy_document, normalized_document):
    expected = LEGACY_FAMILY_SOURCE_SHA256
    if "source_sha256" not in legacy_document:
        raise RuntimeError(
            "normalized current family evidence requires the immutable legacy source hash: "
            f"field=source_sha256 expected={expected}"
        )
    legacy_digests = {
        field: legacy_document[field]
        for field in ("source_hash", "sha256", "original_source_sha256", "source_sha256")
        if field in legacy_document
    }
    for field, value in legacy_digests.items():
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None or value != expected:
            raise RuntimeError(
                "legacy family evidence has an invalid immutable source digest: "
                f"field={field} expected={expected}"
            )
    normalized_provenance = normalized_document.get("source_provenance")
    if not isinstance(normalized_provenance, dict) or not normalized_provenance:
        raise RuntimeError("normalized current family evidence has no source provenance")
    if normalized_provenance.get("source_sha256") != expected:
        raise RuntimeError(
            "normalized current family evidence requires the immutable legacy source hash in provenance: "
            f"field=source_sha256 expected={expected}"
        )
    for field, value in legacy_digests.items():
        if normalized_provenance.get(field) != value:
            raise RuntimeError(
                f"normalized current family evidence changed source provenance: field={field}"
            )
    legacy_provenance = legacy_document.get("source_provenance")
    if legacy_provenance is not None and (
        not isinstance(legacy_provenance, dict)
        or legacy_provenance.get("source_sha256") != expected
    ):
        raise RuntimeError("legacy family evidence source provenance has an invalid source_sha256")
    if isinstance(legacy_provenance, dict):
        for field, value in legacy_provenance.items():
            if field not in normalized_provenance or normalized_provenance[field] != value:
                raise RuntimeError(
                    f"normalized current family evidence changed source provenance: field={field}"
                )


def _assert_legacy_current_observation(value: object) -> None:
    if not isinstance(value, dict):
        raise RuntimeError("release blocked: legacy current evidence must remain observation-only")
    for field in ("ownership_approved", "cleanup_approved"):
        if type(value.get(field)) is not bool or value[field] is not False:
            raise RuntimeError(
                "release blocked: legacy current evidence must contain explicit false "
                f"{field} approval"
            )


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
        if not _is_positive_pid(record["pid"]):
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

_CURRENT_IDENTITY_FIELDS = (
    "pid",
    "creation",
    "executable",
    "argv",
    "argv_sha256",
    "native_command",
    "native_command_sha256",
    "cwd",
    "parent_pid",
    "parent_observations",
    "role",
    "family_relation",
    "read_errors",
    "listening_ports",
    "source_provenance",
)


def _validate_current_identity(record, label, prefix=""):
    """Validate one measured identity, including its parent and provenance."""
    missing = [f"{prefix}{field}" for field in _CURRENT_IDENTITY_FIELDS if f"{prefix}{field}" not in record]
    if missing:
        raise RuntimeError(f"current identity evidence incomplete {label}: fields={missing}")
    pid = record[f"{prefix}pid"]
    if not _is_positive_pid(pid):
        raise RuntimeError(f"current identity evidence invalid {label}: pid is required")
    creation = record[f"{prefix}creation"]
    if not isinstance(creation, str) or not creation.strip():
        raise RuntimeError(f"current identity evidence invalid {label}: creation is required")
    for field in ("executable", "cwd", "native_command", "role", "family_relation"):
        value = record[f"{prefix}{field}"]
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"current identity evidence invalid {label}: field={prefix}{field}")
    argv = record[f"{prefix}argv"]
    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
        raise RuntimeError(f"current identity evidence invalid {label}: field={prefix}argv")
    expected_argv_hash = hashlib.sha256("\0".join(argv).encode("utf-8")).hexdigest()
    if record[f"{prefix}argv_sha256"] != expected_argv_hash:
        raise RuntimeError(f"current identity evidence hash mismatch {label}: field={prefix}argv_sha256")
    native_command = record[f"{prefix}native_command"]
    expected_command_hash = hashlib.sha256(native_command.encode("utf-8")).hexdigest()
    if record[f"{prefix}native_command_sha256"] != expected_command_hash:
        raise RuntimeError(
            f"current identity evidence hash mismatch {label}: field={prefix}native_command_sha256"
        )
    for field in ("argv_sha256", "native_command_sha256"):
        value = record[f"{prefix}{field}"]
        if not isinstance(value, str) or len(value) != 64 or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise RuntimeError(f"current identity evidence invalid {label}: field={prefix}{field}")
    parent_pid = record[f"{prefix}parent_pid"]
    if not _is_positive_pid(parent_pid):
        raise RuntimeError(f"current identity evidence invalid {label}: field={prefix}parent_pid")
    parent_observations = record[f"{prefix}parent_observations"]
    if not isinstance(parent_observations, list) or not parent_observations:
        raise RuntimeError(f"current identity evidence invalid {label}: field={prefix}parent_observations")
    for observation in parent_observations:
        if not isinstance(observation, dict) or observation.get("state") not in HOST_PARENT_STATES:
            raise RuntimeError(f"current identity evidence invalid {label}: parent relation")
        if observation.get("state") == "readable_current_parent":
            for field in (
                "pid", "creation", "parent_pid", "cwd", "executable", "argv", "argv_sha256",
                "native_command", "native_command_sha256", "relation",
            ):
                if field not in observation:
                    raise RuntimeError(
                        f"current identity evidence incomplete {label}: parent field={field}"
                    )
        if observation.get("state") == "historical_parent_exited_pid_reused":
            for field in ("current_creation", "child_creation", "current_parent_pid"):
                if field not in observation:
                    raise RuntimeError(
                        f"current identity evidence incomplete {label}: reused parent field={field}"
                    )
    read_errors = record[f"{prefix}read_errors"]
    if not isinstance(read_errors, list) or any(not isinstance(error, str) or not error.strip() for error in read_errors):
        raise RuntimeError(f"current identity evidence invalid {label}: field={prefix}read_errors")
    if read_errors:
        raise RuntimeError(f"current identity evidence has read errors {label}: {read_errors}")
    ports = record[f"{prefix}listening_ports"]
    if not isinstance(ports, list) or any(isinstance(port, bool) or not isinstance(port, int) or port <= 0 for port in ports):
        raise RuntimeError(f"current identity evidence invalid {label}: field={prefix}listening_ports")
    provenance = record[f"{prefix}source_provenance"]
    if not isinstance(provenance, dict) or not provenance:
        raise RuntimeError(f"current identity evidence invalid {label}: field={prefix}source_provenance")
    return {
        field: record[f"{prefix}{field}"]
        for field in _CURRENT_IDENTITY_FIELDS
    }


def _validate_cleanup_identity(record, label, prefix):
    identity = _validate_current_identity(record, label, prefix)
    files = record.get(f"{prefix}files")
    module_paths = record.get(f"{prefix}module_paths")
    if not isinstance(files, list) or not isinstance(module_paths, list):
        raise RuntimeError(f"current identity evidence incomplete {label}: files and module_paths are required")
    identity["files"] = files
    identity["module_paths"] = module_paths
    return identity


_VERIFIED_ABSENT_NATIVE_ERROR = 87


def _validate_absence_proof(record, expected_creation, label):
    proof = record.get("absence_proof")
    if not isinstance(proof, dict):
        raise RuntimeError(f"current cleanup evidence lacks absence proof: {label}")
    if proof.get("state") != "verified_absent":
        raise RuntimeError(f"current cleanup evidence has invalid absence proof state: {label}")
    if proof.get("pid") != record["pid"]:
        raise RuntimeError(f"current cleanup evidence absence proof PID mismatch: {label}")
    proof_creation = proof.get("expected_creation", proof.get("expected_token"))
    if proof_creation != expected_creation:
        raise RuntimeError(f"current cleanup evidence absence proof creation mismatch: {label}")
    native_error = proof.get("native_error")
    if native_error != _VERIFIED_ABSENT_NATIVE_ERROR:
        raise RuntimeError(
            f"current cleanup evidence absence proof has invalid native error: {label}"
        )
    return {
        "state": proof["state"],
        "pid": proof["pid"],
        "expected_creation": expected_creation,
        "native_error": native_error,
    }


def _current_cleanup_observation(value, label, family_records=None):
    if not isinstance(value, dict):
        raise RuntimeError(f"current cleanup evidence invalid {label}: expected an object")
    records = value.get("observations")
    if not isinstance(records, list) or not records:
        raise RuntimeError(f"current cleanup evidence invalid {label}: observations are required")
    normalized = {}
    for record in records:
        if not isinstance(record, dict) or not _is_positive_pid(record.get("pid")):
            raise RuntimeError(f"current cleanup evidence invalid {label}: each observation needs a positive pid")
        pid = record["pid"]
        if pid in normalized:
            raise RuntimeError(f"current cleanup evidence duplicates pid={pid}: {label}")
        family = None
        if family_records is not None:
            family = next((item for item in family_records if item["pid"] == record["pid"]), None)
            if family is None:
                raise RuntimeError(f"current cleanup evidence has no measured family identity: {label} pid={pid}")
        expected = record.get("expected_creation", record.get("expected_token"))
        if family is not None:
            expected = family["creation"]
            if record.get("expected_creation") != expected:
                raise RuntimeError(f"current cleanup evidence disagrees with measured family: {label} pid={pid}")
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
        if family is None:
            _validate_cleanup_identity(record, f"{label} pid={pid}", "expected_")
        if state == "absent":
            absence_proof = _validate_absence_proof(
                record, expected, f"{label} pid={pid}"
            )
        else:
            absence_proof = None
            if family is None:
                _validate_cleanup_identity(record, f"{label} pid={pid}", "current_")
                if record["current_creation"] != current:
                    raise RuntimeError(f"current cleanup evidence disagrees with current identity: {label} pid={pid}")
        normalized[pid] = {
            **record,
            **({"expected_identity": family} if family is not None else {}),
            "expected_creation": expected,
            "current_creation": current,
            "state": state,
            "absence_proof": absence_proof,
        }
    return normalized

def _current_frontend_observation(value, label):
    if not isinstance(value, dict):
        raise RuntimeError(f"current frontend evidence invalid {label}: expected an object")
    processes = value.get("product_frontend_processes", value.get("frontend_processes"))
    holders = value.get("native_module_holders")
    missing = [field for field in ("read_errors", "listening_ports") if field not in value]
    if missing:
        raise RuntimeError(
            f"current frontend evidence invalid {label}: missing required measured fields={missing}"
        )
    read_errors = value["read_errors"]
    ports = value["listening_ports"]
    if not isinstance(processes, list) or not isinstance(holders, list):
        raise RuntimeError(
            f"current frontend evidence invalid {label}: product_frontend_processes and native_module_holders are required"
        )
    if not isinstance(read_errors, list) or any(
        not isinstance(error, str) or not error.strip() for error in read_errors
    ):
        raise RuntimeError(
            f"current frontend evidence invalid {label}: read_errors must be a list of non-empty strings"
        )
    if read_errors:
        raise RuntimeError(f"current frontend evidence has read errors: {label} errors={read_errors}")
    if not isinstance(ports, list) or any(
        isinstance(port, bool) or not isinstance(port, int) or port <= 0 for port in ports
    ):
        raise RuntimeError(
            f"current frontend evidence invalid {label}: listening_ports must be a list of positive integers"
        )
    normalized_processes = []
    normalized_holders = []
    for collection, target, name in (
        (processes, normalized_processes, "product_frontend_processes"),
        (holders, normalized_holders, "native_module_holders"),
    ):
        for item in collection:
            if not isinstance(item, dict) or not _is_positive_pid(item.get("pid")):
                raise RuntimeError(
                    f"current frontend evidence has an invalid pid: evidence={label} collection={name}"
                )
            identity = _validate_current_identity(item, f"{label} field={name} pid={item['pid']}")
            files = item.get("files")
            module_paths = item.get("module_paths")
            if not isinstance(files, list) or not isinstance(module_paths, list):
                raise RuntimeError(
                    f"current frontend evidence incomplete {label}: field={name} pid={item['pid']} files/module_paths"
                )
            if sorted(identity["listening_ports"]) != sorted(ports):
                raise RuntimeError(
                    f"current frontend evidence disagrees with measured listening_ports: pid={item['pid']}"
                )
            if name == "native_module_holders":
                native_path = (SCRIPT_ROOT / HOST_NATIVE_MODULE).resolve()
                native_values = [
                    candidate
                    for candidate in files + module_paths
                    if isinstance(candidate, str)
                    and (
                        (not Path(candidate).is_absolute() and Path(candidate).as_posix() == HOST_NATIVE_MODULE.as_posix())
                        or (Path(candidate).is_absolute() and _host_path_identity(candidate) == _host_path_identity(native_path))
                    )
                ]
                if len(native_values) != 2:
                    raise RuntimeError(
                        f"current frontend evidence holder lacks exact native path/module evidence: pid={item['pid']}"
                    )
            identity["files"] = list(files)
            identity["module_paths"] = list(module_paths)
            target.append({**item, "current_identity": identity})
    return {"processes": normalized_processes, "holders": normalized_holders, "ports": ports}


def _assert_current_identity_matches_family(item, family, label):
    """Require raw current evidence to match its normalized family record."""
    for field in (
        "creation", "cwd", "executable", "argv", "argv_sha256",
        "native_command", "native_command_sha256", "parent_pid", "role", "family_relation",
        "module_paths", "files", "parent_observations", "source_provenance",
    ):
        if item[field] != family[field]:
            raise RuntimeError(
                f"release blocked: current frontend identity disagrees with normalized family: "
                f"{label} field={field}"
            )
    if sorted(item["listening_ports"]) != sorted(family["ports"]):
        raise RuntimeError(
            f"release blocked: current frontend identity disagrees with normalized family: "
            f"{label} field=listening_ports"
        )


def _derive_historical_roles(node_records, lock_records, family_records):
    """Reconcile immutable loader measurements with the normalized family."""
    if len(node_records) != 116 or len(lock_records) != 116:
        raise RuntimeError("release blocked: both historical inventories must contain 116 identities")
    node_by_identity = {(record["pid"], record["creation"]): record for record in node_records}
    lock_by_identity = {(record["pid"], record["creation"]): record for record in lock_records}
    if set(node_by_identity) != set(lock_by_identity):
        raise RuntimeError("release blocked: historical inventory identity sets differ")
    historical_family = [
        record
        for record in family_records
        if record.get("family_relation") == HISTORICAL_FAMILY_RELATION
    ]
    if len(historical_family) != 116:
        raise RuntimeError("release blocked: normalized family historical-node count is invalid")
    wrapper_family = [
        record
        for record in family_records
        if record.get("family_relation") == WRAPPER_FAMILY_RELATION
    ]
    if len(wrapper_family) != 29:
        raise RuntimeError("release blocked: normalized family wrapper count is invalid")
    if len(family_records) != 145 or len(historical_family) + len(wrapper_family) != len(family_records):
        raise RuntimeError("release blocked: normalized family relation set is invalid")
    family_by_identity = {
        (record["pid"], record["creation"]): record for record in historical_family
    }
    if set(node_by_identity) != set(family_by_identity):
        raise RuntimeError("release blocked: historical inventory does not match normalized family identities")
    native_path = (SCRIPT_ROOT / HOST_NATIVE_MODULE).resolve()
    for identity, node_record in node_by_identity.items():
        pid, _creation = identity
        lock_record = lock_by_identity[identity]
        family_record = family_by_identity[identity]
        previously_loaded = node_record.get("previously_loaded_native_module")
        lock_loaded = lock_record.get("locked_module_loaded")
        loaded_paths = lock_record.get("loaded_module_paths")
        if not isinstance(previously_loaded, bool):
            raise RuntimeError(
                f"release blocked: historical host process evidence missing measured loader flag: pid={pid}"
            )
        if not isinstance(lock_loaded, bool) or not isinstance(loaded_paths, list) or not all(
            isinstance(path, str) for path in loaded_paths
        ):
            raise RuntimeError(
                f"release blocked: historical host process evidence has invalid lock measurement: pid={pid}"
            )
        native_paths = [
            path for path in loaded_paths
            if (
                (not Path(path).is_absolute() and Path(path).as_posix() == HOST_NATIVE_MODULE.as_posix())
                or _host_path_identity(path) == _host_path_identity(native_path)
            )
        ]
        measured_loader = previously_loaded and lock_loaded and len(native_paths) == 1
        if (
            previously_loaded != lock_loaded
            or lock_loaded != bool(native_paths)
            or (lock_loaded and len(native_paths) != 1)
        ):
            raise RuntimeError(f"release blocked: historical loader flag/path disagreement: pid={pid}")
        family_role = family_record.get("role")
        if family_role not in {"lightningcss_loader", "related_test_family"}:
            raise RuntimeError(f"release blocked: normalized family role is invalid: pid={pid}")
        expected_role = "lightningcss_loader" if measured_loader else "related_test_family"
        if family_role != expected_role:
            raise RuntimeError(
                f"release blocked: historical loader role disagrees with measured family: pid={pid}"
            )
        node_record["evidence_sources"] = ["node", "lock"]
        node_record["role"] = family_role
        node_record["loaded_module_paths"] = list(loaded_paths)
    loader_identities = {
        identity
        for identity, record in node_by_identity.items()
        if record["role"] == "lightningcss_loader"
    }
    if len(loader_identities) != 29:
        raise RuntimeError("release blocked: historical inventory loader count is invalid")
    if {
        identity
        for identity, record in family_by_identity.items()
        if record["role"] == "lightningcss_loader"
    } != loader_identities:
        raise RuntimeError("release blocked: historical loader identities disagree across sources")
    if any(record.get("role") != "related_test_family" for record in wrapper_family):
        raise RuntimeError("release blocked: wrapper family role is invalid")
    return node_by_identity, lock_by_identity


def _load_host_process_contract() -> dict[str, Any]:
    """Load and reconcile the measured host evidence before release work."""
    root = HOST_PROCESS_EVIDENCE_ROOT.expanduser().resolve()
    if root == ROOT or ROOT in root.parents:
        raise RuntimeError("release blocked: host process evidence must be outside the product checkout")
    documents = {filename: _read_host_evidence(root, filename) for filename in HOST_PROCESS_EVIDENCE_FILES}
    node_records = _legacy_evidence_records(documents[_LEGACY_NODE_INVENTORY], _LEGACY_NODE_INVENTORY)
    lock_records = _legacy_evidence_records(documents[_LEGACY_LOCK_INVENTORY], _LEGACY_LOCK_INVENTORY)
    legacy_current = documents[HOST_PROCESS_EVIDENCE_FILES[2]]
    _assert_legacy_current_observation(legacy_current)
    legacy_document = documents[HOST_PROCESS_EVIDENCE_FILES[3]]
    normalized_document = documents[HOST_PROCESS_EVIDENCE_FILES[4]]
    legacy_family = _legacy_family_observation_records(legacy_document, HOST_PROCESS_EVIDENCE_FILES[3])
    family_records = _current_family_records(
        normalized_document,
        HOST_PROCESS_EVIDENCE_FILES[4],
        legacy_document,
    )
    _assert_family_source_provenance(legacy_document, normalized_document)
    presence = _current_cleanup_observation(
        documents[HOST_PROCESS_EVIDENCE_FILES[5]],
        HOST_PROCESS_EVIDENCE_FILES[5],
        family_records,
    )
    frontend = _current_frontend_observation(
        documents[HOST_PROCESS_EVIDENCE_FILES[6]],
        str(root / HOST_PROCESS_EVIDENCE_FILES[6]),
    )
    family_by_pid = {record["pid"]: record for record in family_records}
    for collection_name in ("processes", "holders"):
        for item in frontend[collection_name]:
            pid = item["pid"]
            family = family_by_pid.get(pid)
            if family is None:
                raise RuntimeError(
                    f"release blocked: current frontend identity is absent from normalized family: pid={pid}"
                )
            _assert_current_identity_matches_family(item, family, f"pid={pid}")
    legacy_by_pid = {record["pid"]: record for record in legacy_family}
    if set(legacy_by_pid) != set(family_by_pid):
        raise RuntimeError("release blocked: normalized family identity set does not match immutable observation")
    for pid, legacy_record in legacy_by_pid.items():
        _assert_legacy_family_matches_normalized(legacy_record, family_by_pid[pid])
    if set(presence) != set(family_by_pid):
        raise RuntimeError("release blocked: current presence identity set does not match measured family")
    if len(node_records) != 116 or len(lock_records) != 116:
        raise RuntimeError("release blocked: both historical inventories must contain 116 identities")
    node_by_identity, lock_by_identity = _derive_historical_roles(
        node_records, lock_records, family_records
    )
    live_exact = {pid for pid, record in presence.items() if record["state"] in {"live", "present"}}
    approval_document = None
    approval_records = []
    additional_records = []
    if live_exact:
        approval_document = _read_host_evidence(root, HOST_PROCESS_APPROVAL)
        approval_records = _current_observation_records(approval_document, HOST_PROCESS_APPROVAL)
        additional_records = _validate_additional_descendants(approval_document, HOST_PROCESS_APPROVAL)
        approval_by_pid = {record["pid"]: record for record in [*approval_records, *additional_records]}
        if set(approval_by_pid) != set(family_by_pid):
            raise RuntimeError("release blocked: approval identity set does not match measured family")
        for pid, family_record in family_by_pid.items():
            approval_record = approval_by_pid.get(pid)
            if approval_record is None:
                raise RuntimeError(f"release blocked: approval is missing measured identity: pid={pid}")
            for field in ("creation", "parent_pid", "cwd", "executable", "argv", "argv_sha256", "native_command_sha256", "role", "family_relation", "module_paths", "files", "ports", "parent_observations"):
                if approval_record.get(field) != family_record.get(field):
                    raise RuntimeError(f"release blocked: approval disagrees with measured identity: pid={pid} field={field}")
    elif any(record["state"] not in {"absent", "reused"} for record in presence.values()):
        raise RuntimeError("release blocked: current presence state is incomplete")
    node_by_pid = {record["pid"]: record for record in node_by_identity.values()}
    lock_by_pid = {record["pid"]: record for record in lock_by_identity.values()}
    bound_node_records = _bind_normalized_family_records(
        list(node_by_pid.values()), family_records
    )
    return {"root": root, "documents": documents, "node_records": bound_node_records, "lock_records": list(lock_by_pid.values()), "historical_pids": set(node_by_pid), "family_records": family_records, "presence": presence, "frontend": frontend, "live_exact": live_exact, "approval": approval_document, "approval_records": approval_records, "additional_records": additional_records}


class _FreshProcessAbsent(RuntimeError):
    """The native reader proved that a PID does not exist now."""


class _FreshProcessUnreadable(RuntimeError):
    """The native reader could not prove the state of a PID."""


@dataclass(frozen=True)
class _NativeReadState:
    """State for one native identity read.

    Callers provide this state for each read. The reader does not use shared
    mutable state to infer the expected identity or the required access level.
    """

    expected_creation: str | None = None
    limited_only: bool = False


_FRESH_STATE_TRANSITIONS = {
    "absent": frozenset({"absent", "reused", "live"}),
    "reused": frozenset({"absent", "reused", "live"}),
    "live": frozenset({"absent", "reused", "live"}),
    "present": frozenset({"absent", "reused", "live"}),
}


def _validate_fresh_replacement_identity(
    current: dict[str, Any], expected_creation: str, pid: int
) -> None:
    """Require the limited measured identity needed to prove PID reuse."""
    required = (
        "pid",
        "creation",
        "executable",
        "source_provenance",
    )
    missing = [field for field in required if field not in current]
    if missing:
        raise RuntimeError(
            f"release blocked: fresh replacement identity is incomplete: pid={pid} fields={missing}"
        )
    if current["pid"] != pid or current["creation"] == expected_creation:
        raise RuntimeError(
            f"release blocked: fresh replacement identity is not a different PID identity: pid={pid}"
        )
    if not isinstance(current["executable"], str) or not current["executable"].strip():
        raise RuntimeError(f"release blocked: fresh replacement identity has invalid executable: pid={pid}")
    if not isinstance(current["source_provenance"], dict) or not current["source_provenance"]:
        raise RuntimeError(f"release blocked: fresh replacement identity has invalid provenance: pid={pid}")


def _assert_exact_live_identity_matches_family(
    current: dict[str, Any], family: dict[str, Any], pid: int
) -> None:
    """Require the fresh exact identity to match all comparable historical fields."""
    for field in (
        "creation",
        "executable",
        "argv",
        "argv_sha256",
        "native_command",
        "native_command_sha256",
        "cwd",
        "parent_pid",
        "parent_observations",
    ):
        if current[field] != family[field]:
            raise RuntimeError(
                f"release blocked: fresh exact identity disagrees with normalized family: "
                f"pid={pid} field={field}"
            )


def _read_fresh_native_process_identity(
    pid: int,
    read_state: _NativeReadState,
    _ancestry: set[int] | None = None,
    _read_parent_observation: bool = True,
) -> dict[str, Any]:
    """Read one complete current Windows identity from one process handle."""
    if os.name != "nt":
        raise _FreshProcessUnreadable(
            f"native Windows process census is unsupported on host os={os.name!r}"
        )
    if not isinstance(read_state, _NativeReadState):
        raise _FreshProcessUnreadable(
            f"native process census received invalid read state for pid={pid}: {read_state!r}"
        )
    if not _is_positive_pid(pid):
        raise _FreshProcessUnreadable(f"native process census received invalid pid={pid!r}")

    import ctypes

    class FileTime(ctypes.Structure):
        _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]

    class UnicodeString(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_ushort),
            ("maximum_length", ctypes.c_ushort),
            ("buffer", ctypes.c_void_p),
        ]

    class ProcessBasicInformation(ctypes.Structure):
        _fields_ = [
            ("exit_status", ctypes.c_void_p),
            ("peb", ctypes.c_void_p),
            ("affinity", ctypes.c_void_p),
            ("base_priority", ctypes.c_long),
            ("process_id", ctypes.c_void_p),
            ("parent_process_id", ctypes.c_void_p),
        ]

    ancestry = set() if _ancestry is None else set(_ancestry)
    if pid in ancestry:
        raise _FreshProcessUnreadable(f"pid={pid} native ancestry cycle detected")
    ancestry.add(pid)
    pointer_size = ctypes.sizeof(ctypes.c_void_p)
    if pointer_size not in (4, 8):
        raise _FreshProcessUnreadable(
            f"pid={pid} native identity unsupported pointer size={pointer_size}"
        )

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    kernel32.GetProcessTimes.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
    ]
    kernel32.GetProcessTimes.restype = ctypes.c_int
    kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    kernel32.GetExitCodeProcess.restype = ctypes.c_int
    kernel32.QueryFullProcessImageNameW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    kernel32.QueryFullProcessImageNameW.restype = ctypes.c_int
    if not hasattr(kernel32, "IsWow64Process2"):
        raise _FreshProcessUnreadable(
            f"pid={pid} native architecture contract is unsupported: IsWow64Process2 is unavailable"
        )
    kernel32.IsWow64Process2.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_ushort),
        ctypes.POINTER(ctypes.c_ushort),
    ]
    kernel32.IsWow64Process2.restype = ctypes.c_int
    kernel32.ReadProcessMemory.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    kernel32.ReadProcessMemory.restype = ctypes.c_int
    ntdll.NtQueryInformationProcess.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    ntdll.NtQueryInformationProcess.restype = ctypes.c_long

    def read_creation_token(handle: int) -> str:
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
            raise _FreshProcessUnreadable(
                f"pid={pid} native creation read failed: WinError {ctypes.get_last_error()}"
            )
        return str((creation.high << 32) | creation.low)

    def read_executable_path(handle: int) -> str:
        executable_buffer = ctypes.create_unicode_buffer(32768)
        executable_length = ctypes.c_uint32(len(executable_buffer))
        if not kernel32.QueryFullProcessImageNameW(
            handle, 0, executable_buffer, ctypes.byref(executable_length)
        ) or not executable_length.value:
            raise _FreshProcessUnreadable(
                f"pid={pid} native executable read failed: WinError {ctypes.get_last_error()}"
            )
        executable = os.path.normcase(os.path.normpath(executable_buffer.value))
        if not executable:
            raise _FreshProcessUnreadable(f"pid={pid} native executable path is empty")
        return executable

    def read_exit_code(handle: int) -> int:
        status = ctypes.c_uint32()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(status)):
            raise _FreshProcessUnreadable(
                f"pid={pid} native exit-state read failed: WinError {ctypes.get_last_error()}"
            )
        return int(status.value)

    def read_parent_identity(handle: int) -> tuple[int, int]:
        basic = ProcessBasicInformation()
        returned = ctypes.c_ulong()
        status = ntdll.NtQueryInformationProcess(
            handle,
            0,
            ctypes.byref(basic),
            ctypes.sizeof(basic),
            ctypes.byref(returned),
        )
        process_id = int(basic.process_id or 0)
        parent_pid = int(basic.parent_process_id or 0)
        if status != 0 or process_id != pid or not _is_parent_pid(parent_pid):
            raise _FreshProcessUnreadable(
                f"pid={pid} native parent identity read failed: "
                f"status={status} returned_pid={process_id} parent_pid={parent_pid!r}"
            )
        return process_id, parent_pid

    def require_running(handle: int) -> None:
        status = read_exit_code(handle)
        if status != 259:
            raise _FreshProcessUnreadable(
                f"pid={pid} exited during native identity read: status={status}"
            )

    def read_win32_process_row_state() -> str:
        command = (
            "$rows = @(Get-CimInstance Win32_Process -Filter 'ProcessId = "
            f"{pid}'); if ($rows.Count -eq 0) {{ exit 3 }}; "
            "if ($rows.Count -gt 1) { exit 4 }; exit 0"
        )
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise _FreshProcessUnreadable(
                f"pid={pid} authoritative Win32_Process state read failed: {exc}"
            ) from exc
        if result.returncode == 3:
            return "absent"
        if result.returncode != 0:
            raise _FreshProcessUnreadable(
                f"pid={pid} authoritative Win32_Process state read failed: "
                f"rc={result.returncode} stderr={result.stderr[-1000:]}"
            )
        return "present"

    expected_creation = read_state.expected_creation
    limited_only = read_state.limited_only
    limited_handle = kernel32.OpenProcess(0x1000, 0, pid)
    if not limited_handle:
        error = ctypes.get_last_error()
        if error in (6, 87, 1168):
            raise _FreshProcessAbsent(f"pid={pid} is absent")
        raise _FreshProcessUnreadable(
            f"pid={pid} limited native identity open failed: WinError {error}"
        )
    try:
        limited_creation = read_creation_token(limited_handle)
        limited_status = read_exit_code(limited_handle)
        if limited_status != 259:
            process_row_state = read_win32_process_row_state()
            if process_row_state != "absent":
                raise _FreshProcessUnreadable(
                    f"pid={pid} exited handle contradicts authoritative Win32_Process row"
                )
            recheck_handle = kernel32.OpenProcess(0x1000, 0, pid)
            if recheck_handle:
                try:
                    recheck_creation = read_creation_token(recheck_handle)
                    recheck_status = read_exit_code(recheck_handle)
                    if recheck_status == 259:
                        if recheck_creation == expected_creation:
                            raise _FreshProcessUnreadable(
                                f"pid={pid} exited handle recheck returned the exact historical identity as live"
                            )
                        return {
                            "pid": pid,
                            "creation": recheck_creation,
                            "executable": read_executable_path(recheck_handle),
                            "source_provenance": {
                                "reader": "native limited process handle",
                                "classification": "exited handle followed by live PID reuse",
                            },
                        }
                    if recheck_creation != limited_creation:
                        raise _FreshProcessUnreadable(
                            f"pid={pid} exited handle recheck changed creation token while remaining exited"
                        )
                finally:
                    if not kernel32.CloseHandle(recheck_handle):
                        raise _FreshProcessUnreadable(
                            f"pid={pid} recheck process handle close failed: WinError {ctypes.get_last_error()}"
                        )
            return {
                "pid": pid,
                "creation": limited_creation,
                "state": "exited",
                "exit_code": limited_status,
                "expected_creation": expected_creation,
                "exit_proof": {
                    "handle_state": "exited",
                    "authoritative_win32_process": "absent",
                    "creation": limited_creation,
                },
                "source_provenance": {
                    "reader": "native limited process handle",
                    "classification": "exited terminal object",
                    "authoritative_win32_process": "absent",
                },
            }
        limited_executable = read_executable_path(limited_handle)
        if limited_only or (expected_creation is not None and limited_creation != expected_creation):
            limited_process_id, limited_parent_pid = read_parent_identity(limited_handle)
            return {
                "pid": limited_process_id,
                "creation": limited_creation,
                "executable": limited_executable,
                "parent_pid": limited_parent_pid,
                "command": None,
                "source_provenance": {"reader": "native limited process handle"},
            }
    finally:
        if not kernel32.CloseHandle(limited_handle):
            raise _FreshProcessUnreadable(
                f"pid={pid} limited native process handle close failed: WinError {ctypes.get_last_error()}"
            )

    # Only an exact creation-token match reaches this full read. No write or
    # terminate rights are used.
    rights = 0x0400 | 0x1000 | 0x0010 | 0x0040
    handle = kernel32.OpenProcess(rights, 0, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error in (6, 87, 1168):
            raise _FreshProcessAbsent(f"pid={pid} is absent")
        raise _FreshProcessUnreadable(
            f"pid={pid} full native identity open failed: WinError {error}"
        )

    def validate_native_architecture() -> None:
        process_machine = ctypes.c_ushort()
        native_machine = ctypes.c_ushort()
        if not kernel32.IsWow64Process2(
            handle, ctypes.byref(process_machine), ctypes.byref(native_machine)
        ):
            raise _FreshProcessUnreadable(
                f"pid={pid} native architecture read failed: WinError {ctypes.get_last_error()}"
            )
        if process_machine.value != 0:
            raise _FreshProcessUnreadable(
                f"pid={pid} native architecture is unsupported: wow64_machine=0x{process_machine.value:04x}"
            )
        supported_native = {0x014C} if pointer_size == 4 else {0x8664, 0xAA64}
        if native_machine.value not in supported_native:
            raise _FreshProcessUnreadable(
                f"pid={pid} native architecture is unsupported: native_machine=0x{native_machine.value:04x}"
            )
    def creation_token() -> str:
        return read_creation_token(handle)

    def read_remote(address: int, size: int) -> bytes:
        if not isinstance(address, int) or address <= 0 or size <= 0 or size > 131072:
            raise _FreshProcessUnreadable(
                f"pid={pid} native memory contract is invalid: address={address!r} size={size!r}"
            )
        buffer = (ctypes.c_ubyte * size)()
        count = ctypes.c_size_t()
        if not kernel32.ReadProcessMemory(
            handle,
            ctypes.c_void_p(address),
            ctypes.byref(buffer),
            size,
            ctypes.byref(count),
        ) or count.value != size:
            raise _FreshProcessUnreadable(
                f"pid={pid} native memory read failed: address=0x{address:x} requested={size} read={count.value}"
            )
        return bytes(buffer)

    def read_struct(address: int, struct_type):
        raw = read_remote(address, ctypes.sizeof(struct_type))
        return struct_type.from_buffer_copy(raw)

    def read_unicode(address: int, label: str) -> str:
        value = read_struct(address, UnicodeString)
        if value.length == 0 or value.length % 2 or value.length > 32768:
            raise _FreshProcessUnreadable(
                f"pid={pid} native {label} UNICODE_STRING is malformed: length={value.length}"
            )
        if not value.buffer or value.maximum_length < value.length:
            raise _FreshProcessUnreadable(
                f"pid={pid} native {label} UNICODE_STRING is malformed"
            )
        try:
            return read_remote(int(value.buffer), value.length).decode("utf-16-le")
        except UnicodeDecodeError as exc:
            raise _FreshProcessUnreadable(
                f"pid={pid} native {label} text is malformed"
            ) from exc

    try:
        validate_native_architecture()
        require_running(handle)
        initial_creation = creation_token()
        basic = ProcessBasicInformation()
        returned = ctypes.c_ulong()
        status = ntdll.NtQueryInformationProcess(
            handle,
            0,
            ctypes.byref(basic),
            ctypes.sizeof(basic),
            ctypes.byref(returned),
        )
        if status != 0 or not basic.peb:
            raise _FreshProcessUnreadable(
                f"pid={pid} native basic information failed: status={status}"
            )
        if int(basic.process_id or 0) != pid:
            raise _FreshProcessUnreadable(
                f"pid={pid} native identity changed during read: returned_pid={basic.process_id}"
            )
        parent_pid = int(basic.parent_process_id or 0)
        if not _is_parent_pid(parent_pid):
            raise _FreshProcessUnreadable(f"pid={pid} native parent PID is invalid")

        parameters_address = int.from_bytes(
            read_remote(int(basic.peb) + (0x20 if pointer_size == 8 else 0x10), pointer_size),
            "little",
        )
        if not parameters_address:
            raise _FreshProcessUnreadable(f"pid={pid} native process parameters are unavailable")
        command_line = read_unicode(
            parameters_address + (0x70 if pointer_size == 8 else 0x40), "command line"
        )
        cwd = read_unicode(
            parameters_address + (0x38 if pointer_size == 8 else 0x24), "current directory"
        )
        argv = _windows_command_line_argv_native(command_line)
        if not argv:
            raise _FreshProcessUnreadable(f"pid={pid} native command line parsed to empty argv")

        executable = read_executable_path(handle)

        require_running(handle)
        final_creation = creation_token()
        if final_creation != initial_creation:
            raise _FreshProcessUnreadable(
                f"pid={pid} native identity changed during read: creation token changed"
            )
        return {
            "pid": pid,
            "creation": final_creation,
            "executable": executable,
            "native_command": command_line,
            "native_command_sha256": hashlib.sha256(command_line.encode("utf-8")).hexdigest(),
            "argv": argv,
            "argv_sha256": hashlib.sha256("\0".join(argv).encode("utf-8")).hexdigest(),
            "cwd": os.path.normcase(os.path.normpath(cwd)),
            "parent_pid": parent_pid,
            "parent_observations": (
                _read_fresh_parent_observation(pid, final_creation, parent_pid, ancestry)
                if _read_parent_observation
                else []
            ),
            "role": "measured current native process",
            "family_relation": "measured current native process identity",
            "module_paths": [],
            "files": [],
            "ports": [],
            "read_errors": [],
            "listening_ports": [],
            "source_provenance": {"reader": "native process handle"},
        }
    finally:
        if not kernel32.CloseHandle(handle):
            raise _FreshProcessUnreadable(
                f"pid={pid} native process handle close failed: WinError {ctypes.get_last_error()}"
            )


def _windows_command_line_argv_native(command_line: str) -> list[str]:
    """Parse native command text without changing the serialized command."""
    if not isinstance(command_line, str) or not command_line:
        raise _FreshProcessUnreadable("native command line is empty")
    import ctypes

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.CommandLineToArgvW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_int),
    ]
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    count = ctypes.c_int()
    values = shell32.CommandLineToArgvW(command_line, ctypes.byref(count))
    if not values or count.value <= 0:
        raise _FreshProcessUnreadable(
            f"native command line parsing failed: WinError {ctypes.get_last_error()}"
        )
    try:
        return [values[index] for index in range(count.value)]
    finally:
        ctypes.windll.kernel32.LocalFree(values)


def _read_fresh_parent_observation(
    child_pid: int, child_creation: str, parent_pid: int, ancestry: set[int]
) -> list[dict[str, Any]]:
    """Bind two parent reads before using any live-only parent fields."""

    def validate_exit_proof(result: dict[str, Any], read_stage: str, creation: str) -> None:
        proof = result.get("exit_proof")
        provenance = result.get("source_provenance")
        if not isinstance(result.get("exit_code"), int) or isinstance(result.get("exit_code"), bool):
            raise _FreshProcessUnreadable(
                f"child_pid={child_pid} parent_pid={parent_pid} read_stage={read_stage} "
                f"exited parent lacks authoritative exit code: exit_code={result.get('exit_code')!r}"
            )
        if result["exit_code"] == 259:
            raise _FreshProcessUnreadable(
                f"child_pid={child_pid} parent_pid={parent_pid} read_stage={read_stage} "
                "exited parent has contradictory active status: "
                f"exit_code=259 evidence={result!r}"
            )
        if not isinstance(proof, dict) or proof.get("handle_state") != "exited":
            raise _FreshProcessUnreadable(
                f"child_pid={child_pid} parent_pid={parent_pid} read_stage={read_stage} "
                f"exited parent lacks authoritative exit proof: proof={proof!r}"
            )
        if proof.get("authoritative_win32_process") != "absent" or proof.get("creation") != creation:
            raise _FreshProcessUnreadable(
                f"child_pid={child_pid} parent_pid={parent_pid} read_stage={read_stage} "
                f"exited parent proof is incomplete or contradictory: proof={proof!r}"
            )
        if not isinstance(provenance, dict) or provenance.get("authoritative_win32_process") != "absent":
            raise _FreshProcessUnreadable(
                f"child_pid={child_pid} parent_pid={parent_pid} read_stage={read_stage} "
                f"exited parent provenance is incomplete or contradictory: provenance={provenance!r}"
            )

    def classify(result: object, read_stage: str) -> tuple[str, str]:
        if not isinstance(result, dict):
            raise _FreshProcessUnreadable(
                f"child_pid={child_pid} parent_pid={parent_pid} read_stage={read_stage} "
                f"native parent result is not an object: {result!r}"
            )
        observed_pid = result.get("pid")
        creation = result.get("creation")
        if type(observed_pid) is not int or observed_pid != parent_pid:
            raise _FreshProcessUnreadable(
                f"child_pid={child_pid} parent_pid={parent_pid} read_stage={read_stage} "
                f"native parent PID is invalid: observed_pid={observed_pid!r}"
            )
        if not isinstance(creation, str) or not creation:
            raise _FreshProcessUnreadable(
                f"child_pid={child_pid} parent_pid={parent_pid} read_stage={read_stage} "
                f"native parent creation token is invalid: creation={creation!r}"
            )
        state = result.get("state")
        if state == "exited":
            validate_exit_proof(result, read_stage, creation)
            live_fields = {
                "parent_pid", "cwd", "executable", "argv", "argv_sha256",
                "native_command", "native_command_sha256",
            }
            contradictory = sorted(field for field in live_fields if field in result)
            if contradictory:
                raise _FreshProcessUnreadable(
                    f"child_pid={child_pid} parent_pid={parent_pid} read_stage={read_stage} "
                    f"exited parent contains live fields: {contradictory}"
                )
            return "exited", creation
        if state is not None:
            raise _FreshProcessUnreadable(
                f"child_pid={child_pid} parent_pid={parent_pid} read_stage={read_stage} "
                f"native parent state is invalid: state={state!r}"
            )
        return "live", creation

    def raise_read_failure(read_stage: str, exc: BaseException) -> None:
        raise _FreshProcessUnreadable(
            f"child_pid={child_pid} parent_pid={parent_pid} read_stage={read_stage} "
            f"native parent relation read failed: {exc}"
        ) from exc

    def reused_observation(creation: str) -> list[dict[str, Any]]:
        return [
            {
                "pid": parent_pid,
                "state": "historical_parent_exited_pid_reused",
                "current_creation": creation,
                "child_creation": child_creation,
                "current_parent_pid": parent_pid,
            }
        ]

    if not _is_parent_pid(parent_pid):
        raise _FreshProcessUnreadable(
            f"child_pid={child_pid} parent_pid={parent_pid!r} read_stage=before-read "
            "native parent PID is invalid"
        )
    if parent_pid in (0, 4):
        return [{"pid": parent_pid, "state": "windows_system_parent"}]
    if parent_pid in ancestry or parent_pid == child_pid:
        raise _FreshProcessUnreadable(
            f"child_pid={child_pid} parent_pid={parent_pid} read_stage=before-read "
            "native ancestry cycle detected"
        )
    try:
        first = _read_fresh_native_process_identity(
            parent_pid,
            _NativeReadState(limited_only=True),
            ancestry,
            _read_parent_observation=False,
        )
    except _FreshProcessAbsent:
        return [{"pid": parent_pid, "state": "verified_absent_parent"}]
    except _FreshProcessUnreadable as exc:
        raise_read_failure("first-read", exc)

    first_kind, first_creation = classify(first, "first-read")
    if first_kind == "exited":
        return [{"pid": parent_pid, "state": "verified_exited_parent", "creation": first_creation}]

    try:
        second = _read_fresh_native_process_identity(
            parent_pid,
            _NativeReadState(),
            ancestry,
            _read_parent_observation=False,
        )
    except _FreshProcessAbsent:
        return [
            {
                "pid": parent_pid,
                "state": "parent_exited_during_observation",
                "creation": first_creation,
            }
        ]
    except _FreshProcessUnreadable as exc:
        raise_read_failure("second-read", exc)

    second_kind, second_creation = classify(second, "second-read")
    if second_creation != first_creation:
        return reused_observation(second_creation)
    if second_kind == "exited":
        return [{"pid": parent_pid, "state": "verified_exited_parent", "creation": second_creation}]
    try:
        if int(second_creation) > int(child_creation):
            return reused_observation(second_creation)
    except (TypeError, ValueError) as exc:
        raise _FreshProcessUnreadable(
            f"child_pid={child_pid} parent_pid={parent_pid} read_stage=creation-order "
            f"native creation token is not numeric: child={child_creation!r} parent={second_creation!r}"
        ) from exc

    required_live_fields = (
        "parent_pid", "cwd", "executable", "argv", "argv_sha256",
        "native_command", "native_command_sha256",
    )
    missing = [field for field in required_live_fields if field not in second]
    if missing:
        raise _FreshProcessUnreadable(
            f"child_pid={child_pid} parent_pid={parent_pid} read_stage=second-read "
            f"stable live parent evidence is incomplete: fields={missing}"
        )
    if not _is_parent_pid(second["parent_pid"]):
        raise _FreshProcessUnreadable(
            f"child_pid={child_pid} parent_pid={parent_pid} read_stage=second-read "
            f"native parent-of-parent PID is invalid: parent_pid={second['parent_pid']!r}"
        )
    if not isinstance(second["cwd"], str) or not second["cwd"]:
        raise _FreshProcessUnreadable(
            f"child_pid={child_pid} parent_pid={parent_pid} read_stage=second-read "
            "native parent cwd is invalid"
        )
    if not isinstance(second["executable"], str) or not second["executable"]:
        raise _FreshProcessUnreadable(
            f"child_pid={child_pid} parent_pid={parent_pid} read_stage=second-read "
            "native parent executable is invalid"
        )
    if not isinstance(second["argv"], list) or not second["argv"] or not all(
        isinstance(argument, str) for argument in second["argv"]
    ):
        raise _FreshProcessUnreadable(
            f"child_pid={child_pid} parent_pid={parent_pid} read_stage=second-read "
            "native parent argv is invalid"
        )
    if not isinstance(second["native_command"], str) or not second["native_command"]:
        raise _FreshProcessUnreadable(
            f"child_pid={child_pid} parent_pid={parent_pid} read_stage=second-read "
            "native parent command is invalid"
        )
    if second["argv_sha256"] != hashlib.sha256("\0".join(second["argv"]).encode("utf-8")).hexdigest():
        raise _FreshProcessUnreadable(
            f"child_pid={child_pid} parent_pid={parent_pid} read_stage=second-read "
            "native parent argv hash does not match argv"
        )
    if second["native_command_sha256"] != hashlib.sha256(second["native_command"].encode("utf-8")).hexdigest():
        raise _FreshProcessUnreadable(
            f"child_pid={child_pid} parent_pid={parent_pid} read_stage=second-read "
            "native parent command hash does not match command"
        )
    if second["parent_pid"] == child_pid:
        raise _FreshProcessUnreadable(
            f"child_pid={child_pid} parent_pid={parent_pid} read_stage=second-read "
            "native ancestry cycle detected"
        )
    return [
        {
            "pid": parent_pid,
            "state": "readable_current_parent",
            "creation": second_creation,
            "parent_pid": second["parent_pid"],
            "cwd": second["cwd"],
            "executable": second["executable"],
            "argv": second["argv"],
            "argv_sha256": second["argv_sha256"],
            "native_command": second["native_command"],
            "native_command_sha256": second["native_command_sha256"],
            "relation": "current parent of exact child identity",
        }
    ]


def _enumerate_fresh_frontend_resources() -> dict[str, Any]:
    """Measure host process and socket facts for later scoped classification."""
    if os.name != "nt":
        raise RuntimeError(
            f"release blocked: fresh Windows resource census is unsupported on host os={os.name!r}"
        )
    product_root = str(ROOT.resolve()).replace("'", "''")
    command = r'''
$errors = @()
$processes = @()
$holders = @()
$productRoot = '__PRODUCT_ROOT__'
$service = Get-CimInstance Win32_Service -Filter "Name = 'JarvisBrowserService'" -ErrorAction Stop
$serviceRoot = $null
if ($service -and [int]$service.ProcessId -gt 0) {
$serviceRoot = [pscustomobject]@{pid=[int]$service.ProcessId; name='JarvisBrowserService'; path_name=[string]$service.PathName; source_provenance=@{reader='Win32_Service'}}
}
foreach ($p in @(Get-CimInstance Win32_Process)) {
  try {
    $processes += [pscustomobject]@{
      pid = [int]$p.ProcessId
      name = [string]$p.Name
      executable = [string]$p.ExecutablePath
      command = [string]$p.CommandLine
      parent_pid = [int]$p.ParentProcessId
      protected_or_unrelated_state = $null
      source_provenance = @{reader='Win32_Process'}
    }
  } catch {
    $errors += "pid=$($p.ProcessId) process-read=$($_.Exception.Message)"
  }
}
$scopedCandidates = @($processes | Where-Object {
  $_.command -and ($_.command -like "*$productRoot*" -or $_.executable -like "*$productRoot*")
})
foreach ($candidate in $scopedCandidates) {
  try {
    $modules = @(Get-Process -Id $candidate.pid -Module -ErrorAction Stop | ForEach-Object {$_.FileName})
    $holders += [pscustomobject]@{pid=[int]$candidate.pid; module_paths=$modules; source_provenance=@{reader='Process.Modules'; scope='exact product root'}}
  } catch {
    $errors += "pid=$($candidate.pid) module-read=$($_.Exception.Message)"
  }
}
$ports = @(Get-NetTCPConnection -State Listen -ErrorAction Stop | ForEach-Object {[pscustomobject]@{port=[int]$_.LocalPort; pid=[int]$_.OwningProcess}})
[pscustomobject]@{processes=$processes; holders=$holders; ports=$ports; protected_service=$serviceRoot; read_errors=$errors} | ConvertTo-Json -Compress -Depth 8
'''
    command = command.replace("__PRODUCT_ROOT__", product_root)
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"release blocked: fresh resource census failed: {exc}") from exc
    if result.returncode != 0:
        raise RuntimeError(
            "release blocked: fresh resource census failed: "
            f"rc={result.returncode} stderr={result.stderr[-1000:]}"
        )
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("release blocked: fresh resource census returned malformed JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError("release blocked: fresh resource census returned a non-object")
    return value


def _configured_product_ports() -> set[int]:
    """Return only historical and current CiteSpan service ports."""
    ports = {3000, 8000}
    for name in ("CITESPAN_FRONTEND_PORT", "CITESPAN_BACKEND_PORT"):
        value = os.environ.get(name)
        if value is not None:
            try:
                port = int(value)
            except ValueError as exc:
                raise RuntimeError(f"release blocked: configured product port is invalid: {name}") from exc
            if not 1 <= port <= 65535:
                raise RuntimeError(f"release blocked: configured product port is out of range: {name}")
            ports.add(port)
    return ports


def _resource_process_is_relevant(
    item: dict[str, Any],
    product_root: str,
    *,
    identity: dict[str, Any] | None = None,
) -> bool:
    """Classify one process from one complete fresh identity and row."""
    if not isinstance(item, dict):
        raise RuntimeError(
            "release blocked: fresh process relevance is unreadable: row is not an object"
        )
    pid = item.get("pid")
    if type(pid) is int and pid in (0, 4):
        return False
    if not _is_positive_pid(pid):
        raise RuntimeError(
            "release blocked: fresh process relevance is unreadable: "
            f"pid={pid!r} has an invalid non-system PID"
        )
    nested_identity = item.get("current_identity")
    if nested_identity is not None:
        if not isinstance(nested_identity, dict):
            raise RuntimeError(
                "release blocked: fresh process relevance is unreadable: "
                f"pid={pid} current_identity is not an object"
            )
        if not _is_positive_pid(nested_identity.get("pid")) or nested_identity.get("pid") != pid:
            raise RuntimeError(
                "release blocked: fresh process relevance has conflicting PIDs: "
                f"row_pid={pid} identity_pid={nested_identity.get('pid')!r}"
            )
        if identity is None:
            identity = nested_identity
    if not isinstance(identity, dict):
        raise RuntimeError(
            "release blocked: fresh process relevance is unreadable: "
            f"pid={pid} current identity is missing"
        )
    required_identity_fields = (
        "pid",
        "creation",
        "parent_pid",
        "cwd",
        "executable",
        "native_command",
        "argv",
        "argv_sha256",
        "native_command_sha256",
        "parent_observations",
        "module_paths",
        "files",
        "ports",
    )
    missing = [field for field in required_identity_fields if field not in identity]
    if missing:
        raise RuntimeError(
            "release blocked: fresh process relevance is unreadable: "
            f"pid={pid} identity fields={missing}"
        )
    if not _is_positive_pid(identity.get("pid")) or identity.get("pid") != pid or not identity.get("creation"):
        raise RuntimeError(
            "release blocked: fresh process relevance identity does not match the census row: "
            f"pid={pid} identity_pid={identity.get('pid')!r}"
        )
    if not isinstance(identity["argv"], list) or not identity["argv"] or not all(
        isinstance(value, str) and value for value in identity["argv"]
    ):
        raise RuntimeError(
            "release blocked: fresh process relevance has an invalid parsed argv: "
            f"pid={pid}"
        )
    if not isinstance(identity.get("native_command"), str) or not identity["native_command"]:
        raise RuntimeError(
            "release blocked: fresh process relevance has an invalid native command: "
            f"pid={pid}"
        )
    if identity["argv_sha256"] != hashlib.sha256("\0".join(identity["argv"]).encode("utf-8")).hexdigest():
        raise RuntimeError(
            "release blocked: fresh process relevance parsed argv hash does not match: "
            f"pid={pid}"
        )
    if identity["native_command_sha256"] != hashlib.sha256(identity["native_command"].encode("utf-8")).hexdigest():
        raise RuntimeError(
            "release blocked: fresh process relevance native command hash does not match: "
            f"pid={pid}"
        )
    if not isinstance(identity["parent_observations"], list) or not identity["parent_observations"]:
        raise RuntimeError(
            "release blocked: fresh process relevance has incomplete ancestry evidence: "
            f"pid={pid}"
        )
    for field in ("module_paths", "files", "ports"):
        if not isinstance(identity[field], list):
            raise RuntimeError(
                "release blocked: fresh process relevance has invalid resource evidence: "
                f"pid={pid} field={field}"
            )
    if not _is_parent_pid(identity.get("parent_pid")):
        raise RuntimeError(
            "release blocked: fresh process relevance has an invalid parent identity: "
            f"pid={pid}"
        )
    identity_executable = Path(str(identity["executable"])).name.casefold()
    identity_cwd = str(identity["cwd"])
    identity_argv = [str(value) for value in identity["argv"]]
    name = Path(str(item.get("name") or identity_executable)).name.casefold()
    if item.get("protected_or_unrelated_state") in {"protected", "unrelated"}:
        return False
    if _identity_is_protected(identity, product_root):
        return False
    if name in {"system", "system idle process", "registry"}:
        return False
    frontend = _canonical_windows_path_identity(Path(product_root) / "frontend")
    process_types = {
        "node", "node.exe", "cmd", "cmd.exe", "npm", "npm.cmd", "npm-cli.js",
        "next", "next.cmd", "postcss", "postcss.js", "python", "python.exe",
    }
    known_type = name in process_types or identity_executable in process_types
    native_module = _host_path_identity((SCRIPT_ROOT / HOST_NATIVE_MODULE).resolve())
    module_paths = [*item.get("module_paths", []), *identity["module_paths"]]
    exact_native_module = any(
        isinstance(path, str) and _host_path_identity(path) == native_module
        for path in module_paths
    )
    if exact_native_module:
        return True
    frontend_roles = (
        Path(product_root) / "frontend" / "server.js",
        Path(product_root) / "frontend" / "node_modules" / ".bin" / "next.cmd",
        Path(product_root) / "frontend" / "node_modules" / "next" / "dist" / "bin" / "next",
    )
    has_frontend_role = any(
        _canonical_windows_path_identity(argument) == _canonical_windows_path_identity(role)
        or _command_contains_path(argument, role)
        for argument in identity_argv
        for role in frontend_roles
    )
    has_frontend_cwd = _path_is_within(identity_cwd, frontend)
    has_checked_wrapper_relation = any(
        isinstance(observation, dict)
        and observation.get("state") == "readable_current_parent"
        and observation.get("relation") == "current parent of exact child identity"
        and (
            _path_is_within(observation.get("cwd", ""), frontend)
            or any(
                _command_contains_path(str(argument), role)
                for argument in observation.get("argv", [])
                for role in frontend_roles
            )
        )
        for observation in identity["parent_observations"]
    )
    has_scoped_port = any(
        isinstance(port, int) and port in _configured_product_ports()
        for port in identity["ports"]
    ) or any(
        isinstance(port, dict)
        and port.get("port") in _configured_product_ports()
        for port in item.get("ports", [])
    )
    if known_type and not name.startswith("python") and (
        (has_frontend_role and has_frontend_cwd) or has_checked_wrapper_relation or has_scoped_port
    ):
        return True
    if known_type and name.startswith("python"):
        if _path_is_within(identity_cwd, product_root) or any(
            _path_is_within(argument, product_root) for argument in identity_argv[1:]
        ):
            raise RuntimeError(
                "release blocked: unprotected product-root process remains: "
                f"pid={pid} executable={identity['executable']!r} cwd={identity_cwd!r}"
            )
        return False
    if known_type:
        return False
    if _path_is_within(identity_cwd, product_root) or _path_is_within(identity["executable"], product_root):
        raise RuntimeError(
            "release blocked: unprotected product-root process remains: "
            f"pid={pid} executable={identity['executable']!r} cwd={identity_cwd!r}"
        )
    return False


def _identity_is_protected(identity: dict[str, Any], product_root: str) -> bool:
    """Recognize the current gate and observation process family from identity data."""
    executable = Path(str(identity.get("executable") or "")).name.casefold()
    command = str(identity.get("native_command") or "").casefold()
    argv = " ".join(str(value) for value in identity.get("argv", [])).casefold()
    cwd = identity.get("cwd")
    if not cwd or not _path_is_within(cwd, product_root):
        return False
    if executable not in {"python", "python.exe", "cmd", "cmd.exe", "node", "node.exe"}:
        return False
    protected_markers = (
        "pytest",
        "runpy",
        "scripts/release.py",
        "scripts/verify_live.py",
        "scripts/tests/",
        "backend/tests/",
        "controller",
        "observation",
        "acceptance",
    )
    if any(marker in command or marker in argv for marker in protected_markers):
        return True
    for observation in identity.get("parent_observations", []):
        if isinstance(observation, dict) and any(
            marker in str(observation.get(field) or "").casefold()
            for field in ("native_command", "cwd", "executable")
            for marker in protected_markers
        ):
            return True
    return False


def _fresh_process_row_needs_identity(
    item: dict[str, Any],
    *,
    native_holder_pids: set[int],
    scoped_port_owner_pids: set[int],
    protected_pids: set[int],
) -> tuple[bool, str]:
    """Select rows for full identity reads from measured current evidence."""
    pid = item.get("pid")
    if type(pid) is int and pid in (0, 4):
        return False, "Windows system sentinel"
    if not _is_positive_pid(pid):
        raise RuntimeError("release blocked: fresh process relevance has an invalid PID")
    parent_pid = item.get("parent_pid")
    if not _is_parent_pid(parent_pid):
        raise RuntimeError(
            "release blocked: fresh process relevance has an invalid or missing parent PID: "
            f"pid={pid} parent_pid={parent_pid!r}"
        )
    if pid in native_holder_pids:
        return True, "exact native-module holder"
    if pid in scoped_port_owner_pids:
        return True, "scoped listening-port owner"
    if pid in protected_pids:
        return False, "verified protected ancestry"
    if item.get("protected_or_unrelated_state") in {"protected", "unrelated"}:
        return False, "explicit row classification"
    if item.get("parent_pid") in protected_pids:
        return True, "protected ancestry"

    name = Path(str(item.get("name") or "")).name.casefold()
    executable = Path(str(item.get("executable") or "")).name.casefold()
    supported_family = {
        "node", "node.exe", "cmd", "cmd.exe", "npm", "npm.cmd", "npm-cli.js",
        "next", "next.cmd", "postcss", "postcss.js",
    }
    if name not in supported_family and executable not in supported_family:
        return False, "outside measured frontend process family"

    return True, "measured frontend-family candidate"


def _resource_port_records(value: list[Any]) -> list[tuple[int, int | None]]:
    """Normalize scoped socket rows while preserving owner identity."""
    normalized = []
    for item in value:
        if isinstance(item, bool):
            raise RuntimeError("release blocked: fresh listening port measurement is invalid")
        if isinstance(item, int):
            if item <= 0:
                raise RuntimeError("release blocked: fresh listening port measurement is invalid")
            normalized.append((item, None))
            continue
        if not isinstance(item, dict) or type(item.get("port")) is not int or item["port"] <= 0:
            raise RuntimeError("release blocked: fresh listening port ownership is unreadable")
        owner = item.get("pid")
        if type(owner) is not int or owner <= 0:
            raise RuntimeError(
                f"release blocked: fresh listening port owner is unreadable: port={item.get('port')}"
            )
        normalized.append((item["port"], owner))
    return normalized


def _read_current_protected_process_metadata(pid: int) -> dict[str, Any]:
    """Read the current process row used to bind protected ancestry."""
    if type(pid) is not int or pid <= 0:
        raise RuntimeError(f"release blocked: protected service metadata received invalid PID: pid={pid!r}")
    command = (
        "$rows = @(Get-CimInstance Win32_Process -Filter 'ProcessId = "
        f"{pid}'); if ($rows.Count -ne 1) {{ exit 3 }}; "
        "$row = $rows[0]; [pscustomobject]@{"
        "pid=[int]$row.ProcessId; parent_pid=[int]$row.ParentProcessId; "
        "executable=[string]$row.ExecutablePath; command=[string]$row.CommandLine"
        "} | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"protected service metadata read failed: pid={pid}: {exc}") from exc
    if result.returncode != 0:
        raise RuntimeError(
            "protected service metadata read failed: "
            f"pid={pid} rc={result.returncode} stderr={result.stderr[-1000:]}"
        )
    try:
        metadata = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"protected service metadata is not valid JSON: pid={pid}") from exc
    if not isinstance(metadata, dict):
        raise RuntimeError(f"protected service metadata is not an object: pid={pid}")
    required = ("pid", "parent_pid", "executable", "command")
    missing = [field for field in required if field not in metadata]
    if missing:
        raise RuntimeError(f"protected service metadata is incomplete: pid={pid} fields={missing}")
    if metadata["pid"] != pid or not _is_parent_pid(metadata["parent_pid"]):
        raise RuntimeError(
            "protected service metadata has invalid identity: "
            f"pid={pid} returned_pid={metadata['pid']!r} parent_pid={metadata['parent_pid']!r}"
        )
    if not isinstance(metadata["executable"], str) or not metadata["executable"].strip():
        raise RuntimeError(f"protected service metadata has no executable: pid={pid}")
    if not isinstance(metadata["command"], str) or not metadata["command"].strip():
        raise RuntimeError(f"protected service metadata has no command: pid={pid}")
    return metadata


def _read_current_protected_service_metadata() -> dict[str, Any]:
    """Read the current protected service name and PID from the service manager."""
    command = (
        "$service = Get-CimInstance Win32_Service -Filter \"Name = 'JarvisBrowserService'\"; "
        "if (-not $service) { exit 3 }; "
        "[pscustomobject]@{name=[string]$service.Name; pid=[int]$service.ProcessId; "
        "path_name=[string]$service.PathName} | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"protected service metadata read failed: {exc}") from exc
    if result.returncode != 0:
        raise RuntimeError(
            "protected service metadata read failed: "
            f"rc={result.returncode} stderr={result.stderr[-1000:]}"
        )
    try:
        metadata = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("protected service metadata is not valid JSON") from exc
    if (
        not isinstance(metadata, dict)
        or metadata.get("name") != "JarvisBrowserService"
        or not _is_positive_pid(metadata.get("pid"))
    ):
        raise RuntimeError(f"protected service metadata is invalid: {metadata!r}")
    return metadata


def _protected_service_path_diagnostic(value: object) -> str:
    """Return a bounded path identity for a protected-service error."""
    if not isinstance(value, str) or not value.strip():
        return "<missing>"
    identity = _canonical_windows_path_identity(value)
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    return f"<redacted:{digest}>"


def _bind_verified_protected_service(
    resources: dict[str, Any],
    process_rows_by_pid: dict[int, dict[str, Any]],
    identities: dict[int, dict[str, Any]],
) -> set[int]:
    """Bind service protection to current identities and measured parent relations."""
    service = resources.get("protected_service")
    if service is None:
        return set()
    if not isinstance(service, dict) or service.get("name") != "JarvisBrowserService":
        raise RuntimeError("release blocked: protected service evidence is invalid")
    root_pid = service.get("pid")
    if not _is_positive_pid(root_pid):
        raise RuntimeError("release blocked: protected service evidence has an invalid root PID")
    root_row = process_rows_by_pid.get(root_pid)
    if root_row is None:
        raise RuntimeError(
            f"release blocked: protected service root is absent from the current process census: pid={root_pid}"
        )

    def bind(pid: int, label: str) -> dict[str, Any]:
        row = process_rows_by_pid.get(pid)
        if row is None:
            raise RuntimeError(f"release blocked: protected service relation is missing: {label} pid={pid}")
        service_metadata = None
        try:
            read_state = _NativeReadState(limited_only=True)
            first = _read_fresh_native_process_identity(pid, read_state)
            metadata = _read_current_protected_process_metadata(pid)
            missing_metadata = [
                field for field in ("pid", "parent_pid", "executable", "command")
                if field not in metadata
            ]
            if missing_metadata:
                raise RuntimeError(
                    "release blocked: protected service metadata is incomplete: "
                    f"step={label} pid={pid} fields={missing_metadata}"
                )
            if metadata["pid"] != pid or not _is_parent_pid(metadata["parent_pid"]):
                raise RuntimeError(
                    "release blocked: protected service metadata has invalid identity: "
                    f"step={label} pid={pid} returned_pid={metadata.get('pid')!r} "
                    f"parent_pid={metadata.get('parent_pid')!r}"
                )
            if label == "root":
                service_metadata = _read_current_protected_service_metadata()
                if service_metadata["pid"] != pid:
                    raise RuntimeError(
                        "release blocked: protected service root changed during binding: "
                        f"expected_pid={pid} actual_pid={service_metadata['pid']}"
                    )
            second = _read_fresh_native_process_identity(pid, read_state)
        except (_FreshProcessAbsent, _FreshProcessUnreadable, RuntimeError) as exc:
            raise RuntimeError(
                f"release blocked: protected service identity is unreadable: {label} pid={pid}: {exc}"
            ) from exc
        if not isinstance(first, dict) or not isinstance(second, dict):
            raise RuntimeError(f"release blocked: protected service identity is unreadable: {label} pid={pid}")
        if first.get("pid") != pid or second.get("pid") != pid:
            raise RuntimeError(f"release blocked: protected service identity does not match: {label} pid={pid}")
        if first.get("creation") != second.get("creation"):
            raise RuntimeError(
                f"release blocked: protected service identity changed during binding: {label} pid={pid}"
            )
        row_parent_pid = metadata["parent_pid"]
        for read_number, identity in (("before", first), ("after", second)):
            native_executable = identity.get("executable")
            process_executable = metadata.get("executable")
            if not isinstance(native_executable, str) or not native_executable.strip():
                raise RuntimeError(
                    "release blocked: protected service native executable is unreadable: "
                    f"step={label} read={read_number} pid={pid} "
                    f"native_executable={_protected_service_path_diagnostic(native_executable)} "
                    f"process_executable={_protected_service_path_diagnostic(process_executable)} "
                    f"service_path_name={_protected_service_path_diagnostic((service_metadata or {}).get('path_name'))}"
                )
            if not isinstance(process_executable, str) or not process_executable.strip():
                raise RuntimeError(
                    "release blocked: protected service process executable is unreadable: "
                    f"step={label} read={read_number} pid={pid} "
                    f"native_executable={_protected_service_path_diagnostic(native_executable)} "
                    f"process_executable={_protected_service_path_diagnostic(process_executable)} "
                    f"service_path_name={_protected_service_path_diagnostic((service_metadata or {}).get('path_name'))}"
                )
            if _canonical_windows_path_identity(native_executable) != _canonical_windows_path_identity(process_executable):
                raise RuntimeError(
                    "release blocked: protected service executable changed during binding: "
                    f"step={label} read={read_number} pid={pid} "
                    f"native_executable={_protected_service_path_diagnostic(native_executable)} "
                    f"process_executable={_protected_service_path_diagnostic(process_executable)} "
                    f"service_path_name={_protected_service_path_diagnostic((service_metadata or {}).get('path_name'))}"
                )
            identity_parent_pid = identity.get("parent_pid")
            if not _is_parent_pid(identity_parent_pid):
                raise RuntimeError(
                    "release blocked: protected service identity has invalid parent evidence: "
                    f"step={label} read={read_number} pid={pid} parent_pid={identity_parent_pid!r}"
                )
            if identity_parent_pid != row_parent_pid:
                raise RuntimeError(
                    "release blocked: protected service parent relation changed: "
                    f"step={label} read={read_number} child_pid={pid} "
                    f"expected_parent_pid={row_parent_pid} actual_parent_pid={identity_parent_pid!r}"
                )
            identity["command"] = metadata["command"]
        current = first
        if not isinstance(current, dict) or current.get("pid") != pid:
            raise RuntimeError(f"release blocked: protected service identity does not match: {label} pid={pid}")
        if not isinstance(current.get("creation"), str) or not current["creation"]:
            raise RuntimeError(f"release blocked: protected service identity lacks creation token: pid={pid}")
        executable = first["executable"]
        command = metadata["command"]
        bound = {
            "pid": pid,
            "creation": current["creation"],
            "executable": executable,
            "command": command,
            "native_command": command,
            "parent_pid": row_parent_pid,
            "source_provenance": {
                "reader": "native limited process handle plus current CIM process row",
                "binding": label,
                "native_executable": first["executable"],
                "process_executable": metadata["executable"],
                "service_path_name": (service_metadata or {}).get("path_name"),
            },
        }
        identities[pid] = bound
        return bound

    root_identity = bind(root_pid, "root")
    protected = {root_pid}
    pending = [root_pid]
    while pending:
        parent_pid = pending.pop()
        parent_identity = identities[parent_pid]
        for pid, row in process_rows_by_pid.items():
            if pid in protected or row.get("parent_pid") != parent_pid:
                continue
            child = bind(pid, "descendant")
            if child.get("parent_pid") != parent_pid:
                raise RuntimeError(
                    "release blocked: protected service parent relation changed: "
                    f"child_pid={pid} expected_parent_pid={parent_pid} actual_parent_pid={child.get('parent_pid')!r}"
                )
            if not child.get("creation") or not parent_identity.get("creation"):
                raise RuntimeError(
                    "release blocked: protected service parent creation identity is not bound: "
                    f"child_pid={pid} parent_pid={parent_pid}"
                )
            child["parent_observations"] = [{
                "pid": parent_pid,
                "state": "readable_current_parent",
                "creation": parent_identity["creation"],
                "relation": "current CIM parent of exact protected service identity",
            }]
            identities[pid] = child
            protected.add(pid)
            pending.append(pid)
    return protected


def _fresh_resource_scope(
    resources: dict[str, Any],
    product_root: str,
    *,
    scoped_ports: set[int],
    preloaded_identities: dict[int, dict[str, Any]] | None = None,
    protected_pids: set[int] | None = None,
) -> dict[str, Any]:
    """Bind current resource rows to identities after one strict candidate pass."""
    for field in ("processes", "holders", "ports", "read_errors"):
        if not isinstance(resources.get(field), list):
            raise RuntimeError(f"release blocked: fresh resource census is incomplete: field={field}")
    if resources["read_errors"]:
        raise RuntimeError(
            f"release blocked: fresh resource census has read errors: {resources['read_errors']}"
        )
    if any(isinstance(port, bool) or type(port) is not int or port <= 0 for port in scoped_ports):
        raise RuntimeError("release blocked: scoped listening ports are invalid")

    process_rows_by_pid: dict[int, dict[str, Any]] = {}
    all_process_pids: set[int] = set()
    protected = set(protected_pids or ())
    for item in resources["processes"]:
        if not isinstance(item, dict):
            raise RuntimeError("release blocked: fresh process census contains a non-object row")
        pid = item.get("pid")
        if type(pid) is int and pid in (0, 4):
            continue
        if not _is_positive_pid(pid):
            raise RuntimeError(f"release blocked: fresh process relevance has an invalid PID: pid={pid!r}")
        nested = item.get("current_identity")
        if nested is not None and (
            not isinstance(nested, dict)
            or not _is_positive_pid(nested.get("pid"))
            or nested.get("pid") != pid
        ):
            raise RuntimeError(
                "release blocked: fresh process relevance has conflicting PIDs: "
                f"row_pid={pid} identity_pid={nested.get('pid') if isinstance(nested, dict) else nested!r}"
            )
        process_rows_by_pid[pid] = item
        all_process_pids.add(pid)
        parent_pid = item.get("parent_pid")
        if not _is_parent_pid(parent_pid):
            raise RuntimeError(
                f"release blocked: fresh process relevance has an invalid or missing parent PID: pid={pid} parent_pid={parent_pid!r}"
            )

    native_path = _host_path_identity((SCRIPT_ROOT / HOST_NATIVE_MODULE).resolve())
    native_holder_pids = set()
    for item in resources["holders"]:
        if not isinstance(item, dict) or not _is_positive_pid(item.get("pid")):
            raise RuntimeError("release blocked: fresh native holder identity is unreadable")
        module_paths = item.get("module_paths")
        if not isinstance(module_paths, list):
            raise RuntimeError(
                "release blocked: fresh resource census is unstable or unreadable; "
                f"native holder modules are unreadable: pid={item.get('pid')}"
            )
        if any(isinstance(path, str) and _host_path_identity(path) == native_path for path in module_paths):
            native_holder_pids.add(item["pid"])
    port_records = _resource_port_records(resources["ports"])
    scoped_port_owner_pids = {
        owner for port, owner in port_records if port in scoped_ports and owner is not None
    }
    identities = dict(preloaded_identities or {})
    try:
        protected.update(
            _bind_verified_protected_service(resources, process_rows_by_pid, identities)
        )
    except KeyError as exc:
        field = exc.args[0] if exc.args else "<unknown>"
        raise RuntimeError(
            "release blocked: protected service binding failed: "
            f"step=_bind_verified_protected_service field={field!r} "
            f"pids={sorted(process_rows_by_pid)}"
        ) from exc
    candidate_pids = native_holder_pids | scoped_port_owner_pids
    unrelated_exclusions = []
    for item in resources["processes"]:
        pid = item.get("pid")
        if type(pid) is int and pid in (0, 4):
            unrelated_exclusions.append({"pid": pid, "reason": "Windows system sentinel"})
            continue
        if not _is_positive_pid(pid):
            raise RuntimeError(f"release blocked: fresh process relevance has an invalid PID: pid={pid!r}")
        needs_identity, reason = _fresh_process_row_needs_identity(
            item,
            native_holder_pids=native_holder_pids,
            scoped_port_owner_pids=scoped_port_owner_pids,
            protected_pids=protected,
        )
        if not needs_identity:
            unrelated_exclusions.append({"pid": pid, "reason": reason})
            continue
        candidate_pids.add(pid)

    for pid in sorted(candidate_pids):
        if pid not in process_rows_by_pid:
            if pid in native_holder_pids:
                raise RuntimeError(
                    "release blocked: fresh resource census is unstable or unreadable; "
                    "fresh native module holder identity is unreadable: "
                    f"pid={pid}"
                )
            raise RuntimeError(
                "release blocked: fresh resource census is unstable or unreadable; "
                f"selected resource owner is absent from process census: pid={pid}"
            )
        if pid in identities and pid not in (native_holder_pids | scoped_port_owner_pids):
            identity = identities[pid]
        else:
            try:
                identity = process_rows_by_pid[pid].get("current_identity") or _read_fresh_native_process_identity(
                    pid, _NativeReadState()
                )
            except (_FreshProcessAbsent, _FreshProcessUnreadable) as exc:
                raise RuntimeError(
                    "release blocked: fresh resource census is unstable or unreadable; "
                    f"potentially relevant process identity failed: pid={pid}: {exc}"
                ) from exc
            identities[pid] = identity
        if not isinstance(identity, dict) or identity.get("pid") != pid:
            raise RuntimeError(
                "release blocked: fresh process relevance has conflicting PIDs: "
                f"row_pid={pid} identity_pid={identity.get('pid') if isinstance(identity, dict) else identity!r}"
            )
        if identity.get("parent_pid") != process_rows_by_pid[pid].get("parent_pid"):
            raise RuntimeError(
                "release blocked: fresh process relevance has conflicting parent PIDs: "
                f"pid={pid} row_parent_pid={process_rows_by_pid[pid].get('parent_pid')!r} "
                f"identity_parent_pid={identity.get('parent_pid')!r}"
            )

    relevant_processes = []
    for pid, identity in identities.items():
        item = process_rows_by_pid.get(pid)
        if item is None:
            continue
        if pid in protected and pid not in (native_holder_pids | scoped_port_owner_pids):
            protected.add(pid)
            continue
        if _resource_process_is_relevant(item, product_root, identity=identity):
            relevant_processes.append({"row": item, "identity": identity})

    holder_pids = set()
    for item in resources["holders"]:
        if not isinstance(item, dict) or not _is_positive_pid(item.get("pid")):
            raise RuntimeError("release blocked: fresh native holder identity is unreadable")
        pid = item["pid"]
        if pid in native_holder_pids:
            holder_pids.add(pid)

    port_owner_identities = {
        owner: identities[owner]
        for port, owner in port_records
        if port in scoped_ports and owner is not None and owner in identities
    }
    for port, owner in port_records:
        if port in scoped_ports:
            if owner is None or owner not in all_process_pids:
                raise RuntimeError(
                    "release blocked: fresh resource census is unstable or unreadable; "
                    f"scoped listening port owner disappeared before identity binding: port={port} pid={owner}"
                )
            if owner not in port_owner_identities:
                raise RuntimeError(
                    "release blocked: fresh resource census is unstable or unreadable; "
                    f"scoped listening port owner identity is missing: port={port} pid={owner}"
                )

    return {
        "process_rows_by_pid": process_rows_by_pid,
        "identities": identities,
        "relevant_processes": relevant_processes,
        "holder_pids": holder_pids,
        "native_holder_pids": native_holder_pids,
        "port_records": port_records,
        "port_owner_identities": port_owner_identities,
        "protected_pids": protected,
        "unrelated_exclusions": unrelated_exclusions,
        "all_process_pids": all_process_pids,
    }


def _assert_fresh_host_process_census(contract: dict[str, Any]) -> dict[str, Any]:
    """Recheck every historical identity and current release resource before work."""
    family_by_pid = {record["pid"]: record for record in contract["family_records"]}
    presence = contract["presence"]
    identities = {}
    states = {}
    replacements = {}
    terminal_states = {}
    transition_diagnostics = {}
    for pid, family in family_by_pid.items():
        saved_observation = presence[pid]
        if saved_observation.get("expected_creation") != family["creation"]:
            raise RuntimeError(
                f"release blocked: saved presence expected_creation disagrees with normalized family: pid={pid}"
            )
        try:
            current = _read_fresh_native_process_identity(
                pid, _NativeReadState(expected_creation=family["creation"])
            )
        except _FreshProcessAbsent:
            state = "absent"
        except _FreshProcessUnreadable as exc:
            raise RuntimeError(
                f"release blocked: fresh native identity census failed: pid={pid} error={exc}"
            ) from exc
        else:
            if current.get("state") == "exited":
                state = "absent"
                terminal_states[pid] = current
                if current.get("creation") == family["creation"]:
                    terminal_classification = "exited_exact_historical_object"
                else:
                    terminal_classification = "exited_replacement_object"
                transition_diagnostics[pid] = {
                    "saved_state": presence[pid]["state"],
                    "fresh_state": state,
                    "terminal_classification": terminal_classification,
                    "terminal_creation": current.get("creation"),
                    "historical_creation": family["creation"],
                }
            elif current["creation"] != family["creation"]:
                state = "reused"
                _validate_fresh_replacement_identity(current, family["creation"], pid)
                replacements[pid] = current
            else:
                state = "live"
                identities[pid] = current
                _assert_exact_live_identity_matches_family(current, family, pid)
        states[pid] = state
        saved_state = presence[pid]["state"]
        allowed_states = _FRESH_STATE_TRANSITIONS.get(saved_state)
        if allowed_states is None or state not in allowed_states:
            raise RuntimeError(
                f"release blocked: invalid saved-to-fresh presence transition: pid={pid} "
                f"saved={saved_state} fresh={state}"
            )
        if pid not in transition_diagnostics:
            transition_diagnostics[pid] = {"saved_state": saved_state, "fresh_state": state}
        if state == "live" and not contract.get("approval"):
            raise RuntimeError(
                f"release blocked: exact-live historical identity is unapproved: pid={pid}"
            )
    resources = _enumerate_fresh_frontend_resources()
    if not isinstance(resources, dict):
        raise RuntimeError("release blocked: fresh resource census returned an invalid object")
    replacement_pids = set(replacements)
    approved_live_pids = set(identities)
    approved_live_ports = {
        port
        for pid in approved_live_pids
        for port in family_by_pid[pid]["ports"]
    }
    product_root = _canonical_windows_path_identity(ROOT.resolve())
    scoped_ports = _configured_product_ports() | {
        port for family in family_by_pid.values() for port in family["ports"]
    }
    resource_scope = _fresh_resource_scope(
        resources,
        product_root,
        scoped_ports=scoped_ports,
        preloaded_identities={**replacements, **identities},
    )
    relevant_processes = [entry["row"] for entry in resource_scope["relevant_processes"]]
    protected_pids = resource_scope["protected_pids"]
    unrelated_exclusions = resource_scope["unrelated_exclusions"]
    all_process_pids = resource_scope["all_process_pids"]
    holder_pids = resource_scope["holder_pids"]
    port_records = resource_scope["port_records"]
    port_owner_identities = resource_scope["port_owner_identities"]
    measured_holder_pids = {
        item["pid"] for item in resources["holders"] if isinstance(item, dict) and _is_positive_pid(item.get("pid"))
    }
    measured_ports = {port for port, _owner in port_records if port in scoped_ports}
    for pid, identity in identities.items():
        family = family_by_pid[pid]
        if pid not in all_process_pids:
            raise RuntimeError(
                f"release blocked: exact-live identity is absent from fresh resource census: pid={pid}"
            )
        if not set(family["ports"]).issubset(measured_ports):
            raise RuntimeError(
                f"release blocked: exact-live identity resource ports disagree: pid={pid}"
            )
        if (family["files"] or family["module_paths"]) and pid not in measured_holder_pids:
            raise RuntimeError(
                f"release blocked: exact-live native module resource is absent: pid={pid}"
            )
    selected_processes = [
        item
        for item in relevant_processes
        if item["pid"] not in replacement_pids
        and item["pid"] not in protected_pids
        and item["pid"] not in approved_live_pids
    ]
    selected_holders = [
        item for item in resources["holders"]
        if isinstance(item, dict)
        and item.get("pid") in holder_pids
        and item.get("pid") not in replacement_pids
        and item.get("pid") not in approved_live_pids
    ]
    selected_ports = [
        {"port": port, "pid": owner}
        for port, owner in port_records
        if port in scoped_ports
        and port not in approved_live_ports
    ]
    if selected_processes or selected_holders or selected_ports:
        raise RuntimeError(
            "release blocked: fresh relevant frontend process, native holder, or listening port remains; "
            f"processes={selected_processes} holders={selected_holders} ports={selected_ports}"
        )
    return {
        "states": states,
        "identities": identities,
        "replacements": replacements,
        "replacement_pids": sorted(replacement_pids),
        "terminal_states": terminal_states,
        "transition_diagnostics": transition_diagnostics,
        "resources": resources,
        "port_owner_identities": port_owner_identities,
        "unrelated_exclusions": unrelated_exclusions,
    }

def _validate_host_process_evidence() -> dict[str, Any]:
    """Validate measured host evidence without changing host state."""
    contract = _load_host_process_contract()
    fresh = _assert_fresh_host_process_census(contract)
    native = _observe_host_native_resource()
    return {
        "root": str(contract["root"]),
        "historical_identities": len(contract["family_records"]),
        "native_resource": native["state"],
        "native_fingerprint": native.get("fingerprint"),
        "native_sha256": native.get("sha256"),
        "fresh_census": fresh,
    }


def _proof_reference() -> dict[str, Any]:
    return {
        "type": "private host process evidence",
        "files": list(HOST_PROCESS_EVIDENCE_FILES),
    }


def _value_count(value: object) -> int | None:
    if isinstance(value, (list, tuple, dict)):
        return len(value)
    return None


def _summarize_process_evidence(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError("release blocked: host process evidence summary is invalid")
    census = value.get("fresh_census")
    if not isinstance(census, dict):
        raise RuntimeError("release blocked: host process census summary is invalid")
    resources = census.get("resources")
    resource_summary = {}
    if isinstance(resources, dict):
        for name in ("processes", "holders", "ports", "read_errors"):
            count = _value_count(resources.get(name))
            if count is not None:
                resource_summary[f"{name}_count"] = count
    return {
        "historical_identity_count": value.get("historical_identities"),
        "native_resource": value.get("native_resource"),
        "native_fingerprint": value.get("native_fingerprint"),
        "native_sha256": value.get("native_sha256"),
        "fresh_census": {
            "state_count": _value_count(census.get("states")),
            "identity_count": _value_count(census.get("identities")),
            "replacement_count": _value_count(census.get("replacements")),
            "terminal_state_count": _value_count(census.get("terminal_states")),
            "transition_diagnostic_count": _value_count(census.get("transition_diagnostics")),
            "port_owner_identity_count": _value_count(census.get("port_owner_identities")),
            "resources": resource_summary,
        },
        "proof_reference": _proof_reference(),
    }


def _summarize_host_preparation(value: dict[str, Any]) -> dict[str, Any]:
    readiness = value.get("readiness")
    if not isinstance(readiness, dict):
        raise RuntimeError("release blocked: browser readiness result is invalid")
    dependency_findings = readiness.get("dependency_findings")
    if not isinstance(dependency_findings, list):
        raise RuntimeError("release blocked: browser dependency result is invalid")
    return {
        "process_before": _summarize_process_evidence(value["process_before"]),
        "native_release": value["native_release"],
        "dependencies": value["dependencies"],
        "process_after": _summarize_process_evidence(value["process_after"]),
        "readiness": {
            "process": _summarize_process_evidence(readiness["process"]),
            "dependency_findings": dependency_findings,
        },
        "proof_reference": _proof_reference(),
    }


_BROWSER_FRONTEND_REQUIRED_PACKAGES = ("next", "react", "react-dom", "@playwright/test")


def _browser_dependency_findings(frontend_root: Path | None = None) -> list[str]:
    """Check the existing project dependency state without installing packages."""
    frontend_root = (ROOT / "frontend") if frontend_root is None else Path(frontend_root)
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
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
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
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            findings.append(f"{name} installed package metadata is unreadable: {installed_path}: {exc}")
            continue
        if installed.get("version") != lock_entry["version"]:
            findings.append(
                f"{name} installed version does not match package-lock.json: "
                f"installed={installed.get('version')!r} locked={lock_entry['version']!r}"
            )
    next_executable = frontend_root / "node_modules" / ".bin" / (
        "next.cmd" if os.name == "nt" else "next"
    )
    if not next_executable.is_file():
        findings.append(f"project-scoped Next executable is missing: {next_executable}")
    return findings


def _validate_browser_dependency_readiness(
    frontend_root: Path | None = None,
    *,
    process: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate process ownership and installed browser dependencies without mutation."""
    if process is None:
        process = _validate_host_process_evidence()
    findings = _browser_dependency_findings(frontend_root)
    if findings:
        raise RuntimeError(
            "release blocked: browser dependency readiness failed before browser startup: "
            f"findings={findings}"
        )
    return {"process": process, "dependency_findings": findings}


def _validate_immutable_source_commits(
    source_commits: dict[str, object] | None = None,
) -> None:
    """Reject source identities that are not complete hexadecimal commits."""
    values = IMMUTABLE_SOURCE_COMMITS if source_commits is None else source_commits
    for name, value in values.items():
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
            raise RuntimeError(
                f"release blocked: invalid immutable source commit: {name}"
            )


def _validate_immutable_minio_images() -> None:
    """Reject changed, malformed, or mutable MinIO build identities."""
    for name, expected in IMMUTABLE_MINIO_IMAGES.items():
        value = globals()[name]
        if (
            not isinstance(value, str)
            or re.fullmatch(r"[^:@\s]+:[^@\s]+@sha256:[0-9a-f]{64}", value) is None
            or value != expected
        ):
            raise RuntimeError(f"release blocked: invalid immutable image identity: {name}")
CANONICAL_DEMO_RUN_ID = "11111111-1111-4111-8111-111111111111"
CANONICAL_DEMO_ARTIFACT_ROW_ID = "22222222-2222-4222-8222-222222222222"
CANONICAL_DEMO_MESSAGE_ROW_IDS = (
    "33333333-3333-4333-8333-333333333333",
    "44444444-4444-4444-8444-444444444444",
)
CANONICAL_DEMO_FILE_NAME = "demo_synthetic.ufdr"
CANONICAL_DEMO_OWNER_EMAIL = "citespan-demo-owner@example.invalid"
CANONICAL_DEMO_MARKER = "citespan-synthetic-demo-v1"
ORPHAN_CONTAINER_ID = "973174b191c63a34bf306e5e76960f1d07c3e42fe6be4f7a2e4b0f9210972b65"
ORPHAN_CONTAINER_NAME = "citespan-candidate-20261011161102141814605-backend"
ORPHAN_DEPLOYMENT_ID = "citespan-candidate-20261011161102141814605"
ORPHAN_ACTION_KEY = "c83803e08b3db27631bfe6eab6cc7cc57be69c12b7a957a9173afb6a2bfeb9eb"
ORPHAN_BACKUP_DIR = "/opt/citespan/.citespan-backups/20261011161057426069091"
SECRET_PATTERNS = (
    re.compile(r"sk-or-v1-[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?i)(openrouter|openai)_api_key\s*[:=]\s*['\"]?(?!REPLACE_WITH|CHANGE_ME|CHANGEME)[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?i)neo4j_password\s*[:=]\s*(?!os\.getenv\b|[-$]|%[A-Za-z])['\"]?(?!\*{3}REDACTED)[^\s'\"]{8,}"),
)
FORENSIC_EXTENSIONS = {
    ".ufdr", ".zip", ".tar", ".gz", ".tgz", ".7z", ".rar", ".db", ".sqlite",
    ".sqlite3", ".sql", ".csv", ".tsv", ".dd", ".e01", ".aff", ".aff4", ".mem", ".dmp", ".raw",
    ".img", ".iso", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".mp3",
    ".wav", ".mp4", ".mov", ".avi", ".m4a", ".pdf",
}
FORENSIC_MAGIC = (
    b"PK\x03\x04", b"SQLite format 3\x00", b"\x7fELF", b"MZ", b"\xff\xd8\xff",
    b"\x89PNG\r\n\x1a\n", b"RIFF", b"%PDF-", b"ustar",
)
REVIEWED_FORENSIC_TEXT_PATHS = {
    "backend/migrations/v5_indexes.sql",
    "cleanup_empty_runs.sql",
}
REVIEWED_BINARY_SIGNATURES = (
    b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a", b"RIFF",
    b"\x00\x00\x01\x00", b"\x00\x00\x02\x00", b"wOFF", b"wOF2", b"OTTO",
    b"icns",
)
REAL_DATA_NAMES = {
    "test_comprehensive.ufdr", "test_comprehensive.zip", "sample.ufdr", "sample.zip",
}
# A canonical sample is generated by seed code. A tracked forensic-capable
# binary is never accepted by filename, directory, extension, or magic alone.
# Each exact path has a digest, an expected type signature, and provenance.
# Future proof screenshots are intentionally absent from this manifest.
REVIEWED_BINARY_MANIFEST: dict[str, tuple[str, str, str]] = {
    "ALEAPP/assets/ALEAPP_logo.png": ("5e91a66d75f6763d718a8fb005164fab0ef079799527783e4e56657a07969b9b", "png", "vendor_ui_asset"),
    "ALEAPP/assets/icon.icns": ("903f3188cee95386dea84835886c568d64cd5b83994f91eeabc26f0c502a02a7", "icns", "vendor_ui_asset"),
    "ALEAPP/assets/icon.png": ("c5e2d8e0b8a197abae7b964494cf6fa4c7b954f023b13136ecb191f194564df2", "png", "vendor_ui_asset"),
    "ALEAPP/assets/leapps_a_logo.png": ("e0fa5f3b9d858f3db5cc3160e46692d054f0faffbca2ca440063b6fdef84d293", "png", "vendor_ui_asset"),
    "ALEAPP/assets/magnif_glass.png": ("169904f3c53c2a3e968c0b5fbd1fff81f0fff395dd830e2fce79560f95c6b8e7", "png", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/ALEAPP_banner.png": ("a2e8b5ba01eb6cc4c5fe5b6b4a37c0d77f3f4c4e35d82086e71659453659bf1b", "png", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/MDB-Free_4.13.0/img/overlays/01.png": ("5ddb13e84c10a1b7a773f0580f2997c3b5e91d1c2227fc1313c5991429442657", "png", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/MDB-Free_4.13.0/img/overlays/02.png": ("c8afad923ad12f782c6cb53563b0335fd8aa317f3a5814d88b79b19f5679b3bb", "png", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/MDB-Free_4.13.0/img/overlays/03.png": ("021c7caa7ff149c146699ef36babf141e219dba3164ad790ca01671b8bd2ddac", "png", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/MDB-Free_4.13.0/img/overlays/04.png": ("aec578846c14373efb19b86568aa26a7bda6a8190c2ba024f157dd8169584aab", "png", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/MDB-Free_4.13.0/img/overlays/05.png": ("174d12c6dad717d57e3fc10afd45cba4694ceeab0501f1b42dec153f60af7e26", "png", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/MDB-Free_4.13.0/img/overlays/06.png": ("5132930f761724e07ade77c2ee61c0d4a9c68500f1370a078acfcecff86f1034", "png", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/MDB-Free_4.13.0/img/overlays/07.png": ("7cac752f182428a3780fb961447d803b6a51a3ca2f76e3da10fdb53096255a4e", "png", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/MDB-Free_4.13.0/img/overlays/08.png": ("fe02d70713812b91ccd804366c80b40d2f2f8f1f048944e36bce1fd591b850d2", "png", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/MDB-Free_4.13.0/img/overlays/09.png": ("171c728935cc65ccdac105d28992f0020e968598eab1798983bb7973e40272aa", "png", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/logo.png": ("63292e3d7dafdeed8ad0c702a38d31c8e5fc15ff57e39ac061c029c2de4d3090", "png", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/fa/fa-brands-400.eot": ("60fb2d28d2f1dbd2bc1a7a3b44701fec1cb7f630bee439d926c024c3212c1a9c", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/fa/fa-brands-400.ttf": ("ca785b3a0d0f4c1bd0cbbe298a989af28aff3086b6522c2eaf9f7c110f080874", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/fa/fa-brands-400.woff": ("23d9a4585904deec93bbe23b911d97f40fe25bcdf6131737f17b1f87c4b68367", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/fa/fa-brands-400.woff2": ("d3caf12591d194712facd10bca14f0a924edb59c24447a3fd994a48286db8843", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/fa/fa-regular-400.eot": ("b115d3ffeefd0c3a276fa964e3a8aeb8fb04f782f690c476c1042b06ea465cd1", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/fa/fa-regular-400.ttf": ("913a94a29d838712cfed937028ac4ab14eac95ddc784d5207e4d4504ab42fa17", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/fa/fa-regular-400.woff": ("43a881161585db16179f70e53240a274f209aff03aafbcc34bc32e17fb4d95c6", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/fa/fa-regular-400.woff2": ("0fc0a22e5e67c95d02c389a1454acc67df53e2f6a46af739f3eac7e352644751", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/fa/fa-solid-900.eot": ("5ef4c7be9577dde004048607cc872221de00db893f29baa809c378b01370a370", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/fa/fa-solid-900.ttf": ("20656d1a8f2ea44e36c2b8354d15c4db21909ee5140b0224f74f92477e0899f7", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/fa/fa-solid-900.woff": ("7dd5fcdf6f4b330bf82965887ef6b9196b8d27855eddee99ac04fb63de0e351e", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/fa/fa-solid-900.woff2": ("3d1080625d3030e88357b3ac9aa377dcec23f1b529c4ad03f7a9a435ccae04be", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/roboto/v32/KFOlCnqEu92Fr1MmEU9fABc4AMP6lbBP.woff2": ("fc713b2c5b9d52fe86b27172ade5a3cd00739e7684dd6ba9814baf7f4c432d94", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/roboto/v32/KFOlCnqEu92Fr1MmEU9fBBc4AMP6lQ.woff2": ("0e637574ec102b93795e00daaa92eebdacf1dcee9133b123fb9b56ea8eaf7e14", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/roboto/v32/KFOlCnqEu92Fr1MmEU9fBxc4AMP6lbBP.woff2": ("379b0c57c6c5e521f8c352769b08e1517437d1e05e2607b4f0269a43af18a844", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/roboto/v32/KFOlCnqEu92Fr1MmEU9fCBc4AMP6lbBP.woff2": ("b94a79cc9568114ea22814f07603b3579db3bd6052e72ccd6c473ec73c902a33", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/roboto/v32/KFOlCnqEu92Fr1MmEU9fCRc4AMP6lbBP.woff2": ("07ba486b9fb8fc76ff6196a437052f3ae228028c53e66d1096bc0c981d041ab0", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/roboto/v32/KFOlCnqEu92Fr1MmEU9fChc4AMP6lbBP.woff2": ("8d4b5f4d63110c2994973a8752258ccf5384d07c7c03d1520112cf5ad3482924", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/roboto/v32/KFOlCnqEu92Fr1MmEU9fCxc4AMP6lbBP.woff2": ("4072d43309d96cd74de0817e12f8ba175bdab84cc6934c760b1ebb5c25e37c44", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/roboto/v32/KFOlCnqEu92Fr1MmSU5fABc4AMP6lbBP.woff2": ("f7122e8ea20b0d10748174095f79c71e1c7e590377aabc35ccbdb89ae282a5e1", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/roboto/v32/KFOlCnqEu92Fr1MmSU5fBBc4AMP6lQ.woff2": ("a70c2bc728eb261ac55c2ff878249947bcd3a9d8827d94e63fbdd8fe67156986", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/roboto/v32/KFOlCnqEu92Fr1MmSU5fBxc4AMP6lbBP.woff2": ("e05aa1e8055fc82a77f068453a97e1743f714e434a8d0e6f52efc2b9c7bbcf08", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/roboto/v32/KFOlCnqEu92Fr1MmSU5fCBc4AMP6lbBP.woff2": ("81916231442b3aa9c6cdf083d42116661854aa5a18f0c193747b0bd16928eef0", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/roboto/v32/KFOlCnqEu92Fr1MmSU5fCRc4AMP6lbBP.woff2": ("ed0c0cd6983f2fa0c7ff85737eaa99596ff1a62519391cf1eceee45750515c91", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/roboto/v32/KFOlCnqEu92Fr1MmSU5fChc4AMP6lbBP.woff2": ("4fb357ab6ea99551907a8a9457ab97a381367287f129e01b186c3be47ffd0169", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/roboto/v32/KFOlCnqEu92Fr1MmSU5fCxc4AMP6lbBP.woff2": ("18077bdf59eaa79bd6d9762d4c62c2655e892926b4556e0a0f357ee8dfa32474", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/roboto/v32/KFOlCnqEu92Fr1MmWUlfABc4AMP6lbBP.woff2": ("7c226cdfec4156a02a5cd67f8ee22b58514f91d40869e052f066f1b62ede7c1a", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/roboto/v32/KFOlCnqEu92Fr1MmWUlfBBc4AMP6lQ.woff2": ("0a7fc3de6341e5ab2853f213dbf792903cd35039daa9530a649a20a877ccac8a", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/roboto/v32/KFOlCnqEu92Fr1MmWUlfBxc4AMP6lbBP.woff2": ("1cfbbfe0ef243f51fd67251a117932fae00fbbe9df1f619abc85121acda10b1f", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/roboto/v32/KFOlCnqEu92Fr1MmWUlfCBc4AMP6lbBP.woff2": ("8e06da532b5cba39ca6c6f5c22283acc705e37d7606c5786f67f4127601abc9c", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/roboto/v32/KFOlCnqEu92Fr1MmWUlfCRc4AMP6lbBP.woff2": ("e4d446e5b8eddb428db53599067e979e56ad427fd96ab61e4adefc2fe4b2c5e5", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/roboto/v32/KFOlCnqEu92Fr1MmWUlfChc4AMP6lbBP.woff2": ("2e9598916ec58cccd8635c2aa152bd1097fb47fbe1ed13310554296e5ce2127c", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/roboto/v32/KFOlCnqEu92Fr1MmWUlfCxc4AMP6lbBP.woff2": ("1707850a76eb6fd3d17d1f1886fc2549fb10063d0f161316c616dd3dbab2eb37", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/roboto/v32/KFOmCnqEu92Fr1Mu4WxKKTU1Kvnz.woff2": ("21affbfe3f5a769ba917be1afb77ca2ba9c84e72f7c5203ae1a673cfbad7fe91", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/roboto/v32/KFOmCnqEu92Fr1Mu4mxKKTU1Kg.woff2": ("bf9cfe01317e3758dd38982921dc1f26cc7243237d02e7ed90d3830b6f4e8ed0", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/roboto/v32/KFOmCnqEu92Fr1Mu5mxKKTU1Kvnz.woff2": ("1aaa85b178d2582c05a057b886abc2493e994c13e8df64ad52eee764957af337", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/roboto/v32/KFOmCnqEu92Fr1Mu72xKKTU1Kvnz.woff2": ("9b3ac4bb2421eb033978859187b324a5e8c020fbdd77723010b9062186b993fb", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/roboto/v32/KFOmCnqEu92Fr1Mu7GxKKTU1Kvnz.woff2": ("2706f0379df18abe63657c8f52d4eebbea98c7cbbb8ee7ce4d4c64c36b70bb9c", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/roboto/v32/KFOmCnqEu92Fr1Mu7WxKKTU1Kvnz.woff2": ("71ec5c8cfdc6af4a6d11b6c29b9507adbadf437524fa8254257dbf585eb30a91", "font", "vendor_ui_asset"),
    "ALEAPP/scripts/_elements/fonts/roboto/v32/KFOmCnqEu92Fr1Mu7mxKKTU1Kvnz.woff2": ("830bc6b6b20457619ba048491b49497b42cc124ae2867cf872cf2914c490c569", "font", "vendor_ui_asset"),
    "frontend/app/favicon.ico": ("2b8ad2d33455a8f736fc3a8ebf8f0bdea8848ad4c0db48a2833bd0f9cd775932", "ico", "product_ui_asset"),
    "frontend/public/noise.webp": ("6f874a8481dc41fe2793f9e0da09de58d5d392a576a3e6c008af221b82c6e24b", "riff", "product_ui_asset"),
    "frontend/public/query.png": ("edc82d50cefe7a55e74f5bbde4b1d51f9095d7462703fc0c0773f2cc05c747de", "png", "product_ui_asset"),
}
REVIEWED_BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".icns", ".eot", ".ttf", ".otf", ".woff", ".woff2"}
PUBLIC_BRANDING_PATHS = {
    "README.md",
    "DEPLOY.md",
    "DECISIONS.md",
    "DEVELOPMENT.md",
    "backend/README.md",
    "env.example",
    "backend/ingest/services/evidence_report.py",
    "backend/ingest/services/graph_export.py",
    "backend/ingest/services/report_service.py",
    "backend/main.py",
    "backend/server.py",
    "docker/scripts/setup-dev.sh",
    "docker/scripts/setup-prod.sh",
    "fly.toml",
    "frontend/electron-builder.json",
}
CURRENT_PUBLIC_DOCUMENTATION_PATHS = {
    "README.md",
    "DEPLOY.md",
    "DEVELOPMENT.md",
    "DECISIONS.md",
    "backend/README.md",
}
HOSTED_DEMO_AI_TERMS = re.compile(
    r"(?i)\b(?:llm|large language model|generative ai|ai planner|ai-powered)\b"
)
HOSTED_DEMO_AI_ACTIVE_MARKERS = re.compile(
    r"(?i)\b(?:active|enabled|current|live|turns?|translates?|emits?|"
    r"generates?|creates?|powers?|provides?|uses?|plans?)\b"
)
HOSTED_DEMO_AI_LIMITATIONS = re.compile(
    r"(?i)\b(?:disabled|unavailable|not enabled|not a live|not current|"
    r"not valid|not used|optional|incomplete|outside the hosted demo)\b"
)
HOSTED_DEMO_AI_LIMITATION_CLAUSES = re.compile(
    r"(?i)(?:\b(?:it is\s+)?not a live large language model feature\b|"
    r"\b(?:a\s+)?live large language model claim is not valid\b|"
    r"\b(?:external(?:\s+or\s+live)?|live)\s+llm behavior is "
    r"(?:not enabled|disabled|unavailable)(?: and unavailable)?\b|"
    r"\boptional llm integration(?: code)? is incomplete and unavailable\b|"
    r"\bllm-optional,\s*not required\b)"
)
RUNTIME_CONFIG_PATHS = (
    ".env",
    ".env.production",
    "backend/.env",
    "docker/.env",
    "docker/environments/production.env",
)
SECRET_KEYS = re.compile(r"(?i)(api[_-]?key|password|secret|token)")
SAFE_SECRET_REFERENCES = ("$", "os.getenv", "env:", "secret:", "vault:", "REPLACE_WITH", "CHANGE_ME")
REQUIRED_RUNTIME_SECRET_KEYS = {
    "NEO4J_PASSWORD",
    "POSTGRES_PASSWORD",
    "MEILI_MASTER_KEY",
    "MINIO_ROOT_USER",
    "MINIO_ROOT_PASSWORD",
    "MINIO_ACCESS_KEY",
    "MINIO_SECRET_KEY",
    "SECRET_KEY",
}
_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(?:"
    + "|".join(re.escape(key) for key in sorted(REQUIRED_RUNTIME_SECRET_KEYS))
    + r"|openrouter_api_key|openai_api_key|neo4j_password|"
    r"[a-z_][a-z0-9_]*(?:api[_-]?key|password|secret|token)[a-z0-9_]*)\b\s*[:=]\s*"
    r"(?:['\"](?P<quoted>[^'\"]*)['\"]|(?P<bare>[^\s,;}\]]+))"
)
_SECRET_FIELD_PATTERN = re.compile(
    r"(?ix)(?P<key>\"(?:"
    + "|".join(
        re.escape(key)
        for key in sorted(
            REQUIRED_RUNTIME_SECRET_KEYS
            | {"OPENROUTER_API_KEY", "OPENAI_API_KEY", "NEO4J_PASSWORD"}
        )
    )
    + r"|[a-z_][a-z0-9_]*(?:api[_-]?key|password|secret|token)[a-z0-9_]*)\"|'(?:"
    + "|".join(
        re.escape(key)
        for key in sorted(
            REQUIRED_RUNTIME_SECRET_KEYS
            | {"OPENROUTER_API_KEY", "OPENAI_API_KEY", "NEO4J_PASSWORD"}
        )
    )
    + r"|[a-z_][a-z0-9_]*(?:api[_-]?key|password|secret|token)[a-z0-9_]*)'|"
    r"[a-z_][a-z0-9_]*(?:api[_-]?key|password|secret|token)[a-z0-9_]*)"
    r"\s*[:=]\s*(?P<value>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s,;}\]]+)"
)
PLACEHOLDER_SECRET = re.compile(
    r"(?i)^(?:change[_-]?me|replace[_-]?(?:with|me)|"
    r"your[_-](?:[a-z0-9]+[_-])*(?:key|secret)(?:[_-][a-z0-9]+)*[_-]here|placeholder|"
    r"<[^<>\r\n]+>|\$\{[^{}\r\n]+\}|\{\{[^{}\r\n]+\}\})$"
)


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True
    )
    return _decode_utf8(result.stdout, "git stdout").strip()


def _normalize_repository_origin(value: str) -> str:
    """Accept only unambiguous GitHub transport forms for this repository."""
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        raise ValueError("release blocked: repository origin is invalid")
    if value.startswith("git@"):
        match = re.fullmatch(r"git@([^:]+):([^/]+)/([^/]+?)(?:\.git)?", value)
        if not match or match.group(1).lower() != "github.com":
            raise ValueError("release blocked: repository origin is not the authorized GitHub repository")
        owner, repository = match.group(2), match.group(3)
    else:
        parsed = urlsplit(value)
        if (
            parsed.scheme.lower() not in {"https", "ssh"}
            or parsed.hostname is None
            or parsed.hostname.lower() != "github.com"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("release blocked: repository origin is not the authorized GitHub repository")
        parts = parsed.path.strip("/").split("/")
        if len(parts) != 2:
            raise ValueError("release blocked: repository origin is not the authorized GitHub repository")
        owner, repository = parts
        if repository.endswith(".git"):
            repository = repository[:-4]
    if owner != "aayushman-singh" or repository != "ufdr-analyzer":
        raise ValueError("release blocked: repository origin is not the authorized repository")
    return "aayushman-singh/ufdr-analyzer"


def _remote_origin_check_script() -> str:
    """Return the remote-side origin normalizer without exposing its input."""
    return (
        "import os, re; from urllib.parse import urlsplit; "
        "value=os.environ.get('CITESPAN_ORIGIN_URL',''); "
        "scp=re.fullmatch(r'git@([^:]+):([^/]+)/([^/]+?)(?:\\.git)?', value); "
        "parsed=None if scp else urlsplit(value); "
        "path=[] if parsed is None else parsed.path.strip('/').split('/'); "
        "parts=scp.groups() if scp else (parsed.hostname, path[0], path[1][:-4] if path[1].endswith('.git') else path[1]) if len(path)==2 else None; "
        "valid=bool(parts) and parts[0].lower()=='github.com' and parts[1]=='aayushman-singh' and parts[2]=='ufdr-analyzer' and (bool(scp) or (parsed.scheme.lower() in {'https','ssh'} and parsed.username is None and parsed.password is None and parsed.port is None and not parsed.query and not parsed.fragment)); "
        "(_ for _ in ()).throw(SystemExit(1)) if not valid else print('aayushman-singh/ufdr-analyzer')"
    )


def _decode_utf8(value: bytes, stream: str) -> str:
    try:
        return value.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"release blocked: {stream} is not valid UTF-8") from exc


def _tracked_names() -> list[str]:
    """Return the exact regular files reported by Git.

    Release preparation fails when the checkout is not a Git worktree. The
    filesystem is not a substitute for Git's tracked-file boundary.
    """
    git_marker = ROOT / ".git"
    if not git_marker.exists():
        raise RuntimeError("release blocked: exact Git checkout is required")
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=False, capture_output=True
    )
    if result.returncode != 0:
        detail = _decode_utf8(result.stderr, "git ls-files stderr").strip()
        raise RuntimeError(f"release blocked: Git tracked-file enumeration failed: {detail}")
    names = [name for name in _decode_utf8(result.stdout, "git ls-files stdout").split("\0") if name]
    if any("\x00" in name for name in names):
        raise RuntimeError("release blocked: Git returned an invalid tracked path")
    return names


def _reviewed_binary_signature_valid(suffix: str, sample: bytes) -> bool:
    """Validate a reviewed binary by its suffix and format signature."""
    if suffix in {".ttf", ".otf"}:
        return sample.startswith((b"\x00\x01\x00\x00", b"true", b"typ1", b"OTTO"))
    if suffix == ".eot":
        return len(sample) >= 12 and sample[8:12] in {b"\x01\x00\x02\x00", b"\x02\x00\x02\x00"}
    return any(sample.startswith(signature) for signature in REVIEWED_BINARY_SIGNATURES)


def _manifest_binary_record(name: str, path: Path, sample: bytes) -> tuple[str, str, str] | None:
    """Validate one exact binary manifest record.

    The manifest is closed world. A valid magic value does not create trust.
    """
    record = REVIEWED_BINARY_MANIFEST.get(name)
    if record is None:
        return None
    if len(record) != 3:
        raise RuntimeError(f"release blocked: ambiguous binary manifest record: {name}")
    digest, expected_type, provenance = record
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise RuntimeError(f"release blocked: invalid binary manifest digest: {name}")
    if provenance not in {"vendor_ui_asset", "product_ui_asset"}:
        raise RuntimeError(f"release blocked: invalid binary provenance: {name}")
    if path.suffix.lower() not in REVIEWED_BINARY_SUFFIXES:
        raise RuntimeError(f"release blocked: binary manifest has invalid suffix: {name}")
    actual_digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual_digest != digest:
        raise RuntimeError(f"release blocked: binary manifest digest mismatch: {name}")
    type_valid = {
        "png": sample.startswith(b"\x89PNG\r\n\x1a\n"),
        "jpeg": sample.startswith(b"\xff\xd8\xff"),
        "gif": sample.startswith((b"GIF87a", b"GIF89a")),
        "riff": sample.startswith(b"RIFF"),
        "ico": sample.startswith(b"\x00\x00\x01\x00"),
        "icns": sample.startswith(b"icns"),
        "font": _reviewed_binary_signature_valid(path.suffix.lower(), sample),
    }.get(expected_type)
    if type_valid is not True:
        raise RuntimeError(f"release blocked: binary manifest type mismatch: {name}")
    return record


def _tracked_text() -> list[tuple[str, str]]:
    """Scan every tracked file and return the UTF-8 files for text audits.

    Binary assets are accepted only at reviewed project asset paths. All other
    binary content, forensic extensions, and forensic magic values fail closed.
    The scan has no size exception.
    """
    files = _tracked_names()
    values: list[tuple[str, str]] = []
    for name in files:
        if not name:
            continue
        path = ROOT / name
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"release blocked: tracked path is not a regular file: {name}")
        first = b""
        tail = b""
        text_parts: list[str] = []
        decoder = codecs.getincrementaldecoder("utf-8")()
        binary = False
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                if not first:
                    first = chunk[:4096]
                tail = (tail + chunk)[-4096:]
                try:
                    text_parts.append(decoder.decode(chunk))
                except UnicodeDecodeError:
                    binary = True
                    break
        suffix = path.suffix.lower()
        binary = binary or suffix in REVIEWED_BINARY_SUFFIXES
        sample = first + tail
        reviewed_forensic_text = name in REVIEWED_FORENSIC_TEXT_PATHS and not binary
        manifest_record = _manifest_binary_record(name, path, sample) if not reviewed_forensic_text else None
        digest_valid = manifest_record is not None
        if binary:
            if manifest_record is None:
                if suffix in REVIEWED_BINARY_SUFFIXES and not _reviewed_binary_signature_valid(suffix, sample):
                    raise RuntimeError(f"release blocked: unknown type for binary content: {name}")
                raise RuntimeError(f"release blocked: tracked forensic content is not allowlisted: {name}")
            continue
        if not binary:
            try:
                text_parts.append(decoder.decode(b"", final=True))
            except UnicodeDecodeError as exc:
                raise RuntimeError(f"release blocked: tracked content is not valid UTF-8: {name}") from exc
        if suffix in FORENSIC_EXTENSIONS and not reviewed_forensic_text and not digest_valid:
            raise RuntimeError(f"release blocked: tracked forensic content is not allowlisted: {name}")
        text = "".join(text_parts)
        if any(sample.startswith(signature) for signature in FORENSIC_MAGIC) and not digest_valid:
            raise RuntimeError(f"release blocked: tracked forensic content signature: {name}")
        values.append((name, text))
    return values


def _release_text() -> list[tuple[str, str]]:
    """Read current configuration candidates without returning their contents."""
    values = _tracked_text()
    for name in RUNTIME_CONFIG_PATHS:
        path = ROOT / name
        if path.is_file() and all(existing != name for existing, _ in values):
            try:
                values.append((name, path.read_text(encoding="utf-8")))
            except UnicodeDecodeError:
                raise RuntimeError(f"release blocked: configuration is not valid UTF-8: {name}")
    return values


def _credential_scan_findings(values: list[tuple[str, str]]) -> list[str]:
    """Find credential values while excluding inert Python string syntax."""
    findings = []
    for name, text in values:
        normalized_name = name.replace("\\", "/")
        scan_text = _credential_scan_text(normalized_name, text)
        if any(pattern.search(scan_text) for pattern in SECRET_PATTERNS):
            findings.append(name)
    return findings


def _credential_scan_text(name: str, text: str) -> str:
    """Return complete source plus narrowly reviewed static credential evidence."""
    if not name.endswith(".py"):
        return text
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return text

    evidence: list[str] = []
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        elif isinstance(node, ast.Return):
            value = node.value
        if value is None or _is_inert_scanner_definition(node, targets):
            continue

        for target in targets:
            key = _credential_name(target)
            static_value = _static_string_value(value)
            if key is not None and static_value is not None:
                evidence.append(f"{key}={static_value}")

        for key, item in _credential_mapping_entries(value):
            static_value = _static_string_value(item)
            if static_value is not None and not _is_reviewed_inert_python_value(
                name, key, static_value
            ):
                evidence.append(f"{key}={static_value}")

        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            assignment_targets = targets or [node.target]
            for target in assignment_targets:
                if not isinstance(target, ast.Subscript):
                    continue
                key = _credential_subscript_name(target.slice)
                static_value = _static_string_value(value)
                if key is not None and static_value is not None:
                    evidence.append(f"{key}={static_value}")
    return text + "\n" + "\n".join(evidence)


def _credential_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name) and SECRET_KEYS.search(node.id):
        return node.id
    if isinstance(node, ast.Attribute) and SECRET_KEYS.search(node.attr):
        return node.attr
    if isinstance(node, (ast.Tuple, ast.List)):
        for element in node.elts:
            name = _credential_name(element)
            if name is not None:
                return name
    return None


def _is_inert_scanner_definition(node: ast.AST, targets: list[ast.expr]) -> bool:
    if not isinstance(node, (ast.Assign, ast.AnnAssign)):
        return False
    names = {target.id.lower() for target in targets if isinstance(target, ast.Name)}
    return bool(names & {"secret_patterns", "secret_keys"})


def _is_reviewed_inert_python_value(name: str, key: str, value: str) -> bool:
    return (
        name.replace("\\", "/"),
        key,
        value,
    ) == ("scripts/tests/test_release.py", "neo4j_password", "synthetic-test-password")


def _credential_mapping_entries(node: ast.AST) -> list[tuple[str, ast.expr]]:
    entries: list[tuple[str, ast.expr]] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Dict):
            continue
        for key, value in zip(child.keys, child.values):
            credential_name = _credential_subscript_name(key)
            if credential_name is not None:
                entries.append((credential_name, value))
    return entries


def _credential_subscript_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value if SECRET_KEYS.search(node.value) else None
    return _credential_name(node)


def _static_string_value(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _static_string_value(node.left)
        right = _static_string_value(node.right)
        if left is not None and right is not None:
            return left + right
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                return None
            parts.append(value.value)
        return "".join(parts)
    return None


def _history_credential_findings() -> list[str]:
    """Return labels for credential values found in history, never the values."""
    return [label for label, _ in _history_secret_matches()]


def _history_secret_matches() -> list[tuple[str, str]]:
    result = subprocess.run(
        ["git", "log", "--all", "--format=", "--patch", "--binary", "--", "."],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("release blocked: git history cannot be inspected")
    history = _decode_utf8(result.stdout, "git history stdout")
    patterns = (
        (
            "OpenRouter credential in git history",
            re.compile(r"(?P<value>sk-or-v1-[A-Za-z0-9_-]{20,})"),
        ),
        (
            "OpenRouter credential in git history",
            re.compile(
                r"(?i)openrouter_api_key\s*[:=]\s*['\"]?(?P<value>(?!REPLACE_WITH|CHANGE_ME|CHANGEME)[A-Za-z0-9_-]{20,})"
            ),
        ),
        (
            "OpenAI credential in git history",
            re.compile(
                r"(?i)openai_api_key\s*[:=]\s*['\"]?(?P<value>(?!REPLACE_WITH|CHANGE_ME|CHANGEME)[A-Za-z0-9_-]{20,})"
            ),
        ),
        (
            "Neo4j credential in git history",
            re.compile(
                r"(?i)neo4j_password\s*[:=]\s*['\"]?(?P<value>(?!os\.getenv\b|[-$]|\*{3}REDACTED|CHANGE_ME|changeme)[^\s'\"$]{8,})"
            ),
        ),
    )
    matches: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for label, pattern in patterns:
        for match in pattern.finditer(history):
            value = match.group("value")
            item = (label, value)
            if item not in seen:
                seen.add(item)
                matches.append(item)
    return matches


def _history_secret_hashes() -> list[str]:
    """Return SHA-256 fingerprints for historical secret values only."""
    values = {value for _, value in _history_secret_matches()}
    return sorted(hashlib.sha256(value.encode()).hexdigest() for value in values)


def _runtime_validation_script(history_hashes: list[str]) -> str:
    """Return the remote runtime validator without exposing secret values."""
    hashes = repr(tuple(history_hashes))
    return f"""import hashlib
import os
import re
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.is_file():
    raise ValueError(\"runtime env is missing\")
if os.name == "posix" and stat.S_IMODE(path.stat().st_mode) != 0o600:
    raise ValueError(\"runtime env has unsafe permissions\")

required = {{
    \"DEMO_MODE\", \"CITESPAN_SYNTHETIC_ONLY\", \"OPENAI_API_KEY\",
    \"OPENROUTER_API_KEY\", \"NEO4J_PASSWORD\", \"POSTGRES_USER\",
    \"POSTGRES_DB\", \"POSTGRES_PASSWORD\", \"MEILI_MASTER_KEY\",
    \"MINIO_ROOT_USER\", \"MINIO_ROOT_PASSWORD\", \"MINIO_ACCESS_KEY\",
    \"MINIO_SECRET_KEY\", \"SECRET_KEY\",
}}
values = {{}}
for line in path.read_text(encoding=\"utf-8\").splitlines():
    if not line or line.count(\"=\") != 1:
        raise ValueError(\"runtime env contains an invalid line\")
    key, value = line.split(\"=\", 1)
    if not key or not key.isupper() or not key.replace(\"_\", \"A\").isalnum() or key in values:
        raise ValueError(\"runtime env contains a missing or duplicate key\")
    values[key] = value
if set(values) != required:
    missing = sorted(required - set(values))
    extra = sorted(set(values) - required)
    raise ValueError(f\"runtime env key set is invalid: missing={{missing}}, extra={{extra}}\")
if values[\"DEMO_MODE\"] != \"1\" or values[\"CITESPAN_SYNTHETIC_ONLY\"] != \"1\":
    raise ValueError(\"runtime env does not enforce synthetic demo mode\")
if values[\"POSTGRES_USER\"] != \"ufdr_user\" or values[\"POSTGRES_DB\"] != \"ufdr_analyzer\":
    raise ValueError(\"runtime env has invalid PostgreSQL identity\")
placeholder_secret = re.compile(
    r\"(?i)^(?:change[_-]?me|replace[_-]?(?:with|me)|\"
    r\"your[_-](?:[a-z0-9]+[_-])*(?:key|secret)(?:[_-][a-z0-9]+)*[_-]here|placeholder)$\"
)

def is_placeholder(value):
    value = value.strip()
    return bool(placeholder_secret.fullmatch(value)) or (
        len(value) > 2
        and value[0] == \"<\"
        and value[-1] == \">\"
        and \"<\" not in value[1:-1]
        and \">\" not in value[1:-1]
    ) or value.startswith(\"$\" + chr(123)) and value.endswith(chr(125)) or value.startswith(chr(123) * 2) and value.endswith(chr(125) * 2)
for key in (\"NEO4J_PASSWORD\", \"POSTGRES_PASSWORD\", \"MEILI_MASTER_KEY\", \"MINIO_ROOT_USER\", \"MINIO_ROOT_PASSWORD\", \"SECRET_KEY\"):
    if not values[key]:
        raise ValueError(f\"runtime env has an empty {{key}}\")
    if is_placeholder(values[key]):
        raise ValueError(f\"runtime env has a placeholder value for {{key}}\")
    if len(values[key].strip()) < 8 or any(character.isspace() for character in values[key]):
        raise ValueError(f\"runtime env has a non-meaningful value for {{key}}\")
if values[\"OPENAI_API_KEY\"] or values[\"OPENROUTER_API_KEY\"]:
    raise ValueError(\"runtime env enables external AI credentials\")
if values[\"MINIO_ACCESS_KEY\"] != values[\"MINIO_ROOT_USER\"] or values[\"MINIO_SECRET_KEY\"] != values[\"MINIO_ROOT_PASSWORD\"]:
    raise ValueError(\"runtime env has mismatched MinIO credentials\")

historical_hashes = set({hashes})
compromised = [key for key, value in values.items() if value and hashlib.sha256(value.encode()).hexdigest() in historical_hashes]
service_owned = {{\"NEO4J_PASSWORD\", \"POSTGRES_PASSWORD\", \"MEILI_MASTER_KEY\", \"MINIO_ROOT_USER\", \"MINIO_ROOT_PASSWORD\", \"MINIO_ACCESS_KEY\", \"MINIO_SECRET_KEY\"}}
blocked = sorted(set(compromised) & service_owned)
if blocked:
    raise ValueError(\"runtime env contains compromised service credential(s): \" + \", \".join(blocked) + \"; verified in-place credential migration is required before release\")
non_service_compromised = sorted(set(compromised) - service_owned)
if non_service_compromised:
    raise ValueError(\"runtime env contains compromised credential(s): \" + \", \".join(non_service_compromised) + \"; explicit verified rotation is required before release\")
"""


def _project_python() -> str:
    if not PROJECT_PYTHON.is_file():
        raise RuntimeError(f"release blocked: project Python is missing: {PROJECT_PYTHON}")
    return PROJECT_PYTHON.as_posix()


def _failure_python_description() -> str:
    """Describe the configured interpreter without validating its existence."""
    return PROJECT_PYTHON.as_posix()


def _playwright_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["PLAYWRIGHT_BROWSERS_PATH"] = PLAYWRIGHT_BROWSERS_PATH.as_posix()
    return environment


def _validate_python_playwright_contract() -> None:
    expected_wheel = f"playwright-{PYTHON_PLAYWRIGHT_VERSION}-py3-none-win_amd64.whl"
    if PYTHON_PLAYWRIGHT_WHEEL != expected_wheel:
        raise RuntimeError("release blocked: Python Playwright wheel name does not match its version")
    if not PYTHON_PLAYWRIGHT_WHEEL_URL.endswith(f"/{expected_wheel}"):
        raise RuntimeError("release blocked: Python Playwright wheel URL does not match its version")
    if not re.fullmatch(r"[0-9a-f]{64}", PYTHON_PLAYWRIGHT_WHEEL_SHA256):
        raise RuntimeError("release blocked: Python Playwright wheel SHA-256 is missing or invalid")


def _live_verifier_is_usable() -> bool:
    probe = (
        "import importlib.metadata as metadata; "
        f"assert metadata.version('playwright') == {PYTHON_PLAYWRIGHT_VERSION!r}; "
        "from pathlib import Path; "
        "from playwright.sync_api import sync_playwright; "
        "p=sync_playwright().start(); "
        "path=Path(p.chromium.executable_path); "
        "assert path.is_file(), path; p.stop()"
    )
    command = [_project_python(), "-c", probe]
    started_at = _monotonic_now()
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=_playwright_environment(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=PLAYWRIGHT_PROVISION_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        evidence_path = _record_private_subprocess_timeout(
            step="playwright usability probe",
            argv_category="project Python Playwright probe",
            command=command,
            timeout=exc,
            timeout_seconds=PLAYWRIGHT_PROVISION_TIMEOUT_SECONDS,
            elapsed_seconds=_measured_elapsed_seconds(started_at),
        )
        raise RuntimeError(
            "release blocked: Playwright usability probe timed out; "
            f"private evidence: {evidence_path}"
        ) from exc
    return result.returncode == 0


def _record_private_provisioning_failure(
    command: list[str], result: subprocess.CompletedProcess[str]
) -> Path:
    """Store sanitized installer evidence outside hook stdout."""
    EXTERNAL_PROOF_ROOT.mkdir(parents=True, exist_ok=True)
    evidence_dir = Path(tempfile.mkdtemp(prefix="provisioning-failure-", dir=EXTERNAL_PROOF_ROOT))
    def redact(value: str) -> str:
        redacted = value
        for pattern in SECRET_PATTERNS:
            redacted = pattern.sub("<REDACTED>", redacted)
        return redacted

    evidence_path = evidence_dir / "provisioning-failure.json"
    evidence_path.write_text(
        json.dumps(
            {
                "command": command,
                "returncode": result.returncode,
                "stdout": redact(result.stdout or ""),
                "stderr": redact(result.stderr or ""),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return evidence_path


def _bounded_subprocess_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    safe = _sanitize_failure_text(str(value))
    if len(safe) > SUBPROCESS_DIAGNOSTIC_LIMIT:
        return safe[:SUBPROCESS_DIAGNOSTIC_LIMIT] + "<TRUNCATED>"
    return safe


_SENSITIVE_ARGUMENT_NAMES = {
    "--api-key",
    "--password",
    "--secret",
    "--token",
    "--authorization",
    "--header",
}


def _redacted_subprocess_argv(command: list[str]) -> list[str]:
    redacted: list[str] = []
    redact_next = False
    for argument in command:
        value = str(argument)
        if redact_next:
            redacted.append("<REDACTED>")
            redact_next = False
            continue
        if value.casefold() in _SENSITIVE_ARGUMENT_NAMES or any(
            value.casefold().startswith(f"{name}=") for name in _SENSITIVE_ARGUMENT_NAMES
        ):
            if "=" in value:
                redacted.append(value.split("=", 1)[0] + "=<REDACTED>")
            else:
                redacted.append(value)
                redact_next = True
            continue
        redacted.append(_sanitize_failure_text(value))
    return redacted


def _monotonic_now() -> float | None:
    try:
        return time.monotonic()
    except (OSError, RuntimeError):
        return None


def _measured_elapsed_seconds(started_at: float | None) -> float | None:
    if started_at is None:
        return None
    finished_at = _monotonic_now()
    if finished_at is None or finished_at < started_at:
        return None
    return finished_at - started_at


def _timeout_cleanup_evidence(
    descendant_census: dict[str, Any] | None,
) -> dict[str, Any]:
    if descendant_census is None:
        return {
            "status": "failed closed because descendant ownership census is unverified",
            "descendant_state": "unverified",
        }
    if not isinstance(descendant_census, dict):
        raise TypeError("descendant census must be a JSON object")
    census_status = descendant_census.get("status")
    if census_status == "read_failed":
        read_failure = descendant_census.get("read_failure")
        if not isinstance(read_failure, str) or not read_failure:
            raise ValueError("failed descendant census must include read_failure")
        return {
            "status": "failed closed because descendant ownership census read failed",
            "descendant_state": "unreadable",
            "read_failure": _bounded_subprocess_text(read_failure),
        }
    if census_status == "measured":
        descendant_state = descendant_census.get("descendant_state")
        if not isinstance(descendant_state, str) or not descendant_state:
            raise ValueError("measured descendant census must include descendant_state")
        return {
            "status": "failed closed pending measured descendant ownership handling",
            "descendant_state": descendant_state,
        }
    raise ValueError("descendant census status must be measured or read_failed")


def _record_private_subprocess_timeout(
    *,
    step: str,
    argv_category: str,
    command: list[str],
    timeout: subprocess.TimeoutExpired,
    timeout_seconds: int,
    elapsed_seconds: float | None = None,
    descendant_census: dict[str, Any] | None = None,
    cleanup_failure: str | None = None,
) -> Path:
    """Store bounded timeout evidence without writing diagnostics to hook stdout."""
    EXTERNAL_PROOF_ROOT.mkdir(parents=True, exist_ok=True)
    evidence_dir = Path(tempfile.mkdtemp(prefix="subprocess-timeout-", dir=EXTERNAL_PROOF_ROOT))
    evidence_path = evidence_dir / "timeout.json"
    traceback_text = _sanitize_failure_text(traceback.format_exc())
    evidence = {
        "step": step,
        "argv_category": argv_category,
        "cwd": ROOT.as_posix(),
        "timeout_seconds": timeout_seconds,
        "command": _redacted_subprocess_argv(command),
        "argument_count": len(command),
        "exception_type": type(timeout).__name__,
        "exception_message": _bounded_subprocess_text(str(timeout)),
        "traceback": _bounded_subprocess_text(traceback_text),
        "stdout": _bounded_subprocess_text(timeout.stdout),
        "stderr": _bounded_subprocess_text(timeout.stderr),
        "cleanup": _timeout_cleanup_evidence(descendant_census),
    }
    if cleanup_failure:
        evidence["cleanup_failure"] = _bounded_subprocess_text(cleanup_failure)
    if elapsed_seconds is not None:
        evidence["elapsed_seconds"] = elapsed_seconds
    evidence_path.write_text(
        json.dumps(evidence, sort_keys=True),
        encoding="utf-8",
    )
    return evidence_path


def _record_private_failure(command: str, exc: BaseException, state: dict[str, Any] | None = None) -> Path:
    """Write full failure context outside the provider JSON response."""
    EXTERNAL_PROOF_ROOT.mkdir(parents=True, exist_ok=True)
    evidence_dir = Path(tempfile.mkdtemp(prefix="release-failure-", dir=EXTERNAL_PROOF_ROOT))
    detail = traceback.format_exc()
    detail = _sanitize_failure_text(detail)
    safe_error = _sanitize_failure_text(str(exc))
    evidence_path = evidence_dir / "failure.json"
    evidence_path.write_text(
        json.dumps(
            {
                "command": command,
                "failed_step": command,
                "error": safe_error,
                "traceback": detail,
                "state": state or {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return evidence_path


def _record_private_ssh_timeout(
    command: str, timeout: subprocess.TimeoutExpired
) -> Path:
    """Store partial SSH output when the exact client reaches its deadline."""
    EXTERNAL_PROOF_ROOT.mkdir(parents=True, exist_ok=True)
    evidence_dir = Path(tempfile.mkdtemp(prefix="ssh-timeout-", dir=EXTERNAL_PROOF_ROOT))

    def sanitize(value: object, stream: str) -> str | dict[str, object]:
        if value is None:
            return ""
        if isinstance(value, bytes):
            digest = hashlib.sha256(value).hexdigest()
            try:
                decoded = value.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                safe_prefix = value[: exc.start].decode("utf-8", errors="strict")
                return {
                    "type": "encoding_error",
                    "stream": stream,
                    "byte_length": len(value),
                    "sha256": digest,
                    "error": {"offset": exc.start, "reason": exc.reason},
                    "safe_prefix": _sanitize_ssh_diagnostic(safe_prefix, command),
                }
            return _sanitize_ssh_diagnostic(decoded, command)
        return _sanitize_ssh_diagnostic(str(value), command)

    evidence_path = evidence_dir / "ssh-timeout.json"
    evidence_path.write_text(
        json.dumps(
            {
                "command": "<submitted script>",
                "timeout_seconds": SSH_TIMEOUT_SECONDS,
                "outcome": "unknown_external_outcome",
                "stdout": sanitize(timeout.stdout, "stdout"),
                "stderr": sanitize(timeout.stderr, "stderr"),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return evidence_path


def _sanitize_failure_text(value: str) -> str:
    secret_values = []
    for match in _SECRET_FIELD_PATTERN.finditer(value):
        candidate = match.group("value")
        if candidate[:1] in {'"', "'"} and candidate[-1:] == candidate[:1]:
            candidate = candidate[1:-1]
        if candidate and not any(reference in candidate for reference in SAFE_SECRET_REFERENCES):
            secret_values.append(candidate)
    for match in _SECRET_ASSIGNMENT_PATTERN.finditer(value):
        candidate = match.group("quoted") or match.group("bare")
        if candidate and not any(reference in candidate for reference in SAFE_SECRET_REFERENCES):
            secret_values.append(candidate)
    for candidate in sorted(set(secret_values), key=len, reverse=True):
        value = value.replace(candidate, "<REDACTED>")
    for pattern in SECRET_PATTERNS:
        value = pattern.sub("<REDACTED>", value)
    value = _SECRET_FIELD_PATTERN.sub("<REDACTED>", value)
    value = _SECRET_ASSIGNMENT_PATTERN.sub("<REDACTED>", value)
    return value


_PUBLIC_REDACTED_KEYS = {
    "argv",
    "command",
    "cmdline",
    "environment",
    "env",
    "processes",
    "identities",
    "holders",
    "ports",
    "read_errors",
    "replacements",
    "transition_diagnostics",
    "port_owner_identities",
}
_PUBLIC_SECRET_KEY = re.compile(
    r"(?:api[_-]?key|authorization|credential|password|secret|token)", re.IGNORECASE
)


def _sanitize_public_success(value: object, *, key: str | None = None) -> object:
    """Keep provider success JSON bounded and free of private process evidence."""
    if key is not None and (
        key.casefold() in _PUBLIC_REDACTED_KEYS or _PUBLIC_SECRET_KEY.search(key)
    ):
        return "<REDACTED>"
    if isinstance(value, dict):
        return {
            str(item_key): _sanitize_public_success(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_public_success(item) for item in value]
    if isinstance(value, str):
        return _sanitize_failure_text(value)
    return value


def _provision_live_verifier() -> None:
    """Install the verified Python Playwright wheel and its Chromium binary."""
    _validate_python_playwright_contract()
    if _live_verifier_is_usable():
        return
    python = _project_python()
    PLAYWRIGHT_BROWSERS_PATH.mkdir(parents=True, exist_ok=True)
    commands = [
        [
            python,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-deps",
            "--require-hashes",
            "--only-binary=:all:",
            f"{PYTHON_PLAYWRIGHT_WHEEL_URL}#sha256={PYTHON_PLAYWRIGHT_WHEEL_SHA256}",
        ],
        [python, "-m", "playwright", "install", "chromium"],
    ]
    for command in commands:
        started_at = _monotonic_now()
        try:
            result = subprocess.run(
                command,
                cwd=ROOT,
                env=_playwright_environment(),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                check=False,
                timeout=PLAYWRIGHT_PROVISION_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            evidence_path = _record_private_subprocess_timeout(
                step="Playwright provisioning",
                argv_category="project Python Playwright installer",
                command=command,
                timeout=exc,
                timeout_seconds=PLAYWRIGHT_PROVISION_TIMEOUT_SECONDS,
                elapsed_seconds=_measured_elapsed_seconds(started_at),
            )
            raise RuntimeError(
                "release blocked: live verifier provisioning timed out; "
                f"private evidence: {evidence_path}"
            ) from exc
        if type(result.returncode) is not int or result.returncode != 0:
            evidence_path = _record_private_provisioning_failure(command, result)
            raise RuntimeError(
                "release blocked: live verifier provisioning failed "
                f"with exit code {result.returncode}; private evidence: {evidence_path}"
            )
    if not _live_verifier_is_usable():
        raise RuntimeError("release blocked: pinned Playwright package or Chromium browser is unusable")


def _file_identity(path: Path) -> dict[str, Any]:
    """Capture the immutable identity required for one launch contract."""
    try:
        metadata = path.stat()
    except OSError as exc:
        raise RuntimeError(f"release blocked: installer identity cannot be read: {path}") from exc
    if not path.is_file() or path.is_symlink():
        raise RuntimeError(f"release blocked: installer identity is not a regular file: {path}")
    return {
        "path": _canonical_windows_path_identity(path),
        "size": metadata.st_size,
        "mtime_ns": metadata.st_mtime_ns,
        "ctime_ns": metadata.st_ctime_ns,
    }


def _host_installer_contract(frontend_root: Path) -> dict[str, Any]:
    """Resolve the installed Node runtime and npm CLI without a command wrapper."""
    node = shutil.which("node.exe") or shutil.which("node")
    if not node:
        raise RuntimeError("release blocked: installed node.exe is required for locked frontend dependency preparation")
    node_path = Path(node).resolve()
    npm_cli = node_path.parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
    if not npm_cli.is_file():
        raise RuntimeError(f"release blocked: installed npm-cli.js is missing beside node.exe: {npm_cli}")
    marker = f"citespan-host-install-{uuid.uuid4()}"
    return {
        "marker": marker,
        "node": _file_identity(node_path),
        "npm_cli": _file_identity(npm_cli.resolve()),
        "frontend": _canonical_windows_path_identity(frontend_root.resolve()),
        "argv": [
            str(node_path),
            str(npm_cli.resolve()),
            "--prefix",
            str(frontend_root.resolve()),
            "ci",
            "--ignore-scripts",
        ],
    }


def _assert_installer_contract(contract: dict[str, Any]) -> None:
    argv = contract.get("argv")
    if not isinstance(argv, list) or len(argv) != 6:
        raise RuntimeError("release blocked: host installer launch contract is incomplete")
    node = Path(argv[0])
    npm_cli = Path(argv[1])
    if node.name.casefold() != "node.exe" or npm_cli.name.casefold() != "npm-cli.js":
        raise RuntimeError("release blocked: host preparation rejects npm.cmd and cmd.exe wrappers")
    if any(Path(value).name.casefold() in {"npm.cmd", "cmd.exe", "cmd"} for value in argv):
        raise RuntimeError("release blocked: host preparation rejects npm.cmd and cmd.exe wrappers")
    if argv[2:] != ["--prefix", argv[3], "ci", "--ignore-scripts"]:
        raise RuntimeError("release blocked: host installer argv is not the reviewed npm ci contract")
    if not isinstance(contract.get("marker"), str) or not contract["marker"].startswith("citespan-host-install-"):
        raise RuntimeError("release blocked: host installer ownership marker is missing")
    if _file_identity(node) != contract.get("node") or _file_identity(npm_cli) != contract.get("npm_cli"):
        raise RuntimeError("release blocked: installed node/npm identities changed before launch")


def _wait_for_host_installer(
    contract: dict[str, Any], *, frontend_root: Path, timeout: int
) -> subprocess.CompletedProcess[str]:
    """Wait for the exact direct installer and retain its primary output."""
    _assert_installer_contract(contract)
    lock_name = hashlib.sha256(
        _canonical_windows_path_identity(frontend_root).encode("utf-8")
    ).hexdigest()
    lock_path = Path(tempfile.gettempdir()) / f"citespan-frontend-install-{lock_name}.lock"
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError(
            "release blocked: another owned frontend installer is active or its lock is stale: "
            f"frontend={_canonical_windows_path_identity(frontend_root)}"
        ) from exc
    try:
        with os.fdopen(lock_fd, "w", encoding="utf-8") as lock_file:
            lock_file.write(contract["marker"])
        return _wait_for_host_installer_locked(contract, frontend_root=frontend_root, timeout=timeout)
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _host_installer_descendants(root_pid: int) -> list[int]:
    """Read the current process census and return all descendants of the installer."""
    resources = _enumerate_fresh_frontend_resources()
    rows = resources.get("processes") if isinstance(resources, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError("release blocked: installer descendant census is incomplete")
    children: dict[int, list[int]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("release blocked: installer descendant census contains an invalid row")
        pid = row.get("pid")
        parent_pid = row.get("parent_pid")
        if isinstance(pid, bool) or not isinstance(pid, int) or pid < 0:
            raise RuntimeError("release blocked: installer descendant census has an invalid PID")
        if pid == 0:
            continue
        if isinstance(parent_pid, bool) or not isinstance(parent_pid, int) or parent_pid <= 0:
            raise RuntimeError(f"release blocked: installer descendant census has an invalid parent: pid={pid}")
        children.setdefault(parent_pid, []).append(pid)
    pending = list(children.get(root_pid, []))
    descendants: list[int] = []
    while pending:
        pid = pending.pop()
        if pid in descendants:
            continue
        descendants.append(pid)
        pending.extend(children.get(pid, []))
    return sorted(descendants)


def _host_installer_descendant_records(
    root_pid: int, contract: dict[str, Any]
) -> list[dict[str, Any]]:
    """Capture exact descendant identities in leaf-first order."""
    resources = _enumerate_fresh_frontend_resources()
    rows = resources.get("processes") if isinstance(resources, dict) else None
    read_errors = resources.get("read_errors") if isinstance(resources, dict) else None
    if not isinstance(rows, list) or not isinstance(read_errors, list):
        raise RuntimeError("release blocked: installer descendant census is incomplete")
    if read_errors:
        raise RuntimeError(f"release blocked: installer descendant census is unreadable: {read_errors}")
    children: dict[int, list[int]] = {}
    row_by_pid: dict[int, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("release blocked: installer descendant census contains an invalid row")
        pid = row.get("pid")
        parent_pid = row.get("parent_pid")
        if not _is_positive_pid(pid):
            continue
        if not _is_positive_pid(parent_pid):
            raise RuntimeError(f"release blocked: installer descendant census has an invalid parent: pid={pid}")
        row_by_pid[pid] = row
        children.setdefault(parent_pid, []).append(pid)

    ordered: list[int] = []
    active: set[int] = set()

    def visit(pid: int) -> None:
        if pid in active:
            raise RuntimeError(f"release blocked: installer descendant census contains a cycle: pid={pid}")
        active.add(pid)
        for child in children.get(pid, []):
            visit(child)
        active.remove(pid)
        if pid != root_pid:
            ordered.append(pid)

    visit(root_pid)
    records = []
    for pid in ordered:
        identity = _read_fresh_native_process_identity(pid, _NativeReadState())
        if identity.get("pid") != pid or not identity.get("creation"):
            raise RuntimeError(f"release blocked: installer descendant identity is incomplete: pid={pid}")
        row = row_by_pid[pid]
        command = str(identity.get("native_command") or row.get("command") or "")
        if not command or not _host_installer_command_matches_contract(command, contract):
            raise RuntimeError(
                "release blocked: installer descendant is not bound to the exact launch contract: "
                f"pid={pid}"
            )
        records.append(identity)
    return records


def _host_installer_command_matches_contract(command: str, contract: dict[str, Any]) -> bool:
    normalized = command.replace("\\", "/").casefold()
    return all(
        _host_path_identity(str(part)) in normalized
        for part in (contract["argv"][1], contract["argv"][3])
    ) and "ci" in normalized and "ignore-scripts" in normalized


def _terminate_host_installer_process(identity: dict[str, Any]) -> None:
    """Terminate one already validated Windows process identity."""
    if os.name != "nt":
        raise RuntimeError("release blocked: native installer cleanup requires Windows")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.TerminateProcess.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    handle = kernel32.OpenProcess(0x0001 | 0x1000 | 0x00100000, 0, identity["pid"])
    if not handle:
        error = ctypes.get_last_error()
        if error in (6, 87, 1168):
            raise _FreshProcessAbsent(f"pid={identity['pid']} is absent before stop")
        raise _FreshProcessUnreadable(f"pid={identity['pid']} stop handle open failed: WinError {error}")
    try:
        if not kernel32.TerminateProcess(handle, 1):
            raise RuntimeError(
                f"release blocked: installer process stop failed: pid={identity['pid']} "
                f"WinError {ctypes.get_last_error()}"
            )
    finally:
        if not kernel32.CloseHandle(handle):
            raise _FreshProcessUnreadable(
                f"pid={identity['pid']} stop handle close failed: WinError {ctypes.get_last_error()}"
            )


def _verify_host_installer_cleanup(
    identities: list[dict[str, Any]], *, frontend_root: Path
) -> dict[str, Any]:
    """Prove exact installer identities and owned resources are released."""
    states = {}
    for identity in identities:
        pid = identity["pid"]
        try:
            current = _read_fresh_native_process_identity(pid, _NativeReadState())
        except _FreshProcessAbsent:
            states[str(pid)] = "absent"
            continue
        except _FreshProcessUnreadable as exc:
            raise RuntimeError(f"release blocked: installer cleanup identity is unreadable: pid={pid}") from exc
        if current.get("creation") == identity["creation"]:
            raise RuntimeError(f"release blocked: exact installer identity remained live: pid={pid}")
        _validate_fresh_replacement_identity(current, identity["creation"], pid)
        states[str(pid)] = "reused"
    resources = _enumerate_fresh_frontend_resources()
    if resources.get("read_errors"):
        raise RuntimeError(f"release blocked: installer cleanup resource census is unreadable: {resources['read_errors']}")
    owned_pids = {identity["pid"] for identity in identities}
    for row in resources.get("processes", []):
        if isinstance(row, dict) and row.get("pid") in owned_pids:
            raise RuntimeError(f"release blocked: owned installer process remains in resource census: pid={row['pid']}")
    native_path = _host_path_identity((SCRIPT_ROOT / HOST_NATIVE_MODULE).resolve())
    for row in resources.get("holders", []):
        if not isinstance(row, dict) or row.get("pid") not in owned_pids:
            continue
        if any(_host_path_identity(str(path)) == native_path for path in row.get("module_paths", [])):
            raise RuntimeError(f"release blocked: owned installer native holder remains: pid={row['pid']}")
    scoped_ports = _configured_product_ports()
    for port, owner in _resource_port_records(resources.get("ports", [])):
        if port in scoped_ports and owner in owned_pids:
            raise RuntimeError(f"release blocked: owned installer listening port remains: port={port} pid={owner}")
    return {"identities": states, "resources": "released", "frontend": str(frontend_root.resolve())}


def _cleanup_host_installer_resources(
    process: Any,
    contract: dict[str, Any],
    *,
    frontend_root: Path,
    initial_root_identity: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str, str]:
    """Drain exact installer identities and owned resources before the deadline."""
    started_at = _monotonic_now()
    if started_at is None:
        raise RuntimeError("release blocked: installer cleanup clock is unavailable")
    deadline = started_at + HOST_INSTALLER_CLEANUP_TIMEOUT_SECONDS
    phase_times: dict[str, float] = {}
    identities: dict[tuple[int, str], dict[str, Any]] = {}
    terminal: dict[int, str] = {}
    stopped_pids: set[int] = set()
    initially_validated_pids: set[int] = set()

    def elapsed() -> float:
        now = _monotonic_now()
        if now is None:
            raise RuntimeError("release blocked: installer cleanup clock became unavailable")
        return now - started_at

    def require_budget() -> None:
        if elapsed() > HOST_INSTALLER_CLEANUP_TIMEOUT_SECONDS:
            raise RuntimeError(
                "installer timeout cleanup exceeded its bounded cleanup budget: "
                f"seconds={HOST_INSTALLER_CLEANUP_TIMEOUT_SECONDS} phase_times={phase_times}"
            )

    def measure_census() -> list[dict[str, Any]]:
        census_started = _monotonic_now()
        try:
            records = _host_installer_descendant_records(process.pid, contract)
        finally:
            measured = _measured_elapsed_seconds(census_started)
            if measured is not None:
                phase_times["census"] = phase_times.get("census", 0.0) + measured
        return records

    def bind(record: dict[str, Any]) -> None:
        pid = record.get("pid")
        creation = record.get("creation")
        if not _is_positive_pid(pid) or not isinstance(creation, str) or not creation:
            raise RuntimeError(f"release blocked: installer cleanup identity is incomplete: {record}")
        key = (pid, creation)
        for existing_pid, existing_creation in identities:
            if existing_pid == pid and existing_creation != creation:
                _validate_fresh_replacement_identity(
                    {"pid": pid, "creation": creation, "executable": record.get("executable"), "source_provenance": record.get("source_provenance")},
                    existing_creation,
                    pid,
                )
                terminal[pid] = "reused"
                return
        identities.setdefault(key, record)

    if initial_root_identity is not None:
        bind(initial_root_identity)
        initially_validated_pids.add(initial_root_identity["pid"])

    while True:
        require_budget()
        for record in measure_census():
            bind(record)

        live: list[dict[str, Any]] = []
        for identity in list(identities.values()):
            pid = identity["pid"]
            if pid in terminal:
                continue
            try:
                if pid in initially_validated_pids:
                    current = identity
                    initially_validated_pids.remove(pid)
                else:
                    current = _read_fresh_native_process_identity(pid, _NativeReadState())
            except _FreshProcessAbsent:
                terminal[pid] = "absent"
                continue
            except _FreshProcessUnreadable as exc:
                raise RuntimeError(
                    f"release blocked: installer cleanup identity is unreadable: pid={pid}"
                ) from exc
            if current.get("creation") != identity["creation"]:
                _validate_fresh_replacement_identity(current, identity["creation"], pid)
                terminal[pid] = "reused"
                continue
            live.append(identity)

        for identity in sorted(live, key=lambda item: item["pid"], reverse=True):
            if identity["pid"] in stopped_pids:
                continue
            require_budget()
            stop_started = _monotonic_now()
            _terminate_host_installer_process(identity)
            stopped_pids.add(identity["pid"])
            stopped = _measured_elapsed_seconds(stop_started)
            if stopped is not None:
                phase_times["stop"] = phase_times.get("stop", 0.0) + stopped

        if live:
            continue

        proof_started = _monotonic_now()
        proof = _verify_host_installer_cleanup(list(identities.values()), frontend_root=frontend_root)
        proved = _measured_elapsed_seconds(proof_started)
        if proved is not None:
            phase_times["final_proof"] = phase_times.get("final_proof", 0.0) + proved
        drain_started = _monotonic_now()
        stdout = ""
        stderr = ""
        while True:
            require_budget()
            try:
                stdout, stderr = process.communicate(timeout=0)
                break
            except subprocess.TimeoutExpired as exc:
                stdout = getattr(exc, "stdout", None) or getattr(exc, "output", None) or stdout
                stderr = getattr(exc, "stderr", None) or stderr
                time.sleep(0.01)
        drained = _measured_elapsed_seconds(drain_started)
        if drained is not None:
            phase_times["pipe_drain"] = phase_times.get("pipe_drain", 0.0) + drained
        return {"status": "measured", "descendant_state": "owned-identities-drained", "phase_times": phase_times, "proof": proof}, _bounded_subprocess_text(stdout), _bounded_subprocess_text(stderr)


def _format_installer_cleanup_failure(step: str, exc: BaseException) -> str:
    """Keep one installer cleanup failure with its step and traceback."""
    return (
        f"{type(exc).__name__}: {exc}\n"
        f"step={step}\n"
        f"traceback:\n{traceback.format_exc()}"
    )


def _wait_for_host_installer_locked(
    contract: dict[str, Any], *, frontend_root: Path, timeout: int
) -> subprocess.CompletedProcess[str]:
    """Run one installer while its frontend ownership lock is held."""
    environment = os.environ.copy()
    environment["CITESPAN_HOST_INSTALL_OWNER"] = contract["marker"]
    environment["CITESPAN_HOST_INSTALL_FRONTEND"] = str(frontend_root.resolve())
    process = None
    try:
        process = subprocess.Popen(
            contract["argv"],
            cwd=ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
        )
        stdout, stderr = process.communicate(timeout=timeout)
        if not _is_positive_pid(getattr(process, "pid", None)):
            raise RuntimeError("release blocked: direct frontend installer PID is unavailable")
        descendants = _host_installer_descendants(process.pid)
        if descendants:
            census, _, _ = _cleanup_host_installer_resources(
                process, contract, frontend_root=frontend_root
            )
            raise RuntimeError(
                "release blocked: direct frontend installer returned while owned descendants remained; "
                f"pids={descendants} cleanup={census} stdout={_sanitize_failure_text(stdout[-SUBPROCESS_DIAGNOSTIC_LIMIT:])} "
                f"stderr={_sanitize_failure_text(stderr[-SUBPROCESS_DIAGNOSTIC_LIMIT:])}"
            )
    except subprocess.TimeoutExpired as exc:
        primary_stdout = _bounded_subprocess_text(getattr(exc, "stdout", None) or getattr(exc, "output", None))
        primary_stderr = _bounded_subprocess_text(getattr(exc, "stderr", None))
        cleanup_failure = None
        descendant_census = None
        try:
            if process is None or not _is_positive_pid(getattr(process, "pid", None)):
                raise RuntimeError("installer root PID is unavailable")
            root_identity = None
            try:
                root_identity = _read_fresh_native_process_identity(process.pid, _NativeReadState())
                if not root_identity.get("creation"):
                    raise RuntimeError("installer root native creation token is unavailable")
                if not _host_installer_command_matches_contract(
                    str(root_identity.get("native_command") or ""), contract
                ):
                    raise RuntimeError("installer root is not bound to the exact launch contract")
            except _FreshProcessAbsent:
                root_identity = None
            descendant_census, _, _ = _cleanup_host_installer_resources(
                process,
                contract,
                frontend_root=frontend_root,
                initial_root_identity=root_identity,
            )
        except BaseException as cleanup_exc:
            cleanup_failure = _format_installer_cleanup_failure(
                "locked frontend dependency cleanup", cleanup_exc
            )
            if descendant_census is None:
                descendant_census = {"status": "read_failed", "read_failure": cleanup_failure}
        finally:
            drain_started = _monotonic_now()
            drain_failure = None
            try:
                stdout, stderr = process.communicate(timeout=0) if process is not None else ("", "")
            except (subprocess.TimeoutExpired, OSError) as drain_exc:
                drain_failure = _format_installer_cleanup_failure(
                    "locked frontend dependency final pipe drain", drain_exc
                )
                stdout, stderr = primary_stdout, primary_stderr
            drain_elapsed = _measured_elapsed_seconds(drain_started)
            if isinstance(descendant_census, dict) and drain_elapsed is not None:
                descendant_census.setdefault("phase_times", {})["pipe_drain"] = drain_elapsed
            if drain_failure:
                cleanup_failure = (
                    f"{cleanup_failure}\n{drain_failure}" if cleanup_failure else drain_failure
                )
            primary_stdout = _bounded_subprocess_text(primary_stdout or stdout)
            primary_stderr = _bounded_subprocess_text(primary_stderr or stderr)
            if process is not None:
                for stream_name in ("stdout", "stderr"):
                    stream = getattr(process, stream_name, None)
                    if stream is not None:
                        stream.close()
        evidence_path = _record_private_subprocess_timeout(
            step="locked frontend dependency preparation",
            argv_category="direct node/npm-cli installer",
            command=contract["argv"],
            timeout=exc,
            timeout_seconds=timeout,
            descendant_census=descendant_census,
            cleanup_failure=cleanup_failure,
        )
        raise RuntimeError(
            "release blocked: direct frontend installer timed out; "
            f"marker={contract['marker']} stdout={primary_stdout} stderr={primary_stderr} "
            f"cleanup_failure={cleanup_failure or 'none'} private evidence={evidence_path}"
        ) from exc
    finally:
        if process is not None:
            for stream_name in ("stdout", "stderr"):
                stream = getattr(process, stream_name, None)
                if stream is not None:
                    stream.close()
    return subprocess.CompletedProcess(contract["argv"], process.returncode, stdout, stderr)


def _prepare_frontend_dependencies(frontend_root: Path | None = None) -> dict[str, Any]:
    """Install the reviewed frontend lock through the direct Node/npm boundary."""
    frontend_root = (ROOT / "frontend") if frontend_root is None else Path(frontend_root)
    if not (frontend_root / "package.json").is_file() or not (frontend_root / "package-lock.json").is_file():
        raise RuntimeError(
            "release blocked: reviewed frontend package.json and package-lock.json are required "
            f"before locked dependency preparation: {frontend_root}"
        )
    findings = _critical_dependency_findings()
    if findings:
        raise RuntimeError(
            "release blocked: reviewed frontend dependency metadata is invalid before installation: "
            f"findings={findings}"
        )
    contract = _host_installer_contract(frontend_root)
    try:
        result = _wait_for_host_installer(
            contract,
            frontend_root=frontend_root,
            timeout=PLAYWRIGHT_PROVISION_TIMEOUT_SECONDS,
        )
    except RuntimeError:
        raise
    if type(result.returncode) is not int or result.returncode != 0:
        diagnostic_path = _record_private_dependency_install_failure(
            frontend_root=frontend_root,
            command=contract["argv"],
            result=result,
        )
        raise RuntimeError(
            "release blocked: locked frontend dependency preparation failed: "
            + json.dumps(
                {
                    "command_category": "direct node/npm-cli locked frontend dependency preparation",
                    "exit_code": result.returncode,
                    "stdout": _sanitize_failure_text(result.stdout[-SUBPROCESS_DIAGNOSTIC_LIMIT:]),
                    "stderr": _sanitize_failure_text(result.stderr[-SUBPROCESS_DIAGNOSTIC_LIMIT:]),
                    "private_diagnostic": str(diagnostic_path),
                    "ownership_marker": contract["marker"],
                },
                sort_keys=True,
            )
        )
    findings = _browser_dependency_findings(frontend_root)
    if findings:
        raise RuntimeError(
            "release blocked: locked frontend dependency preparation did not produce a usable install: "
            f"findings={findings}"
        )
    return {
        "state": "completed",
        "package_manager": "npm",
        "lockfile": "frontend/package-lock.json",
        "dependency_findings": findings,
    }
def _record_private_dependency_install_failure(
    *, frontend_root: Path, command: list[str], result: subprocess.CompletedProcess[str]
) -> Path:
    EXTERNAL_PROOF_ROOT.mkdir(parents=True, exist_ok=True)
    evidence_dir = Path(tempfile.mkdtemp(prefix="dependency-install-failure-", dir=EXTERNAL_PROOF_ROOT))
    evidence_path = evidence_dir / "failure.json"
    evidence_path.write_text(
        json.dumps(
            {
                "step": "locked frontend dependency preparation",
                "command_category": "direct node/npm-cli locked frontend dependency preparation",
                "frontend_root": _canonical_windows_path_identity(frontend_root),
                "argv": _redacted_subprocess_argv(command),
                "exit_code": result.returncode,
                "stdout": _sanitize_failure_text(result.stdout[-SUBPROCESS_DIAGNOSTIC_LIMIT:]),
                "stderr": _sanitize_failure_text(result.stderr[-SUBPROCESS_DIAGNOSTIC_LIMIT:]),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return evidence_path


def _prepare_host(frontend_root: Path | None = None) -> dict[str, Any]:
    """Prepare the host in the only permitted order before browser startup."""
    process_before = _validate_host_process_evidence()
    native = _prove_host_native_release()
    dependencies = _prepare_frontend_dependencies(frontend_root)
    _provision_live_verifier()
    process_after = _validate_host_process_evidence()
    readiness = _validate_browser_dependency_readiness(frontend_root, process=process_after)
    return _summarize_host_preparation({
        "process_before": process_before,
        "native_release": native,
        "dependencies": dependencies,
        "process_after": process_after,
        "readiness": readiness,
    })


def _critical_dependency_findings() -> list[str]:
    """Report frontend dependency metadata that blocks a release."""
    package_path = ROOT / "frontend" / "package.json"
    lock_path = ROOT / "frontend" / "package-lock.json"
    if not package_path.is_file() or not lock_path.is_file():
        return ["frontend/package.json and frontend/package-lock.json are required"]
    package = json.loads(package_path.read_text(encoding="utf-8"))
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    findings: list[str] = []
    frontend_root = package_path.parent
    installed_root = frontend_root / "node_modules"
    next_version = package.get("dependencies", {}).get("next")
    next_lock = lock.get("packages", {}).get("node_modules/next", {}).get("version")
    if next_version != next_lock:
        findings.append(
            "frontend/package.json and frontend/package-lock.json disagree on Next "
            f"(declared {next_version}, locked {next_lock})"
        )
    if next_version != "15.5.27":
        findings.append(
            "upgrade frontend/package.json and frontend/package-lock.json Next to the reviewed patched release "
            f"(declared {next_version}, locked {next_lock})"
        )
    packages = lock.get("packages", {})
    semver_pattern = re.compile(
        r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
        r"(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$"
    )

    def version_key(value: str) -> tuple[int, int, int, tuple[tuple[int, Any], ...]]:
        match = semver_pattern.fullmatch(value)
        if not match:
            raise ValueError(f"invalid semantic version {value!r}")
        prerelease = match.group(4)
        parts: list[tuple[int, Any]] = []
        if prerelease:
            for part in prerelease.split("."):
                parts.append((0, int(part)) if part.isdigit() else (1, part))
        return (int(match.group(1)), int(match.group(2)), int(match.group(3)), tuple(parts))

    def at_least(value: str, minimum: str) -> bool:
        return version_key(value) >= version_key(minimum)

    def lower_bound(spec: Any) -> str | None:
        if not isinstance(spec, str):
            return None
        match = re.search(r"(?<!\d)(\d+\.\d+\.\d+)(?:$|[^\d])", spec)
        return match.group(1) if match else None

    def package_entries(name: str) -> list[tuple[str, dict[str, Any]]]:
        return [
            (key, value)
            for key, value in packages.items()
            if (key == f"node_modules/{name}" or key.endswith(f"/node_modules/{name}"))
            and isinstance(value, dict)
        ]

    required_versions = {
        "next": "15.5.27",
        "eslint-config-next": "15.5.27",
        "shell-quote": "1.12.0",
        "tar": "7.5.22",
    }

    def check_registry_metadata(name: str, entries: list[tuple[str, dict[str, Any]]]) -> None:
        for key, value in entries:
            version = value.get("version")
            resolved = value.get("resolved")
            integrity = value.get("integrity")
            if not isinstance(version, str) or not semver_pattern.fullmatch(version):
                findings.append(f"{key} has an invalid semantic version")
                continue
            expected_url = f"https://registry.npmjs.org/{name}/-/{name}-{version}.tgz"
            if resolved != expected_url:
                findings.append(f"{key} has stale or mismatched registry metadata")
            if not isinstance(integrity, str) or not re.fullmatch(r"sha512-[A-Za-z0-9+/]+=*", integrity):
                findings.append(f"{key} has invalid lock integrity metadata")
            else:
                try:
                    digest = base64.b64decode(integrity.removeprefix("sha512-"), validate=True)
                except (ValueError, base64.binascii.Error):
                    digest = b""
                if len(digest) != hashlib.sha512().digest_size:
                    findings.append(f"{key} has mismatched authentic registry integrity metadata")
            expected = AUTHENTIC_REGISTRY_METADATA.get((name, version))
            if name in required_versions and expected != (resolved, integrity):
                findings.append(f"{key} has mismatched authentic registry integrity metadata")

    def check_installed_state(name: str, entries: list[tuple[str, dict[str, Any]]]) -> None:
        for key, value in entries:
            relative = key.removeprefix("node_modules/")
            installed_package = installed_root / relative / "package.json"
            if not installed_package.is_file():
                continue
            installed = json.loads(installed_package.read_text(encoding="utf-8"))
            if installed.get("version") != value.get("version"):
                findings.append(f"{key} installed version does not match package-lock.json")

    thresholds = {"shell-quote": "1.12.0", "tar": "7.5.22"}
    entries_by_name = {name: package_entries(name) for name in thresholds}
    for name, minimum in thresholds.items():
        entries = entries_by_name[name]
        check_registry_metadata(name, entries)
        check_installed_state(name, entries)
        versions = sorted({value["version"] for _, value in entries})
        try:
            vulnerable = any(not at_least(version, minimum) for version in versions)
        except ValueError as exc:
            findings.append(str(exc))
            vulnerable = True
        if vulnerable:
            findings.append(
                f"upgrade frontend/package.json and frontend/package-lock.json {name} and all locked transitive entries (versions {', '.join(versions)})"
            )

    concurrently_entries = package_entries("concurrently")
    check_registry_metadata("concurrently", concurrently_entries)
    for name, required_version in required_versions.items():
        entries = package_entries(name)
        if not entries:
            findings.append(f"{name} is required in the reviewed dependency records")
        elif not any(value.get("version") == required_version for _, value in entries):
            findings.append(f"{name} must resolve to the reviewed version {required_version}")
        check_registry_metadata(name, entries)
        check_installed_state(name, entries)
    overrides = package.get("overrides", {})
    shell_override = lower_bound(overrides.get("shell-quote")) if isinstance(overrides, dict) else None
    locked_shell_quote_versions = {
        value.get("version")
        for key, value in entries_by_name["shell-quote"]
        if isinstance(value.get("version"), str)
    }
    effective_shell_quote_is_patched = any(
        at_least(version, thresholds["shell-quote"])
        for version in locked_shell_quote_versions
    )
    for key, value in concurrently_entries:
        shell_range = value.get("dependencies", {}).get("shell-quote")
        shell_bound = lower_bound(shell_range)
        if shell_bound and not at_least(shell_bound, thresholds["shell-quote"]):
            if not effective_shell_quote_is_patched and (
                not shell_override or not at_least(shell_override, thresholds["shell-quote"])
            ):
                findings.append(
                    f"concurrently dependency tree {key} selects vulnerable shell-quote {shell_range}; add a patched npm override"
                )
    return findings


def _branding_findings() -> list[str]:
    """Find old names in public product surfaces and unscoped AI claims."""
    findings: list[str] = []
    old_name = re.compile(r"\b(?:(?i:ForensicAI)|(?i:UFDR Analyzer)|UFDR Report)\b")
    legacy_identifier_exceptions = {
        "fly.toml": re.compile(
            r'^\s*(?:app\s*=\s*"ufdr-analyzer-api"|'
            r'CORS_ALLOWED_ORIGINS\s*=\s*"https://ufdr-analyzer\.vercel\.app"|'
            r'POSTGRES_HOST\s*=\s*"ufdr-analyzer-db\.internal"|'
            r'MEILI_URL\s*=\s*"http://ufdr-analyzer-meili\.internal:7700"|'
            r'MINIO_ENDPOINT\s*=\s*"ufdr-analyzer-minio\.internal:9000")\s*$'
        ),
    }
    for name, text in _tracked_text():
        normalized_name = name.replace("\\", "/")
        findings.extend(_hosted_demo_documentation_findings(normalized_name, text))
        if name not in PUBLIC_BRANDING_PATHS and not (
            normalized_name.startswith("frontend/app/")
            or normalized_name.startswith("frontend/components/")
        ):
            continue
        public_text = re.sub(r"(?s)/\*.*?\*/", "", text)
        if normalized_name == "frontend/electron-builder.json":
            try:
                parsed_electron_config = json.loads(text)
            except json.JSONDecodeError:
                findings.append("frontend/electron-builder.json is malformed JSON")
                continue
            if not isinstance(parsed_electron_config, dict):
                findings.append("frontend/electron-builder.json must contain a JSON object")
                continue
            if "productName" not in parsed_electron_config:
                findings.append("frontend/electron-builder.json is missing productName")
                continue
            if parsed_electron_config["productName"] != "CiteSpan":
                findings.append(
                    "frontend/electron-builder.json productName must equal CiteSpan"
                )
                continue
            if "appId" not in parsed_electron_config:
                findings.append("frontend/electron-builder.json is missing appId")
                continue
            if parsed_electron_config["appId"] != "com.ufdr-analyzer.app":
                findings.append(
                    "frontend/electron-builder.json appId must equal com.ufdr-analyzer.app"
                )
                continue
        for line in public_text.splitlines():
            stripped = line.strip()
            comment_prefixes = ("//", "*", "/*", "*/")
            if Path(name).suffix in {".py", ".ts", ".tsx", ".sh", ".css"}:
                comment_prefixes += ("#",)
            if stripped.startswith(comment_prefixes):
                continue
            legacy_identifier = (
                re.search(r"(?i)\bufdr-analyzer(?:-[a-z0-9]+)*\b", line)
                if normalized_name in legacy_identifier_exceptions
                else None
            )
            legacy_allowed = legacy_identifier and legacy_identifier_exceptions.get(
                normalized_name, re.compile(r"a^")
            ).fullmatch(stripped)
            if old_name.search(line) or (legacy_identifier and not legacy_allowed):
                findings.append(f"old public product name remains in {name}")
                break
    unscoped = (
        "frontend/components/dashboard/data.ts",
        "frontend/components/dashboard/views/DataVisualizationView.tsx",
        "frontend/components/dashboard/views/GraphAnalysisView.tsx",
        "frontend/app/upload/page.tsx",
    )
    ai_claim = re.compile(r"(?i)AI[- ]powered|AI Forensic Assistant")
    for name in unscoped:
        path = ROOT / name
        if path.is_file() and ai_claim.search(path.read_text(encoding="utf-8")):
            findings.append(f"unscoped public AI claim requires scope expansion: {name}")
    return findings


def _hosted_demo_documentation_findings(
    name: str, text: str
) -> list[str]:
    """Reject active AI claims in current public documentation.

    Archived review transcripts and implementation files are excluded by the
    caller. Limitation text is allowed when it clearly describes the hosted
    deterministic demo contract.
    """
    if name not in CURRENT_PUBLIC_DOCUMENTATION_PATHS:
        return []
    findings: list[str] = []
    for line_number, statement in _documentation_statements(text):
        if not HOSTED_DEMO_AI_TERMS.search(statement):
            continue
        claim_text = HOSTED_DEMO_AI_LIMITATION_CLAUSES.sub(" ", statement)
        claim_text = HOSTED_DEMO_AI_LIMITATIONS.sub(" ", claim_text)
        if _has_nearby_active_ai_marker(claim_text):
            findings.append(
                f"active hosted AI claim in current documentation: {name}:{line_number}"
            )
    return findings


def _documentation_statements(text: str) -> list[tuple[int, str]]:
    """Return normalized statements with their first physical source line.

    Markdown wraps paragraphs and list items across physical lines. The claim
    scanner must classify the rendered statement, while retaining its source
    location for a useful finding.
    """
    statements: list[tuple[int, str]] = []
    parts: list[str] = []
    start_line: int | None = None

    def flush() -> None:
        nonlocal parts, start_line
        if not parts or start_line is None:
            parts = []
            start_line = None
            return
        rendered = re.sub(r"\s+", " ", " ".join(parts)).strip()
        for statement in re.split(r"(?<=[.!?])\s+", rendered):
            statement = statement.strip()
            if statement:
                statements.append((start_line, statement))
        parts = []
        start_line = None

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            flush()
            continue
        list_item = re.match(r"^(?:[-+*]|\d+[.)])\s+(.*)$", line)
        if list_item:
            flush()
            line = list_item.group(1)
        if start_line is None:
            start_line = line_number
        parts.append(line)
    flush()
    return statements


def _has_nearby_active_ai_marker(statement: str) -> bool:
    """Find an active marker attached to an AI or LLM term."""
    for term in HOSTED_DEMO_AI_TERMS.finditer(statement):
        window = statement[max(0, term.start() - 80) : term.end() + 80]
        if HOSTED_DEMO_AI_ACTIVE_MARKERS.search(window):
            return True
    return False


def _read_input() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        raise ValueError("deployment hook requires a JSON object on stdin")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("deployment hook input must be a JSON object")
    return value


def _action(payload: dict[str, Any]) -> str:
    action = payload.get("action_key")
    if not isinstance(action, str) or not action.strip():
        raise ValueError("deployment hook input requires a non-empty action_key")
    return action


def _expected_commit(payload: dict[str, Any]) -> str:
    intent = payload.get("intent")
    value = intent.get("expected_commit") if isinstance(intent, dict) else None
    if not value and isinstance(intent, dict):
        checkpoint = intent.get("checkpoint")
        if isinstance(checkpoint, dict):
            value = checkpoint.get("commit") or checkpoint.get("expected_commit")
    value = value or payload.get("expected_commit")
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("verification blocked: expected commit was not supplied")
    value = value.strip()
    if not re.fullmatch(r"[0-9a-fA-F]{40}", value):
        raise RuntimeError("verification blocked: expected commit must be a full git commit")
    return value.lower()


def _public_url(payload: dict[str, Any]) -> str:
    supplied = []
    for name in ("live_url", "public_url", "deployment_url"):
        value = _payload_value(payload, name)
        if value is not None:
            supplied.append((name, _validate_live_url(value, f"provider {name}")))
    if not supplied:
        return AUTHORIZED_LIVE_ORIGIN
    origins = {value for _, value in supplied}
    if len(origins) != 1:
        names = ", ".join(name for name, _ in supplied)
        raise RuntimeError(f"release blocked: provider URL aliases conflict: {names}")
    return supplied[0][1]


def _validate_live_url(value: Any, context: str = "live URL") -> str:
    if not isinstance(value, str):
        raise RuntimeError(f"release blocked: {context} is missing or is not a string")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise RuntimeError(f"release blocked: {context} is malformed") from exc
    if (
        parsed.scheme != "https"
        or parsed.netloc != DEPLOY_DOMAIN
        or parsed.hostname != DEPLOY_DOMAIN
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError(f"release blocked: {context} is not the authorized CiteSpan HTTPS origin")
    return AUTHORIZED_LIVE_ORIGIN


def _api_origin(payload: dict[str, Any]) -> str:
    value = _payload_value(payload, "api_origin")
    expected = f"{_public_url(payload)}/api"
    if value is not None and value.rstrip("/") != expected:
        raise RuntimeError("release blocked: provider API origin does not match the authorized live origin")
    return expected


def _payload_value(payload: dict[str, Any], name: str) -> Any:
    """Read a deployment setting from the provider payload, including intent."""
    candidates = [payload]
    intent = payload.get("intent")
    if isinstance(intent, dict):
        candidates.append(intent)
    for candidate in candidates:
        value = candidate.get(name)
        if value is not None:
            return value
        for container_name in (
            "deployment",
            "target",
            "runtime",
            "runtime_config",
            "release_config",
            "environment",
        ):
            container = candidate.get(container_name)
            if isinstance(container, dict) and name in container:
                return container[name]
    return None


def _enforce_hosted_demo_mode(payload: dict[str, Any]) -> str:
    """Enforce the hosted release demo invariant without ambient defaults."""
    configured = [("provider payload", _payload_value(payload, "DEMO_MODE"))]
    configured.append(("process environment", os.environ.get("DEMO_MODE")))
    enabled = {"1", "true", "yes", "on"}
    for source, value in configured:
        if value is None:
            continue
        normalized = str(value).strip().lower()
        if normalized not in enabled:
            raise RuntimeError(
                f"release blocked: {source} DEMO_MODE must be 1 for the hosted synthetic demo"
            )
    return "1"


def _observation_value(payload: dict[str, Any], name: str) -> Any:
    observation = payload.get("observation")
    if isinstance(observation, dict):
        return observation.get(name)
    return None


def _provider_payload(payload: dict[str, Any]) -> str:
    """Validate the payload emitted by DeploymentProvider.from_commands."""
    action = _action(payload)
    intent = payload.get("intent")
    if intent is not None and not isinstance(intent, (dict, str)):
        raise ValueError("deployment intent must be an object or string")
    if "observation" in payload and not isinstance(payload["observation"], (dict, type(None))):
        raise ValueError("deployment observation must be an object or null")
    return action


def _validate_raw_input(payload: dict[str, Any]) -> None:
    """Validate deterministic input invariants before host evidence access."""
    if not isinstance(payload, dict):
        raise ValueError("deployment hook input must be a JSON object")
    _action(payload)
    intent = payload.get("intent")
    if intent is not None and not isinstance(intent, (dict, str)):
        raise ValueError("deployment intent must be an object or string")
    if "observation" in payload and not isinstance(payload["observation"], (dict, type(None))):
        raise ValueError("deployment observation must be an object or null")
    _check_payload_secrets(payload)
    _check_payload_runtime_placeholders(payload)
    _enforce_hosted_demo_mode(payload)
    _expected_commit(payload)
    _public_url(payload)
    _api_origin(payload)


def _check_payload_secrets(payload: dict[str, Any]) -> None:
    """Reject literal target credentials without inspecting the supervisor environment."""
    def visit(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                visit(child_value, str(child_key))
            return
        if isinstance(value, list):
            for child_value in value:
                visit(child_value, key)
            return
        if not isinstance(value, str) or not SECRET_KEYS.search(key):
            return
        stripped = value.strip()
        if not stripped or any(reference in stripped for reference in SAFE_SECRET_REFERENCES):
            return
        raise RuntimeError("release blocked: target deployment input contains a literal credential")

    visit(payload)

    if _payload_value(payload, "secret_rotation") is not None:
        raise RuntimeError("release blocked: secret_rotation is provider-owned and must not be supplied")


def _check_payload_runtime_placeholders(payload: dict[str, Any]) -> None:
    """Reject unsafe values in nested provider runtime configuration."""

    def normalize_key(value: Any) -> str:
        return re.sub(r"[^A-Z0-9]", "_", str(value).upper()).strip("_")

    def required_key(value: Any) -> bool:
        return normalize_key(value) in REQUIRED_RUNTIME_SECRET_KEYS

    def secret_key(value: Any) -> bool:
        return bool(SECRET_KEYS.search(str(value)))

    def safe_component(value: Any) -> str:
        component = re.sub(r"[^A-Za-z0-9_.-]", "_", str(value))
        return component[:80] or "field"

    def path_for(path: tuple[str, ...]) -> str:
        return ".".join(path) or "payload"

    def inspect_value(value: Any, field: Any, path: tuple[str, ...]) -> None:
        is_required = required_key(field)
        is_secret = secret_key(field)
        if is_required and (not isinstance(value, str) or not value.strip()):
            raise RuntimeError(
                "release blocked: runtime configuration has a malformed required "
                f"secret at {path_for(path)}"
            )
        if (is_required or is_secret) and isinstance(value, str) and PLACEHOLDER_SECRET.fullmatch(value.strip()):
            raise RuntimeError(
                "release blocked: runtime configuration contains a placeholder at "
                f"{path_for(path)}"
            )

    def inspect_assignment(value: str, path: tuple[str, ...]) -> None:
        if "=" not in value:
            return
        field, assigned = value.split("=", 1)
        if not field or not (required_key(field) or secret_key(field)):
            return
        inspect_value(assigned, field, path + (safe_component(field),))

    visited: set[int] = set()

    def visit(value: Any, path: tuple[str, ...] = (), field: Any = None) -> None:
        if isinstance(value, dict):
            identity = id(value)
            if identity in visited:
                return
            visited.add(identity)
            for child_field, child_value in value.items():
                child_path = path + (safe_component(child_field),)
                inspect_value(child_value, child_field, child_path)
                visit(child_value, child_path, child_field)
            return
        if isinstance(value, list):
            identity = id(value)
            if identity in visited:
                return
            visited.add(identity)
            for index, child_value in enumerate(value):
                child_path = path + (f"[{index}]",)
                if isinstance(child_value, str):
                    inspect_assignment(child_value, child_path)
                visit(child_value, child_path, field)
            return
        if isinstance(value, str) and field is not None:
            inspect_assignment(value, path)

    visit(payload)


def _require_project_python(command: str) -> None:
    expected = PROJECT_PYTHON.resolve()
    try:
        actual = Path(sys.executable).resolve()
    except OSError as exc:
        raise RuntimeError(f"{command} command must use the project virtual-environment Python") from exc
    if actual != expected:
        raise RuntimeError(
            f"{command} command must use the project Python is missing or is not the project virtual-environment Python: {PROJECT_PYTHON}"
        )


def _windows_ssh_path() -> Path | None:
    system_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR")
    if not system_root:
        return None
    return Path(system_root) / "System32" / "OpenSSH" / "ssh.exe"


def _ssh_executable() -> Path:
    path_candidate = shutil.which("ssh")
    if path_candidate:
        path = Path(path_candidate)
        if path.is_file():
            return path.resolve()
    if os.name == "nt":
        standard_path = _windows_ssh_path()
        if standard_path is not None and standard_path.is_file():
            return standard_path.resolve()
    raise RuntimeError("release blocked: OpenSSH is unavailable")


def _ssh(command: str) -> str:
    try:
        key_exists = SSH_KEY.is_file()
    except OSError as exc:
        raise RuntimeError(f"release blocked: SSH key cannot be inspected: {SSH_KEY}") from exc
    if not key_exists:
        raise RuntimeError(f"release blocked: SSH key is missing: {SSH_KEY}")
    argv = [
        str(_ssh_executable()),
        "-i",
        SSH_KEY.as_posix(),
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        DEPLOY_HOST,
        "bash",
        "-seuo",
        "pipefail",
    ]
    try:
        result = subprocess.run(
            argv,
            input=command.encode("utf-8"),
            cwd=ROOT,
            capture_output=True,
            text=False,
            check=False,
            timeout=SSH_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        evidence_path = _record_private_ssh_timeout(command, exc)
        raise RuntimeError(
            "remote deployment command timed out; unknown external outcome; "
            f"the exact SSH client was terminated; private evidence: {evidence_path}"
        ) from exc
    except OSError as exc:
        detail = _sanitize_ssh_diagnostic(str(exc), command)
        raise RuntimeError(
            f"remote deployment process could not start: {detail}"
        ) from exc
    stdout = _decode_ssh_output(result.stdout, "stdout", result.returncode)
    stderr = _decode_ssh_output(result.stderr, "stderr", result.returncode)
    if result.returncode != 0:
        detail = _sanitize_ssh_diagnostic(
            stderr.strip() or stdout.strip() or "no remote error output",
            command,
        )
        raise RuntimeError(
            f"remote deployment command failed (exit code {result.returncode}): {detail}"
        )
    return stdout.strip()


def _decode_ssh_output(value: bytes, stream: str, returncode: int) -> str:
    try:
        return value.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        outcome = (
            f"remote deployment command failed (exit code {returncode}): "
            if returncode
            else "remote deployment output is invalid: "
        )
        raise RuntimeError(f"{outcome}{stream} is not valid UTF-8") from exc


def _sanitize_ssh_diagnostic(detail: str, command: str) -> str:
    """Remove the submitted script and known secret values from SSH diagnostics."""
    sanitized = detail.replace(command, "<submitted script>")
    if command.strip() != command:
        sanitized = sanitized.replace(command.strip(), "<submitted script>")
    for key_path in {SSH_KEY.as_posix(), str(SSH_KEY), str(SSH_KEY.resolve())}:
        sanitized = sanitized.replace(key_path, "<configured SSH key>")
    sanitized = sanitized.replace("CITESPAN_PRIVATE_SCRIPT_MARKER", "<redacted marker>")
    return _sanitize_failure_text(sanitized)


def _runtime_compromise_resolved(payload: dict[str, Any]) -> bool:
    """Prove that deployment replaces compromised history with safe runtime inputs."""
    default_runtime_value = re.compile(
        r"(?i)(openrouter|openai)_api_key\s*[:=]\s*(?:REPLACE_WITH|CHANGE_ME|CHANGEME)|"
        r"neo4j_password\s*[:=]\s*(?:REPLACE_WITH|CHANGE_ME|CHANGEME|neo4j_password)"
    )
    current_runtime_findings = []
    for name, text in _release_text():
        if name in RUNTIME_CONFIG_PATHS:
            if default_runtime_value.search(text) or any(
                pattern.search(text) for pattern in SECRET_PATTERNS
            ):
                current_runtime_findings.append(name)
    if current_runtime_findings:
        return False
    override = _compose_override(payload)
    command = _deployment_command(payload)
    return (
        'OPENAI_API_KEY: ""' in override
        and 'OPENROUTER_API_KEY: ""' in override
        and "neo4j_password=$(openssl rand -hex 32)" in command
        and "postgres_password=$(openssl rand -hex 32)" in command
        and "meili_master_key=$(openssl rand -hex 32)" in command
        and "minio_root_user=$(openssl rand -hex 16)" in command
        and "minio_root_password=$(openssl rand -hex 32)" in command
        and "secret_key=$(openssl rand -hex 32)" in command
    )


def _demo_run_id(payload: dict[str, Any]) -> str:
    value = _payload_value(payload, "demo_run_id") or _payload_value(payload, "run_id")
    if value is None:
        return CANONICAL_DEMO_RUN_ID
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}",
        value,
    ):
        raise RuntimeError("release blocked: canonical synthetic demo run id is required")
    value = value.lower()
    if value != CANONICAL_DEMO_RUN_ID:
        raise RuntimeError("release blocked: canonical synthetic demo identity is required")
    return value


def _required_demo_run_id(payload: dict[str, Any]) -> str:
    """Require the caller to bind live verification to one explicit demo run."""
    value = _payload_value(payload, "demo_run_id")
    if value is None:
        value = _payload_value(payload, "run_id")
    if value is None or not isinstance(value, str) or not value.strip():
        raise RuntimeError("verification blocked: demo run id is required from the caller")
    return _demo_run_id({"demo_run_id": value})


def _compose_override(payload: dict[str, Any]) -> str:
    api_origin = _api_origin(payload)
    run_id = _demo_run_id(payload)
    return "\n".join(
        [
            "services:",
            "  backend:",
            '    container_name: ${CITESPAN_DEPLOYMENT_ID}-backend',
            "    environment:",
            '      DEMO_MODE: "1"',
            '      OPENAI_API_KEY: ""',
            '      OPENROUTER_API_KEY: ""',
            '      NEO4J_PASSWORD: ${NEO4J_PASSWORD}',
            '      CITESPAN_DEPLOYMENT_ID: ${CITESPAN_DEPLOYMENT_ID}',
            f"      CITESPAN_DEMO_RUN_ID: {json.dumps(run_id)}",
            f"      CITESPAN_DEMO_OWNER_EMAIL: {json.dumps(CANONICAL_DEMO_OWNER_EMAIL)}",
            f"      CITESPAN_SYNTHETIC_MARKER: {json.dumps(CANONICAL_DEMO_MARKER)}",
            '      GRAPH_BACKEND: "postgres"',
            f"      CORS_ALLOWED_ORIGINS: {json.dumps(_public_url(payload))}",
            f"      PUBLIC_API_ORIGIN: {json.dumps(api_origin)}",
            '      CITESPAN_SYNTHETIC_ONLY: "1"',
            '      DATABASE_URL: postgresql://${POSTGRES_USER:-ufdr_user}:${POSTGRES_PASSWORD}@${CITESPAN_AUTHORITATIVE_POSTGRES}:5432/${POSTGRES_DB:-ufdr_analyzer}',
            '      MEILI_URL: http://${CITESPAN_AUTHORITATIVE_MEILI}:7700',
            '      MINIO_ENDPOINT: ${CITESPAN_AUTHORITATIVE_MINIO}:9000',
            "    ports: !override",
            '      - "127.0.0.1:${CITESPAN_BACKEND_PORT}:8000"',
            "  frontend:",
            '    container_name: ${CITESPAN_DEPLOYMENT_ID}-frontend',
            "    ports: !override",
            '      - "127.0.0.1:${CITESPAN_FRONTEND_PORT}:3000"',
            "networks:",
            "  ufdr_demo:",
            "    external: true",
            '    name: ${CITESPAN_AUTHORITATIVE_NETWORK}',
            "",
        ]
    )


def _normalize_rendered_backend_port(value: Any) -> int | None:
    """Normalize one Compose published port without accepting ambiguous forms."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        normalized = value
    elif (
        isinstance(value, str)
        and 1 <= len(value) <= 5
        and value[0] != "0"
        and all(character in "0123456789" for character in value)
    ):
        normalized = int(value)
    else:
        return None
    return normalized if 1 <= normalized <= 65535 else None


def _validate_rendered_backend_ports(config: dict[str, Any], allocated_port: int | str) -> None:
    """Require the rendered Compose backend ports to contain one loopback binding."""
    expected_port = _normalize_rendered_backend_port(allocated_port)
    if expected_port is None:
        raise RuntimeError("release blocked: allocated backend port is not an integer")
    services = config.get("services")
    backend = services.get("backend") if isinstance(services, dict) else None
    ports = backend.get("ports") if isinstance(backend, dict) else None
    if not isinstance(ports, list) or len(ports) != 1 or not isinstance(ports[0], dict):
        raise RuntimeError("release blocked: rendered Compose backend ports do not contain the exact allocated loopback backend binding")
    binding = ports[0]
    if (
        binding.get("host_ip") != "127.0.0.1"
        or _normalize_rendered_backend_port(binding.get("published")) != expected_port
        or binding.get("target") != 8000
        or binding.get("protocol") != "tcp"
    ):
        raise RuntimeError("release blocked: rendered Compose backend ports do not contain the exact allocated loopback backend binding")


def _compose_backend_port_validation_script() -> str:
    """Return the validator executed against Compose's rendered JSON output."""
    return """import json
import sys


def normalize_port(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        normalized = value
    elif (
        isinstance(value, str)
        and 1 <= len(value) <= 5
        and value[0] != "0"
        and all(character in "0123456789" for character in value)
    ):
        normalized = int(value)
    else:
        return None
    return normalized if 1 <= normalized <= 65535 else None


config = json.load(sys.stdin)
services = config.get("services")
backend = services.get("backend") if isinstance(services, dict) else None
ports = backend.get("ports") if isinstance(backend, dict) else None
expected = normalize_port(sys.argv[1])
message = "rendered Compose backend ports do not contain the exact allocated loopback backend binding"
assert expected is not None, message
assert isinstance(ports, list) and len(ports) == 1 and isinstance(ports[0], dict), message
binding = ports[0]
assert (
    binding.get("host_ip") == "127.0.0.1"
    and normalize_port(binding.get("published")) == expected
    and binding.get("target") == 8000
    and binding.get("protocol") == "tcp"
), message
"""


def _metadata_writer_script() -> str:
    """Return the atomic deployment metadata writer used on the host."""
    return """import hashlib
import json
import os
import sys
import tempfile

(
    network,
    postgres,
    meili,
    minio,
    postgres_volume,
    meili_volume,
    output,
    marker,
    runtime,
    deployment_id,
    backend_id,
    commit,
    live_url,
    backend_port,
    frontend_port,
    static_container,
    static_content_dir,
    runtime_identity,
    backend_identity,
    static_identity,
) = sys.argv[1:21]

data = {
    "network": network,
    "postgres": postgres,
    "meili": meili,
    "minio": minio,
    "postgres_volume": postgres_volume,
    "meili_volume": meili_volume,
    "minio_volume": "citespan-minio-data",
    "runtime_hash": hashlib.sha256(open(runtime, "rb").read()).hexdigest(),
    "marker": marker,
    "deployment_id": deployment_id,
    "backend_container": backend_id,
    "commit": commit,
    "live_url": live_url,
    "backend_port": int(backend_port),
    "frontend_port": int(frontend_port),
    "static_container": static_container,
    "static_content_dir": static_content_dir,
    "authoritative_network": network,
    "authoritative_postgres": postgres,
    "authoritative_meili": meili,
    "authoritative_minio": minio,
    "authoritative_data": True,
    "runtime_identity": runtime_identity,
    "backend_identity": backend_identity,
    "static_identity": static_identity,
    "synthetic_only": True,
}

temporary_path = None
try:
    output_directory = os.path.dirname(os.path.abspath(output))
    os.makedirs(output_directory, mode=0o700, exist_ok=True)
    descriptor, temporary_path = tempfile.mkstemp(
        dir=output_directory, prefix=".citespan-metadata-", suffix=".tmp"
    )
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(data, handle, sort_keys=True)
        handle.write("\\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary_path, 0o600)
    with open(temporary_path, encoding="utf-8") as handle:
        parsed = json.load(handle)
    if parsed != data:
        raise ValueError("metadata validation failed")
    os.replace(temporary_path, output)
    temporary_path = None
finally:
    if temporary_path is not None:
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass
"""


def _demo_seed_script() -> str:
    return """import datetime, json, os, uuid
from sqlmodel import Session, select
from database import engine
from db_setup import AleappArtifact, Message, Run, User

run_id = uuid.UUID(os.environ["CITESPAN_DEMO_RUN_ID"])
email = os.environ["CITESPAN_DEMO_OWNER_EMAIL"]
with Session(engine) as session:
    owner = session.exec(select(User).where(User.email == email)).first()
    if owner is None:
        owner = User(username="CiteSpan demo owner", email=email, password_hash="release-owner-disabled")
        session.add(owner)
        session.commit()
        session.refresh(owner)
    run = session.exec(select(Run).where(Run.id == run_id)).first()
    if run is not None:
        raise RuntimeError("candidate demo volume already contains the canonical run")
    run = Run(
        id=run_id,
        user_id=owner.id,
        ufdr_file_name="demo_synthetic.ufdr",
        status="complete",
        end_time=datetime.datetime.now(),
        extraction_metadata=json.dumps({
            "citespan_marker": os.environ["CITESPAN_SYNTHETIC_MARKER"],
            "synthetic_only": True,
            "sample_id": "canonical-v1",
            "owner_email": email,
        }, sort_keys=True),
    )
    session.add(run)
    session.add_all([
        Message(id=uuid.UUID("33333333-3333-4333-8333-333333333333"), run_id=run_id, sender="+15551234567", receiver="+15559876543", timestamp=datetime.datetime(2025, 3, 10, 14), content="Can you send the bitcoin wallet address for the transfer?"),
        Message(id=uuid.UUID("44444444-4444-4444-8444-444444444444"), run_id=run_id, sender="+15559876543", receiver="+15551234567", timestamp=datetime.datetime(2025, 3, 10, 16), content="Use the bank transfer reference for the synthetic sample."),
        AleappArtifact(id=uuid.UUID("22222222-2222-4222-8222-222222222222"), run_id=run_id, artifact_type="csv", filename="whatsapp_messages.csv", file_path="/synthetic/whatsapp_messages.csv", category="WhatsApp messages", row_count=1, data=json.dumps({"message": "The synthetic WhatsApp message confirms the bank transfer reference."}, sort_keys=True)),
    ])
    session.commit()
    assert run.ufdr_file_name == "demo_synthetic.ufdr"
    assert run.extraction_metadata and os.environ["CITESPAN_SYNTHETIC_MARKER"] in run.extraction_metadata
"""


def _demo_empty_check_script() -> str:
    return """from sqlmodel import Session, select
from database import engine
from db_setup import (
    AleappArtifact, AleappReport, AuditEvent, Call, Contact,
    EntityIndex, Media, Message, Result, Rule, Run, Transcript,
)

forensic_models = (
    Run, Message, AleappArtifact, AleappReport, Call, Contact, Media,
    Transcript, EntityIndex, Result, Rule, AuditEvent,
)
with Session(engine) as session:
    if any(session.exec(select(model)).first() is not None for model in forensic_models):
        print("EXISTING")
    else:
        print("EMPTY")
"""


def _demo_audit_script() -> str:
    return """import json, os, uuid
from sqlmodel import Session, select
from database import engine
from db_setup import (
    AleappArtifact, AleappReport, AuditEvent, Call, CaseMembership,
    Backup, Contact, EntityIndex, Media, Message, Query, Result, Rule, Run,
    Transcript, User,
)

canonical = uuid.UUID(os.environ["CITESPAN_DEMO_RUN_ID"])
marker = os.environ["CITESPAN_SYNTHETIC_MARKER"]
owner_email = os.environ["CITESPAN_DEMO_OWNER_EMAIL"]
canonical_messages = (
    ("+15551234567", "+15559876543", "Can you send the bitcoin wallet address for the transfer?"),
    ("+15559876543", "+15551234567", "Use the bank transfer reference for the synthetic sample."),
)
canonical_artifact = {
    "artifact_type": "csv",
    "filename": "whatsapp_messages.csv",
    "file_path": "/synthetic/whatsapp_messages.csv",
    "category": "WhatsApp messages",
    "row_count": 1,
    "data": json.dumps({"message": "The synthetic WhatsApp message confirms the bank transfer reference."}, sort_keys=True),
}

def canonical_count(model, expected, label):
    rows = session.exec(select(model)).all()
    if len(rows) != expected:
        raise RuntimeError(f"existing deployment does not match exact canonical sample; non-canonical {label} count: {len(rows)}")
    return rows

with Session(engine) as session:
    owner = session.exec(select(User).where(User.email == owner_email)).first()
    if owner is None:
        raise RuntimeError("existing deployment is missing the canonical demo owner")
    runs = canonical_count(Run, 1, "Run")
    run = runs[0]
    if run.id != canonical or run.user_id != owner.id or run.ufdr_file_name != "demo_synthetic.ufdr" or run.status != "complete" or run.file_content_hash is not None or run.original_file_path is not None:
        raise RuntimeError("existing deployment contains an unverified canonical run relationship")
    metadata = json.loads(run.extraction_metadata or "{}")
    if metadata != {"citespan_marker": marker, "owner_email": owner_email, "sample_id": "canonical-v1", "synthetic_only": True}:
        raise RuntimeError("existing deployment contains unverified forensic data")
    messages = canonical_count(Message, 2, "Message")
    observed_messages = tuple((item.sender, item.receiver, item.content) for item in sorted(messages, key=lambda item: item.timestamp))
    if any(item.run_id != canonical for item in messages) or observed_messages != canonical_messages:
        raise RuntimeError("existing deployment contains unverified message contents")
    canonical_message_ids = {str(item.id) for item in messages}
    artifacts = canonical_count(AleappArtifact, 1, "AleappArtifact")
    observed_artifacts = [{key: getattr(item, key) for key in canonical_artifact} for item in artifacts]
    if any(item.run_id != canonical for item in artifacts) or observed_artifacts != [canonical_artifact]:
        raise RuntimeError("existing deployment contains unverified artifacts")
    backups = session.exec(select(Backup)).all()
    forensic_backup_terms = ("snapshot", "forensic", "ufdr", "e01", "aff4", "sqlite", "artifact")
    for backup in backups:
        description = (backup.description or "").lower()
        snapshot_path = (backup.snapshot_path or "").lower()
        if backup.snapshot_path or any(term in description for term in forensic_backup_terms):
            raise RuntimeError("existing deployment contains an unverified Backup snapshot or forensic reference")
    users = session.exec(select(User)).all()
    permitted_users = {user.id for user in users}
    if owner.id not in permitted_users:
        raise RuntimeError("existing deployment contains an unverified canonical owner reference")
    for user in users:
        if not isinstance(user.id, uuid.UUID) or not isinstance(user.username, str) or not isinstance(user.email, str) or not isinstance(user.password_hash, str) or not isinstance(user.is_admin, bool):
            raise RuntimeError("existing deployment contains an unverified User row")
    if owner.username != "CiteSpan demo owner" or owner.email != owner_email or owner.password_hash != "release-owner-disabled" or owner.is_admin is not False:
        raise RuntimeError("existing deployment contains an unverified canonical demo owner")

    authorized_users = {owner.id}
    memberships = session.exec(select(CaseMembership)).all()
    for membership in memberships:
        if membership.run_id != canonical or membership.user_id not in permitted_users:
            raise RuntimeError("existing deployment contains an unverified CaseMembership")
        if membership.role == "owner":
            if membership.user_id != owner.id or membership.granted_by != owner.id:
                raise RuntimeError("existing deployment contains an unverified CaseMembership")
        elif membership.role == "viewer":
            if membership.user_id == owner.id or membership.granted_by != owner.id:
                raise RuntimeError("existing deployment contains an unverified CaseMembership")
            authorized_users.add(membership.user_id)
        else:
            raise RuntimeError("existing deployment contains an unverified CaseMembership")
    rules = session.exec(select(Rule)).all()
    if len(rules) > 1:
        raise RuntimeError("existing deployment contains an unverified Rule")
    rule_ids = set()
    for rule in rules:
        if rule.user_id not in authorized_users or not isinstance(rule.title, str) or not isinstance(rule.description, str) or not isinstance(rule.query_text, str) or not isinstance(rule.is_template, bool):
            raise RuntimeError("existing deployment contains an unverified Rule")
        rule_ids.add(rule.id)

    queries = session.exec(select(Query)).all()
    for query in queries:
        if query.run_id != canonical or query.user_id not in authorized_users or not isinstance(query.query_text, str) or query.status not in {"pending", "completed", "failed"} or not isinstance(query.result_count, int) or query.result_count < 0:
            raise RuntimeError("existing deployment contains an unverified Query")
        for field in (query.intent, query.parameters, query.results_summary, query.error_message):
            if field is not None and not isinstance(field, str):
                raise RuntimeError("existing deployment contains an unverified Query schema")

    results = session.exec(select(Result)).all()
    for result in results:
        if result.run_id != canonical or result.rule_id not in rule_ids or result.result_type != "message" or (result.confidence_score is not None and not isinstance(result.confidence_score, (int, float))):
            raise RuntimeError("existing deployment contains an unverified Result")
        try:
            evidence = json.loads(result.evidence_data)
        except (TypeError, json.JSONDecodeError):
            raise RuntimeError("existing deployment contains an unverified Result row")
        if not isinstance(evidence, dict) or evidence.get("source") != "synthetic" or not set(evidence).issubset({"source", "citations", "evidence_spans"}):
            raise RuntimeError("existing deployment contains an unverified Result row")
        for key in ("citations", "evidence_spans"):
            values = evidence.get(key, [])
            if not isinstance(values, list) or any(not isinstance(item, dict) or not set(item).issubset({"kind", "id", "source_id", "start", "end"}) or any(not isinstance(value, (str, int)) for value in item.values()) for item in values):
                raise RuntimeError("existing deployment contains an unverified Result row")
            for item in values:
                if item.get("kind") is not None and item["kind"] != "message":
                    raise RuntimeError("existing deployment contains an unverified Result evidence reference")
                for reference_key in ("id", "source_id"):
                    if reference_key in item and item[reference_key] not in canonical_message_ids:
                        raise RuntimeError("existing deployment contains an unverified Result evidence reference")

    events = session.exec(select(AuditEvent)).all()
    allowed_event_types = {"query", "ingest", "export", "user_login", "user_signup", "demo_reset"}
    legacy_payload_keys = {"action", "result_count", "sample_id", "synthetic_only", "status", "run_id", "user_id"}
    query_payload_keys = {"question", "planner", "plan", "sql", "total", "row_ids"}
    allowed_payload_keys = legacy_payload_keys | query_payload_keys
    canonical_evidence_ids = {
        str(value).replace("-", "")
        for value in (canonical_message_ids | {str(item.id) for item in artifacts})
    }

    def fail_event():
        raise RuntimeError("existing deployment contains an unverified AuditEvent")

    def validate_query_payload(payload, event):
        if set(payload) != query_payload_keys or event.event_type != "query":
            fail_event()
        question = payload["question"]
        if not isinstance(question, str) or not question.strip() or payload["planner"] != "stub":
            fail_event()
        if not isinstance(payload["sql"], str) or not payload["sql"].lstrip().upper().startswith("SELECT"):
            fail_event()
        if not isinstance(payload["total"], int) or payload["total"] < 0:
            fail_event()
        row_ids = payload["row_ids"]
        if not isinstance(row_ids, list) or len(row_ids) != payload["total"] or len(set(row_ids)) != len(row_ids):
            fail_event()
        if any(not isinstance(row_id, str) or row_id.replace("-", "") not in canonical_evidence_ids for row_id in row_ids):
            fail_event()
        try:
            from ai.planner import _stub_plan
            from ai.query_plan import QueryPlan
            expected_plan = _stub_plan(question)
            observed_plan = QueryPlan.model_validate(payload["plan"])
            if observed_plan.model_dump(mode="json") != expected_plan.model_dump(mode="json"):
                fail_event()
            if observed_plan.compile().rendered_sql != payload["sql"]:
                fail_event()
        except Exception as exc:
            if isinstance(exc, RuntimeError):
                raise
            fail_event()
    for event in events:
        if event.event_type not in allowed_event_types or (event.run_id is not None and event.run_id != canonical) or (event.user_id is not None and event.user_id not in authorized_users):
            fail_event()
        if event.user_id is not None and event.user_id != owner.id and event.user_id not in authorized_users:
            fail_event()
        try:
            payload = json.loads(event.payload or "{}")
        except (TypeError, json.JSONDecodeError):
            fail_event()
        if not isinstance(payload, dict) or not set(payload).issubset(allowed_payload_keys):
            fail_event()
        if query_payload_keys & set(payload):
            validate_query_payload(payload, event)
            continue
        if payload.get("action") is not None and payload["action"] not in allowed_event_types:
            fail_event()
        if payload.get("sample_id") is not None and payload["sample_id"] != "canonical-v1":
            fail_event()
        if payload.get("synthetic_only") is not None and payload["synthetic_only"] is not True:
            fail_event()
        if payload.get("result_count") is not None and (not isinstance(payload["result_count"], int) or payload["result_count"] < 0):
            fail_event()
        if payload.get("status") is not None and payload["status"] not in {"pending", "completed", "failed"}:
            fail_event()
        if payload.get("run_id") is not None and payload["run_id"] != str(canonical):
            fail_event()
        if payload.get("user_id") is not None and payload["user_id"] not in {str(value) for value in permitted_users}:
            fail_event()
        if any(not isinstance(value, (str, int, bool, type(None))) for value in payload.values()):
            fail_event()

    # These tables carry no canonical hosted-demo rows. Any existing row is
    # unsafe because its full content cannot be matched to the sample.
    for model, label in (
        (EntityIndex, "EntityIndex"), (Transcript, "Transcript"),
        (Call, "Call"), (Contact, "Contact"), (Media, "Media"),
        (AleappReport, "AleappReport"),
    ):
        canonical_count(model, 0, label)
"""


def _receipt_writer() -> str:
    return """import hashlib, json, os, sys, tempfile
from pathlib import Path

receipt, runtime, marker, network, postgres, meili, minio = sys.argv[1:8]
path = Path(receipt)
state = json.loads(path.read_text(encoding=\"utf-8\")) if path.exists() else {}
state.update({\"runtime_hash\": hashlib.sha256(Path(runtime).read_bytes()).hexdigest(), \"marker\": marker, \"network\": network, \"postgres\": postgres, \"meili\": meili, \"minio\": minio, \"postgres_volume\": \"citespan-postgres-data\", \"meili_volume\": \"citespan-meili-data\", \"minio_volume\": \"citespan-minio-data\", \"resources\": state.get(\"resources\", {name: {\"created\": False, \"ready\": False} for name in (\"network\", \"postgres\", \"meili\", \"minio\")})})
if len(sys.argv) == 10:
    state[\"resources\"][sys.argv[8]][sys.argv[9]] = True
fd, temporary_name = tempfile.mkstemp(dir=str(path.parent), prefix=\".citespan-receipt-\")
os.close(fd)
temporary = Path(temporary_name)
try:
    temporary.write_text(json.dumps(state, sort_keys=True) + \"\\n\", encoding=\"utf-8\")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
finally:
    if temporary.exists():
        temporary.unlink()
"""


def _receipt_validate() -> str:
    return """import hashlib, json, sys
from pathlib import Path

receipt, runtime, marker, network, postgres, meili, minio = sys.argv[1:]
data = json.loads(Path(receipt).read_text(encoding=\"utf-8\"))
assert data[\"runtime_hash\"] == hashlib.sha256(Path(runtime).read_bytes()).hexdigest()
assert data[\"marker\"] == marker and data[\"network\"] == network and data[\"postgres\"] == postgres and data[\"meili\"] == meili and data[\"minio\"] == minio
assert data[\"postgres_volume\"] == \"citespan-postgres-data\" and data[\"meili_volume\"] == \"citespan-meili-data\" and data[\"minio_volume\"] == \"citespan-minio-data\"
assert set(data[\"resources\"]) == {\"network\", \"postgres\", \"meili\", \"minio\"}
assert all(set(state) == {\"created\", \"ready\"} for state in data[\"resources\"].values())
assert all(isinstance(value, bool) for state in data[\"resources\"].values() for value in state.values())
assert all(not state[\"ready\"] or state[\"created\"] for state in data[\"resources\"].values())
    """


def _readiness_sanitizer() -> str:
    return """sanitize_probe_output() {
    local value="$1"
    local secret
    for secret in "$OPENAI_API_KEY" "$OPENROUTER_API_KEY" "$NEO4J_PASSWORD" "$POSTGRES_PASSWORD" "$MEILI_MASTER_KEY" "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY" "$SECRET_KEY"; do
        if [ -n "$secret" ]; then
            value=${value//"$secret"/[REDACTED]}
        fi
    done
    printf '%s' "$value"
}"""


def _minio_readiness_command(receipt_writer: str) -> str:
    return f"""failed_step=readiness-minio
minio_ready=0
command -v curl >/dev/null 2>&1 || {{
    echo 'readiness failed: MinIO permanent probe fault; cause=curl is missing' >&2
    exit 1
}}
minio_identity=$(docker inspect -f '{{{{.Name}}}}' "$authoritative_minio" 2>&1)
minio_identity_status=$?
minio_identity_cause=$(sanitize_probe_output "$minio_identity")
if [ "$minio_identity_status" -ne 0 ] || [ "$minio_identity" != "/$authoritative_minio" ]; then
    echo "readiness failed: MinIO permanent probe fault; cause=container identity check failed: $minio_identity_cause" >&2
    exit 1
fi
minio_ip=$(docker inspect -f '{{{{range .NetworkSettings.Networks}}}}{{{{.IPAddress}}}}{{{{end}}}}' "$authoritative_minio" 2>&1)
minio_inspect_status=$?
minio_ip_cause=$(sanitize_probe_output "$minio_ip")
if [ "$minio_inspect_status" -ne 0 ] || [ -z "$minio_ip" ]; then
    echo "readiness failed: MinIO permanent probe fault; cause=container IP check failed: $minio_ip_cause" >&2
    exit 1
fi
last_readiness_cause='container is not ready'
for readiness_attempt in $(seq 1 30); do
    minio_probe_error=$(mktemp)
    set +e
    minio_http_status=$(curl --silent --show-error --output /dev/null --write-out '%{{http_code}}' "http://$minio_ip:9000/minio/health/ready" 2>"$minio_probe_error")
    readiness_status=$?
    set -e
    readiness_output="http_status=$minio_http_status curl_status=$readiness_status $(cat "$minio_probe_error")"
    last_readiness_cause=$(sanitize_probe_output "$readiness_output")
    rm -f "$minio_probe_error"
    printf '%s\\n' "service=minio identity=$authoritative_minio ip=$minio_ip attempt=$readiness_attempt status=$readiness_status cause=$last_readiness_cause" >> "$readiness_evidence"
    if [ "$readiness_status" -eq 0 ] && [ "$minio_http_status" = 200 ]; then
        minio_ready=1
        break
    fi
    if [ "$readiness_status" -eq 127 ] || printf '%s' "$readiness_output" | grep -Eqi 'not found|invalid|malformed|unauthorized|authentication|permission denied|wrong identity'; then
        echo "readiness failed: MinIO permanent probe fault; cause=$last_readiness_cause; see $readiness_evidence" >&2
        exit 1
    fi
    sleep 1
done
if [ "$minio_ready" -ne 1 ]; then
    echo "readiness failed: MinIO timed out; last_cause=$last_readiness_cause; see $readiness_evidence" >&2
    exit 1
fi
python3 -c {receipt_writer} "$receipt" "$runtime" "$CITESPAN_SYNTHETIC_MARKER" "$authoritative_network" "$authoritative_postgres" "$authoritative_meili" "$authoritative_minio" minio ready
"""


def _candidate_backend_readiness_command() -> str:
    """Return the bounded readiness probe for the single candidate backend."""
    return _readiness_sanitizer() + r'''
failed_step=candidate-backend-readiness
candidate_ready=0
candidate_expected_name="/$CITESPAN_DEPLOYMENT_ID-backend"
candidate_state=unknown
candidate_health_status=unknown
candidate_http_status=000
candidate_curl_status=1
candidate_readiness_cause='candidate backend is not ready'
candidate_health_body=$(mktemp)
candidate_probe_error=$(mktemp)
candidate_health_body_context=unknown
candidate_health_validation_status=1
capture_candidate_failure() {
    printf '%s\n' "service=candidate-backend attempt=$readiness_attempt identity=$candidate_backend expected_name=$candidate_expected_name port=$backend_port state=$candidate_state health_status=$candidate_health_status http_status=$candidate_http_status curl_status=$candidate_curl_status health_validation_status=$candidate_health_validation_status health_body=$candidate_health_body_context cause=$candidate_readiness_cause" >> "$readiness_evidence"
    set +e
    candidate_logs=$(docker logs "$candidate_backend" 2>&1)
    candidate_logs_status=$?
    set -e
    printf '%s\n' "candidate_logs_status=$candidate_logs_status logs=$(sanitize_probe_output "$candidate_logs")" >> "$readiness_evidence"
}
readiness_deadline=$((SECONDS + 190))
readiness_attempt=0
while :; do
    readiness_attempt=$((readiness_attempt + 1))
    if [ "$SECONDS" -ge "$readiness_deadline" ]; then
        candidate_readiness_cause='candidate readiness deadline exceeded'
        capture_candidate_failure
        echo "readiness failed: candidate backend deadline exceeded; see $readiness_evidence" >&2
        exit 1
    fi
    set +e
    candidate_identity=$(docker inspect -f '{{.Id}}' "$candidate_backend" 2>&1)
    candidate_identity_status=$?
    candidate_name=$(docker inspect -f '{{.Name}}' "$candidate_backend" 2>&1)
    candidate_name_status=$?
    candidate_state=$(docker inspect -f '{{.State.Status}}' "$candidate_backend" 2>&1)
    candidate_state_status=$?
    candidate_health_status=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$candidate_backend" 2>&1)
    candidate_health_inspect_status=$?
    set -e
    candidate_identity=$(sanitize_probe_output "$candidate_identity")
    candidate_name=$(sanitize_probe_output "$candidate_name")
    candidate_state=$(sanitize_probe_output "$candidate_state")
    candidate_health_status=$(sanitize_probe_output "$candidate_health_status")
    if [ "$candidate_identity_status" -ne 0 ] || [ "$candidate_identity" != "$candidate_backend" ]; then
        candidate_readiness_cause='candidate identity check failed'
        capture_candidate_failure
        echo "readiness failed: candidate backend permanent identity failure; see $readiness_evidence" >&2
        exit 1
    fi
    if [ "$candidate_name_status" -ne 0 ] || [ "$candidate_name" != "$candidate_expected_name" ]; then
        candidate_readiness_cause='candidate name check failed'
        capture_candidate_failure
        echo "readiness failed: candidate backend permanent name failure; see $readiness_evidence" >&2
        exit 1
    fi
    if [ "$candidate_state_status" -ne 0 ] || [ "$candidate_health_inspect_status" -ne 0 ] || [ "$candidate_state" = exited ] || [ "$candidate_state" = dead ]; then
        candidate_readiness_cause='candidate container exited or inspect failed'
        capture_candidate_failure
        echo "readiness failed: candidate backend permanent startup failure; see $readiness_evidence" >&2
        exit 1
    fi
    : > "$candidate_health_body"
    : > "$candidate_probe_error"
    candidate_probe_remaining=$((readiness_deadline - SECONDS))
    if [ "$candidate_probe_remaining" -le 0 ]; then
        candidate_readiness_cause='candidate readiness deadline exceeded before health probe'
        capture_candidate_failure
        echo "readiness failed: candidate backend deadline exceeded before health probe; see $readiness_evidence" >&2
        exit 1
    fi
    candidate_connect_timeout=2
    if [ "$candidate_probe_remaining" -lt "$candidate_connect_timeout" ]; then
        candidate_connect_timeout=$candidate_probe_remaining
    fi
    candidate_max_time=5
    if [ "$candidate_probe_remaining" -lt "$candidate_max_time" ]; then
        candidate_max_time=$candidate_probe_remaining
    fi
    set +e
    candidate_http_status=$(curl --silent --show-error --connect-timeout "$candidate_connect_timeout" --max-time "$candidate_max_time" --output "$candidate_health_body" --write-out '%{http_code}' "http://127.0.0.1:$backend_port/health/" 2>"$candidate_probe_error")
    candidate_curl_status=$?
    set -e
    candidate_curl_context=$(cat "$candidate_probe_error")
    candidate_curl_context=$(sanitize_probe_output "$candidate_curl_context")
    if [ "$candidate_curl_status" -eq 0 ] && [ "$candidate_http_status" = 200 ]; then
        set +e
        candidate_health_body_context=$(cat "$candidate_health_body")
        candidate_health_body_context=$(sanitize_probe_output "$candidate_health_body_context")
        python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); assert value == {"status": "OK"}' "$candidate_health_body" >/dev/null 2>&1
        candidate_health_validation_status=$?
        set -e
        if [ "$candidate_health_validation_status" -eq 0 ]; then
            candidate_ready=1
            candidate_readiness_cause='health response is valid'
            printf '%s\n' "service=candidate-backend identity=$candidate_backend expected_name=$candidate_expected_name port=$backend_port attempt=$readiness_attempt state=$candidate_state health_status=$candidate_health_status http_status=$candidate_http_status curl_status=$candidate_curl_status cause=$candidate_readiness_cause" >> "$readiness_evidence"
            break
        fi
        candidate_readiness_cause="invalid health response: parser_status=$candidate_health_validation_status body=$candidate_health_body_context"
        capture_candidate_failure
        echo "readiness failed: candidate backend permanent health response failure; see $readiness_evidence" >&2
        exit 1
    fi
    candidate_readiness_cause="health probe failed: $candidate_curl_context"
    printf '%s\n' "service=candidate-backend identity=$candidate_backend expected_name=$candidate_expected_name port=$backend_port attempt=$readiness_attempt state=$candidate_state health_status=$candidate_health_status http_status=$candidate_http_status curl_status=$candidate_curl_status cause=$candidate_readiness_cause" >> "$readiness_evidence"
    if [ "$candidate_curl_status" -eq 127 ] || printf '%s' "$candidate_curl_context" | grep -Eqi 'not found|invalid|malformed|unauthorized|authorization|authentication|permission denied|wrong identity'; then
        capture_candidate_failure
        echo "readiness failed: candidate backend permanent health probe failure; see $readiness_evidence" >&2
        exit 1
    fi
    if [ "$((readiness_deadline - SECONDS))" -lt 1 ]; then
        candidate_readiness_cause='candidate readiness deadline exceeded before sleep'
        capture_candidate_failure
        echo "readiness failed: candidate backend deadline exceeded before sleep; see $readiness_evidence" >&2
        exit 1
    fi
    sleep 1
done
rm -f "$candidate_health_body" "$candidate_probe_error"
if [ "$candidate_ready" -ne 1 ]; then
    capture_candidate_failure
    echo "readiness failed: candidate backend timed out; see $readiness_evidence" >&2
    exit 1
fi
'''


def _minio_source_build_definition() -> str:
    """Return the controlled Dockerfile that compiles the official MinIO source."""
    _validate_immutable_source_commits()
    _validate_immutable_minio_images()
    return f"""FROM {MINIO_BUILDER_IMAGE} AS builder
WORKDIR /src
COPY . .
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -o /out/minio ./ && chmod 0755 /out/minio

FROM {MINIO_RUNTIME_IMAGE}
RUN apk add --no-cache ca-certificates
COPY --from=builder /out/minio /usr/bin/minio
VOLUME [\"/data\"]
ENTRYPOINT [\"/usr/bin/minio\"]
CMD [\"server\", \"/data\"]
"""


def _minio_source_preflight_script() -> str:
    """Return a fail-closed, temporary-only MinIO source build preflight."""
    _validate_immutable_source_commits()
    definition = base64.b64encode(_minio_source_build_definition().encode()).decode()
    return f"""minio_source_preflight() {{
    command -v docker >/dev/null 2>&1 || {{ echo 'source build dependency unavailable: docker' >&2; exit 1; }}
    command -v git >/dev/null 2>&1 || {{ echo 'source build dependency unavailable: git' >&2; exit 1; }}
    work_dir=$(mktemp -d)
    trap 'rm -rf \"$work_dir\"' RETURN
    if ! git clone --quiet --filter=blob:none --branch {shlex.quote(MINIO_SOURCE_REVISION)} --depth 1 {shlex.quote(MINIO_SOURCE_REPOSITORY)} \"$work_dir/minio\"; then
        echo 'minio source checkout failed' >&2
        exit 1
    fi
    source_revision=$(git -C \"$work_dir/minio\" rev-parse HEAD 2>/dev/null) || {{ echo 'minio source checkout failed: revision unavailable' >&2; exit 1; }}
    case \"$source_revision\" in
        {MINIO_SOURCE_COMMIT}) ;;
        *) echo 'minio source checkout failed: verified revision mismatch' >&2; exit 1 ;;
    esac
    printf %s {shlex.quote(definition)} | base64 -d > \"$work_dir/minio/Dockerfile.citespan\" || {{ echo 'minio source build definition failed' >&2; exit 1; }}
    docker pull {shlex.quote(MINIO_BUILDER_IMAGE)} >/dev/null 2>&1 || {{ echo 'source build dependency unavailable: official builder image' >&2; exit 1; }}
    docker pull {shlex.quote(MINIO_RUNTIME_IMAGE)} >/dev/null 2>&1 || {{ echo 'source build dependency unavailable: official runtime image' >&2; exit 1; }}
    if ! docker build --pull=false --file \"$work_dir/minio/Dockerfile.citespan\" --tag {shlex.quote(MINIO_IMAGE)} \"$work_dir/minio\" >/dev/null; then
        echo 'minio source compilation failed' >&2
        exit 1
    fi
    minio_image={shlex.quote(MINIO_IMAGE)}
}}
"""


def _authoritative_reconciliation_script(receipt_writer_source: str) -> str:
    """Return shell checks that preserve compatible partial data resources."""
    receipt_writer = shlex.quote(receipt_writer_source)
    return f"""reconcile_authoritative_resources() {{
    if docker network inspect \"$authoritative_network\" >/dev/null 2>&1; then
        python3 -c {receipt_writer} \"$receipt\" \"$runtime\" \"$CITESPAN_SYNTHETIC_MARKER\" \"$authoritative_network\" \"$authoritative_postgres\" \"$authoritative_meili\" \"$authoritative_minio\" network created
    elif [ \"$(python3 -c 'import json,sys; print(int(json.load(open(sys.argv[1]))[\"resources\"][\"network\"][\"created\"]))' \"$receipt\")\" -eq 1 ]; then
        echo 'incompatible authoritative network: receipt owns a missing network' >&2
        exit 1
    else
        docker network create \"$authoritative_network\"
        python3 -c {receipt_writer} \"$receipt\" \"$runtime\" \"$CITESPAN_SYNTHETIC_MARKER\" \"$authoritative_network\" \"$authoritative_postgres\" \"$authoritative_meili\" \"$authoritative_minio\" network created
    fi
    for service in postgres meili minio; do
        case \"$service\" in
            postgres) container=\"$authoritative_postgres\"; expected_image=postgres:17-alpine; volume=citespan-postgres-data; image_field=postgres ;;
            meili) container=\"$authoritative_meili\"; expected_image=getmeili/meilisearch:v1.15; volume=citespan-meili-data; image_field=meili ;;
            minio) container=\"$authoritative_minio\"; expected_image=\"$minio_image\"; volume=citespan-minio-data; image_field=minio ;;
        esac
        if docker inspect \"$container\" >/dev/null 2>&1; then
            docker inspect \"$container\" | python3 -c 'import json, os, sys
data = json.load(sys.stdin)[0]
service, expected_image, network, volume = sys.argv[1:5]
if data.get("Config", {{}}).get("Image") != expected_image:
    raise SystemExit(f"incompatible authoritative {{service}} image")
if set(data.get("NetworkSettings", {{}}).get("Networks", {{}})) != {{network}}:
    raise SystemExit(f"incompatible authoritative {{service}} network")
destinations = {{"postgres": "/var/lib/postgresql/data", "meili": "/meili_data", "minio": "/data"}}
mounts = data.get("Mounts", [])
expected_mount = {{"Type": "volume", "Name": volume, "Destination": destinations[service], "RW": True}}
if len(mounts) != 1 or any(mount.get(key) != value for mount in mounts for key, value in expected_mount.items()):
    raise SystemExit(f"incompatible authoritative {{service}} volume")
env = {{item.split("=", 1)[0]: item.split("=", 1)[1] for item in data.get("Config", {{}}).get("Env", []) if "=" in item}}
required = {{"postgres": ("POSTGRES_USER", "POSTGRES_DB", "POSTGRES_PASSWORD"), "meili": ("MEILI_MASTER_KEY",), "minio": ("MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY")}}[service]
if any(env.get(key) != os.environ.get(key) for key in required):
    raise SystemExit(f"incompatible authoritative {{service}} credentials")
' \"$service\" \"$expected_image\" \"$authoritative_network\" \"$volume\"
            python3 -c {receipt_writer} \"$receipt\" \"$runtime\" \"$CITESPAN_SYNTHETIC_MARKER\" \"$authoritative_network\" \"$authoritative_postgres\" \"$authoritative_meili\" \"$authoritative_minio\" \"$image_field\" created
        fi
    done
}}
"""


def _guarded_orphan_recovery_script() -> str:
    """Return the one-time, exact-identity orphan recovery operation."""
    return f'''guarded_orphan_recovery() {{
    orphan_evidence=$(mktemp /tmp/citespan-orphan-recovery.XXXXXX) || {{ echo 'orphan recovery blocked: evidence creation failed' >&2; exit 70; }}
    chmod 600 "$orphan_evidence" || {{ echo 'orphan recovery blocked: evidence protection failed' >&2; exit 70; }}
    umask 077
    cleanup_orphan_temps() {{ rm -f "${{preservation_before:-}}" "${{preservation_after:-}}" "${{receipt_before:-}}" "${{receipt_after:-}}" "${{old_backup_before:-}}" "${{old_backup_after:-}}" "${{inspect_buffer:-}}" "${{process_rows_file:-}}"; }}
    trap cleanup_orphan_temps EXIT
    record_orphan() {{ printf '%s\\n' "$1" >> "$orphan_evidence"; }}
    recovery_receipt={DEPLOY_PATH}/.citespan-authoritative-receipt.json
    orphan_backup_dir={ORPHAN_BACKUP_DIR}
    runtime_file={DEPLOY_PATH}/.citespan-runtime.env
    test -f "$recovery_receipt" && test -f "$runtime_file" && test -d "$orphan_backup_dir" && test -n "$(find "$orphan_backup_dir" -type f -print -quit)" || {{ record_orphan 'operation=preservation-proof result=refused cause=authoritative-receipt-runtime-or-old-backup-missing'; echo "orphan recovery blocked: authoritative preservation proof is unavailable; evidence=$orphan_evidence" >&2; exit 70; }}
    sanitize_orphan() {{
        local text="$1" secret_name secret_value
        for secret_name in OPENAI_API_KEY OPENROUTER_API_KEY NEO4J_PASSWORD POSTGRES_PASSWORD MEILI_MASTER_KEY MINIO_ROOT_PASSWORD MINIO_SECRET_KEY SECRET_KEY; do
            secret_value="${{!secret_name-}}"
            if [ -n "$secret_value" ]; then
                text=${{text//"$secret_value"/<REDACTED>}}
            fi
        done
        sed -E 's/(PASSWORD|SECRET|KEY|TOKEN|AUTHORIZATION|API_KEY)([=:][^ ]*)/<REDACTED>/Ig' <<<"$text"
    }}
    inspect_orphan() {{
        local output status identity="$1" operation="$2" inspect_buffer
        inspect_buffer=$(mktemp /tmp/citespan-orphan-inspect.XXXXXX) || {{ record_orphan "operation=$operation result=incomplete-cleanup cause=inspection-buffer-creation-failed"; orphan_inspect_state=unknown; return 0; }}
        chmod 600 "$inspect_buffer" || {{ rm -f "$inspect_buffer"; record_orphan "operation=$operation result=incomplete-cleanup cause=inspection-buffer-protection-failed"; orphan_inspect_state=unknown; return 0; }}
        if docker inspect --format '{{{{.Id}}}}\t{{{{.Name}}}}\t{{{{.State.Status}}}}\t{{{{index .Config.Labels "com.docker.compose.project"}}}}\t{{{{index .Config.Labels "com.docker.compose.service"}}}}' "$identity" >"$inspect_buffer" 2>&1; then
            status=0
        else
            status=$?
        fi
        output=$(sanitize_orphan "$(cat "$inspect_buffer" 2>/dev/null)")
        rm -f "$inspect_buffer"
        record_orphan "operation=$operation identity=$identity docker_exit_status=$status cause=$output"
        if [ "$status" -eq 0 ]; then
            orphan_inspect_state=present
        elif [ "$status" -ne 0 ] && grep -Fqx "Error: No such object: $identity" <<<"$output"; then
            orphan_inspect_state=absent
        elif [ "$status" -ne 0 ] && grep -Fqx "No such object: $identity" <<<"$output"; then
            orphan_inspect_state=absent
        else
            orphan_inspect_state=unknown
        fi
    }}
    inspect_orphan {ORPHAN_CONTAINER_ID} initial
    case "$orphan_inspect_state" in
        absent)
            record_orphan 'operation=orphan-recovery result=already-confirmed-absent'
            return 0
            ;;
        unknown)
            record_orphan 'operation=orphan-recovery result=incomplete-cleanup cause=initial-inspection-unprovable'
            echo "orphan recovery blocked: initial inspection is not a recognized missing-container result; evidence=$orphan_evidence" >&2
            exit 70
            ;;
    esac
    orphan_record=$(docker inspect --format '{{{{.Id}}}}	{{{{.Name}}}}	{{{{.State.Status}}}}	{{{{index .Config.Labels "com.docker.compose.project"}}}}	{{{{index .Config.Labels "com.docker.compose.service"}}}}' {ORPHAN_CONTAINER_ID} 2>&1) || {{ record_orphan "operation=orphan-identity docker_exit_status=$? cause=$(sanitize_orphan \"$orphan_record\")"; echo "orphan recovery blocked: identity inspection failed; evidence=$orphan_evidence" >&2; exit 70; }}
    record_orphan "operation=orphan-identity identity=$(sanitize_orphan \"$orphan_record\")"
    IFS=$'\\t' read -r -a orphan_fields <<<"$orphan_record"
    [ "${{#orphan_fields[@]}}" -eq 5 ] || {{ record_orphan 'operation=orphan-identity result=refused cause=field-count-mismatch'; echo "orphan recovery blocked: identity field count is not five; evidence=$orphan_evidence" >&2; exit 70; }}
    orphan_id="${{orphan_fields[0]}}"
    orphan_name="${{orphan_fields[1]}}"
    orphan_state="${{orphan_fields[2]}}"
    orphan_project="${{orphan_fields[3]}}"
    orphan_service="${{orphan_fields[4]}}"
    [ "$orphan_id" = "{ORPHAN_CONTAINER_ID}" ] && [ "$orphan_name" = "/{ORPHAN_CONTAINER_NAME}" ] && [ "$orphan_project" = "{ORPHAN_DEPLOYMENT_ID}" ] && [ "$orphan_service" = "backend" ] || {{ record_orphan 'operation=orphan-identity result=refused cause=identity-or-ownership-mismatch'; echo "orphan recovery blocked: identity or ownership mismatch; evidence=$orphan_evidence" >&2; exit 70; }}
    case "$orphan_state" in created|running|paused|restarting|removing|exited|dead) ;; *) record_orphan 'operation=orphan-identity result=refused cause=invalid-container-state'; echo "orphan recovery blocked: container state is invalid; evidence=$orphan_evidence" >&2; exit 70 ;; esac
    current_pid=$$
    current_ancestry=" $current_pid "
    while [ "$current_pid" -gt 1 ]; do
        if ! ancestry_row=$(ps -o pid=,ppid= -p "$current_pid" 2>&1); then
            record_orphan 'operation=process-proof result=incomplete-cleanup cause=process-ancestry-query-failed'
            echo "orphan recovery blocked: process ancestry query failed; evidence=$orphan_evidence" >&2
            exit 70
        fi
        [[ "$ancestry_row" != *$'\n'* ]] || {{ record_orphan 'operation=process-proof result=incomplete-cleanup cause=process-ancestry-ambiguous'; echo "orphan recovery blocked: process ancestry is ambiguous; evidence=$orphan_evidence" >&2; exit 70; }}
        read -r ancestry_pid ancestry_parent <<<"$ancestry_row"
        [[ "$ancestry_pid" =~ ^[0-9]+$ && "$ancestry_parent" =~ ^[0-9]+$ ]] || {{ record_orphan 'operation=process-proof result=incomplete-cleanup cause=process-ancestry-ambiguous'; echo "orphan recovery blocked: process ancestry is ambiguous; evidence=$orphan_evidence" >&2; exit 70; }}
        current_ancestry+="$ancestry_parent "
        current_pid="$ancestry_parent"
    done
    process_rows_file=$(mktemp /tmp/citespan-process-rows.XXXXXX) || {{ echo "orphan recovery blocked: process evidence creation failed; evidence=$orphan_evidence" >&2; exit 70; }}
    chmod 600 "$process_rows_file" || {{ echo "orphan recovery blocked: process evidence protection failed; evidence=$orphan_evidence" >&2; exit 70; }}
    if ps -eo pid=,ppid=,args= >"$process_rows_file" 2>&1; then
        process_query_status=0
    else
        process_query_status=$?
    fi
    process_query_output=$(sanitize_orphan "$(cat "$process_rows_file" 2>/dev/null)")
    record_orphan "operation=process-proof query_exit_status=$process_query_status cause=$process_query_output"
    [ "$process_query_status" -eq 0 ] || {{ record_orphan 'operation=process-proof result=incomplete-cleanup cause=process-query-failed'; echo "orphan recovery blocked: process query failed; evidence=$orphan_evidence" >&2; exit 70; }}
    process_match_status=0
    process_matches=$(CITESPAN_ORPHAN_ACTION_KEY="{ORPHAN_ACTION_KEY}" python3 - "$current_ancestry" "$process_rows_file" 2>&1 <<'PY'
import os
import shlex
import sys

ancestry = {{int(value) for value in sys.argv[1].split() if value}}
action_key = os.environ["CITESPAN_ORPHAN_ACTION_KEY"]
try:
    rows_path = sys.argv[2] if len(sys.argv) > 2 else "-"
    rows_text = sys.stdin.read() if rows_path == "-" else open(rows_path, encoding="utf-8").read()
except (OSError, UnicodeError) as exc:
    print(f"parse-error: {{type(exc).__name__}}")
    raise SystemExit(70)

matches = []
for line in rows_text.splitlines():
    fields = line.strip().split(None, 2)
    if len(fields) != 3:
        print("parse-error: malformed-process-row")
        raise SystemExit(70)
    try:
        pid, parent = (int(fields[0]), int(fields[1]))
    except ValueError:
        print("parse-error: non-numeric-process-identity")
        raise SystemExit(70)
    try:
        argv = shlex.split(fields[2], posix=True)
    except ValueError:
        print("parse-error: ambiguous-process-argv")
        raise SystemExit(70)
    if not argv:
        print("parse-error: empty-process-argv")
        raise SystemExit(70)
    if pid in ancestry:
        continue
    executable = os.path.basename(argv[0]).lower()
    is_old_release_transport = executable == "bash" and argv[1:] == ["-seuo", "pipefail"]
    is_old_release = action_key in argv
    is_npm_build = executable in {{"npm", "npm.cmd", "npm-cli", "npm-cli.js"}} and (argv[1:2] == ["build"] or argv[1:3] == ["run", "build"])
    is_next_build = executable in {{"next", "next.cmd"}} and argv[1:2] == ["build"]
    is_shell_command = executable in {{"sh", "bash"}} and argv[1:2] == ["-c"]
    shell_command = []
    if is_shell_command:
        if len(argv) < 3:
            print("parse-error: missing-shell-command")
            raise SystemExit(70)
        try:
            shell_command = shlex.split(argv[2], posix=True)
        except ValueError:
            print("parse-error: ambiguous-shell-command")
            raise SystemExit(70)
    is_shell_builder = shell_command[:2] == ["next", "build"]
    is_shell_action = action_key in shell_command
    if is_old_release_transport or is_old_release or is_npm_build or is_next_build or is_shell_builder or is_shell_action:
        matches.append(f"pid={{pid}} ppid={{parent}} argv={{shlex.join(argv)}}")
print("\\n".join(matches))
PY
    ) || process_match_status=$?
    if [ "$process_match_status" -ne 0 ]; then
        sanitized_process_matches=$(sanitize_orphan "$process_matches")
        record_orphan "operation=process-proof result=incomplete-cleanup cause=process-match-query-failed detail=$sanitized_process_matches"
        echo "orphan recovery blocked: process enumeration or parsing is ambiguous; evidence=$orphan_evidence" >&2
        exit 70
    elif [ -n "$process_matches" ]; then
        record_orphan "operation=process-proof result=refused cause=$(sanitize_orphan \"$process_matches\")"
        echo "orphan recovery blocked: old release or frontend builder is alive; evidence=$orphan_evidence" >&2
        exit 70
    fi
    preservation_before=$(mktemp /tmp/citespan-preservation-before.XXXXXX) || {{ echo "orphan recovery blocked: preservation evidence creation failed; evidence=$orphan_evidence" >&2; exit 70; }}
    chmod 600 "$preservation_before"
    inspect_authoritative_container() {{ docker inspect --format '{{{{.Id}}}}\t{{{{.Name}}}}\t{{{{.State.Status}}}}\t{{{{.Config.Image}}}}\t{{{{range $network, $_ := .NetworkSettings.Networks}}}}{{{{$network}}}},{{{{end}}}}\t{{{{range .Mounts}}}}{{{{.Type}}}}:{{{{.Name}}}}:{{{{.Destination}}}}:{{{{.RW}}}},{{{{end}}}}' "$1"; }}
    inspect_authoritative_network() {{ docker network inspect --format '{{{{.ID}}}}\t{{{{.Name}}}}\t{{{{.Driver}}}}\t{{{{.Scope}}}}\t{{{{range .IPAM.Config}}}}{{{{.Subnet}}}}:{{{{.Gateway}}}},{{{{end}}}}' "$1"; }}
    inspect_authoritative_volume() {{ docker volume inspect --format '{{{{.Name}}}}\t{{{{.Driver}}}}\t{{{{.Mountpoint}}}}\t{{{{.Scope}}}}' "$1"; }}
    preservation_identity() {{
        inspect_authoritative_network citespan-authoritative-network || return 1
        for resource in citespan-authoritative-postgres citespan-authoritative-meili citespan-authoritative-minio; do inspect_authoritative_container "$resource" || return 1; done
        for volume in citespan-postgres-data citespan-meili-data citespan-minio-data; do inspect_authoritative_volume "$volume" || return 1; done
        test -n "\${{backup_dir:-}}" && test -d "$backup_dir" || return 1
        find "$backup_dir" -maxdepth 1 -type f -print0 | sort -z | xargs -0 sha256sum || return 1
    }}
    old_backup_identity() {{ find "$orphan_backup_dir" -type f -print0 | sort -z | xargs -0 sha256sum; }}
    preservation_identity | sha256sum >> "$preservation_before" || {{ record_orphan 'operation=preservation-proof result=refused cause=authoritative-resource-inspection-failed'; echo "orphan recovery blocked: authoritative resource proof failed; evidence=$orphan_evidence" >&2; exit 70; }}
    receipt_before=$(mktemp /tmp/citespan-receipt-before.XXXXXX) || {{ echo "orphan recovery blocked: receipt evidence creation failed; evidence=$orphan_evidence" >&2; exit 70; }}
    chmod 600 "$receipt_before"
    sha256sum "$runtime_file" "$recovery_receipt" > "$receipt_before" || {{ echo "orphan recovery blocked: runtime or receipt proof failed; evidence=$orphan_evidence" >&2; exit 70; }}
    old_backup_before=$(mktemp /tmp/citespan-old-backup-before.XXXXXX) || {{ echo "orphan recovery blocked: old backup evidence creation failed; evidence=$orphan_evidence" >&2; exit 70; }}
    chmod 600 "$old_backup_before"
    old_backup_identity > "$old_backup_before" || {{ echo "orphan recovery blocked: old backup proof failed; evidence=$orphan_evidence" >&2; exit 70; }}
    record_orphan "operation=preservation-proof phase=before digest=$(sha256sum \"$preservation_before\" | cut -d' ' -f1)"
    docker stop {ORPHAN_CONTAINER_ID} >/dev/null 2>&1 || {{ record_orphan "operation=stop identity={ORPHAN_CONTAINER_ID} result=failed"; echo "orphan recovery failed: exact container stop failed; evidence=$orphan_evidence" >&2; exit 70; }}
    docker rm {ORPHAN_CONTAINER_ID} >/dev/null 2>&1 || {{ record_orphan "operation=remove identity={ORPHAN_CONTAINER_ID} result=failed"; echo "orphan recovery failed: exact container removal failed; evidence=$orphan_evidence" >&2; exit 70; }}
    inspect_orphan {ORPHAN_CONTAINER_ID} post-removal
    [ "$orphan_inspect_state" = absent ] || {{ record_orphan "operation=post-removal result=incomplete-cleanup state=$orphan_inspect_state"; echo "orphan recovery failed: exact container absence is unproved; evidence=$orphan_evidence" >&2; exit 70; }}
    preservation_after=$(mktemp /tmp/citespan-preservation-after.XXXXXX) || {{ echo "orphan recovery failed: post-preservation evidence creation failed; evidence=$orphan_evidence" >&2; exit 70; }}
    chmod 600 "$preservation_after"
    preservation_identity | sha256sum >> "$preservation_after" || {{ echo "orphan recovery failed: authoritative resource changed or disappeared; evidence=$orphan_evidence" >&2; exit 70; }}
    receipt_after=$(mktemp /tmp/citespan-receipt-after.XXXXXX) || {{ echo "orphan recovery failed: receipt evidence creation failed; evidence=$orphan_evidence" >&2; exit 70; }}
    chmod 600 "$receipt_after"
    sha256sum "$runtime_file" "$recovery_receipt" > "$receipt_after" || {{ echo "orphan recovery failed: runtime or receipt changed or disappeared; evidence=$orphan_evidence" >&2; exit 70; }}
    old_backup_after=$(mktemp /tmp/citespan-old-backup-after.XXXXXX) || {{ echo "orphan recovery failed: old backup evidence creation failed; evidence=$orphan_evidence" >&2; exit 70; }}
    chmod 600 "$old_backup_after"
    old_backup_identity > "$old_backup_after" || {{ echo "orphan recovery failed: old backup changed or disappeared; evidence=$orphan_evidence" >&2; exit 70; }}
    cmp -s "$preservation_before" "$preservation_after" || {{ record_orphan 'operation=preservation-proof result=failed cause=authoritative-state-mismatch'; echo "orphan recovery failed: authoritative state changed; evidence=$orphan_evidence" >&2; exit 70; }}
    cmp -s "$receipt_before" "$receipt_after" || {{ record_orphan 'operation=preservation-proof result=failed cause=authoritative-receipt-changed'; echo "orphan recovery failed: authoritative receipt changed; evidence=$orphan_evidence" >&2; exit 70; }}
    cmp -s "$old_backup_before" "$old_backup_after" || {{ record_orphan 'operation=preservation-proof result=failed cause=old-backup-changed'; echo "orphan recovery failed: immutable old backup changed; evidence=$orphan_evidence" >&2; exit 70; }}
    record_orphan "operation=orphan-recovery result=complete identity={ORPHAN_CONTAINER_ID} name={ORPHAN_CONTAINER_NAME} volume_deletion=none"
    cleanup_orphan_temps
    trap - EXIT
}}
'''


def _cleanup_inspection_script() -> str:
    """Return the tri-state container inspection used by rollback cleanup."""
    return r'''    inspect_container_state() {
        inspect_operation="$1"
        inspect_identity="$2"
        inspect_output=$(mktemp "$rollback_evidence.inspect.XXXXXX") || { cleanup_status=70; cleanup_cause='inspection buffer creation failed'; return 1; }
        chmod 600 "$inspect_output" 2>/dev/null || { cleanup_status=70; cleanup_cause='inspection buffer protection failed'; rm -f "$inspect_output"; return 1; }
        if docker inspect --format '{{.Id}}\t{{.Name}}\t{{.State.Running}}\t{{.State.Status}}' "$inspect_identity" >"$inspect_output" 2>&1; then
            inspect_status=0
        else
            inspect_status=$?
        fi
        inspect_cause=$(sanitize_probe_output "$(cat "$inspect_output" 2>/dev/null)")
        printf '%s\n' "$inspect_operation: identity=$inspect_identity docker_exit_status=$inspect_status cause=$inspect_cause" >> "$recovery_log"
        if ! rm -f "$inspect_output" || [ -e "$inspect_output" ]; then
            cleanup_status=70
            cleanup_cause="${inspect_cause:+$inspect_cause; }inspection buffer removal failed"
            return 1
        fi
        if [ "$inspect_status" -eq 0 ]; then
            IFS=$'\t' read -r inspect_id inspect_name inspect_running inspect_status_name <<<"$inspect_cause"
            if [ "$inspect_running" != true ] && [ "$inspect_running" != false ]; then
                cleanup_status=70
                cleanup_cause='container running state is not true or false'
                return 1
            fi
            inspect_state=present
            inspect_running="$inspect_running"
        elif [ "$inspect_status" -ne 0 ] && printf '%s\n' "$inspect_cause" | grep -Fqx "Error: No such object: $inspect_identity"; then
            inspect_state=absent
        elif [ "$inspect_status" -ne 0 ] && printf '%s\n' "$inspect_cause" | grep -Fqx "No such object: $inspect_identity"; then
            inspect_state=absent
        else
            inspect_state=unknown
        fi
        return 0
    }
'''


def _deployment_command_authoritative(payload: dict[str, Any]) -> str:
    """Build a candidate-only transaction over one authoritative data-service state."""
    expected_commit = _expected_commit(payload)
    expected = shlex.quote(expected_commit)
    override = shlex.quote(base64.b64encode(_compose_override(payload).encode()).decode())
    seed = shlex.quote(base64.b64encode(_demo_seed_script().encode()).decode())
    audit = shlex.quote(base64.b64encode(_demo_audit_script().encode()).decode())
    empty_check = shlex.quote(base64.b64encode(_demo_empty_check_script().encode()).decode())
    history_values = _history_secret_hashes()
    history_hashes = " ".join(shlex.quote(value) for value in history_values)
    if history_values:
        history_check = (
            "if [ \"$history_hash_count\" -eq 0 ]; then :; else "
            f"for compromised_hash in {history_hashes}; do test -n \"$compromised_hash\"; done; fi; "
        )
    else:
        history_check = 'if [ "$history_hash_count" -eq 0 ]; then :; fi; '
    domain_value = _public_url(payload).removeprefix("https://").rstrip("/")
    domain = shlex.quote(domain_value)
    run_id = shlex.quote(_demo_run_id(payload))
    port_check = shlex.quote(_compose_backend_port_validation_script())
    candidate_readiness = _candidate_backend_readiness_command()
    runtime_check = shlex.quote(_runtime_validation_script(history_values))
    origin_check = shlex.quote(_remote_origin_check_script())
    receipt_writer_source = _receipt_writer()
    receipt_writer = shlex.quote(receipt_writer_source)
    receipt_validate = shlex.quote(_receipt_validate())
    minio_preflight = _minio_source_preflight_script()
    reconciliation = _authoritative_reconciliation_script(receipt_writer_source)
    orphan_recovery = _guarded_orphan_recovery_script()
    rollback_script = f"""rollback() {{
    status=$?
    set +e
    rollback_evidence="${{recovery_log}}.failure"
    umask 077
    : > "$rollback_evidence"
    chmod 600 "$rollback_evidence"
    exec >>"$rollback_evidence" 2>&1
    : > "$recovery_log"
    chmod 600 "$recovery_log"
    record_recovery() {{
        if ! printf '%s\\n' "$1" >> "$recovery_log" 2>/dev/null; then
            rollback_incomplete=1
        fi
    }}
    record_failure() {{
        printf '%s\\n' "$1" >> "$rollback_evidence"
    }}
    cleanup_command() {{
        cleanup_operation="$1"
        shift
        cleanup_diagnostic=$(mktemp "$rollback_evidence.cleanup.XXXXXX") || {{
            cleanup_status=70
            cleanup_cause='diagnostic buffer creation failed'
            return 1
        }}
        chmod 600 "$cleanup_diagnostic" 2>/dev/null || {{
            cleanup_status=70
            cleanup_cause='diagnostic buffer protection failed'
            rm -f "$cleanup_diagnostic"
            return 1
        }}
        "$@" >"$cleanup_diagnostic" 2>&1
        cleanup_status=$?
        cleanup_cause=$(sanitize_probe_output "$(cat "$cleanup_diagnostic" 2>/dev/null)")
        if ! rm -f "$cleanup_diagnostic" || [ -e "$cleanup_diagnostic" ]; then
            cleanup_status=70
            cleanup_cause="${{cleanup_cause:+$cleanup_cause; }}diagnostic buffer removal failed"
            return 1
        fi
        return "$cleanup_status"
    }}
    record_cleanup_failure() {{
        record_recovery "$cleanup_operation: failed exit_status=$cleanup_status cause=$cleanup_cause"
        record_failure "recovery failed: $cleanup_operation exit_status=$cleanup_status cause=$cleanup_cause"
        rollback_incomplete=1
    }}
    {_cleanup_inspection_script()}
    if [ "$status" -ne 0 ]; then
        safe_failed_step=$(sanitize_probe_output "$failed_step")
        if ! phase_failure "$safe_failed_step" "$status"; then
            rollback_incomplete=1
        fi
        record_failure "deployment failed at $safe_failed_step"
        if [ "$cutover_committed" -eq 1 ]; then
            record_recovery 'rollback skipped after metadata commit; prior-container retirement failed'
            record_failure 'rollback skipped after metadata commit; prior-container retirement failed'
        else
            if [ "$route_active" -eq 1 ]; then
                if ! cleanup_command 'restore route' cp -p "$caddy_backup" /etc/caddy/Caddyfile; then
                    record_cleanup_failure
                else
                    record_recovery 'restore route: ok'
                fi
                if ! cleanup_command 'validate route' caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile; then
                    record_cleanup_failure
                else
                    record_recovery 'validate route: ok'
                fi
                if ! cleanup_command 'reload route' systemctl reload caddy; then
                    record_cleanup_failure
                else
                    record_recovery 'reload route: ok'
                fi
            else
                record_recovery 'restore route: skipped'
            fi
            if [ -f "$backup_dir/.citespan-deployment.json" ]; then
                if ! cleanup_command "restore metadata identity=$deployment_metadata" cp -p "$backup_dir/.citespan-deployment.json" "$deployment_metadata"; then
                    record_cleanup_failure
                else
                    record_recovery 'restore metadata: ok'
                fi
            else
                record_recovery 'restore metadata: skipped'
            fi
            if [ -f "$backup_dir/.citespan-demo-marker.json" ] && ! cleanup_command "restore demo marker identity=$demo_marker" cp -p "$backup_dir/.citespan-demo-marker.json" "$demo_marker"; then
                record_cleanup_failure
            elif [ -f "$backup_dir/.citespan-demo-marker.json" ]; then
                record_recovery 'restore demo marker: ok'
            else
                record_recovery 'restore demo marker: skipped'
            fi
            if [ -f "$backup_dir/.citespan-runtime.env" ] && ! cleanup_command "restore runtime identity=$runtime" cp -p "$backup_dir/.citespan-runtime.env" {DEPLOY_PATH}/.citespan-runtime.env; then
                record_cleanup_failure
            elif [ -f "$backup_dir/.citespan-runtime.env" ]; then
                record_recovery 'restore runtime: ok'
            else
                record_recovery 'restore runtime: skipped'
            fi
            if [ "$previous_backend_running" -eq 1 ] && ! cleanup_command "restart prior backend identity=$previous_backend" docker start "$previous_backend"; then
                record_cleanup_failure
            elif [ "$previous_backend_running" -eq 1 ]; then
                record_recovery 'restart prior backend: ok'
            else
                record_recovery 'restart prior backend: skipped'
            fi
            if [ "$previous_static_running" -eq 1 ] && ! cleanup_command "restart prior static identity=$previous_static" docker start "$previous_static"; then
                record_cleanup_failure
            elif [ "$previous_static_running" -eq 1 ]; then
                record_recovery 'restart prior static: ok'
            else
                record_recovery 'restart prior static: skipped'
            fi
            if [ -n "${{candidate_static:-}}" ]; then
                if ! cleanup_command 'remove candidate static: Docker unavailable' docker info; then
                    record_cleanup_failure
                elif cleanup_operation="inspect candidate static identity=$candidate_static"; ! inspect_container_state "inspect candidate static identity" "$candidate_static"; then
                    record_cleanup_failure
                elif [ "$inspect_state" = present ]; then
                    record_recovery 'remove candidate static: inspect=present'
                    candidate_static_running="$inspect_running"
                    candidate_static_stopped=0
                    if [ "$candidate_static_running" = true ]; then
                        if ! cleanup_command "stop candidate static identity=$candidate_static" docker stop "$candidate_static"; then
                            record_cleanup_failure
                        else
                            record_recovery 'stop candidate static: ok'
                            candidate_static_stopped=1
                        fi
                    elif [ "$candidate_static_running" = false ]; then
                        record_recovery 'stop candidate static: skipped; already stopped'
                        candidate_static_stopped=1
                    else
                        record_recovery 'remove candidate static: skipped after unknown running state'
                        cleanup_status=70
                        cleanup_cause='candidate static running state is unknown'
                        record_cleanup_failure
                    fi
                    if [ "$candidate_static_stopped" -eq 1 ]; then
                    if ! cleanup_command "remove candidate static identity=$candidate_static" docker rm "$candidate_static"; then
                        record_cleanup_failure
                    else
                        record_recovery 'remove candidate static: ok'
                    fi
                    cleanup_operation="verify candidate static removal identity=$candidate_static"
                    if ! inspect_container_state "verify candidate static removal" "$candidate_static"; then
                        record_cleanup_failure
                    elif [ "$inspect_state" = absent ]; then
                        record_recovery "remove candidate static: inspect=absent identity=$candidate_static"
                    else
                        cleanup_status=70
                        cleanup_cause="candidate static removal is unproved state=$inspect_state"
                        record_cleanup_failure
                    fi
                    fi
                elif [ "$inspect_state" = absent ]; then
                    record_recovery "remove candidate static: inspect=absent identity=$candidate_static exit_status=$inspect_status cause=$inspect_cause"
                else
                    cleanup_status=70
                    cleanup_cause='candidate static inspection is incomplete'
                    record_cleanup_failure
                fi
            else
                record_recovery 'remove candidate static: skipped'
            fi
            if [ -n "${{compose_override:-}}" ] && ! cleanup_command "remove candidate services identity=$CITESPAN_DEPLOYMENT_ID" docker compose --project-name "$CITESPAN_DEPLOYMENT_ID" --env-file {DEPLOY_PATH}/.citespan-runtime.env -f {DEPLOY_PATH}/{DEMO_COMPOSE} -f "$compose_override" down --remove-orphans; then
                record_cleanup_failure
            elif [ -n "${{compose_override:-}}" ]; then
                record_recovery 'remove candidate services: ok'
            else
                record_recovery 'remove candidate services: skipped'
            fi
        fi
    fi
    if [ -n "${{compose_override:-}}" ]; then
        if cleanup_command "remove compose override identity=$compose_override" rm -f "$compose_override"; then
            record_recovery 'remove compose override: ok'
        else
            record_cleanup_failure
            cleanup_failed=1
            status=70
        fi
    else
        record_recovery 'remove compose override: skipped'
    fi
    if [ "$rollback_incomplete" -ne 0 ]; then
        record_recovery 'rollback result: incomplete'
        record_failure "recovery incomplete; see $recovery_log"
        exit 70
    fi
    record_recovery 'rollback result: complete'
    exit "$status"
}}
trap rollback EXIT
"""
    command = (
        "set -Eeuo pipefail; failed_step=bootstrap; route_active=0; route_switched=0; rollback_incomplete=0; cutover_committed=0; cleanup_failed=0; "
        "trap 'failed_step=\"$BASH_COMMAND\"' ERR; "
        + " test -f /etc/caddy/Caddyfile; "
        + minio_preflight
        + " minio_source_preflight; "
        f"domain={domain}; expected={expected}; run_id={run_id}; "
        f"test -f /etc/caddy/Caddyfile; if [ ! -d {DEPLOY_PATH}/.git ]; then git clone {shlex.quote(DEPLOY_REPOSITORY)} {DEPLOY_PATH}; fi; "
        f"test -d {DEPLOY_PATH}/.git; if ! origin_url=$(git -C {DEPLOY_PATH} config --get remote.origin.url 2>/dev/null); then echo 'release blocked: origin lookup failed' >&2; exit 1; fi; test -n \"$origin_url\"; verified_origin=$(CITESPAN_ORIGIN_URL=\"$origin_url\" python3 -c {origin_check}); test \"$verified_origin\" = aayushman-singh/ufdr-analyzer; "
        f"export CITESPAN_SYNTHETIC_MARKER={shlex.quote(CANONICAL_DEMO_MARKER)}; "
        f"deployment_metadata={DEPLOYMENT_METADATA}; demo_marker={DEMO_MARKER}; receipt={DEPLOY_PATH}/.citespan-authoritative-receipt.json; backup_dir={DEPLOY_PATH}/.citespan-backups/$(date -u +%Y%m%d%H%M%S%N); mkdir -p \"$backup_dir\"; phase_trace=\"$backup_dir/release-phase-trace.log\"; umask 077; : > \"$phase_trace\"; chmod 600 \"$phase_trace\"; printf 'release phase trace=%s\\n' \"$phase_trace\" >&2; phase_start() {{ printf '%s phase=%s status=start\\n' \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\" \"$1\" >> \"$phase_trace\"; }}; phase_end() {{ printf '%s phase=%s status=end exit_code=%s\\n' \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\" \"$1\" \"$2\" >> \"$phase_trace\"; }}; phase_failure() {{ printf '%s phase=%s status=failure exit_code=%s\\n' \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\" \"$1\" \"$2\" >> \"$phase_trace\"; }}; phase_start \"bootstrap\"; "
        f"runtime={DEPLOY_PATH}/.citespan-runtime.env; if [ ! -f \"$runtime\" ]; then umask 077; neo4j_password=$(openssl rand -hex 32); postgres_password=$(openssl rand -hex 32); meili_master_key=$(openssl rand -hex 32); minio_root_user=$(openssl rand -hex 16); minio_root_password=$(openssl rand -hex 32); secret_key=$(openssl rand -hex 32); temporary_runtime=$(mktemp \"$runtime.XXXXXX\"); printf 'DEMO_MODE=1\\nCITESPAN_SYNTHETIC_ONLY=1\\nOPENAI_API_KEY=\\nOPENROUTER_API_KEY=\\nNEO4J_PASSWORD=%s\\nPOSTGRES_USER=ufdr_user\\nPOSTGRES_DB=ufdr_analyzer\\nPOSTGRES_PASSWORD=%s\\nMEILI_MASTER_KEY=%s\\nMINIO_ROOT_USER=%s\\nMINIO_ROOT_PASSWORD=%s\\nMINIO_ACCESS_KEY=%s\\nMINIO_SECRET_KEY=%s\\nSECRET_KEY=%s\\n' \"$neo4j_password\" \"$postgres_password\" \"$meili_master_key\" \"$minio_root_user\" \"$minio_root_password\" \"$minio_root_user\" \"$minio_root_password\" \"$secret_key\" > \"$temporary_runtime\"; chmod 600 \"$temporary_runtime\"; mv -f \"$temporary_runtime\" \"$runtime\"; fi; python3 -c {runtime_check} \"$runtime\"; set -a; . \"$runtime\"; set +a; "
        + orphan_recovery
        + " guarded_orphan_recovery; "
        "previous_deployment_id=; previous_backend=; previous_static=; previous_frontend=; candidate_backend=; candidate_static=; "
        "previous_backend_running=0; previous_static_running=0; "
        "candidate_metadata=; prior_metadata=; compose_override=; recovery_log=; caddy_backup=; "
        "if [ -f \"$deployment_metadata\" ]; then "
        "cp -p \"$deployment_metadata\" \"$backup_dir/.citespan-deployment.json\"; "
        f"cp -p \"$demo_marker\" \"$backup_dir/.citespan-demo-marker.json\"; "
        f"cp -p {DEPLOY_PATH}/.citespan-runtime.env \"$backup_dir/.citespan-runtime.env\"; "
        f"python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); required=(\"deployment_id\",\"backend_container\",\"static_container\",\"runtime_identity\",\"backend_identity\",\"static_identity\",\"commit\",\"live_url\",\"static_content_dir\",\"authoritative_network\",\"authoritative_postgres\",\"authoritative_meili\",\"authoritative_minio\",\"authoritative_data\",\"synthetic_only\",\"marker\"); assert all(isinstance(m.get(k),str) and m.get(k) for k in required if k not in (\"synthetic_only\", \"authoritative_data\")); assert m.get(\"authoritative_data\") is True and m.get(\"synthetic_only\") is True and m.get(\"marker\") == \"{CANONICAL_DEMO_MARKER}\"; assert len(m.get(\"commit\",\"\")) == 40' \"$deployment_metadata\"; python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); assert m.get(\"marker\") == \"{CANONICAL_DEMO_MARKER}\" and m.get(\"synthetic_only\") is True' \"$demo_marker\"; "
        "previous_deployment_id=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[\"deployment_id\"])' \"$deployment_metadata\"); "
        "previous_backend=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get(\"backend_container\") or sys.argv[2] + \"-backend\")' \"$deployment_metadata\" \"$previous_deployment_id\"); "
        "previous_static=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[\"static_container\"])' \"$deployment_metadata\"); "
        "authoritative_network=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[\"authoritative_network\"])' \"$deployment_metadata\"); authoritative_postgres=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[\"authoritative_postgres\"])' \"$deployment_metadata\"); authoritative_meili=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[\"authoritative_meili\"])' \"$deployment_metadata\"); authoritative_minio=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[\"authoritative_minio\"])' \"$deployment_metadata\"); "
        "docker inspect --format '{{.Id}}\\t{{.Name}}\\t{{.State.Status}}\\t{{.Config.Image}}' \"$previous_backend\" > \"$backup_dir/prior-backend.inspect.txt\"; docker inspect --format '{{.Id}}\\t{{.Name}}\\t{{.State.Status}}\\t{{.Config.Image}}' \"$previous_static\" > \"$backup_dir/prior-static.inspect.txt\"; "
        "if [ \"$(docker inspect -f '{{.State.Running}}' \"$previous_backend\")\" = true ]; then previous_backend_running=1; fi; "
        "if [ \"$(docker inspect -f '{{.State.Running}}' \"$previous_static\")\" = true ]; then previous_static_running=1; fi; "
        "fi; "
        f"recovery_log=\"$backup_dir/recovery.log\"; caddy_backup=\"$backup_dir/Caddyfile\"; readiness_evidence=\"$backup_dir/readiness-evidence.log\"; umask 077; : > \"$readiness_evidence\"; chmod 600 \"$readiness_evidence\"; cp -p /etc/caddy/Caddyfile \"$caddy_backup\"; "
            + _readiness_sanitizer()
            + "\n"
            + rollback_script
        + "phase_end \"bootstrap\" 0; phase_start \"authoritative-data-readiness\"; history_hash_count=$(printf '%s\\n' " + shlex.quote(history_hashes) + " | wc -w); "
        + history_check
        + f"git -C {DEPLOY_PATH} fetch --prune origin main; test \"$(git -C {DEPLOY_PATH} rev-parse refs/remotes/origin/main)\" = {expected}; git -C {DEPLOY_PATH} fetch --prune origin {expected_commit}; test \"$(git -C {DEPLOY_PATH} rev-parse FETCH_HEAD)\" = {expected}; git -C {DEPLOY_PATH} checkout --detach --force {expected_commit}; "
        f"test \"$(git -C {DEPLOY_PATH} rev-parse HEAD)\" = {expected_commit}; "
        "if [ -n \"$previous_deployment_id\" ]; then\n"
        "test -n \"$authoritative_network\"; test -n \"$authoritative_postgres\"; test -n \"$authoritative_meili\"; test -n \"$authoritative_minio\"; "
        "test \"$(docker inspect -f '{{.Name}}' \"$authoritative_postgres\")\" = \"/$authoritative_postgres\"; test \"$(docker inspect -f '{{.Name}}' \"$authoritative_meili\")\" = \"/$authoritative_meili\"; test \"$(docker inspect -f '{{.Name}}' \"$authoritative_minio\")\" = \"/$authoritative_minio\"; "
        "else\n"
        "authoritative_network=citespan-authoritative-network; authoritative_postgres=citespan-authoritative-postgres; authoritative_meili=citespan-authoritative-meili; authoritative_minio=citespan-authoritative-minio; "
        f"if [ -f \"$receipt\" ]; then python3 -c {receipt_validate} \"$receipt\" \"$runtime\" \"$CITESPAN_SYNTHETIC_MARKER\" \"$authoritative_network\" \"$authoritative_postgres\" \"$authoritative_meili\" \"$authoritative_minio\"; else python3 -c {receipt_writer} \"$receipt\" \"$runtime\" \"$CITESPAN_SYNTHETIC_MARKER\" \"$authoritative_network\" \"$authoritative_postgres\" \"$authoritative_meili\" \"$authoritative_minio\"; fi; "
        + reconciliation
        + " reconcile_authoritative_resources; "
        f"if [ \"$(python3 -c 'import json,sys; print(int(json.load(open(sys.argv[1]))[\"resources\"][\"network\"][\"created\"]))' \"$receipt\")\" -eq 0 ]; then if docker network inspect \"$authoritative_network\" >/dev/null 2>&1; then echo 'authoritative receipt does not own existing network' >&2; exit 1; fi; docker network create \"$authoritative_network\"; python3 -c {receipt_writer} \"$receipt\" \"$runtime\" \"$CITESPAN_SYNTHETIC_MARKER\" \"$authoritative_network\" \"$authoritative_postgres\" \"$authoritative_meili\" \"$authoritative_minio\" network created; fi; docker network inspect \"$authoritative_network\" >/dev/null; "
        f"if [ \"$(python3 -c 'import json,sys; print(int(json.load(open(sys.argv[1]))[\"resources\"][\"postgres\"][\"created\"]))' \"$receipt\")\" -eq 0 ]; then if docker inspect \"$authoritative_postgres\" >/dev/null 2>&1; then echo 'authoritative receipt does not own existing PostgreSQL container' >&2; exit 1; fi; docker run -d --name \"$authoritative_postgres\" --network \"$authoritative_network\" -e POSTGRES_USER=\"$POSTGRES_USER\" -e POSTGRES_DB=\"$POSTGRES_DB\" -e POSTGRES_PASSWORD=\"$POSTGRES_PASSWORD\" -v citespan-postgres-data:/var/lib/postgresql/data postgres:17-alpine; python3 -c {receipt_writer} \"$receipt\" \"$runtime\" \"$CITESPAN_SYNTHETIC_MARKER\" \"$authoritative_network\" \"$authoritative_postgres\" \"$authoritative_meili\" \"$authoritative_minio\" postgres created; fi; test -n \"$(docker inspect -f '{{.Name}}' \"$authoritative_postgres\")\"; "
        f"if [ \"$(python3 -c 'import json,sys; print(int(json.load(open(sys.argv[1]))[\"resources\"][\"meili\"][\"created\"]))' \"$receipt\")\" -eq 0 ]; then if docker inspect \"$authoritative_meili\" >/dev/null 2>&1; then echo 'authoritative receipt does not own Meilisearch container' >&2; exit 1; fi; docker run -d --name \"$authoritative_meili\" --network \"$authoritative_network\" -e MEILI_MASTER_KEY=\"$MEILI_MASTER_KEY\" -v citespan-meili-data:/meili_data getmeili/meilisearch:v1.15; python3 -c {receipt_writer} \"$receipt\" \"$runtime\" \"$CITESPAN_SYNTHETIC_MARKER\" \"$authoritative_network\" \"$authoritative_postgres\" \"$authoritative_meili\" \"$authoritative_minio\" meili created; fi; test -n \"$(docker inspect -f '{{.Name}}' \"$authoritative_meili\")\"; "
        f"if [ \"$(python3 -c 'import json,sys; print(int(json.load(open(sys.argv[1]))[\"resources\"][\"minio\"][\"created\"]))' \"$receipt\")\" -eq 0 ]; then if docker inspect \"$authoritative_minio\" >/dev/null 2>&1; then echo 'authoritative receipt does not own MinIO container' >&2; exit 1; fi; docker run -d --name \"$authoritative_minio\" --network \"$authoritative_network\" -e MINIO_ROOT_USER=\"$MINIO_ROOT_USER\" -e MINIO_ROOT_PASSWORD=\"$MINIO_ROOT_PASSWORD\" -e MINIO_ACCESS_KEY=\"$MINIO_ROOT_USER\" -e MINIO_SECRET_KEY=\"$MINIO_ROOT_PASSWORD\" -v citespan-minio-data:/data \"$minio_image\" server /data; python3 -c {receipt_writer} \"$receipt\" \"$runtime\" \"$CITESPAN_SYNTHETIC_MARKER\" \"$authoritative_network\" \"$authoritative_postgres\" \"$authoritative_meili\" \"$authoritative_minio\" minio created; fi; test -n \"$(docker inspect -f '{{.Name}}' \"$authoritative_minio\")\"; "
        "failed_step=readiness-postgresql; postgres_ready=0; last_readiness_cause=; for readiness_attempt in $(seq 1 30); do set +e; readiness_output=$(docker exec \"$authoritative_postgres\" env PGPASSWORD=\"$POSTGRES_PASSWORD\" pg_isready -U \"$POSTGRES_USER\" -d \"$POSTGRES_DB\" 2>&1); readiness_status=$?; set -e; last_readiness_cause=$(sanitize_probe_output \"$readiness_output\"); printf '%s\n' \"service=postgres identity=$authoritative_postgres attempt=$readiness_attempt status=$readiness_status cause=$last_readiness_cause\" >> \"$readiness_evidence\"; if [ \"$readiness_status\" -eq 0 ] && printf '%s' \"$readiness_output\" | grep -q accepting; then postgres_ready=1; break; fi; if [ \"$readiness_status\" -eq 127 ] || printf '%s' \"$readiness_output\" | grep -Eqi 'not found|invalid|malformed|authentication|permission denied|wrong identity'; then echo \"readiness failed: PostgreSQL permanent probe fault; cause=$last_readiness_cause; see $readiness_evidence\" >&2; exit 1; fi; sleep 1; done; test \"$postgres_ready\" -eq 1 || { echo \"readiness failed: PostgreSQL timed out; last_cause=$last_readiness_cause; see $readiness_evidence\" >&2; exit 1; }; python3 -c {receipt_writer} \"$receipt\" \"$runtime\" \"$CITESPAN_SYNTHETIC_MARKER\" \"$authoritative_network\" \"$authoritative_postgres\" \"$authoritative_meili\" \"$authoritative_minio\" postgres ready; "
        "failed_step=readiness-meilisearch; meili_ready=0; last_readiness_cause=; for readiness_attempt in $(seq 1 30); do set +e; readiness_output=$(docker exec \"$authoritative_meili\" sh -c 'wget --header=\"Authorization: Bearer $MEILI_MASTER_KEY\" -qO- http://127.0.0.1:7700/health' 2>&1); readiness_status=$?; set -e; last_readiness_cause=$(sanitize_probe_output \"$readiness_output\"); printf '%s\n' \"service=meili identity=$authoritative_meili attempt=$readiness_attempt status=$readiness_status cause=$last_readiness_cause\" >> \"$readiness_evidence\"; if [ \"$readiness_status\" -eq 0 ] && printf '%s' \"$readiness_output\" | grep -q available; then meili_ready=1; break; fi; if [ \"$readiness_status\" -eq 127 ] || printf '%s' \"$readiness_output\" | grep -Eqi 'not found|invalid|malformed|unauthorized|authentication|permission denied|wrong identity'; then echo \"readiness failed: Meilisearch permanent probe fault; cause=$last_readiness_cause; see $readiness_evidence\" >&2; exit 1; fi; sleep 1; done; test \"$meili_ready\" -eq 1 || { echo \"readiness failed: Meilisearch timed out; last_cause=$last_readiness_cause; see $readiness_evidence\" >&2; exit 1; }; python3 -c {receipt_writer} \"$receipt\" \"$runtime\" \"$CITESPAN_SYNTHETIC_MARKER\" \"$authoritative_network\" \"$authoritative_postgres\" \"$authoritative_meili\" \"$authoritative_minio\" meili ready; "
        "failed_step=readiness-minio; minio_ready=0; last_readiness_cause=; for readiness_attempt in $(seq 1 30); do set +e; readiness_output=$(docker exec \"$authoritative_minio\" sh -c 'wget --user=\"$MINIO_ROOT_USER\" --password=\"$MINIO_ROOT_PASSWORD\" -qO- http://127.0.0.1:9000/minio/health/live' 2>&1); readiness_status=$?; set -e; last_readiness_cause=$(sanitize_probe_output \"$readiness_output\"); printf '%s\n' \"service=minio identity=$authoritative_minio attempt=$readiness_attempt status=$readiness_status cause=$last_readiness_cause\" >> \"$readiness_evidence\"; if [ \"$readiness_status\" -eq 0 ] && printf '%s' \"$readiness_output\" | grep -q -E 'OK|live|success'; then minio_ready=1; break; fi; if [ \"$readiness_status\" -eq 127 ] || printf '%s' \"$readiness_output\" | grep -Eqi 'not found|invalid|malformed|unauthorized|authentication|permission denied|wrong identity'; then echo \"readiness failed: MinIO permanent probe fault; cause=$last_readiness_cause; see $readiness_evidence\" >&2; exit 1; fi; sleep 1; done; test \"$minio_ready\" -eq 1 || { echo \"readiness failed: MinIO timed out; last_cause=$last_readiness_cause; see $readiness_evidence\" >&2; exit 1; }; python3 -c {receipt_writer} \"$receipt\" \"$runtime\" \"$CITESPAN_SYNTHETIC_MARKER\" \"$authoritative_network\" \"$authoritative_postgres\" \"$authoritative_meili\" \"$authoritative_minio\" minio ready; fi\n"
        "test \"$DEMO_MODE\" = 1; export DEMO_MODE=1; candidate_suffix=$(date -u +%Y%m%d%H%M%S%N); export CITESPAN_DEPLOYMENT_ID=\"citespan-candidate-$candidate_suffix\" CITESPAN_DEMO_RUN_ID=\"$run_id\" CITESPAN_SYNTHETIC_MARKER="
        + shlex.quote(CANONICAL_DEMO_MARKER)
        + " CITESPAN_SYNTHETIC_ONLY=1 CITESPAN_AUTHORITATIVE_NETWORK=\"$authoritative_network\" CITESPAN_AUTHORITATIVE_POSTGRES=\"$authoritative_postgres\" CITESPAN_AUTHORITATIVE_MEILI=\"$authoritative_meili\" CITESPAN_AUTHORITATIVE_MINIO=\"$authoritative_minio\" OPENAI_API_KEY= OPENROUTER_API_KEY=; "
        "backend_port=$(python3 -c 'import socket; s=socket.socket(); s.bind((\"127.0.0.1\",0)); print(s.getsockname()[1]); s.close()'); candidate_frontend_port=$(python3 -c 'import socket; s=socket.socket(); s.bind((\"127.0.0.1\",0)); print(s.getsockname()[1]); s.close()'); frontend_port=$candidate_frontend_port; "
        "export CITESPAN_BACKEND_PORT=\"$backend_port\" CITESPAN_FRONTEND_PORT=\"$candidate_frontend_port\" DEMO_MODE=1 CITESPAN_SYNTHETIC_ONLY=1; "
        f"compose_override=$(mktemp {DEPLOY_PATH}/.citespan-demo-override.XXXXXX); "
        f"printf %s {override} | base64 -d > \"$compose_override\"; "
        f'compose="docker compose --project-name $CITESPAN_DEPLOYMENT_ID --env-file {DEPLOY_PATH}/.citespan-runtime.env -f {DEPLOY_PATH}/{DEMO_COMPOSE} -f $compose_override"; '
        f"$compose config --format json | python3 -c {port_check} \"$backend_port\"; "
        "$compose up -d --no-deps --build backend; backend_id=$($compose ps -q backend); test -n \"$backend_id\"; candidate_backend=\"$backend_id\"; "
        + candidate_readiness
        + "demo_state=$(docker exec \"$backend_id\" sh -c 'echo " + empty_check + " | base64 -d | python3'); "
        "if [ \"$demo_state\" = EMPTY ]; then echo 'candidate demo target is empty'; docker exec \"$backend_id\" sh -c 'echo " + seed + " | base64 -d | python3'; elif [ \"$demo_state\" = EXISTING ]; then test -f \"$receipt\"; "
        f"python3 -c {receipt_validate} \"$receipt\" \"$runtime\" \"$CITESPAN_SYNTHETIC_MARKER\" \"$authoritative_network\" \"$authoritative_postgres\" \"$authoritative_meili\" \"$authoritative_minio\"; "
        "if [ -f \"$deployment_metadata\" ]; then python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); required=(\"deployment_id\",\"backend_container\",\"static_container\",\"runtime_identity\",\"backend_identity\",\"static_identity\",\"commit\",\"live_url\",\"static_content_dir\",\"authoritative_network\",\"authoritative_postgres\",\"authoritative_meili\",\"authoritative_minio\",\"authoritative_data\",\"synthetic_only\",\"marker\"); assert all(key in m for key in required); assert m[\"authoritative_data\"] is True and m[\"synthetic_only\"] is True and m[\"marker\"] == \"" + CANONICAL_DEMO_MARKER + "\"; assert len(m[\"commit\"]) == 40' \"$deployment_metadata\"; python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); assert m[\"marker\"] == \"" + CANONICAL_DEMO_MARKER + "\" and m[\"synthetic_only\"] is True' \"$demo_marker\"; test \"$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[\"runtime_identity\"])' \"$deployment_metadata\")\" = \"$previous_deployment_id\"; test \"$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[\"backend_identity\"])' \"$deployment_metadata\")\" = \"$previous_backend\"; test \"$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[\"static_identity\"])' \"$deployment_metadata\")\" = \"$previous_static\"; fi; test \"$CITESPAN_SYNTHETIC_ONLY\" = 1; else echo 'candidate demo target is not empty' >&2; exit 1; fi; "
        "docker exec \"$backend_id\" sh -c 'echo " + audit + " | base64 -d | python3'; phase_end \"application-candidate\" 0; "
        f"mkdir -p \"$backup_dir/static-content\"; frontend_builder=node:22-alpine; docker run --rm -v {DEPLOY_PATH}:/workspace -w /workspace/frontend -e {shlex.quote(f'NEXT_PUBLIC_API_URL=https://{domain_value}/api')} -e NEXT_PUBLIC_DEMO_MODE=1 \"$frontend_builder\" sh -c 'npm ci && npm run build'; test -d {DEPLOY_PATH}/frontend/out; cp -a {DEPLOY_PATH}/frontend/out/. \"$backup_dir/static-content/\"; static_content_dir=\"$backup_dir/static-content\"; "
        "candidate_static=$CITESPAN_DEPLOYMENT_ID-static; docker run -d --name \"$candidate_static\" -p 127.0.0.1:$candidate_frontend_port:80 -v \"$static_content_dir:/usr/share/nginx/html:ro\" nginx:1.29-alpine; "
        "test -n \"$(docker ps -q --filter name=^/$candidate_static$)\"; "
        "failed_step=candidate-static-health; candidate_static_body=\"$backup_dir/candidate-static.html\"; if ! curl --fail --silent --show-error http://127.0.0.1:$candidate_frontend_port/ >\"$candidate_static_body\"; then exit 1; fi; grep -qi CiteSpan \"$candidate_static_body\"; "
        "if ! curl --fail --silent --show-error http://127.0.0.1:$backend_port/health/ >/dev/null; then exit 1; fi; "
        "caddy_backup=\"$backup_dir/Caddyfile\"; "
        "failed_step=route-stage; route_file=\"$backup_dir/citespan-route\"; printf '%s\\n' '# BEGIN CITESPAN ROUTE' \"$domain {\" '    handle_path /api/* {' \"        reverse_proxy 127.0.0.1:$backend_port\" '    }' \"    reverse_proxy 127.0.0.1:$frontend_port\" '}' '# END CITESPAN ROUTE' > \"$route_file\"; "
        "CITESPAN_ROUTE_FILE=\"$route_file\" python3 -c 'import os; from pathlib import Path; p=Path(\"/etc/caddy/Caddyfile\"); route=Path(os.environ[\"CITESPAN_ROUTE_FILE\"]).read_text(); text=p.read_text(); begin=\"# BEGIN CITESPAN ROUTE\"; end=\"# END CITESPAN ROUTE\"; start=text.find(begin); finish=text.find(end, start); assert text.count(begin) <= 1 and text.count(end) <= 1; assert (start < 0 and finish < 0) or (start >= 0 and finish > start); prefix=text if start < 0 else text[:start]; suffix=\"\" if start < 0 else text[finish+len(end):]; tmp=p.with_name(\".Caddyfile.citespan.tmp\"); tmp.write_text(prefix+route+suffix); tmp.replace(p)'; "
        "failed_step=caddy-validate; route_active=1; route_switched=1; caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile; failed_step=route-reload; systemctl reload caddy; "
        f"failed_step=public-route-check; public_route_body=\"$backup_dir/public-route.html\"; if ! curl --fail --silent --show-error --tlsv1.2 https://$domain/ >\"$public_route_body\"; then exit 1; fi; grep -qi CiteSpan \"$public_route_body\"; "
        f"failed_step=metadata-commit; verified_commit=$(git -C {DEPLOY_PATH} rev-parse HEAD); test \"$verified_commit\" = {expected}; test \"$(printf %s \"$verified_commit\" | wc -c)\" -eq 40; marker_tmp=\"$backup_dir/demo-marker.json.tmp\"; "
        f"python3 -c "
        + shlex.quote(_metadata_writer_script())
        + " \"$authoritative_network\" \"$authoritative_postgres\" \"$authoritative_meili\" \"$authoritative_minio\" citespan-postgres-data citespan-meili-data \"$deployment_metadata\" \"$CITESPAN_SYNTHETIC_MARKER\" \"$runtime\" \"$CITESPAN_DEPLOYMENT_ID\" \"$backend_id\" \"$verified_commit\" \"https://$domain\" \"$backend_port\" \"$frontend_port\" \"$candidate_static\" \"$static_content_dir\" \"$CITESPAN_DEPLOYMENT_ID\" \"$backend_id\" \"$candidate_static\"; "
        f"printf '{{\"deployment_id\":\"%s\",\"run_id\":\"%s\",\"synthetic_only\":true,\"marker\":\"{CANONICAL_DEMO_MARKER}\"}}\\n' \"$CITESPAN_DEPLOYMENT_ID\" \"$run_id\" > \"$marker_tmp\"; "
        "python3 -c 'import json,sys; json.load(open(sys.argv[1]))' \"$deployment_metadata\"; python3 -c 'import json,sys; json.load(open(sys.argv[1]))' \"$marker_tmp\"; "
        f"mv -f \"$marker_tmp\" \"$demo_marker\"; cutover_committed=1; "
        "if [ -n \"$previous_deployment_id\" ]; then for prior_container in \"$previous_backend\" \"$previous_static\"; do if [ \"$(docker inspect -f '{{.State.Running}}' \"$prior_container\")\" = true ]; then if ! docker stop \"$prior_container\" >/dev/null; then echo \"retirement failed: could not stop $prior_container\" >&2; cleanup_failed=1; continue; fi; fi; if ! docker rm \"$prior_container\" >/dev/null; then echo \"retirement failed: could not remove $prior_container\" >&2; cleanup_failed=1; fi; done; fi; if [ \"$cleanup_failed\" -ne 0 ]; then echo 'retirement failed after metadata commit' >&2; exit 1; fi; "
        "printf '{\"live_url\":\"https://%s\",\"deployment_id\":\"%s\",\"backend_port\":%s,\"frontend_port\":%s,\"authoritative_data\":true}\\n' \"$domain\" \"$CITESPAN_DEPLOYMENT_ID\" \"$backend_port\" \"$frontend_port\""
    )
    command = command.replace("{receipt_writer}", receipt_writer)
    minio_start = command.index("failed_step=readiness-minio;")
    minio_end = command.index("candidate_suffix=", minio_start)
    authoritative_services = _minio_readiness_command(receipt_writer) + 'fi\nphase_end "authoritative-data-readiness" 0\nphase_start "application-candidate"\n'
    command = command[:minio_start] + authoritative_services + command[minio_end:]
    return command


def _deployment_command(payload: dict[str, Any]) -> str:
    return _deployment_command_authoritative(payload)


def _observation_command() -> str:
    runtime_check = shlex.quote(_runtime_validation_script(_history_secret_hashes()))
    observation_script = (
        "import json,sys,re; "
        "metadata=json.load(open(sys.argv[1])); marker=json.load(open(sys.argv[2])); "
        "required=('deployment_id','commit','live_url','backend_port','frontend_port','static_container','static_content_dir','synthetic_only','marker'); "
        "assert all(key in metadata for key in required), 'deployment metadata is incomplete'; "
        "assert metadata['synthetic_only'] is True, 'deployment is not synthetic-only'; "
        "assert metadata['marker'] == sys.argv[3], 'deployment metadata marker mismatch'; "
        "assert isinstance(metadata['commit'],str) and len(metadata['commit']) == 40, 'deployment identity is invalid'; "
        "assert metadata['live_url'] == sys.argv[6], 'live URL is not the authorized origin'; "
        "assert isinstance(metadata['deployment_id'],str) and metadata['deployment_id'], 'deployment ID is missing'; "
        "assert re.fullmatch(r'[0-9a-z-]+', metadata['static_container']), 'static container identity is invalid'; "
        "assert isinstance(metadata['static_content_dir'],str) and metadata['static_content_dir'].startswith('/opt/citespan/.citespan-backups/'), 'static content identity is invalid'; "
        "required_marker=('deployment_id','run_id','synthetic_only','marker'); "
        "assert all(key in marker for key in required_marker), 'demo marker is incomplete'; "
        "assert marker['deployment_id'] == metadata['deployment_id'], 'demo marker deployment identity mismatch'; "
        "assert marker['run_id'] == sys.argv[4], 'demo marker run ID mismatch'; "
        "assert marker['synthetic_only'] is True, 'demo marker is not synthetic-only'; "
        "assert marker['marker'] == sys.argv[5], 'demo marker contents mismatch'; "
        "print(json.dumps({'deployment_commit':metadata['commit'],'live_url':metadata['live_url'],'deployment_id':metadata['deployment_id'],'backend_port':metadata['backend_port'],'frontend_port':metadata['frontend_port'],'static_container':metadata['static_container'],'static_content_dir':metadata['static_content_dir'],'synthetic_only':True,'demo_mode':'1','runtime_validated':True,'demo_run_id':marker['run_id'],'metadata_marker':metadata['marker'],'demo_marker':marker['marker']}))"
    )
    return (
        "set -eu; "
        f"if [ ! -f {DEPLOYMENT_METADATA} ] || [ ! -f {DEMO_MARKER} ]; then printf 'NOT_DEPLOYED\\n'; "
        f"else deployment_id=$(python3 -c 'import json; print(json.load(open(\"{DEPLOYMENT_METADATA}\"))[\"deployment_id\"]'); static_container=$(python3 -c 'import json; print(json.load(open(\"{DEPLOYMENT_METADATA}\"))[\"static_container\"]'); runtime={DEPLOY_PATH}/.citespan-runtime.env; python3 -c {runtime_check} \"$runtime\"; grep -Fxq 'DEMO_MODE=1' \"$runtime\"; grep -Fxq 'CITESPAN_SYNTHETIC_ONLY=1' \"$runtime\"; backend_id=$(docker ps -q --filter name=^/$deployment_id-backend$); test -n \"$backend_id\"; test -n \"$(docker ps -q --filter name=^/$static_container$)\"; backend_env=$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' \"$backend_id\"); printf %s \"$backend_env\" | grep -Fxq 'DEMO_MODE=1'; printf %s \"$backend_env\" | grep -Fxq 'CITESPAN_SYNTHETIC_ONLY=1'; printf %s \"$backend_env\" | grep -Fxq 'CITESPAN_DEMO_RUN_ID={CANONICAL_DEMO_RUN_ID}'; printf %s \"$backend_env\" | grep -Fxq 'CITESPAN_SYNTHETIC_MARKER={CANONICAL_DEMO_MARKER}'; printf %s \"$backend_env\" | grep -Fxq \"CITESPAN_DEPLOYMENT_ID=$deployment_id\"; test \"$(git -C {DEPLOY_PATH} rev-parse HEAD)\" = \"$(python3 -c 'import json; print(json.load(open(\"{DEPLOYMENT_METADATA}\"))[\"commit\"]')\"; test -f /etc/caddy/Caddyfile; grep -Fq '# BEGIN CITESPAN ROUTE' /etc/caddy/Caddyfile; "
        "python3 -c " + shlex.quote(observation_script) + " "
        + DEPLOYMENT_METADATA
        + " "
        + DEMO_MARKER
        + " "
         + shlex.quote(CANONICAL_DEMO_MARKER)
        + " "
        + shlex.quote(CANONICAL_DEMO_RUN_ID)
        + " "
        + shlex.quote(CANONICAL_DEMO_MARKER)
        + " "
        + shlex.quote(AUTHORIZED_LIVE_ORIGIN)
        + "; fi"
    )


def _prepare(
    payload: dict[str, Any], *, validate_process_evidence: bool = True
) -> dict[str, Any]:
    _validate_raw_input(payload)
    action = _action(payload)
    demo_mode = _enforce_hosted_demo_mode(payload)
    release_text = _release_text()
    for name in _credential_scan_findings(release_text):
        raise RuntimeError(f"release blocked: credential pattern found in tracked file {name}")
    for name, _ in release_text:
        if Path(name).name.lower() in REAL_DATA_NAMES:
            raise RuntimeError(f"release blocked: real forensic data file is tracked: {name}")
    _demo_run_id(payload)
    history_findings = _history_credential_findings()
    if history_findings and not _runtime_compromise_resolved(payload):
        raise RuntimeError(
            "release blocked: credential history findings remain unresolved in current runtime configuration"
        )
    expected = _expected_commit(payload)
    actual = _git("rev-parse", "HEAD").lower()
    if actual != expected:
        raise RuntimeError("release blocked: prepared commit does not match expected commit")
    dependency_findings = _critical_dependency_findings()
    branding_findings = _branding_findings()
    release_ready = not dependency_findings and not branding_findings
    host_preparation = None
    if validate_process_evidence and release_ready:
        host_preparation = _prepare_host()
    return {
        "action_key": action,
        "complete": release_ready,
        "release_ready": release_ready,
        "repository": "aayushman-singh/ufdr-analyzer",
        "commit": expected,
        "product_name": "CiteSpan",
        "python": _project_python(),
        "demo_policy": {
            "mode": demo_mode,
            "runtime": {"DEMO_MODE": "1", "CITESPAN_SYNTHETIC_ONLY": "1"},
            "upload": False,
            "reset_to_sample": True,
            "sample": "canonical synthetic UFDR",
        },
        "secret_policy": "known historical credentials are compromised; runtime secrets are external and rotated",
        "credential_history_findings": history_findings,
        "critical_dependency_findings": dependency_findings,
        "branding_findings": branding_findings,
        "host_preparation": host_preparation,
        "release_config": {
            "live_url": _public_url(payload),
            "api_origin": _api_origin(payload),
            "demo_run_id": _demo_run_id(payload),
            "route": "dedicated Caddy HTTPS route with /api forwarded to backend",
        },
    }


def _run_live_verifier(payload: dict[str, Any]) -> dict[str, Any]:
    """Run the one authorized live verifier with script-relative arguments."""
    url = _public_url(payload)
    run_id = _required_demo_run_id(payload)
    configured_root = _payload_value(payload, "proof_dir") or os.environ.get(
        "CITESPAN_PROOF_DIR"
    )
    proof_root = Path(configured_root).expanduser() if configured_root else EXTERNAL_PROOF_ROOT
    if not proof_root.is_absolute():
        raise RuntimeError("verification blocked: proof_dir must be an absolute external path")
    proof_root.mkdir(parents=True, exist_ok=True)
    output_dir = Path(
        tempfile.mkdtemp(
            prefix=f"{_expected_commit(payload)}-",
            dir=proof_root,
        )
    )
    observation = payload.get("observation")
    deployment_id = observation.get("deployment_id") if isinstance(observation, dict) else None
    if not isinstance(deployment_id, str) or not deployment_id:
        raise RuntimeError("verification blocked: observed deployment identity is missing")
    argv = [
        _project_python(),
        str(ROOT / "scripts" / "verify_live.py"),
        "--url",
        url,
        "--run-id",
        run_id,
        "--deployment-id",
        deployment_id,
        "--output-dir",
        str(output_dir),
    ]
    started_at = _monotonic_now()
    try:
        result = subprocess.run(
            argv,
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=LIVE_VERIFIER_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        evidence_path = _record_private_subprocess_timeout(
            step="live user-flow verification",
            argv_category="project Python live verifier",
            command=argv,
            timeout=exc,
            timeout_seconds=LIVE_VERIFIER_TIMEOUT_SECONDS,
            elapsed_seconds=_measured_elapsed_seconds(started_at),
        )
        raise RuntimeError(
            "live verification timed out; "
            f"private evidence: {evidence_path}"
        ) from exc
    if result.returncode != 0:
        raise RuntimeError(
            "live verification failed: "
            + json.dumps(
                {
                    "command": argv,
                    "exit_code": result.returncode,
                    "stderr": result.stderr.strip(),
                },
                sort_keys=True,
            )
        )
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("live verification returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError("live verification must return a JSON object")
    return value


def _observe(payload: dict[str, Any]) -> dict[str, Any]:
    action = _provider_payload(payload)
    _check_payload_secrets(payload)
    output = _ssh(_observation_command())
    if output == "NOT_DEPLOYED":
        return {
            "action_key": action,
            "complete": False,
            "observed": False,
            "state": "not_deployed",
            "external_identity": f"{DEPLOY_HOST}:citespan",
        }
    try:
        observed = json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError("observation failed: remote host returned invalid JSON") from exc
    if not isinstance(observed, dict):
        raise RuntimeError("observation failed: remote host returned invalid JSON")
    remote_commit = observed.get("deployment_commit")
    if not isinstance(remote_commit, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", remote_commit):
        raise RuntimeError("observation failed: remote host returned no valid deployed commit")
    expected = _expected_commit(payload)
    if remote_commit.lower() != expected:
        raise RuntimeError("observation failed: remote commit does not match expected commit")
    if observed.get("demo_mode") != "1":
        raise RuntimeError("observation failed: deployed DEMO_MODE is not 1")
    if observed.get("runtime_validated") is not True:
        raise RuntimeError("observation failed: remote runtime validation is not confirmed")
    result = {
        "action_key": action,
        "complete": True,
        "observed": True,
        "deployment_commit": remote_commit,
        "external_identity": f"{DEPLOY_HOST}:citespan",
        "runtime_validated": True,
    }
    live_url = observed.get("live_url")
    live_url = _validate_live_url(live_url, "observed live URL")
    if observed.get("synthetic_only") is not True:
        raise RuntimeError("observation failed: deployment is not marked synthetic-only")
    deployment_id = observed.get("deployment_id")
    if not isinstance(deployment_id, str) or not deployment_id:
        raise RuntimeError("observation failed: deployment identity is invalid")
    static_container = observed.get("static_container")
    static_content_dir = observed.get("static_content_dir")
    if not isinstance(static_container, str) or not re.fullmatch(
        r"[0-9a-z-]+", static_container
    ):
        raise RuntimeError("observation failed: static container identity is invalid")
    if not isinstance(static_content_dir, str) or not static_content_dir.startswith(
        f"{DEPLOY_PATH}/.citespan-backups/"
    ):
        raise RuntimeError("observation failed: static content identity is invalid")
    requested_deployment_id = _payload_value(payload, "deployment_id")
    if requested_deployment_id is not None and requested_deployment_id != deployment_id:
        raise RuntimeError("observation failed: deployment identity does not match requested deployment")
    if observed.get("demo_run_id") != CANONICAL_DEMO_RUN_ID:
        raise RuntimeError("observation failed: canonical demo run ID does not match")
    if observed.get("metadata_marker") != CANONICAL_DEMO_MARKER:
        raise RuntimeError("observation failed: deployment metadata marker does not match")
    if observed.get("demo_marker") != CANONICAL_DEMO_MARKER:
        raise RuntimeError("observation failed: canonical demo marker does not match")
    result["live_url"] = live_url.rstrip("/")
    result["deployment_id"] = deployment_id
    result["backend_port"] = observed.get("backend_port")
    result["frontend_port"] = observed.get("frontend_port")
    result["static_container"] = static_container
    result["static_content_dir"] = static_content_dir
    result["synthetic_only"] = True
    result["demo_mode"] = "1"
    result["demo_run_id"] = observed["demo_run_id"]
    result["metadata_marker"] = observed["metadata_marker"]
    result["demo_marker"] = observed["demo_marker"]
    return result


def _execute(payload: dict[str, Any]) -> dict[str, Any]:
    prepared = _prepare(payload)
    if prepared.get("release_ready") is not True:
        findings = "; ".join(
            prepared.get("critical_dependency_findings", [])
            + prepared.get("branding_findings", [])
        )
        raise RuntimeError(
            "execute blocked: critical frontend dependency scope is unresolved: " + findings
        )
    _ssh(_deployment_command(payload))
    observation = _observe(payload)
    expected_commit = _expected_commit(payload)
    if (
        not isinstance(observation, dict)
        or observation.get("action_key") != _action(payload)
        or observation.get("complete") is not True
        or observation.get("observed") is not True
        or observation.get("state") is not None
        or observation.get("external_identity") != f"{DEPLOY_HOST}:citespan"
        or observation.get("deployment_commit") != expected_commit
    ):
        raise RuntimeError("execute failed: deployment did not produce strict remote commit evidence")
    return {
        "action_key": _action(payload),
        "complete": True,
        "external_identity": observation["external_identity"],
        "deployment_commit": observation["deployment_commit"],
        "live_url": observation.get("live_url", _public_url(payload)),
        "repository": prepared["repository"],
        "product_name": prepared["product_name"],
        "demo_policy": prepared["demo_policy"],
    }


def _verify(payload: dict[str, Any]) -> dict[str, Any]:
    _provider_payload(payload)
    _check_payload_secrets(payload)
    observation = payload.get("observation")
    if not isinstance(observation, dict):
        raise RuntimeError("verification blocked: deployment observation is missing")
    if (
        observation.get("state") == "not_deployed"
        or observation.get("complete") is False
        or observation.get("observed") is False
    ):
        expected_initial = {
            "action_key",
            "complete",
            "observed",
            "state",
            "external_identity",
        }
        if (
            set(observation) != expected_initial
            or observation.get("action_key") != _action(payload)
            or observation.get("complete") is not False
            or observation.get("observed") is not False
            or observation.get("state") != "not_deployed"
            or observation.get("external_identity") != f"{DEPLOY_HOST}:citespan"
        ):
            raise RuntimeError("verification blocked: invalid not_deployed observation")
        return {
            "action_key": _action(payload),
            "complete": False,
            "observed": False,
            "state": "not_deployed",
            "external_identity": f"{DEPLOY_HOST}:citespan",
        }
    expected = _expected_commit(payload)
    deployment_commit = observation.get("deployment_commit")
    if not isinstance(deployment_commit, str) or not deployment_commit:
        raise RuntimeError("verification blocked: observation has no deployed commit")
    if deployment_commit.lower() != expected:
        raise RuntimeError("verification blocked: observed commit does not match expected commit")
    if observation.get("observed") is not True:
        raise RuntimeError("verification blocked: deployment observation is not confirmed")
    live_url = observation.get("live_url")
    live_url = _validate_live_url(live_url, "observed live URL")
    payload_url = _public_url(payload)
    if payload_url != live_url:
        raise RuntimeError("verification blocked: payload live URL does not match observation")
    payload_deployment_id = _payload_value(payload, "deployment_id")
    if payload_deployment_id is not None and payload_deployment_id != observation.get("deployment_id"):
        raise RuntimeError("verification blocked: payload deployment identity does not match observation")
    if observation.get("synthetic_only") is not True:
        raise RuntimeError("verification blocked: observed deployment is not synthetic-only")
    if observation.get("runtime_validated") is not True:
        raise RuntimeError("verification blocked: remote runtime validation is not confirmed")
    if observation.get("demo_mode") != "1":
        raise RuntimeError("verification blocked: observed deployment DEMO_MODE is not 1")
    if observation.get("demo_run_id") != CANONICAL_DEMO_RUN_ID:
        raise RuntimeError("verification blocked: observed canonical demo run ID is invalid")
    if observation.get("metadata_marker") != CANONICAL_DEMO_MARKER or observation.get("demo_marker") != CANONICAL_DEMO_MARKER:
        raise RuntimeError("verification blocked: observed canonical demo markers are invalid")
    if not isinstance(observation.get("deployment_id"), str) or not observation["deployment_id"]:
        raise RuntimeError("verification blocked: observed deployment identity is missing")
    observed_payload = {**payload, "observation": observation, "live_url": live_url, "demo_run_id": observation["demo_run_id"]}
    result = _run_live_verifier(observed_payload)
    result["action_key"] = _action(payload)
    result["deployment_commit"] = deployment_commit
    if result.get("complete") is not True:
        raise RuntimeError("verification did not report complete=true")
    if not result.get("external_identity"):
        raise RuntimeError("verification did not return external_identity")
    for field in (
        "live_url",
        "steps",
        "result",
        "screenshots",
        "screenshot_paths",
        "limits",
        "proof_path",
        "launch_post_path",
        "launch_post",
    ):
        if not result.get(field):
            raise RuntimeError(f"verification did not return proof field: {field}")
    screenshot_paths = result["screenshot_paths"]
    if not isinstance(screenshot_paths, list) or any(
        not isinstance(path, str) or not Path(path).is_file() for path in screenshot_paths
    ):
        raise RuntimeError("verification returned non-existent screenshot paths")
    for field in ("proof_path", "launch_post_path"):
        path = result[field]
        if not isinstance(path, str) or not Path(path).is_file():
            raise RuntimeError(f"verification returned non-existent {field}")
    launch_post_path = Path(result["launch_post_path"])
    if result["launch_post"] != launch_post_path.read_text(encoding="utf-8"):
        raise RuntimeError("verification launch post does not match its durable artifact")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "observe", "execute", "verify"))
    args = parser.parse_args()
    try:
        _require_project_python(args.command)
        payload = _read_input()
        value = {"prepare": _prepare, "observe": _observe, "execute": _execute, "verify": _verify}[args.command](payload)
        print(json.dumps(_sanitize_public_success(value), sort_keys=True))
        return 0
    except Exception as exc:
        evidence = _record_private_failure(
            args.command,
            exc,
            {"root": str(ROOT), "python": _failure_python_description()},
        )
        safe_error = _sanitize_failure_text(str(exc))
        print(json.dumps({"complete": False, "error": safe_error, "python": _failure_python_description(), "failure_evidence": str(evidence)}), flush=True)
        print(f"release {args.command} failed; evidence={evidence}\n{traceback.format_exc()}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
