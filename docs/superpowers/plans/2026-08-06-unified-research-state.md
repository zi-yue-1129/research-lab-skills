# Unified Research State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `skills/agent-state` with three new canonical entities — Project,
Hypothesis, Experiment — that sit above the existing Question/Run/Result/Claim
chain, so every Run that has research context can be traced up through
`Experiment → Hypothesis → Question → Project`, with write-time referential
integrity checks and an on-demand `--validate` scan.

**Architecture:** Same three flat scripts, extended in place:
`state_store.py` gains Project/Hypothesis/Experiment CRUD, a `project_id`
field on Question, an `experiment_id` field on Run, `start_run`'s auto-fill
resolution, and `validate_referential_integrity`; `state_index.py` gains
three new tables plus the `runs.experiment_id` column (behind an
`INDEX_SCHEMA_VERSION` bump, so old `index.db` files self-heal via the
existing corruption/version-mismatch recovery path instead of hitting a
missing-column `sqlite3.OperationalError`); `state.py` gains
`--create-project`, `--create-hypothesis`, `--create-experiment`,
`--set-hypothesis-status`, `--set-experiment-status`, `--validate`, and
extends `--start-run`/`--query` with the new id filters. No new files, no
new top-level `.research/` directories.

**Tech Stack:** Same as the base skill — Python 3, PyYAML, `sqlite3`
(stdlib), `argparse` (stdlib), `pytest` + `subprocess` for tests. No new pip
dependencies.

**Design spec:** `docs/superpowers/specs/2026-08-06-unified-research-state-design.md`.

## Global Constraints

