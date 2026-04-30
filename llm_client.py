"""
DeepSeek API client wrapper (OpenAI-compatible format).
"""
import json
import re
import time
import httpx
from openai import OpenAI
from config import (LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, LLM_TIMEOUT, HTTP_PROXY,
                     LOG_REQUEST, LOG_RESPONSE)

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a professional translator specializing in Danbooru tags (二次元插画标签).
Danbooru tags are short English phrases (often single words or compound nouns) used \
to tag anime-style illustrations.

Your task: translate each tag into accurate Chinese.

Guidelines:
- **tag_cn**: Short Chinese translation (typically 2-6 characters). Use established \
term if one exists in Chinese ACG community (e.g. "tsundere" → "傲娇"). \
If no established term, create a concise and natural translation.
- **confidence**: Your certainty level:
  - A = very confident (common tag, well-known translation)
  - B = mostly confident (clear meaning, slight ambiguity)
  - C = ambiguous (multiple possible interpretations)
  - D = needs human review (unfamiliar, obscure, or unclear)
- **tag_cn_long**: A brief Chinese explanation or definition (one short sentence). \
For objects: describe what it is. For actions: describe what happens. \
For attributes: describe the visual appearance.

You MUST output valid JSON only — no markdown, no extra text, no code fences."""

USER_PROMPT_TEMPLATE = """\
Translate the following {count} Danbooru tags into Chinese.
Each tag entry includes the tag name, its group/category, and an optional wiki \
description for context.

Tags to translate:
{context_json}

Output a JSON array with exactly {count} items in this exact format:
```json
[
  {{
    "tag": "original_tag_name",
    "tag_cn": "短翻译",
    "confidence": "A",
    "tag_cn_long": "一段简短的中文解释说明。"
  }}
]
```

