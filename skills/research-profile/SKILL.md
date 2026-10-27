---
name: research-profile
description: "Selects and resolves named profiles: bundles of conventions that belong to one way of working rather than to a skill's core, such as a writing voice, a language policy, a field's references, a venue's citation style, or a slide style. Skills keep general defaults and read the active profile from here. Use when the user wants to list, inspect, choose, or clear a profile, or when a skill needs to know which conventions are in force. Triggers: /profile, use profile, switch profile, which profile, list profiles, set project profile, 切換設定檔, 使用設定檔, 目前用哪個設定檔."
metadata:
  version: "1.0.0"
  last_updated: "2026-10-27"
  data_access_level: raw
  task_type: open-ended
  related_skills:
    - academic-paper
    - academic-paper-reviewer
    - academic-pipeline
    - deep-research
    - research-mode
    - report-slides
---

# Research Profile

A **profile** is a named, selectable bundle of conventions. Anything that is
true for one person, course, lab, field, venue, or language, and not for
research in general, lives in a profile instead of a skill's core. With no
profile active, every skill runs on its general defaults.

Profiles are a third axis, separate from the two kinds of "mode" in this repo:

| Concept | Answers | Example |
|---------|---------|---------|
| Skill mode (`MODE_REGISTRY.md`) | Which task? | `academic-paper` `revision` |
| Work mode (`/mode`, research-mode) | Which phase of work? | `/mode publish` |
| Profile (this skill, `PROFILE_REGISTRY.md`) | Whose conventions? | `formal-explicit-voice` |

They combine freely: `academic-paper` in `revision` mode, during
`/mode publish`, with a profile active.

## Axes

A profile sets any subset of five axes. An axis it leaves unset keeps the core
default. Full field definitions: `references/profile_schema.md`.

| Axis | Decides | Core default (no profile) | Read by |
|------|---------|---------------------------|---------|
| `voice` | Sentence-level writing rules | None: no prescriptive voice | academic-paper, deep-research report writing |
| `language` | Body, abstract, and interface language | Follow the user's language; one abstract, in the body language | academic-paper, research-mode, research-log |
| `field` | Domain, evidence profile, glossary, journals, ethics jurisdiction, examples | None: ask, never assume a domain | deep-research, academic-paper, academic-paper-reviewer |
| `venue` | Citation style and venue references | Ask; never preselect a style | academic-paper, academic-pipeline, deep-research |
| `slides` | Which style or preset each slide skill uses | Each slide skill's own default | report-slides, lecture-slides |

The `slides` axis names a style or preset that the slide skill itself owns
(for example `slides: {report-slides: paper}`). Profiles never copy slide
style files.

## Choosing a profile

Precedence, lowest to highest:

1. **Core defaults:** no profile.
2. **Project:** `.research/profile.yaml` (`profile: <name>`), next to
   resource-resolver's `workspace.yaml`. Set with `/profile set <name>`.
3. **Session:** `/profile use <name>` in conversation, or "use the <name>
   profile" in a request. Lasts until the session ends or `/profile clear`.

## Commands

| Command | Action |
|---------|--------|
| `/profile` or `/profile status` | Show the active profile, where it came from, and what each axis resolves to |
| `/profile list` | List installed profiles and the axes each sets |
| `/profile show <name>` | Show one profile, `extends` merged |
| `/profile use <name>` | Activate for this session only |
| `/profile set <name>` | Record as this project's profile (writes `.research/profile.yaml`) |
| `/profile clear` | Drop the session choice; with `--project`, also clear the project file |

All of them go through the script:

```bash
# macOS / Linux / Git Bash:
PROFILE="$(find ~/.claude -path "*/research-profile/scripts/profile.py" | head -1)"
python "$PROFILE" --active --json                       # status
python "$PROFILE" --active --session <name> --json      # status with a session choice
python "$PROFILE" --list
python "$PROFILE" --show <name>
python "$PROFILE" --set <name>                          # project file
python "$PROFILE" --clear                               # project file
```

`/profile use` is held in the conversation, not on disk: pass it to every
later `--active` call as `--session <name>`. Confirm before `--set`, since it
changes the project for everyone who works in it.

## How a consuming skill reads the profile

At the start of a task, a skill that has an axis listed above runs
`--active --json` (adding `--session` if the user chose one) and uses
`axes.<axis>` from the result. The result always carries every axis, filled
with the core default when no profile sets it, so the skill never restates
its own fallback.

- A file-valued key (`voice.rules`, `field.references`, ...) is an absolute
  path. Read the file; it is part of the instructions for this task.
- `language.*: follow-user` means use the language the user writes in.
  `language.abstract` lists every abstract to produce; `[follow-user]`
  means one abstract in the body language.
- `venue.citation_style: null` means ask the user, as the skill did before.
- When a profile is active, say so once in the skill's opening banner or
  first reply: `Profile: <name>`.

A profile adjusts conventions. It never switches off an IRON RULE, an
integrity gate, or a citation requirement; where a profile rule conflicts with
one, the rule in the core wins and the conflict is reported to the user.

## Writing a new profile

1. Pick a **descriptive, non-identifying name**: it says what the profile
   does, never who it is for. No person, advisor, school, lab, course, or
   paper names. `formal-explicit-voice`, not a professor's surname;
   `bilingual-education-research`, not a university. Example sentences inside
   the profile are de-identified the same way.
2. Create `profiles/<name>/profile.yaml` from `profiles/README.md`'s
   template, plus any files it points at.
3. Use `extends` to compose: a personal profile can extend a voice profile and
   a venue profile and override one key.
4. Run `python "$PROFILE" --validate <name>`, then add a row to
   `PROFILE_REGISTRY.md` at the repository root.

`scripts/checks/check_profiles.py` enforces the schema, the registry, and the
naming rule in CI. `scripts/checks/check_core_neutrality.py` keeps
profile-specific terms from creeping back into skill cores.
