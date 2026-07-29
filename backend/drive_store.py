"""
Lưu trữ dữ liệu (tài khoản, phiếu test, trạm, sự vụ, audit log...) qua thẳng
Google Drive API — KHÔNG còn phụ thuộc Google Drive for Desktop (client hay
lỗi vặt: Paused, nhầm ổ đĩa, Stream/Mirror...). App tự gọi mạng để đồng bộ.

Gọi thẳng REST API của Drive (qua thư viện "requests", thông qua
AuthorizedSession của google-auth) thay vì dùng gói googleapiclient — vì
googleapiclient mặc định dùng httplib2, và httplib2 bị lỗi
"SSL: WRONG_VERSION_NUMBER" khi đóng gói bằng PyInstaller (rất có thể do
xung đột bản OpenSSL giữa gói cryptography và _ssl gốc của Python khi đóng
gói) — dùng "requests" (qua urllib3) ổn định hơn nhiều với PyInstaller,
lại nhẹ hơn (không cần kéo theo cả bộ googleapiclient nữa).

Kiến trúc — giống hệt cách Dropbox/Google Drive Desktop tự hoạt động, chỉ
thu nhỏ đúng phạm vi cần cho app này:
  - Đọc luôn luôn từ CACHE CỤC BỘ (nhanh, không cần chờ mạng).
  - Ghi: lưu cache cục bộ ngay (nhanh), rồi thử đẩy lên Drive; nếu mạng đang
    chậm/lỗi thì cứ để trong "hàng chờ", vòng lặp nền sẽ tự thử lại.
  - Định kỳ (mỗi 20s) tải về các thay đổi mới từ máy khác.

Mỗi bản ghi vẫn là 1 file JSON riêng (giữ nguyên quy ước cũ) — chỉ khác là
file đó giờ nằm trên Drive thay vì trên 1 ổ đĩa mạng ánh xạ (mapped drive).
"""

import json
import logging
import os
import sys
import tempfile
import threading
import time
import uuid

from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials

logger = logging.getLogger("rbcontrol")

# ID Shared Drive "Charge Station Documents" và thư mục "App Data" bên trong
# nó — cố định, xác định 1 lần khi thiết lập (không đổi trừ khi tạo lại
# Shared Drive khác).
SHARED_DRIVE_ID = "0AMg_6FEF6xeYUk9PVA"
APP_DATA_FOLDER_ID = "1vDMj1meFOirO6CDXPhnZZkDtMnH2IRPU"

COLLECTIONS = ["users", "pillar_tests", "tram_tong", "su_vu", "ipc_list", "audit_log"]
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]

DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3"

PULL_INTERVAL_SECONDS = 20
REQUEST_TIMEOUT_SECONDS = 30


