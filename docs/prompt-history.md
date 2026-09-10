# Prompt history: which prompt governed the committed extraction

> **Generated file — do not edit.** Written by `scripts/prompt_history.py` from the committed response caches and records.

The extraction prompt in `test_gemini.py` is at version **2.11**. The review of 10 September 2026 (T02) found three defects in the prompt as it stood at 2.10 and earlier: it asked for the regulatory segmental classes, forbade the divisional breakdown and then preferred divisional totals; it defined gross claims incurred with premiums earned; and its loss-ratio route let total premium stand in for missing underwriting-year premiums. Version 2.11 states one business-mix hierarchy (the segmental note; the divisional summary only when there is none; never merged), the claims-incurred identity (paid claims plus the change in the gross claims provision), and a loss-ratio route that returns null without underwriting-year premiums.

## What the committed responses were produced under

| Prompt version | Cached responses |
|---|---:|
| unversioned | 76 |
| 2.6 | 738 |
| 2.7 | 20 |
| 2.8 | 118 |
| 2.9 | 28 |
| 2.10 | 1,695 |

2,675 cached responses cover 1,006 syndicate-years; the corpus holds 1,065 records. The newest version any cache carries is **2.10**; **0** caches were produced under the current version 2.11. Every committed record therefore rests on responses produced under the old prompt rules.

## Which records the changed routes touched

- **Business mix.** Since round 54 the premium mix is read from the annual segmental table by the deterministic pass, and a model's mix is admitted only when its classes reconcile with the record's own premium within 10% (`_parse_nutrient_lob`, the loader's reconciliation in the analysis repository). The prompt's conflicting mix instructions therefore governed only the model's fallback mix.
- **Claims incurred.** The corrected sentence explains what not to use; it changes no extracted value.
- **Loss-ratio route.** 32 record(s) mention a loss ratio in a model's data-quality notes, in any context; 0 of them carry a note that also mentions an approximation or a total premium, the records where the old fallback could have substituted total premium for underwriting-year premiums; 8 record(s) had the deterministic loss-ratio fallback applied at managed or group level (syndicate_2623_2016, syndicate_2623_2017, syndicate_2623_2021, syndicate_2623_2022, syndicate_3622_2020, syndicate_3622_2021, syndicate_3622_2022, syndicate_5623_2022). A record whose adopted figure rests on the loss-ratio route can be regenerated only by fresh model inference under version 2.11, which needs the source reports and paid API access.

## Replay

Offline replay (`--offline`) serves a cache miss at the current version from the committed entry for the same model, syndicate and year at the newest cached version (`_llm_cache_by_meta`), and records that version in `_served_from`; so a replayed record is reproducible and still carries the old prompt's responses. No record has been described as revalidated under version 2.11.

