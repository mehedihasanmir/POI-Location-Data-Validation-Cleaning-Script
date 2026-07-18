"""
POI Data Quality & Validation Pipeline
----------------------------------------
Simulates a real-world field-data QA workflow for a map/location-data company
(e.g. Barikoi). Takes raw, field-collected POI data (CSV) and runs automated
checks used to catch the most common errors in ground-collected POI data:

    1. Duplicate POI detection      (same place logged twice, slightly different name/coords)
    2. Missing critical fields      (address, phone, category)
    3. Naming / address standardization (Rd. vs Road, R/A vs Residential Area, etc.)
    4. Category mismatch            (name suggests one category, tagged as another)

Outputs:
    reports/duplicates_report.csv
    reports/missing_fields_report.csv
    reports/naming_inconsistency_report.csv
    reports/category_mismatch_report.csv
    reports/qa_summary.md
    data/dhanmondi_poi_cleaned.csv   (deduplicated + standardized dataset)

Usage:
    python poi_qa.py --input data/dhanmondi_poi_raw.csv
"""

import argparse
import math
import re
from difflib import SequenceMatcher

import pandas as pd

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DUPLICATE_DISTANCE_METERS = 60      # POIs closer than this are candidates for duplication
DUPLICATE_NAME_SIMILARITY = 0.55    # min normalized name similarity (0-1) to flag as duplicate

REQUIRED_FIELDS = ["address", "phone", "category"]

# name-keyword -> expected category. Used to catch mistagged POIs.
CATEGORY_KEYWORDS = {
    "hospital": "hospital",
    "clinic": "hospital",
    "diagnostic": "hospital",
    "pharmacy": "pharmacy",
    "medical store": "pharmacy",
    "medicine": "pharmacy",
    "bank": "bank",
    "atm": "bank",
    "restaurant": "restaurant",
    "kabab": "restaurant",
    "dine": "restaurant",
    "cafe": "restaurant",
    "mosque": "mosque",
    "masjid": "mosque",
    "school": "school",
    "college": "school",
}

