import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from charts.artist_metadata import artist_country
from charts.master_dataset import (
    MONTHS,
    apply_merge_canonicalization,
    load_master_workbook,
    load_merge_pairs,
)

DEFAULT_MERGE_WORKBOOK = BACKEND_ROOT / "Data" / "ngoma_duplicate_releases_final_merge_ready.xlsx"


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
    rank = int(row["Rank"])
    result = {
        "r": rank,
        "t": str(row["Title"]),
        "a": primary_artist,
        "fa": str(row.get("Featured_Artists") or ""),
        "p": 51 - rank if 1 <= rank <= 50 else 0,
        "rp": int(row["Points"]),
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
    parser = argparse.ArgumentParser(
        description=(
            "Export chartData.js from the master workbook. "
            "Automatically applies the duplicate-release merge workbook when present."
        )
    )
    parser.add_argument("workbook", type=Path, help="Path to Ngoma_Charts_MASTER.xlsx")
    parser.add_argument("output", type=Path, help="Destination chartData.js path")
    parser.add_argument(
        "--merge-workbook",
        type=Path,
        default=DEFAULT_MERGE_WORKBOOK,
        metavar="XLSX",
        help=(
            "Path to the duplicate-release merge workbook "
            f"(default: {DEFAULT_MERGE_WORKBOOK.relative_to(BACKEND_ROOT)}). "
            "Auto-applied when the file exists."
        ),
    )
    parser.add_argument(
        "--no-merge",
        action="store_true",
        help="Skip merge-workbook canonicalization.",
    )
    args = parser.parse_args()

    data = load_master_workbook(args.workbook)

    merge_applied = False
    if not args.no_merge:
        merge_path = Path(args.merge_workbook)
        if merge_path.exists():
            merge_pairs = load_merge_pairs(merge_path)
            if merge_pairs:
                data = apply_merge_canonicalization(data, merge_pairs)
                print(f"Applied {len(merge_pairs)} merge pairs from {merge_path.name}")
                merge_applied = True
        else:
            print(f"Merge workbook not found at {merge_path}, skipping canonicalization.")

    header_comment = (
        "// Generated from Ngoma_Charts_MASTER.xlsx + duplicate-release merge workbook."
        if merge_applied
        else "// Generated from Ngoma_Charts_MASTER.xlsx."
    )
    header_comment += " Do not edit chart rows by hand.\n"

    full = build_frontend_data(data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        header_comment
        + f"export const MONTHS = {json.dumps(MONTHS, ensure_ascii=False)};\n"
        + f"export const FULL = {json.dumps(full, ensure_ascii=False, separators=(',', ':'))};\n",
        encoding="utf-8",
    )
    print(f"Wrote {args.output} from {args.workbook}")


if __name__ == "__main__":
    main()
