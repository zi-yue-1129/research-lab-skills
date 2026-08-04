# Workspace Discovery and Resource Resolver — Design Spec

- **Date**: 2026-08-04
- **Status**: Draft, pending user review
- **Author**: Claude (brainstorming session with user)

## Problem

Every skill in this repo currently hardcodes its own idea of where project resources
live: `research-log` assumes `docs/research_log/`, `report-slides` assumes
`docs/slides/reports/`, and neither `deep-research` nor `academic-pipeline` has any
fixed convention at all (both currently ask the user ad hoc or write inline). This
means:

- Skills cannot be reused across projects with different folder conventions without
  editing `SKILL.md` files.
- There is no shared way to express "this role has multiple sources" (e.g. a
  read-only shared bibliography plus a project-local one).
- Every skill re-implements its own "does this directory exist, should I create it"
  logic.

## Goal

Introduce a **Resource Resolver**: a layer that maps logical resource *roles*
(research log, experiment config, results, slides, paper, bibliography) to actual
project paths, without assuming any particular folder name or repo structure.

Non-goals (explicitly out of scope for this design):

- Moving, reorganizing, or renaming any of the user's existing files or directories.
- Auto-creating any directory without an explicit, per-directory user confirmation.
- Fetching or syncing content from external services (Notion, Zotero, Google Drive,
  etc.) — the Resolver stores a URI string for such sources and nothing more.
- Designing the internal structure of `.research/state/`, `.research/events/`,
  `.research/indexes/`, `.research/cache/`. These directories are reserved for future
  subsystems (mode state tracking, event logging, discovery caching) and this design
  only creates them as empty placeholders. Their contents are a separate design.

## Architecture

```
skills/resource-resolver/references/resolver_roles.yaml
                                         ← role schema (6 roles, data-driven, extensible)
skills/resource-resolver/scripts/resolve.py
                                         ← CLI query/discovery/confirmation engine
.research/
  workspace.yaml                        ← confirmed role -> path mappings (this design)
  state/  events/  indexes/  cache/     ← reserved, empty, out of scope
.claude/settings.json (hooks.SessionStart)
                                         ← silently runs `resolve.py --check`
skills/{research-log,report-slides,
        deep-research,academic-pipeline}/SKILL.md
                                         ← call resolve.py for paths instead of
                                            hardcoding them
```

Skills are **consumers** of the Resolver. When a skill needs the path for a role, it
calls `resolve.py`. The Resolver never touches the filesystem beyond reading
`workspace.yaml` and (only on explicit user confirmation) creating a directory that
was just approved.

## Components

### `skills/resource-resolver/references/resolver_roles.yaml`

Static role registry, versioned with the skill suite, not normally edited by end
users. Adding a new role means adding an entry here — no code changes.

```yaml
version: 1
roles:
  - name: research_log
    description: Structured research log entries (one file per experiment/session)
    aliases: [research_log, research-log, lab_notes, labnotes, logs]
    default_relative_path: docs/research_log
    consumed_by: [research-log, research-mode]

  - name: experiment_config
    description: Experiment parameter/config files (yaml/json/toml run configs)
    aliases: [experiment_config, configs, experiments, runs, params]
    default_relative_path: configs
    consumed_by: [research-mode]

  - name: results
    description: Experiment outputs, metrics, artifacts
    aliases: [results, outputs, artifacts, evals]
    default_relative_path: results
    consumed_by: [research-log, report-slides]

  - name: slides
    description: Generated presentation decks and slide assets
    aliases: [slides, presentations, decks, reports]
    default_relative_path: docs/slides
    consumed_by: [report-slides]

  - name: paper
    description: Manuscript drafts and paper-related documents
    aliases: [paper, papers, manuscript, manuscripts, draft]
    default_relative_path: docs/papers
    consumed_by: [academic-pipeline]

  - name: bibliography
    description: Reference/citation libraries (BibTeX, Zotero exports, etc.)
    aliases: [bibliography, references, citations, bib]
    default_relative_path: docs/bibliography
    consumed_by: [deep-research, academic-pipeline]
```

### `.research/workspace.yaml`

