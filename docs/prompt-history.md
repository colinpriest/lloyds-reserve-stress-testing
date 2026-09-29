# Prompt history: which prompt governed the committed extraction

> **Generated file — do not edit.** Written by `scripts/prompt_history.py` from the committed response caches and records.

The extraction prompt in `test_gemini.py` is at version **2.13**. The versions since the review of 10 September 2026, from `pdf_extraction/spec/prompt_versions.json`:

- **2.11** (2026-09-10): One business-mix hierarchy; claims-incurred identity corrected; loss-ratio route requires underwriting-year premiums
- **2.12** (2026-09-11): Withdrawn. Five corrections to the extraction instructions, run over part of the corpus and superseded by 2.13 in the same round *Amended 2026-09-13:* R164, described here as the fix, was reverted by R193 on 13 September 2026 (owner's decision): the sign veto applies whatever the triangle's shape. 73 records carried a figure only because of R164, and where they were checked the models were right; 3010/2022's provisions note prints 146,569 (GBP000), which both models read, against the triangle's -10.9m. The prompt text of this version is unchanged. Evidence: pdf_extraction/audit/r193_sign_veto_restored.json.
- **2.13** (2026-09-11): The 2.12 corrections, restated after the override gate was fixed, and validated on known-answer records before any corpus run *Amended 2026-09-13:* R164, described here as the fix, was reverted by R193 on 13 September 2026 (owner's decision): the sign veto applies whatever the triangle's shape. 73 records carried a figure only because of R164, and where they were checked the models were right; 3010/2022's provisions note prints 146,569 (GBP000), which both models read, against the triangle's -10.9m. The prompt text of this version is unchanged. Evidence: pdf_extraction/audit/r193_sign_veto_restored.json.

## What the committed responses were produced under

| Prompt version | Cached responses |
|---|---:|
| unversioned | 77 |
| 2.6 | 738 |
| 2.7 | 20 |
| 2.8 | 118 |
| 2.9 | 28 |
| 2.10 | 1,695 |
| 2.12 | 1,040 |
| 2.13 | 2,109 |

5,825 cached responses cover 1,021 syndicate-years; the corpus holds 1,065 records. The newest version any cache carries is **2.13**, and 2,109 caches were produced under the current version. 1,055 records were written under the current version 2.13; the other 10 were written under an older version: syndicate_1100_2024 (2.6), syndicate_2357_2014 (2.9), syndicate_2689_2017 (2.10), syndicate_2689_2018 (2.10), syndicate_2786_2016 (2.10), syndicate_2786_2017 (2.10), syndicate_2988_2017 (2.10), syndicate_2988_2018 (2.10), syndicate_3268_2018 (2.10), syndicate_3268_2019 (2.10). Bringing those to the current version needs fresh paid inference.

## Which records the changed routes touched

- **Business mix.** Since round 54 the premium mix is read from the annual segmental table by the deterministic pass. Since round 58 that mix is admitted only when its classes sum, within 2%, to a gross premiums written total one of the models read -- an independent reading, not the same parse's own sum (`_lob_override_gate`) -- and the analysis loader reconciles again, within the larger of 2% and 0.2m, against a total another reader gave (`mix_reconciles`). Round 54's check compared the classes with the record's own premium within 10%, and the extraction had written that parse's class sum into that total, so a partial table reconciled with itself. The prompt's conflicting mix instructions therefore governed only the model's fallback mix.
- **Claims incurred.** The corrected sentence explains what not to use; it changes no extracted value.
- **Loss-ratio route.** 37 record(s) mention a loss ratio in a model's data-quality notes, in any context; 3 of them carry a note that also mentions an approximation or a total premium (syndicate_2010_2014, syndicate_2623_2022, syndicate_2988_2023), the records where the old fallback could have substituted total premium for underwriting-year premiums; 4 record(s) had the deterministic loss-ratio fallback applied at managed or group level (syndicate_3622_2020, syndicate_3622_2021, syndicate_3622_2022, syndicate_6107_2022). Every record named here was written under the current version 2.13.

## Replay

Offline replay (`--offline`) serves a cache miss at the current version from the committed entry for the same model, syndicate and year at the newest cached version (`_llm_cache_by_meta`), and records that version in `_served_from`. No committed model response carries one, so no committed record rests on a response served from another version's cache.

