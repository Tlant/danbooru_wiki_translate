# Danbooru Tag 中文翻译项目

## 项目概述

对 [Danbooru](https://danbooru.donmai.us) 网站的插画标签(tag)进行精准的中文翻译。

Danbooru 是二次元插画网站，使用简略的英文短语对图片打标（如 `cock_ring`、`thighhighs`）。本项目的 tag 数据来自 Danbooru 官方分类——每个 tag 归属于一个 tag group（如 `sex_objects`、`attire`），group 之下再按 category 细分（如 `Sex Toys`、`Fluids`）。

翻译借助 DeepSeek LLM，利用 tag + group/category 路径 + 官方 wiki 说明作为联合上下文，确保翻译准确。

### 数据规模

| 数据项 | 数量 |
|--------|------|
| Tag Group 文件 | 54 个 |
| Tag 条目总数 | ~9320 条 |
| 去重后唯一 Tag | 8308 个 |
| Wiki 总页面 | 204,442 条 |
| 匹配到 Wiki 的 Tag | ~6956 个 (84%) |

---

## 目录结构

```
danbooru_wiki/
├── config.py              # 所有可调参数（模型、批量、并发、路径等）
├── context_builder.py     # 上下文构造：解析 tag JSON + 查询 wiki
├── llm_client.py          # LLM 客户端：DeepSeek API 封装 + prompt 设计
├── translator.py          # 翻译调度器：批量、并发、重试、断点续跑
├── merger.py              # 结果合并：缓存 → tag group 输出文件
├── main.py                # 入口脚本（CLI 参数）
├── search_wiki.py          # [工具] wiki 模糊搜索（独立使用）
├── read_data.py            # [工具] 读取 parquet 数据集（独立使用）
├── note.md                 # 需求文档
├── plan.md                 # 设计文档
│
├── data/
│   ├── tag_group/          # 输入：54 个 tag group JSON
│   │   ├── accessories.json
│   │   ├── attire.json
│   │   ├── sex_objects.json
│   │   └── ...
│   ├── danbooru_wikis_full/  # 输入：Danbooru 官方 wiki 数据集 (parquet)
│   │   └── wiki_pages.parquet
│   ├── cache/              # 缓存：逐 tag 翻译结果 + 进度文件
│   │   ├── progress.json   #   全局进度跟踪
│   │   ├── contexts.json   #   全量上下文快照（调试用）
│   │   └── {tag_name}.json #   每个 tag 一个翻译结果文件
│   └── translated/         # 输出：翻译后的 tag group JSON
│       ├── accessories.json
│       ├── sex_objects.json
│       └── ...
└── .venv/                  # Python 虚拟环境
```

---

## 数据源详解

### Tag Group JSON 格式

`data/tag_group/*.json` — 从 Danbooru wiki 页面抓取的 tag 分组数据。

```json
{
  "group_name": "sex_objects",
  "display_name": "Tag group:sex objects",
  "categories": [
    {"h4": "Sex Toys", "path": "Sex Toys", "tag_count": 96},
    {"h4": "Fluids", "path": "Fluids", "tag_count": 5}
  ],
  "tags": [
    {
      "name": "anal beads",
      "tag_type": 0,
      "wiki_url": "/wiki_pages/anal_beads",
      "category_path": "Sex Toys",
      "wiki_exists": true
    }
  ]
}
```

关键字段：
- `group_name`：tag 所属分组标识
- `tags[].name`：tag 原始英文名
- `tags[].category_path`：tag 在组内的分类路径
- `tags[].wiki_exists`：Danbooru 官方是否有该 tag 的 wiki 页面

### Wiki Parquet 格式

`data/danbooru_wikis_full/wiki_pages.parquet` — 来自 [HuggingFace itterative/danbooru_wikis_full](https://huggingface.co/datasets/itterative/danbooru_wikis_full)。

| 列名 | 类型 | 说明 |
|------|------|------|
| `id` | int | wiki 页面 ID |
| `title` | str | 页面标题（与 tag name 相同或变体） |
| `body` | str | wiki 正文，包含 wikitext 标记 |
| `is_deleted` | bool | 是否已删除 |
| `created_at` | timestamp | 创建时间 |
| `updated_at` | timestamp | 更新时间 |
| `is_locked` | bool | 是否锁定 |
| `other_names` | list | 别名列表 |

**Tag→Wiki 匹配逻辑**（见 `context_builder.py:_search_wiki`）：
1. 精确匹配 tag name（转为小写）
2. 若 tag 含下划线，按下划线转空格再匹配
3. 若 tag 含下划线，去掉下划线再匹配
4. 若 tag 含空格，转为下划线再匹配
5. 取第一条匹配结果，截取 body 前 500 字符

---

## 架构设计

### 整体数据流

```
tag_group/*.json  ────┐
                      ├──> context_builder ──> contexts ──> translator ──> cache/*.json
wiki_pages.parquet ───┘                                         │
                                                            progress.json
                                                                 │
cache/*.json ──────────────────────────────────> merger ──> translated/*.json
tag_group/*.json ────────────────────────────────┘
```

### 模块关系图

```
main.py
  ├── context_builder.py
  │     ├── load_tag_groups()     → 读取所有 tag group JSON
  │     ├── extract_unique_tags() → 去重，按 tag name 取 first-seen
  │     ├── _prep_wiki_df()       → 加载 wiki parquet，过滤已删除
  │     └── _search_wiki()        → 模糊匹配 wiki title
  ├── translator.py
  │     ├── load_cache()          → 扫描现有缓存，去重跳过
  │     ├── load_progress()       → 读取进度文件
  │     ├── chunk_list()          → 按 BATCH_SIZE 分批
  │     ├── _translate_batch_with_retry() → 调用 LLM + 重试
  │     └── _dry_run()            → 预览 prompt 不调 API
  ├── merger.py
  │     ├── load_all_cached()     → 加载所有缓存
  │     └── merge_one_group()     → 单 group 合并
  ├── llm_client.py
  │     ├── _build_context_json() → 序列化上下文
  │     ├── translate_batch()     → 调用 DeepSeek API
  │     ├── _parse_response()     → 从响应中提取 JSON
  │     └── preview_prompt()      → 返回 prompt 文本（dry-run 用）
  └── config.py                   → 全局配置常量
```

---

## 模块详解

### 1. `config.py` — 配置中心

项目所有可调参数集中于此，无命令行参数依赖（除 `--dry-run`、`--stats` 等模式切换）。

```python
# LLM
LLM_BASE_URL = "https://api.deepseek.com"
LLM_API_KEY = "sk-f035d1e0c2354c4eaf809c9f3526fd99"
LLM_MODEL = "deepseek-v4-pro"
AVAILABLE_MODELS = ["deepseek-v4-pro", "deepseek-v4-flash"]

# 翻译策略
BATCH_SIZE = 15           # 每批翻译 tag 数（1=逐条高质量, 10-20=均衡）
MAX_CONCURRENCY = 1       # 并发线程数
REQUEST_INTERVAL = 0.5    # 提交两个 batch 之间的等待秒数

# 重试
MAX_RETRIES = 3           # 每批最大重试次数
RETRY_BACKOFF = 2.0       # 指数退避倍率（第n次等待 2^n 秒）

# Wiki 截断
WIKI_MAX_CHARS = 500      # wiki 正文最大字符数（过长会撑爆 prompt）

# 模式
DRY_RUN = False           # True=只预览 prompt 不调 API
```

**修改建议**：
- 追求质量：`BATCH_SIZE = 1`、`LLM_MODEL = "deepseek-v4-pro"`
- 追求速度/省钱：`BATCH_SIZE = 20`、`LLM_MODEL = "deepseek-v4-flash"`
- 服务器性能好：调高 `MAX_CONCURRENCY`（注意 API 限流）
- 网络不稳定：调高 `MAX_RETRIES`

### 2. `context_builder.py` — 上下文构造器

**核心函数**：

| 函数 | 说明 |
|------|------|
| `load_tag_groups()` | 遍历 `data/tag_group/*.json`，返回 `list[dict]` |
| `extract_unique_tags(groups)` | 按 `tag.name` 去重，保留 first-seen 的 group 归属 |
| `_prep_wiki_df()` | 加载 parquet，过滤 `is_deleted=True`，新增 `title_lower` 列 |
| `_search_wiki(df, tag_name)` | 多级模糊匹配，返回 wiki body 或空串 |
| `build_contexts(tags, wiki_df)` | 为每个 tag 附上 wiki 文本 |
| `build_all()` | 一键流程，返回 8308 个上下文字典 |
| `save_contexts_to_json(contexts, path)` | 保存上下文快照到 `data/cache/contexts.json` |

**去重策略**：同一 tag name 可能出现在多个 group（如 `torn_clothes` 同时属于 `attire` 和 `body_parts`），采用 first-seen 原则——仅保留第一次遇到的 group 归属。翻译后，merger 会将该翻译复制到所有含此 tag 的 group 输出中。

**Wiki 匹配**：采用与 `search_wiki.py` 相同的多级模糊匹配。tag `cock_ring` 会依次尝试 `cock_ring` → `cock ring` → `cockring`。只查询 `wiki_exists=True` 的 tag，避免无效查询。

**输出格式**：
```json
{
  "tag": "cock_ring",
  "group_name": "sex_objects",
  "category_path": "Sex Toys",
  "wiki": "A ring at the base of the penis that constricts blood flow..."
}
```

### 3. `llm_client.py` — LLM 客户端

**类 `LLMClient`**：
```python
class LLMClient:
    def __init__(self, base_url, api_key, model)
    def translate_batch(self, contexts: list[dict]) -> list[dict]  # 核心方法
    def preview_prompt(self, contexts: list[dict]) -> str           # dry-run 用
```

**API 调用参数**（与 DeepSeek 文档一致）：
```python
response = client.chat.completions.create(
    model=self.model,
    messages=[...],
    stream=False,
    reasoning_effort="high",
    extra_body={"thinking": {"type": "enabled"}},
)
```

**Prompt 结构**：

- **System Prompt**：定位为"二次元插画标签翻译专家"，给出三条翻译指南：
  1. `tag_cn`：2-6 字短翻译，ACG 圈子有惯例词的用惯例词
  2. `confidence`：A=很确定，B=基本确定，C=有歧义，D=需人工审核
  3. `tag_cn_long`：一句话中文释义
  4. 强调只输出 JSON，不要 markdown

- **User Prompt**：包含 tag 数量 + 上下文 JSON + 输出格式模板

**响应解析 `_parse_response()`**：
1. 去除可能的 ```json ``` 代码块包裹
2. 查找 `[...]` 边界
3. `json.loads()` 解析

**修改 prompt 的注意事项**：
- 中文 prompt 可能导致 LLM 在输出中夹杂中文说明，需要强调"只输出 JSON"
- 如果 LLM 频繁输出格式错误，考虑在 `_parse_response()` 中添加更多容错逻辑

### 4. `translator.py` — 翻译调度器（核心模块）

**核心函数**：

| 函数 | 说明 |
|------|------|
| `load_cache()` | 扫描 `data/cache/*.json`，构建 `{tag_name: result}` 映射 |
| `save_tag_cache(result)` | 写入单个 tag 的翻译结果文件 |
| `load_progress()` / `save_progress()` | 读写 `progress.json` |
| `_validate_result(item)` | 校验翻译结果含 `tag/tag_cn/confidence/tag_cn_long` |
| `_translate_batch_with_retry(client, batch)` | 调 LLM 并指数退避重试 |
| `translate_all(contexts)` | 主入口，编排全流程 |
| `_dry_run(batches)` | 打印前 3 个 batch 的 prompt |

**断点续跑机制**：

```
启动时
  ├── 扫描 data/cache/ 下所有 {tag}.json
  ├── 构建已完成集合 {tag_name, ...}
  ├── 从 context 列表中剔除已完成的 tag
  └── 继续翻译剩余 tag

中断后重启
  └── 同上逻辑，自动跳过已翻译的 tag
```

**缓存文件格式**（`data/cache/{tag_name}.json`）：
```json
{
  "tag": "cock_ring",
  "tag_cn": "阴茎环",
  "confidence": "A",
  "tag_cn_long": "套在阴茎根部用于维持勃起的性玩具。"
}
```
文件名由 tag name 生成，`/` 和 `\` 替换为 `_`。

**进度文件格式**（`data/cache/progress.json`）：
```json
{
  "total": 8308,
  "completed": ["1girl", "1boy", "absurdres", ...],
  "failed_batches": [
    "tag_a,tag_b,tag_c",
    "..."
  ]
}
```

**重试逻辑**：
- 单批最多重试 `MAX_RETRIES` 次
- 等待时间 = `RETRY_BACKOFF ^ attempt`（2、4、8 秒）
- 全部重试失败后记录 `failed_batches` 并继续下一批
- 下次运行时自动跳过 `failed_batches` 中的批次

**并发模型**：
- 使用 `concurrent.futures.ThreadPoolExecutor`
- `MAX_CONCURRENCY` 控制线程数
- 提交每个 batch 之间 `sleep(REQUEST_INTERVAL)` 防止瞬间堆满连接

### 5. `merger.py` — 结果合并器

**职责**：将分散的 `data/cache/{tag}.json` 翻译结果，按原始 tag group 结构聚合输出。

**流程**：
```
遍历 data/tag_group/*.json
  ├── 读取原始 group JSON
  ├── 遍历 group 内每个 tag
  │     ├── 在 cache 中查找 tag.name
  │     ├── 若找到：附加 tag_cn / confidence / tag_cn_long
  │     └── 若缺失：填入空字符串
  └── 写入 data/translated/{group_name}.json
```

**输出格式**（以 `sex_objects.json` 为例）：
```json
{
  "group_name": "sex_objects",
  "display_name": "Tag group:sex objects",
  "source_url": "/wiki_pages/tag_group%3Asex_objects",
  "url": "https://danbooru.donmai.us/wiki_pages/tag_group%3Asex_objects",
  "categories": [ ... ],
  "tags": [
    {
      "name": "anal beads",
      "tag_type": 0,
      "wiki_url": "/wiki_pages/anal_beads",
      "category_path": "Sex Toys",
      "wiki_exists": true,
      "tag_cn": "肛门拉珠",
      "confidence": "A",
      "tag_cn_long": "一种用于肛门刺激的性玩具，由多个珠子串联而成。"
    }
  ]
}
```

### 6. `main.py` — 入口脚本

```bash
# 完整流程：构造上下文 → 翻译 → 合并 → 统计
.venv/Scripts/python main.py

# 只预览 prompt，不调用 API（检查 wiki 匹配是否正确）
.venv/Scripts/python main.py --dry-run

# 只执行合并（跳过翻译，用于重新生成输出文件）
.venv/Scripts/python main.py --merge-only

# 查看缓存和进度统计
.venv/Scripts/python main.py --stats
```

**完整执行流程**：
```
main.py (无参数)
  ├── cmd_translate()
  │     ├── context_builder.build_all()      # 构造 8308 个上下文
  │     ├── 保存 contexts.json 到 cache/    # 完整上下文快照
  │     └── translator.translate_all()       # 批量翻译
  ├── cmd_merge()
  │     └── merger.merge_all()              # 生成 54 个输出文件
  └── cmd_stats()                            # 打印翻译统计
```

---

## 使用指南

### 环境准备

```bash
# 1. 进入项目目录
cd d:/AI_coding/danbooru_wiki

# 2. 激活虚拟环境（Windows）
.venv\Scripts\activate

# 3. 安装依赖
pip install openai pandas pyarrow

# 4. （可选）配置 HTTP 代理
# 见下方"代理配置"章节
```

### 第一次运行建议

```bash
# Step 1：dry-run 检查 wiki 匹配质量
.venv/Scripts/python main.py --dry-run

# Step 2：小批量测试（先修改 config.py）
#   BATCH_SIZE = 3
#   MAX_CONCURRENCY = 1
# 然后手动运行 translator 只翻译 10 个 tag 验证流程
.venv/Scripts/python -c "
import json
from context_builder import build_all
from translator import translate_all

contexts = build_all()
results = translate_all(contexts[:10])
print(json.dumps(results, ensure_ascii=False, indent=2))
"

# Step 3：确认结果质量后，改回 BATCH_SIZE=15，运行全量
.venv/Scripts/python main.py
```

### 中断恢复

翻译中途可以随时 `Ctrl+C` 中断。再次运行 `main.py` 时会自动跳过已翻译的 tag。

```bash
# 中断后查看进度
.venv/Scripts/python main.py --stats

# 继续翻译
.venv/Scripts/python main.py
```

### 重新合并输出

翻译缓存保留在 `data/cache/` 中。如果修改了 merger 逻辑或想换一种输出格式，无需重新翻译：

```bash
.venv/Scripts/python main.py --merge-only
```

---

## 代理配置（待实现）

`note.md` 要求网络交互使用 HTTP 代理 `http://127.0.0.1:10801`。

**实现方式**：在 `llm_client.py` 的 `LLMClient.__init__()` 中，通过 `httpx.Client` 传入代理：

```python
import httpx

proxy_url = "http://127.0.0.1:10801"
http_client = httpx.Client(proxy=proxy_url)
self.client = OpenAI(
    api_key=api_key,
    base_url=base_url,
    http_client=http_client,
)
```

**建议**：在 `config.py` 增加 `HTTP_PROXY` 配置项，设为 `None` 则直连，设为 URL 字符串则走代理。

---

## 工程特性总结

| 特性 | 实现方式 | 对应模块 |
|------|----------|----------|
| 断点续跑 | `data/cache/{tag}.json` 逐文件缓存 + `progress.json` 进度跟踪 | `translator.py` |
| 结果缓存 | 每个 tag 一个 JSON 文件，tag name 去重后 ~8308 个文件 | `translator.py` |
| 失败重试 | 指数退避 `2^n` 秒，最多 3 次；失败批次记录到 progress | `translator.py` |
| 并发调用 | `ThreadPoolExecutor`，`MAX_CONCURRENCY` 可配 | `translator.py` |
| 批量/逐条可配 | `BATCH_SIZE` 设为 1 即方案 A，10-20 即方案 B | `config.py` |
| 模型可切换 | `LLM_MODEL` 选 pro/flash | `config.py` |
| Wiki 上下文 | 多级模糊匹配，截断至 500 字符 | `context_builder.py` |
| JSON 容错解析 | 自动去除 code fence，定位 `[...]` 边界 | `llm_client.py` |
| Dry-run | `--dry-run` 只预览 prompt，不调 API | `main.py` |

---

## 依赖清单

| 包 | 版本要求 | 用途 |
|----|----------|------|
| Python | >= 3.9 | 运行环境 |
| `openai` | (最新) | DeepSeek API 调用（OpenAI 兼容格式） |
| `pandas` | (已安装) | 读取 wiki_pages.parquet |
| `pyarrow` | (已安装) | pandas parquet 引擎 |

其余为标准库：`json`、`concurrent.futures`、`argparse`、`pathlib`、`re`、`time`、`traceback`、`textwrap`。

注意：项目使用了 `from __future__ import annotations` 以兼容 Python 3.9 的类型注解语法，如果升级到 Python 3.11+ 可以移除这些 import。

---

## 二次开发指引

### 常见修改场景

**1. 替换 LLM 提供商（如换成 OpenAI/Claude/本地模型）**

修改 `llm_client.py`：
- 替换 `LLMClient.__init__()` 中的 `base_url` 和 `api_key`
- 替换 `translate_batch()` 中的 API 调用方式
- 如果新 LLM 不支持 `reasoning_effort` 和 `extra_body`，删除这两个参数
- 如果新 LLM 输出格式不同，修改 `_parse_response()` 的解析逻辑

**2. 修改翻译 prompt**

修改 `llm_client.py` 中的 `SYSTEM_PROMPT` 和 `USER_PROMPT_TEMPLATE`。常见调整：
- 增加更多翻译示例（few-shot）
- 改为使用中文 prompt（当前 system prompt 为英文）
- 增加输出字段（如 `tag_cn_alt`）

**3. 修改 Wiki 匹配策略**

修改 `context_builder.py:_search_wiki()`：
- 增加更多匹配变体
- 使用模糊匹配（`str.contains`）代替精确匹配
- 返回多条 wiki 供 LLM 参考
- 调整 `WIKI_MAX_CHARS` 截断长度

**4. 按 confidence 分级审核**

翻译完成后按 confidence 筛选人工审核项：
```python
import json, os
# 读取所有 D 级 translation
for f in os.listdir("data/cache"):
    with open(f"data/cache/{f}") as fp:
        data = json.load(fp)
    if isinstance(data, dict) and data.get("confidence") == "D":
        print(f"{data['tag']}: {data['tag_cn_long']}")
```

**5. 增量翻译新增 tag**

如果后续增加了新的 tag group 文件：
1. 将新 JSON 放入 `data/tag_group/`
2. 重新运行 `main.py`——已翻译的 tag 从缓存恢复，新 tag 自动翻译

**6. 重新翻译指定 tag（覆盖缓存）**

手动删除对应的缓存文件：
```bash
rm data/cache/{tag_name}.json
```
再运行 `main.py` 即可重新翻译该 tag。

### 项目中的关键约定

1. **Python 路径**：始终使用 `.venv/Scripts/python`（Windows）或 `.venv/bin/python`（Linux/Mac）运行脚本
2. **编码**：所有文件读写使用 `encoding="utf-8"`，入口脚本调用 `sys.stdout.reconfigure(encoding="utf-8")`
3. **路径**：所有路径通过 `config.py` 中的 `PROJECT_ROOT` 派生，使用 `pathlib.Path`，不要硬编码
4. **缓存文件名**：使用 `tag.name.replace("/", "_").replace("\\", "_")` 生成合法文件名
5. **类型注解**：`from __future__ import annotations` 使 `X | None` 语法在 Python 3.9 生效
