"""
从 wiki_pages.parquet 根据 title 搜索
支持: 模糊查询, 下划线模糊转换查询
"""
import pandas as pd
import re
from pathlib import Path

DATA_FILE = Path(__file__).parent / "data" / "wiki_pages.parquet"


def load_data() -> pd.DataFrame:
    return pd.read_parquet(DATA_FILE)


def fuzzy_search(df: pd.DataFrame, query: str, limit: int = 20) -> pd.DataFrame:
    """
    模糊搜索:
    - 原始查询
    - 下划线转空格 (touhou_project -> touhou project)
    - 下划线转空 (touhou_project -> touhouproject)
    """
    q = query.strip().lower()

    # 生成查询变体
    variants = [q]
    if '_' in q:
        variants.extend([
            q.replace('_', ' '),   # 下划线转空格
            q.replace('_', ''),    # 下划线转空
        ])
    else:
        variants.append(q.replace(' ', '_'))  # 空格转下划线

    results = []
    for v in variants:
        mask = df['title'].str.lower().str.contains(v, na=False)
        results.append(df[mask].copy())
        if len(results[-1]) > 0:
            break

    if not results or len(results[-1]) == 0:
        return pd.DataFrame()

    result = results[-1].head(limit)
    return result


def search_by_title(query: str, limit: int = 20) -> pd.DataFrame:
    df = load_data()
    return fuzzy_search(df, query, limit)


def wrap_text(text: str, width: int = 80) -> str:
    import textwrap
    return '\n'.join(textwrap.wrap(str(text), width=width))


def print_results(results: pd.DataFrame):
    if results.empty:
        print("No results found.")
        return

    print(f"\nFound {len(results)} results:")
    print("=" * 60)

    for i, row in results.iterrows():
        print(f"\n--- {row['title']} (id: {row['id']}) ---")
        body = str(row['body'])[:300].replace('\r\n', '\n')
        print(f"  {body}...")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')

    query = input("Enter search query: ").strip()
    if not query:
        print("Empty query.")
        exit()

    results = search_by_title(query)
    print_results(results)

    # 示例: 搜索 "touhou_project"
    # results = search_by_title("touhou_project")
    # print_results(results)