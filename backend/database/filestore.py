"""
Lưu trữ kiểu file — thay thế hoàn toàn PostgreSQL/Supabase để app chạy được
100% offline trên từng máy, đồng bộ giữa các máy qua Google Drive (Shared
Drive) thay vì qua 1 server database chung.

Nguyên tắc: MỖI BẢN GHI LÀ 1 FILE JSON RIÊNG (không dùng 1 file DB chung) —
để 2 máy chỉ "đụng nhau" khi cùng sửa đúng 1 bản ghi cùng lúc (hiếm), thay vì
đụng nhau mỗi khi bất kỳ ai ghi bất cứ gì (chắc chắn xảy ra nếu dùng 1 file
chung, dễ hỏng cả file).

ID vẫn giữ kiểu số (không đổi sang UUID chuỗi) để toàn bộ code frontend hiện
tại (các chỗ onclick="...(${item.id})" không có dấu nháy) chạy đúng mà không
cần sửa gì — dùng số ngẫu nhiên lớn (52-bit) thay cho auto-increment, để
nhiều máy tạo bản ghi cùng lúc mà không lo trùng ID.

Thư mục gốc lấy từ biến môi trường DATA_ROOT (đặt vào đúng thư mục trong
Shared Drive, vd "G:\\Shared drives\\Charge Station Documents\\App Data").
"""

import glob
import json
import os
import random
import tempfile


def get_data_root():
    root = os.environ.get("DATA_ROOT")
    if not root:
        # Mặc định dùng khi chạy dev cục bộ, chưa cấu hình DATA_ROOT.
        root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "local_data")
    return root


def _collection_dir(collection):
    d = os.path.join(get_data_root(), collection)
    os.makedirs(d, exist_ok=True)
    return d


def _record_path(collection, record_id):
    return os.path.join(_collection_dir(collection), f"{record_id}.json")


def new_id():
    """Số ngẫu nhiên 52-bit — nằm gọn trong Number.MAX_SAFE_INTEGER của JS,
    xác suất trùng giữa nhiều máy tạo cùng lúc gần như bằng 0."""
    return random.getrandbits(52)


def list_records(collection):
    """Đọc toàn bộ bản ghi trong 1 collection, mới nhất trước (theo id giảm dần
    - id lớn hơn = tạo sau, vì new_id() dùng số ngẫu nhiên nên xấp xỉ ngẫu
    nhiên về thời gian; các API cần sort theo thời gian thật nên tự sort lại
    theo time_label/created_at khi cần)."""
    items = []
    for path in glob.glob(os.path.join(_collection_dir(collection), "*.json")):
        try:
            with open(path, "r", encoding="utf-8") as f:
                items.append(json.load(f))
        except (OSError, json.JSONDecodeError):
            continue  # bỏ qua file lỗi/đang ghi dở, không làm sập cả danh sách
    return items


def get_record(collection, record_id):
    path = _record_path(collection, record_id)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def save_record(collection, record_id, data):
    """Ghi đè hoặc tạo mới 1 bản ghi. Ghi ra file tạm rồi rename để tránh file
    bị dở dang nếu app tắt đột ngột giữa lúc ghi."""
    path = _record_path(collection, record_id)
    dir_ = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp_", dir=dir_)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def delete_record(collection, record_id):
    path = _record_path(collection, record_id)
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def find_one(collection, predicate):
    """Tìm 1 bản ghi đầu tiên khớp điều kiện — thay cho SQL WHERE ... LIMIT 1."""
    for item in list_records(collection):
        if predicate(item):
            return item
    return None


def find_all(collection, predicate):
    """Tìm mọi bản ghi khớp điều kiện — thay cho SQL WHERE ..."""
    return [item for item in list_records(collection) if predicate(item)]