Per-project, written only by `resolve.py --set` after explicit user confirmation.
Paths are always relative to the project root, defined as the nearest ancestor
directory (walking up from the CLI's working directory) containing a `.git` entry;
`resolve.py` errors out explicitly if no `.git` is found rather than guessing, since
every consuming skill already assumes it runs inside a git repository. This keeps
`workspace.yaml` safe to commit and share across a team. A role that has not been
confirmed simply does not appear as a key — it is never written as `null`.

```yaml
version: 1
resolved_at: "2026-08-04T10:00:00+08:00"
roles:
  research_log:
    primary: docs/research_log
    readonly_sources: []
    confirmed_at: "2026-08-04T10:00:00+08:00"

  bibliography:
    primary: docs/bibliography
    readonly_sources:
      - "notion://shared-lab-library"
    confirmed_at: "2026-08-04T10:02:00+08:00"
```

Multi-source rule: each role has exactly one `primary` (read + write) and an
optional `readonly_sources` list. Writes always go to `primary`. Reads may combine
`primary` with `readonly_sources`. This covers the large majority of cases (a shared
read-only reference plus a project-local write target) without the complexity of a
fully generic per-source read/write matrix.

External services are stored as opaque URI strings inside `readonly_sources` (or
`primary`, if the role's only home is external). `resolve.py` returns them verbatim;
it never dereferences or validates them.

### `skills/resource-resolver/scripts/resolve.py`

Three actions, all CLI, following the same pattern as the existing
`skills/research-log/scripts/git_context.py`:

**`resolve.py --check`** — read-only, silent-safe. Diffs the roles in
`resolver_roles.yaml` against the keys present in `workspace.yaml` and reports which
roles are configured vs. not. No filesystem scanning. Cheap enough to run at the
start of every session via the SessionStart hook.

**`resolve.py --role <name>`** — single-role lookup.
1. If `workspace.yaml` has a `primary` for `<name>`, return it (plus
   `readonly_sources` if present) and stop.
2. Otherwise, scan the project directory tree (depth-limited, default 3, skipping
   `.git`, `node_modules`, and similar) for directories whose name matches one of the
   role's `aliases`. Return the ranked candidate list (exact alias match ranked above
   partial match) — the caller (the LLM) presents these to the user and does not
   pick automatically.
3. If there are zero candidates, return `no_candidates` plus the role's
   `default_relative_path` as a suggested value.

**`resolve.py --set <role> --path <path> [--readonly <path> ...] [--create] [--skip]`**
— writes the user-confirmed mapping into `workspace.yaml`. `--create` is required to
actually create the directory if it doesn't exist yet; without it, `--set` only
records the mapping. `--skip` writes a marker (role present in `workspace.yaml`
without a `primary`) so `--check` distinguishes "asked and declined" from "never
asked." Used by both the one-time setup flow (loop over all roles) and the lazy
per-role confirmation flow (same write interface).

### SessionStart hook

Runs `resolve.py --check` at the start of each session and silently injects the
result (which roles are configured / unconfigured) into context. This removes the
dependency on the LLM remembering to check role status on its own, the same problem
`research-mode`'s current "run `git_context.py` silently" instruction has today (it's
an LLM instruction, not an enforced hook). If the hook fails for any reason
(missing dependency, permissions), it fails silently and does not block session
startup — this is the one place in the whole design where silent failure is
acceptable, because the hook is a convenience trigger and the lazy per-role fallback
(triggered from within `SKILL.md` instructions when a skill actually needs a role)
still works without it.

The hook command follows the same discovery pattern skills already use for their own
scripts (see `skills/research-log/SKILL.md`'s `LOG_STATS="$(find ~/.claude -path
"*/research-log/scripts/log_stats.py" | head -1)"`):

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

The trailing `|| true` guarantees the hook never returns a non-zero exit code that
could block session startup, consistent with the "silent failure is acceptable here"
rule above.

### Installation gap (found during self-review, fixed as part of this design)

`install.sh` currently only copies `skills/<name>/` directories into
`~/.claude/skills/` (see `LAB_SKILLS`/`ARS_SKILLS` arrays and the `cp -r
"$TMP/repo/skills/$skill" "$DEST/"` loop). `bridge/` is never installed at all — this
is a pre-existing gap that already silently breaks `bridge/scripts/passport_to_log.py`
for anyone who installs via `install.sh` rather than working inside this repo
directly.

Placing `resolve.py` under `bridge/scripts/` would inherit the same gap. This design
resolves it by **moving the Resolver's installable artifacts into their own skill
directory**, `skills/resource-resolver/`, containing `scripts/resolve.py` and
`references/resolver_roles.yaml` — following the exact same layout convention every
other skill already uses. `resource-resolver` is added to `install.sh` as an
always-installed dependency, unconditionally, regardless of `--lab-only` or
`--ars-only`, since both `LAB_SKILLS` and `ARS_SKILLS` consumers need it:

```bash
# install.sh: resource-resolver is a shared foundation, always installed
SKILLS=("resource-resolver" "${LAB_SKILLS[@]}" "${ARS_SKILLS[@]}")
# ... existing --ars-only / --lab-only handling still applies to the other two arrays,
# but resource-resolver is prepended unconditionally in both branches.
```

`bridge/` itself (and the pre-existing `passport_to_log.py` install gap) is left
untouched — fixing it is a separate concern from this design and not required for the
Resolver to work.

## Data Flow

