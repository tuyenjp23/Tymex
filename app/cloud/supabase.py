"""Client Supabase tối giản (REST + Storage) dùng khóa service_role. CHỈ chạy trên GitHub Actions, không bao giờ đưa xuống trình duyệt."""
from __future__ import annotations

import httpx


class SupabaseError(Exception):
    pass


class SupabaseClient:
    def __init__(self, url: str, service_key: str, *, timeout: float = 120.0, transport: httpx.BaseTransport | None = None):
        if not url or not service_key:
            raise SupabaseError("Thiếu SUPABASE_URL hoặc SUPABASE_SERVICE_KEY.")
        self.base = url.rstrip("/")
        headers = {"apikey": service_key}
        if not service_key.startswith("sb_secret_"):
            # Khóa service_role kiểu cũ là JWT nên gửi thêm Authorization; khóa "secret" kiểu mới (sb_secret_...) không phải JWT, chỉ gửi apikey.
            headers["Authorization"] = f"Bearer {service_key}"
        self._c = httpx.Client(timeout=timeout, transport=transport, headers=headers)

    @staticmethod
    def _check(resp: httpx.Response, what: str) -> None:
        if resp.status_code >= 300:
            # Không in nội dung request (có thể chứa khóa); chỉ in mã và phản hồi của máy chủ.
            raise SupabaseError(f"Supabase {what} lỗi HTTP {resp.status_code}: {resp.text[:300]}")

    # ------------------------------------------------------------------ bảng dữ liệu
    def upsert(self, table: str, rows: list[dict], on_conflict: str, batch: int = 300) -> int:
        """Ghi đè theo khóa chính. Mọi dòng trong cùng một lô phải có cùng bộ cột (yêu cầu của PostgREST)."""
        for i in range(0, len(rows), batch):
            resp = self._c.post(f"{self.base}/rest/v1/{table}", params={"on_conflict": on_conflict}, json=rows[i:i + batch],
                                headers={"Prefer": "resolution=merge-duplicates,return=minimal"})
            self._check(resp, f"upsert {table}")
        return len(rows)

    # ------------------------------------------------------------------ bảng kv (đọc/gọn dẹp cho các job nhẹ)
    def get_kv(self, key: str) -> dict | None:
        """Đọc một dòng của bảng kv theo khóa; chưa có thì trả None."""
        resp = self._c.get(f"{self.base}/rest/v1/kv",
                           params={"select": "key,payload,updated_at", "key": f"eq.{key}", "limit": "1"})
        self._check(resp, "đọc kv")
        rows = resp.json()
        return rows[0] if rows else None

    def prune_kv_prefix(self, prefix: str, updated_before: str) -> int:
        """Xóa các dòng kv có khóa bắt đầu bằng `prefix` và updated_at cũ hơn mốc ISO cho trước.

        Hai bước (đếm trước bằng cùng điều kiện rồi mới DELETE) để việc dọn dẹp có con số kiểm chứng
        và dùng đúng mẫu truy vấn PostgREST như phần còn lại của client."""
        cond = {"key": f"like.{prefix}*", "updated_at": f"lt.{updated_before}"}
        resp = self._c.get(f"{self.base}/rest/v1/kv", params={"select": "key", **cond})
        self._check(resp, "liệt kê kv cần dọn")
        keys = [r["key"] for r in resp.json()]
        if not keys:
            return 0
        resp = self._c.delete(f"{self.base}/rest/v1/kv", params=cond,
                              headers={"Prefer": "return=minimal"})
        self._check(resp, "xóa kv cũ")
        return len(keys)

    # ------------------------------------------------------------------ Storage (lưu file SQLite giữa các lần chạy)
    def ensure_bucket(self, bucket: str) -> None:
        resp = self._c.post(f"{self.base}/storage/v1/bucket", json={"id": bucket, "name": bucket, "public": False})
        if resp.status_code in (200, 201):
            return
        if resp.status_code in (400, 409) and "exist" in resp.text.lower():
            return   # đã có sẵn
        self._check(resp, "tạo bucket")

    def download_object(self, bucket: str, path: str) -> bytes | None:
        resp = self._c.get(f"{self.base}/storage/v1/object/{bucket}/{path}")
        if resp.status_code in (400, 404):
            return None   # chưa có file (lần chạy đầu tiên)
        self._check(resp, "tải file")
        return resp.content

    def upload_object(self, bucket: str, path: str, data: bytes) -> None:
        resp = self._c.post(f"{self.base}/storage/v1/object/{bucket}/{path}", content=data,
                            headers={"x-upsert": "true", "Content-Type": "application/octet-stream"})
        self._check(resp, "tải file lên")
