from pathlib import Path
import math
import re
from difflib import SequenceMatcher

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
import streamlit as st

import warnings
warnings.filterwarnings("ignore")


DUPLICATE_DISTANCE_METERS = 60
DUPLICATE_NAME_SIMILARITY = 0.55
REQUIRED_FIELDS = ["address", "phone", "category"]

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

ADDRESS_STANDARDIZATION = [
    (r"\bRd\.?\b", "Road"),
    (r"\bR/A\b", "Residential Area"),
    (r"\bNo\.?\b", "No"),
    (r"\bHouse-\s*", "House "),
    (r"\s+", " "),
]

GENERIC_NAME_WORDS = {
    "ltd",
    "limited",
    "branch",
    "store",
    "shop",
    "dhanmondi",
    "bank",
    "school",
    "pharmacy",
    "hospital",
    "restaurant",
    "mosque",
    "centre",
    "center",
    "college",
}


def haversine_meters(lat1, lon1, lat2, lon2):
    radius = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def normalize_name(name):
    name = str(name).lower()
    name = re.sub(r"[.,&\-]", " ", name)
    tokens = [token for token in name.split() if token not in GENERIC_NAME_WORDS]
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
    lname = str(name).lower()
    for keyword, category in CATEGORY_KEYWORDS.items():
        if keyword in lname:
            return category
    return None


def find_duplicates(df):
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
                flags.append(
                    {
                        "poi_id_1": a["poi_id"],
                        "name_1": a["name"],
                        "poi_id_2": b["poi_id"],
                        "name_2": b["name"],
                        "distance_meters": round(dist, 1),
                        "name_similarity": round(sim, 2),
                        "suggested_action": "merge / keep most complete record",
                    }
                )
    return pd.DataFrame(flags)


def find_missing_fields(df):
    flags = []
    for _, row in df.iterrows():
        missing = [field for field in REQUIRED_FIELDS if pd.isna(row.get(field)) or str(row.get(field)).strip() == ""]
        if missing:
            flags.append(
                {
                    "poi_id": row["poi_id"],
                    "name": row["name"],
                    "missing_fields": ", ".join(missing),
                }
            )
    return pd.DataFrame(flags)


def find_naming_inconsistencies(df):
    flags = []
    for _, row in df.iterrows():
        addr = row.get("address")
        std = standardize_address(addr)
        if pd.notna(addr) and std != addr:
            flags.append(
                {
                    "poi_id": row["poi_id"],
                    "name": row["name"],
                    "original_address": addr,
                    "standardized_address": std,
                }
            )
    return pd.DataFrame(flags)


def find_category_mismatches(df):
    flags = []
    for _, row in df.iterrows():
        expected = expected_category(row["name"])
        actual = str(row.get("category", "")).strip().lower()
        if expected and expected != actual:
            flags.append(
                {
                    "poi_id": row["poi_id"],
                    "name": row["name"],
                    "tagged_category": row.get("category"),
                    "expected_category": expected,
                }
            )
    return pd.DataFrame(flags)


