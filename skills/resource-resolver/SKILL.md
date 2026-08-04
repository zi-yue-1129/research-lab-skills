---
name: resource-resolver
description: Maps logical resource roles (research log, experiment config, results, slides, paper, bibliography) to actual project paths, without assuming any folder naming convention. Use when a skill needs to know where to read or write a project resource, or when the user wants to set up or change where these resources live. Triggers on phrases like "set up my workspace", "where should slides go", "change the research log location", "resolve workspace".
metadata:
  data_access_level: raw
  task_type: open-ended
---

# Resource Resolver

Maps six logical resource **roles** to actual project paths, confirmed by the
user and recorded in `.research/workspace.yaml`. Other skills call `resolve.py`
instead of hardcoding paths like `docs/research_log/`. This skill never moves,
reorganizes, or renames existing files, and never creates a directory without
an explicit user-confirmed `--create`.

## Roles

| Role | Default | Consumed by |
|------|---------|-------------|
| `research_log` | `docs/research_log` | research-log, research-mode |
| `experiment_config` | `configs` | research-mode |
| `results` | `results` | research-log, report-slides |
| `slides` | `docs/slides` | report-slides |
| `paper` | `docs/papers` | academic-pipeline |
| `bibliography` | `docs/bibliography` | deep-research, academic-pipeline |

Full definitions (aliases used for discovery, descriptions) live in
`references/resolver_roles.yaml`.

## `/resolve-workspace` (one-time setup)

Run this once per project to confirm all six roles up front:

```bash
# macOS / Linux / Git Bash:
RESOLVE="$(find ~/.claude -path "*/resource-resolver/scripts/resolve.py" | head -1)"
python "$RESOLVE" --check --json
```

```powershell
# Windows (PowerShell):
$RESOLVE = (Get-ChildItem $env:USERPROFILE\.claude -Recurse -Filter resolve.py |
    Where-Object FullName -like "*resource-resolver*" | Select-Object -First 1).FullName
python $RESOLVE --check --json
```

For every role listed under `"unconfigured"`:

1. Run `python "$RESOLVE" --role <name> --json`.
2. If `status` is `"unresolved"`, present the `candidates` list to the user
   and let them pick one (or name a different path).
3. If `status` is `"no_candidates"`, tell the user no matching directory was
   found and suggest `default_relative_path`; let them accept it, name a
   different path, or say the role doesn't apply to this project.
4. If the user names a path that doesn't exist yet, ask explicitly whether to
   create it. Only then call `--set <name> --path <chosen-path> --create`.
   If it already exists, omit `--create`.
5. If the user says a role doesn't apply here, call
   `python "$RESOLVE" --set <name> --skip` so future checks don't re-ask.

## First-use role confirmation (lazy fallback)

If a skill needs a role that turns out to be unconfigured mid-task, don't stop
and force the user through the full setup flow — run the same `--role` /
`--set` sequence above for just that one role, inline, then continue.

## Calling convention for other skills

This is the canonical pattern. Other skills reference this section rather than
restating the branching logic.

```bash
# macOS / Linux / Git Bash:
RESOLVE="$(find ~/.claude -path "*/resource-resolver/scripts/resolve.py" | head -1)"
ROLE_JSON=$(python "$RESOLVE" --role <role_name> --json)
TARGET_DIR=$(echo "$ROLE_JSON" | python3 -c "
import json, sys
d = json.load(sys.stdin)
if d.get('status') == 'resolved':
    print(d['primary'])
")
```

```powershell
# Windows (PowerShell):
$RESOLVE = (Get-ChildItem $env:USERPROFILE\.claude -Recurse -Filter resolve.py |
    Where-Object FullName -like "*resource-resolver*" | Select-Object -First 1).FullName
$RoleJson = python $RESOLVE --role <role_name> --json | ConvertFrom-Json
$TargetDir = if ($RoleJson.status -eq "resolved") { $RoleJson.primary } else { "" }
```

**Only a `"resolved"` status yields a usable path.** Never read `primary`
without checking `status` first: a `stale_mapping` response *also* carries a
non-empty `primary` — the previously confirmed path that no longer exists — so
keying off `primary` alone silently proceeds with a dead path, and any skill
that creates missing directories would silently recreate it at the old
location the user just moved away from.

**If `$TARGET_DIR` (or `$TargetDir`) is empty, inspect `$ROLE_JSON` itself
before assuming the role is merely unconfigured.** Check in this order:

1. **An `error` key is present** (`{"error": ..., "message": ...}`, exit
   code 1) — the resolver itself failed: unparseable `workspace.yaml`, no git
   root above the working directory, an unreadable role registry. Surface
   `message` to the user and stop. Do **not** fall into the confirmation flow;
   there is nothing to confirm, and the same error will just recur.
2. **`status` is `"stale_mapping"`** — the role was confirmed previously, but
   its `primary` no longer exists (moved, renamed, or deleted). Tell the user
   the configured path is gone, show it, and ask them to re-confirm a
   location. Never silently recreate the old path.
3. **`status` is `"unresolved"` or `"no_candidates"`** — the role has genuinely
   never been confirmed for this project. Follow "First-use role confirmation"
   above.

Because every failure path is reported as JSON on stdout (never as a raw
traceback), `$ROLE_JSON` is always safe to parse.

Shell state does not persist across separate tool-call invocations. If a later
step needs the resolved path in a new bash/PowerShell call, either re-run the
resolve snippet in that same call, or substitute the already-resolved path as
a literal value into the command.

## Optional: SessionStart hook

Add this to `.claude/settings.json` (project or user level, via the
`update-config` skill or by hand) to silently surface unconfigured roles at
the start of every session, instead of relying on a skill to think to check:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "f=$(find ~/.claude -path '*/resource-resolver/scripts/resolve.py' 2>/dev/null | head -1); [ -n \"$f\" ] && python3 \"$f\" --check || true"
          }
        ]
      }
    ]
  }
}
```

This hook is intentionally allowed to fail silently (`|| true`) — it's a
convenience trigger, not a requirement. Every skill above still resolves
roles lazily on first use even if this hook is never installed.

## Non-goals

- Never moves, reorganizes, or renames existing user files or directories.
- Never creates a directory without an explicit user-confirmed `--create`.
- Never fetches or syncs external services (Notion, Zotero, Google Drive,
  etc.) — a `readonly_sources` or `primary` entry containing `://` is stored
  and returned verbatim, never dereferenced.
- `.research/state/`, `.research/events/`, `.research/indexes/`,
  `.research/cache/` are reserved empty directories for future subsystems;
  this skill does not read or write inside them.
