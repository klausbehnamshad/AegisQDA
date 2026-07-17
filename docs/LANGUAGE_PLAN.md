# Language plan

## Required languages

- German (`de`)
- French (`fr`)
- English (`en`)

German, French and English use installed local spaCy 3.8 large NER packages
(`de_core_news_lg`, `fr_core_news_lg`, `en_core_web_lg`) together with the
versioned AegisQDA recognizers. Their curated synthetic suite is a bounded
acceptance check, not a general recall claim.

## Optional language

- Luxembourgish (`lb`)

Luxembourgish has a synthetic rule fixture but no approved local NER strategy.
It remains blocked per run and does not block readiness for the three required
languages. Language fallback is forbidden.

Each language needs synthetic cases for:

- person and organization names;
- local and foreign places;
- phone, email, URL, IBAN and identifiers;
- dates, ages, kinship and occupations;
- code-switching and spelling variation;
- indirect identification and rare-event combinations;
- safe non-PII controls to measure destructive over-redaction.