def run_qa(df):
    total = len(df)

    dup_df = find_duplicates(df)
    missing_df = find_missing_fields(df)
    naming_df = find_naming_inconsistencies(df)
    category_df = find_category_mismatches(df)

    cleaned = df.copy()
    if "address" in cleaned.columns:
        cleaned["address"] = cleaned["address"].apply(standardize_address)

    drop_ids = set()
    for _, row in dup_df.iterrows():
        rec1 = df[df.poi_id == row.poi_id_1].iloc[0]
        rec2 = df[df.poi_id == row.poi_id_2].iloc[0]
        completeness1 = sum(
            pd.notna(rec1.get(field)) and str(rec1.get(field)).strip() != "" for field in REQUIRED_FIELDS
        )
        completeness2 = sum(
            pd.notna(rec2.get(field)) and str(rec2.get(field)).strip() != "" for field in REQUIRED_FIELDS
        )
        drop_ids.add(row.poi_id_2 if completeness1 >= completeness2 else row.poi_id_1)

    if not dup_df.empty:
        cleaned = cleaned[~cleaned.poi_id.isin(drop_ids)]

    summary_df = pd.DataFrame(
        {
            "check": [
                "Duplicate POI pairs",
                "Records with missing fields",
                "Naming/address inconsistencies",
                "Category mismatches",
            ],
            "issues_found": [len(dup_df), len(missing_df), len(naming_df), len(category_df)],
        }
    )
    summary_df["pct_of_dataset"] = 0 if total == 0 else (summary_df["issues_found"] / total * 100).round(1)

    summary_text = f"""# POI Data QA Summary

## Overview

**Total records processed:** {total}
**Records removed after deduplication:** {len(drop_ids)}
**Final cleaned dataset size:** {len(cleaned)} records

## Requirement validation

| Requested requirement | Implemented in this project | Status |
|---|---|---|
| Collect POI data from OpenStreetMap or a compatible source | `fetch_osm_poi.py` collects OSM data; the Streamlit app also accepts an uploaded CSV in the same schema | Done |
| Detect duplicate POIs by similar name and nearby coordinates | Haversine distance plus fuzzy name matching in `find_duplicates()` | Done |
| Flag missing fields such as address, category, and phone | `find_missing_fields()` checks required columns | Done |
| Detect naming inconsistency such as Rd. vs Road or Dhanmondi variants | `standardize_address()` and `find_naming_inconsistencies()` | Done |
| Flag category mismatch such as a restaurant tagged as hospital | `expected_category()` and `find_category_mismatches()` | Done |
| Produce a cleaning / QA workflow for deduplication, formatting, and validation | `run_qa()` returns cleaned data plus report tables | Done |
| Support the Data Acquisition Engineer responsibility of reviewing location, category, and naming accuracy | Directly covered by the four QA checks above | Done |

## QA results

| Check | Issues found | % of dataset |
|---|---:|---:|
| Duplicate POI pairs | {len(dup_df)} | {summary_df.iloc[0]['pct_of_dataset']}% |
| Records with missing fields | {len(missing_df)} | {summary_df.iloc[1]['pct_of_dataset']}% |
| Naming/address inconsistencies | {len(naming_df)} | {summary_df.iloc[2]['pct_of_dataset']}% |
| Category mismatches | {len(category_df)} | {summary_df.iloc[3]['pct_of_dataset']}% |

## What each check catches

- **Duplicates** — same POI logged twice by different field agents or from OSM import overlap, detected via GPS proximity (< {DUPLICATE_DISTANCE_METERS}m) and fuzzy name matching.
- **Missing fields** — records missing address, phone, or category, which block search, routing, and downstream data completeness checks.
- **Naming inconsistency** — inconsistent abbreviations such as Rd. vs Road or R/A vs Residential Area that hurt address search and geocoding reliability.
- **Category mismatch** — POIs whose name implies one category but are tagged as another, which breaks category-based search and filtering.

## Suggested next steps

1. Route flagged duplicates back to the field team for re-verification before merging records.
2. Apply naming standardization rules at data-entry time to prevent inconsistent address formats.
3. Add category validation to the collection form so mismatches are caught before data is finalized.
"""

    return {
        "input_df": df,
        "summary": summary_df,
        "duplicates": dup_df,
        "missing": missing_df,
        "naming": naming_df,
        "category": category_df,
        "cleaned": cleaned,
        "summary_text": summary_text,
    }


def df_to_csv_bytes(df):
    return df.to_csv(index=False).encode("utf-8")


