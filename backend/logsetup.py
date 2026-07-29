"""
Ghi log hoạt động của backend để chẩn đoán lỗi từ xa (vd máy đồng nghiệp bị
treo/chậm mà không rõ nguyên nhân) — không cần đồng nghiệp hiểu gì cả, log
tự chạy nền, người quản trị đọc lại trên máy mình sau khi Drive đồng bộ xong.

Ghi ra file LOCAL trước (nhanh, không phụ thuộc mạng), rồi định kỳ đẩy file
đó lên Google Drive (qua drive_store.py, gọi thẳng API — KHÔNG còn copy vào
1 ổ đĩa mạng ánh xạ như trước, vì đó chính là kiểu thao tác từng gây treo
trên máy đồng nghiệp mà log này dùng để chẩn đoán).
"""

import logging
import os
import tempfile
import threading
import time
from logging.handlers import RotatingFileHandler

from drive_store import get_shared_sync

SYNC_INTERVAL_SECONDS = 30


def _machine_name():
    return os.environ.get("COMPUTERNAME") or os.environ.get("USERNAME") or "unknown"


def setup_logging():
    machine = _machine_name()

    local_dir = os.path.join(tempfile.gettempdir(), "rb-control-logs")
    os.makedirs(local_dir, exist_ok=True)
    local_path = os.path.join(local_dir, f"{machine}.log")

    logger = logging.getLogger("rbcontrol")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    handler = RotatingFileHandler(local_path, maxBytes=2_000_000, backupCount=1, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(handler)

    def _sync_loop():
        while True:
            try:
                get_shared_sync().upload_log_file(f"{machine}.log", local_path)
            except Exception:
                pass  # đồng bộ log là phụ — lỗi ở đây không được ảnh hưởng app chính
            time.sleep(SYNC_INTERVAL_SECONDS)

    threading.Thread(target=_sync_loop, daemon=True).start()

    return logger
