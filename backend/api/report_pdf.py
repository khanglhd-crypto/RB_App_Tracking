"""
Xuất Phiếu Ảnh (Test Trụ/On Trạm/Nâng Cấp Trụ Sạc): lưu ảnh lẻ + PDF thẳng
lên Google Drive (qua drive_store.py), và phục vụ lại file đã xuất.

Luồng xuất phiếu gồm 2 bước gọi từ frontend:
  1. POST /api/export-report-pdf.php — lưu ảnh lẻ lên Drive, trả về thông
     tin thư mục/tên file cần dùng ("driveTarget") cho bước 2.
  2. Electron (main.js) tự vẽ HTML thành PDF (Chromium có sẵn, không cần
     Playwright), rồi gọi POST /api/upload-pdf-to-drive.php để tải PDF vừa
     vẽ lên đúng thư mục đó — endpoint này mới thực sự ghi liên kết PDF vào
     bản ghi trụ (lúc bước 1 chưa có PDF nên chưa biết fileId để ghi).

Trước đây (Google Drive for Desktop) lưu vào 1 ổ đĩa ánh xạ cục bộ — hay
lỗi (Access denied/Paused/nhầm ổ đĩa) không rõ nguyên nhân. Giờ gọi thẳng
Drive API qua mạng, lỗi gì báo rõ ngay, không còn phụ thuộc phần mềm Google
Drive for Desktop nữa.
"""

import base64
import re

from flask import Blueprint, Response, jsonify, request

from audit import log_action
from database import filestore
from drive_store import get_shared_sync

report_pdf_bp = Blueprint("report_pdf", __name__, url_prefix="/api")

PILLAR_COLLECTION = "pillar_tests"
DEFAULT_BASE_FOLDER = "Charge Point"

# Cột hợp lệ để ghi/đọc fileId PDF trên pillar_tests — whitelist tránh lỗi
# nhập tên cột tùy ý. "pdf_path" = PDF Test Xuất Xưởng, "nghiem_thu_pdf_path"
# = PDF Nghiệm Thu On Trạm, "nang_cap_pdf_path" = PDF Nâng Cấp Trụ Sạc.
# (Tên cột giữ nguyên "_path" dù giờ chứa Drive fileId chứ không phải đường
# dẫn ổ đĩa nữa — đổi tên cột sẽ phải sửa dữ liệu cũ, không cần thiết.)
PDF_LINK_COLUMNS = {"pdf_path", "nghiem_thu_pdf_path", "nang_cap_pdf_path"}

# baseFolder -> tên module ghi vào audit_log. "List Xu Ly Su Co" (Sự Vụ) không
# nằm trong danh sách này vì đã được ghi log riêng, rõ ràng hơn ở suvu.py
# (suvu-set-pdf.php), lúc gắn PDF vào đúng sự vụ.
MODULE_BY_BASE_FOLDER = {
    "Charge Point": "test_tru",
    "List On Tram": "on_tram",
    "Modify Charge Point": "nang_cap",
}


def _safe_name(name):
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip() or "unnamed"


