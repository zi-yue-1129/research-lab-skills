# Profile Registry

Single source of truth for every profile the suite ships. A profile is a
named, selectable bundle of conventions (voice, language, field, venue,
slides) that would otherwise be hardcoded into a skill. See
`skills/research-profile/SKILL.md` for how profiles are chosen and read, and
`skills/research-profile/references/profile_schema.md` for the fields.

When adding or changing a profile, update this file in the same change:
`scripts/checks/check_profiles.py` fails when this table and
`skills/research-profile/profiles/` disagree.

Names describe what a profile does, never who it is for: no person, advisor,
school, lab, course, or paper names.

| Profile | Axes set | Extends | Use for |
|---------|----------|---------|---------|
| `formal-explicit-voice` | voice | — | Formal academic English: first-person claims, explicit connectives, subordination, strict acronym and numeral rules, raised verb register. Applied by `writing-voice`. |
