"""
Build translation context for each unique tag from tag-group JSONs + wiki parquet.
"""
from __future__ import annotations
import json
import pandas as pd
from pathlib import Path
from config import TAG_GROUP_DIR, WIKI_PARQUET, WIKI_MAX_CHARS


def load_tag_groups() -> list[dict]:
    """Load all tag-group JSON files and return a list of parsed group dicts."""
    groups = []
    for fpath in sorted(TAG_GROUP_DIR.glob("*.json")):
        with open(fpath, "r", encoding="utf-8") as f:
            groups.append(json.load(f))
    return groups


def extract_unique_tags(groups: list[dict]) -> list[dict]:
    """
    Extract unique tags across all groups.
    Each entry: {name, group_name, category_path, wiki_exists}
    """
    seen = {}  # tag_name -> first-seen info
    for grp in groups:
        for tag in grp.get("tags", []):
            name = tag["name"]
            if name not in seen:
                seen[name] = {
                    "tag": name,
                    "group_name": grp["group_name"],
                    "category_path": tag.get("category_path", ""),
                    "wiki_exists": tag.get("wiki_exists", False),
                }
    return list(seen.values())


def _prep_wiki_df() -> pd.DataFrame:
    """Load wiki parquet, lowercased title column for matching."""
    df = pd.read_parquet(WIKI_PARQUET)
    # filter deleted
    df = df[df["is_deleted"] == False]  # noqa: E712
    df["title_lower"] = df["title"].str.lower()
    return df


def _search_wiki(df: pd.DataFrame, tag_name: str) -> str:
    """
    Search wiki for tag_name. Returns body text or empty string.
    Tries exact match then fuzzy variants.
    """
    q = tag_name.strip().lower()
    variants = [q]
    if "_" in q:
        variants += [q.replace("_", " "), q.replace("_", "")]
    else:
        variants.append(q.replace(" ", "_"))

    for v in variants:
        mask = df["title_lower"] == v
        rows = df[mask]
        if len(rows) > 0:
            body = str(rows.iloc[0]["body"])
            return body[:WIKI_MAX_CHARS]

    return ""


def build_contexts(tags: list[dict], wiki_df: pd.DataFrame | None = None) -> list[dict]:
    """
    Attach wiki body to each tag entry.
    Returns list of context dicts: {tag, group_name, category_path, wiki}
    """
    if wiki_df is None:
        wiki_df = _prep_wiki_df()

    contexts = []
    for t in tags:
        wiki = _search_wiki(wiki_df, t["tag"]) if t["wiki_exists"] else ""
        contexts.append({
            "tag": t["tag"],
            "group_name": t["group_name"],
            "category_path": t["category_path"],
            "wiki": wiki,
        })
    return contexts


def build_all() -> list[dict]:
    """Full pipeline: load groups → extract unique tags → attach wiki."""
    groups = load_tag_groups()
    tags = extract_unique_tags(groups)
    print(f"Loaded {len(groups)} tag groups, {len(tags)} unique tags")
    wiki_df = _prep_wiki_df()
    contexts = build_contexts(tags, wiki_df)
    wiki_hits = sum(1 for c in contexts if c["wiki"])
    print(f"Wiki found for {wiki_hits}/{len(contexts)} tags")
    return contexts


def save_contexts_to_json(contexts: list[dict], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(contexts, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    ctx = build_all()
    print(f"\n--- Sample contexts ---")
    for c in ctx[:5]:
        print(json.dumps(c, ensure_ascii=False, indent=2))