Output ONLY the JSON array. No markdown, no explanation."""


def _build_context_json(contexts: list[dict]) -> str:
    """Serialize context list to a compact JSON string for the prompt."""
    simplified = []
    for c in contexts:
        entry = {
            "tag": c["tag"],
            "group": c["group_name"],
            "category": c["category_path"],
        }
        if c.get("wiki"):
            entry["wiki"] = c["wiki"]
        simplified.append(entry)
    return json.dumps(simplified, ensure_ascii=False, indent=2)


def _parse_response(text: str) -> list[dict]:
    """Extract JSON array from LLM response. Handles code-fence wrapping."""
    text = text.strip()
    # Strip code fences if present
    m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    # Find JSON array boundaries
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON array found in response: {text[:200]}")
    return json.loads(text[start:end + 1])


class LLMClient:
    """Wrapper around OpenAI-compatible DeepSeek API."""

    def __init__(self, base_url: str = LLM_BASE_URL,
                 api_key: str = LLM_API_KEY, model: str = LLM_MODEL):
        timeout = httpx.Timeout(LLM_TIMEOUT, connect=30.0)
        if HTTP_PROXY:
            http_client = httpx.Client(proxy=HTTP_PROXY, timeout=timeout)
        else:
            http_client = httpx.Client(timeout=timeout)
        self.client = OpenAI(api_key=api_key, base_url=base_url,
                             http_client=http_client)
        self.model = model
        self._call_count = 0
        # Cumulative stats
        self._total_prompt_tokens = 0
        self._total_completion_tokens = 0
        self._total_elapsed = 0.0
        self._total_tags = 0
        proxy_info = f" proxy={HTTP_PROXY}" if HTTP_PROXY else ""
        print(f"[llm] Client init: model={model} base_url={base_url} "
              f"timeout={LLM_TIMEOUT}s{proxy_info}", flush=True)

    @property
    def stats(self) -> dict:
        """Return cumulative usage statistics."""
        avg_batch_time = self._total_elapsed / self._call_count if self._call_count > 0 else 0
        avg_batch_tokens = ((self._total_prompt_tokens + self._total_completion_tokens)
                            / self._call_count) if self._call_count > 0 else 0
        avg_tag_tokens = ((self._total_prompt_tokens + self._total_completion_tokens)
                          / self._total_tags) if self._total_tags > 0 else 0
        return {
            "calls": self._call_count,
            "total_tags": self._total_tags,
            "total_prompt_tokens": self._total_prompt_tokens,
            "total_completion_tokens": self._total_completion_tokens,
            "total_tokens": self._total_prompt_tokens + self._total_completion_tokens,
            "total_elapsed": self._total_elapsed,
            "avg_batch_time": avg_batch_time,
            "avg_batch_tokens": avg_batch_tokens,
            "avg_tag_tokens": avg_tag_tokens,
        }

    def translate_batch(self, contexts: list[dict]) -> list[dict]:
        """
        Send a batch of tag contexts to LLM, return parsed translation results.
        Each result: {tag, tag_cn, confidence, tag_cn_long}

        Raises ValueError on parse failure, or API errors.
        """
        self._call_count += 1
        call_id = self._call_count
        n_tags = len(contexts)
        tag_names = [c["tag"] for c in contexts[:5]]
        tag_preview = ", ".join(tag_names)
        if n_tags > 5:
            tag_preview += f", ... (+{n_tags - 5} more)"

        print(f"  [llm #{call_id}] Sending {n_tags} tags: {tag_preview}...", flush=True)

        context_json = _build_context_json(contexts)
        prompt_chars = len(context_json)

        user_prompt = USER_PROMPT_TEMPLATE.format(
            count=n_tags, context_json=context_json)

        if LOG_REQUEST:
            print(f"  [llm #{call_id}] === REQUEST ===", flush=True)
            print(user_prompt, flush=True)
            print(f"  [llm #{call_id}] === END REQUEST ===", flush=True)

        t0 = time.time()
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            stream=False,
            reasoning_effort="high",
            extra_body={"thinking": {"type": "enabled"}},
        )
        elapsed = time.time() - t0

        usage = response.usage
        raw = response.choices[0].message.content

        # Accumulate stats
        self._total_elapsed += elapsed
        self._total_tags += n_tags
        if usage:
            self._total_prompt_tokens += usage.prompt_tokens
            self._total_completion_tokens += usage.completion_tokens

        # Count tokens if available
        tok_info = ""
        if usage:
            tok_info = (f" prompt={usage.prompt_tokens}tok "
                        f"completion={usage.completion_tokens}tok")

        print(f"  [llm #{call_id}] Response in {elapsed:.1f}s.{tok_info} "
              f"output={len(raw)}chars", flush=True)

        if LOG_RESPONSE:
            print(f"  [llm #{call_id}] === RESPONSE ===", flush=True)
            print(raw, flush=True)
            print(f"  [llm #{call_id}] === END RESPONSE ===", flush=True)

        results = _parse_response(raw)

        # Print confidence distribution for this batch
        conf_dist = {"A": 0, "B": 0, "C": 0, "D": 0}
        for r in results:
            c = r.get("confidence", "?")
            conf_dist[c] = conf_dist.get(c, 0) + 1
        print(f"  [llm #{call_id}] Confidence: A={conf_dist['A']} B={conf_dist['B']} "
              f"C={conf_dist['C']} D={conf_dist['D']}", flush=True)

        # Show all translations for this batch
        for r in results:
            print(f"    {r['tag']} → {r['tag_cn']} ({r['confidence']}) | {r['tag_cn_long']}",
                  flush=True)

        return results

    def preview_prompt(self, contexts: list[dict]) -> str:
        """Return the user prompt that would be sent (for dry-run)."""
        context_json = _build_context_json(contexts)
        return USER_PROMPT_TEMPLATE.format(
            count=len(contexts),
            context_json=context_json,
        )


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    client = LLMClient()
    samples = [
        {"tag": "cock_ring", "group_name": "sex_objects",
         "category_path": "Sex Toys",
         "wiki": "A ring at the base of the penis that constricts blood flow."},
        {"tag": "tsundere", "group_name": "personality",
         "category_path": "Personality", "wiki": ""},
    ]
    print("=== SYSTEM PROMPT ===")
    print(SYSTEM_PROMPT[:500])
    print("\n=== USER PROMPT ===")
    print(client.preview_prompt(samples))
