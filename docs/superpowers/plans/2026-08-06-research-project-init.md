# Research Project Initialization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new, independent skill — `research-project-init` — that runs a
lightweight guided dialogue to turn a preliminary research idea into a project
charter (Markdown, with every item tagged confirmed/assumption/suggestion/open)
plus a `Project` record and its Initial Research Questions registered in
`agent-state`. Close the loop left open by the unified-research-state work:
`--create-project` currently has no caller anywhere in the skill set.

**Architecture:** One small addition to `agent-state` (a bare `--create-question`
CLI action, so registering a Question doesn't require creating a Run), one new
skill directory (`skills/research-project-init/`, prose-driven — no sub-agent
team, the same shape as `research-log`/`report-slides`), and routing additions
to `.claude/CLAUDE.md` so the new skill has a place in the pipeline diagram,
the Skills Overview table, and the Routing Rules that already disambiguate the
academic-pipeline family.

**Tech Stack:** Same as `agent-state` — Python 3, PyYAML, `argparse` (stdlib),
`pytest` + `subprocess` for the one task with automated tests. Tasks 2 and 3
are documentation-only, consistent with how every other prose-driven skill in
this repo (`research-log`, `report-slides`, `deep-research`) carries no
automated test for its own dialogue flow.

**Design spec:** `docs/superpowers/specs/2026-08-06-research-project-init-design.md`.

## Global Constraints

- Every function signature has type hints; every public function/class has a
  Google-style docstring — non-negotiable even where the code is
  self-explanatory (user's global code-style standard).
- No silent failures: `--create-question` with empty/missing `--question` text
  raises `ValueError` at write time — it does not write a Question record with
  `text: null`. Every CLI error path prints valid JSON to stdout when `--json`
  is given and exits non-zero — never an uncaught traceback.
- Task 1 adds a two-line guard (`if not text: raise ValueError(...)`) to the
  **existing** `create_question()` in `state_store.py`. This is a deliberate,
  minimal tightening of an already-shipped function's contract — necessary
  because it previously only had one caller (`start_run`'s Branch 3, which
  already only calls it when `question_text` is truthy) and never needed to
  validate its own input. It is not scope creep on the just-merged
  unified-research-state feature; do not expand this into any other change to
  that function.
- All generated **file content** (the project charter, the charter template)
  is English regardless of conversation language — the skill's own dialogue
  prompts follow the conversation's language, matching "Default output
  language matches user input" in `.claude/CLAUDE.md`.
- All code comments, docstrings, commit subjects, and log/error messages are
  in English regardless of conversation language.
- Every code/prose snippet below is the actual content to write — no
  "implement later", no "similar to Task N" shorthand.
- `skills/agent-state/scripts/tests/test_state_cli.py` is already ~1478 lines
  (pre-existing, over the project's own ~1000-line guidance, and already
  explicitly parked as a known, accepted issue by the prior
  unified-research-state review). Task 1 adds ~70 lines to it. Do not attempt
  to split or refactor this file as part of this plan — that's unrelated to
  this feature and was already triaged as out of scope once.
- Baseline before Task 1: 87 tests passing
  (`pytest skills/agent-state/scripts/tests/ -v`). Task 1's final step re-runs
  the full suite and expects 93. Tasks 2 and 3 touch no test suite; their
  review is a reading review, not a pytest run.

---

### Task 1: `--create-question` CLI action in `agent-state`

**Files:**
- Modify: `skills/agent-state/scripts/state_store.py`
- Modify: `skills/agent-state/scripts/state.py`
- Test: `skills/agent-state/scripts/tests/test_state_cli.py`

**Interfaces:**
- Consumes: existing `state_store.create_question(project_root, text,
  origin_skill, project_id=None)`, existing `state_store.ProjectNotFoundError`.
- Produces (used by Task 2's `SKILL.md`):
  `python state.py --create-question --question TEXT [--skill NAME]
  [--project-id ID] [--json]` — creates a Question record directly, with
  **no** Run side effect (unlike `--start-run --question TEXT`).

- [ ] **Step 1: Write the failing tests**

Append to `skills/agent-state/scripts/tests/test_state_cli.py`:

```python
def test_create_question_returns_open_question(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(
        project, "--create-question", "--question", "Does this need offline support?",
        "--skill", "research-project-init", "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["text"] == "Does this need offline support?"
    assert data["origin_skill"] == "research-project-init"
    assert data["project_id"] == "proj_default"
    assert data["status"] == "open"
    assert data["id"].startswith("q_")


def test_create_question_without_skill_defaults_to_user(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--create-question", "--question", "Q?", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["origin_skill"] == "user"


def test_create_question_with_explicit_project_id(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    created = _run(project, "--create-project", "--name", "Offline Support Initiative", "--json")
    project_id = json.loads(created.stdout)["id"]

    result = _run(
        project, "--create-question", "--question", "Does this need offline support?",
        "--skill", "research-project-init", "--project-id", project_id, "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["project_id"] == project_id


def test_create_question_unknown_project_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(
        project, "--create-question", "--question", "Q?",
        "--project-id", "proj_missing", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ProjectNotFoundError"


def test_create_question_without_question_text_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--create-question", "--skill", "research-project-init", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"


def test_create_question_does_not_create_a_run(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    _run(
        project, "--create-question", "--question", "Does this need offline support?",
        "--skill", "research-project-init", "--json",
    )

    assert not (project / ".research" / "state" / "runs.yaml").exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest skills/agent-state/scripts/tests/test_state_cli.py -v -k create_question`
Expected: FAIL — `--create-question` isn't a recognized flag yet (argparse
rejects it since it's not in the mutually exclusive action group).

- [ ] **Step 3: Add the input-validation guard to `create_question()`**

In `skills/agent-state/scripts/state_store.py`, change:

```python
def create_question(
    project_root: Path,
    text: str,
    origin_skill: str,
    project_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new Question record with status "open".

    Args:
        project_root: The project's root directory.
        text: The request or sub-task text.
        origin_skill: Name of the skill that raised this Question.
        project_id: Project this Question belongs to. Defaults to the
            lazily-created "proj_default" if omitted.

    Returns:
        The full new Question record, including its generated "id".

    Raises:
        ProjectNotFoundError: If project_id is given but doesn't exist.
    """
    if project_id is None:
```

to:

```python
def create_question(
    project_root: Path,
    text: str,
    origin_skill: str,
    project_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new Question record with status "open".

    Args:
        project_root: The project's root directory.
        text: The request or sub-task text.
        origin_skill: Name of the skill that raised this Question.
        project_id: Project this Question belongs to. Defaults to the
            lazily-created "proj_default" if omitted.

    Returns:
        The full new Question record, including its generated "id".

    Raises:
        ValueError: If text is empty/missing.
        ProjectNotFoundError: If project_id is given but doesn't exist.
    """
    if not text:
        raise ValueError("text is required")
    if project_id is None:
```

(Everything after the `if project_id is None:` line is unchanged.)

- [ ] **Step 4: Add the `--create-question` CLI action to `state.py`**

In `skills/agent-state/scripts/state.py`, update the module docstring's
`Usage:` block — change:

```
    python state.py --create-project --name "..." [--description "..."] \
        [--skill NAME] [--json]

    python state.py --start-run --skill NAME [--mode MODE] \
```

to:

```
    python state.py --create-project --name "..." [--description "..."] \
        [--skill NAME] [--json]

    python state.py --create-question --question "..." [--skill NAME] \
        [--project-id PROJ_ID] [--json]

    python state.py --start-run --skill NAME [--mode MODE] \
```

Add the action flag — change:

```python
    action.add_argument("--create-project", action="store_true")
    action.add_argument("--create-hypothesis", action="store_true")
```

to:

```python
    action.add_argument("--create-project", action="store_true")
    action.add_argument("--create-question", action="store_true")
    action.add_argument("--create-hypothesis", action="store_true")
```

Add the dispatch branch — change:

```python
    if args.create_project:
        return state_store.create_project(
            project_root, args.name,
            description=args.description, created_by=args.skill or "user",
        )
    if args.create_hypothesis:
```

to:

```python
    if args.create_project:
        return state_store.create_project(
            project_root, args.name,
            description=args.description, created_by=args.skill or "user",
        )
    if args.create_question:
        return state_store.create_question(
            project_root, args.question, args.skill or "user",
            project_id=args.project_id,
        )
    if args.create_hypothesis:
```

No new argparse value flags — `--question`, `--skill`, and `--project-id`
already exist.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest skills/agent-state/scripts/tests/test_state_cli.py -v -k create_question`
Expected: PASS (6 passed).

- [ ] **Step 6: Run the full suite and commit**

Run: `pytest skills/agent-state/scripts/tests/ -v`
Expected: 93 passed (87 baseline + 6 new).

```bash
git add skills/agent-state/scripts/state_store.py skills/agent-state/scripts/state.py skills/agent-state/scripts/tests/test_state_cli.py
git commit -m "feat(agent-state): add --create-question CLI action

Registers a Question directly, without --start-run's Run side effect --
needed by research-project-init, which registers Initial Research
Questions as bookkeeping, not as an attempt to answer them."
```

---

### Task 2: `research-project-init` skill

**Files:**
- Create: `skills/research-project-init/SKILL.md`
- Create: `skills/research-project-init/references/charter_template.md`

**Interfaces:**
- Consumes: Task 1's `--create-question` CLI contract; existing
  `agent-state` actions `--create-project`, `--query --project-id`.
- Produces (used by Task 3): the skill name `research-project-init`, its
  slash command `/research-init`, and the charter file path convention
  `.research/projects/<project_id>/charter.md`.

**Interfaces:** None — documentation only, no code, no test suite (see
Global Constraints and the design spec's Testing Plan: this skill's dialogue
is validated by scenario walkthrough, the same as every other prose-driven
skill in this repo).

- [ ] **Step 1: Create `skills/research-project-init/SKILL.md`**

```markdown
---
name: research-project-init
description: Turn a preliminary research idea into a scoped, reviewable, trackable project. Runs a lightweight guided dialogue covering problem statement, scope, exclusions, expected contributions, initial research questions, constraints, resources, milestones, success criteria, stop conditions, risks, and ethics considerations -- tagging every captured item as confirmed, assumption, suggestion, or open. Writes a project charter to .research/projects/<project_id>/charter.md and registers a Project plus its initial Questions in agent-state. Does not perform literature research or run experiments -- deep-research remains the place a research question gets sharpened. Use when the user has a rough idea and wants to formalize it into a project before research begins. Trigger directly with /research-init, or natural-language phrases like "start a new research project", "formalize this idea", "define project scope", "scope out this project", "建立研究專案", "把這個構想變成正式專案", "幫我把研究範圍定義清楚".
metadata:
  data_access_level: raw
  task_type: open-ended
---

# Research Project Initialization

Turns a preliminary research idea into a project charter -- a reviewable
Markdown document with explicit scope, exclusions, contributions,
constraints, milestones, success/stop conditions, risks, and ethics -- plus
a Project record (and one Question record per Initial Research Question) in
`agent-state`.

Sits upstream of `deep-research`:

```
research-project-init -> deep-research (socratic/full) -> academic-paper -> ...
```

This skill formalizes the container. It does not investigate anything
inside it: no literature search, no FINER-scoring or sharpening of a
research question (that's `deep-research` socratic mode's job, run
afterward against the Question IDs this skill creates), no experiments. See
Non-goals below.

## When to use this vs. `deep-research` socratic mode

Use this skill when the user's concerns are project-shaped: scope,
exclusions, deliverables, timeline, resources, ethics, risk -- the boundary
and governance around one or more research questions. Use `deep-research`
socratic mode when the concern is a single research question that needs
sharpening. If the user has no research question at all yet and no
project-shaped concerns either, `deep-research` socratic mode's existing
"prefer socratic when ambiguous" default still applies -- this skill does
not change that default.

## Calling convention

```bash
STATE="$(find ~/.claude -path "*/agent-state/scripts/state.py" | head -1)"
```

All state changes go through `state.py`; this skill never edits
`.research/state/*.yaml` directly. See `skills/agent-state/SKILL.md` for
the full CLI contract. Every action below prints JSON on stdout, including
errors (`{"error": ..., "message": ...}`, exit 1) -- check `error` before
trusting any other field.

This skill assumes it runs with the working directory inside the target
project (the same assumption `agent-state` and `research-log` make) -- the
charter file is written to `.research/projects/<project_id>/charter.md`
relative to that directory.

## The guided dialogue

Work through these sections in order. For each one, ask what's needed to
fill it, then record every captured item as one bullet tagged with exactly
one of:

- `[confirmed]` -- the user stated it as fact or a firm decision.
- `[assumption]` -- taken as true without verification; flags it for
  `deep-research`/reviewers to check later.
- `[suggestion]` -- the skill proposed it and the user accepted it, rather
  than originating it.
- `[open]` -- raised but not resolved in this dialogue; carried forward as
  a known gap, never silently dropped.

1. **Problem Statement** -- what's actually being investigated and why it
   matters.
2. **Scope** -- what's in bounds.
3. **Exclusions (Out of Scope)** -- what's explicitly not covered, and why
   (a scope without exclusions usually hides an unexamined assumption --
   push on this if the user hasn't named any).
4. **Expected Contributions** -- what this project is meant to produce or
   show.
5. **Initial Research Questions** -- one or more rough questions. These are
   captured as-is, not sharpened (see Non-goals). If the user genuinely has
   none yet, record a single `[open]` item here instead of forcing a
   question into existence.
6. **Constraints** -- time, budget, data access, tooling, or other hard
   limits.
7. **Resources** -- what's available to do the work (people, compute,
   existing data, prior work).
8. **Milestones** -- rough checkpoints, even approximate ones.
9. **Success Criteria** -- what "this project worked" looks like.
10. **Stop Conditions** -- what would make continuing not worth it.
11. **Risks** -- what could go wrong, technically or otherwise.
12. **Ethics Considerations** -- human subjects, sensitive data, dual-use
    concerns, or "none identified" as an explicit `[confirmed]` item rather
    than a silently skipped section.

Ask one section at a time, not all twelve at once -- the same
one-topic-per-question discipline used elsewhere in this skill set. If the
user's answer to one section reveals something relevant to an earlier one,
go back and add it there rather than duplicating it out of order.

The dialogue itself follows the conversation's language. The charter
document it produces is always written in English, regardless of
conversation language -- generated file content in this skill set is
English by standing convention.

## Checking for an existing Project first

Before creating a new Project, check whether one already exists in this
`.research/` directory:

```bash
python "$STATE" --query --project-id proj_default --json
```

If it returns an existing Project (or the user mentions one), surface its
name and ID and confirm with the user that they intend a genuinely new
Project rather than duplicating an existing effort. This skill always
creates a new Project when it proceeds -- it never merges into or edits an
existing one (see Non-goals) -- so this check exists only to catch an
accidental duplicate before it happens, not to block or auto-merge.

## Registering in agent-state

Do this after the dialogue is complete, in this order:

```bash
# 1. Create the Project.
python "$STATE" --create-project --name "<short project name>" \
  --description "<one-paragraph problem statement>" \
  --skill research-project-init --json
# -> capture the returned "id" as PROJECT_ID

# 2. Register each Initial Research Question captured in section 5.
python "$STATE" --create-question --question "<question text>" \
  --skill research-project-init --project-id "$PROJECT_ID" --json
# -> capture the returned "id" as one of QUESTION_IDS, repeat per question
```

If section 5 recorded only a single `[open]` item (no real question yet),
skip step 2 entirely -- a Project can exist with zero Questions.

If step 1 fails, stop and report the error; do not write a charter file
with no `project_id` to reference. If step 2 fails partway through several
questions, stop and report which ones succeeded (with their IDs) and which
failed -- let the user decide whether to retry the failed ones or proceed
with a partial set, rather than silently continuing.

## Writing the charter

Use `references/charter_template.md` as the skeleton. Fill in the
frontmatter (`project_id`, `created_at`, `git_head` if the project is a git
repo, `status: initialized`, `question_ids`) and all twelve sections from
the dialogue, and save to `.research/projects/<project_id>/charter.md`.

## Reporting back

After the charter is written and registered, report to the user:

- The charter file path.
- The Project ID and name.
- The Question ID(s), if any were registered.
- A one-line suggestion to continue with `deep-research` (socratic mode if
  any Initial Research Question needs sharpening, full mode if the
  questions are already sharp enough to research directly).

## Non-goals

- **No literature research, source verification, or investigation of the
  Initial Research Questions' content.** That's `deep-research`'s job,
  unchanged.
- **No sharpening or FINER-scoring of a Research Question.** Initial
  Research Questions are recorded at face value.
- **No Hypothesis or Experiment creation.** Those levels of the chain stay
  untouched -- they get auto-filled later the normal way, via
  `--start-run --question-id ...`.
- **No editing or appending to an already-initialized Project.** Each run
  of this skill creates exactly one new Project. Revisiting an existing
  charter is future work.
- **No change to `deep-research`'s own socratic/full activation logic or
  trigger rules.**
```

- [ ] **Step 2: Create `skills/research-project-init/references/charter_template.md`**

```markdown
---
project_id: <PROJECT_ID>
created_at: "<ISO-8601 timestamp>"
git_head: <sha, omit this line if the project isn't a git repo>
status: initialized
question_ids: [<QUESTION_ID>, ...]   # empty list if section 5 had no real question yet
---

# <Project Name>

## Tag Legend

- `[confirmed]` -- stated as fact or a firm decision.
- `[assumption]` -- taken as true without verification; flagged for later checking.
- `[suggestion]` -- proposed by the skill and accepted, not originated by the user.
- `[open]` -- raised but not resolved; a known gap, not a silent omission.

## Problem Statement

- [confirmed] ...

## Scope

- [confirmed] ...

## Exclusions (Out of Scope)

- [confirmed] ...

## Expected Contributions

- [confirmed] ...

## Initial Research Questions

- [confirmed] ...

## Constraints

- [confirmed] ...

## Resources

- [confirmed] ...

## Milestones

- [confirmed] ...

## Success Criteria

- [confirmed] ...

## Stop Conditions

- [confirmed] ...

## Risks

- [confirmed] ...

## Ethics Considerations

- [confirmed] ...
```

- [ ] **Step 3: Self-check readability and consistency**

Read both files fresh and confirm: every section named in the SKILL.md's
"guided dialogue" list (12 sections) has a matching `##` heading in
`charter_template.md`, in the same order; every code block is valid
Markdown/bash (no unclosed fences); the frontmatter field names in the
`SKILL.md` "Writing the charter" section match the ones in
`charter_template.md` exactly (`project_id`, `created_at`, `git_head`,
`status`, `question_ids`). Fix any mismatch found.

- [ ] **Step 4: Commit**

```bash
git add skills/research-project-init/SKILL.md skills/research-project-init/references/charter_template.md
git commit -m "feat(research-project-init): add new skill

Guided dialogue that turns a preliminary research idea into a project
charter and registers a Project + Initial Research Questions in
agent-state. Sits upstream of deep-research; does not do research itself."
```

---

### Task 3: Wire `research-project-init` into `.claude/CLAUDE.md` routing

**Files:**
- Modify: `.claude/CLAUDE.md`

**Interfaces:**
- Consumes: Task 2's skill name `research-project-init`, slash command
  `/research-init`, and the charter path convention
  `.research/projects/<project_id>/charter.md`.
- Produces: nothing further downstream — this is the last task.

**Interfaces:** None — documentation only, no code, no test suite.

- [ ] **Step 1: Add Routing Rule 6**

In `.claude/CLAUDE.md`, under `## Routing Rules`, change:

```markdown
5. **academic-paper-reviewer guided vs full**: guided = Socratic review that engages the author in dialogue about issues. full = standard multi-perspective review report. When the user wants to learn from the review, suggest guided mode.

## Key Rules
```

to:

```markdown
5. **academic-paper-reviewer guided vs full**: guided = Socratic review that engages the author in dialogue about issues. full = standard multi-perspective review report. When the user wants to learn from the review, suggest guided mode.

6. **research-project-init vs deep-research socratic**: research-project-init = scopes a *project* (problem statement, scope, exclusions, contributions, constraints, resources, milestones, success/stop conditions, risks, ethics) and registers it in agent-state, without sharpening any research question or doing research. deep-research socratic = sharpens a *single* research question (FINER scoring, methodology blueprint) once one exists. When the user's request is about project-level scope/governance rather than one question, prefer research-project-init; when it's about clarifying one question, prefer deep-research socratic (unchanged default). Recommended flow: research-project-init → deep-research (socratic/full).

## Key Rules
```

- [ ] **Step 2: Prepend `research-project-init` to the pipeline diagram**

In `.claude/CLAUDE.md`, under `## Full Academic Pipeline`, change:

````markdown
```
deep-research (socratic/full)
  → academic-paper (plan/full)
    → integrity check (Stage 2.5)
      → academic-paper-reviewer (full/guided)
        → academic-paper (revision)
          → academic-paper-reviewer (re-review, max 2 loops)
            → final integrity check (Stage 4.5)
              → academic-paper (format-convert → final output)
                → Process Summary + AI Self-Reflection Report
```
````

to:

````markdown
```
research-project-init (optional)
  → deep-research (socratic/full)
    → academic-paper (plan/full)
      → integrity check (Stage 2.5)
        → academic-paper-reviewer (full/guided)
          → academic-paper (revision)
            → academic-paper-reviewer (re-review, max 2 loops)
              → final integrity check (Stage 4.5)
                → academic-paper (format-convert → final output)
                  → Process Summary + AI Self-Reflection Report
```
````

Every existing line gains one more level of `  ` indent, since it's now
nested one level deeper under the new first line. `(optional)` marks that
this step is skippable — a user with an already-clear research question
goes straight to `deep-research`, exactly as before this skill existed.

- [ ] **Step 3: Add a row to the Skills Overview table**

Change:

```markdown
## Skills Overview

| Skill | Description |
|-------|-------------|
| `deep-research` v2.9.4 | Research engine |
```

to:

```markdown
## Skills Overview

| Skill | Description |
|-------|-------------|
| `research-project-init` v1.0.0 | Project scoping (upstream of deep-research) |
| `deep-research` v2.9.4 | Research engine |
```

- [ ] **Step 4: Add a Handoff Protocol entry**

In `.claude/CLAUDE.md`, under `## Handoff Protocol`, change:

```markdown
## Handoff Protocol

### deep-research → academic-paper
```

to:

```markdown
## Handoff Protocol

### research-project-init → deep-research
Materials: Project ID, Initial Research Question ID(s), charter file path
(`.research/projects/<project_id>/charter.md`).

### deep-research → academic-paper
```

- [ ] **Step 5: Self-check and commit**

Read the full modified `## Routing Rules`, `## Full Academic Pipeline`,
`## Skills Overview`, and `## Handoff Protocol` sections fresh; confirm the
pipeline diagram's indentation is consistent (each `→` one space deeper
than its parent) and no existing row/rule was accidentally altered instead
of added-to.

```bash
git add .claude/CLAUDE.md
git commit -m "docs(claude-md): route research-project-init upstream of deep-research

Adds the new skill to the routing rules, pipeline diagram, skills
overview table, and handoff protocol."
```
