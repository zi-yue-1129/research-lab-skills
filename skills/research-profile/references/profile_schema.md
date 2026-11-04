# Profile Schema

Every profile is a directory `profiles/<name>/` holding a `profile.yaml` and
the files it points at. `scripts/profile.py --validate` enforces this schema.

## Top level

| Key | Required | Type | Meaning |
|-----|----------|------|---------|
| `name` | yes | kebab-case string | Must equal the directory name |
| `description` | yes | string | One line: what the profile changes, not who it is for |
| `extends` | no | list of names | Profiles merged first, in order; this profile's keys win |
| `axes` | unless `extends` is set | mapping | Any subset of the five axes below |

## Axes

File-valued keys are paths relative to the profile directory. `--show` and
`--active` return them as absolute paths.

### `voice`

| Key | Type | Meaning |
|-----|------|---------|
| `rules` | file | Prescriptive writing rules, applied when drafting and run as a checklist when revising. Format: see the `writing-voice` skill |

### `language`

Language tags are BCP 47 style (`en`, `zh-TW`, `ja`), or `follow-user`.

| Key | Type | Core default | Meaning |
|-----|------|--------------|---------|
| `body` | tag | `follow-user` | Language of the paper or report body |
| `abstract` | list of tags | `[follow-user]` | One abstract per tag; `follow-user` means the body language |
| `interface` | tag | `follow-user` | Language of banners, prompts, and log drafts |

### `field`

| Key | Type | Meaning |
|-----|------|---------|
| `domain` | string | Default domain to propose at intake (the user still confirms) |
| `evidence_profile` | string | A domain evidence profile id from `academic-paper`'s intake (Step on domain evidence) |
| `references` | list of files | Glossaries and field guides to load alongside the skill's own references |
| `ethics` | file | Ethics-review jurisdiction details (e.g. a national IRB process) |
| `journals` | file | Journals to add to the reviewer's journal directory |
| `examples` | list of files | Worked examples in this field |

### `venue`

| Key | Type | Core default | Meaning |
|-----|------|--------------|---------|
| `citation_style` | one of `apa7`, `chicago-author-date`, `chicago-notes`, `mla9`, `ieee`, `vancouver` | `null` (ask) | Citation style to use without asking |
| `references` | list of files | none | Style guides for this venue or style |

### `slides`

A mapping from a slide skill's name to one of that skill's own style or
preset names, e.g. `report-slides: paper`. The slide skill validates the name.

## Resolution

`--active` returns every axis. An axis the profile sets is merged key by key
over the core default; an axis it leaves unset is the core default.
