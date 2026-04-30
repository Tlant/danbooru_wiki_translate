"""
Translation orchestrator: batch dispatch, concurrency, retry, checkpoint/resume.
"""
from __future__ import annotations
import json
import time
import traceback
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import (
    BATCH_SIZE, MAX_CONCURRENCY, REQUEST_INTERVAL,
    MAX_RETRIES, RETRY_BACKOFF, CACHE_DIR, PROGRESS_FILE, DRY_RUN,
)
from llm_client import LLMClient


def chunk_list(lst: list, size: int) -> list[list]:
    """Split list into chunks of given size."""
    return [lst[i:i + size] for i in range(0, len(lst), size)]


def _tag_cache_path(tag_name: str) -> Path:
    """File path for a single tag's cached translation result."""
    safe_name = tag_name.replace("/", "_").replace("\\", "_")
    return CACHE_DIR / f"{safe_name}.json"


def load_cache() -> dict[str, dict]:
    """Load all cached tag translations. Returns {tag_name: result_dict}."""
    cache = {}
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for fpath in CACHE_DIR.glob("*.json"):
        if fpath.name == PROGRESS_FILE.name:
            continue
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "tag" in data:
                cache[data["tag"]] = data
        except (json.JSONDecodeError, KeyError):
            pass
    return cache


def save_tag_cache(result: dict) -> None:
    """Save a single tag translation result to its cache file."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _tag_cache_path(result["tag"])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


def load_progress() -> dict:
    """Load progress tracking state."""
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"total": 0, "completed": [], "failed_batches": []}


def save_progress(progress: dict) -> None:
    """Save progress tracking state."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def _validate_result(item: dict) -> bool:
    """Check that a single translation result has all required fields."""
    required = ["tag", "tag_cn", "confidence", "tag_cn_long"]
    return all(k in item for k in required) and item["confidence"] in "ABCD"


def _translate_batch_with_retry(client: LLMClient,
                                batch: list[dict],
                                batch_idx: int = 0,
                                total: int = 0) -> list[dict]:
    """Call LLM for a batch, retrying on failure with exponential backoff."""
    last_error = None
    tag_preview = ", ".join(c["tag"] for c in batch[:3])
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if attempt > 1:
                print(f"  [batch {batch_idx}/{total}] Attempt {attempt}/{MAX_RETRIES}...",
                      flush=True)
            results = client.translate_batch(batch)
            # Validate each result
            for r in results:
                if not _validate_result(r):
                    raise ValueError(f"Invalid result format: {r}")
            print(f"  [batch {batch_idx}/{total}] OK — {len(results)} tags translated",
                  flush=True)
            return results
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF ** attempt
                print(f"  [batch {batch_idx}/{total}] FAIL (attempt {attempt}): {e}", flush=True)
                print(f"  [batch {batch_idx}/{total}] Retrying in {wait:.1f}s...", flush=True)
                time.sleep(wait)
    raise RuntimeError(
        f"Batch {batch_idx} failed after {MAX_RETRIES} retries. Tags: {tag_preview}... "
        f"Last error: {last_error}"
    )


def translate_all(contexts: list[dict]) -> dict[str, dict]:
    """
    Main translation pipeline.
    Returns {tag_name: {tag, tag_cn, confidence, tag_cn_long}}
    """
    # Load existing cache
    cache = load_cache()
    progress = load_progress()
    progress["total"] = len(contexts)

    # Filter out already-translated tags
    pending = [c for c in contexts if c["tag"] not in cache]
    print(f"Total: {len(contexts)}, cached: {len(cache)}, pending: {len(pending)}")

    if not pending:
        print("All tags already translated!")
        return cache

    batches = chunk_list(pending, BATCH_SIZE)
    print(f"Batches: {len(batches)} (batch_size={BATCH_SIZE}, "
          f"concurrency={MAX_CONCURRENCY})")

    if DRY_RUN:
        _dry_run(batches)
        return cache

    client = LLMClient()
    print(f"[translator] LLM model: {client.model} | batch_size={BATCH_SIZE} | "
          f"concurrency={MAX_CONCURRENCY} | retries={MAX_RETRIES}", flush=True)
    failed_batches = progress.get("failed_batches", [])

    t_start = time.time()
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENCY) as pool:
        future_to_batch = {}
        for i, batch in enumerate(batches):
            batch_idx = i + 1
            # Check if this batch was previously failed
            batch_key = ",".join(c["tag"] for c in batch[:3])
            if batch_key in failed_batches:
                print(f"  [batch {batch_idx}/{len(batches)}] SKIP (previously failed)",
                      flush=True)
                continue

            f = pool.submit(_translate_batch_with_retry, client, batch,
                            batch_idx, len(batches))
            future_to_batch[f] = (i, batch, batch_idx)
            print(f"  [batch {batch_idx}/{len(batches)}] Submitted ({len(batch)} tags)",
                  flush=True)
            time.sleep(REQUEST_INTERVAL)

        done_count = 0
        for f in as_completed(future_to_batch):
            i, batch, batch_idx = future_to_batch[f]
            batch_key = ",".join(c["tag"] for c in batch[:3])
            try:
                results = f.result()
                # Save each result to cache
                for r in results:
                    cache[r["tag"]] = r
                    save_tag_cache(r)

                # Update progress
                for r in results:
                    if r["tag"] not in progress["completed"]:
                        progress["completed"].append(r["tag"])
                save_progress(progress)

                done_count += 1
                pct = 100 * done_count / len(batches)
                elapsed = time.time() - t_start
                eta = elapsed / done_count * (len(batches) - done_count) if done_count > 0 else 0
                print(f"  [progress] {done_count}/{len(batches)} batches ({pct:.0f}%) | "
                      f"elapsed={elapsed:.0f}s eta={eta:.0f}s | "
                      f"{len(progress['completed'])}/{progress['total']} tags done",
                      flush=True)

            except Exception as e:
                traceback.print_exc()
                failed_batches.append(batch_key)
                progress["failed_batches"] = failed_batches
                save_progress(progress)
                print(f"  [batch {batch_idx}/{len(batches)}] GAVE UP: {e}", flush=True)

    # Final summary
    print(f"\nDone. Translated: {len(cache)}, "
          f"Failed batches: {len(progress['failed_batches'])}")
    return cache


def _dry_run(batches: list[list[dict]]) -> None:
    """Print sample prompts without calling LLM."""
    client = LLMClient()
    for i, batch in enumerate(batches[:3]):
        print(f"\n{'=' * 60}")
        print(f"Batch {i + 1}/{len(batches)} — {len(batch)} tags:")
        print(f"Tags: {[c['tag'] for c in batch]}")
        print(f"\nUser prompt preview (first 800 chars):")
        prompt = client.preview_prompt(batch)
        print(prompt[:800])
        print("..." if len(prompt) > 800 else "")
    print(f"\n{'=' * 60}")
    print(f"(Dry run: {len(batches)} total batches, first 3 shown)")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    from context_builder import build_all

    contexts = build_all()
    results = translate_all(contexts)
