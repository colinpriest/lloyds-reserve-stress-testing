#!/usr/bin/env python3
"""Analyze reserve strengthening movements for stress testing."""

import json
from collections import defaultdict

data = json.load(open('results/combined/unified_corpus.json'))

# Filter to strengthenings only
strengthenings = [m for m in data['movements'] if m.get('direction') == 'strengthening']

print(f"Total strengthenings: {len(strengthenings)}")
print(f"With specific events: {len([m for m in strengthenings if m.get('specific_events')])}")
print(f"With narrative: {len([m for m in strengthenings if m.get('standardized_narrative')])}")

# Cause distribution for strengthenings
print("\n=== Causes of Strengthening ===\n")
cause_counts = defaultdict(int)
for m in strengthenings:
    for cause in m.get('primary_causes', []):
        cause_counts[cause] += 1

for cause, count in sorted(cause_counts.items(), key=lambda x: -x[1]):
    print(f"  {cause}: {count}")

# LOB distribution for strengthenings
print("\n=== Strengthenings by LOB ===\n")
lob_counts = defaultdict(int)
for m in strengthenings:
    lob_counts[m.get('line_of_business', 'Unknown')] += 1

for lob, count in sorted(lob_counts.items(), key=lambda x: -x[1]):
    print(f"  {lob}: {count}")

# Year distribution
print("\n=== Strengthenings by Year ===\n")
year_counts = defaultdict(int)
for m in strengthenings:
    year_counts[m.get('year', 0)] += 1

for year, count in sorted(year_counts.items()):
    print(f"  {year}: {count}")

# Sample rich strengthening narratives
print("\n=== Sample Strengthenings with Specific Events ===\n")
count = 0
for m in strengthenings:
    if m.get('specific_events'):
        print(f"Syndicate: {m.get('syndicate')}")
        print(f"Year: {m.get('year')}")
        print(f"LOB: {m.get('line_of_business')}")
        print(f"Amount: £{m.get('amount_gbp_m')}m / ${m.get('amount_usd_m')}m")
        print(f"Causes: {m.get('primary_causes')}")
        print(f"Events: {m.get('specific_events')}")
        print(f"Narrative: {m.get('standardized_narrative')}")
        print("-" * 60)
        count += 1
        if count >= 10:
            break

# Sample generic "Adverse claims development" to see if narrative has more detail
print("\n=== Sample 'Adverse claims development' Strengthenings ===\n")
count = 0
for m in strengthenings:
    if 'Adverse claims development' in m.get('primary_causes', []) and not m.get('specific_events'):
        print(f"Syndicate: {m.get('syndicate')}")
        print(f"Year: {m.get('year')}")
        print(f"LOB: {m.get('line_of_business')}")
        print(f"Causes: {m.get('primary_causes')}")
        print(f"Narrative: {m.get('standardized_narrative')}")
        print("-" * 60)
        count += 1
        if count >= 5:
            break