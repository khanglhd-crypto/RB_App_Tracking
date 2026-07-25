-- ============================================================
-- RB Control Tracking System — Database Schema
-- Engine   : InnoDB
-- Charset  : utf8mb4 / Collation: utf8mb4_unicode_ci
-- Target   : MySQL 8.0+
-- ============================================================

CREATE DATABASE IF NOT EXISTS app_tracking
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE app_tracking;

SET NAMES utf8mb4;

-- ------------------------------------------------------------
-- 1. users
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id             BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    username       VARCHAR(100) NOT NULL,
    password_hash  VARCHAR(255) NOT NULL,
    fullname       VARCHAR(150) DEFAULT '',
    role           VARCHAR(30)  NOT NULL DEFAULT 'viewer', -- 'admin' hoặc loại tài khoản tự đăng ký: 'Engineer'|'OS'|'AS'
    email          VARCHAR(255) NULL, -- chỉ email đuôi @redblue.vn mới được tự đăng ký (xem /api/register)
    status         VARCHAR(20)  NOT NULL DEFAULT 'active', -- 'pending' (tự đăng ký, chờ admin duyệt) | 'active'
    created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_users_username (username),
    UNIQUE KEY uq_users_email (email)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- 2. stations
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stations (
    id                   BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    station_code         VARCHAR(100) NOT NULL,
    station_name         VARCHAR(200) DEFAULT '',
    station_type         VARCHAR(50)  DEFAULT '',
    network_type         ENUM('Link','Non-Link') NOT NULL DEFAULT 'Non-Link',
    owner                VARCHAR(150) DEFAULT '',
    phone                VARCHAR(30)  DEFAULT '',
    address              VARCHAR(255) DEFAULT '',
    acceptance_engineer  VARCHAR(150) DEFAULT '',
    created_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_stations_code (station_code)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- 3. ipc_devices
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ipc_devices (
    id             BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    station_id     BIGINT UNSIGNED NOT NULL,
    serial_number  VARCHAR(100) NOT NULL,
    anydesk        VARCHAR(50)  DEFAULT '',
    ultraviewer    VARCHAR(50)  DEFAULT '',
    note           TEXT,
    status         VARCHAR(30)  DEFAULT 'active',
    created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_ipc_serial (serial_number),
    KEY idx_ipc_station (station_id),
    CONSTRAINT fk_ipc_station FOREIGN KEY (station_id)
        REFERENCES stations(id) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- 4. chargers
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chargers (
    id             BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    station_id     BIGINT UNSIGNED NOT NULL,
    charger_code   VARCHAR(100) NOT NULL,
    serial_number  VARCHAR(100) DEFAULT '',
    status         VARCHAR(30)  DEFAULT 'active',
    created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_chargers_code (charger_code),
    KEY idx_chargers_station (station_id),
    CONSTRAINT fk_chargers_station FOREIGN KEY (station_id)
        REFERENCES stations(id) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- 5. production_tests
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS production_tests (
    id          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    charger_id  BIGINT UNSIGNED NOT NULL,
    tester      VARCHAR(150) DEFAULT '',
    result      VARCHAR(20)  DEFAULT '',
    note        TEXT,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_prodtest_charger (charger_id),
    CONSTRAINT fk_prodtest_charger FOREIGN KEY (charger_id)
        REFERENCES chargers(id) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- 6. on_station_tests
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS on_station_tests (
    id          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    charger_id  BIGINT UNSIGNED NOT NULL,
    tester      VARCHAR(150) DEFAULT '',
    result      VARCHAR(20)  DEFAULT '',
    note        TEXT,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_onstation_charger (charger_id),
    CONSTRAINT fk_onstation_charger FOREIGN KEY (charger_id)
        REFERENCES chargers(id) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- 7. incidents
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS incidents (
    id                   BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    charger_id           BIGINT UNSIGNED NOT NULL,
    description          TEXT,
    priority             ENUM('low','medium','high','critical') NOT NULL DEFAULT 'medium',
    status               ENUM('open','in_progress','resolved','closed') NOT NULL DEFAULT 'open',
    repair_by            VARCHAR(150) DEFAULT '',
    repair_description   TEXT,
    resolved_at          DATETIME NULL,
    created_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_incidents_charger (charger_id),
    CONSTRAINT fk_incidents_charger FOREIGN KEY (charger_id)
        REFERENCES chargers(id) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- 8. photos
-- Polymorphic attachment: module + record_id identifies the parent
-- row (e.g. module='production_test', record_id=15). No FK, since
-- record_id can point at different tables depending on module —
-- adding a new module later needs no schema change.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS photos (
    id          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    module      VARCHAR(50)  NOT NULL,
    record_id   BIGINT UNSIGNED NOT NULL,
    file_name   VARCHAR(255) NOT NULL,
    file_path   VARCHAR(500) NOT NULL,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_photos_module_record (module, record_id)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- 9. pillar_tests
-- Phiếu "Test Trụ Xuất Xưởng" (frontend: test-tru.html). Mã trụ
-- được nhập tự do (không chọn từ bảng chargers/stations), nên bảng
-- này độc lập, không ràng buộc khóa ngoại.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pillar_tests (
    id           BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
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
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_pillar_tests_pillar (pillar)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- 10. ipc_list
-- Danh sách IPC (frontend: test-ipc.html) — sổ đăng ký SN/AnyDesk/
-- UltraViewer độc lập, chưa gắn với trạm nào (được gắn sau, dưới
-- dạng bản sao JSON, khi chọn trong module Trạm Sạc).
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ipc_list (
    id                BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
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
    UNIQUE KEY uq_ipc_list_sn (sn)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- 11. tram_tong
-- Trạm Sạc (frontend: on-tram.html). tram_nho lưu nguyên mảng JSON
-- các mã IPC con (mỗi mã kèm bản sao ipc/truMaster/truSlaves đã
-- chọn), khớp đúng cấu trúc mà giao diện đã tự dựng sẵn.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tram_tong (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
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
    UNIQUE KEY uq_tram_tong_ma (ma_tong)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- 12. su_vu
-- Sự Vụ (frontend: su-vu.html) — ghi nhận báo lỗi theo mã trạm/mã
-- trụ nhập tự do, độc lập với tram_tong.
-- ------------------------------------------------------------
-- trang_thai (quy trình 6 bước): chua-xu-ly, dang-kiem-tra, da-tim-loi,
--   gui-linh-kien, linh-kien-den-noi, da-fix-dong-case
-- muc_do (mức độ ưu tiên): khan-cap, qua-han, moi-xuat-hien
CREATE TABLE IF NOT EXISTS su_vu (
    id          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    ma_tram     VARCHAR(100) NOT NULL,
    ma_tru      VARCHAR(100) NOT NULL,
    mo_ta       TEXT,
    trang_thai      VARCHAR(20)  DEFAULT 'chua-xu-ly',
    muc_do          VARCHAR(30)  DEFAULT 'moi-xuat-hien',
    xu_ly_pdf_path  VARCHAR(500) NULL, -- PDF Phiếu Xử Lý Sự Cố
    time_label      VARCHAR(50)  DEFAULT '',
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- 13. audit_log
-- Lịch sử chỉnh sửa (ai làm gì, khi nào) trên toàn bộ app — xem lại
-- ở trang Cài Đặt (chỉ admin). username lấy từ header X-Username do
-- frontend tự gắn vào mọi request ghi (xem apiPost trong từng trang).
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    username    VARCHAR(100) NOT NULL DEFAULT 'unknown',
    module      VARCHAR(50)  NOT NULL,
    action      VARCHAR(20)  NOT NULL, -- create | update | delete | export
    target      VARCHAR(255) DEFAULT '',
    detail      VARCHAR(500) DEFAULT '',
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_audit_log_created (created_at)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
