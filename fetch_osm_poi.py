"""
fetch_osm_poi.py
-----------------
Pulls real POI data from OpenStreetMap via the Overpass API for a given
bounding box and saves it in the same schema used by poi_qa.py.

Run this locally (it needs internet access to overpass-api.de, which is not
reachable from this sandboxed environment):

    pip install requests pandas
    python fetch_osm_poi.py --area dhanmondi

This will overwrite data/dhanmondi_poi_raw.csv with live OSM data. Note real
OSM data is usually cleaner than field-collected data, so for QA-testing
purposes you may want to keep using the synthetic dataset (which has
deliberately injected duplicates/errors), or merge OSM data with your own
field survey CSV to simulate the real workflow: field team collects -> you
cross-check against OSM as a reference source.
"""

import argparse
import csv

import requests

# Rough bounding boxes: (south, west, north, east)
AREAS = {
    "dhanmondi": (23.7350, 90.3650, 23.7550, 90.3850),
    "gulshan": (23.7750, 90.4050, 23.8050, 90.4250),
}

OVERPASS_URL = "https://overpass-api.de/api/interpreter"


def build_query(bbox):
    south, west, north, east = bbox
    return f"""
    [out:json][timeout:60];
    (
      node["amenity"]({south},{west},{north},{east});
      node["shop"]({south},{west},{north},{east});
    );
    out body;
    """


def fetch(area):
    bbox = AREAS[area]
    query = build_query(bbox)
    resp = requests.post(OVERPASS_URL, data={"data": query}, timeout=90)
    resp.raise_for_status()
    return resp.json()["elements"]


def to_rows(elements):
    rows = []
    for i, el in enumerate(elements, start=1):
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name:
            continue  # skip unnamed nodes, not useful as POIs
        category = tags.get("amenity") or tags.get("shop") or "unknown"
        address_parts = [
            tags.get("addr:housenumber"),
            tags.get("addr:street"),
            tags.get("addr:area") or tags.get("addr:suburb"),
        ]
        address = ", ".join(p for p in address_parts if p)
        rows.append({
            "poi_id": f"OSM{i:04d}",
            "name": name,
            "category": category,
            "address": address,
            "phone": tags.get("phone", ""),
            "latitude": el.get("lat"),
            "longitude": el.get("lon"),
            "source": "osm_live",
        })
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--area", choices=AREAS.keys(), default="dhanmondi")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    output_path = args.output or f"data/{args.area}_poi_raw.csv"
    elements = fetch(args.area)
    rows = to_rows(elements)

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "poi_id", "name", "category", "address", "phone",
            "latitude", "longitude", "source",
        ])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Saved {len(rows)} POIs to {output_path}")
