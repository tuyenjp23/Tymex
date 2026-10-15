# Bản web trên điện thoại: Cloudflare Pages + Supabase + GitHub

Cách hoạt động (chỉ một mình bạn dùng, vào bằng tên đăng nhập + mật khẩu):

```
GitHub Actions (mỗi 3 giờ)            Supabase                      Cloudflare Pages
 chạy Python: lấy dữ liệu bóng đá  →  lưu trận, phân tích,   →   web tĩnh (thư mục web/)
 tính dự đoán, chấm điểm              dự đoán (có đăng nhập)        đọc dữ liệu sau khi bạn đăng nhập
```

- Không cần bật laptop. Khóa API bóng đá chỉ nằm trong GitHub Secrets, không bao giờ đến trình duyệt.
- Bản chạy trên máy (`start.bat`) vẫn nguyên vẹn, hai bản độc lập nhau.

## Bước 1. Supabase (đăng nhập và lưu dữ liệu)
1. Vào supabase.com → New project (chọn vùng gần Nhật, ví dụ Tokyo). Ghi nhớ mật khẩu database (không cần dùng tới).
2. Menu **SQL Editor** → New query → dán toàn bộ file `cloud/supabase_schema.sql` → **Run**.
3. Menu **Authentication → Users → Add user → Create new user**: email `tuyen@tymex.app` (tên đăng nhập sẽ là `tuyen`), đặt mật khẩu mạnh, **bật Auto Confirm User**.
4. Trong cài đặt đăng nhập của Authentication (mục Sign In / Providers), **tắt "Allow new users to sign up"** để không ai tự tạo tài khoản.
5. Lấy URL và khóa (giao diện Supabase đã đổi tên một số mục, tìm theo mô tả dưới đây):
   - **Project URL** (dạng `https://xxxx.supabase.co`): ngay trang **Home** của project, hoặc nút **Connect** ở thanh trên, hoặc **Project Settings → Data API**.
   - **Khóa** nằm ở **Project Settings → API Keys**. Có hai kiểu: kiểu mới là *Publishable key* (`sb_publishable_...`) và *Secret key* (`sb_secret_...`); kiểu cũ là `anon` và `service_role`, nằm ở thẻ **Legacy API Keys**.
   - Khóa công khai (`anon` hoặc Publishable): điền vào `web/config.js` (được phép công khai; an toàn nhờ đăng nhập + RLS). Nên ưu tiên khóa `anon` ở thẻ Legacy nếu còn hiện, vì thư viện web đang dùng đã được thử với kiểu này.
   - Khóa bí mật (`service_role` hoặc Secret): CHỈ đặt vào GitHub Secrets (bước 2). Không dán vào `config.js`, không gửi cho ai. Cả hai kiểu đều dùng được cho phần GitHub Actions.

## Bước 2. GitHub (mã nguồn + cập nhật tự động)
1. Tạo repository **Private** và đẩy cả thư mục dự án lên (file `.env` và `data/*.db` đã nằm trong `.gitignore`).
   Tạo thư mục `.github/workflows/` rồi **sao chép** file `cloud/github-workflow-sync.yml` vào đó với tên `sync.yml` (công cụ của Claude không ghi được vào thư mục `.github`, nên file này để ở `cloud/`).
2. Repository → **Settings → Secrets and variables → Actions → New repository secret**, tạo 3 secret:
   `FOOTBALL_DATA_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`.
   (Tùy chọn: tab Variables, biến `LEAGUES` ví dụ `PL,PD,BL1,SA,FL1`.)
3. Tab **Actions** → "Đồng bộ dữ liệu" → **Run workflow**. Lần đầu mất vài phút (gói miễn phí giới hạn 10 lần gọi/phút).
   Khi chạy xong màu xanh là dữ liệu đã lên Supabase. Sau đó workflow tự chạy mỗi 3 giờ.

## Bước 3. Cloudflare Pages (giao diện)
1. Sửa `web/config.js`: điền `SUPABASE_URL` và `SUPABASE_ANON_KEY` rồi commit/push.
2. Cloudflare → **Workers & Pages → Create → Pages → Connect to Git** → chọn repository.
3. Cấu hình build: Framework preset **None**, Build command **để trống**, Build output directory **`web`**.
4. Deploy xong sẽ có địa chỉ dạng `https://<tên>.pages.dev`. Mở trên điện thoại, đăng nhập `tuyen` + mật khẩu. Mỗi lần push lên GitHub, Cloudflare tự triển khai lại.

## Lưu ý
- Dữ liệu cập nhật theo lịch (3 giờ/lần), nên tỷ số trận đang đá có thể chậm. Muốn cập nhật ngay: Actions → Run workflow.
- Phân tích chi tiết được tính sẵn cho trận từ 30 ngày trước đến 14 ngày tới; trận cũ hơn không mở được trang phân tích.
- Bản web chỉ xem: không có nút đồng bộ, nhập khóa API hay viết bài AI (khóa nằm trong GitHub Secrets).
- GitHub có thể tạm dừng workflow theo lịch nếu repository không có hoạt động trong thời gian dài; khi đó chỉ cần bấm Run workflow lại.
- Quên mật khẩu: Supabase → Authentication → Users → đặt lại mật khẩu.
- Chạy thử trên máy: `python scripts/cloud_sync.py` cần 3 biến môi trường như trên; test: `pytest -q`.
