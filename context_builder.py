"""
Build translation context for each unique tag from tag-group JSONs + wiki parquet.
"""
from __future__ import annotations
import json
import time
import pandas as pd
from pathlib import Path
from config import TAG_GROUP_DIR, WIKI_PARQUET, WIKI_MAX_CHARS


def load_tag_groups() -> list[dict]:
    """Load all tag-group JSON files and return a list of parsed group dicts."""
    groups = []
    files = sorted(TAG_GROUP_DIR.glob("*.json"))
    for fpath in files:
        with open(fpath, "r", encoding="utf-8") as f:
            groups.append(json.load(f))
    print(f"[context] Loaded {len(groups)} tag group files", flush=True)
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
    print(f"[context] {len(seen)} unique tags (from {sum(len(g.get('tags', [])) for g in groups)} total)",
          flush=True)
    return list(seen.values())


def _build_wiki_dict() -> dict[str, str]:
    """
    Load wiki parquet and build a dict: {title_lower: body}.
    Also precomputes common fuzzy variants.
    """
    t0 = time.time()
    print("[context] Loading wiki parquet...", flush=True)
    df = pd.read_parquet(WIKI_PARQUET)
    df = df[df["is_deleted"] == False]  # noqa: E712
    print(f"[context] Wiki parquet loaded: {len(df)} pages ({time.time() - t0:.1f}s)", flush=True)

    t0 = time.time()
    wiki_dict = {}
    for _, row in df.iterrows():
        title = str(row["title"]).strip().lower()
        body = str(row["body"])
        if title:
            wiki_dict[title] = body

    # Pre-index variants: for titles with underscores, also index space/nospace variants
    extras = {}
    for title, body in wiki_dict.items():
        if "_" in title:
            extras.setdefault(title.replace("_", " "), body)
            extras.setdefault(title.replace("_", ""), body)
        elif " " in title:
            extras.setdefault(title.replace(" ", "_"), body)

    wiki_dict.update(extras)
    print(f"[context] Wiki dict built: {len(wiki_dict)} keys ({time.time() - t0:.1f}s)", flush=True)
    return wiki_dict


def _search_wiki_fast(wiki_dict: dict[str, str], tag_name: str) -> str:
    """
    O(1) dict lookup for wiki body. Tries exact match then fuzzy variants.
    """
    q = tag_name.strip().lower()
    # Try exact
    if q in wiki_dict:
        return wiki_dict[q][:WIKI_MAX_CHARS]
    # Try variants
    if "_" in q:
        for v in [q.replace("_", " "), q.replace("_", "")]:
            if v in wiki_dict:
                return wiki_dict[v][:WIKI_MAX_CHARS]
    else:
        v = q.replace(" ", "_")
        if v in wiki_dict:
            return wiki_dict[v][:WIKI_MAX_CHARS]
    return ""


def build_contexts(tags: list[dict], wiki_dict: dict[str, str] | None = None) -> list[dict]:
    """
    Attach wiki body to each tag entry.
    Returns list of context dicts: {tag, group_name, category_path, wiki}
    """
    if wiki_dict is None:
        wiki_dict = _build_wiki_dict()

    total = len(tags)
    need_wiki = sum(1 for t in tags if t["wiki_exists"])
    print(f"[context] Building contexts for {total} tags ({need_wiki} need wiki lookup)...", flush=True)

    t0 = time.time()
    contexts = []
    wiki_hits = 0
    found_but_missing_flag = 0  # wiki_exists=False but wiki found anyway
    report_every = max(1, total // 10)  # Report every 10%

    for i, t in enumerate(tags):
        wiki = ""
        if t["wiki_exists"]:
            wiki = _search_wiki_fast(wiki_dict, t["tag"])
            if wiki:
                wiki_hits += 1
        else:
            # Try anyway — tag group data may be stale
            wiki = _search_wiki_fast(wiki_dict, t["tag"])
            if wiki:
                found_but_missing_flag += 1

        contexts.append({
            "tag": t["tag"],
            "group_name": t["group_name"],
            "category_path": t["category_path"],
            "wiki": wiki,
        })

        if (i + 1) % report_every == 0:
            elapsed = time.time() - t0
            print(f"[context]   {i + 1}/{total} tags processed ({elapsed:.1f}s)...", flush=True)

    elapsed = time.time() - t0
    print(f"[context] Contexts built in {elapsed:.1f}s. "
          f"Wiki hits: {wiki_hits} (flag=true) + {found_but_missing_flag} (flag=false but found)",
          flush=True)
    return contexts


def build_all() -> list[dict]:
    """Full pipeline: load groups → extract unique tags → attach wiki."""
    t0 = time.time()
    groups = load_tag_groups()
    tags = extract_unique_tags(groups)
    wiki_dict = _build_wiki_dict()
    contexts = build_contexts(tags, wiki_dict)
    print(f"[context] build_all complete in {time.time() - t0:.1f}s", flush=True)
    return contexts


def save_contexts_to_json(contexts: list[dict], path: str) -> None:
    print(f"[context] Saving contexts to {path}...", flush=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(contexts, f, ensure_ascii=False, indent=2)


def load_contexts_from_json(path: str) -> list[dict] | None:
    """Load contexts from cached JSON if it exists. Returns None if not found."""
    p = Path(path)
    if not p.exists():
        return None
    t0 = time.time()
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"[context] Loaded {len(data)} contexts from {path} ({time.time() - t0:.1f}s)", flush=True)
    return data


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    ctx = build_all()
    print(f"\n--- Sample contexts ---")
    for c in ctx[:5]:
        print(json.dumps(c, ensure_ascii=False, indent=2))
