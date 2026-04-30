"""
读取 danbooru_wikis_full 数据集的脚本
数据集: https://huggingface.co/datasets/itterative/danbooru_wikis_full
"""
import pandas as pd
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

FILES = {
    # "artist_urls": "artist_urls.parquet",
    # "artists": "artists.parquet",
    "tag_aliases": "tag_aliases.parquet",
    "tag_groups": "tag_groups.parquet",
    # "tag_implications": "tag_implications.parquet",
    # "tag_versions": "tag_versions.parquet",
    # "tags": "tags.parquet",
    "wiki_pages": "wiki_pages.parquet",
}


def wrap_text(text: str, width: int = 80) -> str:
    """长文本自动换行"""
    import textwrap
    return '\n'.join(textwrap.wrap(str(text), width=width))

def load(name: str) -> pd.DataFrame:
    path = DATA_DIR / FILES[name]
    df = pd.read_parquet(path)
    print(f"\n{'=' * 60}")
    print(f" {name}.parquet - {len(df)} rows, {len(df.columns)} columns")
    print(f"{'=' * 60}")
    print(f"Columns: {list(df.columns)}")
    print(f"\nFirst 5 rows:")

    # 长文本自动换行
    pd.set_option('display.max_colwidth', 100)
    pd.set_option('display.width', 200)

    for i in range(min(5, len(df))):
        row = df.iloc[i]
        print(f"\n--- Row {i} ---")
        for col in df.columns:
            val = row[col]
            if isinstance(val, str) and len(val) > 80:
                print(f"  {col}:")
                print(f"    {wrap_text(val, 60)}")
            else:
                print(f"  {col}: {val}")
    return df


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    for name in FILES:
        load(name)