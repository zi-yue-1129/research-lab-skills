# IRB Decision Tree — Human Subjects Research Ethics Review Guide

## Purpose
IRB (Institutional Review Board) ethics review decision tree. Jurisdiction-specific processes come from the active research profile (section 3). Used by the ethics_review_agent to determine whether research involves human subjects, and by the research_architect_agent to plan IRB review during methodology design.

---

## 1. Human Subjects Research Determination Decision Tree

```
Does your research collect, use, or analyze data from humans?
│
├── No → Does not involve human subjects, no IRB review needed
│         (e.g., pure theoretical research, literature review, secondary analysis of public statistics)
│
└── Yes → Is the data personally identifiable?
          │
          ├── No → Is the data publicly available public data?
          │        │
          │        ├── Yes → Typically exempt from review
          │        │         But must still submit an exempt review application to IRB for confirmation
          │        │
          │        └── No → Proceed to "Review Level Determination" below
          │
          └── Yes → Does the research involve direct interaction with subjects?
                    │
                    ├── No → Only uses existing data/specimens
                    │        │
                    │        ├── Data already de-identified → May apply for exempt review
                    │        └── Data contains identifiable information → Expedited or full board review
                    │
                    └── Yes → Proceed to "Review Level Determination" below
```

---

## 2. Three-Level Review System

### 2.1 Exempt Review

**Applicable Conditions** (any one of the following):
- [ ] Uses publicly available, de-identified datasets
- [ ] Research on educational practices in normal educational settings
- [ ] Involves only anonymous surveys (no sensitive topics)
- [ ] Observation of public behavior (no identifiable information recorded)
- [ ] Uses government public statistical data

**Note**: Exempt review does not mean exempt from application — you must still submit to IRB to confirm exempt status.

### 2.2 Expedited Review

**Applicable Conditions** (all must be met):
- [ ] Research risk is no greater than risks ordinarily encountered in daily life (minimal risk)
- [ ] Does not involve vulnerable populations
- [ ] Research methods are on the expedited review category list

**Common Categories**:
- Surveys (containing sensitive but not high-risk topics)
- Interviews (general topics)
- Teaching intervention research (non-invasive)
- Audio/video recording (with consent)
- Secondary analysis of previously collected clinical data

### 2.3 Full Board Review

**Applicable Conditions** (any one of the following):
- [ ] Greater than minimal risk
- [ ] Involves vulnerable populations (children, prisoners, pregnant women, individuals with cognitive impairments)
- [ ] Involves sensitive topics (sexual behavior, illegal behavior, mental health)
- [ ] Uses deception
- [ ] May cause psychological or social harm

---

## 3. Jurisdiction-Specific Process

Review authorities, governing law, application steps, and timelines differ by
country and institution, so they are not hardcoded here. In order:

1. If the active research profile sets `field.ethics` (`research-profile`,
   `--active --json`), read that file: it holds the process for its
   jurisdiction.
2. Otherwise ask the user which country and institution will review the study,
   and plan around their institution's IRB or ethics committee. Do not assume
   any one country's law or authorities.

The general shape is common: determine whether human subjects are involved
(section 1), pick the review level (section 2), submit the proposal, consent
form, instruments and training certificates to the institutional committee,
start only after approval, then report progress and closure.

---

## 4. Field Quick Reference

Scenario-by-scenario review levels for one field (for example education
research) ship in that field's research profile, alongside its jurisdiction
process. Section 2's criteria apply everywhere.

---

## 5. Informed Consent Form Elements

### 5.1 Required Items

- [ ] Research title
- [ ] Research institution and principal investigator name
- [ ] Research purpose
- [ ] Research procedures description (what subjects need to do, how long it takes)
- [ ] Potential risks and discomfort
- [ ] Potential benefits
- [ ] Confidentiality measures (how data is stored, who has access, retention period)
- [ ] Voluntary nature of participation (may withdraw at any time, no penalties)
- [ ] Researcher contact information
- [ ] IRB contact information (complaint channel)
- [ ] Subject signature and date field

### 5.2 Special Situations

| Situation | Additional Requirements |
|-----------|------------------------|
| **Online survey** | Electronic consent (clicking "I agree" constitutes consent); must state that IP addresses will not be recorded |
| **Audio/video recording** | Separate checkbox item: consent to audio/video recording |
| **Minors** | Legal guardian consent + subject assent |
| **Cross-national research** | Comply with the IRB requirements of every jurisdiction involved (the researcher's home institution and each research site) |
| **Indigenous research** | Community consent (tribal consent) + individual informed consent |

### 5.3 Informed Consent Form Template Structure

```
Research Participation Consent Form

1. Research Project Title: [                    ]
2. Principal Investigator: [      ] / Institution: [        ]
3. Research Purpose: [                              ]
4. Research Methods and Procedures:
    You will be invited to [specific description of what the subject will do],
    estimated to take [  ] minutes.
5. Potential Risks or Discomfort: [                        ]
6. Potential Benefits: [                              ]
7. Confidentiality Measures:
    Your data will be processed using codes; research results will only be
    presented in aggregate form, and your personal identity will not be
    disclosed. Data will be destroyed after [X] years.
8. Voluntary Nature of Participation:
    You are free to decide whether to participate in this study and may
    withdraw at any time without any adverse consequences.
9. Contact Information:
    Principal Investigator: [Name] [Phone] [Email]
    IRB Contact: [Institution Name] [Phone] [Email]

□ I have read and understood the above explanation and agree to participate
  in this research.

Subject Signature: __________ Date: __________
Researcher Signature: __________ Date: __________
```

---

## 6. Data De-identification and Privacy Protection

### 6.1 De-identification Strategies

| Strategy | Description | Applicable Scenario |
|----------|-------------|---------------------|
| **Anonymization** | Complete removal of all identifiable information, irreversible | Final data publication |
| **Pseudonymization** | Replace with codes, retain a linkage table | Need to track during research process |
| **Data generalization** | Convert precise values to ranges (e.g., age → age group) | Statistical analysis |
| **Data masking** | Hide partial information (e.g., partially masked email) | Data display |
| **k-anonymity** | Ensure each record is indistinguishable from at least k-1 other records | Dataset release |

### 6.2 Common Privacy Risks in Higher Education Research

- **Small sample identification**: Small departments may allow re-identification through descriptive statistics
- **Cross-referencing**: Combining multiple de-identified datasets may enable re-identification
- **Narrative identification**: Qualitative research quotations may reveal interviewee identity
- **Institutional identification**: Overly specific institutional characteristics may allow institution identification

### 6.3 Recommended Practices

- [ ] Remove direct identifiers (names, student IDs, national ID numbers)
- [ ] Assess indirect identifier risks (department + year + gender combinations may identify individuals)
- [ ] Check qualitative quotations: remove identifiable details
- [ ] Handle institutional names: decide whether to anonymize based on research needs
- [ ] Encrypt data storage with access controls
- [ ] Establish data retention and destruction timeline

---

## Quick Reference: Researcher Self-Check

Before starting research, answer the following questions:

1. [ ] Does my research collect, use, or analyze human-related data?
2. [ ] If yes, is the data completely de-identified and publicly available?
3. [ ] If not, which level of IRB review do I need to apply for?
4. [ ] Have I completed research ethics training (CITI or equivalent)?
5. [ ] Does my informed consent form include all required elements?
6. [ ] Do I have an appropriate data protection plan?
7. [ ] If vulnerable populations are involved, are there additional protective measures?
8. [ ] Has the IRB review timeline been incorporated into the research project timeline?
