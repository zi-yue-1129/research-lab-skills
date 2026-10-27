---
name: writing-voice
description: "Draft or revise academic prose in a specific, calibrated voice, and calibrate new voices from someone's real manuscript edits. The voice's rules come from the active research profile (its `voice` axis), never from this skill, so the skill works for any author or advisor. Ships scripts that extract a returned .docx and align it sentence by sentence against the Markdown sources, to derive or refresh a voice. Guardrails keep style from dropping limitations, inflating claims, or touching numbers. Triggers: write in my advisor's style, advisor style, lab writing style, apply the voice, calibrate a writing voice, learn from these edits, 教授的寫法, 教授風格, 用教授的風格改寫, polish this paragraph, academic English polish."
metadata:
  version: "2.0.0"
  last_updated: "2026-10-27"
  status: active
  data_access_level: verified_only
  task_type: open-ended
  related_skills:
    - research-profile
    - academic-paper
    - academic-paper-reviewer
    - academic-pipeline
---

# Writing Voice

Applies a prescriptive writing voice to drafting and revision, and derives new
voices from real edits. This skill holds the method and the guardrails. The
rules of any particular voice live in a profile (`research-profile`, axis
`voice`), so one person's habits never become everyone's default.

For a soft, descriptive match to an author's own past papers, use
`academic-paper`'s Style Calibration instead
(`shared/protocols/style_calibration_protocol.md`). Use this skill when the
voice is prescriptive: someone's edits say "write it this way".

## Which voice

```bash
PROFILE="$(find ~/.claude -path "*/research-profile/scripts/profile.py" | head -1)"
python "$PROFILE" --active --json        # add --session <name> if /profile use was given
```

- `axes.voice.rules` is a path: read that file. It holds the numbered rules,
  their before and after examples, and the voice's own revision checklist.
- `axes.voice` is `null`: no voice is active. Do not invent one. Say so, and
  offer the choices: activate a profile that sets a voice
  (`python "$PROFILE" --list` shows which do), calibrate a new one (below), or
  fall back to `academic-paper`'s Style Calibration.
- The user hands over a rules file directly: use it for this task only.

State once which voice is in use: `Voice: <profile name>`.

## Applying a voice

- **Drafting:** write against the rules from the start.
- **Revising:** run the voice's checklist over the draft in order, then the
  guardrail checks below. Report what changed in a short list.
- A rule that would break a venue requirement the user names (length, citation
  style, section order) yields to the venue. Mention the conflict.

## Guardrails

Style is a way of writing, not a licence to change what the paper claims.
These hold for every voice and outrank every voice rule.

- **IRON RULE: never drop a limitation to tighten a sentence.** Compression is
  where hedges die: a control still to be run, a parameter fixed by argument
  rather than swept, the reason two metrics sit on separate figures. If a rule
  makes a caveat awkward, give the caveat its own sentence, and tell the
  author what moved.
- **IRON RULE: a strengthened verb needs evidence that strong.** A raised
  register makes claims sound stronger. Check each strengthened verb
  ("demonstrates", "establishes") against the test that backs it. If nothing
  survives correction, the sentence says so.
- **IRON RULE: style never touches a number.** Numerals may replace spelled-out
  words; they never replace a value. Figures come from the analysis pipeline.

Run after every revision:

1. Is every caveat still present and still true?
2. Does any strengthened verb outrun its evidence?
3. Is every number, citation, and cross-reference unchanged? (`sentence_diff.py
   --facts` before and after gives the inventory.)

## Calibrating a new voice

Use when someone returns edited manuscripts and wants future drafts to arrive
in that voice.

1. Extract the returned document and align it against the sources:
   ```bash
   VOICE_DIR="$(dirname "$(find ~/.claude -path "*/writing-voice/SKILL.md" | head -1)")"
   python3 "$VOICE_DIR/scripts/docx_text.py" returned.docx > returned.txt
   python3 "$VOICE_DIR/scripts/sentence_diff.py" --docx returned.txt --sources paper/*.md
   ```
2. Group the changes into patterns. Keep a pattern only when it recurs at
   least twice. Record each with its real before and after.
3. Watch for what an edit round also carries: compressed hedges, stale
   numbers, new typos, inline notes that are really to-dos. Those are tasks,
   not voice.
4. Write a new profile under `research-profile`'s `profiles/<name>/`:
   `voice.md` (rules, examples, revision checklist), `derivation_evidence.md`
   (the observations and their instances), and `profile.yaml` with
   `axes.voice.rules: voice.md`. `profiles/formal-explicit-voice/` is a
   complete worked example.
5. **Name and de-identify.** The profile name says what the voice does
   (`concise-passive-voice`), never whose it is. Replace method, paper, and
   project names in the examples with neutral stand-ins; keep the patterns.
6. Validate and register: `python "$PROFILE" --validate <name>`, then a row in
   `PROFILE_REGISTRY.md`.

To refresh an existing voice after a new round of edits, rerun steps 1 to 3,
add what recurs to its `derivation_evidence.md`, and promote a pattern to a
rule in `voice.md` once it has two instances. Do not carry rules from one
person's voice into another's on the assumption that academic style is
universal.
