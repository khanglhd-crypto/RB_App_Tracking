-- ============================================================
-- RB Control Tracking System — CẤU TRÚC DỮ LIỆU (tài liệu tham khảo)
-- ============================================================
-- LƯU Ý: file này KHÔNG còn được chạy thật nữa — app đã chuyển sang lưu
-- file JSON (mỗi bản ghi 1 file, xem backend/database/filestore.py) để
-- chạy offline, đồng bộ nhiều máy qua Google Drive/Shared Drive thay vì
-- 1 database SQL chung. Giữ file này lại chỉ để tham khảo tên trường/kiểu
-- dữ liệu của từng "collection" (users, pillar_tests, ipc_list, tram_tong,
-- su_vu, audit_log) — tên bảng SQL bên dưới ứng với tên thư mục JSON.
-- ============================================================

-- ------------------------------------------------------------
-- 1. users
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id             BIGSERIAL PRIMARY KEY,
    username       VARCHAR(100) NOT NULL,
    password_hash  VARCHAR(255) NOT NULL,
    fullname       VARCHAR(150) DEFAULT '',
    role           VARCHAR(30)  NOT NULL DEFAULT 'viewer', -- 'admin' hoặc loại tài khoản tự đăng ký: 'Engineer'|'OS'|'AS'
    email          VARCHAR(255) NULL, -- chỉ email đuôi @redblue.vn mới được tự đăng ký (xem /api/register)
    status         VARCHAR(20)  NOT NULL DEFAULT 'active', -- 'pending' (tự đăng ký, chờ admin duyệt) | 'active'
    created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_users_username UNIQUE (username),
    CONSTRAINT uq_users_email UNIQUE (email)
);

-- ------------------------------------------------------------
-- 2. pillar_tests
-- Phiếu "Test Trụ Xuất Xưởng" (frontend: test-tru.html). Mã trụ
-- được nhập tự do, không ràng buộc khóa ngoại với bảng nào khác.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pillar_tests (
    id           BIGSERIAL PRIMARY KEY,
    pillar       VARCHAR(100) NOT NULL,
    model        VARCHAR(20)  DEFAULT '',
    source       VARCHAR(50)  DEFAULT '',
    factory      VARCHAR(50)  DEFAULT '',
    ver          VARCHAR(50)  DEFAULT '',
    tester       VARCHAR(150) DEFAULT '',
    result       VARCHAR(20)  DEFAULT '',
    reason       TEXT,
    time_label   VARCHAR(50)  DEFAULT '',
    folder_name  VARCHAR(255) DEFAULT '',
    file_names   JSON NULL,
    ship_status  VARCHAR(20)  DEFAULT '',
    pdf_path             VARCHAR(500) NULL, -- PDF Test Xuất Xưởng
    nghiem_thu_pdf_path  VARCHAR(500) NULL, -- PDF Nghiệm Thu (On Trạm)
    nang_cap_pdf_path    VARCHAR(500) NULL, -- PDF Nâng Cấp Trụ Sạc (tách PE, lắp bộ kit)
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_pillar_tests_pillar ON pillar_tests (pillar);

-- ------------------------------------------------------------
-- 3. ipc_list
-- Danh sách IPC (frontend: test-ipc.html) — sổ đăng ký SN/AnyDesk/
-- UltraViewer độc lập, chưa gắn với trạm nào (được gắn sau, dưới
-- dạng bản sao JSON, khi chọn trong module Trạm Sạc).
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ipc_list (
    id                BIGSERIAL PRIMARY KEY,
    sn                VARCHAR(100) NOT NULL,
    anydesk           VARCHAR(50)  DEFAULT '',
    ultraview         VARCHAR(50)  DEFAULT '',
    note              TEXT,
    status            VARCHAR(30)  DEFAULT 'configuring',
    sn_photo_path         VARCHAR(500) NULL,
    anydesk_photo_path    VARCHAR(500) NULL,
    ultraview_photo_path  VARCHAR(500) NULL,
    time_label        VARCHAR(50)  DEFAULT '',
    created_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_ipc_list_sn UNIQUE (sn)
);

-- ------------------------------------------------------------
-- 4. tram_tong
-- Trạm Sạc (frontend: on-tram.html). tram_nho lưu nguyên mảng JSON
-- các mã IPC con (mỗi mã kèm bản sao ipc/truMaster/truSlaves đã
-- chọn), khớp đúng cấu trúc mà giao diện đã tự dựng sẵn.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tram_tong (
    id              BIGSERIAL PRIMARY KEY,
    ma_tong         VARCHAR(100) NOT NULL,
    loai_tram       VARCHAR(30)  DEFAULT '',
    ten_chu_tram    VARCHAR(150) DEFAULT '',
    sdt_lien_he     VARCHAR(30)  DEFAULT '',
    dia_chi         VARCHAR(255) DEFAULT '',
    ktv_nghiem_thu  VARCHAR(150) DEFAULT '',
    trang_thai      VARCHAR(30)  DEFAULT 'hoat-dong',
    tram_nho        JSON NULL,
    time_label      VARCHAR(50)  DEFAULT '',
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_tram_tong_ma UNIQUE (ma_tong)
);

-- ------------------------------------------------------------
-- 5. su_vu
-- Sự Vụ (frontend: su-vu.html) — ghi nhận báo lỗi theo mã trạm/mã
-- trụ nhập tự do, độc lập với tram_tong.
-- ------------------------------------------------------------
-- trang_thai (quy trình 6 bước): chua-xu-ly, dang-kiem-tra, da-tim-loi,
--   gui-linh-kien, linh-kien-den-noi, da-fix-dong-case
-- muc_do (mức độ ưu tiên): khan-cap, qua-han, moi-xuat-hien
CREATE TABLE IF NOT EXISTS su_vu (
    id          BIGSERIAL PRIMARY KEY,
    ma_tram     VARCHAR(100) NOT NULL,
    ma_tru      VARCHAR(100) NOT NULL,
    mo_ta       TEXT,
    trang_thai      VARCHAR(20)  DEFAULT 'chua-xu-ly',
    muc_do          VARCHAR(30)  DEFAULT 'moi-xuat-hien',
    xu_ly_pdf_path  VARCHAR(500) NULL, -- PDF Phiếu Xử Lý Sự Cố
    time_label      VARCHAR(50)  DEFAULT '',
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ------------------------------------------------------------
-- 6. audit_log
-- Lịch sử chỉnh sửa (ai làm gì, khi nào) trên toàn bộ app — xem lại
-- ở trang Cài Đặt (chỉ admin). username lấy từ header X-Username do
-- frontend tự gắn vào mọi request ghi (xem apiPost trong từng trang).
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGSERIAL PRIMARY KEY,
    username    VARCHAR(100) NOT NULL DEFAULT 'unknown',
    module      VARCHAR(50)  NOT NULL,
    action      VARCHAR(20)  NOT NULL, -- create | update | delete | export
    target      VARCHAR(255) DEFAULT '',
    detail      VARCHAR(500) DEFAULT '',
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log (created_at);
