"""
Danbooru Tag 中文翻译 — 入口脚本

Usage:
  .venv/Scripts/python main.py                 # Full pipeline (uses cached contexts if exists)
  .venv/Scripts/python main.py --dry-run       # Preview prompts only
  .venv/Scripts/python main.py --merge-only    # Only merge cached results
  .venv/Scripts/python main.py --stats         # Show cache/progress statistics
  .venv/Scripts/python main.py --rebuild       # Force rebuild contexts (ignore cache)
  .venv/Scripts/python main.py --test N        # Test-translate first N tags only
"""
import sys
import argparse
from pathlib import Path

# Ensure project root on sys.path
sys.path.insert(0, str(Path(__file__).parent))


CONTEXTS_CACHE = Path("data/cache/contexts.json")


def _get_contexts(rebuild: bool = False) -> list[dict]:
    """Get contexts from cache or build from scratch."""
    from context_builder import (
        build_all, save_contexts_to_json, load_contexts_from_json,
    )

    if not rebuild:
        cached = load_contexts_from_json(str(CONTEXTS_CACHE))
        if cached is not None:
            return cached

    print("Building contexts from source...")
    contexts = build_all()

    CONTEXTS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    save_contexts_to_json(contexts, str(CONTEXTS_CACHE))
    return contexts


def cmd_translate(rebuild: bool = False, test_n: int = 0) -> None:
    from translator import translate_all

    print("=" * 60)
    print("Step 1/2: Getting translation contexts...")
    contexts = _get_contexts(rebuild)

    if test_n > 0:
        contexts = contexts[:test_n]
        print(f"[main] TEST MODE: only translating first {test_n} tags")

    print(f"\nStep 2/2: Translating ({len(contexts)} tags)...")
    print("=" * 60)
    results = translate_all(contexts)
    print(f"\nTranslation complete: {len(results)} tags translated.")


def cmd_merge() -> None:
    from merger import merge_all
    merge_all()


def cmd_stats() -> None:
    from config import CACHE_DIR, PROGRESS_FILE
    import json

    print("=" * 60)
    print("Translation Cache Stats")
    print("=" * 60)

    if not CACHE_DIR.exists():
        print("No cache directory found.")
        return

    cache_files = list(CACHE_DIR.glob("*.json"))
    tag_files = [f for f in cache_files if f.name not in ("progress.json", "contexts.json")]
    print(f"Cached tag translations: {len(tag_files)}")

    # Confidence breakdown
    conf_counts = {"A": 0, "B": 0, "C": 0, "D": 0, "?": 0}
    for f in tag_files:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            c = data.get("confidence", "?")
            conf_counts[c] = conf_counts.get(c, 0) + 1
        except Exception:
            conf_counts["?"] += 1
    total = sum(conf_counts.values())
    if total > 0:
        print(f"Confidence: A={conf_counts['A']} ({100*conf_counts['A']/total:.0f}%) "
              f"B={conf_counts['B']} ({100*conf_counts['B']/total:.0f}%) "
              f"C={conf_counts['C']} ({100*conf_counts['C']/total:.0f}%) "
              f"D={conf_counts['D']} ({100*conf_counts['D']/total:.0f}%)")
    else:
        print("Confidence: (no translations yet)")

    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            progress = json.load(f)
        done = len(progress.get("completed", []))
        failed = len(progress.get("failed_batches", []))
        total = progress.get("total", 0)
        print(f"Progress: {done}/{total} completed, {failed} failed batches")
        if total > 0:
            print(f"Completion: {100 * done / total:.1f}%")
    else:
        print("Progress: no progress file yet")


def main() -> None:
    parser = argparse.ArgumentParser(description="Danbooru Tag Chinese Translation")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview prompts without calling LLM")
    parser.add_argument("--merge-only", action="store_true",
                        help="Only merge cached translations (skip LLM calls)")
    parser.add_argument("--stats", action="store_true",
                        help="Show cache and progress statistics")
    parser.add_argument("--rebuild", action="store_true",
                        help="Force rebuild contexts (ignore cache)")
    parser.add_argument("--test", type=int, default=0, metavar="N",
                        help="Test mode: only translate first N tags")
    args = parser.parse_args()

    if args.stats:
        cmd_stats()
    elif args.dry_run:
        import config
        config.DRY_RUN = True
        cmd_translate(rebuild=args.rebuild)
    elif args.merge_only:
        cmd_merge()
    else:
        cmd_translate(rebuild=args.rebuild, test_n=args.test)
        cmd_merge()
        cmd_stats()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
