# Danbooru Tag 中文翻译项目计划

## Context

danbooru 网站的 tag 需要精准的中文翻译。翻译借助 DeepSeek LLM，但由于 danbooru tag 使用极简英文（如 `cock_ring`），单独送给 LLM 可能无法准确翻译，需要结合 danbooru 官方 wiki 说明补全上下文。

数据源：
- 54 个 tag group JSON 文件（`data/tag_group/`），共 ~9320 条 tag 记录，约 8308 个唯一 tag
- wiki 数据（`data/danbooru_wikis_full/wiki_pages.parquet`），204,442 条 wiki 页面

目标：为每个唯一 tag 输出精准中文翻译，结果按 tag group 合并输出。

---

## 1. 项目结构

```
danbooru_wiki/
├── config.py              # 所有可配置参数集中管理
├── context_builder.py     # 从 tag JSON + wiki parquet 构建翻译上下文
├── llm_client.py          # DeepSeek API 客户端封装（OpenAI 兼容）
├── translator.py          # 翻译调度器：批量、并发、重试、断点续跑
├── merger.py              # 将翻译结果合并回 tag group 文件
├── main.py                # 入口脚本
├── data/
│   ├── tag_group/         # 输入：tag group JSON
│   ├── danbooru_wikis_full/  # 输入：wiki parquet
│   ├── cache/             # 缓存：逐 tag 翻译结果（支持断点续跑）
│   └── translated/        # 输出：翻译后的 tag group JSON
├── note.md
├── search_wiki.py         # 已有：wiki 模糊搜索参考
└── read_data.py           # 已有：数据读取参考
```

## 2. 配置设计 (`config.py`)

```python
# -- LLM 配置 --
LLM_BASE_URL = "https://api.deepseek.com"
LLM_API_KEY = "sk-f035d1e0c2354c4eaf809c9f3526fd99"
LLM_MODEL = "deepseek-v4-pro"          # 可选: deepseek-v4-pro, deepseek-v4-flash
AVAILABLE_MODELS = ["deepseek-v4-pro", "deepseek-v4-flash"]

# -- 翻译策略 --
BATCH_SIZE = 15              # 单次 LLM 请求翻译的 tag 条数（支持 1~20 可调）
MAX_CONCURRENCY = 1          # 并发调用 LLM 的线程数（默认 1）
REQUEST_INTERVAL = 0.5       # 请求间隔（秒），避免触发限流

# -- 重试配置 --
MAX_RETRIES = 3              # 单批最大重试次数
RETRY_BACKOFF = 2.0          # 重试退避倍率

# -- 路径配置 --
TAG_GROUP_DIR = "data/tag_group"
WIKI_PARQUET = "data/danbooru_wikis_full/wiki_pages.parquet"
CACHE_DIR = "data/cache"
OUTPUT_DIR = "data/translated"
PROGRESS_FILE = "data/cache/progress.json"
```

用户可修改 `config.py` 切换模型、调整批量大小和并发数。

## 3. 核心模块设计

### 3.1 `context_builder.py` — 上下文构造器

**职责**：为每个唯一 tag 构建翻译上下文（不含 wiki 也可翻译，但有 wiki 时附上）

**流程**：
1. 遍历 `data/tag_group/*.json`，提取所有 tag
2. 按 tag name 去重，保留其 `group_name` 和 `category_path`（同一 tag 可能出现在多个 group，取 first seen）
3. 对每个 tag，用 `search_wiki.py` 的模糊搜索方法查询 wiki_pages.parquet，获取 `body` 字段
4. 输出标准化的上下文 dict 列表

**上下文格式**：
```json
{
  "tag": "cock_ring",
  "group_name": "sex_objects",
  "category_path": "Sex Toys",
  "wiki": "A ring at the base of the penis that constricts blood flow to help maintain an erection..."
}
```
- `wiki` 字段：若 wiki 存在则填入 body 文本（截断至 500 字符），不存在则为空字符串

**复用**：`search_wiki.py` 中的 `fuzzy_search()` 函数 — 支持下划线/空格模糊匹配

### 3.2 `llm_client.py` — LLM 客户端

**职责**：封装 DeepSeek API 调用，使用 OpenAI 兼容格式

**核心方法**：
```python
class LLMClient:
    def __init__(self, base_url, api_key, model):
        self.client = OpenAI(api_key=api_key, base_url=base_url)

    def translate_batch(self, contexts: list[dict]) -> dict:
        """
        发送一批 tag 上下文给 LLM，返回解析后的 JSON
        - 构造 system prompt + user prompt（包含 JSON 输出格式要求）
        - 调用 API（reasoning_effort="high", thinking enabled）
        - 解析返回 JSON，验证格式
        - 失败时抛出异常供上层重试
        """
```

