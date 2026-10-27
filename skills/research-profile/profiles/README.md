# Profiles

Each subdirectory is one profile. The registry of all profiles, with what each
one sets, is `PROFILE_REGISTRY.md` at the repository root. The schema is
`../references/profile_schema.md`.

Name a profile for what it does, never for who it belongs to: no person,
advisor, school, lab, course, or paper names, in the directory name or in the
example sentences inside it.

## Template

```yaml
# profiles/<name>/profile.yaml
name: <name>
description: <one line: what this profile changes>
extends: []            # optional: profiles to merge first
axes:
  voice:
    rules: voice.md
  language:
    body: en
    abstract: [en]
    interface: follow-user
  field:
    domain: <domain>
    references: [field/glossary.md]
  venue:
    citation_style: ieee
  slides:
    report-slides: paper
```

Delete the axes the profile does not set; they keep the core default.