def _bundle_path(name):
    """Tìm file cấu hình OAuth — khi đóng gói PyInstaller thì nó nằm trong
    thư mục giải nén tạm (_MEIPASS), khi chạy dev thì nằm ngay cạnh file này."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        bundled = os.path.join(sys._MEIPASS, name)
        if os.path.isfile(bundled):
            return bundled
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), name)


TOKEN_FILE = _bundle_path("google_drive_token.json")


def _local_cache_root():
    root = os.path.join(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir(), "RBControlCache")
    os.makedirs(root, exist_ok=True)
    return root


class DriveSync:
    def __init__(self):
        self._session = None
        self._session_lock = threading.Lock()
        self.cache_root = _local_cache_root()
        self.lock = threading.RLock()
        self.folder_ids = {}          # collection -> Drive folder id
        self.file_meta = {}           # collection -> {record_id: {"id":.., "modifiedTime":..}}
        self.pending_uploads = set()  # {(collection, record_id)} cần đẩy lên
        self.pending_deletes = {}     # {(collection, record_id): drive_file_id} cần xóa trên Drive
        self.in_flight_pushes = set()  # {(collection, record_id)} đang đẩy dở — chặn đẩy trùng
        self.miss_streak = {}          # collection -> {record_id: số lần pull liên tiếp không thấy}
        self.ready = threading.Event()  # bật khi "users" đã sẵn sàng (đủ để đăng nhập)
        self._folder_path_cache = {}   # (parent_id, name) -> Drive folder id (ảnh/PDF, khác App Data)

        threading.Thread(target=self._startup, daemon=True).start()

    # ------------------------------------------------------------------ #
    # REST client mỏng — gọi thẳng Drive API v3 qua "requests"
    # ------------------------------------------------------------------ #
    def _get_session(self):
        with self._session_lock:
            if self._session is None:
                creds = Credentials.from_authorized_user_file(TOKEN_FILE, DRIVE_SCOPES)
                self._session = AuthorizedSession(creds)  # tự refresh token khi hết hạn
            return self._session

    def _list_files(self, q, fields, page_token=None):
        res = self._get_session().get(
            f"{DRIVE_API_BASE}/files",
            params={
                "q": q, "driveId": SHARED_DRIVE_ID, "corpora": "drive",
                "includeItemsFromAllDrives": "true", "supportsAllDrives": "true",
                "fields": fields, "pageToken": page_token, "pageSize": 1000,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        res.raise_for_status()
        return res.json()

    def _create_folder(self, name, parent_id):
        res = self._get_session().post(
            f"{DRIVE_API_BASE}/files",
            params={"supportsAllDrives": "true", "fields": "id"},
            json={"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        res.raise_for_status()
        return res.json()

    def _download_file(self, file_id):
        res = self._get_session().get(
            f"{DRIVE_API_BASE}/files/{file_id}",
            params={"alt": "media", "supportsAllDrives": "true"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        res.raise_for_status()
        return res.content

    def _create_file_with_content(self, name, parent_id, content, mimetype, fields):
        boundary = uuid.uuid4().hex
        metadata = json.dumps({"name": name, "parents": [parent_id]})
        body = (
            f"--{boundary}\r\n"
            f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{metadata}\r\n"
            f"--{boundary}\r\n"
            f"Content-Type: {mimetype}\r\n\r\n"
        ).encode("utf-8") + content + f"\r\n--{boundary}--".encode("utf-8")
        res = self._get_session().post(
            f"{DRIVE_UPLOAD_BASE}/files",
            params={"uploadType": "multipart", "supportsAllDrives": "true", "fields": fields},
            data=body, headers={"Content-Type": f"multipart/related; boundary={boundary}"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        res.raise_for_status()
        return res.json()

    def _update_file_content(self, file_id, content, mimetype, fields):
        res = self._get_session().patch(
            f"{DRIVE_UPLOAD_BASE}/files/{file_id}",
            params={"uploadType": "media", "supportsAllDrives": "true", "fields": fields},
            data=content, headers={"Content-Type": mimetype},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        res.raise_for_status()
        return res.json()

    def _trash_file(self, file_id):
        res = self._get_session().patch(
            f"{DRIVE_API_BASE}/files/{file_id}",
            params={"supportsAllDrives": "true"},
            json={"trashed": True},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        res.raise_for_status()

    # ------------------------------------------------------------------ #
    # Khởi tạo
    # ------------------------------------------------------------------ #
    def _startup(self):
        try:
            self._init_folders()
            # "users" cần có ngay để đăng nhập được — ưu tiên tải trước và
            # bật "ready" NGAY sau đó (KHÔNG đợi hết mọi collection), để thời
            # gian mở app không phình to dần theo tổng dữ liệu lịch sử (audit
            # log, phiếu test... càng dùng lâu càng nhiều) — tránh timeout mở
            # app. Các màn hình khác (IPC, Trạm, Sự vụ...) có thể hiện trống
            # vài giây đầu trong lúc tải nốt ở nền, tự hết ngay sau đó.
            self._pull_collection("users")
            self.ready.set()
            for col in COLLECTIONS:
                if col != "users":
                    self._pull_collection(col)
        except Exception:
            logger.exception("Loi khi khoi tao DriveSync (_startup)")
            self.ready.set()  # đừng để app treo mãi nếu lần đầu lỗi — cứ chạy tiếp với cache rỗng
        self._sync_loop()

    def _init_folders(self):
        for col in COLLECTIONS:
            res = self._list_files(
                q=f"name='{col}' and '{APP_DATA_FOLDER_ID}' in parents and trashed=false",
                fields="files(id,name)",
            )
            files = res.get("files", [])
            if files:
                self.folder_ids[col] = files[0]["id"]
            else:
                folder = self._create_folder(col, APP_DATA_FOLDER_ID)
                self.folder_ids[col] = folder["id"]

    def _collection_cache_dir(self, collection):
        d = os.path.join(self.cache_root, collection)
        os.makedirs(d, exist_ok=True)
        return d

    # ------------------------------------------------------------------ #
    # Ảnh/PDF (Test Trụ, On Trạm, Test IPC...) — thư mục KHÁC "App Data",
    # nằm ở gốc Shared Drive (vd "List End Of Line Test/Charge Point/...",
    # "IPC/..."), tìm/tạo theo tên từng cấp thư mục con, có cache lại để
    # không phải hỏi Drive lại mỗi lần dùng cùng 1 đường dẫn.
    # ------------------------------------------------------------------ #
    def _find_or_create_folder(self, name, parent_id):
        cache_key = (parent_id, name)
        with self.lock:
            cached = self._folder_path_cache.get(cache_key)
        if cached:
            return cached
        res = self._list_files(
            q=f"name='{name}' and '{parent_id}' in parents and trashed=false",
            fields="files(id,name)",
        )
        files = res.get("files", [])
        folder_id = files[0]["id"] if files else self._create_folder(name, parent_id)["id"]
        with self.lock:
            self._folder_path_cache[cache_key] = folder_id
        return folder_id

    def resolve_folder_path(self, base_folder, segments):
        """Trả về Drive folder id sau khi tìm/tạo đủ các cấp thư mục con.
        "Charge Point" (Test Trụ Xuất Xưởng) nằm BÊN TRONG "List End Of Line
        Test", còn các baseFolder khác (vd "List On Tram", "IPC") nằm ngay ở
        gốc Shared Drive — giữ đúng cấu trúc thư mục cũ đã dùng từ trước."""
        if base_folder == "Charge Point":
            eol_id = self._find_or_create_folder("List End Of Line Test", SHARED_DRIVE_ID)
            current = self._find_or_create_folder("Charge Point", eol_id)
        else:
            current = self._find_or_create_folder(base_folder, SHARED_DRIVE_ID)
        for seg in segments:
            if seg:
                current = self._find_or_create_folder(seg, current)
        return current

    def upload_named_file(self, folder_id, filename, content, mimetype):
        """Tạo mới (hoặc ghi đè nếu đã có đúng tên trong đúng thư mục) 1 file
        — dùng cho ảnh lẻ/PDF, không cần theo dõi modifiedTime như dữ liệu
        JSON (mỗi lần xuất phiếu là 1 file mới hoặc ghi đè bản cũ, không cần
        đồng bộ 2 chiều phức tạp)."""
        res = self._list_files(
            q=f"name='{filename}' and '{folder_id}' in parents and trashed=false",
            fields="files(id)",
        )
        found = res.get("files", [])
        if found:
            return self._update_file_content(found[0]["id"], content, mimetype, "id")["id"]
        return self._create_file_with_content(filename, folder_id, content, mimetype, "id")["id"]

    def download_file_bytes(self, file_id):
        return self._download_file(file_id)

    # ------------------------------------------------------------------ #
    # Vòng lặp nền: tải thay đổi mới + đẩy các thay đổi đang chờ
    # ------------------------------------------------------------------ #
    def _sync_loop(self):
        while True:
            time.sleep(PULL_INTERVAL_SECONDS)
            for col in COLLECTIONS:
                try:
                    self._pull_collection(col)
                except Exception:
                    pass  # thử lại ở vòng sau, không làm app dừng

            with self.lock:
                pending_up = list(self.pending_uploads)
                pending_del = dict(self.pending_deletes)
            for collection, record_id in pending_up:
                self._try_push_one(collection, record_id)
            for key, file_id in pending_del.items():
                self._try_delete_one(key, file_id)

    def _pull_collection(self, collection):
        folder_id = self.folder_ids[collection]
        seen = {}
        page_token = None
        while True:
            res = self._list_files(
                q=f"'{folder_id}' in parents and trashed=false",
                fields="nextPageToken, files(id,name,modifiedTime)",
                page_token=page_token,
            )
            for f in res.get("files", []):
                if f["name"].endswith(".json"):
                    seen[f["name"][:-5]] = {"id": f["id"], "modifiedTime": f["modifiedTime"]}
            page_token = res.get("nextPageToken")
            if not page_token:
                break

        cache_dir = self._collection_cache_dir(collection)
        with self.lock:
            known = self.file_meta.setdefault(collection, {})
            pending_ids = {rid for (c, rid) in self.pending_uploads if c == collection}

        for record_id, meta in seen.items():
            if record_id in pending_ids:
                continue  # đang có thay đổi cục bộ CHƯA đẩy lên — đừng ghi đè bằng bản cũ trên Drive
            old = known.get(record_id)
            if old and old.get("modifiedTime") == meta["modifiedTime"]:
                continue  # không đổi gì, khỏi tải lại
            local_path = os.path.join(cache_dir, f"{record_id}.json")
            try:
                content = self._download_file(meta["id"])
                tmp_fd, tmp_path = tempfile.mkstemp(dir=cache_dir, prefix=".tmp_")
                with os.fdopen(tmp_fd, "wb") as fh:
                    fh.write(content)
                os.replace(tmp_path, local_path)
            except Exception:
                continue
            with self.lock:
                known[record_id] = meta

        # Bản ghi đã bị xóa ở máy khác -> xóa khỏi cache cục bộ. Chỉ xóa sau khi
        # vắng mặt ĐỦ 3 lần pull LIÊN TIẾP (~1 phút) — vì files().list() của
        # Drive đôi khi có độ trễ (eventual consistency), 1 lần "không thấy"
        # chưa chắc là đã xóa thật, tránh xóa nhầm dữ liệu cục bộ còn dùng được.
        with self.lock:
            local_ids = list(known.keys())
            miss_streak = self.miss_streak.setdefault(collection, {})
        for record_id in local_ids:
            if record_id in seen or record_id in pending_ids:
                with self.lock:
                    miss_streak.pop(record_id, None)
                continue
            with self.lock:
                miss_streak[record_id] = miss_streak.get(record_id, 0) + 1
                count = miss_streak[record_id]
            if count < 3:
                continue
            local_path = os.path.join(cache_dir, f"{record_id}.json")
            try:
                os.remove(local_path)
            except OSError:
                pass
            with self.lock:
                known.pop(record_id, None)
                miss_streak.pop(record_id, None)

    # ------------------------------------------------------------------ #
    # Đẩy 1 bản ghi lên Drive (tạo mới hoặc cập nhật)
    # ------------------------------------------------------------------ #
    def _try_push_one(self, collection, record_id):
        # save_record() gọi hàm này ngay lập tức, NHƯNG vòng lặp nền
        # (_sync_loop) cũng thử đẩy lại mọi pending_uploads mỗi 20s — nếu 2
        # đường này chạy trùng nhau cho ĐÚNG 1 record, cả 2 đều thấy "chưa có
        # file" (known=None) và cùng tạo file mới -> ra 2 file trùng tên. Chặn
        # bằng 1 "khóa" theo từng record để chỉ 1 lần đẩy chạy tại 1 thời điểm.
        key = (collection, record_id)
        with self.lock:
            if key in self.in_flight_pushes:
                return
            self.in_flight_pushes.add(key)
        try:
            self._push_one(collection, record_id)
            with self.lock:
                self.pending_uploads.discard(key)
        except Exception:
            pass  # còn trong hàng chờ, vòng lặp sau thử lại
        finally:
            with self.lock:
                self.in_flight_pushes.discard(key)

    def _push_one(self, collection, record_id):
        cache_dir = self._collection_cache_dir(collection)
        local_path = os.path.join(cache_dir, f"{record_id}.json")
        if not os.path.isfile(local_path):
            return  # đã bị xóa cục bộ trước khi kịp đẩy lên
        with open(local_path, "rb") as f:
            content = f.read()

        with self.lock:
            known = self.file_meta.get(collection, {}).get(record_id)

        if known:
            updated = self._update_file_content(known["id"], content, "application/json", "id,modifiedTime")
        else:
            updated = self._create_file_with_content(
                f"{record_id}.json", self.folder_ids[collection], content, "application/json", "id,modifiedTime",
            )

        with self.lock:
            self.file_meta.setdefault(collection, {})[record_id] = {
                "id": updated["id"], "modifiedTime": updated["modifiedTime"],
            }

    def _try_delete_one(self, key, file_id):
        try:
            # Xóa vĩnh viễn (files.delete) cần quyền "Manager" của Shared Drive
            # — tài khoản dùng cho app chỉ ở mức Content Manager (được
            # tạo/sửa/chuyển vào thùng rác, KHÔNG được xóa hẳn), nên dùng
            # "trashed=True" (chuyển vào thùng rác) thay vì xóa thẳng. Vì mọi
            # query đọc đều đã lọc "trashed=false", tác dụng với app coi như
            # đã xóa — Manager thật có thể dọn thùng rác định kỳ sau.
            self._trash_file(file_id)
            with self.lock:
                self.pending_deletes.pop(key, None)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # API công khai — dùng bởi filestore.py, giữ nguyên hành vi cũ
    # ------------------------------------------------------------------ #
    def list_records(self, collection):
        cache_dir = self._collection_cache_dir(collection)
        items = []
        for name in os.listdir(cache_dir):
            if not name.endswith(".json") or name.startswith(".tmp_"):
                continue
            try:
                with open(os.path.join(cache_dir, name), "r", encoding="utf-8") as f:
                    items.append(json.load(f))
            except (OSError, json.JSONDecodeError):
                continue
        return items

    def get_record(self, collection, record_id):
        path = os.path.join(self._collection_cache_dir(collection), f"{record_id}.json")
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

    def save_record(self, collection, record_id, data):
        record_id = str(record_id)
        cache_dir = self._collection_cache_dir(collection)
        local_path = os.path.join(cache_dir, f"{record_id}.json")
        tmp_fd, tmp_path = tempfile.mkstemp(dir=cache_dir, prefix=".tmp_")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, local_path)
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise

        with self.lock:
            self.pending_uploads.add((collection, record_id))
        self._try_push_one(collection, record_id)  # co gang day ngay - khong duoc thi vong lap nen tu thu lai

    # ------------------------------------------------------------------ #
    # Log chẩn đoán (logsetup.py) — 1 file .log riêng mỗi máy trong thư mục
    # "_logs", tần suất thấp (mỗi 30s) nên không cần cache phức tạp như trên,
    # cứ tìm theo tên rồi tạo/cập nhật là đủ.
    # ------------------------------------------------------------------ #
    def upload_log_file(self, filename, local_path):
        with open(local_path, "rb") as f:
            content = f.read()
        self.upload_log_content(filename, content)

    def upload_log_content(self, filename, content):
        """content: bytes HOẶC str — dùng cho cả log backend (đọc từ file cục
        bộ) lẫn log Electron (nhận thẳng nội dung qua API, xem server.py)."""
        if isinstance(content, str):
            content = content.encode("utf-8")

        with self.lock:
            logs_folder_id = self.folder_ids.get("_logs")
        if not logs_folder_id:
            res = self._list_files(
                q=f"name='_logs' and '{APP_DATA_FOLDER_ID}' in parents and trashed=false",
                fields="files(id,name)",
            )
            found = res.get("files", [])
            if found:
                logs_folder_id = found[0]["id"]
            else:
                folder = self._create_folder("_logs", APP_DATA_FOLDER_ID)
                logs_folder_id = folder["id"]
            with self.lock:
                self.folder_ids["_logs"] = logs_folder_id

        with self.lock:
            known_id = self.file_meta.setdefault("_logs", {}).get(filename, {}).get("id")
        if not known_id:
            res = self._list_files(
                q=f"name='{filename}' and '{logs_folder_id}' in parents and trashed=false",
                fields="files(id)",
            )
            found = res.get("files", [])
            known_id = found[0]["id"] if found else None

        if known_id:
            self._update_file_content(known_id, content, "text/plain", "id")
        else:
            created = self._create_file_with_content(filename, logs_folder_id, content, "text/plain", "id")
            known_id = created["id"]

        with self.lock:
            self.file_meta.setdefault("_logs", {})[filename] = {"id": known_id}

    def is_ready(self):
        return self.ready.is_set()

    def delete_record(self, collection, record_id):
        record_id = str(record_id)
        cache_dir = self._collection_cache_dir(collection)
        local_path = os.path.join(cache_dir, f"{record_id}.json")
        try:
            os.remove(local_path)
        except OSError:
            pass

        with self.lock:
            self.pending_uploads.discard((collection, record_id))
            known = self.file_meta.get(collection, {}).pop(record_id, None)
        if known:
            with self.lock:
                self.pending_deletes[(collection, record_id)] = known["id"]
            self._try_delete_one((collection, record_id), known["id"])
        return True


_shared_sync = None
_shared_sync_lock = threading.Lock()


def get_shared_sync():
    """1 instance DriveSync dùng chung cho cả filestore.py (dữ liệu) và
    logsetup.py (log chẩn đoán) — tránh mỗi bên tự mở 1 kết nối Drive riêng."""
    global _shared_sync
    with _shared_sync_lock:
        if _shared_sync is None:
            _shared_sync = DriveSync()
    return _shared_sync
