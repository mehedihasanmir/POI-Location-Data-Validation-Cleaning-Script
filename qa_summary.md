# POI Data QA Summary

**Input file:** `data/dhanmondi_poi_raw.csv`
**Total records processed:** 40

| Check                          | Issues found | % of dataset |
|---------------------------------|-------------:|-------------:|
| Duplicate POI pairs             | 5 | 12.5% |
| Records with missing fields     | 18 | 45.0% |
| Naming/address inconsistencies  | 11 | 27.5% |
| Category mismatches             | 5 | 12.5% |

**Records removed after deduplication:** 5
**Final cleaned dataset size:** 35 records (12.5% reduction)

## What this catches
- **Duplicates** — same POI logged twice by different field agents or from OSM import overlap,
  detected via GPS proximity (< 60m) + fuzzy name matching.
- **Missing fields** — records missing address, phone, or category, which block map search/routing quality.
- **Naming inconsistency** — inconsistent abbreviations (Rd. vs Road, R/A vs Residential Area) that
  hurt address search/geocoding reliability.
- **Category mismatch** — POIs whose name implies one category (e.g. "Hospital") but tagged as another
  (e.g. "restaurant"), which breaks category-based search and filtering.

## Suggested next steps
1. Route flagged duplicates back to field team for on-ground re-verification before merging.
2. Auto-apply naming standardization rules at data-entry time (form validation) to prevent recurrence.
3. Build a category-keyword validation rule into the field app so mismatches are caught at collection time.
