"""
Merge per-tag translation cache back into tag-group JSON output files.
"""
import json
from pathlib import Path
from config import TAG_GROUP_DIR, OUTPUT_DIR, CACHE_DIR


def load_all_cached() -> dict[str, dict]:
    """Load all cached translation results. Returns {tag_name: translation}."""
    cached = {}
    if not CACHE_DIR.exists():
        return cached
    for fpath in CACHE_DIR.glob("*.json"):
        if fpath.name == "progress.json":
            continue
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "tag" in data:
                cached[data["tag"]] = data
        except (json.JSONDecodeError, KeyError):
            pass
    return cached


def merge_one_group(group: dict, cached: dict[str, dict]) -> dict:
    """Attach translations to tags in a single group dict. Mutates and returns."""
    missing = 0
    for tag in group.get("tags", []):
        trans = cached.get(tag["name"])
        if trans:
            tag["tag_cn"] = trans.get("tag_cn", "")
            tag["confidence"] = trans.get("confidence", "")
            tag["tag_cn_long"] = trans.get("tag_cn_long", "")
        else:
            tag["tag_cn"] = ""
            tag["confidence"] = ""
            tag["tag_cn_long"] = ""
            missing += 1
    if missing:
        print(f"  {group['group_name']}: {missing} tags missing translation")
    return group


def merge_all() -> None:
    """Read all tag groups, merge translations, write output files."""
    cached = load_all_cached()
    if not cached:
        print("No cached translations found. Run translator first.")
        return

    print(f"Loaded {len(cached)} cached translations")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    total_tags = 0
    translated = 0

    for fpath in sorted(TAG_GROUP_DIR.glob("*.json")):
        with open(fpath, "r", encoding="utf-8") as f:
            group = json.load(f)

        merge_one_group(group, cached)

        tags_in_group = len(group.get("tags", []))
        translated_in_group = sum(
            1 for t in group.get("tags", []) if t.get("tag_cn")
        )
        total_tags += tags_in_group
        translated += translated_in_group

        out_path = OUTPUT_DIR / fpath.name
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(group, f, ensure_ascii=False, indent=2)

    print(f"\nMerged {translated}/{total_tags} tags across "
          f"{len(list(TAG_GROUP_DIR.glob('*.json')))} groups")
    print(f"Output: {OUTPUT_DIR}")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    merge_all()