@report_pdf_bp.route("/export-report-pdf.php", methods=["POST"])
def export_report_pdf():
    data = request.get_json(silent=True) or {}
    pillar = (data.get("pillar") or "").strip()
    folder_name = (data.get("folderName") or "").strip() or _safe_name(pillar or "unnamed")
    # folderPath: mảng các cấp thư mục con (vd ["V.E.HCM1348","HCM1348.001","HCM1348.001"])
    # để lưu sâu nhiều cấp — nếu không có thì dùng folderName như 1 cấp duy nhất (cũ)
    folder_path = data.get("folderPath") or [folder_name]
    report_name = (data.get("reportName") or "Phieu_Test").strip()
    base_folder = (data.get("baseFolder") or DEFAULT_BASE_FOLDER).strip() or DEFAULT_BASE_FOLDER
    images = data.get("images") or []  # [{label, dataUrl}, ...] - ảnh lẻ lưu chung thư mục với PDF
    record_id = data.get("id")
    link_column = data.get("linkColumn") or "pdf_path"
    if link_column not in PDF_LINK_COLUMNS:
        link_column = "pdf_path"

    if not pillar:
        return jsonify({"ok": False, "error": "Thiếu mã trụ sạc"}), 400

    safe_segments = [_safe_name(seg) for seg in folder_path if str(seg or "").strip()]

    try:
        sync = get_shared_sync()
        folder_id = sync.resolve_folder_path(base_folder, safe_segments)
    except Exception as err:
        return jsonify({"ok": False, "error": f"Không tạo được thư mục lưu trên Drive: {err}"}), 500

    try:
        for img in images:
            label = (img.get("label") or "").strip()
            data_url = img.get("dataUrl")
            if label and data_url:
                header, b64data = data_url.split(",", 1)
                raw = base64.b64decode(b64data)
                sync.upload_named_file(folder_id, f"{_safe_name(label)}.jpg", raw, "image/jpeg")
    except Exception as err:
        return jsonify({"ok": False, "error": f"Không lưu được ảnh lẻ lên Drive: {err}"}), 500

    filename = f"{_safe_name(report_name)}_{_safe_name(pillar)}.pdf"

    module = MODULE_BY_BASE_FOLDER.get(base_folder)
    if module:
        log_action(module, "export", target=pillar, detail=report_name)

    display_path = "/".join([base_folder, *safe_segments, filename])
    return jsonify({
        "ok": True,
        "path": display_path,
        "driveTarget": {
            "baseFolder": base_folder,
            "folderPath": safe_segments,
            "filename": filename,
            "id": record_id,
            "linkColumn": link_column,
        },
    })


@report_pdf_bp.route("/upload-pdf-to-drive.php", methods=["POST"])
def upload_pdf_to_drive():
    """Electron (main.js) gọi endpoint này SAU KHI đã tự vẽ xong PDF (qua
    Chromium có sẵn) — nhận nội dung PDF (base64), tải lên đúng thư mục đã
    xác định ở export-report-pdf.php, rồi mới ghi liên kết vào bản ghi trụ
    (lúc export-report-pdf.php chạy thì PDF chưa tồn tại nên chưa có fileId)."""
    data = request.get_json(silent=True) or {}
    base_folder = (data.get("baseFolder") or DEFAULT_BASE_FOLDER).strip() or DEFAULT_BASE_FOLDER
    folder_path = data.get("folderPath") or []
    filename = (data.get("filename") or "").strip()
    pdf_b64 = data.get("pdfBase64")
    record_id = data.get("id")
    link_column = data.get("linkColumn") or "pdf_path"
    if link_column not in PDF_LINK_COLUMNS:
        link_column = "pdf_path"

    if not filename or not pdf_b64:
        return jsonify({"ok": False, "error": "Thiếu tên file hoặc nội dung PDF"}), 400

    try:
        raw = base64.b64decode(pdf_b64)
        sync = get_shared_sync()
        folder_id = sync.resolve_folder_path(base_folder, folder_path)
        file_id = sync.upload_named_file(folder_id, filename, raw, "application/pdf")
    except Exception as err:
        return jsonify({"ok": False, "error": f"Không tải được PDF lên Drive: {err}"}), 500

    if record_id:
        row = filestore.get_record(PILLAR_COLLECTION, record_id)
        if row:
            row[link_column] = file_id
            filestore.save_record(PILLAR_COLLECTION, record_id, row)

    return jsonify({"ok": True, "fileId": file_id})


@report_pdf_bp.route("/pillar-pdf.php", methods=["GET"])
def view_pillar_pdf():
    record_id = request.args.get("id")
    if not record_id:
        return jsonify({"ok": False, "error": "Thiếu id"}), 400

    pdf_type = request.args.get("type")
    if pdf_type == "nghiem-thu":
        link_column = "nghiem_thu_pdf_path"
    elif pdf_type == "nang-cap":
        link_column = "nang_cap_pdf_path"
    else:
        link_column = "pdf_path"

    # link_column chi co 2 gia tri co dinh o tren, khong lay truc tiep tu request
    row = filestore.get_record(PILLAR_COLLECTION, record_id)
    file_id = row.get(link_column) if row else None

    if not file_id:
        return jsonify({"ok": False, "error": "Trụ này chưa xuất Phiếu Ảnh"}), 404

    try:
        content = get_shared_sync().download_file_bytes(file_id)
    except Exception as err:
        return jsonify({"ok": False, "error": f"Không tải được PDF từ Drive: {err}"}), 404

    return Response(content, mimetype="application/pdf")
