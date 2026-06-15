import argparse
import json
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from charts.artist_metadata import artist_country
from charts.master_dataset import MONTHS, load_master_workbook


def compact_country(artist_name):
    metadata = artist_country(artist_name)
    return {"cc": metadata[1] if metadata else ""}


def compact_combined(row):
    result = {
        "r": int(row["Rank"]),
        "t": str(row["Title"]),
        "a": str(row["Primary_Artist"]),
        "fa": str(row["Featured_Artists"] or ""),
        "p": int(row["Display_Points"]),
        "rp": int(row["Combined_Points_Raw"]),
        "pl": f"{int(row['Platforms'])}/{int(row['Platforms_Max'])}",
        "w": int(row["Weeks"]),
        "y": int(row["Release_Year"]) if row["Release_Year"] is not None else None,
        "c": str(row["Confidence"] or ""),
    }
    result.update(compact_country(row["Primary_Artist"]))
    return result


def compact_platform(row):
    primary_artist = str(row.get("Primary_Artist") or row["Artist"])
    result = {
        "r": int(row["Rank"]),
        "t": str(row["Title"]),
        "a": primary_artist,
        "fa": str(row.get("Featured_Artists") or ""),
        "p": int(row["Points"]),
        "w": int(row["Weeks"]),
    }
    result.update(compact_country(primary_artist))
    return result


def build_frontend_data(data):
    full = {}
    for chart_type in ("singles", "albums"):
        combined = {month: [] for month in MONTHS}
        platforms = {}

        for row in data[chart_type]["combined"]:
            combined[row["Month"]].append(compact_combined(row))

        for row in data[chart_type]["platforms"]:
            platform = str(row["Platform"]).upper()
            platforms.setdefault(platform, {month: [] for month in MONTHS})
            platforms[platform][row["Month"]].append(compact_platform(row))

        full[chart_type] = {"combined": combined, "platforms": platforms}
    return full


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("workbook", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    data = load_master_workbook(args.workbook)
    full = build_frontend_data(data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "// Generated from Ngoma_Charts_MASTER.xlsx. Do not edit chart rows by hand.\n"
        f"export const MONTHS = {json.dumps(MONTHS, ensure_ascii=False)};\n"
        f"export const FULL = {json.dumps(full, ensure_ascii=False, separators=(',', ':'))};\n",
        encoding="utf-8",
    )
    print(f"Wrote {args.output} from {args.workbook}")


if __name__ == "__main__":
    main()
