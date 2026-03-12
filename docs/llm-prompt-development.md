# LLM Prompt Development Note

## Initial Design Intent

Four distinct LLM roles were defined: (i) Perplexity for source discovery, returning URLs with brief descriptions; (ii) ChatGPT for market commentary standardisation, extracting reserve movements as direction/percentage/amount triples with causal factor classification; (iii) ChatGPT for syndicate report summarisation, parsing individual annual report PDFs into structured JSON with line-of-business breakdowns; and (iv) ChatGPT for synthetic scenario generation, producing plausible stress narratives calibrated to specific severity and portfolio-complexity cells derived from a fitted GPD tail model.

## Errors Observed in Trial Runs

Early prompt iterations exhibited recurring errors in five areas:

1. **Reserve-base confusion.** The model conflated prior-year development as a percentage of net earned premium (market commentary) with PYD as a percentage of opening reserves (syndicate reports and synthetic scenarios). Severity figures were therefore inconsistent across pipeline stages.

2. **Generic causal attribution.** When source text contained named events (e.g., Hurricane Harvey, a mining landslide, or an RITC transaction), the model frequently defaulted to generic labels such as "Adverse claims development" rather than extracting the specific loss.

3. **LoB taxonomy drift.** Generated outputs used ad-hoc segment names from the source documents (e.g., "treaty property cat", "offshore energy") rather than the 12-class study taxonomy, making downstream aggregation unreliable.

4. **Table-parsing failures.** Syndicate reports that presented reserve movements in tabular form (e.g., "Marine GBP 14.9m, Property GBP 14.9m, Energy GBP 11.4m") were often summarised as a single aggregate movement, discarding the per-class breakdown.

5. **Temporal leakage in synthetic scenarios.** Generated narratives referenced specific calendar years (e.g., "In 2023, a Category 5 hurricane..."), anchoring supposedly forward-looking stress scenarios to historical dates and undermining their use as hypothetical projections.

## Revisions Made

Prompts were refined iteratively across several dimensions:

- **Two-stage syndicate extraction.** A keyword-detection pass now precedes the LLM call. When specific event names (catastrophes, transactions, named losses) are found in the source text, they are injected into the prompt as mandatory extraction targets, and the model must populate a `keyword_disposition` field accounting for every keyword&mdash;either linking it to a reserve movement or explaining why it is not reserve-related.

- **Explicit reserve-base specification.** Each prompt now states the denominator unambiguously: market prompts request "% of net earned premium", while syndicate and synthetic-generation prompts request "% of opening reserves". The severity metric used in the GPD tail model is defined inline as PYD / Opening Reserves.

- **Strict LoB mapping with enumerated taxonomy.** All prompts list the 12 permissible Lloyd's lines of business by exact name and provide parenthetical synonyms (e.g., "Marine (marine hull, cargo, specie, war, transport)"). The model is instructed to map source segment labels to the study taxonomy only when the disclosure supports an unambiguous correspondence, and to use "Aggregate" only when no breakdown is available.

- **Table-parsing directives.** Prompts now include explicit instructions to parse segment tables row by row, extracting each line of business as a separate movement with its own amount and direction.

- **Temporal controls for synthetic generation.** Generation prompts forbid specific calendar years and require hypothetical, forward-looking language (e.g., "A major hurricane strikes the US Gulf Coast..." rather than "Hurricane in 2024..."). Relative temporal references ("recent accident years", "older long-tail years") are permitted.

- **Few-shot examples.** Both syndicate and synthetic-generation prompts include worked examples demonstrating correct LoB mapping, severity calibration, and the expected relationship between portfolio complexity and diversification benefit.

## Final Prompt Architecture

The final prompts enforce a layered validation strategy: keyword pre-screening ensures specific events are not lost to generic summarisation; strict enum constraints on direction, confidence, and causal categories prevent taxonomy drift; severity bounds and complexity-score definitions are stated inline to eliminate base-rate ambiguity; and a mandatory `data_quality_notes` field captures extraction caveats so that downstream consumers can assess reliability without re-reading the source text.
