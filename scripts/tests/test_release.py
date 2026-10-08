import base64
import json
import errno
import stat
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import io
from pathlib import Path
from pathlib import PurePosixPath
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import release


ROOT = Path(__file__).resolve().parents[2]
PYTHON = str(ROOT / ".venv" / "Scripts" / "python.exe")
EXPECTED_COMMIT = release._git("rev-parse", "HEAD")


def _git_bash_executable() -> Path:
    """Resolve Bash without assuming a host install path."""
    candidates = []
    for name in ("bash.exe", "bash"):
        resolved = shutil.which(name)
        if resolved:
            candidates.append(Path(resolved).resolve())
    git = shutil.which("git.exe") or shutil.which("git")
    if git:
        git_path = Path(git).resolve()
        candidates.extend(
            [
                git_path.parent.parent / "usr" / "bin" / "bash.exe",
                Path(subprocess.check_output([str(git_path), "--exec-path"], text=True).strip()).parent / "bash.exe",
            ]
        )
    for candidate in candidates:
        if not candidate.is_file() or "WindowsApps" in str(candidate):
            continue
        probe = subprocess.run(
            [
                str(candidate),
                "-lc",
                "test -r \"$(cygpath -w \"$1\")\"",
                "bash",
                str(Path(tempfile.gettempdir()).resolve()),
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if probe.returncode == 0:
            return candidate
    raise RuntimeError("supported Git Bash executable is not available")


def _bash_path(path: Path) -> str:
    """Convert a native path only when it enters a Bash command."""
    bash_tmp_root_result = subprocess.run(
        [
            str(_git_bash_executable()),
            "-lc",
            "cygpath -w /tmp",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    bash_tmp_root = Path(bash_tmp_root_result.stdout.strip()).resolve()
    resolved_path = path.resolve()
    if resolved_path.is_relative_to(bash_tmp_root):
        relative = resolved_path.relative_to(bash_tmp_root)
        return PurePosixPath("/tmp", *relative.parts).as_posix()

    result = subprocess.run(
        [str(_git_bash_executable()), "-lc", 'cygpath -u "$1"', "bash", str(path.resolve())],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _bash_writable_temp_root() -> Path:
    """Return one verified fixture root derived from the native temp directory."""
    root = Path(tempfile.gettempdir()).resolve() / "citespan-release-test-fixtures"
    if root == ROOT or ROOT in root.parents:
        raise RuntimeError(f"fixture root is inside the source checkout: {root}")
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = Path(tempfile.mkdtemp(prefix="citespan-bash-probe-", dir=root))
        try:
            probe_bash_path = _bash_path(probe)
            result = subprocess.run(
                [
                    str(_git_bash_executable()),
                    "-lc",
                    'touch "$1/.citespan-write-probe" && rm "$1/.citespan-write-probe"',
                    "bash",
                    probe_bash_path,
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"Git Bash access failed for {probe}: {result.stderr.strip()}"
                )
        finally:
            _remove_fixture_path(probe, "fixture probe")
            if probe.exists():
                raise RuntimeError(f"fixture probe cleanup failed: {probe}")
    except Exception as exc:
        if isinstance(exc, RuntimeError):
            raise
        raise RuntimeError(f"fixture root operation failed for {root}: {exc}") from exc
    return root


def _remove_fixture_path(path: Path, label: str) -> None:
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


@pytest.fixture
def bash_tmp_path():
    root = _bash_writable_temp_root()
    path = Path(tempfile.mkdtemp(prefix="citespan-release-test-", dir=root))
    try:
        yield path
    finally:
        _remove_fixture_path(path, "bash fixture")


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
    mkdir -p "$backup_dir"
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
        "OPENAI_API_KEY=\n"
        "OPENROUTER_API_KEY=\n"
        "NEO4J_PASSWORD=synthetic-neo4j-password\n"
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
        "live_url": "https://citespan.example",
        "demo_run_id": "11111111-1111-4111-8111-111111111111",
        "DEMO_MODE": "1",
    }
    payload.update(extra)
    return payload


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


@pytest.mark.parametrize("command", ["prepare", "observe", "execute", "verify"])
def test_each_hook_emits_json_when_project_python_is_missing(command, capsys):
    with patch.object(
        release,
        "_require_project_python",
        side_effect=RuntimeError("project Python is missing"),
    ) as require_python, patch.object(
        release, "_record_private_failure", return_value=Path("private-failure.json")
    ), patch.object(sys, "argv", ["release.py", command]):
        assert release.main() == 1

    value = json.loads(capsys.readouterr().out)
    assert value["complete"] is False
    assert "project Python is missing" in value["error"]
    require_python.assert_called_once_with(command)


def test_prepare_returns_one_contract_object_without_secret_values():
    result = run_hook("prepare", valid_payload(), DEMO_MODE="1")

    value = json.loads(result.stdout)
    assert result.returncode == 0, result.stderr
    assert value["complete"] is True
    assert value["product_name"] == "CiteSpan"
    assert "api_key" not in result.stdout.lower()


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


def test_prepare_cli_accepts_only_contract_payload_fields():
    result = run_hook(
        "prepare",
        {
            "action_key": "citespan-release",
            "intent": {"action_key": "citespan-release", "expected_commit": EXPECTED_COMMIT},
            "DEMO_MODE": "1",
        },
    )

    value = json.loads(result.stdout)
    assert result.returncode == 0, result.stderr
    assert value["complete"] is True
    assert value["release_config"]["route"].startswith("dedicated Caddy")


def test_prepare_ignores_unrelated_supervisor_llm_environment():
    result = run_hook(
        "prepare",
        valid_payload(),
        DEMO_MODE="1",
        OPENROUTER_API_KEY="supervisor-owned-value",
        OPENAI_API_KEY="supervisor-owned-value",
    )

    value = json.loads(result.stdout)
    assert result.returncode == 0, result.stderr
    assert value["complete"] is True


def test_prepare_rejects_literal_target_credential():
    result = run_hook(
        "prepare",
        {
            **valid_payload(),
            "environment": {"OPENROUTER_API_KEY": "literal-target-secret"},
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


def test_prepare_reports_script_relative_project_python_and_demo_limits():
    result = run_hook("prepare", valid_payload(), DEMO_MODE="1")

    value = json.loads(result.stdout)
    assert result.returncode == 0, result.stderr
    assert value["python"].endswith(".venv/Scripts/python.exe")
    assert value["demo_policy"] == {
        "upload": False,
        "reset_to_sample": True,
        "sample": "canonical synthetic UFDR",
    }


def test_observe_accepts_the_deployment_provider_payload_without_argv():
    payload = valid_payload()
    with patch.object(release, "_ssh", return_value="NOT_DEPLOYED"):
        value = release._observe(payload)
    assert value["action_key"] == "citespan-release"
    assert value["observed"] is False


def test_execute_fails_closed_without_deployment_evidence():
    with patch.object(release, "_critical_dependency_findings", return_value=[]), patch.object(
        release, "_branding_findings", return_value=[]
    ), patch.object(release, "_ssh", return_value="NOT_DEPLOYED"):
        with pytest.raises(RuntimeError, match="deployment did not produce remote commit evidence"):
            release._execute(valid_payload())


def test_deployment_command_executes_checked_recovery_and_restores_prior_state(tmp_path):
    command = release._deployment_command(valid_payload())
    start = command.index("rollback() {")
    end = command.index("\ntrap rollback EXIT\n", start)
    rollback_function = command[start:end]

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
        "case \"$*\" in *' up -d '*) exit 1;; esac\n"
        "case \"$*\" in *' down '*) exit 1;; esac\n"
        "case \"$*\" in *'ps -aq'*candidate-static*) echo candidate-static;; *'ps -aq'*previous-static*) echo previous-static;; esac\n",
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
    assert "recovery incomplete" in result.stderr
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
    assert "deployment failed at forced_failure" in result.stderr
    assert "|| true" not in command
    assert "docker volume rm" not in command
    assert "tar " not in command
    assert "recovery.log" in command


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
            "live_url": "https://citespan.example",
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
    (deploy_root / "authoritative-data.txt").write_text("prior-data\n", encoding="utf-8")
    (caddy_root / "Caddyfile").write_text("previous-route\n", encoding="utf-8")

    call_log = tmp_path / "calls.log"
    call_log.touch()
    (bin_root / "docker").write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$CALL_LOG\"\n"
        "case \"$*\" in\n"
        "  *'inspect -f {{.State.Running}} '*) echo true ;;\n"
        "  *'inspect -f {{.Name}} '*) container=; for argument do container=$argument; done; printf '/%s\\n' \"$container\" ;;\n"
        "  *'inspect '*) printf '%s\\n' '[{\"Id\":\"prior-id\",\"Name\":\"previous\",\"State\":{\"Running\":true},\"Config\":{\"Env\":[\"CITESPAN_SYNTHETIC_ONLY=1\"]}}]' ;;\n"
        "  *'pg_isready'*) exit 0 ;;\n"
        "  *'7700/health'*) printf 'available\\n' ;;\n"
        "  *'9000/minio/health/live'*) exit 0 ;;\n"
        "  *'base64 -d'*) printf 'EMPTY\\n' ;;\n"
        "  *' exec '*) exit 0 ;;\n"
        "  *' network inspect '*|*' volume inspect '*) printf 'ok\\n' ;;\n"
        "  *' config --format json'*) printf '%s\\n' \"{\\\"services\\\":{\\\"backend\\\":{\\\"ports\\\":[{\\\"host_ip\\\":\\\"127.0.0.1\\\",\\\"published\\\":${CITESPAN_BACKEND_PORT},\\\"target\\\":8000,\\\"protocol\\\":\\\"tcp\\\"}]}}}\" ;;\n"
        "  *'up -d --no-deps --build backend'*) if [ \"$CITESPAN_FAIL_STEP\" = pre_cutover ]; then printf '%s\\n' \"injected failure: $CITESPAN_FAIL_STEP\" >> \"$CALL_LOG\"; echo \"injected failure: $CITESPAN_FAIL_STEP\" >&2; exit 42; fi ;;\n"
        "  *'ps -q '*) echo candidate-id ;;\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    (bin_root / "git").write_text(
        f"#!/bin/sh\nprintf '%s\\n' \"git $*\" >> \"$CALL_LOG\"\ncase \"$1\" in -C) shift 2;; esac\n[ \"$1\" = rev-parse ] && echo {EXPECTED_COMMIT}\nexit 0\n",
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
        "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$CALL_LOG\"\ncase \"$*\" in *https://*) if [ \"$CITESPAN_FAIL_STEP\" = post_cutover ]; then printf '%s\\n' \"injected failure: $CITESPAN_FAIL_STEP\" >> \"$CALL_LOG\"; echo \"injected failure: $CITESPAN_FAIL_STEP\" >&2; exit 22; fi;; esac\nprintf 'CiteSpan\\n'\n",
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
    env = {
        **os.environ,
        "PATH": f"{_bash_path(bin_root)}:{os.environ['PATH']}",
        "CALL_LOG": _bash_path(call_log),
        "CITESPAN_FAIL_STEP": failure,
        "CITESPAN_ROUTE_NATIVE": str(bash_tmp_native_root / "citespan-route"),
        "CITESPAN_CADDY_NATIVE": str(caddy_root / "Caddyfile"),
    }
    result = subprocess.run(
        [str(_git_bash_executable()), _bash_path(script_path)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
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
    assert not any("volume rm" in call for call in calls)
    if failure == "pre_cutover":
        up_index = next(index for index, call in enumerate(calls) if "up -d --no-deps --build backend" in call)
        assert compose_calls[0] < up_index
        assert "injected failure: pre_cutover" in result.stderr
        assert "injected failure: pre_cutover" in calls
    else:
        https_index = next(index for index, call in enumerate(calls) if "https://" in call)
        assert compose_calls[0] < https_index
        assert any("down --remove-orphans" in call for call in calls)
        assert "injected failure: post_cutover" in result.stderr or "deployment failed at" in result.stderr
        assert any("injected failure: post_cutover" in call for call in calls)


def test_execute_deploys_to_authorized_host_and_returns_remote_commit():
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        if any("citespan-deployment.json" in item for item in argv):
            return subprocess.CompletedProcess(
                argv,
                0,
                json.dumps(
                    {
                        "deployment_commit": EXPECTED_COMMIT,
                        "live_url": "https://citespan.example",
                        "deployment_id": "citespan-test",
                        "backend_port": 18000,
                        "frontend_port": 18001,
                        "static_container": "citespan-test-static-1",
                        "static_content_dir": "/opt/citespan/.citespan-backups/1/static-1",
                        "synthetic_only": True,
                        "demo_run_id": release.CANONICAL_DEMO_RUN_ID,
                        "metadata_marker": release.CANONICAL_DEMO_MARKER,
                        "demo_marker": release.CANONICAL_DEMO_MARKER,
                    }
                ),
                "",
            )
        if any("rev-parse" in item for item in argv):
            return subprocess.CompletedProcess(argv, 0, f"{EXPECTED_COMMIT}\n", "")
        return subprocess.CompletedProcess(argv, 0, "deployed\n", "")

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
        release.subprocess, "run", side_effect=fake_run
    ), patch.object(release, "SSH_KEY", Path(__file__)):
        result = release._execute(payload)

    assert result["complete"] is True
    assert result["deployment_commit"] == EXPECTED_COMMIT
    assert result["external_identity"] == "root@169.58.64.150:citespan"
    assert any(argv[0] == "ssh" and any("169.58.64.150" in item for item in argv) for argv, _ in calls)
    assert all("deployment_result" not in json.dumps(argv) for argv, _ in calls)


def test_observe_fails_loudly_when_external_host_cannot_be_observed():
    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 255, "", "connection refused")

    payload = valid_payload()
    with patch.object(release.subprocess, "run", side_effect=fake_run), patch.object(
        release, "SSH_KEY", Path(__file__)
    ), pytest.raises(RuntimeError, match="remote deployment command failed"):
        release._observe(payload)


def test_observe_reports_not_deployed_without_claiming_success():
    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, "NOT_DEPLOYED\n", "")

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
                    "live_url": "https://citespan.example",
                    "deployment_id": "citespan-test",
                    "backend_port": 18000,
                    "frontend_port": 18001,
                    "static_container": "citespan-test-static-1",
                    "static_content_dir": "/opt/citespan/.citespan-backups/1/static-1",
                    "synthetic_only": True,
                    "demo_run_id": release.CANONICAL_DEMO_RUN_ID,
                    "metadata_marker": release.CANONICAL_DEMO_MARKER,
                    "demo_marker": release.CANONICAL_DEMO_MARKER,
                }
            ),
            "",
        )

    payload = valid_payload()
    with patch.object(release.subprocess, "run", side_effect=fake_run), patch.object(
        release, "SSH_KEY", Path(__file__)
    ):
        result = release._observe(payload)

    assert result["observed"] is True
    assert result["deployment_commit"] == EXPECTED_COMMIT
    assert "source_commit" not in result


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("live_url", "http://citespan.example", "live HTTPS URL"),
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
        "live_url": "https://citespan.example",
        "deployment_id": "citespan-test",
        "backend_port": 18000,
        "frontend_port": 18001,
        "static_container": "citespan-test-static-1",
        "static_content_dir": "/opt/citespan/.citespan-backups/1/static-1",
        "synthetic_only": True,
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
            "deployment_commit": EXPECTED_COMMIT,
            "external_identity": "root@169.58.64.150:citespan",
            "live_url": "https://citespan.example",
            "deployment_id": "citespan-test",
            "synthetic_only": True,
            "demo_run_id": release.CANONICAL_DEMO_RUN_ID,
            "metadata_marker": release.CANONICAL_DEMO_MARKER,
            "demo_marker": release.CANONICAL_DEMO_MARKER,
        },
        "live_url": "https://citespan.example",
        "demo_run_id": "synthetic-run",
    }
    with patch.object(release, "_check_payload_secrets"), patch.object(
        release,
        "_run_live_verifier",
        return_value={
            "complete": True,
            "external_identity": "https://citespan.example",
            "live_url": "https://citespan.example",
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


def test_live_verifier_uses_durable_external_directory_and_returns_draft(tmp_path):
    verifier_result = {
        "complete": True,
        "external_identity": "https://citespan.example",
        "live_url": "https://citespan.example",
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
        "deployment_commit": EXPECTED_COMMIT,
        "live_url": "https://citespan.example",
        "deployment_id": "citespan-observed",
        "synthetic_only": True,
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

    def run_verifier(argv, **kwargs):
        calls.append(argv)
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


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("live_url", "http://citespan.example", "live URL"),
        ("live_url", "https://other.example", "payload live URL"),
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
        "deployment_commit": EXPECTED_COMMIT,
        "live_url": "https://citespan.example",
        "deployment_id": "citespan-test",
        "synthetic_only": True,
        "demo_run_id": release.CANONICAL_DEMO_RUN_ID,
        "metadata_marker": release.CANONICAL_DEMO_MARKER,
        "demo_marker": release.CANONICAL_DEMO_MARKER,
    }
    observation[field] = value
    payload = {**valid_payload(), "observation": observation}
    if field == "live_url" and value == "https://other.example":
        payload["live_url"] = "https://citespan.example"
    with patch.object(release, "_check_payload_secrets"), pytest.raises(
        RuntimeError, match=message
    ):
        release._verify(payload)


def test_verify_passes_exact_observed_url_and_identity_to_live_verifier(tmp_path):
    observation = {
        "observed": True,
        "deployment_commit": EXPECTED_COMMIT,
        "live_url": "https://observed.example",
        "deployment_id": "citespan-observed",
        "synthetic_only": True,
        "demo_run_id": release.CANONICAL_DEMO_RUN_ID,
        "metadata_marker": release.CANONICAL_DEMO_MARKER,
        "demo_marker": release.CANONICAL_DEMO_MARKER,
    }
    payload = {**valid_payload(), "live_url": "https://observed.example", "observation": observation}
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
        "external_identity": "https://observed.example",
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
        "live_url": "https://citespan.example",
        "demo_run_id": "synthetic-run",
    }
    payload["observation"]["observed"] = True
    with patch.object(release, "_check_payload_secrets"), patch.object(
        release, "_run_live_verifier", return_value={"complete": True}
    ), pytest.raises(RuntimeError, match="expected commit was not supplied"):
        release._verify(payload)


def test_prepare_does_not_require_provider_external_fields():
    payload = valid_payload()
    payload.pop("live_url")
    payload.pop("demo_run_id")
    with patch.object(release, "_history_credential_findings", return_value=[]), patch.object(
        release, "_critical_dependency_findings", return_value=[]
    ):
        result = release._prepare(payload)
    assert result["complete"] is True
    assert result["release_config"]["live_url"].startswith("https://")


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
            valid_payload(intent={"action_key": "citespan-release", "expected_commit": fixture_commit})
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
            valid_payload(intent={"action_key": "citespan-release", "expected_commit": fixture_commit})
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

    commands = [call.args[0] for call in run.call_args_list]
    assert ["C:/project/.venv/Scripts/python.exe", "-m", "pip", "install", "--disable-pip-version-check", "playwright==1.55.0"] in commands
    assert ["C:/project/.venv/Scripts/python.exe", "-m", "playwright", "install", "chromium"] in commands


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
        "playwright==1.55.0",
    ]
    assert value["returncode"] == "unknown"
    assert value["stdout"] == "installer output"
    assert value["stderr"] == "installer error"


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
        "curl --fail --silent --show-error http://127.0.0.1:$candidate_frontend_port/ | grep -qi CiteSpan"
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
    assert 'prior-backend.inspect.json' in command
    assert 'prior-static.inspect.json' in command
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
        "https://citespan.example",
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
    if os.name == "posix":
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
    assert metadata["live_url"] == "https://citespan.example"
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


def test_demo_audit_allows_product_state_but_rejects_extra_forensic_state():
    audit = release._demo_audit_script()

    assert "User" in audit
    assert "CaseMembership" in audit
    assert "Query" in audit
    assert "Result" in audit
    assert "exact_count(User" not in audit
    assert "exact_count(CaseMembership" not in audit
    assert "exact_count(Query" not in audit
    assert "exact_count(Result" not in audit
    assert '(Call, "Call")' in audit
    assert '(Media, "Media")' in audit
    assert '(Transcript, "Transcript")' in audit


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
    analyst = User(username='synthetic analyst', email='analyst@example.invalid', password_hash='disabled')
    session.add(analyst)
    session.commit()
    session.refresh(analyst)
    session.add(CaseMembership(run_id=run.id, user_id=analyst.id, role='viewer', granted_by=owner.id))
    rule = Rule(user_id=analyst.id, title='Transfer query', description='Synthetic query', query_text='Show transfers')
    session.add(rule)
    session.commit()
    session.refresh(rule)
    session.add_all([
        Query(run_id=run.id, user_id=analyst.id, query_text='Show transfers', status='completed', result_count=1),
        Result(run_id=run.id, rule_id=rule.id, result_type='message', evidence_data='synthetic'),
        AuditEvent(seq=1, event_type='query', run_id=run.id, user_id=analyst.id, timestamp=datetime.datetime.utcnow(), payload='{{}}'),
        Backup(user_id=analyst.id, event_type='user_login', description='Synthetic login'),
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
    analyst = User(username='synthetic analyst', email='analyst@example.invalid', password_hash='disabled')
    session.add(analyst); session.commit(); session.refresh(analyst)
    session.add(CaseMembership(run_id=run.id, user_id=analyst.id, role='viewer', granted_by=owner.id))
    rule = Rule(user_id=analyst.id, title='Transfer query', description='Synthetic query', query_text='Show transfers')
    session.add(rule); session.commit(); session.refresh(rule)
    session.add(Query(run_id=run.id, user_id=analyst.id, query_text='Show transfers', status='completed', result_count=1))
    session.add(Result(run_id=run.id, rule_id=rule.id, result_type='message', evidence_data='synthetic'))
    session.add(AuditEvent(seq=1, event_type='query', run_id=run.id, user_id=analyst.id, timestamp=datetime.datetime.utcnow(), payload='{}'))
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
    assert command.index("CITESPAN_SYNTHETIC_MARKER") < command.index("receipt=")
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


def test_history_scan_returns_only_compromised_credential_fingerprints():
    secret = "sk-or-v1-123456789012345678901234567890"
    completed = subprocess.CompletedProcess(
        ["git"], 0, f"OPENROUTER_API_KEY={secret}\n".encode(), b""
    )
    with patch.object(release.subprocess, "run", return_value=completed):
        findings = release._history_credential_findings()

    assert findings == ["OpenRouter credential in git history"]
    assert secret not in json.dumps(findings)


def test_history_secret_hashes_use_named_value_groups_for_each_provider():
    history = (
        "OPENROUTER_API_KEY=sk-or-v1-123456789012345678901234567890\n"
        "OPENAI_API_KEY=openai-123456789012345678901234\n"
        "NEO4J_PASSWORD=neo4j-secret-1234\n"
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
    "change, expected",
    [
        (lambda lines: [line for line in lines if not line.startswith("NEO4J_PASSWORD=")], "NEO4J_PASSWORD"),
        (lambda lines: lines + ["POSTGRES_USER=stale"], "duplicate"),
    ],
)
def test_remote_runtime_validation_rejects_missing_or_duplicate_keys(tmp_path, change, expected):
    lines = _complete_runtime_fixture().splitlines()
    result, _ = _run_runtime_validation(tmp_path, "\n".join(change(lines)) + "\n")

    assert result.returncode != 0
    assert expected in result.stderr


def test_remote_runtime_validation_rejects_compromised_service_value_without_leaking_it(tmp_path):
    secret = "synthetic-neo4j-password"
    compromised_hash = hashlib.sha256(secret.encode()).hexdigest()
    result, _ = _run_runtime_validation(tmp_path, _complete_runtime_fixture(), [compromised_hash])

    assert result.returncode != 0
    assert "NEO4J_PASSWORD" in result.stderr
    assert secret not in result.stderr
    assert compromised_hash not in result.stderr


def test_remote_runtime_validation_rejects_compromised_secret_key_without_mutation(tmp_path):
    secret = "previous"
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


def test_readiness_sanitizer_keeps_safe_cause_and_removes_runtime_secret():
    secret = "synthetic-readiness-secret"
    script = (
        release._readiness_sanitizer()
        + f'\nNEO4J_PASSWORD={secret}\n'
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
    ), patch.object(release, "_critical_dependency_findings", return_value=[]):
        result = release._prepare(valid_payload())

    assert result["complete"] is True
    assert result["credential_history_findings"] == ["Neo4j credential in git history"]


def test_runtime_compromise_proof_rejects_default_runtime_credentials():
    with patch.object(
        release,
        "_release_text",
        return_value=[(".env", "NEO4J_PASSWORD=CHANGE_ME")],
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


@pytest.mark.parametrize("command", ("prepare", "observe", "execute", "verify"))
def test_each_release_hook_emits_json_when_project_python_is_missing(
    command, monkeypatch, capsys
):
    missing_python = ROOT / ".missing-test-venv" / "Scripts" / "python.exe"
    monkeypatch.setattr(release, "PROJECT_PYTHON", missing_python)
    monkeypatch.setattr(release.sys, "argv", ["release.py", command])
    monkeypatch.setattr(release.sys, "stdin", io.StringIO("{}"))

    assert release.main() == 1
    output = capsys.readouterr().out.strip().splitlines()
    assert len(output) == 1
    value = json.loads(output[0])
    assert value["complete"] is False
    assert "project Python is missing" in value["error"]
    assert value["python"] == missing_python.as_posix()


def test_demo_seed_creates_whatsapp_aleapp_artifact_for_default_question():
    seed = release._demo_seed_script()

    assert "AleappArtifact" in seed
    assert 'filename="whatsapp_messages.csv"' in seed
    assert "bank transfer" in seed


def test_observe_rejects_remote_commit_mismatch():
    payload = valid_payload()
    observation = {
        "deployment_commit": "b" * 40,
        "live_url": "https://citespan.example",
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