- Every function signature has type hints; every public function/class has a
  Google-style docstring — non-negotiable even where the code is
  self-explanatory (user's global code-style standard).
- No file in this plan grows past ~1000 lines. `state_store.py` is ~570
  lines and `state_index.py` is ~385 lines before this plan; the additions
  below keep both well under that ceiling.
- No silent failures: a dangling foreign key raises a named exception at
  write time; nothing defaults its way past an invalid reference. Every CLI
  error path prints valid JSON to stdout when `--json` is given and exits
  non-zero — never an uncaught traceback.
- **A Run given zero levels (`--question`/`--question-id`/`--hypothesis-id`/
  `--experiment-id` all absent) stays exactly as standalone as it is today**:
  `question_id`, `hypothesis_id`, and `experiment_id` all `null`, nothing
  auto-created. Auto-fill only triggers once a Question is resolvable (given
  directly, or implied by a `--hypothesis-id`/`--experiment-id`). Do not
  modify `test_start_run_without_question` in `test_state_cli.py` — its
  assertion that a level-less Run has `question_id: null` must keep passing
  unchanged throughout every task in this plan.
- Tests are subprocess-based against `state.py`, matching every existing
  test in `tests/test_state_cli.py` and `tests/test_state_locking.py` — no
  internal-module unit tests, no new import-path machinery.
- All code comments, docstrings, commit subjects, and log/error messages are
  in English regardless of conversation language.
- Every code snippet below is the actual content to write — no "implement
  later", no "similar to Task N" shorthand.
- Baseline before Task 1: 49 tests passing (`pytest skills/agent-state/scripts/tests/ -v`).
  Every task's final step re-runs the full suite and states the expected new
  total.

---

### Task 1: Project entity

**Files:**
- Modify: `skills/agent-state/scripts/state_store.py`
- Modify: `skills/agent-state/scripts/state.py`
- Test: `skills/agent-state/scripts/tests/test_state_cli.py`

**Interfaces:**
- Produces (used by Task 2 and later):
  - `state_store.PROJECTS_RELATIVE_PATH: Path` = `.research/state/projects.yaml`
  - `state_store.DEFAULT_PROJECT_ID: str` = `"proj_default"`
  - `state_store.load_projects(project_root: Path) -> Dict[str, Any]`
  - `state_store.create_project(project_root: Path, name: str, description: Optional[str] = None, created_by: str = "user") -> Dict[str, Any]`
  - `state_store._ensure_default_project(project_root: Path) -> str`
  - `state.py` CLI: `--create-project --name TEXT [--description TEXT] [--skill NAME] [--json]`

- [ ] **Step 1: Write the failing tests**

Append to `skills/agent-state/scripts/tests/test_state_cli.py`:

```python
def test_create_project_returns_active_project(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--create-project", "--name", "Offline Support Initiative", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["name"] == "Offline Support Initiative"
    assert data["description"] is None
    assert data["status"] == "active"
    assert data["created_by"] == "user"
    assert data["id"].startswith("proj_")


def test_create_project_with_description_and_skill(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(
        project, "--create-project", "--name", "Offline Support Initiative",
        "--description", "Investigate offline usage patterns.",
        "--skill", "deep-research", "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["description"] == "Investigate offline usage patterns."
    assert data["created_by"] == "deep-research"


def test_create_project_without_name_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--create-project", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest skills/agent-state/scripts/tests/test_state_cli.py -v -k create_project`
Expected: FAIL (`AssertionError: no action selected despite argparse required group`,
surfaced as an `AssertionError` JSON payload — `--create-project` isn't a
recognized flag yet).

- [ ] **Step 3: Implement the Project entity in `state_store.py`**

Add the constant to the existing constants block — in
`skills/agent-state/scripts/state_store.py`, change:

```python
QUESTIONS_RELATIVE_PATH = Path(".research/state/questions.yaml")
RUNS_RELATIVE_PATH = Path(".research/state/runs.yaml")
EVENTS_RELATIVE_DIR = Path(".research/events")
STATE_SCHEMA_VERSION = 1
```

to:

```python
PROJECTS_RELATIVE_PATH = Path(".research/state/projects.yaml")
QUESTIONS_RELATIVE_PATH = Path(".research/state/questions.yaml")
RUNS_RELATIVE_PATH = Path(".research/state/runs.yaml")
EVENTS_RELATIVE_DIR = Path(".research/events")
STATE_SCHEMA_VERSION = 1
DEFAULT_PROJECT_ID = "proj_default"
```

Add the new functions right after `_save_yaml_map` and before
`load_questions` (i.e. insert this block between those two, keeping
`load_questions`/`load_runs` immediately below it):

```python
def load_projects(project_root: Path) -> Dict[str, Any]:
    """Load all Project records.

    Args:
        project_root: The project's root directory.

    Returns:
        id -> Project record map (empty if none exist yet).
    """
    return _load_yaml_map(project_root / PROJECTS_RELATIVE_PATH, "projects")


def create_project(
    project_root: Path,
    name: str,
    description: Optional[str] = None,
    created_by: str = "user",
) -> Dict[str, Any]:
    """Create a new Project record with status "active".

    Args:
        project_root: The project's root directory.
        name: Human-readable Project name.
        description: Optional longer description.
        created_by: Name of the skill creating this Project, or "user" for
            a direct CLI call.

    Returns:
        The full new Project record, including its generated "id".

    Raises:
        ValueError: If name is empty/missing.
    """
    if not name:
        raise ValueError("name is required")
    path = project_root / PROJECTS_RELATIVE_PATH
    with _locked_file(project_root, path):
        projects = _load_yaml_map(path, "projects")
        project_id = generate_id("proj")
        record = {
            "id": project_id,
            "name": name,
            "description": description,
            "status": "active",
            "created_at": _utc_now_iso(),
            "created_by": created_by,
        }
        projects[project_id] = record
        _save_yaml_map(path, "projects", projects)
    return record


def _ensure_default_project(project_root: Path) -> str:
    """Return "proj_default", creating it if it doesn't exist yet.

    Args:
        project_root: The project's root directory.

    Returns:
        The literal string "proj_default".
    """
    path = project_root / PROJECTS_RELATIVE_PATH
    with _locked_file(project_root, path):
        projects = _load_yaml_map(path, "projects")
        if DEFAULT_PROJECT_ID not in projects:
            now = _utc_now_iso()
            projects[DEFAULT_PROJECT_ID] = {
                "id": DEFAULT_PROJECT_ID,
                "name": "Default Project",
                "description": None,
                "status": "active",
                "created_at": now,
                "created_by": "user",
            }
            _save_yaml_map(path, "projects", projects)
    return DEFAULT_PROJECT_ID
```

- [ ] **Step 4: Wire `--create-project` in `state.py`**

In `skills/agent-state/scripts/state.py`'s `_build_parser`, add the action
flag next to the other `action.add_argument` calls (after `--report`):

```python
    action.add_argument("--create-project", action="store_true")
```

Add the two new value flags next to `--question`/`--question-id`:

```python
    parser.add_argument("--name", metavar="TEXT")
    parser.add_argument("--description", metavar="TEXT")
```

In `_dispatch`, add a branch before the final `raise AssertionError` line:

```python
    if args.create_project:
        return state_store.create_project(
            project_root, args.name,
            description=args.description, created_by=args.skill or "user",
        )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest skills/agent-state/scripts/tests/test_state_cli.py -v`
Expected: PASS (49 tests total: 46 baseline in this file + 3 new). This
command only runs `test_state_cli.py`; the repo-wide baseline of 49 in
Global Constraints includes `test_state_locking.py`'s 3 tests too, which
this command doesn't touch.

- [ ] **Step 6: Commit**

```bash
git add skills/agent-state/scripts/state_store.py \
        skills/agent-state/scripts/state.py \
        skills/agent-state/scripts/tests/test_state_cli.py
git commit -m "feat(agent-state): add Project entity and --create-project"
```

---

### Task 2: Question gains `project_id`

**Files:**
- Modify: `skills/agent-state/scripts/state_store.py`
- Test: `skills/agent-state/scripts/tests/test_state_cli.py`

**Interfaces:**
- Consumes: `state_store.load_projects`, `state_store._ensure_default_project`,
  `state_store.DEFAULT_PROJECT_ID` (Task 1).
- Produces (used by Task 3 and later):
  - `state_store.ProjectNotFoundError(ValueError)`
  - `state_store.create_question(project_root: Path, text: str, origin_skill: str, project_id: Optional[str] = None) -> Dict[str, Any]`
    now returns a record with a `"project_id"` key.

- [ ] **Step 1: Write the failing tests**

Append to `skills/agent-state/scripts/tests/test_state_cli.py`:

```python
def test_start_run_with_question_defaults_to_default_project(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    _run(project, "--start-run", "--skill", "research-mode", "--question", "Q?", "--json")

    questions_yaml = (project / ".research" / "state" / "questions.yaml").read_text()
    assert "project_id: proj_default" in questions_yaml
    projects_yaml = (project / ".research" / "state" / "projects.yaml").read_text()
    assert "proj_default" in projects_yaml
    assert "Default Project" in projects_yaml


def test_default_project_is_created_lazily_only_once(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    _run(project, "--start-run", "--skill", "research-mode", "--question", "Q1?", "--json")
    _run(project, "--start-run", "--skill", "research-mode", "--question", "Q2?", "--json")

    doc = yaml.safe_load((project / ".research" / "state" / "projects.yaml").read_text())
    assert list(doc["projects"].keys()) == ["proj_default"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest skills/agent-state/scripts/tests/test_state_cli.py -v -k default_project`
Expected: FAIL (`AssertionError: assert 'project_id: proj_default' in ...`
— `questions.yaml` has no `project_id` field yet).

- [ ] **Step 3: Add `ProjectNotFoundError` and update `create_question`**

In `skills/agent-state/scripts/state_store.py`, add the new exception class
right after `QuestionNotFoundError`:

```python
class ProjectNotFoundError(ValueError):
    """Raised when a project_id does not exist in state/projects.yaml."""
```

Replace `create_question` in full:

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
        project_id = _ensure_default_project(project_root)
    elif project_id not in load_projects(project_root):
        raise ProjectNotFoundError(f"Unknown project_id: {project_id}")
    path = project_root / QUESTIONS_RELATIVE_PATH
    with _locked_file(project_root, path):
        questions = _load_yaml_map(path, "questions")
        question_id = generate_id("q")
        now = _utc_now_iso()
        record = {
            "id": question_id,
            "text": text,
            "origin_skill": origin_skill,
            "project_id": project_id,
            "status": "open",
            "created_at": now,
            "updated_at": now,
        }
        questions[question_id] = record
        _save_yaml_map(path, "questions", questions)
    return record
```

- [ ] **Step 4: Register `ProjectNotFoundError` as a caught CLI error**

In `skills/agent-state/scripts/state.py`'s `main`, both `except` tuples
currently read:

```python
    except (
        state_store.ProjectRootNotFoundError,
        state_store.StateParseError,
        state_store.QuestionNotFoundError,
        state_store.RunNotFoundError,
        state_store.LockTimeoutError,
        ValueError,
    ) as exc:
```

`state_store.ProjectNotFoundError` already subclasses `ValueError`, which is
already in this tuple — no edit needed here. (This step is a checkpoint, not
a code change: confirm the tuple still catches it via the `ValueError`
branch before moving on.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest skills/agent-state/scripts/tests/test_state_cli.py -v`
Expected: PASS (51 tests total: 49 + 2 new).

- [ ] **Step 6: Commit**

```bash
git add skills/agent-state/scripts/state_store.py \
        skills/agent-state/scripts/tests/test_state_cli.py
git commit -m "feat(agent-state): give Question a project_id, defaulting to proj_default"
```

---

### Task 3: Hypothesis entity

**Files:**
- Modify: `skills/agent-state/scripts/state_store.py`
- Modify: `skills/agent-state/scripts/state.py`
- Test: `skills/agent-state/scripts/tests/test_state_cli.py`

**Interfaces:**
- Consumes: `state_store.load_questions`, `state_store.QuestionNotFoundError`
  (existing).
- Produces (used by Task 4 and later):
  - `state_store.HYPOTHESES_RELATIVE_PATH: Path` = `.research/state/hypotheses.yaml`
  - `state_store.HypothesisNotFoundError(ValueError)`
  - `state_store.load_hypotheses(project_root: Path) -> Dict[str, Any]`
  - `state_store.create_hypothesis(project_root: Path, question_id: str, statement: str, created_by: str = "user", synthetic: bool = False) -> Dict[str, Any]`
  - `state_store.set_hypothesis_status(project_root: Path, hypothesis_id: str, status: str) -> Dict[str, Any]`
  - `state.py` CLI: `--create-hypothesis --question-id ID --statement TEXT [--skill NAME] [--json]`,
    `--set-hypothesis-status --hypothesis-id ID --status supported|refuted|inconclusive [--json]`

- [ ] **Step 1: Write the failing tests**

Append to `skills/agent-state/scripts/tests/test_state_cli.py`:

```python
def _create_question_id(project: Path, text: str = "Needs offline support?") -> str:
    result = _run(
        project, "--start-run", "--skill", "research-mode", "--question", text, "--json"
    )
    return json.loads(result.stdout)["question_id"]


def test_create_hypothesis_returns_proposed_hypothesis(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    question_id = _create_question_id(project)

    result = _run(
        project, "--create-hypothesis", "--question-id", question_id,
        "--statement", "Offline support is unnecessary.",
        "--skill", "deep-research", "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["question_id"] == question_id
    assert data["statement"] == "Offline support is unnecessary."
    assert data["status"] == "proposed"
    assert data["synthetic"] is False
    assert data["created_by"] == "deep-research"
    assert data["id"].startswith("hyp_")


def test_create_hypothesis_without_statement_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    question_id = _create_question_id(project)

    result = _run(project, "--create-hypothesis", "--question-id", question_id, "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"


def test_create_hypothesis_unknown_question_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(
        project, "--create-hypothesis", "--question-id", "q_missing",
        "--statement", "x", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "QuestionNotFoundError"


def test_set_hypothesis_status_updates_status(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    question_id = _create_question_id(project)
    hypothesis_id = json.loads(
        _run(
            project, "--create-hypothesis", "--question-id", question_id,
            "--statement", "x", "--json",
        ).stdout
    )["id"]

    result = _run(
        project, "--set-hypothesis-status", "--hypothesis-id", hypothesis_id,
        "--status", "supported", "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["status"] == "supported"


def test_set_hypothesis_status_unknown_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(
        project, "--set-hypothesis-status", "--hypothesis-id", "hyp_missing",
        "--status", "refuted", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "HypothesisNotFoundError"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest skills/agent-state/scripts/tests/test_state_cli.py -v -k hypothesis`
Expected: FAIL (`--create-hypothesis`/`--set-hypothesis-status` aren't
recognized flags yet).

- [ ] **Step 3: Implement the Hypothesis entity in `state_store.py`**

Add the exception right after `ProjectNotFoundError`:

```python
class HypothesisNotFoundError(ValueError):
    """Raised when a hypothesis_id does not exist in state/hypotheses.yaml."""
```

Add the constant and status set next to the existing status-set constants —
change:

```python
_CLOSING_RUN_STATUSES = frozenset({"completed", "failed"})
_QUESTION_STATUSES = frozenset({"answered", "abandoned"})
```

to:

```python
_CLOSING_RUN_STATUSES = frozenset({"completed", "failed"})
_QUESTION_STATUSES = frozenset({"answered", "abandoned"})
_HYPOTHESIS_STATUSES = frozenset({"supported", "refuted", "inconclusive"})
```

Add `HYPOTHESES_RELATIVE_PATH` to the constants block, next to
`PROJECTS_RELATIVE_PATH`:

```python
HYPOTHESES_RELATIVE_PATH = Path(".research/state/hypotheses.yaml")
```

Add the new functions right after `set_question_status` and before
`start_run`:

```python
def load_hypotheses(project_root: Path) -> Dict[str, Any]:
    """Load all Hypothesis records.

    Args:
        project_root: The project's root directory.

    Returns:
        id -> Hypothesis record map (empty if none exist yet).
    """
    return _load_yaml_map(project_root / HYPOTHESES_RELATIVE_PATH, "hypotheses")


def create_hypothesis(
    project_root: Path,
    question_id: str,
    statement: str,
    created_by: str = "user",
    synthetic: bool = False,
) -> Dict[str, Any]:
    """Create a new Hypothesis record with status "proposed".

    Args:
        project_root: The project's root directory.
        question_id: The Question this Hypothesis proposes to answer; must
            already exist.
        statement: The hypothesis text.
        created_by: Name of the skill creating this Hypothesis, or "user"
            for a direct CLI call.
        synthetic: True if this record was auto-created by start_run's
            chain-completion logic rather than deliberately declared.

    Returns:
        The full new Hypothesis record, including its generated "id".

    Raises:
        QuestionNotFoundError: If question_id doesn't exist.
        ValueError: If statement is empty/missing.
    """
    if not statement:
        raise ValueError("statement is required")
    if question_id not in load_questions(project_root):
        raise QuestionNotFoundError(f"Unknown question_id: {question_id}")
    path = project_root / HYPOTHESES_RELATIVE_PATH
    with _locked_file(project_root, path):
        hypotheses = _load_yaml_map(path, "hypotheses")
        hypothesis_id = generate_id("hyp")
        record = {
            "id": hypothesis_id,
            "question_id": question_id,
            "statement": statement,
            "status": "proposed",
            "synthetic": synthetic,
            "created_at": _utc_now_iso(),
            "created_by": created_by,
        }
        hypotheses[hypothesis_id] = record
        _save_yaml_map(path, "hypotheses", hypotheses)
    return record


def set_hypothesis_status(project_root: Path, hypothesis_id: str, status: str) -> Dict[str, Any]:
    """Transition a Hypothesis's verdict status.

    Args:
        project_root: The project's root directory.
        hypothesis_id: The Hypothesis to update.
        status: New status, must be "supported", "refuted", or "inconclusive".

    Returns:
        The updated Hypothesis record.

    Raises:
        HypothesisNotFoundError: If hypothesis_id doesn't exist.
        ValueError: If status isn't one of the allowed values.
    """
    if status not in _HYPOTHESIS_STATUSES:
        raise ValueError(
            f"status must be 'supported', 'refuted', or 'inconclusive', got {status!r}"
        )
    path = project_root / HYPOTHESES_RELATIVE_PATH
    with _locked_file(project_root, path):
        hypotheses = _load_yaml_map(path, "hypotheses")
        if hypothesis_id not in hypotheses:
            raise HypothesisNotFoundError(f"Unknown hypothesis_id: {hypothesis_id}")
        hypotheses[hypothesis_id]["status"] = status
        _save_yaml_map(path, "hypotheses", hypotheses)
        return hypotheses[hypothesis_id]
```

- [ ] **Step 4: Wire the two new actions in `state.py`**

In `_build_parser`, add two action flags after `--create-project`:

```python
    action.add_argument("--create-hypothesis", action="store_true")
    action.add_argument("--set-hypothesis-status", action="store_true")
```

Add the new value flag next to `--run-id`:

```python
    parser.add_argument("--hypothesis-id", metavar="ID")
```

`--statement` doesn't need any change — it already exists and is reused
as-is for the hypothesis statement text. `--status`'s choices do need
widening — change:

```python
    parser.add_argument("--status", choices=["completed", "failed"])
```

to:

```python
    parser.add_argument(
        "--status",
        choices=["completed", "failed", "running", "supported", "refuted", "inconclusive"],
    )
```

(Each store function still enforces its own narrower allowed set — this
widened list only lets argparse accept the union up front; `complete_run`
still rejects `"supported"` the same way it already rejects any value
outside `_CLOSING_RUN_STATUSES`.)

In `_dispatch`, add two branches before the final `raise AssertionError`:

```python
    if args.create_hypothesis:
        return state_store.create_hypothesis(
            project_root, args.question_id, args.statement,
            created_by=args.skill or "user",
        )
    if args.set_hypothesis_status:
        return state_store.set_hypothesis_status(
            project_root, args.hypothesis_id, args.status
        )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest skills/agent-state/scripts/tests/test_state_cli.py -v`
Expected: PASS (57 tests total: 51 + 6 new).

- [ ] **Step 6: Commit**

```bash
git add skills/agent-state/scripts/state_store.py \
        skills/agent-state/scripts/state.py \
        skills/agent-state/scripts/tests/test_state_cli.py
git commit -m "feat(agent-state): add Hypothesis entity"
```

---

### Task 4: Experiment entity

**Files:**
- Modify: `skills/agent-state/scripts/state_store.py`
- Modify: `skills/agent-state/scripts/state.py`
- Test: `skills/agent-state/scripts/tests/test_state_cli.py`

**Interfaces:**
- Consumes: `state_store.load_hypotheses`, `state_store.HypothesisNotFoundError`
  (Task 3).
- Produces (used by Task 5 and later):
  - `state_store.EXPERIMENTS_RELATIVE_PATH: Path` = `.research/state/experiments.yaml`
  - `state_store.ExperimentNotFoundError(ValueError)`
  - `state_store.load_experiments(project_root: Path) -> Dict[str, Any]`
  - `state_store.create_experiment(project_root: Path, hypothesis_id: str, description: str, created_by: str = "user", synthetic: bool = False) -> Dict[str, Any]`
  - `state_store.set_experiment_status(project_root: Path, experiment_id: str, status: str) -> Dict[str, Any]`
  - `state.py` CLI: `--create-experiment --hypothesis-id ID --description TEXT [--skill NAME] [--json]`,
    `--set-experiment-status --experiment-id ID --status running|completed|failed [--json]`

This mirrors Task 3's shape exactly, one level down the chain.

- [ ] **Step 1: Write the failing tests**

Append to `skills/agent-state/scripts/tests/test_state_cli.py`:

```python
def _create_hypothesis_id(project: Path, question_id: str, statement: str = "H1") -> str:
    result = _run(
        project, "--create-hypothesis", "--question-id", question_id,
        "--statement", statement, "--json",
    )
    return json.loads(result.stdout)["id"]


def test_create_experiment_returns_planned_experiment(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    question_id = _create_question_id(project)
    hypothesis_id = _create_hypothesis_id(project, question_id)

    result = _run(
        project, "--create-experiment", "--hypothesis-id", hypothesis_id,
        "--description", "Survey production traffic logs.",
        "--skill", "deep-research", "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["hypothesis_id"] == hypothesis_id
    assert data["description"] == "Survey production traffic logs."
    assert data["status"] == "planned"
    assert data["synthetic"] is False
    assert data["created_by"] == "deep-research"
    assert data["id"].startswith("exp_")


def test_create_experiment_without_description_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    question_id = _create_question_id(project)
    hypothesis_id = _create_hypothesis_id(project, question_id)

    result = _run(project, "--create-experiment", "--hypothesis-id", hypothesis_id, "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"


def test_create_experiment_unknown_hypothesis_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(
        project, "--create-experiment", "--hypothesis-id", "hyp_missing",
        "--description", "x", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "HypothesisNotFoundError"


def test_set_experiment_status_updates_status(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    question_id = _create_question_id(project)
    hypothesis_id = _create_hypothesis_id(project, question_id)
    experiment_id = json.loads(
        _run(
            project, "--create-experiment", "--hypothesis-id", hypothesis_id,
            "--description", "x", "--json",
        ).stdout
    )["id"]

    result = _run(
        project, "--set-experiment-status", "--experiment-id", experiment_id,
        "--status", "running", "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["status"] == "running"


def test_set_experiment_status_unknown_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(
        project, "--set-experiment-status", "--experiment-id", "exp_missing",
        "--status", "completed", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ExperimentNotFoundError"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest skills/agent-state/scripts/tests/test_state_cli.py -v -k experiment`
Expected: FAIL (`--create-experiment`/`--set-experiment-status` aren't
recognized flags yet).

- [ ] **Step 3: Implement the Experiment entity in `state_store.py`**

Add the exception right after `HypothesisNotFoundError`:

```python
class ExperimentNotFoundError(ValueError):
    """Raised when an experiment_id does not exist in state/experiments.yaml."""
```

Add the status set next to `_HYPOTHESIS_STATUSES`:

```python
_EXPERIMENT_STATUSES = frozenset({"running", "completed", "failed"})
```

Add `EXPERIMENTS_RELATIVE_PATH` to the constants block, next to
`HYPOTHESES_RELATIVE_PATH`:

```python
EXPERIMENTS_RELATIVE_PATH = Path(".research/state/experiments.yaml")
```

Add the new functions right after `set_hypothesis_status` and before
`start_run`:

```python
def load_experiments(project_root: Path) -> Dict[str, Any]:
    """Load all Experiment records.

    Args:
        project_root: The project's root directory.

    Returns:
        id -> Experiment record map (empty if none exist yet).
    """
    return _load_yaml_map(project_root / EXPERIMENTS_RELATIVE_PATH, "experiments")


def create_experiment(
    project_root: Path,
    hypothesis_id: str,
    description: str,
    created_by: str = "user",
    synthetic: bool = False,
) -> Dict[str, Any]:
    """Create a new Experiment record with status "planned".

    Args:
        project_root: The project's root directory.
        hypothesis_id: The Hypothesis this Experiment tests; must already
            exist.
        description: What the experiment does.
        created_by: Name of the skill creating this Experiment, or "user"
            for a direct CLI call.
        synthetic: True if this record was auto-created by start_run's
            chain-completion logic rather than deliberately declared.

    Returns:
        The full new Experiment record, including its generated "id".

    Raises:
        HypothesisNotFoundError: If hypothesis_id doesn't exist.
        ValueError: If description is empty/missing.
    """
    if not description:
        raise ValueError("description is required")
    if hypothesis_id not in load_hypotheses(project_root):
        raise HypothesisNotFoundError(f"Unknown hypothesis_id: {hypothesis_id}")
    path = project_root / EXPERIMENTS_RELATIVE_PATH
    with _locked_file(project_root, path):
        experiments = _load_yaml_map(path, "experiments")
        experiment_id = generate_id("exp")
        record = {
            "id": experiment_id,
            "hypothesis_id": hypothesis_id,
            "description": description,
            "status": "planned",
            "synthetic": synthetic,
            "created_at": _utc_now_iso(),
            "created_by": created_by,
        }
        experiments[experiment_id] = record
        _save_yaml_map(path, "experiments", experiments)
    return record


def set_experiment_status(project_root: Path, experiment_id: str, status: str) -> Dict[str, Any]:
    """Transition an Experiment's status.

    Args:
        project_root: The project's root directory.
        experiment_id: The Experiment to update.
        status: New status, must be "running", "completed", or "failed".

    Returns:
        The updated Experiment record.

    Raises:
        ExperimentNotFoundError: If experiment_id doesn't exist.
        ValueError: If status isn't one of the allowed values.
    """
    if status not in _EXPERIMENT_STATUSES:
        raise ValueError(
            f"status must be 'running', 'completed', or 'failed', got {status!r}"
        )
    path = project_root / EXPERIMENTS_RELATIVE_PATH
    with _locked_file(project_root, path):
        experiments = _load_yaml_map(path, "experiments")
        if experiment_id not in experiments:
            raise ExperimentNotFoundError(f"Unknown experiment_id: {experiment_id}")
        experiments[experiment_id]["status"] = status
        _save_yaml_map(path, "experiments", experiments)
        return experiments[experiment_id]
```

- [ ] **Step 4: Wire the two new actions in `state.py`**

In `_build_parser`, add two action flags after `--set-hypothesis-status`:

```python
    action.add_argument("--create-experiment", action="store_true")
    action.add_argument("--set-experiment-status", action="store_true")
```

Add the new value flag next to `--hypothesis-id`:

```python
    parser.add_argument("--experiment-id", metavar="ID")
```

`--description` was already added in Task 1 for `--create-project` — reused
as-is for the experiment description text.

In `_dispatch`, add two branches before the final `raise AssertionError`:

```python
    if args.create_experiment:
        return state_store.create_experiment(
            project_root, args.hypothesis_id, args.description,
            created_by=args.skill or "user",
        )
    if args.set_experiment_status:
        return state_store.set_experiment_status(
            project_root, args.experiment_id, args.status
        )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest skills/agent-state/scripts/tests/test_state_cli.py -v`
Expected: PASS (63 tests total: 57 + 6 new).

- [ ] **Step 6: Commit**

```bash
git add skills/agent-state/scripts/state_store.py \
        skills/agent-state/scripts/state.py \
        skills/agent-state/scripts/tests/test_state_cli.py
git commit -m "feat(agent-state): add Experiment entity"
```

---

### Task 5: Run gains `experiment_id` and `--start-run` auto-fill

**Files:**
- Modify: `skills/agent-state/scripts/state_store.py`
- Modify: `skills/agent-state/scripts/state.py`
- Test: `skills/agent-state/scripts/tests/test_state_cli.py`

**Interfaces:**
- Consumes: `state_store.load_experiments`, `state_store.load_hypotheses`,
  `state_store.create_hypothesis`, `state_store.create_experiment`,
  `state_store.ExperimentNotFoundError`, `state_store.HypothesisNotFoundError`
  (Tasks 3-4).
- Produces (used by Task 6):
  - `state_store._question_id_for_experiment(project_root: Path, experiment_id: str) -> str`
  - `state_store.start_run(...)` extended with `hypothesis_id` and
    `experiment_id` parameters; every Run record now also has an
    `"experiment_id"` key.
  - `state.py` CLI: `--start-run` accepts `--hypothesis-id`/`--experiment-id`
    in addition to `--question`/`--question-id`.

This is the task that implements the four-branch resolution algorithm from
the design spec's "`--start-run` (extended resolution)" section. **Branch 4
(nothing given at all) must stay byte-for-byte the same as today** — see
Global Constraints.

- [ ] **Step 1: Write the failing tests**

Append to `skills/agent-state/scripts/tests/test_state_cli.py`:

```python
def test_start_run_without_any_level_stays_fully_standalone(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--start-run", "--skill", "deep-research", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["question_id"] is None
    assert data["experiment_id"] is None
    assert not (project / ".research" / "state" / "hypotheses.yaml").exists()
    assert not (project / ".research" / "state" / "experiments.yaml").exists()


def test_start_run_with_question_creates_synthetic_hypothesis_and_experiment(
    tmp_path: Path,
) -> None:
    project = _make_project(tmp_path)

    result = _run(
        project, "--start-run", "--skill", "deep-research",
        "--question", "Does this need offline support?", "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["question_id"].startswith("q_")
    assert data["experiment_id"].startswith("exp_")

    hyp_doc = yaml.safe_load(
        (project / ".research" / "state" / "hypotheses.yaml").read_text()
    )
    assert len(hyp_doc["hypotheses"]) == 1
    hypothesis = next(iter(hyp_doc["hypotheses"].values()))
    assert hypothesis["question_id"] == data["question_id"]
    assert hypothesis["synthetic"] is True

    exp_doc = yaml.safe_load(
        (project / ".research" / "state" / "experiments.yaml").read_text()
    )
    experiment = exp_doc["experiments"][data["experiment_id"]]
    assert experiment["hypothesis_id"] == hypothesis["id"]
    assert experiment["synthetic"] is True


def test_start_run_with_hypothesis_id_creates_synthetic_experiment(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    question_id = _create_question_id(project)
    hypothesis_id = _create_hypothesis_id(project, question_id)

    result = _run(
        project, "--start-run", "--skill", "deep-research",
        "--hypothesis-id", hypothesis_id, "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["experiment_id"].startswith("exp_")
    assert data["question_id"] == question_id

    exp_doc = yaml.safe_load(
        (project / ".research" / "state" / "experiments.yaml").read_text()
    )
    experiment = exp_doc["experiments"][data["experiment_id"]]
    assert experiment["hypothesis_id"] == hypothesis_id
    assert experiment["synthetic"] is True


def test_start_run_with_unknown_hypothesis_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(
        project, "--start-run", "--skill", "deep-research",
        "--hypothesis-id", "hyp_missing", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "HypothesisNotFoundError"


def test_start_run_with_experiment_id_links_directly(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    question_id = _create_question_id(project)
    hypothesis_id = _create_hypothesis_id(project, question_id)
    experiment_id = json.loads(
        _run(
            project, "--create-experiment", "--hypothesis-id", hypothesis_id,
            "--description", "E1", "--json",
        ).stdout
    )["id"]

    result = _run(
        project, "--start-run", "--skill", "deep-research",
        "--experiment-id", experiment_id, "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["experiment_id"] == experiment_id
    assert data["question_id"] == question_id

    exp_doc = yaml.safe_load(
        (project / ".research" / "state" / "experiments.yaml").read_text()
    )
    assert len(exp_doc["experiments"]) == 1  # no extra synthetic experiment created


def test_start_run_with_unknown_experiment_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(
        project, "--start-run", "--skill", "deep-research",
        "--experiment-id", "exp_missing", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ExperimentNotFoundError"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest skills/agent-state/scripts/tests/test_state_cli.py -v -k start_run`
Expected: FAIL — `--start-run` doesn't accept `--hypothesis-id`/
`--experiment-id` yet (`error: unrecognized arguments`, exit code 2), and
`test_start_run_without_any_level_stays_fully_standalone`'s
`data["experiment_id"] is None` assertion fails with a `KeyError`-shaped
mismatch since the field doesn't exist on Run records yet.

- [ ] **Step 3: Implement chain resolution in `state_store.py`**

Add the helper right before `start_run`:

```python
def _question_id_for_experiment(project_root: Path, experiment_id: str) -> str:
    """Walk experiment_id -> hypothesis_id -> question_id to find the owning Question.

    Args:
        project_root: The project's root directory.
        experiment_id: An Experiment id already known to exist.

    Returns:
        The question_id of the Hypothesis the Experiment belongs to.
    """
    experiments = load_experiments(project_root)
    hypothesis_id = experiments[experiment_id]["hypothesis_id"]
    hypotheses = load_hypotheses(project_root)
    return hypotheses[hypothesis_id]["question_id"]
```

Replace `start_run` in full:

```python
def start_run(
    project_root: Path,
    skill: str,
    mode: Optional[str] = None,
    question_id: Optional[str] = None,
    question_text: Optional[str] = None,
    hypothesis_id: Optional[str] = None,
    experiment_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Start a new Run, auto-completing its research chain as needed.

    Resolution, most specific first:
      1. experiment_id given -- validated to exist, used directly.
      2. hypothesis_id given (no experiment_id) -- validated to exist, a
         synthetic Experiment is created under it.
      3. question_id or question_text given (no hypothesis_id/experiment_id)
         -- resolved exactly as before, then a synthetic Hypothesis and a
         synthetic Experiment are created under it.
      4. Nothing given at all -- unchanged standalone behavior: question_id,
         hypothesis_id, and experiment_id are all left None. No Question,
         Hypothesis, or Experiment is created.

    Args:
        project_root: The project's root directory.
        skill: Name of the skill executing this Run.
        mode: Optional mode name within that skill.
        question_id: Link to an existing Question. Mutually exclusive with
            question_text.
        question_text: Create a new Question (status "open") and link this
            Run to it. Mutually exclusive with question_id.
        hypothesis_id: Link to an existing Hypothesis; a synthetic
            Experiment is created under it.
        experiment_id: Link directly to an existing Experiment.

    Returns:
        The full new Run record, including its generated "id". Its
        "question_id" is always derived by walking "experiment_id"'s chain
        when an experiment is involved, rather than taken from the
        question_id/question_text arguments directly.

    Raises:
        QuestionNotFoundError: If question_id is given but doesn't exist.
        HypothesisNotFoundError: If hypothesis_id is given but doesn't exist.
        ExperimentNotFoundError: If experiment_id is given but doesn't exist.
        ValueError: If skill is empty/missing, or if both question_id and
            question_text are given.
    """
    if not skill:
        raise ValueError("skill is required")
    if question_id and question_text:
        raise ValueError("question_id and question_text are mutually exclusive")

    if experiment_id:
        if experiment_id not in load_experiments(project_root):
            raise ExperimentNotFoundError(f"Unknown experiment_id: {experiment_id}")
    elif hypothesis_id:
        if hypothesis_id not in load_hypotheses(project_root):
            raise HypothesisNotFoundError(f"Unknown hypothesis_id: {hypothesis_id}")
        experiment = create_experiment(
            project_root, hypothesis_id,
            description=f"Auto-created for run started by {skill}",
            created_by=skill, synthetic=True,
        )
        experiment_id = experiment["id"]
    elif question_id or question_text:
        if question_text:
            question = create_question(project_root, question_text, origin_skill=skill)
            question_id = question["id"]
        elif question_id not in load_questions(project_root):
            raise QuestionNotFoundError(f"Unknown question_id: {question_id}")
        hypothesis = create_hypothesis(
            project_root, question_id,
            statement=f"Auto-created for run started by {skill}",
            created_by=skill, synthetic=True,
        )
        experiment = create_experiment(
            project_root, hypothesis["id"],
            description=f"Auto-created for run started by {skill}",
            created_by=skill, synthetic=True,
        )
        experiment_id = experiment["id"]

    resolved_question_id = (
        _question_id_for_experiment(project_root, experiment_id) if experiment_id else None
    )

    path = project_root / RUNS_RELATIVE_PATH
    with _locked_file(project_root, path):
        runs = _load_yaml_map(path, "runs")
        run_id = generate_id("run")
        record = {
            "id": run_id,
            "skill": skill,
            "mode": mode,
            "question_id": resolved_question_id,
            "experiment_id": experiment_id,
            "status": "running",
            "started_at": _utc_now_iso(),
            "ended_at": None,
        }
        runs[run_id] = record
        _save_yaml_map(path, "runs", runs)
    return record
```

- [ ] **Step 4: Extend `--start-run` in `state.py`**

In `_dispatch`, replace the `args.start_run` branch:

```python
    if args.start_run:
        return state_store.start_run(
            project_root, args.skill, mode=args.mode,
            question_id=args.question_id, question_text=args.question,
        )
```

with:

```python
    if args.start_run:
        return state_store.start_run(
            project_root, args.skill, mode=args.mode,
            question_id=args.question_id, question_text=args.question,
            hypothesis_id=args.hypothesis_id, experiment_id=args.experiment_id,
        )
```

(`--hypothesis-id`/`--experiment-id` were already added as CLI flags in
Tasks 3-4 — this only wires them into `--start-run`'s call.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest skills/agent-state/scripts/tests/test_state_cli.py -v`
Expected: PASS (69 tests total: 63 + 6 new). Also confirm
`test_start_run_without_question` (the pre-existing test) still passes
unchanged: `pytest skills/agent-state/scripts/tests/test_state_cli.py -v -k test_start_run_without_question`.

- [ ] **Step 6: Run the full suite including locking tests**

Run: `pytest skills/agent-state/scripts/tests/ -v`
Expected: PASS (72 tests total: 69 in `test_state_cli.py` + 3 in
`test_state_locking.py`, unaffected since this task didn't change
`_locked_file` or its call sites' locking behavior).

- [ ] **Step 7: Commit**

```bash
git add skills/agent-state/scripts/state_store.py \
        skills/agent-state/scripts/state.py \
        skills/agent-state/scripts/tests/test_state_cli.py
git commit -m "feat(agent-state): give Run an experiment_id and auto-fill its chain"
```

---

### Task 6: Index projects/hypotheses/experiments, extend `--query`

**Files:**
- Modify: `skills/agent-state/scripts/state_index.py`
- Modify: `skills/agent-state/scripts/state.py`
- Test: `skills/agent-state/scripts/tests/test_state_cli.py`

**Interfaces:**
- Consumes: `state_store.PROJECTS_RELATIVE_PATH`,
  `state_store.HYPOTHESES_RELATIVE_PATH`, `state_store.EXPERIMENTS_RELATIVE_PATH`,
  `state_store.DEFAULT_PROJECT_ID` (Tasks 1, 3, 4).
- Produces:
  - `state_index.INDEX_SCHEMA_VERSION` bumped from `1` to `2`.
  - `state_index.query(...)` gains `project_id`, `hypothesis_id`,
    `experiment_id` keyword filters.
  - `state.py` CLI: `--query` accepts `--project-id`/`--hypothesis-id`/
    `--experiment-id` in addition to its existing filters.

Bumping `INDEX_SCHEMA_VERSION` matters here specifically because
`CREATE TABLE IF NOT EXISTS runs (...)` does **not** alter an
already-existing `runs` table — an `index.db` built before this task has no
`experiment_id` column, and inserting into it by name would fail. The
version bump makes `_connect`'s existing mismatch-recovery path (already
built in the schema-versioning work) wipe and rebuild any old `index.db`
automatically, the same way a corrupted one is handled — no separate
migration code needed.

- [ ] **Step 1: Write the failing tests**

Append to `skills/agent-state/scripts/tests/test_state_cli.py`:

```python
def test_query_by_project_id_returns_project_and_questions(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    started = json.loads(
        _run(project, "--start-run", "--skill", "research-mode", "--question", "Q?", "--json").stdout
    )

    result = _run(project, "--query", "--project-id", "proj_default", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["projects"][0]["id"] == "proj_default"
    assert data["questions"][0]["id"] == started["question_id"]


def test_query_by_hypothesis_id_returns_hypothesis_and_experiments(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    question_id = _create_question_id(project)
    hypothesis_id = _create_hypothesis_id(project, question_id)
    experiment_id = json.loads(
        _run(
            project, "--create-experiment", "--hypothesis-id", hypothesis_id,
            "--description", "E1", "--json",
        ).stdout
    )["id"]

    result = _run(project, "--query", "--hypothesis-id", hypothesis_id, "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["hypotheses"][0]["id"] == hypothesis_id
    assert data["experiments"][0]["id"] == experiment_id


def test_query_by_experiment_id_returns_experiment_and_runs(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    question_id = _create_question_id(project)
    hypothesis_id = _create_hypothesis_id(project, question_id)
    started = json.loads(
        _run(
            project, "--start-run", "--skill", "deep-research",
            "--hypothesis-id", hypothesis_id, "--json",
        ).stdout
    )

    result = _run(project, "--query", "--experiment-id", started["experiment_id"], "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["experiments"][0]["id"] == started["experiment_id"]
    assert data["runs"][0]["id"] == started["id"]


def test_query_requires_exactly_one_filter_still_rejects_zero_and_many(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    zero = _run(project, "--query", "--json")
    many = _run(
        project, "--query", "--project-id", "proj_default",
        "--hypothesis-id", "hyp_x", "--json",
    )

    assert zero.returncode == 1
    assert json.loads(zero.stdout)["error"] == "ValueError"
    assert many.returncode == 1
    assert json.loads(many.stdout)["error"] == "ValueError"


def test_index_rebuild_recovers_from_pre_experiment_id_schema(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _run(project, "--start-run", "--skill", "deep-research", "--json")
    index_path = project / ".research" / "indexes" / "index.db"

    # Simulate an index.db built before this task's runs.experiment_id
    # column existed: drop it back to schema version 1 with the old runs
    # table shape.
    conn = sqlite3.connect(str(index_path))
    conn.execute("PRAGMA user_version = 1")
    conn.execute("DROP TABLE runs")
    conn.execute(
        "CREATE TABLE runs (id TEXT PRIMARY KEY, skill TEXT, mode TEXT, "
        "question_id TEXT, status TEXT, started_at TEXT, ended_at TEXT)"
    )
    conn.commit()
    conn.close()

    result = _run(project, "--rebuild-index", "--json")

    assert result.returncode == 0, result.stderr
    conn = sqlite3.connect(str(index_path))
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    columns = {row[1] for row in conn.execute("PRAGMA table_info(runs)")}
    assert "experiment_id" in columns
    conn.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest skills/agent-state/scripts/tests/test_state_cli.py -v -k "query_by_project or query_by_hypothesis or query_by_experiment or pre_experiment_id"`
Expected: FAIL — `--project-id`/`--hypothesis-id`/`--experiment-id` aren't
accepted by `--query` yet, and the old-schema index isn't recovered from
(the `INSERT` in `_sync_state_tables` would raise `sqlite3.OperationalError:
table runs has no column named experiment_id` if reached — but since
`INDEX_SCHEMA_VERSION` hasn't been bumped yet, the manually-forced
`user_version = 1` reads as *already current*, so `_connect` won't trigger
recovery and the test fails on the missing-column error instead).

- [ ] **Step 3: Extend the schema and version**

In `skills/agent-state/scripts/state_index.py`, change:

```python
INDEX_RELATIVE_PATH = Path(".research/indexes/index.db")
INDEX_SCHEMA_VERSION = 1
```

to:

```python
INDEX_RELATIVE_PATH = Path(".research/indexes/index.db")
INDEX_SCHEMA_VERSION = 2
```

Replace `_SCHEMA` in full:

```python
_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY, name TEXT, description TEXT, status TEXT,
    created_at TEXT, created_by TEXT
);
CREATE TABLE IF NOT EXISTS questions (
    id TEXT PRIMARY KEY, text TEXT, origin_skill TEXT, project_id TEXT,
    status TEXT, created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS hypotheses (
    id TEXT PRIMARY KEY, question_id TEXT, statement TEXT, status TEXT,
    synthetic INTEGER, created_at TEXT, created_by TEXT
);
CREATE TABLE IF NOT EXISTS experiments (
    id TEXT PRIMARY KEY, hypothesis_id TEXT, description TEXT, status TEXT,
    synthetic INTEGER, created_at TEXT, created_by TEXT
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY, skill TEXT, mode TEXT, question_id TEXT,
    experiment_id TEXT, status TEXT, started_at TEXT, ended_at TEXT
);
CREATE TABLE IF NOT EXISTS results (
    id TEXT PRIMARY KEY, run_id TEXT, summary TEXT,
    artifact_role TEXT, artifact_path TEXT, ts TEXT
);
CREATE TABLE IF NOT EXISTS claims (
    id TEXT PRIMARY KEY, run_id TEXT, statement TEXT,
    confidence TEXT, evidence_ref TEXT, ts TEXT
);
CREATE TABLE IF NOT EXISTS shard_checkpoints (
    shard_name TEXT PRIMARY KEY, lines_ingested INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_questions_project_id ON questions(project_id);
CREATE INDEX IF NOT EXISTS idx_hypotheses_question_id ON hypotheses(question_id);
CREATE INDEX IF NOT EXISTS idx_experiments_hypothesis_id ON experiments(hypothesis_id);
CREATE INDEX IF NOT EXISTS idx_runs_skill ON runs(skill);
CREATE INDEX IF NOT EXISTS idx_runs_question_id ON runs(question_id);
CREATE INDEX IF NOT EXISTS idx_runs_experiment_id ON runs(experiment_id);
CREATE INDEX IF NOT EXISTS idx_results_run_id ON results(run_id);
CREATE INDEX IF NOT EXISTS idx_claims_run_id ON claims(run_id);
"""
```

- [ ] **Step 4: Sync the three new tables and the widened `runs` insert**

Replace the `from state_store import (...)` line and the body of
`_sync_state_tables` in full:

```python
def _sync_state_tables(conn: sqlite3.Connection, project_root: Path) -> None:
    """Replace the projects/questions/hypotheses/experiments/runs tables
    with the current YAML contents.

    Args:
        conn: Open connection (schema already applied).
        project_root: The project's root directory.
    """
    # Imported here, not at module scope, so this module never needs
    # state_store's YAML-loading functions except at rebuild time.
    from state_store import (
        DEFAULT_PROJECT_ID,
        EXPERIMENTS_RELATIVE_PATH,
        HYPOTHESES_RELATIVE_PATH,
        PROJECTS_RELATIVE_PATH,
        QUESTIONS_RELATIVE_PATH,
        RUNS_RELATIVE_PATH,
        _load_yaml_map,
    )

    projects = _load_yaml_map(project_root / PROJECTS_RELATIVE_PATH, "projects")
    questions = _load_yaml_map(project_root / QUESTIONS_RELATIVE_PATH, "questions")
    hypotheses = _load_yaml_map(project_root / HYPOTHESES_RELATIVE_PATH, "hypotheses")
    experiments = _load_yaml_map(project_root / EXPERIMENTS_RELATIVE_PATH, "experiments")
    runs = _load_yaml_map(project_root / RUNS_RELATIVE_PATH, "runs")

    conn.execute("DELETE FROM projects")
    if projects:
        conn.executemany(
            "INSERT INTO projects (id, name, description, status, created_at, created_by) "
            "VALUES (:id, :name, :description, :status, :created_at, :created_by)",
            list(projects.values()),
        )
    conn.execute("DELETE FROM questions")
    if questions:
        # Questions written before Task 2 have no "project_id" key at all --
        # default them to DEFAULT_PROJECT_ID, matching create_question's own
        # default, rather than letting the missing key raise a
        # sqlite3.ProgrammingError from executemany's named-parameter binding.
        conn.executemany(
            "INSERT INTO questions "
            "(id, text, origin_skill, project_id, status, created_at, updated_at) "
            "VALUES (:id, :text, :origin_skill, :project_id, :status, :created_at, :updated_at)",
            [{**q, "project_id": q.get("project_id", DEFAULT_PROJECT_ID)} for q in questions.values()],
        )
    conn.execute("DELETE FROM hypotheses")
    if hypotheses:
        conn.executemany(
            "INSERT INTO hypotheses "
            "(id, question_id, statement, status, synthetic, created_at, created_by) "
            "VALUES (:id, :question_id, :statement, :status, :synthetic, :created_at, :created_by)",
            list(hypotheses.values()),
        )
    conn.execute("DELETE FROM experiments")
    if experiments:
        conn.executemany(
            "INSERT INTO experiments "
            "(id, hypothesis_id, description, status, synthetic, created_at, created_by) "
            "VALUES (:id, :hypothesis_id, :description, :status, :synthetic, :created_at, :created_by)",
            list(experiments.values()),
        )
    conn.execute("DELETE FROM runs")
    if runs:
        # Runs written before Task 5 have no "experiment_id" key -- default
        # to None (no ancestry), same reasoning as the questions.project_id
        # default above but with a different fallback value, since a
        # pre-existing standalone Run genuinely has no Experiment to point
        # to (see the design spec's Error Handling section).
        conn.executemany(
            "INSERT INTO runs "
            "(id, skill, mode, question_id, experiment_id, status, started_at, ended_at) "
            "VALUES (:id, :skill, :mode, :question_id, :experiment_id, :status, :started_at, :ended_at)",
            [{**r, "experiment_id": r.get("experiment_id")} for r in runs.values()],
        )
```

- [ ] **Step 5: Extend `query`'s filters**

Replace `query` in full:

```python
def query(
    project_root: Path,
    *,
    run_id: Optional[str] = None,
    question_id: Optional[str] = None,
    project_id: Optional[str] = None,
    hypothesis_id: Optional[str] = None,
    experiment_id: Optional[str] = None,
    skill: Optional[str] = None,
    since: Optional[str] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Sync the index incrementally, then return records for exactly one filter.

    Args:
        project_root: The project's root directory.
        run_id: Return this Run plus its Results and Claims.
        question_id: Return this Question plus Runs linked to it.
        project_id: Return this Project plus Questions linked to it.
        hypothesis_id: Return this Hypothesis plus Experiments linked to it.
        experiment_id: Return this Experiment plus Runs linked to it.
        skill: Return Runs executed by this skill.
        since: ISO-8601 date/datetime string; return Runs started at or
            after it.

    Returns:
        A dict with whichever result keys are relevant to the filter used,
        each a list of row dicts.

    Raises:
        ValueError: If zero or more than one filter is given.
    """
    filters = [
        f for f in
        (run_id, question_id, project_id, hypothesis_id, experiment_id, skill, since)
        if f is not None
    ]
    if len(filters) != 1:
        raise ValueError(
            "query requires exactly one of "
            "run_id/question_id/project_id/hypothesis_id/experiment_id/skill/since"
        )

    rebuild_index(project_root, full=False)
    conn = _connect(project_root)
    try:
        if run_id is not None:
            return {
                "runs": _rows(conn, "SELECT * FROM runs WHERE id = ?", (run_id,)),
                "results": _rows(
                    conn, "SELECT * FROM results WHERE run_id = ? ORDER BY ts", (run_id,)
                ),
                "claims": _rows(
                    conn, "SELECT * FROM claims WHERE run_id = ? ORDER BY ts", (run_id,)
                ),
            }
        if question_id is not None:
            return {
                "questions": _rows(
                    conn, "SELECT * FROM questions WHERE id = ?", (question_id,)
                ),
                "runs": _rows(
                    conn,
                    "SELECT * FROM runs WHERE question_id = ? ORDER BY started_at",
                    (question_id,),
                ),
            }
        if project_id is not None:
            return {
                "projects": _rows(
                    conn, "SELECT * FROM projects WHERE id = ?", (project_id,)
                ),
                "questions": _rows(
                    conn,
                    "SELECT * FROM questions WHERE project_id = ? ORDER BY created_at",
                    (project_id,),
                ),
            }
        if hypothesis_id is not None:
            return {
                "hypotheses": _rows(
                    conn, "SELECT * FROM hypotheses WHERE id = ?", (hypothesis_id,)
                ),
                "experiments": _rows(
                    conn,
                    "SELECT * FROM experiments WHERE hypothesis_id = ? ORDER BY created_at",
                    (hypothesis_id,),
                ),
            }
        if experiment_id is not None:
            return {
                "experiments": _rows(
                    conn, "SELECT * FROM experiments WHERE id = ?", (experiment_id,)
                ),
                "runs": _rows(
                    conn,
                    "SELECT * FROM runs WHERE experiment_id = ? ORDER BY started_at",
                    (experiment_id,),
                ),
            }
        if skill is not None:
            return {
                "runs": _rows(
                    conn, "SELECT * FROM runs WHERE skill = ? ORDER BY started_at", (skill,)
                )
            }
        return {
            "runs": _rows(
                conn,
                "SELECT * FROM runs WHERE started_at >= ? ORDER BY started_at",
                (since,),
            )
        }
    finally:
        conn.close()
```

- [ ] **Step 6: Wire the new filters in `state.py`**

In `_build_parser`, add the new value flag next to `--hypothesis-id`:

```python
    parser.add_argument("--project-id", metavar="ID")
```

In `_dispatch`, replace the `args.query` branch:

```python
    if args.query:
        return state_index.query(
            project_root, run_id=args.run_id, question_id=args.question_id,
            skill=args.skill, since=args.since,
        )
```

with:

```python
    if args.query:
        return state_index.query(
            project_root, run_id=args.run_id, question_id=args.question_id,
            project_id=args.project_id, hypothesis_id=args.hypothesis_id,
            experiment_id=args.experiment_id, skill=args.skill, since=args.since,
        )
```

- [ ] **Step 7: Add the `sqlite3` import to the test file if not already present**

`tests/test_state_cli.py` already imports `sqlite3` at the top (added
during the earlier schema-versioning work) — confirm with
`grep -n "^import sqlite3" skills/agent-state/scripts/tests/test_state_cli.py`
before writing `test_index_rebuild_recovers_from_pre_experiment_id_schema`;
no action needed if it's already there.

- [ ] **Step 8: Run the tests to verify they pass**

Run: `pytest skills/agent-state/scripts/tests/test_state_cli.py -v`
Expected: PASS (74 tests total: 69 + 5 new).

- [ ] **Step 9: Run the full suite including locking tests**

Run: `pytest skills/agent-state/scripts/tests/ -v`
Expected: PASS (77 tests total: 74 in `test_state_cli.py` + 3 in
`test_state_locking.py`, unaffected by this task).

- [ ] **Step 10: Commit**

```bash
git add skills/agent-state/scripts/state_index.py \
        skills/agent-state/scripts/state.py \
        skills/agent-state/scripts/tests/test_state_cli.py
git commit -m "feat(agent-state): index Project/Hypothesis/Experiment, extend --query"
```

---

### Task 7: `--validate`

**Files:**
- Modify: `skills/agent-state/scripts/state_store.py`
- Modify: `skills/agent-state/scripts/state.py`
- Test: `skills/agent-state/scripts/tests/test_state_cli.py`

**Interfaces:**
- Consumes: `state_store.load_projects`, `load_questions`, `load_hypotheses`,
  `load_experiments`, `load_runs` (Tasks 1-5).
- Produces:
  - `state_store.validate_referential_integrity(project_root: Path) -> List[Dict[str, Any]]`
  - `state.py` CLI: `--validate [--json]`, returning
    `{"violations": [...], "clean": bool}`.

- [ ] **Step 1: Write the failing tests**

Append to `skills/agent-state/scripts/tests/test_state_cli.py`:

```python
def test_validate_on_clean_project_reports_no_violations(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _run(project, "--start-run", "--skill", "deep-research", "--question", "Q?", "--json")

    result = _run(project, "--validate", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data == {"violations": [], "clean": True}


def test_validate_detects_dangling_hypothesis_question_id(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _run(project, "--start-run", "--skill", "deep-research", "--question", "Q?", "--json")
    hypotheses_path = project / ".research" / "state" / "hypotheses.yaml"
    doc = yaml.safe_load(hypotheses_path.read_text())
    only_hypothesis = next(iter(doc["hypotheses"].values()))
    only_hypothesis["question_id"] = "q_does_not_exist"
    hypotheses_path.write_text(yaml.safe_dump(doc, sort_keys=True))

    result = _run(project, "--validate", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["clean"] is False
    assert data["violations"] == [{
        "entity": "hypothesis", "id": only_hypothesis["id"],
        "field": "question_id", "missing_id": "q_does_not_exist",
    }]


def test_validate_detects_dangling_experiment_hypothesis_id(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _run(project, "--start-run", "--skill", "deep-research", "--question", "Q?", "--json")
    experiments_path = project / ".research" / "state" / "experiments.yaml"
    doc = yaml.safe_load(experiments_path.read_text())
    only_experiment = next(iter(doc["experiments"].values()))
    only_experiment["hypothesis_id"] = "hyp_does_not_exist"
    experiments_path.write_text(yaml.safe_dump(doc, sort_keys=True))

    result = _run(project, "--validate", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["clean"] is False
    assert {
        "entity": "experiment", "id": only_experiment["id"],
        "field": "hypothesis_id", "missing_id": "hyp_does_not_exist",
    } in data["violations"]


def test_validate_detects_dangling_question_project_id(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    started = json.loads(
        _run(project, "--start-run", "--skill", "deep-research", "--question", "Q?", "--json").stdout
    )
    questions_path = project / ".research" / "state" / "questions.yaml"
    doc = yaml.safe_load(questions_path.read_text())
    doc["questions"][started["question_id"]]["project_id"] = "proj_does_not_exist"
    questions_path.write_text(yaml.safe_dump(doc, sort_keys=True))

    result = _run(project, "--validate", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["clean"] is False
    assert {
        "entity": "question", "id": started["question_id"],
        "field": "project_id", "missing_id": "proj_does_not_exist",
    } in data["violations"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest skills/agent-state/scripts/tests/test_state_cli.py -v -k validate`
Expected: FAIL (`--validate` isn't a recognized flag yet).

- [ ] **Step 3: Implement `validate_referential_integrity` in `state_store.py`**

Change the `typing` import line from:

```python
from typing import Any, Dict, Iterator, Optional
```

to:

```python
from typing import Any, Dict, Iterator, List, Optional
```

Add the function at the end of the file, after `record_claim`:

```python
def validate_referential_integrity(project_root: Path) -> List[Dict[str, Any]]:
    """Scan state/*.yaml for dangling foreign keys.

    This is a diagnostic pass over hand-authored/hand-edited data -- every
    write path in this module already rejects a dangling reference at write
    time, so a clean project should always report zero violations. Nothing
    is repaired; repair is a human decision.

    Args:
        project_root: The project's root directory.

    Returns:
        A list of violation dicts, each shaped
        {"entity": <type>, "id": <record id>, "field": <fk field name>,
        "missing_id": <the dangling id>}. Empty if nothing is broken.
    """
    projects = load_projects(project_root)
    questions = load_questions(project_root)
    hypotheses = load_hypotheses(project_root)
    experiments = load_experiments(project_root)
    runs = load_runs(project_root)

    violations: List[Dict[str, Any]] = []
    for question_id, question in questions.items():
        project_id = question.get("project_id")
        if project_id and project_id not in projects:
            violations.append({
                "entity": "question", "id": question_id,
                "field": "project_id", "missing_id": project_id,
            })
    for hypothesis_id, hypothesis in hypotheses.items():
        question_id = hypothesis.get("question_id")
        if question_id not in questions:
            violations.append({
                "entity": "hypothesis", "id": hypothesis_id,
                "field": "question_id", "missing_id": question_id,
            })
    for experiment_id, experiment in experiments.items():
        hypothesis_id = experiment.get("hypothesis_id")
        if hypothesis_id not in hypotheses:
            violations.append({
                "entity": "experiment", "id": experiment_id,
                "field": "hypothesis_id", "missing_id": hypothesis_id,
            })
    for run_id, run in runs.items():
        experiment_id = run.get("experiment_id")
        if experiment_id and experiment_id not in experiments:
            violations.append({
                "entity": "run", "id": run_id,
                "field": "experiment_id", "missing_id": experiment_id,
            })
    return violations
```

- [ ] **Step 4: Wire `--validate` in `state.py`**

In `_build_parser`, add the action flag after `--report`:

```python
    action.add_argument("--validate", action="store_true")
```

In `_dispatch`, add the branch right before the final
`raise AssertionError`:

```python
    if args.validate:
        violations = state_store.validate_referential_integrity(project_root)
        return {"violations": violations, "clean": len(violations) == 0}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest skills/agent-state/scripts/tests/test_state_cli.py -v`
Expected: PASS (78 tests total: 74 + 4 new).

- [ ] **Step 6: Run the full suite**

Run: `pytest skills/agent-state/scripts/tests/ -v`
Expected: PASS (81 tests total: 78 in `test_state_cli.py` + 3 in
`test_state_locking.py`).

- [ ] **Step 7: Commit**

```bash
git add skills/agent-state/scripts/state_store.py \
        skills/agent-state/scripts/state.py \
        skills/agent-state/scripts/tests/test_state_cli.py
git commit -m "feat(agent-state): add --validate for referential integrity"
```

---

### Task 8: Update `SKILL.md`

**Files:**
- Modify: `skills/agent-state/SKILL.md`

**Interfaces:** None — documentation only, no code.

- [ ] **Step 1: Update the frontmatter description**

Change the `description:` line (currently ending
`"...Triggers on phrases like \"what have you been running\", \"log this
run\", \"show agent activity\"."`) to also mention the new entities. Replace
the full `description:` value:

```yaml
description: Records what the agent does as it drives other skills -- Questions worked on, Runs executed, Results produced, Claims asserted -- in .research/state (canonical, low-frequency) and .research/events (canonical, append-only). Also models the research itself as Project/Hypothesis/Experiment, layered above Question/Run, with write-time referential integrity checks. Use when a skill wants to track its own execution history instead of writing one file per run, or when a user wants to see what the agent has been doing. Triggers on phrases like "what have you been running", "log this run", "show agent activity".
```

- [ ] **Step 2: Update the opening paragraph**

Replace the opening paragraph (currently "Stores four cross-skill entities
without one file per record: Question and Run are low-frequency, mutable,
and live in id-keyed YAML maps under `.research/state/`; Result and Claim
are immutable facts appended to daily JSONL shards under `.research/events/`.
A SQLite index under `.research/indexes/` gives fast filtered queries and is
rebuilt on demand -- it is never a source of truth and can be deleted at any
time.") with:

```markdown
Stores seven cross-skill entities without one file per record. Project,
Question, Hypothesis, Experiment, and Run are low-frequency, mutable, and
live in id-keyed YAML maps under `.research/state/`; Result and Claim are
immutable facts appended to daily JSONL shards under `.research/events/`.
A SQLite index under `.research/indexes/` gives fast filtered queries and is
rebuilt on demand -- it is never a source of truth and can be deleted at any
time.

The research entities form a strict linear chain -- Project -> Question ->
Hypothesis -> Experiment -> Run -> Result -- with a foreign key validated at
write time on every link. A Run that supplies at least a Question (directly
or via `--hypothesis-id`/`--experiment-id`) gets any missing levels below it
auto-filled with `synthetic: true` placeholder records, so the chain is
never broken. A Run given none of `--question`/`--question-id`/
`--hypothesis-id`/`--experiment-id` stays fully standalone, exactly as
before this chain existed: `question_id`, `hypothesis_id`, and
`experiment_id` are all `null`, and nothing is auto-created.
```

- [ ] **Step 3: Add a "Research chain" section**

Insert a new section after the existing "## Calling convention" section
(before "## Querying"):

```markdown
## Research chain

```bash
# Register a Project by hand (optional -- proj_default is created lazily
# the first time any Question needs a Project, and covers the common
# single-Project case with no setup step).
python "$STATE" --create-project --name "Offline Support Initiative" \
  --description "Investigate offline usage patterns." --json

# Declare a Hypothesis under an existing Question, and an Experiment under it.
python "$STATE" --create-hypothesis --question-id q_20260806_ab12cd \
  --statement "Offline support is unnecessary." --skill deep-research --json
python "$STATE" --create-experiment --hypothesis-id hyp_20260806_ef34gh \
  --description "Survey production traffic logs." --skill deep-research --json

# Start a Run against that Experiment directly...
python "$STATE" --start-run --skill deep-research --experiment-id exp_20260806_ij56kl --json
# ...or let --start-run auto-fill a synthetic Hypothesis+Experiment from
# just a Question, the same as before this feature existed:
python "$STATE" --start-run --skill deep-research --question "New question text" --json

# Record a verdict once the Experiment concludes.
python "$STATE" --set-hypothesis-status --hypothesis-id hyp_20260806_ef34gh --status supported --json
python "$STATE" --set-experiment-status --experiment-id exp_20260806_ij56kl --status completed --json
```

`synthetic: true` on an auto-created Hypothesis/Experiment marks it as
chain-completion scaffolding rather than a deliberately declared one --
`--query`/`--report` output can filter on it, but it behaves identically to
a hand-created record otherwise (queryable, its status can be changed).
```

- [ ] **Step 4: Extend the "Querying" section**

In the existing `## Querying` code block, add three lines after the
`--question-id` example:

```bash
python "$STATE" --query --project-id proj_default --json      # project + its questions
python "$STATE" --query --hypothesis-id hyp_20260806_ef34gh --json  # hypothesis + its experiments
python "$STATE" --query --experiment-id exp_20260806_ij56kl --json  # experiment + its runs
```

- [ ] **Step 5: Add a "Validating referential integrity" section**

Insert a new section after "## Rebuilding the index" (before "## Schema
versioning"):

```markdown
## Validating referential integrity

```bash
python "$STATE" --validate --json
```

Every `--create-hypothesis`/`--create-experiment`/`--start-run` call already
rejects a dangling foreign key at write time -- `--validate` exists for the
case where `state/*.yaml` was hand-edited afterward. It reports every
dangling reference it finds (`{"entity": ..., "id": ..., "field": ...,
"missing_id": ...}` per violation) and repairs nothing; a clean project
returns `{"violations": [], "clean": true}`.
```

- [ ] **Step 6: Update the "Non-goals" section**

In the existing `## Non-goals` list, add one bullet after the existing
"Does not implement actual cross-version data migration..." bullet:

```markdown
- Does not migrate `research-log`, `report-slides`, `academic-paper`, or any
  review workflow to actually call into the Project/Hypothesis/Experiment
  layer -- this defines the schema and CLI contract; wiring a specific
  consumer to it is separate follow-up work.
- Does not enforce a status state machine on Hypothesis/Experiment (e.g.
  nothing stops moving a `completed` Experiment back to `running`) -- status
  is a label a caller sets, not a guarded lifecycle.
```

- [ ] **Step 7: Verify the doc renders sensibly**

Run: `cat skills/agent-state/SKILL.md` and read it end to end once, checking
the new sections sit in the order Steps 1-6 placed them and that no
Markdown code fence was left unclosed (an easy mistake when inserting a code
block inside a section that's itself demonstrated via a code block).

- [ ] **Step 8: Commit**

```bash
git add skills/agent-state/SKILL.md
git commit -m "docs(agent-state): document Project/Hypothesis/Experiment and --validate"
```

---

## Final Regression Check (after Task 8)

Run the full test suite one more time from the repository root to confirm
nothing outside `skills/agent-state/` was touched or broken:

```bash
pytest skills/agent-state/scripts/tests/ -v
```

Expected: 81 tests passing (49 baseline + 32 added across Tasks 1-7:
3 + 2 + 6 + 6 + 6 + 5 + 4).

```bash
ruff check skills/agent-state/
```

Expected: clean (no new lint findings).
