# CiteSpan deployment

This runbook describes the authorized personal-host deployment for the CiteSpan
slim demo. The release hooks deploy to `/opt/citespan` on
`root@169.58.64.150` with the existing key `~/.ssh/everything`.

The hosted demo uses the canonical synthetic Universal Forensic Data Report
(UFDR) sample. `DEMO_MODE=1` disables upload. Reset to sample is the only
allowed data mutation. The planner is deterministic demo behavior. It is not a
live large language model feature.

The current public URL is not hardcoded in this file. The release flow emits
and verifies the live HTTPS URL after deployment.

## Requirements

1. Create the project virtual environment at `.venv`.
2. Install project dependencies into that environment.
3. Keep compromised OpenRouter and Neo4j credentials out of runtime config.
4. Use only synthetic demo data. Do not upload or deploy real forensic data.
5. Do not install project dependencies into the Jarvis runtime.

The repository identity remains `aayushman-singh/ufdr-analyzer`. This is a
technical repository identifier. It is not the public product name.

## Release hooks

The server invokes each hook with one JSON object on standard input. Each hook
returns one JSON object on standard output. The hook uses the project Python at
`.venv/Scripts/python.exe` and script-relative paths. The hook does not use the
Jarvis runtime.

```powershell
$python = ".venv/Scripts/python.exe"
Get-Content phase-prepare.json -Raw | & $python scripts/release.py prepare | Tee-Object prepare.json
Get-Content phase-observe.json -Raw | & $python scripts/release.py observe | Tee-Object observe.json
Get-Content phase-execute.json -Raw | & $python scripts/release.py execute | Tee-Object execute.json
Get-Content phase-verify.json -Raw | & $python scripts/release.py verify | Tee-Object verify.json
```

Assigning `$payload` alone does not send it to the hook. If a caller stores a
payload in a variable, it must serialize and pipe it explicitly:

```powershell
$payload | ConvertTo-Json -Depth 20 | & $python scripts/release.py prepare
```

Use the exact payload required by the owner `DeploymentProvider` contract.
Each phase has a separate input contract:

1. `prepare` requires the provider `action_key`, the expected 40-character
   commit in `intent.expected_commit` or `expected_commit`, and the provider
   intent. It checks the local source and returns release readiness.
2. `observe` requires the provider `action_key` and expected commit. It reads
   the remote state and returns either the strict `not_deployed` observation or
   the complete deployed observation.
3. `execute` requires the same release input as `prepare`. It deploys to
   `/opt/citespan`, then obtains a fresh remote observation.
4. `verify` requires the provider `action_key`, expected commit, and the exact
   `observation` returned by `observe` or `execute`. Initial `not_deployed`
   verification is strict and does not prove a deployment. Do not fabricate an
   observation.

The hooks fail with an error object and diagnostic evidence when the input,
runtime, deployment, or proof is invalid. The current Contabo target is
`root@169.58.64.150:/opt/citespan`; the live HTTPS URL comes from the verified
remote observation. It is not the Fly or Vercel URL.

The normal sequence is:

1. Write a phase-specific provider payload for `prepare`.
2. Run `prepare` and stop on any failure.
3. Write the `observe` payload with the expected commit, then run `observe`.
4. Run `execute` only after preparation passes. It preserves authoritative
   stores, cuts over the route, and records deployment metadata.
5. Pass the actual `observe` result as `observation` in the `verify` payload.
   Run `verify` only after the live HTTPS target exists.

## Live user verification

Verification must use a clean end user session. It must prove all of these
steps in the live product:

1. Open the emitted HTTPS URL.
2. Sign up or sign in as a new test user.
3. Open the canonical synthetic sample.
4. Ask a natural language question.
5. Confirm that results include citations tied to evidence spans.
6. Confirm that upload is disabled and Reset to sample is available.

The verification proof stores the live URL, exact steps, observed result,
screenshots, and limits. A README, build result, or health response is not
proof. The launch post is created only after this user flow passes. Nothing is
published by the release hooks. The hosted demo is synthetic-only. It uses
`DEMO_MODE=1`, keeps real upload disabled, allows Reset to sample, and labels
the planner as deterministic demo behavior. A live large language model claim
is not valid.

## Legacy Fly configuration

`fly.toml` remains only as a compatibility record for the prior Fly deployment.
Its Fly application names and hostnames are legacy technical identifiers. They
are not current deployment instructions or the current launch URL. Do not use
that file to deploy CiteSpan.
