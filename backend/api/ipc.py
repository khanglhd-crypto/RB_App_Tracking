"""
Test IPC API.

Exposes:
  GET  /api/ipc-list.php    - danh sách IPC
  POST /api/ipc-save.php    - thêm IPC mới (kèm ảnh SN/AnyDesk/UltraView, nếu có)
  POST /api/ipc-status.php  - đổi trạng thái IPC
  POST /api/ipc-delete.php  - xóa 1 IPC
  GET  /api/ipc-photo.php   - xem lại 1 ảnh đã lưu (?id=...&field=sn|anydesk|ultraview)

Ảnh SN/AnyDesk/UltraView được tải thẳng lên Google Drive (thư mục gốc
"IPC/<mã SN>/SN.jpg | AnyDesk.jpg | UltraView.jpg") qua drive_store.py —
không còn ghi trực tiếp vào ổ đĩa Google Drive for Desktop ánh xạ (hay lỗi
Access denied/Paused không rõ nguyên nhân) nữa. Chỉ Drive fileId được ghi
vào bản ghi JSON (không lưu base64 trong đó).
"""

import base64
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from flask import Blueprint, Response, jsonify, request

from audit import log_action
from database import filestore
from drive_store import get_shared_sync

ipc_bp = Blueprint("ipc", __name__, url_prefix="/api")

IPC_BASE_FOLDER = "IPC"
COLLECTION = "ipc_list"

PHOTO_FIELD_KEYS = {
    "sn": ("sn_photo_path", "SN"),
    "anydesk": ("anydesk_photo_path", "AnyDesk"),
    "ultraview": ("ultraview_photo_path", "UltraView"),
}


def _safe_name(name):
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip() or "unnamed"


def _row_to_item(row):
    return {
        "id": row["id"],
        "sn": row.get("sn", ""),
        "anydesk": row.get("anydesk") or "",
        "ultraview": row.get("ultraview") or "",
        "note": row.get("note") or "",
        "status": row.get("status", "configuring"),
        "hasSnPhoto": bool(row.get("sn_photo_path")),
        "hasAnydeskPhoto": bool(row.get("anydesk_photo_path")),
        "hasUltraviewPhoto": bool(row.get("ultraview_photo_path")),
        "time": row.get("time_label", ""),
    }


@ipc_bp.route("/ipc-list.php", methods=["GET"])
def ipc_list():
    rows = filestore.list_records(COLLECTION)
    rows.sort(key=lambda r: r.get("id", 0), reverse=True)
    return jsonify({"ok": True, "items": [_row_to_item(r) for r in rows]})


@ipc_bp.route("/ipc-save.php", methods=["POST"])
def ipc_save():
    data = request.get_json(silent=True) or {}
    sn = (data.get("sn") or "").strip()
    if not sn:
        return jsonify({"ok": False, "error": "Thiếu mã SN"}), 400

    if filestore.find_one(COLLECTION, lambda r: r.get("sn") == sn):
        return jsonify({"ok": False, "error": f"Mã SN \"{sn}\" đã tồn tại"}), 400

    time_label = datetime.now().strftime("%d/%m/%Y %H:%M")

    photo_paths = {"sn": None, "anydesk": None, "ultraview": None}

    def _upload_one(field_and_label):
        field, (_, label) = field_and_label
        data_url = data.get(f"{field}Photo")
        if not data_url:
            return field, None
        header, b64data = data_url.split(",", 1)
        raw = base64.b64decode(b64data)
        filename = f"{label}.jpg"
        file_id = sync.upload_named_file(folder_id, filename, raw, "image/jpeg", known_id=known_names.get(filename))
        return field, file_id

    try:
        sync = get_shared_sync()
        folder_id = sync.resolve_folder_path(IPC_BASE_FOLDER, [_safe_name(sn)])
        known_names = sync.list_folder_names(folder_id)
        # Toi da 3 anh (SN/AnyDesk/UltraView), doc lap nhau -> tai song song
        # thay vi tuan tu de khong cong don do tre mang.
        with ThreadPoolExecutor(max_workers=3) as executor:
            for field, file_id in executor.map(_upload_one, PHOTO_FIELD_KEYS.items()):
                photo_paths[field] = file_id
    except (ValueError, IndexError) as err:
        return jsonify({"ok": False, "error": f"Ảnh không hợp lệ: {err}"}), 400
    except Exception as err:
        return jsonify({"ok": False, "error": f"Không lưu được ảnh IPC lên Drive: {err}"}), 500

    new_id = filestore.new_id()
    filestore.save_record(COLLECTION, new_id, {
        "id": new_id,
        "sn": sn,
        "anydesk": data.get("anydesk") or "",
        "ultraview": data.get("ultraview") or "",
        "note": data.get("note") or "",
        "status": data.get("status") or "configuring",
        "sn_photo_path": photo_paths["sn"],
        "anydesk_photo_path": photo_paths["anydesk"],
        "ultraview_photo_path": photo_paths["ultraview"],
        "time_label": time_label,
    })

    log_action("ipc", "create", target=sn)
    return jsonify({"ok": True, "id": new_id})


@ipc_bp.route("/ipc-photo.php", methods=["GET"])
def ipc_photo():
    record_id = request.args.get("id")
    field = request.args.get("field")
    if not record_id or field not in PHOTO_FIELD_KEYS:
        return jsonify({"ok": False, "error": "Thiếu id hoặc field không hợp lệ"}), 400

    key, _ = PHOTO_FIELD_KEYS[field]
    row = filestore.get_record(COLLECTION, record_id)
    file_id = row.get(key) if row else None

    if not file_id:
        return jsonify({"ok": False, "error": "IPC này chưa có ảnh"}), 404

    try:
        content = get_shared_sync().download_file_bytes(file_id)
    except Exception as err:
        return jsonify({"ok": False, "error": f"Không tải được ảnh từ Drive: {err}"}), 404

    return Response(content, mimetype="image/jpeg")


@ipc_bp.route("/ipc-status.php", methods=["POST"])
def ipc_status():
    data = request.get_json(silent=True) or {}
    record_id = data.get("id")
    status = data.get("status", "")
    if not record_id:
        return jsonify({"ok": False, "error": "Thiếu id"}), 400

    row = filestore.get_record(COLLECTION, record_id)
    if row:
        row["status"] = status
        filestore.save_record(COLLECTION, record_id, row)

    log_action("ipc", "update", target=str(record_id), detail=f"status={status}")
    return jsonify({"ok": True})


@ipc_bp.route("/ipc-delete.php", methods=["POST"])
def ipc_delete():
    data = request.get_json(silent=True) or {}
    record_id = data.get("id")
    if not record_id:
        return jsonify({"ok": False, "error": "Thiếu id"}), 400

    filestore.delete_record(COLLECTION, record_id)

    log_action("ipc", "delete", target=str(record_id))
    return jsonify({"ok": True})
