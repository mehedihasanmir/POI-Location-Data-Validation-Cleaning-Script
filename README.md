# POI Data QA & Validation Pipeline

A field-data quality pipeline for location/map data, built to mirror the kind
of work a **Data Acquisition Engineer** does at a map/POI company: collecting
ground-level POI data, validating it, and automating cleanup so bad data
doesn't reach the map.

![POI Data QA & Validation](POI%20Data%20QA%20%26%20Validation.gif)

## Why this project

Field-collected POI data is messy in predictable ways:
- The same place gets logged twice by different field agents, with slightly
  different names or GPS coordinates.
- Agents skip fields under time pressure (no phone number, no address).
- Addresses get written inconsistently ("Rd." vs "Road", "R/A" vs full form),
  which breaks address search and geocoding.
- POIs get tagged into the wrong category (a pharmacy tagged as a hospital),
  which breaks category-based map search.

This pipeline catches all four issues automatically instead of relying on
manual review of every record.

## What it does

The notebook and Streamlit app run four checks over a raw POI CSV:

| Check | Method |
|---|---|
| **Duplicate detection** | GPS proximity (Haversine distance, <60m) combined with fuzzy name matching after stripping generic words (bank, road, dhanmondi, etc.) so it doesn't confuse two different banks on the same road for duplicates |
| **Missing fields** | Flags records missing address, phone, or category |
| **Naming/address standardization** | Normalizes abbreviations (Rd. → Road, R/A → Residential Area) and flags any record that changes, so inconsistent entries can be fixed at the source |
| **Category mismatch** | Keyword-based check, if a POI's name contains "Hospital" but it's tagged `restaurant`, it gets flagged |

It then produces a deduplicated, standardized cleaned dataset and a QA
summary report with error rates the kind of report a field QA lead would
hand to their manager.

## Results on the sample dataset

Ran against 40 synthetic-but-realistic Dhanmondi POI records (built to mimic
common field-collection errors):

| Check | Issues found | % of dataset |
|---|---:|---:|
| Duplicate POI pairs | 5 | 12.5% |
| Records with missing fields | 18 | 45.0% |
| Naming/address inconsistencies | 11 | 27.5% |
| Category mismatches | 5 | 12.5% |

**35 clean records** remained after deduplication (12.5% reduction from
merging duplicate entries).

Full report: [`qa_summary.md`](qa_summary.md)

## Project structure

```
poi-qa-project/
├── data/
│   ├── dhanmondi_poi_raw.csv       # sample input (synthetic, errors injected)
│   └── dhanmondi_poi_cleaned.csv   # output after running the pipeline
├── reports/
│   ├── duplicates_report.csv
│   ├── missing_fields_report.csv
│   ├── naming_inconsistency_report.csv
│   └── category_mismatch_report.csv
├── poi_qa.ipynb                    # notebook workflow for the QA pipeline
├── app.py                          # simple Streamlit UI for running the QA checks
├── fetch_osm_poi.py                # pulls live POI data from OpenStreetMap (Overpass API)
├── POI Data QA & Validation.gif    # project demo preview
└── README.md
```

## Running it

```bash
pip install pandas
python -m streamlit run app.py
```

To run the notebook version, open `poi_qa.ipynb` in VS Code and run the cells.

To test against real-world data instead of the synthetic sample, pull live
OSM data for an area:

```bash
pip install requests
python fetch_osm_poi.py --area dhanmondi
python -m streamlit run app.py
```

## A note on the sample data

The sample dataset is **synthetic but realistic** I hand-built it to
reflect the exact error patterns you see in real field-collected POI data
(duplicate entries from OSM-import + field-survey overlap, missing phone
numbers, inconsistent road-name abbreviations, mistagged categories). This
was necessary because live OSM data is comparatively clean and wouldn't
exercise all four QA checks meaningfully. `fetch_osm_poi.py` is included so
the pipeline can be pointed at live data or a real field-survey export.

## Known limitation / design tradeoff

Duplicate detection uses a fixed distance threshold (60m) and a fuzzy name
similarity cutoff (0.55) after removing generic terms. This is a precision/
recall tradeoff common to all real-world entity-resolution systems — tighter
thresholds miss true duplicates, looser ones create false positives that
waste field-team re-verification time. In production this would be tuned
against a labeled validation set and likely supplemented with a human review
step for borderline matches rather than fully automated merging.

## Relevance to the Data Acquisition Engineer role

This project directly covers the role's core responsibilities: validating
POIs for accuracy/completeness, reviewing location/category/naming accuracy,
writing automation scripts for cleaning/deduplication/QA, and producing data
quality reports for field progress and error tracking.