**One-time setup** (`/resolve-workspace` or equivalent command): loop over all roles
in `resolver_roles.yaml`, run `--role <name>` for each, present candidates (or "no
candidates, suggest default") to the user, confirm, call `--set`.

**Lazy first-use** (fallback, and the primary trigger per the user's explicit
choice): a skill's `SKILL.md` calls `resolve.py --role <name>` when it needs that
role's path. If already configured, this returns instantly. If not, the skill
surfaces the candidate list (or the "no candidates" suggestion) to the user
conversationally, gets confirmation, and calls `--set` before proceeding.

## Error Handling and Edge Cases

- **Multiple candidates found**: all are returned, ranked by match confidence; the
  LLM presents them to the user, who picks. `resolve.py` never auto-selects.
- **Zero candidates found**: `resolve.py` returns `no_candidates` plus the
  `default_relative_path` suggestion. The LLM asks the user whether to create a new
  directory there or specify a different path. `resolve.py` never creates a
  directory on its own — creation only happens via an explicit `--create` flag on a
  `--set` call the user has approved.
- **Previously confirmed `primary` path no longer exists**: `resolve.py --role`
  does a lightweight existence check before returning a cached `primary`. If it's
  gone, it returns `stale_mapping` instead of silently returning a dead path or
  silently rewriting `workspace.yaml` (the path might just be un-checked-out, not
  actually gone — rewriting would be presumptuous). The LLM prompts the user to
  re-resolve.
- **Malformed `workspace.yaml`**: `--set` refuses to write and reports a parse
  error. `--check` and `--role` degrade to read-only behavior with a clear error
  message. `resolve.py` never attempts to auto-repair a file the user may have
  hand-edited.
- **Role explicitly skipped during setup**: recorded via `--skip` as a marker (role
  key present, no `primary`), so future `--check` calls don't re-prompt for it.

## Migration Plan for Existing Skills

Migration is a mechanical swap of hardcoded path literals for `resolve.py` calls; it
does not change any skill's existing behavior, output format, or interaction flow.
This decouples "does the Resolver work" from "did the migration break anything."

- **`research-log`** (heavy migration): 20+ occurrences of `docs/research_log`
  throughout `SKILL.md`, including inside bash snippets (`--dir docs/research_log`).
  Add a one-time `resolve.py --role research_log` call in the Setup section, store
  the result as `$RESEARCH_LOG_DIR`, and replace the literal path everywhere else
  with the variable.
- **`report-slides`** (heavy migration + one cross-role read): replace
  `docs/slides/reports/`, `docs/slides/_style.md`, `docs/slides/styles/` with
  `resolve.py --role slides`. Separately, `SKILL.md:80` reads
  `docs/research_log/INDEX.md` — this is a read-only consumption of the
  `research_log` role and should call `resolve.py --role research_log` instead,
  demonstrating that a single skill can consume more than one role.
- **`deep-research`** (net-new adoption, not a migration): currently has no fixed
  output convention. Add a `resolve.py --role bibliography` (or `results`, depending
  on context) call at the point where it currently asks the user ad hoc where to
  save something, replacing a repeated per-run question with the Resolver's
  one-time-then-cached confirmation flow.
- **`academic-pipeline`** (orchestrator, net-new adoption): call
  `resolve.py --role paper` once at Stage 1 and pass the resolved path down to
  `academic-paper`, rather than querying per stage.

## Testing Plan

**`resolve.py` unit tests** (`skills/resource-resolver/scripts/tests/test_resolve.py`,
following the existing pattern in `bridge/scripts/tests/`):

- `--check` against an empty `workspace.yaml` (all roles unconfigured) and a
  partially-populated one (correct diff).
- `--role` already-configured case (returns `primary` directly from `workspace.yaml`);
  unconfigured case with a temp directory tree exercising alias matching and
  candidate ranking; zero-candidate case returns `no_candidates` plus the default
  suggestion.
- `--set`: new role, overwrite of an existing role, `--create` present vs. absent
  (directory actually created or not), `--skip` marker behavior.
- Edge cases: malformed `workspace.yaml` causes `--set` to refuse with a clear
  error; a `primary` path deleted after confirmation causes `--role` to report
  `stale_mapping`.
- Path serialization: paths are always written/read relative to the detected
  project root regardless of the CLI's current working directory at invocation time.

**Manual integration walkthrough** (not automated, matching how this repo currently
validates skill changes):

- Run the one-time setup flow in this repo itself: `research_log` discovery should
  find the existing `docs/research_log/` (since it's already there), validating the
  alias-matching logic against real data.
- Confirm `report-slides`'s read of the `research_log` role (via the migrated call)
  returns the same `INDEX.md` content as before migration.
- Confirm the SessionStart hook does not block session startup when it fails (e.g.
  temporarily break `workspace.yaml` permissions and verify the session still
  starts).

Out of scope for testing: `.research/state/`, `events/`, `indexes/`, `cache/` — no
behavior is defined for them in this design.
