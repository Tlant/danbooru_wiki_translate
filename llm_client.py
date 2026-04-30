"""
DeepSeek API client wrapper (OpenAI-compatible format).
"""
import json
import re
from openai import OpenAI
from config import LLM_BASE_URL, LLM_API_KEY, LLM_MODEL

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
    """Thin wrapper around OpenAI-compatible DeepSeek API."""

    def __init__(self, base_url: str = LLM_BASE_URL,
                 api_key: str = LLM_API_KEY, model: str = LLM_MODEL):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def translate_batch(self, contexts: list[dict]) -> list[dict]:
        """
        Send a batch of tag contexts to LLM, return parsed translation results.
        Each result: {tag, tag_cn, confidence, tag_cn_long}

        Raises ValueError on parse failure, or API errors.
        """
        context_json = _build_context_json(contexts)
        user_prompt = USER_PROMPT_TEMPLATE.format(
            count=len(contexts),
            context_json=context_json,
        )

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

        raw = response.choices[0].message.content
        return _parse_response(raw)

    def preview_prompt(self, contexts: list[dict]) -> str:
        """Return the user prompt that would be sent (for dry-run)."""
        context_json = _build_context_json(contexts)
        return USER_PROMPT_TEMPLATE.format(
            count=len(contexts),
            context_json=context_json,
        )


if __name__ == "__main__":
    # Quick smoke test: preview prompt for a few sample tags
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
