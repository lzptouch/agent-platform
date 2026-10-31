"""命令行入库脚本：python -m scripts.ingest_data

**幂等（批次 03 / WP-3.6）**：默认走增量模式（``recreate=False``）——
按「文件绝对路径 + 内容哈希」跳过已入库的文件，重复启动**不会重复入库**。

需要强制重建时加 ``--recreate``。
"""
import argparse
import logging

from app.services.rag.ingest import ingest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RAG 数据入库（幂等）")
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="重建 collection 并全量重灌（默认增量幂等）",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="确认执行破坏性操作（--recreate 必需）",
    )
    args = parser.parse_args()

    # **E10**：``--recreate`` 会**删除并重建**整个 collection → 丢掉全量向量数据。
    # 此前无任何确认 → 误传即造成不可逆的数据丢失。
    if args.recreate and not args.yes:
        print("[ingest] ✗ --recreate 会删除并重建 collection（全量向量数据丢失）。")
        print("[ingest]   确认无误后追加 --yes 重新运行。")
        raise SystemExit(2)

    stats = ingest(recreate=args.recreate)
    if stats.get("ingested", 0) == 0 and stats.get("skipped", 0) > 0:
        print(f"已是最新，无新增内容（跳过 {stats['skipped']} 个文档）: {stats}")
    else:
        print(f"入库完成: {stats}")