def build_visualizations(results):
    input_df = results["input_df"].copy()
    summary_df = results["summary"].copy()
    duplicates_df = results["duplicates"].copy()
    missing_df = results["missing"].copy()
    naming_df = results["naming"].copy()
    category_df = results["category"].copy()

    sns.set_theme(style="whitegrid", context="talk")

    figures = {}

    fig, ax = plt.subplots(figsize=(10, 5))
    summary_plot = summary_df.sort_values("issues_found", ascending=False)
    sns.barplot(data=summary_plot, x="issues_found", y="check", ax=ax, palette="viridis")
    ax.set_title("QA issue count by check")
    ax.set_xlabel("issues found")
    ax.set_ylabel("")
    figures["qa_summary"] = fig

    fig, ax = plt.subplots(figsize=(10, 5))
    category_counts = (
        input_df["category"].fillna("missing").astype(str).str.strip().replace("", "missing").value_counts().reset_index()
    )
    category_counts.columns = ["category", "count"]
    sns.barplot(data=category_counts, x="count", y="category", ax=ax, palette="magma")
    ax.set_title("POI volume by category")
    ax.set_xlabel("records")
    ax.set_ylabel("")
    figures["category_distribution"] = fig

    fig, ax = plt.subplots(figsize=(10, 5))
    missing_breakdown = pd.DataFrame(
        {"field": REQUIRED_FIELDS, "count": [missing_df["missing_fields"].str.contains(field, na=False).sum() for field in REQUIRED_FIELDS]}
    )
    sns.barplot(data=missing_breakdown, x="count", y="field", ax=ax, palette="rocket")
    ax.set_title("Missing field counts")
    ax.set_xlabel("records flagged")
    ax.set_ylabel("")
    figures["missing_fields"] = fig

    fig, ax = plt.subplots(figsize=(10, 5))
    if duplicates_df.empty:
        ax.text(0.5, 0.5, "No duplicate pairs detected", ha="center", va="center", fontsize=14)
        ax.set_axis_off()
    else:
        sns.scatterplot(
            data=duplicates_df,
            x="distance_meters",
            y="name_similarity",
            hue="suggested_action",
            s=120,
            ax=ax,
        )
        ax.set_title("Duplicate pairs: distance vs name similarity")
        ax.set_xlabel("distance in meters")
        ax.set_ylabel("name similarity")
        ax.legend(loc="lower left", bbox_to_anchor=(1.02, 0))
    figures["duplicates"] = fig

    fig, ax = plt.subplots(figsize=(10, 6))
    spatial_df = input_df.dropna(subset=["latitude", "longitude"]).copy()
    if spatial_df.empty:
        ax.text(0.5, 0.5, "No coordinate data available", ha="center", va="center", fontsize=14)
        ax.set_axis_off()
    else:
        spatial_df["category_clean"] = spatial_df["category"].fillna("missing").astype(str).replace("", "missing")
        sns.scatterplot(
            data=spatial_df,
            x="longitude",
            y="latitude",
            hue="category_clean",
            palette="tab10",
            s=80,
            ax=ax,
        )
        ax.set_title("Spatial view of POIs")
        ax.set_xlabel("longitude")
        ax.set_ylabel("latitude")
        ax.legend(loc="lower left", bbox_to_anchor=(1.02, 0))
    figures["spatial"] = fig

    fig, ax = plt.subplots(figsize=(10, 5))
    naming_summary = pd.DataFrame(
        {
            "status": ["changed address", "no change detected"],
            "count": [len(naming_df), max(len(input_df) - len(naming_df), 0)],
        }
    )
    sns.barplot(data=naming_summary, x="count", y="status", ax=ax, palette="crest")
    ax.set_title("Naming and address standardization impact")
    ax.set_xlabel("records")
    ax.set_ylabel("")
    figures["naming"] = fig

    fig, ax = plt.subplots(figsize=(10, 5))
    if category_df.empty:
        ax.text(0.5, 0.5, "No category mismatches detected", ha="center", va="center", fontsize=14)
        ax.set_axis_off()
    else:
        category_plot = category_df["expected_category"].value_counts().reset_index()
        category_plot.columns = ["expected_category", "count"]
        sns.barplot(data=category_plot, x="count", y="expected_category", ax=ax, palette="cubehelix")
        ax.set_title("Category mismatches by expected category")
        ax.set_xlabel("records flagged")
        ax.set_ylabel("")
    figures["category_mismatch"] = fig

    return figures


st.set_page_config(page_title="POI QA Dashboard", layout="wide")
st.title("POI QA Dashboard")
st.caption("Review location accuracy, category accuracy, and naming consistency in one place.")

sample_path = Path(__file__).parent / "data" / "dhanmondi_poi_raw.csv"
source_mode = st.sidebar.radio("Input source", ["Sample dataset", "Upload CSV"], index=0)
uploaded_file = None
if source_mode == "Upload CSV":
    uploaded_file = st.sidebar.file_uploader("Choose a POI CSV", type=["csv"])

use_source = sample_path if source_mode == "Sample dataset" else uploaded_file

if use_source is None:
    st.info("Upload a CSV file to run the QA checks.")
    st.stop()

if source_mode == "Sample dataset":
    df = pd.read_csv(sample_path)
    st.sidebar.write(f"Sample file: {sample_path.name}")
else:
    df = pd.read_csv(uploaded_file)
    st.sidebar.write(f"Uploaded file: {uploaded_file.name}")

if df.empty:
    st.warning("The selected file has no rows.")
    st.stop()

results = run_qa(df)
summary_df = results["summary"]
issue_total = int(summary_df["issues_found"].sum())
top_issue_row = summary_df.sort_values("issues_found", ascending=False).iloc[0]

with st.container(border=True):
    intro_left, intro_right = st.columns([2, 1], vertical_alignment="center")
    with intro_left:
        st.markdown(
            """
            ### What this dashboard checks
            - duplicate POIs using proximity and fuzzy name matching
            - missing address, phone, and category fields
            - naming and address consistency
            - category mismatch against the POI name
            """
        )
    with intro_right:
        st.metric("total issues flagged", issue_total)
        st.caption(f"Most common issue: {top_issue_row['check']}")

