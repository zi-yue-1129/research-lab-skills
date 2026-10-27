# bilingual-education-research

The conventions the academic skills (inherited from upstream ARS) used to apply
to everyone: a higher-education domain, an English + Traditional Chinese
abstract pair on every paper, APA 7, Taiwan's IRB process, Taiwan's
TSSCI-indexed education journals, and higher-education worked examples. They
now apply only when this profile is active.

| Axis | Setting | Read by |
|------|---------|---------|
| `language.abstract` | `[en, zh-TW]`: two independently composed abstracts | `academic-paper` intake and `abstract_bilingual_agent` |
| `field.domain` | higher education (proposed at intake; the user confirms) | `academic-paper` intake, `deep-research` |
| `field.references` | `field/hei_domain_glossary.md` (bilingual terminology) | `academic-paper` drafting and abstracts |
| `field.ethics` | `field/taiwan_irb_and_education_ethics.md` | `deep-research` ethics review and research design |
| `field.journals` | `field/regional_journals.md` (TSSCI education journals) | `academic-paper-reviewer` field analyst and EIC |
| `field.examples` | IMRaD and Chinese-language paper examples; a full and a cross-disciplinary review | `academic-paper`, `academic-paper-reviewer` |
| `venue.citation_style` | `apa7` | `academic-paper` intake, `deep-research` reports |

Body and interface language are not set, so they still follow the user.

The optional `tw-hei-intelligence` skill (not part of this repository), which
verifies higher-education statistics against public Ministry of Education
data, pairs naturally with this profile.
