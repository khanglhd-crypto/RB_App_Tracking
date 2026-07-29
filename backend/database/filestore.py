"""
Lưu trữ kiểu file — nay ủy quyền toàn bộ cho drive_store.py (gọi thẳng
Google Drive API), thay vì đọc/ghi trực tiếp vào 1 ổ đĩa mạng ánh xạ (mapped
drive qua Google Drive for Desktop — hay lỗi vặt: Paused, nhầm ổ đĩa,
Stream/Mirror...).

Giữ NGUYÊN chữ ký các hàm cũ (list_records, get_record, save_record,
delete_record, find_one, find_all, new_id) để toàn bộ code ở api/*.py không
cần sửa gì — chỉ đổi bên trong cách lưu trữ hoạt động.

ID vẫn giữ kiểu số (không đổi sang UUID chuỗi) để code frontend hiện tại
(các chỗ onclick="...(${item.id})" không có dấu nháy) chạy đúng mà không
cần sửa gì — dùng số ngẫu nhiên lớn (52-bit) thay cho auto-increment, để
nhiều máy tạo bản ghi cùng lúc mà không lo trùng ID.
"""

import random

from drive_store import get_shared_sync as _get_sync


def new_id():
    """Số ngẫu nhiên 52-bit — nằm gọn trong Number.MAX_SAFE_INTEGER của JS,
    xác suất trùng giữa nhiều máy tạo cùng lúc gần như bằng 0."""
    return random.getrandbits(52)


def is_ready():
    """True khi collection "users" đã tải xong từ Drive — dùng để /api/health
    báo cho Electron biết lúc nào thật sự nên mở cửa sổ (tránh mở app sớm rồi
    người dùng đăng nhập ngay lúc dữ liệu chưa kịp tải xong)."""
    return _get_sync().is_ready()


def list_records(collection):
    return _get_sync().list_records(collection)


def get_record(collection, record_id):
    return _get_sync().get_record(collection, record_id)


def save_record(collection, record_id, data):
    _get_sync().save_record(collection, record_id, data)


def delete_record(collection, record_id):
    return _get_sync().delete_record(collection, record_id)


def find_one(collection, predicate):
    """Tìm 1 bản ghi đầu tiên khớp điều kiện — thay cho SQL WHERE ... LIMIT 1."""
    for item in list_records(collection):
        if predicate(item):
            return item
    return None


def find_all(collection, predicate):
    """Tìm mọi bản ghi khớp điều kiện — thay cho SQL WHERE ..."""
    return [item for item in list_records(collection) if predicate(item)]