with st.container(border=True):
    metric_cols = st.columns(5)
    metric_cols[0].metric("Records", len(results["input_df"]))
    metric_cols[1].metric("Duplicate pairs", len(results["duplicates"]))
    metric_cols[2].metric("Missing fields", len(results["missing"]))
    metric_cols[3].metric("Naming issues", len(results["naming"]))
    metric_cols[4].metric("Category mismatches", len(results["category"]))

summary_left, summary_right = st.columns([1.2, 1], gap="large")
with summary_left:
    with st.container(border=True):
        st.subheader("QA Summary")
        st.dataframe(summary_df, width="stretch", hide_index=True)
with summary_right:
    with st.container(border=True):
        st.subheader("Key observations")
        st.markdown(
            f"""
            - **Duplicate pairs:** {len(results['duplicates'])}
            - **Missing fields:** {len(results['missing'])}
            - **Naming issues:** {len(results['naming'])}
            - **Category mismatches:** {len(results['category'])}

            The summary table and charts below show where the current dataset needs the most attention.
            """
        )

with st.container(border=True):
    left, right = st.columns(2, gap="large")
    with left:
        st.download_button(
            "Download cleaned CSV",
            data=df_to_csv_bytes(results["cleaned"]),
            file_name="dhanmondi_poi_cleaned.csv" if source_mode == "Sample dataset" else "poi_cleaned.csv",
            mime="text/csv",
            width="stretch",
        )
    with right:
        st.download_button(
            "Download QA summary",
            data=results["summary_text"].encode("utf-8"),
            file_name="qa_summary.md",
            mime="text/markdown",
            width="stretch",
        )

with st.container(border=True):
    st.subheader("Detailed Findings")
    tabs = st.tabs(["Duplicates", "Missing Fields", "Naming", "Category", "Cleaned Data"])

    with tabs[0]:
        st.dataframe(results["duplicates"], width="stretch", hide_index=True)
    with tabs[1]:
        st.dataframe(results["missing"], width="stretch", hide_index=True)
    with tabs[2]:
        st.dataframe(results["naming"], width="stretch", hide_index=True)
    with tabs[3]:
        st.dataframe(results["category"], width="stretch", hide_index=True)
    with tabs[4]:
        st.dataframe(results["cleaned"], width="stretch", hide_index=True)

with st.container(border=True):
    st.subheader("Visual analytics")
    st.caption("These charts give a quick read on issue concentration, spatial spread, and classification quality.")
    figures = build_visualizations(results)
    viz_tabs = st.tabs(["Issue mix", "Category mix", "Missing fields", "Duplicates", "Spatial view", "Naming changes", "Category mismatch"])

    with viz_tabs[0]:
        st.pyplot(figures["qa_summary"], clear_figure=True)
    with viz_tabs[1]:
        st.pyplot(figures["category_distribution"], clear_figure=True)
    with viz_tabs[2]:
        st.pyplot(figures["missing_fields"], clear_figure=True)
    with viz_tabs[3]:
        st.pyplot(figures["duplicates"], clear_figure=True)
    with viz_tabs[4]:
        st.pyplot(figures["spatial"], clear_figure=True)
    with viz_tabs[5]:
        st.pyplot(figures["naming"], clear_figure=True)
    with viz_tabs[6]:
        st.pyplot(figures["category_mismatch"], clear_figure=True)

if source_mode == "Sample dataset":
    st.sidebar.divider()
    if st.sidebar.checkbox("Write sample outputs to disk", value=True):
        reports_dir = Path(__file__).parent / "reports"
        data_dir = Path(__file__).parent / "data"
        reports_dir.mkdir(parents=True, exist_ok=True)
        data_dir.mkdir(parents=True, exist_ok=True)
        results["duplicates"].to_csv(reports_dir / "duplicates_report.csv", index=False)
        results["missing"].to_csv(reports_dir / "missing_fields_report.csv", index=False)
        results["naming"].to_csv(reports_dir / "naming_inconsistency_report.csv", index=False)
        results["category"].to_csv(reports_dir / "category_mismatch_report.csv", index=False)
        results["cleaned"].to_csv(data_dir / "dhanmondi_poi_cleaned.csv", index=False)
        (Path(__file__).parent / "qa_summary.md").write_text(results["summary_text"], encoding="utf-8")
        st.sidebar.success("Outputs written to qa_summary.md, reports/, and data/.")
