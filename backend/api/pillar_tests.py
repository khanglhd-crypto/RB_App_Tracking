"""
Test Trụ Xuất Xưởng API.

Exposes:
  GET  /api/history.php      - danh sách phiếu kiểm tra trụ
  POST /api/save-pillar.php  - lưu phiếu kiểm tra mới
  POST /api/delete.php       - xóa 1 phiếu
  POST /api/ship-status.php  - đổi trạng thái vận chuyển
"""

from datetime import datetime

from flask import Blueprint, jsonify, request

from audit import log_action
from database import filestore

pillar_tests_bp = Blueprint("pillar_tests", __name__, url_prefix="/api")

COLLECTION = "pillar_tests"


def _row_to_item(row):
    return {
        "id": row["id"],
        "pillar": row.get("pillar", ""),
        "model": row.get("model", ""),
        "source": row.get("source", ""),
        "factory": row.get("factory", ""),
        "ver": row.get("ver", ""),
        "tester": row.get("tester", ""),
        "result": row.get("result", ""),
        "reason": row.get("reason") or "",
        "time": row.get("time_label", ""),
        "folderName": row.get("folder_name", ""),
        "fileNames": row.get("file_names") or [],
        "shipStatus": row.get("ship_status") or "",
        "hasPdf": bool(row.get("pdf_path")),
    }


@pillar_tests_bp.route("/history.php", methods=["GET"])
def history():
    rows = filestore.list_records(COLLECTION)
    rows.sort(key=lambda r: r.get("id", 0), reverse=True)
    return jsonify({"ok": True, "items": [_row_to_item(r) for r in rows]})


@pillar_tests_bp.route("/save-pillar.php", methods=["POST"])
def save_pillar():
    data = request.get_json(silent=True) or {}
    folder_label = (data.get("folderLabel") or "").strip()
    file_names = data.get("fileNames") or []
    info = data.get("info") or {}

    pillar = (info.get("pillar") or "").strip()
    if not pillar:
        return jsonify({"ok": False, "error": "Thiếu mã số trụ sạc"}), 400

    time_label = datetime.now().strftime("%d/%m/%Y %H:%M")
    new_id = filestore.new_id()
    filestore.save_record(COLLECTION, new_id, {
        "id": new_id,
        "pillar": pillar,
        "model": info.get("model") or "",
        "source": info.get("source") or "",
        "factory": info.get("factory") or "",
        "ver": info.get("ver") or "",
        "tester": info.get("tester") or "",
        "result": info.get("result") or "",
        "reason": info.get("reason") or "",
        "time_label": time_label,
        "folder_name": folder_label,
        "file_names": file_names,
        "ship_status": "",
        "pdf_path": None,
        "nghiem_thu_pdf_path": None,
        "nang_cap_pdf_path": None,
    })

    log_action("test_tru", "create", target=pillar, detail=f"result={info.get('result') or ''}")
    return jsonify({"ok": True, "id": new_id})


@pillar_tests_bp.route("/delete.php", methods=["POST"])
def delete_pillar():
    data = request.get_json(silent=True) or {}
    record_id = data.get("id")
    if not record_id:
        return jsonify({"ok": False, "error": "Thiếu id"}), 400

    filestore.delete_record(COLLECTION, record_id)

    log_action("test_tru", "delete", target=str(record_id))
    return jsonify({"ok": True})


@pillar_tests_bp.route("/ship-status.php", methods=["POST"])
def set_ship_status():
    data = request.get_json(silent=True) or {}
    record_id = data.get("id")
    status = data.get("status", "")
    if not record_id:
        return jsonify({"ok": False, "error": "Thiếu id"}), 400

    row = filestore.get_record(COLLECTION, record_id)
    if row:
        row["ship_status"] = status
        filestore.save_record(COLLECTION, record_id, row)

    log_action("test_tru", "update", target=str(record_id), detail=f"ship_status={status}")
    return jsonify({"ok": True})
