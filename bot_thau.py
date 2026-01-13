import time
import os
import requests
import json
from datetime import datetime
from playwright.sync_api import sync_playwright

# ==========================================
# 1. CẤU HÌNH
# ==========================================

TRELLO_API_KEY = os.environ.get('TRELLO_API_KEY')
TRELLO_TOKEN = os.environ.get('TRELLO_TOKEN')
TRELLO_LIST_ID = os.environ.get('TRELLO_LIST_ID')

KEYWORDS = [
    # Mảng Âm thanh & Hội nghị
    "âm thanh hội trường",
    "hội nghị truyền hình",
    "phòng họp trực tuyến",
    "hệ thống âm thanh",
    "màn hình led",
    "thiết bị hội thảo",
    # Mảng CNTT
    "máy tính xách tay",
    "thiết bị công nghệ thông tin",
    "phần mềm máy chủ",
    "máy chủ",
    "thiết bị tin học"
]

SCAN_LIMIT = 20
MAX_CARDS_PER_KEYWORD = 5
HISTORY_FILE = "processed_ids.txt"

# ==========================================
# 2. HÀM HỖ TRỢ
# ==========================================

def load_processed_ids():
    if not os.path.exists(HISTORY_FILE): return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f)

def save_processed_id(bid_id):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(f"{bid_id}\n")

def parse_date_flexible(date_str):
    if not date_str: return None
    formats = ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%d/%m/%Y %H:%M", "%d/%m/%Y"]
    for fmt in formats:
        try:
            clean_date = date_str[:19] if 'T' in date_str and len(date_str) > 19 else date_str
            return datetime.strptime(clean_date, fmt)
        except ValueError: continue
    return None

def check_trello_connection():
    try:
        url = f"https://api.trello.com/1/members/me?key={TRELLO_API_KEY}&token={TRELLO_TOKEN}"
        return requests.get(url).status_code == 200
    except: return False

def safe_get_text(value):
    """Hàm an toàn: Chuyển mọi thứ (List, None, Number) thành String"""
    if value is None:
        return ""
    if isinstance(value, list):
        # Nếu là list ['abc'], nối lại thành "abc"
        return " ".join(map(str, value))
    return str(value)

def create_trello_card(item, keyword_tag):
    url = "https://api.trello.com/1/cards"
    
    bid_no = safe_get_text(item.get('notifyNo') or item.get('bidNo') or "N/A")
    bid_name = safe_get_text(item.get('bidName') or "Không có tên")
    item_id = item.get('id')
    investor = safe_get_text(item.get('investorName') or "N/A")
    
    base_url = "https://muasamcong.mpi.gov.vn/web/guest/contractor-selection"
    params = (
        f"?p_p_id=egpportalcontractorselectionv2_WAR_egpportalcontractorselectionv2"
        f"&p_p_lifecycle=0&p_p_state=normal&p_p_mode=view"
        f"&_egpportalcontractorselectionv2_WAR_egpportalcontractorselectionv2_render=detail-v2"
        f"&type=es-notify-contractor&step=tbmt&id={item_id}&notifyId={item_id}&notifyNo={bid_no}"
    )
    
    price = item.get('investTotal', 0)
    price_str = f"{price:,} VNĐ" if isinstance(price, (int, float)) else str(price)
    
    desc = f"""
### 🏷️ Từ khóa: {keyword_tag}
---
- **Mã TBMT:** {bid_no}
- **Bên mời thầu:** {investor}
- **Giá gói thầu:** {price_str}
- **Ngày đăng:** {item.get('publicDate', 'N/A')}
- **Đóng thầu:** {item.get('bidCloseDate', 'N/A')}

[🔗 Xem chi tiết]({base_url + params})
    """

    query = {
        'key': TRELLO_API_KEY, 'token': TRELLO_TOKEN, 'idList': TRELLO_LIST_ID,
        'name': f"[{bid_no}] {bid_name}", 'desc': desc, 'pos': 'top'
    }

    try:
        if requests.post(url, params=query).status_code == 200:
            print(f"   ✅ Đã đẩy Trello: [{bid_no}]")
            if bid_no != "N/A": save_processed_id(bid_no)
            return True
    except Exception as e: print(f"   ❌ Lỗi Trello: {e}")
    return False

