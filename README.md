# Bot Mua Sắm Công

Bot tự động quét thông báo mời thầu trên Cổng mua sắm công `muasamcong.mpi.gov.vn` theo danh sách từ khóa, lọc theo giá gói thầu và tạo thẻ Trello cho các gói thầu phù hợp.

Bot chạy tự động mỗi ngày lúc 01:00 UTC (08:00 giờ Việt Nam) thông qua GitHub Actions.

## Cách hoạt động

1. Mở trang tra cứu nhà thầu của Cổng mua sắm công bằng Playwright (Chromium).
2. Với mỗi từ khóa trong `KEYWORDS`, lấy tối đa `MAX_CARDS_PER_KEYWORD` (5) thông báo mới.
3. Bỏ qua các mã đã xử lý (lưu trong `processed_ids.txt`) hoặc đã loại (ghi lý do vào `discarded_ids.txt`).
4. Lấy giá kế hoạch lựa chọn nhà thầu; bỏ qua gói có giá trị vượt `MAX_BID_PRICE` (2 tỷ VND).
5. Tạo thẻ Trello trong danh sách cấu hình sẵn, kèm link chi tiết, từ khóa, giá và thông tin bảo lãnh.
6. Ghi nhận mã đã xử lý để tránh tạo trùng ở lần chạy sau.

Danh sách từ khóa mặc định: âm thanh, hội nghị truyền hình, phòng họp, màn hình LED, thiết bị hội thảo, micro, máy tính, thiết bị công nghệ thông tin, phần mềm, máy chủ.

## Yêu cầu

- Python 3.11+
- Tài khoản Trello (API key, token, ID danh sách đích)

## Cài đặt và chạy

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install requests playwright
python -m playwright install chromium

export TRELLO_API_KEY=xxx
export TRELLO_TOKEN=xxx
export TRELLO_LIST_ID=xxx

python bot_thau.py
```

Trên Windows (PowerShell) dùng `$env:TRELLO_API_KEY="xxx"` cho từng biến. Script đọc biến môi trường của hệ thống, không tự nạp file `.env`.

## Biến môi trường

| Biến | Bắt buộc | Mô tả |
| --- | --- | --- |
| `TRELLO_API_KEY` | Có | API key Trello |
| `TRELLO_TOKEN` | Có | Token truy cập Trello |
| `TRELLO_LIST_ID` | Có | ID danh sách Trello nhận thẻ mới |

## GitHub Actions

Workflow `.github/workflows/daily_scan.yml` chạy theo lịch và có thể kích hoạt thủ công (`workflow_dispatch`). Cần khai báo repository secrets:

- `TRELLO_API_KEY`
- `TRELLO_TOKEN`
- `TRELLO_LIST_ID`

Sau mỗi lần chạy, workflow commit `processed_ids.txt` và `discarded_ids.txt` trở lại repository để duy trì lịch sử chống trùng.

## Tùy chỉnh

Sửa trực tiếp trong `bot_thau.py`:

- `KEYWORDS` — danh sách từ khóa tìm kiếm.
- `MAX_CARDS_PER_KEYWORD` — số thẻ tối đa mỗi từ khóa.
- `MAX_BID_PRICE` — ngưỡng giá gói thầu (VND).
- `HISTORY_FILE`, `DISCARD_FILE` — file lưu lịch sử.

## Lưu ý

Chỉ sử dụng cho mục đích hợp lệ và tuân thủ điều khoản của Cổng mua sắm công cũng như chính sách của Trello.
