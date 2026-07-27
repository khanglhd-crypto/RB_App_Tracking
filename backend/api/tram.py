"""
Trạm Sạc (On Trạm) API.

Exposes:
  GET  /api/tram-list.php    - danh sách trạm tổng
  POST /api/tram-save.php    - lưu 1 trạm tổng mới
  POST /api/tram-status.php  - đổi trạng thái hoạt động của trạm
  POST /api/tram-delete.php  - xóa 1 trạm tổng
"""

import json
from datetime import datetime

import psycopg2
from flask import Blueprint, jsonify, request

from audit import log_action
from database.db import get_connection

tram_bp = Blueprint("tram", __name__, url_prefix="/api")


def _row_to_item(row):
    return {
        "id": row["id"],
        "maTong": row["ma_tong"],
        "loaiTram": row["loai_tram"] or "",
        "tenChuTram": row["ten_chu_tram"] or "",
        "sdtLienHe": row["sdt_lien_he"] or "",
        "diaChi": row["dia_chi"] or "",
        "ktvNghiemThu": row["ktv_nghiem_thu"] or "",
        "trangThai": row["trang_thai"] or "hoat-dong",
        "time": row["time_label"],
        "tramNho": row["tram_nho"] or [],
    }


def _enrich_nghiem_thu_pdf(items, cursor):
    """Đính kèm hasNghiemThuPdf cho từng trụ Master/Slave, dựa trên
    pillar_tests.nghiem_thu_pdf_path (tra theo id trụ đã nhúng sẵn)."""
    tru_ids = set()
    for item in items:
        for nho in item["tramNho"]:
            if nho.get("truMaster", {}).get("id"):
                tru_ids.add(nho["truMaster"]["id"])
            for t in nho.get("truSlaves") or []:
                if t.get("id"):
                    tru_ids.add(t["id"])

    if not tru_ids:
        return

    placeholders = ",".join(["%s"] * len(tru_ids))
    cursor.execute(
        f"SELECT id, nghiem_thu_pdf_path FROM pillar_tests WHERE id IN ({placeholders})",
        tuple(tru_ids),
    )
    has_pdf = {r["id"]: bool(r["nghiem_thu_pdf_path"]) for r in cursor.fetchall()}

    for item in items:
        for nho in item["tramNho"]:
            master = nho.get("truMaster")
            if master:
                master["hasNghiemThuPdf"] = has_pdf.get(master.get("id"), False)
            for t in nho.get("truSlaves") or []:
                t["hasNghiemThuPdf"] = has_pdf.get(t.get("id"), False)


@tram_bp.route("/tram-list.php", methods=["GET"])
def tram_list():
    try:
        connection = get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM tram_tong ORDER BY id DESC")
                rows = cursor.fetchall()
                items = [_row_to_item(r) for r in rows]
                _enrich_nghiem_thu_pdf(items, cursor)
        finally:
            connection.close()
    except psycopg2.Error as err:
        return jsonify({"ok": False, "error": f"Lỗi kết nối cơ sở dữ liệu: {err}"}), 500

    return jsonify({"ok": True, "items": items})


@tram_bp.route("/tram-save.php", methods=["POST"])
def tram_save():
    data = request.get_json(silent=True) or {}
    ma_tong = (data.get("maTong") or "").strip()
    if not ma_tong:
        return jsonify({"ok": False, "error": "Thiếu mã trạm tổng"}), 400

    time_label = datetime.now().strftime("%d/%m/%Y %H:%M")

    try:
        connection = get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO tram_tong
                       (ma_tong, loai_tram, ten_chu_tram, sdt_lien_he, dia_chi,
                        ktv_nghiem_thu, trang_thai, tram_nho, time_label)
                       VALUES (%s,%s,%s,%s,%s,%s,'hoat-dong',%s,%s) RETURNING id""",
                    (
                        ma_tong,
                        data.get("loaiTram") or "",
                        data.get("tenChuTram") or "",
                        data.get("sdtLienHe") or "",
                        data.get("diaChi") or "",
                        data.get("ktvNghiemThu") or "",
                        json.dumps(data.get("tramNho") or [], ensure_ascii=False),
                        time_label,
                    ),
                )
                new_id = cursor.fetchone()["id"]
        finally:
            connection.close()
    except psycopg2.errors.UniqueViolation:
        return jsonify({"ok": False, "error": f"Mã trạm tổng \"{ma_tong}\" đã tồn tại"}), 400
    except psycopg2.Error as err:
        return jsonify({"ok": False, "error": f"Lỗi kết nối cơ sở dữ liệu: {err}"}), 500

    log_action("on_tram", "create", target=ma_tong)
    return jsonify({"ok": True, "id": new_id})


@tram_bp.route("/tram-status.php", methods=["POST"])
def tram_status():
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
                    "UPDATE tram_tong SET trang_thai = %s WHERE id = %s", (status, record_id)
                )
        finally:
            connection.close()
    except psycopg2.Error as err:
        return jsonify({"ok": False, "error": f"Lỗi kết nối cơ sở dữ liệu: {err}"}), 500

    log_action("on_tram", "update", target=str(record_id), detail=f"trang_thai={status}")
    return jsonify({"ok": True})


@tram_bp.route("/tram-delete.php", methods=["POST"])
def tram_delete():
    data = request.get_json(silent=True) or {}
    record_id = data.get("id")
    if not record_id:
        return jsonify({"ok": False, "error": "Thiếu id"}), 400

    try:
        connection = get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM tram_tong WHERE id = %s", (record_id,))
        finally:
            connection.close()
    except psycopg2.Error as err:
        return jsonify({"ok": False, "error": f"Lỗi kết nối cơ sở dữ liệu: {err}"}), 500

    log_action("on_tram", "delete", target=str(record_id))

    return jsonify({"ok": True})