# common raw -> standardized address token replacements
ADDRESS_STANDARDIZATION = [
    (r"\bRd\.?\b", "Road"),
    (r"\bR/A\b", "Residential Area"),
    (r"\bNo\.?\b", "No"),
    (r"\bHouse-\s*", "House "),
    (r"\s+", " "),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def haversine_meters(lat1, lon1, lat2, lon2):
    """Great-circle distance between two lat/lon points, in meters."""
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


GENERIC_NAME_WORDS = {
    "ltd", "limited", "branch", "store", "shop", "dhanmondi", "bank", "school",
    "pharmacy", "hospital", "restaurant", "mosque", "centre", "center", "college",
}


def normalize_name(name):
    """Lowercase, strip punctuation/generic words that cause false-positive matches."""
    name = str(name).lower()
    name = re.sub(r"[.,&\-]", " ", name)
    tokens = [t for t in name.split() if t not in GENERIC_NAME_WORDS]
    return " ".join(tokens).strip()


def name_similarity(a, b):
    return SequenceMatcher(None, normalize_name(a), normalize_name(b)).ratio()


def standardize_address(addr):
    if pd.isna(addr) or str(addr).strip() == "":
        return addr
    out = str(addr)
    for pattern, replacement in ADDRESS_STANDARDIZATION:
        out = re.sub(pattern, replacement, out)
    return out.strip()


def expected_category(name):
    """Guess the expected category from keywords found in the POI name."""
    lname = str(name).lower()
    for keyword, category in CATEGORY_KEYWORDS.items():
        if keyword in lname:
            return category
    return None


# ---------------------------------------------------------------------------
# QA checks
# ---------------------------------------------------------------------------

def find_duplicates(df):
    """Pairwise comparison: flag POIs that are geographically close AND have similar names."""
    flags = []
    seen_pairs = set()
    records = df.to_dict("records")

    for i in range(len(records)):
        for j in range(i + 1, len(records)):
            a, b = records[i], records[j]
            dist = haversine_meters(a["latitude"], a["longitude"], b["latitude"], b["longitude"])
            if dist > DUPLICATE_DISTANCE_METERS:
                continue
            sim = name_similarity(a["name"], b["name"])
            if sim >= DUPLICATE_NAME_SIMILARITY:
                pair_key = tuple(sorted([a["poi_id"], b["poi_id"]]))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                flags.append({
                    "poi_id_1": a["poi_id"], "name_1": a["name"],
                    "poi_id_2": b["poi_id"], "name_2": b["name"],
                    "distance_meters": round(dist, 1),
                    "name_similarity": round(sim, 2),
                    "suggested_action": "merge / keep most complete record",
                })
    return pd.DataFrame(flags)


def find_missing_fields(df):
    flags = []
    for _, row in df.iterrows():
        missing = [f for f in REQUIRED_FIELDS if pd.isna(row.get(f)) or str(row.get(f)).strip() == ""]
        if missing:
            flags.append({
                "poi_id": row["poi_id"],
                "name": row["name"],
                "missing_fields": ", ".join(missing),
            })
    return pd.DataFrame(flags)


def find_naming_inconsistencies(df):
    flags = []
    for _, row in df.iterrows():
        addr = row.get("address")
        std = standardize_address(addr)
        if pd.notna(addr) and std != addr:
            flags.append({
                "poi_id": row["poi_id"],
                "name": row["name"],
                "original_address": addr,
                "standardized_address": std,
            })
    return pd.DataFrame(flags)


def find_category_mismatches(df):
    flags = []
    for _, row in df.iterrows():
        expected = expected_category(row["name"])
        actual = str(row.get("category", "")).strip().lower()
        if expected and expected != actual:
            flags.append({
                "poi_id": row["poi_id"],
                "name": row["name"],
                "tagged_category": row.get("category"),
                "expected_category": expected,
            })
    return pd.DataFrame(flags)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_qa(input_path, reports_dir="reports", cleaned_output="data/dhanmondi_poi_cleaned.csv"):
    df = pd.read_csv(input_path)
    total = len(df)

    dup_df = find_duplicates(df)
    missing_df = find_missing_fields(df)
    naming_df = find_naming_inconsistencies(df)
    category_df = find_category_mismatches(df)

    dup_df.to_csv(f"{reports_dir}/duplicates_report.csv", index=False)
    missing_df.to_csv(f"{reports_dir}/missing_fields_report.csv", index=False)
    naming_df.to_csv(f"{reports_dir}/naming_inconsistency_report.csv", index=False)
    category_df.to_csv(f"{reports_dir}/category_mismatch_report.csv", index=False)

    # Build a cleaned dataset: standardize addresses, drop the second record
    # of each detected duplicate pair, keep the more complete one.
    cleaned = df.copy()
    cleaned["address"] = cleaned["address"].apply(standardize_address)

    drop_ids = set()
    for _, row in dup_df.iterrows():
        rec1 = df[df.poi_id == row.poi_id_1].iloc[0]
        rec2 = df[df.poi_id == row.poi_id_2].iloc[0]
        completeness1 = sum(pd.notna(rec1.get(f)) and str(rec1.get(f)).strip() != "" for f in REQUIRED_FIELDS)
        completeness2 = sum(pd.notna(rec2.get(f)) and str(rec2.get(f)).strip() != "" for f in REQUIRED_FIELDS)
        drop_ids.add(row.poi_id_2 if completeness1 >= completeness2 else row.poi_id_1)

    cleaned = cleaned[~cleaned.poi_id.isin(drop_ids)]
    cleaned.to_csv(cleaned_output, index=False)

    # Summary report
    summary = f"""# POI Data QA Summary

**Input file:** `{input_path}`
**Total records processed:** {total}

| Check                          | Issues found | % of dataset |
|---------------------------------|-------------:|-------------:|
| Duplicate POI pairs             | {len(dup_df)} | {len(dup_df) / total * 100:.1f}% |
| Records with missing fields     | {len(missing_df)} | {len(missing_df) / total * 100:.1f}% |
| Naming/address inconsistencies  | {len(naming_df)} | {len(naming_df) / total * 100:.1f}% |
| Category mismatches             | {len(category_df)} | {len(category_df) / total * 100:.1f}% |

**Records removed after deduplication:** {len(drop_ids)}
**Final cleaned dataset size:** {len(cleaned)} records ({len(drop_ids) / total * 100:.1f}% reduction)

## What this catches
- **Duplicates** — same POI logged twice by different field agents or from OSM import overlap,
  detected via GPS proximity (< {DUPLICATE_DISTANCE_METERS}m) + fuzzy name matching.
- **Missing fields** — records missing address, phone, or category, which block map search/routing quality.
- **Naming inconsistency** — inconsistent abbreviations (Rd. vs Road, R/A vs Residential Area) that
  hurt address search/geocoding reliability.
- **Category mismatch** — POIs whose name implies one category (e.g. "Hospital") but tagged as another
  (e.g. "restaurant"), which breaks category-based search and filtering.

## Suggested next steps
1. Route flagged duplicates back to field team for on-ground re-verification before merging.
2. Auto-apply naming standardization rules at data-entry time (form validation) to prevent recurrence.
3. Build a category-keyword validation rule into the field app so mismatches are caught at collection time.
"""
    with open(f"{reports_dir}/qa_summary.md", "w") as f:
        f.write(summary)

    print(summary)
    return {
        "duplicates": dup_df,
        "missing": missing_df,
        "naming": naming_df,
        "category": category_df,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="POI Data QA Pipeline")
    parser.add_argument("--input", default="data/dhanmondi_poi_raw.csv", help="Path to raw POI CSV")
    parser.add_argument("--reports-dir", default="reports", help="Directory to write QA reports")
    parser.add_argument("--cleaned-output", default="data/dhanmondi_poi_cleaned.csv", help="Path for cleaned CSV output")
    args = parser.parse_args()

    run_qa(args.input, args.reports_dir, args.cleaned_output)
