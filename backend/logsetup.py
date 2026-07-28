"""
Ghi log hoạt động của backend để chẩn đoán lỗi từ xa (vd máy đồng nghiệp bị
treo/chậm mà không rõ nguyên nhân) — không cần đồng nghiệp hiểu gì cả, log
tự chạy nền, người quản trị đọc lại trên máy mình sau khi Shared Drive đồng
bộ xong.

Ghi ra file LOCAL trước (nhanh, không phụ thuộc Google Drive), rồi định kỳ
copy file đó lên Shared Drive (_logs/<tên máy>.log) — KHÔNG ghi trực tiếp
lên Shared Drive mỗi request, vì chính kiểu ghi file dồn dập lên ổ đĩa ảo
của Google Drive là nghi phạm gây treo mà log này đang muốn tìm ra.
"""

import logging
import os
import shutil
import tempfile
import threading
import time
from logging.handlers import RotatingFileHandler

SYNC_INTERVAL_SECONDS = 30


def _machine_name():
    return os.environ.get("COMPUTERNAME") or os.environ.get("USERNAME") or "unknown"


def setup_logging(data_root):
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

    remote_dir = os.path.join(data_root, "_logs")
    remote_path = os.path.join(remote_dir, f"{machine}.log")

    def _sync_once():
        try:
            os.makedirs(remote_dir, exist_ok=True)
            shutil.copyfile(local_path, remote_path)
        except OSError:
            pass  # đồng bộ log là phụ — lỗi ở đây không được làm ảnh hưởng app chính

    def _sync_loop():
        while True:
            _sync_once()
            time.sleep(SYNC_INTERVAL_SECONDS)

    threading.Thread(target=_sync_loop, daemon=True).start()

    return logger
