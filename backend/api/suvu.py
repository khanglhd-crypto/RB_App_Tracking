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

from datetime import datetime

from flask import Blueprint, Response, jsonify, request

from audit import log_action
from database import filestore
from drive_store import get_shared_sync

suvu_bp = Blueprint("suvu", __name__, url_prefix="/api")

COLLECTION = "su_vu"
PILLAR_COLLECTION = "pillar_tests"
TRAM_COLLECTION = "tram_tong"


def _row_to_item(row):
    return {
        "id": row["id"],
        "maTram": row.get("ma_tram", ""),
        "maTru": row.get("ma_tru", ""),
        "moTa": row.get("mo_ta") or "",
        "trangThai": row.get("trang_thai") or "chua-xu-ly",
        "mucDo": row.get("muc_do") or "moi-xuat-hien",
        "hasXuLyPdf": bool(row.get("xu_ly_pdf_path")),
        "time": row.get("time_label", ""),
    }


@suvu_bp.route("/suvu-list.php", methods=["GET"])
def suvu_list():
    rows = filestore.list_records(COLLECTION)
    rows.sort(key=lambda r: r.get("id", 0), reverse=True)
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
    new_id = filestore.new_id()
    filestore.save_record(COLLECTION, new_id, {
        "id": new_id,
        "ma_tram": ma_tram,
        "ma_tru": ma_tru,
        "mo_ta": mo_ta,
        "trang_thai": "chua-xu-ly",
        "muc_do": muc_do,
        "xu_ly_pdf_path": None,
        "time_label": time_label,
    })

    log_action("su_vu", "create", target=f"{ma_tram}/{ma_tru}", detail=mo_ta[:200])
    return jsonify({"ok": True, "id": new_id})


@suvu_bp.route("/suvu-status.php", methods=["POST"])
def suvu_status():
    data = request.get_json(silent=True) or {}
    record_id = data.get("id")
    status = data.get("status", "")
    if not record_id:
        return jsonify({"ok": False, "error": "Thiếu id"}), 400

    row = filestore.get_record(COLLECTION, record_id)
    if row:
        row["trang_thai"] = status
        filestore.save_record(COLLECTION, record_id, row)

    log_action("su_vu", "update", target=str(record_id), detail=f"trang_thai={status}")
    return jsonify({"ok": True})


@suvu_bp.route("/suvu-mucdo.php", methods=["POST"])
def suvu_mucdo():
    data = request.get_json(silent=True) or {}
    record_id = data.get("id")
    muc_do = data.get("mucDo", "")
    if not record_id:
        return jsonify({"ok": False, "error": "Thiếu id"}), 400

    row = filestore.get_record(COLLECTION, record_id)
    if row:
        row["muc_do"] = muc_do
        filestore.save_record(COLLECTION, record_id, row)

    log_action("su_vu", "update", target=str(record_id), detail=f"muc_do={muc_do}")
    return jsonify({"ok": True})


@suvu_bp.route("/pillar-detail.php", methods=["GET"])
def pillar_detail():
    ma_tru = (request.args.get("maTru") or "").strip()
    ma_tram = (request.args.get("maTram") or "").strip()
    exclude_id = request.args.get("excludeId")
    exclude_id = int(exclude_id) if exclude_id else None

    result = {"ok": True, "pdf": None, "station": None, "lastRepair": None}

    if ma_tru:
        matches = filestore.find_all(PILLAR_COLLECTION, lambda r: r.get("pillar") == ma_tru)
        if matches:
            matches.sort(key=lambda r: r.get("id", 0), reverse=True)
            row = matches[0]
            result["pdf"] = {
                "id": row["id"],
                "hasPdf": bool(row.get("pdf_path")),
                "hasNghiemThuPdf": bool(row.get("nghiem_thu_pdf_path")),
                "hasNangCapPdf": bool(row.get("nang_cap_pdf_path")),
            }

    if ma_tram:
        row = filestore.find_one(TRAM_COLLECTION, lambda r: r.get("ma_tong") == ma_tram)
        if row:
            result["station"] = {"id": row["id"], "maTong": row["ma_tong"], "diaChi": row.get("dia_chi") or ""}

    if ma_tru:
        matches = filestore.find_all(
            COLLECTION,
            lambda r: r.get("ma_tru") == ma_tru
            and r.get("trang_thai") == "da-fix-dong-case"
            and r.get("id") != exclude_id,
        )
        if matches:
            matches.sort(key=lambda r: r.get("id", 0), reverse=True)
            row = matches[0]
            result["lastRepair"] = {"time": row.get("time_label", ""), "moTa": row.get("mo_ta", "")}

    return jsonify(result)


@suvu_bp.route("/suvu-set-pdf.php", methods=["POST"])
def suvu_set_pdf():
    data = request.get_json(silent=True) or {}
    record_id = data.get("id")
    pdf_path = (data.get("path") or "").strip()
    if not record_id or not pdf_path:
        return jsonify({"ok": False, "error": "Thiếu id hoặc đường dẫn PDF"}), 400

    row = filestore.get_record(COLLECTION, record_id)
    if row:
        row["xu_ly_pdf_path"] = pdf_path
        filestore.save_record(COLLECTION, record_id, row)

    log_action("su_vu", "export", target=str(record_id), detail="Phiếu Xử Lý Sự Cố")
    return jsonify({"ok": True})


@suvu_bp.route("/suvu-pdf.php", methods=["GET"])
def view_suvu_pdf():
    record_id = request.args.get("id")
    if not record_id:
        return jsonify({"ok": False, "error": "Thiếu id"}), 400

    row = filestore.get_record(COLLECTION, record_id)
    file_id = row.get("xu_ly_pdf_path") if row else None

    if not file_id:
        return jsonify({"ok": False, "error": "Sự vụ này chưa xuất Phiếu Xử Lý Sự Cố"}), 404

    try:
        content = get_shared_sync().download_file_bytes(file_id)
    except Exception as err:
        return jsonify({"ok": False, "error": f"Không tải được PDF từ Drive: {err}"}), 404

    return Response(content, mimetype="application/pdf")


@suvu_bp.route("/suvu-delete.php", methods=["POST"])
def suvu_delete():
    data = request.get_json(silent=True) or {}
    record_id = data.get("id")
    if not record_id:
        return jsonify({"ok": False, "error": "Thiếu id"}), 400

    filestore.delete_record(COLLECTION, record_id)

    log_action("su_vu", "delete", target=str(record_id))
    return jsonify({"ok": True})
