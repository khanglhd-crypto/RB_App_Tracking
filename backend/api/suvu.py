"""
Sự Vụ API.

Exposes:
  GET  /api/suvu-list.php      - danh sách sự vụ
  POST /api/suvu-save.php      - ghi nhận sự vụ mới
  POST /api/suvu-status.php    - đổi tình trạng xử lý (quy trình 6 bước)
  POST /api/suvu-mucdo.php     - đổi mức độ ưu tiên
  POST /api/suvu-delete.php    - xóa 1 sự vụ
  POST /api/suvu-set-pdf.php   - gắn đường dẫn Phiếu Xử Lý Sự Cố vào 1 sự vụ
  GET  /api/suvu-pdf.php       - xem lại Phiếu Xử Lý Sự Cố (?id=...)
  GET  /api/pillar-detail.php  - tra cứu chéo 1 mã trụ: phiếu PDF (Test Trụ),
                                 trạm chứa trụ đó (Trạm Sạc), lần sửa chữa gần nhất
"""

import os
from datetime import datetime

import psycopg2
from flask import Blueprint, jsonify, request, send_file

from audit import log_action
from database.db import get_connection

suvu_bp = Blueprint("suvu", __name__, url_prefix="/api")


def _row_to_item(row):
    return {
        "id": row["id"],
        "maTram": row["ma_tram"],
        "maTru": row["ma_tru"],
        "moTa": row["mo_ta"] or "",
        "trangThai": row["trang_thai"] or "chua-xu-ly",
        "mucDo": row["muc_do"] or "moi-xuat-hien",
        "hasXuLyPdf": bool(row["xu_ly_pdf_path"]),
        "time": row["time_label"],
    }


@suvu_bp.route("/suvu-list.php", methods=["GET"])
def suvu_list():
    try:
        connection = get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM su_vu ORDER BY id DESC")
                rows = cursor.fetchall()
        finally:
            connection.close()
    except psycopg2.Error as err:
        return jsonify({"ok": False, "error": f"Lỗi kết nối cơ sở dữ liệu: {err}"}), 500

    return jsonify({"ok": True, "items": [_row_to_item(r) for r in rows]})


