"""
Danbooru Tag 中文翻译 — 入口脚本

Usage:
  .venv/Scripts/python main.py              # Full translation pipeline
  .venv/Scripts/python main.py --dry-run    # Preview prompts only
  .venv/Scripts/python main.py --merge-only # Only merge cached results
  .venv/Scripts/python main.py --stats      # Show cache/progress statistics
"""
import sys
import argparse
from pathlib import Path

# Ensure project root on sys.path
sys.path.insert(0, str(Path(__file__).parent))


def cmd_translate() -> None:
    from context_builder import build_all, save_contexts_to_json
    from translator import translate_all

    print("=" * 50)
    print("Step 1/2: Building translation contexts...")
    contexts = build_all()

    # Save contexts for inspection
    ctx_path = Path("data/cache/contexts.json")
    ctx_path.parent.mkdir(parents=True, exist_ok=True)
    save_contexts_to_json(contexts, str(ctx_path))

    print(f"\nStep 2/2: Translating...")
    results = translate_all(contexts)
    print(f"\nTranslation complete: {len(results)} tags translated.")


def cmd_merge() -> None:
    from merger import merge_all
    merge_all()


def cmd_stats() -> None:
    from config import CACHE_DIR, PROGRESS_FILE
    import json

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
    print(f"Confidence: A={conf_counts['A']} B={conf_counts['B']} "
          f"C={conf_counts['C']} D={conf_counts['D']} unknown={conf_counts['?']}")

    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            progress = json.load(f)
        print(f"Progress: {len(progress.get('completed', []))} completed, "
              f"{len(progress.get('failed_batches', []))} failed batches")
        total = progress.get("total", 0)
        done = len(progress.get("completed", []))
        if total > 0:
            print(f"Completion: {done}/{total} ({100 * done / total:.1f}%)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Danbooru Tag Chinese Translation")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview prompts without calling LLM")
    parser.add_argument("--merge-only", action="store_true",
                        help="Only merge cached translations (skip LLM calls)")
    parser.add_argument("--stats", action="store_true",
                        help="Show cache and progress statistics")
    args = parser.parse_args()

    if args.stats:
        cmd_stats()
    elif args.dry_run:
        import config
        config.DRY_RUN = True
        cmd_translate()
    elif args.merge_only:
        cmd_merge()
    else:
        cmd_translate()
        cmd_merge()
        cmd_stats()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