**Prompt 设计要点**：
- System prompt：说明角色（日系二次元插画标签翻译专家）、输出要求
- User prompt：包含上下文列表 + 严格 JSON 输出格式
- 要求返回 JSON 数组，每个元素含 `tag`, `tag_cn`, `confidence`, `tag_cn_long`

### 3.3 `translator.py` — 翻译调度器

**职责**：核心编排逻辑 — 批量、并发、重试、缓存、断点续跑

**核心流程**：
```
构建上下文 → 加载进度缓存 → 分批 → 并发调用 LLM → 解析结果 → 缓存 → 输出
```

**关键设计**：

**缓存与断点续跑**：
- 每翻译完一批，立即写入 `data/cache/{tag_name}.json`（一个 tag 一个文件）
- `progress.json` 记录全局进度：`{"total": 8308, "completed": 1234, "failed_tags": []}`
- 启动时扫描 cache 目录，已缓存的 tag 自动跳过

**批量翻译**：
- 将待翻译的 contexts 按 `BATCH_SIZE` 分组
- 每组为一个工作单元

**并发控制**：
- 使用 `concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENCY)`
- 每个 worker 调用 `llm_client.translate_batch()`

**失败重试**：
- 单批失败后指数退避重试，最多 `MAX_RETRIES` 次
- 重试仍失败的 tag 记入 `failed_tags`，输出错误报告

**流程伪代码**：
```python
def run():
    contexts = build_all_contexts()
    progress = load_progress()
    pending = [c for c in contexts if c['tag'] not in progress['completed']]
    batches = chunk(pending, BATCH_SIZE)

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENCY) as pool:
        futures = []
        for batch in batches:
            f = pool.submit(translate_with_retry, batch)
            futures.append(f)
            time.sleep(REQUEST_INTERVAL)  # 提交间隔

        for f in futures:
            results = f.result()
            for r in results:
                save_cache(r)
                update_progress(r['tag'])
```

### 3.4 `merger.py` — 结果合并器

**职责**：将缓存的逐 tag 翻译结果，按原始 tag group 结构合并输出

**流程**：
1. 读取原始 tag group JSON
2. 对每个 tag，从 `data/cache/{tag_name}.json` 读取翻译结果
3. 在原始 tag 对象上增加 `tag_cn`, `confidence`, `tag_cn_long` 字段
4. 输出到 `data/translated/{group_name}.json`

**输出格式**（tag group 级别）：
```json
{
  "group_name": "sex_objects",
  "tags": [
    {
      "name": "anal beads",
      "tag_type": 0,
      "category_path": "Sex Toys",
      "tag_cn": "肛门拉珠",
      "confidence": "A",
      "tag_cn_long": "一种用于肛门刺激的性玩具，由多个珠子串联而成。"
    },
    ...
  ]
}
```

### 3.5 `main.py` — 入口脚本

```python
def main():
    # 1. 检查配置
    # 2. 构建上下文（或从缓存加载）
    # 3. 执行翻译（带进度显示）
    # 4. 合并输出结果
    # 5. 打印统计报告
```

## 4. 依赖

需要安装的 Python 包（在 `.venv` 中）：
- `openai` — DeepSeek API 调用
- `pandas` + `pyarrow` — 读取 parquet（已有）
- 标准库足够：`json`, `concurrent.futures`, `time`, `pathlib`, `re`

## 5. 执行顺序

| 阶段 | 文件 | 说明 |
|------|------|------|
| 1 | `config.py` | 创建配置文件 |
| 2 | `context_builder.py` | 上下文构造，依赖 search_wiki.py 的模糊搜索逻辑 |
| 3 | `llm_client.py` | LLM 客户端封装 |
| 4 | `translator.py` | 核心翻译调度 |
| 5 | `merger.py` | 结果合并输出 |
| 6 | `main.py` | 入口脚本串联全流程 |

## 6. 验证计划

1. **单元验证**：用 `--dry-run` 模式打印 3-5 个 tag 的上下文和 prompt，检查 wiki 匹配是否正确
2. **小批量测试**：用 `MAX_CONCURRENCY=1`, `BATCH_SIZE=3` 翻译 10 个 tag，验证输出格式和缓存
3. **断点续跑测试**：中断翻译后重新运行，确认已完成的 tag 被跳过
4. **全量运行**：翻译全部 8308 个 tag，检查所有 group 输出文件格式正确

## 7. 风险与应对

- **API 限流**：默认并发 1，可调高；加请求间隔；重试机制兜底
- **LLM 输出格式不合法**：prompt 中强调 JSON 格式；解析失败自动重试；重试后仍失败人工介入
- **wiki 匹配不准**：复用 search_wiki.py 已验证的模糊搜索逻辑；wiki 为空的 tag 仍可仅凭 tag name 翻译