@suvu_bp.route("/suvu-save.php", methods=["POST"])
def suvu_save():
    data = request.get_json(silent=True) or {}
    ma_tram = (data.get("maTram") or "").strip()
    ma_tru = (data.get("maTru") or "").strip()
    mo_ta = (data.get("moTa") or "").strip()
    muc_do = (data.get("mucDo") or "moi-xuat-hien").strip()
    if not ma_tram or not ma_tru or not mo_ta:
        return jsonify({"ok": False, "error": "Thiếu mã trạm, mã trụ hoặc mô tả lỗi"}), 400

    time_label = datetime.now().strftime("%d/%m/%Y %H:%M")

    try:
        connection = get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO su_vu (ma_tram, ma_tru, mo_ta, trang_thai, muc_do, time_label)
                       VALUES (%s,%s,%s,'chua-xu-ly',%s,%s) RETURNING id""",
                    (ma_tram, ma_tru, mo_ta, muc_do, time_label),
                )
                new_id = cursor.fetchone()["id"]
        finally:
            connection.close()
    except psycopg2.Error as err:
        return jsonify({"ok": False, "error": f"Lỗi kết nối cơ sở dữ liệu: {err}"}), 500

    log_action("su_vu", "create", target=f"{ma_tram}/{ma_tru}", detail=mo_ta[:200])
    return jsonify({"ok": True, "id": new_id})


@suvu_bp.route("/suvu-status.php", methods=["POST"])
def suvu_status():
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
                    "UPDATE su_vu SET trang_thai = %s WHERE id = %s", (status, record_id)
                )
        finally:
            connection.close()
    except psycopg2.Error as err:
        return jsonify({"ok": False, "error": f"Lỗi kết nối cơ sở dữ liệu: {err}"}), 500

    log_action("su_vu", "update", target=str(record_id), detail=f"trang_thai={status}")
    return jsonify({"ok": True})


@suvu_bp.route("/suvu-mucdo.php", methods=["POST"])
def suvu_mucdo():
    data = request.get_json(silent=True) or {}
    record_id = data.get("id")
    muc_do = data.get("mucDo", "")
    if not record_id:
        return jsonify({"ok": False, "error": "Thiếu id"}), 400

    try:
        connection = get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE su_vu SET muc_do = %s WHERE id = %s", (muc_do, record_id)
                )
        finally:
            connection.close()
    except psycopg2.Error as err:
        return jsonify({"ok": False, "error": f"Lỗi kết nối cơ sở dữ liệu: {err}"}), 500

    log_action("su_vu", "update", target=str(record_id), detail=f"muc_do={muc_do}")
    return jsonify({"ok": True})


@suvu_bp.route("/pillar-detail.php", methods=["GET"])
def pillar_detail():
    ma_tru = (request.args.get("maTru") or "").strip()
    ma_tram = (request.args.get("maTram") or "").strip()
    exclude_id = request.args.get("excludeId")

    result = {"ok": True, "pdf": None, "station": None, "lastRepair": None}

    try:
        connection = get_connection()
        try:
            with connection.cursor() as cursor:
                if ma_tru:
                    cursor.execute(
                        "SELECT id, pdf_path, nghiem_thu_pdf_path, nang_cap_pdf_path FROM pillar_tests WHERE pillar = %s ORDER BY id DESC LIMIT 1",
                        (ma_tru,),
                    )
                    row = cursor.fetchone()
                    if row:
                        result["pdf"] = {
                            "id": row["id"],
                            "hasPdf": bool(row["pdf_path"]),
                            "hasNghiemThuPdf": bool(row["nghiem_thu_pdf_path"]),
                            "hasNangCapPdf": bool(row["nang_cap_pdf_path"]),
                        }

                if ma_tram:
                    cursor.execute(
                        "SELECT id, ma_tong, dia_chi FROM tram_tong WHERE ma_tong = %s LIMIT 1",
                        (ma_tram,),
                    )
                    row = cursor.fetchone()
                    if row:
                        result["station"] = {"id": row["id"], "maTong": row["ma_tong"], "diaChi": row["dia_chi"] or ""}

                if ma_tru:
                    query = """SELECT time_label, mo_ta FROM su_vu
                               WHERE ma_tru = %s AND trang_thai = 'da-fix-dong-case'"""
                    params = [ma_tru]
                    if exclude_id:
                        query += " AND id != %s"
                        params.append(exclude_id)
                    query += " ORDER BY id DESC LIMIT 1"
                    cursor.execute(query, params)
                    row = cursor.fetchone()
                    if row:
                        result["lastRepair"] = {"time": row["time_label"], "moTa": row["mo_ta"]}
        finally:
            connection.close()
    except psycopg2.Error as err:
        return jsonify({"ok": False, "error": f"Lỗi kết nối cơ sở dữ liệu: {err}"}), 500

    return jsonify(result)


@suvu_bp.route("/suvu-set-pdf.php", methods=["POST"])
def suvu_set_pdf():
    data = request.get_json(silent=True) or {}
    record_id = data.get("id")
    pdf_path = (data.get("path") or "").strip()
    if not record_id or not pdf_path:
        return jsonify({"ok": False, "error": "Thiếu id hoặc đường dẫn PDF"}), 400

    try:
        connection = get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE su_vu SET xu_ly_pdf_path = %s WHERE id = %s", (pdf_path, record_id)
                )
        finally:
            connection.close()
    except psycopg2.Error as err:
        return jsonify({"ok": False, "error": f"Lỗi kết nối cơ sở dữ liệu: {err}"}), 500

    log_action("su_vu", "export", target=str(record_id), detail="Phiếu Xử Lý Sự Cố")
    return jsonify({"ok": True})


@suvu_bp.route("/suvu-pdf.php", methods=["GET"])
def view_suvu_pdf():
    record_id = request.args.get("id")
    if not record_id:
        return jsonify({"ok": False, "error": "Thiếu id"}), 400

    try:
        connection = get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT xu_ly_pdf_path FROM su_vu WHERE id = %s", (record_id,))
                row = cursor.fetchone()
        finally:
            connection.close()
    except psycopg2.Error as err:
        return jsonify({"ok": False, "error": f"Lỗi kết nối cơ sở dữ liệu: {err}"}), 500

    if not row or not row["xu_ly_pdf_path"]:
        return jsonify({"ok": False, "error": "Sự vụ này chưa xuất Phiếu Xử Lý Sự Cố"}), 404
    if not os.path.isfile(row["xu_ly_pdf_path"]):
        return jsonify({"ok": False, "error": "Không tìm thấy file PDF trên máy chủ (có thể đã bị xóa/di chuyển)"}), 404

    return send_file(row["xu_ly_pdf_path"], mimetype="application/pdf")


@suvu_bp.route("/suvu-delete.php", methods=["POST"])
def suvu_delete():
    data = request.get_json(silent=True) or {}
    record_id = data.get("id")
    if not record_id:
        return jsonify({"ok": False, "error": "Thiếu id"}), 400

    try:
        connection = get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM su_vu WHERE id = %s", (record_id,))
        finally:
            connection.close()
    except psycopg2.Error as err:
        return jsonify({"ok": False, "error": f"Lỗi kết nối cơ sở dữ liệu: {err}"}), 500

    log_action("su_vu", "delete", target=str(record_id))
    return jsonify({"ok": True})