# ==========================================
# 3. CHƯƠNG TRÌNH CHÍNH
# ==========================================

def run_bot():
    if not check_trello_connection(): return

    processed_ids = load_processed_ids()
    print(f"🚀 Bot khởi động (Safe Mode).")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, slow_mo=500)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            print("🌍 Vào trang chủ...")
            page.goto("https://muasamcong.mpi.gov.vn/", timeout=90000, wait_until="domcontentloaded")
            
            # Flush dữ liệu nền
            print("🧹 Đợi dọn dẹp dữ liệu nền...")
            try:
                with page.expect_response(
                    lambda response: "contractor-selection" in response.url and response.status == 200, 
                    timeout=5000
                ): pass
            except: pass

            for keyword in KEYWORDS:
                print(f"\n🔎 --- TỪ KHÓA: '{keyword}' ---")
                
                try:
                    search_url = "https://muasamcong.mpi.gov.vn/web/guest/contractor-selection?render=index"
                    page.goto(search_url, timeout=60000, wait_until="domcontentloaded")
                    page.wait_for_timeout(1000)
                    
                    search_input = 'input[name="keyword"]'
                    page.wait_for_selector(search_input, timeout=20000)
                    
                    page.fill(search_input, "") 
                    page.fill(search_input, keyword)
                    print(f"   ✍️ Đã nhập: {keyword}")

                    print("   ⏳ Đang gửi yêu cầu...")
                    with page.expect_response(
                        lambda response: "contractor-selection" in response.url and response.status == 200, 
                        timeout=60000
                    ) as response_info:
                        page.keyboard.press("Enter")
                    
                    json_data = response_info.value.json()
                    
                    items = []
                    if 'data' in json_data: items = json_data['data']
                    elif 'page' in json_data and 'content' in json_data['page']: items = json_data['page']['content']

                    if not items:
                        print(f"   ⚠️ Không có kết quả.")
                        continue

                    # --- KIỂM TRA CHÉO (Đã fix lỗi 'list' object) ---
                    match_count = 0
                    check_limit = min(len(items), 5)
                    keyword_parts = safe_get_text(keyword).lower().split()
                    
                    for i in range(check_limit):
                        # Dùng hàm safe_get_text để đảm bảo không bị lỗi list
                        name = safe_get_text(items[i].get('bidName')).lower()
                        if any(part in name for part in keyword_parts):
                            match_count += 1
                    
                    if match_count == 0:
                        print(f"   🚨 Cảnh báo: Kết quả trả về không khớp từ khóa (Lấy nhầm). Bỏ qua.")
                        continue

                    print(f"   ✅ Dữ liệu hợp lệ. Bắt đầu lọc...")
                    
                    cards_created = 0
                    scanned_count = 0
                    current_time = datetime.now()

                    for item in items:
                        if scanned_count >= SCAN_LIMIT: break
                        scanned_count += 1
                        if cards_created >= MAX_CARDS_PER_KEYWORD: break
                        
                        bid_code = safe_get_text(item.get('notifyNo') or item.get('bidNo'))
                        if bid_code and bid_code in processed_ids: continue

                        # Check ngày hết hạn
                        close_date_str = item.get('bidCloseDate')
                        if close_date_str:
                            close_date = parse_date_flexible(close_date_str)
                            if close_date and close_date < current_time:
                                continue
                        
                        if create_trello_card(item, keyword):
                            cards_created += 1
                        
                    print(f"   ✅ Đã tạo {cards_created} thẻ mới.")
                    time.sleep(1)

                except Exception as k_err:
                    print(f"   ⚠️ Lỗi từ khóa này: {k_err}")

        except Exception as e:
            print(f"❌ Lỗi hệ thống: {e}")
        
        finally:
            print("\n🏁 Hoàn tất. Đóng trình duyệt.")
            browser.close()

if __name__ == "__main__":
    run_bot()
