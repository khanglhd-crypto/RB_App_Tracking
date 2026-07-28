"""
Trạm Sạc (On Trạm) API.

Exposes:
  GET  /api/tram-list.php    - danh sách trạm tổng
  POST /api/tram-save.php    - lưu 1 trạm tổng mới
  POST /api/tram-status.php  - đổi trạng thái hoạt động của trạm
  POST /api/tram-delete.php  - xóa 1 trạm tổng
"""

from datetime import datetime

from flask import Blueprint, jsonify, request

from audit import log_action
from database import filestore

tram_bp = Blueprint("tram", __name__, url_prefix="/api")

COLLECTION = "tram_tong"
PILLAR_COLLECTION = "pillar_tests"


def _row_to_item(row):
    return {
        "id": row["id"],
        "maTong": row.get("ma_tong", ""),
        "loaiTram": row.get("loai_tram") or "",
        "tenChuTram": row.get("ten_chu_tram") or "",
        "sdtLienHe": row.get("sdt_lien_he") or "",
        "diaChi": row.get("dia_chi") or "",
        "ktvNghiemThu": row.get("ktv_nghiem_thu") or "",
        "trangThai": row.get("trang_thai") or "hoat-dong",
        "time": row.get("time_label", ""),
        "tramNho": row.get("tram_nho") or [],
    }


def _enrich_nghiem_thu_pdf(items):
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

    has_pdf = {}
    for tru_id in tru_ids:
        pillar_row = filestore.get_record(PILLAR_COLLECTION, tru_id)
        has_pdf[tru_id] = bool(pillar_row and pillar_row.get("nghiem_thu_pdf_path"))

    for item in items:
        for nho in item["tramNho"]:
            master = nho.get("truMaster")
            if master:
                master["hasNghiemThuPdf"] = has_pdf.get(master.get("id"), False)
            for t in nho.get("truSlaves") or []:
                t["hasNghiemThuPdf"] = has_pdf.get(t.get("id"), False)


@tram_bp.route("/tram-list.php", methods=["GET"])
def tram_list():
    rows = filestore.list_records(COLLECTION)
    rows.sort(key=lambda r: r.get("id", 0), reverse=True)
    items = [_row_to_item(r) for r in rows]
    _enrich_nghiem_thu_pdf(items)
    return jsonify({"ok": True, "items": items})


@tram_bp.route("/tram-save.php", methods=["POST"])
def tram_save():
    data = request.get_json(silent=True) or {}
    ma_tong = (data.get("maTong") or "").strip()
    if not ma_tong:
        return jsonify({"ok": False, "error": "Thiếu mã trạm tổng"}), 400

    if filestore.find_one(COLLECTION, lambda r: r.get("ma_tong") == ma_tong):
        return jsonify({"ok": False, "error": f"Mã trạm tổng \"{ma_tong}\" đã tồn tại"}), 400

    time_label = datetime.now().strftime("%d/%m/%Y %H:%M")
    new_id = filestore.new_id()
    filestore.save_record(COLLECTION, new_id, {
        "id": new_id,
        "ma_tong": ma_tong,
        "loai_tram": data.get("loaiTram") or "",
        "ten_chu_tram": data.get("tenChuTram") or "",
        "sdt_lien_he": data.get("sdtLienHe") or "",
        "dia_chi": data.get("diaChi") or "",
        "ktv_nghiem_thu": data.get("ktvNghiemThu") or "",
        "trang_thai": "hoat-dong",
        "tram_nho": data.get("tramNho") or [],
        "time_label": time_label,
    })

    log_action("on_tram", "create", target=ma_tong)
    return jsonify({"ok": True, "id": new_id})


@tram_bp.route("/tram-status.php", methods=["POST"])
def tram_status():
    data = request.get_json(silent=True) or {}
    record_id = data.get("id")
    status = data.get("status", "")
    if not record_id:
        return jsonify({"ok": False, "error": "Thiếu id"}), 400

    row = filestore.get_record(COLLECTION, record_id)
    if row:
        row["trang_thai"] = status
        filestore.save_record(COLLECTION, record_id, row)

    log_action("on_tram", "update", target=str(record_id), detail=f"trang_thai={status}")
    return jsonify({"ok": True})


@tram_bp.route("/tram-delete.php", methods=["POST"])
def tram_delete():
    data = request.get_json(silent=True) or {}
    record_id = data.get("id")
    if not record_id:
        return jsonify({"ok": False, "error": "Thiếu id"}), 400

    filestore.delete_record(COLLECTION, record_id)

    log_action("on_tram", "delete", target=str(record_id))

    return jsonify({"ok": True})
