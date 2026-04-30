"""
All configurable parameters for the Danbooru Tag translation project.
Edit values here before running — no command-line args needed.
"""
from pathlib import Path

# ---------------------------------------------------------------------------
# LLM configuration
# ---------------------------------------------------------------------------
LLM_BASE_URL = "https://api.deepseek.com"
LLM_API_KEY = "sk-f035d1e0c2354c4eaf809c9f3526fd99"
LLM_MODEL = "deepseek-v4-flash"
AVAILABLE_MODELS = ["deepseek-v4-pro", "deepseek-v4-flash"]
LLM_TIMEOUT = 6000                # API 请求超时秒数（thinking 模式响应慢，设长一些）
HTTP_PROXY = "http://127.0.0.1:10801"  # HTTP 代理，不需要则设为 None

# ---------------------------------------------------------------------------
# Translation strategy
# ---------------------------------------------------------------------------
BATCH_SIZE = 20                  # tags per LLM request (1 = quality-first, 10-20 = balanced)
MAX_CONCURRENCY = 10              # concurrent LLM call threads
REQUEST_INTERVAL = 0.5           # seconds between submitting batches

# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------
MAX_RETRIES = 3                  # max retries per batch
RETRY_BACKOFF = 2.0              # exponential backoff multiplier

# ---------------------------------------------------------------------------
# Wiki context
# ---------------------------------------------------------------------------
WIKI_MAX_CHARS = 500             # truncate wiki body to this many characters

# ---------------------------------------------------------------------------
# Paths  (relative to project root)
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent
TAG_GROUP_DIR = PROJECT_ROOT / "data" / "tag_group"
WIKI_PARQUET = PROJECT_ROOT / "data" / "danbooru_wikis_full" / "wiki_pages.parquet"
CACHE_DIR = PROJECT_ROOT / "data" / "cache"
OUTPUT_DIR = PROJECT_ROOT / "data" / "translated"
PROGRESS_FILE = CACHE_DIR / "progress.json"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_REQUEST = False              # 控制台打印完整请求报文（调试时开启）
LOG_RESPONSE = False              # 控制台打印完整返回报文

# ---------------------------------------------------------------------------
# Dry run  — set True to preview prompts without calling LLM
# ---------------------------------------------------------------------------
DRY_RUN = False
