# Tóm tắt dự án Football Analytics (Tymex) - để chuyển ngữ cảnh

> File này KHÔNG chứa khóa/mật khẩu. Không dán khóa vào đây.

## 1. Mục tiêu
Web phân tích bóng đá cá nhân (lịch thi đấu, bảng xếp hạng, dự đoán Poisson, lịch sử dự đoán). Chỉ một mình Tuyen dùng, xem trên điện thoại ở mọi mạng, chỉ cần đăng nhập (tên đăng nhập + mật khẩu).

## 2. Kiến trúc
Nguồn dữ liệu (football-data.org) -> GitHub Actions (mỗi 3 giờ + chạy tay) chạy `scripts/cloud_sync.py` -> đồng bộ + tính dự đoán -> đẩy lên Supabase (bảng `matches`, `analysis`, `kv`, RLS chỉ cho `authenticated` đọc; file SQLite lưu ở Storage bucket `tymex-private`) -> web tĩnh trong `web/` (Cloudflare Worker static assets) đọc bằng supabase-js sau khi đăng nhập.

- Frontend: Cloudflare Worker, URL https://tymex.tuyenjp23.workers.dev, cấu hình `wrangler.jsonc` (assets = `./web`), tự deploy khi push lên `main`.
- Đăng nhập: Supabase Auth, tên đăng nhập `tuyen` được ánh xạ thành email `tuyen@tymex.app` (tắt đăng ký, user tạo sẵn).
- Mã nguồn: GitHub repo private `Tymex` (đẩy bằng GitHub Desktop). Repo public cũ `Tymex-football` cần xóa.

## 3. File quan trọng
- `app/cloud/supabase.py`, `app/cloud/export.py`, `scripts/cloud_sync.py`: phần đẩy dữ liệu lên Supabase.
- `cloud/supabase_schema.sql`: tạo bảng (chạy trong Supabase SQL Editor).
- `.github/workflows/sync.yml` (bản gốc `cloud/github-workflow-sync.yml`): workflow đồng bộ.
- `web/index.html`, `web/app.js`, `web/data.js`, `web/styles.css`, `web/config.js`: giao diện.
- `HUONG_DAN_CLOUD.md`: hướng dẫn triển khai.
- `app/prediction/poisson.py`: mô hình (chưa đổi).

## 4. Cấu hình (giá trị thật KHÔNG ghi ở đây)
`web/config.js` (khóa anon là public, được phép nằm trong file này):
```js
window.TYMEX_CONFIG = {
  SUPABASE_URL: "https://<project-id>.supabase.co",
  SUPABASE_ANON_KEY: "<anon key, MỘT dòng>",
  USERNAME_DOMAIN: "tymex.app",
};
```
GitHub Secrets (Settings > Secrets and variables > Actions): `FOOTBALL_DATA_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` (khóa `sb_secret_...` hoặc `service_role`).

Quy tắc bắt buộc:
- `SUPABASE_URL` chỉ là `https://<project-id>.supabase.co`, KHÔNG có `/rest/v1/`.
- Mọi khóa/secret phải nằm trên một dòng, KHÔNG bấm Enter sau khi dán (ký tự xuống dòng gây lỗi cú pháp ở `config.js` và `InvalidURL` ở workflow).
- Khóa `service_role`/`sb_secret_` chỉ để trong GitHub Secrets, không đưa vào `config.js`, không commit `.env`, repo luôn private.

## 5. Đã xong
- Review, vá bảo mật, sửa N+1, `start.bat`; 83 test chạy qua.
- Triển khai Cloudflare + Supabase + GitHub; trang đăng nhập hoạt động, đăng nhập được.

## 6. Còn dang dở (làm tiếp từ đây)
1. Workflow "Đồng bộ dữ liệu" lần #1 bị lỗi: `httpx.InvalidURL ... '\n' at position 49` tại `client.ensure_bucket(BUCKET)`. Nguyên nhân: secret `SUPABASE_URL` trên GitHub dính đuôi `/rest/v1/` và ký tự xuống dòng. Cần cập nhật lại 3 secret (một dòng, đúng URL), rồi Actions > Đồng bộ dữ liệu > Run workflow. Trang web hiện báo "Chưa có dữ liệu" cho đến khi lần chạy này xanh.
2. Sửa code để tự `strip()` khoảng trắng/xuống dòng và bỏ `/rest/v1/` ở `SUPABASE_URL`/`SUPABASE_SERVICE_KEY` (chưa làm, Tuyen chưa đồng ý).
3. Xóa repo public `Tymex-football`.
4. Kiểm tra bảng đã tạo trong Supabase (đã chạy `cloud/supabase_schema.sql` chưa) khi workflow chạy lại.

## 7. Kế hoạch về sau: thêm nguồn dữ liệu
- Nguồn API khác: thêm lớp kế thừa `FootballDataProvider` trong `app/data_providers/`, thêm secret mới nếu cần, sửa workflow, push.
- Nguồn CSV: viết `scripts/import_csv.py` (cần file CSV mẫu để ánh xạ cột), đặt file vào `data_import/`, workflow tự nhập. Cần bảng quy đổi tên đội, ghi kèm tên nguồn, nhập lặp không tạo trùng.
- Không khuyến nghị cào (scraping) web; ưu tiên API chính thức hoặc file công khai. Kiểm tra điều khoản sử dụng của từng nguồn.
- Hoãn: hiệu chỉnh Dixon-Coles cho mô hình Poisson cho đến khi có dữ liệu thật để backtest.
- (2026-10-26) Đã triển khai hiệu chỉnh Dixon-Coles (ρ = −0,08, `MODEL_VERSION = "poisson-v2-dc"`, `score_matrix(..., rho=...)`, `predict()` dùng sẵn) vì kho dữ liệu thật đã đủ lớn (~21 nghìn trận nhập lịch sử) để việc hiệu chỉnh có ý nghĩa. Cùng đợt: thêm `app/prediction/live.py` (dự đoán trực tiếp `predict_live` + mô phỏng `simulate_match`), endpoint `GET /api/matches/{id}/live-prediction`, và trang **Trực tiếp** ở bản web lấy tỷ số/thống kê trực tiếp phía trình duyệt từ ESPN (nhiều giải châu Âu/Á/Mỹ, Cúp C1 ưu tiên) + quét toàn cầu TheSportsDB (phủ K League, V.League), kèm chế độ mô phỏng có gắn nhãn rõ. Dự đoán trước trận vẫn chỉ chạy trên các giải đã đồng bộ football-data.org/Supabase như cũ.

## 8. Ghi chú khi làm việc với Tuyen
- Trả lời tiếng Việt, hướng dẫn từng bước đơn giản (Tuyen không rành Git/CLI, dùng GitHub Desktop và giao diện web).
- Gọi công ty là "ナカシマ".
- Không tự ý ghi vào `library\Claude` khi chưa hỏi.
