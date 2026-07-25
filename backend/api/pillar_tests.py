"""
Test Trụ Xuất Xưởng API.

Exposes:
  GET  /api/history.php      - danh sách phiếu kiểm tra trụ
  POST /api/save-pillar.php  - lưu phiếu kiểm tra mới
  POST /api/delete.php       - xóa 1 phiếu
  POST /api/ship-status.php  - đổi trạng thái vận chuyển
"""

import json
from datetime import datetime

import pymysql
from flask import Blueprint, jsonify, request

from audit import log_action
from database.db import get_connection

pillar_tests_bp = Blueprint("pillar_tests", __name__, url_prefix="/api")


def _row_to_item(row):
    return {
        "id": row["id"],
        "pillar": row["pillar"],
        "model": row["model"],
        "source": row["source"],
        "factory": row["factory"],
        "ver": row["ver"],
        "tester": row["tester"],
        "result": row["result"],
        "reason": row["reason"] or "",
        "time": row["time_label"],
        "folderName": row["folder_name"],
        "fileNames": json.loads(row["file_names"]) if row["file_names"] else [],
        "shipStatus": row["ship_status"] or "",
        "hasPdf": bool(row["pdf_path"]),
    }


@pillar_tests_bp.route("/history.php", methods=["GET"])
def history():
    try:
        connection = get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM pillar_tests ORDER BY id DESC")
                rows = cursor.fetchall()
        finally:
            connection.close()
    except pymysql.MySQLError as err:
        return jsonify({"ok": False, "error": f"Lỗi kết nối cơ sở dữ liệu: {err}"}), 500

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

    try:
        connection = get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO pillar_tests
                       (pillar, model, source, factory, ver, tester, result, reason,
                        time_label, folder_name, file_names, ship_status)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'')""",
                    (
                        pillar,
                        info.get("model") or "",
                        info.get("source") or "",
                        info.get("factory") or "",
                        info.get("ver") or "",
                        info.get("tester") or "",
                        info.get("result") or "",
                        info.get("reason") or "",
                        time_label,
                        folder_label,
                        json.dumps(file_names, ensure_ascii=False),
                    ),
                )
                new_id = cursor.lastrowid
        finally:
            connection.close()
    except pymysql.MySQLError as err:
        return jsonify({"ok": False, "error": f"Lỗi kết nối cơ sở dữ liệu: {err}"}), 500

    log_action("test_tru", "create", target=pillar, detail=f"result={info.get('result') or ''}")
    return jsonify({"ok": True, "id": new_id})


@pillar_tests_bp.route("/delete.php", methods=["POST"])
def delete_pillar():
    data = request.get_json(silent=True) or {}
    record_id = data.get("id")
    if not record_id:
        return jsonify({"ok": False, "error": "Thiếu id"}), 400

    try:
        connection = get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM pillar_tests WHERE id = %s", (record_id,))
        finally:
            connection.close()
    except pymysql.MySQLError as err:
        return jsonify({"ok": False, "error": f"Lỗi kết nối cơ sở dữ liệu: {err}"}), 500

    log_action("test_tru", "delete", target=str(record_id))
    return jsonify({"ok": True})


@pillar_tests_bp.route("/ship-status.php", methods=["POST"])
def set_ship_status():
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
                    "UPDATE pillar_tests SET ship_status = %s WHERE id = %s",
                    (status, record_id),
                )
        finally:
            connection.close()
    except pymysql.MySQLError as err:
        return jsonify({"ok": False, "error": f"Lỗi kết nối cơ sở dữ liệu: {err}"}), 500

    log_action("test_tru", "update", target=str(record_id), detail=f"ship_status={status}")
    return jsonify({"ok": True})
