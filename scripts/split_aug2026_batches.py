import json

with open("scripts/new_top50_aug2026_report.json", encoding="utf-8") as f:
    report = json.load(f)

releases = report["releases"]
artists = report["artists"]

# Group releases by artist_id, keep artist's releases together
by_artist = {}
for rid, r in releases.items():
    by_artist.setdefault(r["artist_id"], []).append((rid, r))

# Weight = number of releases + 1 (for the artist row itself, if it needs research)
groups = list(by_artist.items())
groups.sort(key=lambda kv: -len(kv[1]))  # largest first for better bin-packing

NUM_BATCHES = 4
batches = [{"weight": 0, "artist_ids": []} for _ in range(NUM_BATCHES)]

for artist_id, rels in groups:
    weight = len(rels) + (1 if str(artist_id) in artists else 0)
    target = min(range(NUM_BATCHES), key=lambda i: batches[i]["weight"])
    batches[target]["weight"] += weight
    batches[target]["artist_ids"].append(artist_id)

for i, b in enumerate(batches, start=1):
    out = {"artists": {}, "releases": {}}
    for aid in b["artist_ids"]:
        if str(aid) in artists:
            out["artists"][str(aid)] = artists[str(aid)]
        for rid, r in by_artist[aid]:
            out["releases"][rid] = r
    path = f"scripts/aug2026_batch{i}_queue.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(path, "-> artists:", len(out["artists"]), "releases:", len(out["releases"]), "weight:", b["weight"])
