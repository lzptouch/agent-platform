"""命令行入库脚本：python -m scripts.ingest_data"""
import logging

from app.services.rag.ingest import ingest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

if __name__ == "__main__":
    stats = ingest(recreate=True)
    print(f"入库完成: {stats}")
