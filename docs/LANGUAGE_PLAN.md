# Language plan

## Required languages

- German (`de`)
- French (`fr`)
- Luxembourgish (`lb`)
- English (`en`)

Presidio's NLP engine and recognizers must be configured per language. German,
French and English may start with suitable local spaCy/Stanza models plus rule
recognizers. Luxembourgish requires an explicit tokenizer/NER decision and
custom recognizers; it must remain fail-closed until its synthetic recall suite
passes. Language fallback is forbidden.

Each language needs synthetic cases for:

- person and organization names;
- local and foreign places;
- phone, email, URL, IBAN and identifiers;
- dates, ages, kinship and occupations;
- code-switching and spelling variation;
- indirect identification and rare-event combinations;
- safe non-PII controls to measure destructive over-redaction.

