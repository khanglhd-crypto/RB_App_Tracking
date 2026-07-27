"""
Test IPC API.

Exposes:
  GET  /api/ipc-list.php    - danh sách IPC
  POST /api/ipc-save.php    - thêm IPC mới (kèm ảnh SN/AnyDesk/UltraView, nếu có)
  POST /api/ipc-status.php  - đổi trạng thái IPC
  POST /api/ipc-delete.php  - xóa 1 IPC
  GET  /api/ipc-photo.php   - xem lại 1 ảnh đã lưu (?id=...&field=sn|anydesk|ultraview)

Ảnh SN/AnyDesk/UltraView được lưu trực tiếp trên máy chủ, vào:
    <root_path>/IPC/<mã SN>/SN.jpg | AnyDesk.jpg | UltraView.jpg
Chỉ đường dẫn file được ghi vào MySQL (không lưu base64 trong DB).
"""

import base64
import json
import os
import re
from datetime import datetime

import psycopg2
from flask import Blueprint, jsonify, request, send_file

from audit import log_action
from database.db import get_connection

ipc_bp = Blueprint("ipc", __name__, url_prefix="/api")

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "server_config.json")
IPC_FOLDER_NAME = "IPC"

PHOTO_FIELD_COLUMNS = {
    "sn": ("sn_photo_path", "SN"),
    "anydesk": ("anydesk_photo_path", "AnyDesk"),
    "ultraview": ("ultraview_photo_path", "UltraView"),
}


def _get_root_path():
    # Biến môi trường ROOT_PATH (đặt trên server thật, vd Render) được ưu tiên
    # hơn server_config.json — vì đường dẫn Windows cục bộ trong file đó không
    # tồn tại trên server Linux.
    env_path = os.environ.get("ROOT_PATH")
    if env_path:
        return env_path
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["root_path"]


def _safe_name(name):
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip() or "unnamed"


def _save_photo(target_dir, label, data_url):
    """Giải mã 1 ảnh base64 (data URL) và ghi ra file .jpg trong target_dir. Trả về đường dẫn file."""
    header, b64data = data_url.split(",", 1)
    raw = base64.b64decode(b64data)
    path = os.path.join(target_dir, f"{label}.jpg")
    with open(path, "wb") as f:
        f.write(raw)
    return path


def _row_to_item(row):
    return {
        "id": row["id"],
        "sn": row["sn"],
        "anydesk": row["anydesk"] or "",
        "ultraview": row["ultraview"] or "",
        "note": row["note"] or "",
        "status": row["status"],
        "hasSnPhoto": bool(row["sn_photo_path"]),
        "hasAnydeskPhoto": bool(row["anydesk_photo_path"]),
        "hasUltraviewPhoto": bool(row["ultraview_photo_path"]),
        "time": row["time_label"],
    }


@ipc_bp.route("/ipc-list.php", methods=["GET"])
def ipc_list():
    try:
        connection = get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM ipc_list ORDER BY id DESC")
                rows = cursor.fetchall()
        finally:
            connection.close()
    except psycopg2.Error as err:
        return jsonify({"ok": False, "error": f"Lỗi kết nối cơ sở dữ liệu: {err}"}), 500

    return jsonify({"ok": True, "items": [_row_to_item(r) for r in rows]})


@ipc_bp.route("/ipc-save.php", methods=["POST"])
def ipc_save():
    data = request.get_json(silent=True) or {}
    sn = (data.get("sn") or "").strip()
    if not sn:
        return jsonify({"ok": False, "error": "Thiếu mã SN"}), 400

    time_label = datetime.now().strftime("%d/%m/%Y %H:%M")

    photo_paths = {"sn": None, "anydesk": None, "ultraview": None}
    try:
        root_path = _get_root_path()
        target_dir = os.path.join(root_path, IPC_FOLDER_NAME, _safe_name(sn))
        for field, (_, label) in PHOTO_FIELD_COLUMNS.items():
            data_url = data.get(f"{field}Photo")
            if data_url:
                os.makedirs(target_dir, exist_ok=True)
                photo_paths[field] = _save_photo(target_dir, label, data_url)
    except (OSError, KeyError, json.JSONDecodeError, ValueError) as err:
        return jsonify({"ok": False, "error": f"Không lưu được ảnh IPC: {err}"}), 500

    try:
        connection = get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO ipc_list
                       (sn, anydesk, ultraview, note, status,
                        sn_photo_path, anydesk_photo_path, ultraview_photo_path, time_label)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (
                        sn,
                        data.get("anydesk") or "",
                        data.get("ultraview") or "",
                        data.get("note") or "",
                        data.get("status") or "configuring",
                        photo_paths["sn"],
                        photo_paths["anydesk"],
                        photo_paths["ultraview"],
                        time_label,
                    ),
                )
                new_id = cursor.fetchone()["id"]
        finally:
            connection.close()
    except psycopg2.errors.UniqueViolation:
        return jsonify({"ok": False, "error": f"Mã SN \"{sn}\" đã tồn tại"}), 400
    except psycopg2.Error as err:
        return jsonify({"ok": False, "error": f"Lỗi kết nối cơ sở dữ liệu: {err}"}), 500

    log_action("ipc", "create", target=sn)
    return jsonify({"ok": True, "id": new_id})


@ipc_bp.route("/ipc-photo.php", methods=["GET"])
def ipc_photo():
    record_id = request.args.get("id")
    field = request.args.get("field")
    if not record_id or field not in PHOTO_FIELD_COLUMNS:
        return jsonify({"ok": False, "error": "Thiếu id hoặc field không hợp lệ"}), 400

    column, _ = PHOTO_FIELD_COLUMNS[field]
    try:
        connection = get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT {column} AS photo_path FROM ipc_list WHERE id = %s", (record_id,))
                row = cursor.fetchone()
        finally:
            connection.close()
    except psycopg2.Error as err:
        return jsonify({"ok": False, "error": f"Lỗi kết nối cơ sở dữ liệu: {err}"}), 500

    if not row or not row["photo_path"]:
        return jsonify({"ok": False, "error": "IPC này chưa có ảnh"}), 404
    if not os.path.isfile(row["photo_path"]):
        return jsonify({"ok": False, "error": "Không tìm thấy file ảnh trên máy chủ"}), 404

    return send_file(row["photo_path"], mimetype="image/jpeg")


@ipc_bp.route("/ipc-status.php", methods=["POST"])
def ipc_status():
    data = request.get_json(silent=True) or {}
    record_id = data.get("id")
    status = data.get("status", "")
    if not record_id:
        return jsonify({"ok": False, "error": "Thiếu id"}), 400

    try:
        connection = get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE ipc_list SET status = %s WHERE id = %s", (status, record_id)
                )
        finally:
            connection.close()
    except psycopg2.Error as err:
        return jsonify({"ok": False, "error": f"Lỗi kết nối cơ sở dữ liệu: {err}"}), 500

    log_action("ipc", "update", target=str(record_id), detail=f"status={status}")
    return jsonify({"ok": True})


@ipc_bp.route("/ipc-delete.php", methods=["POST"])
def ipc_delete():
    data = request.get_json(silent=True) or {}
    record_id = data.get("id")
    if not record_id:
        return jsonify({"ok": False, "error": "Thiếu id"}), 400

    try:
        connection = get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM ipc_list WHERE id = %s", (record_id,))
        finally:
            connection.close()
    except psycopg2.Error as err:
        return jsonify({"ok": False, "error": f"Lỗi kết nối cơ sở dữ liệu: {err}"}), 500

    log_action("ipc", "delete", target=str(record_id))
    return jsonify({"ok": True})
