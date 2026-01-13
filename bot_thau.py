import time
import os
import requests
import json
from datetime import datetime
from playwright.sync_api import sync_playwright

# ==========================================
# 1. CẤU HÌNH (LẤY TỪ GITHUB SECRETS)
# ==========================================
TRELLO_API_KEY = os.environ.get('TRELLO_API_KEY')
TRELLO_TOKEN = os.environ.get('TRELLO_TOKEN')
TRELLO_LIST_ID = os.environ.get('TRELLO_LIST_ID')

KEYWORDS = [
    "âm thanh hội trường", "hội nghị truyền hình", "phòng họp trực tuyến",
    "hệ thống âm thanh", "màn hình led", "thiết bị hội thảo",
    "máy tính xách tay", "thiết bị công nghệ thông tin",
    "phần mềm máy chủ", "máy chủ", "thiết bị tin học"
]

SCAN_LIMIT = 20
MAX_CARDS_PER_KEYWORD = 3
HISTORY_FILE = "processed_ids.txt"

# ==========================================
# 2. HÀM HỖ TRỢ (GIỮ NGUYÊN & TỐI ƯU)
# ==========================================
def load_processed_ids():
    if not os.path.exists(HISTORY_FILE): 
        with open(HISTORY_FILE, "w") as f: pass
        return set()
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
            d = date_str[:19] if 'T' in date_str else date_str
            return datetime.strptime(d, fmt)
        except: continue
    return None

def safe_get_text(value):
    if value is None: return ""
    if isinstance(value, list): return " ".join(map(str, value))
    return str(value)

def create_trello_card(item, keyword_tag):
    url = "https://api.trello.com/1/cards"
    bid_no = safe_get_text(item.get('notifyNo') or item.get('bidNo') or "N/A")
    bid_name = safe_get_text(item.get('bidName') or "Không tên")
    item_id = item.get('id')
    
    link = f"https://muasamcong.mpi.gov.vn/web/guest/contractor-selection?p_p_id=egpportalcontractorselectionv2_WAR_egpportalcontractorselectionv2&p_p_lifecycle=0&p_p_state=normal&p_p_mode=view&_egpportalcontractorselectionv2_WAR_egpportalcontractorselectionv2_render=detail-v2&type=es-notify-contractor&step=tbmt&id={item_id}&notifyId={item_id}&notifyNo={bid_no}"
    
    price = item.get('investTotal', 0)
    price_str = f"{price:,} VNĐ" if isinstance(price, (int, float)) else str(price)
    
    desc = f"### 🏷️ Từ khóa: {keyword_tag}\n---\n- **Mã TBMT:** {bid_no}\n- **Bên mời thầu:** {item.get('investorName')}\n- **Giá:** {price_str}\n- **Đóng thầu:** {item.get('bidCloseDate')}\n\n[🔗 Xem chi tiết]({link})"

    query = {'key': TRELLO_API_KEY, 'token': TRELLO_TOKEN, 'idList': TRELLO_LIST_ID, 'name': f"[{bid_no}] {bid_name}", 'desc': desc, 'pos': 'top'}
    if requests.post(url, params=query).status_code == 200:
        print(f"   ✅ Trello OK: [{bid_no}]")
        save_processed_id(bid_no)
        return True
    return False

# ==========================================
# 3. CHƯƠNG TRÌNH CHÍNH
# ==========================================
def run_bot():
    processed_ids = load_processed_ids()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True) # Headless=True khi chạy GitHub
        page = browser.new_page(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

        try:
            print("🌍 Khởi tạo tại trang chủ...")
            page.goto("https://muasamcong.mpi.gov.vn/", timeout=90000)
            page.wait_for_timeout(5000) # Đợi dọn dẹp dữ liệu rác ban đầu

            for keyword in KEYWORDS:
                print(f"\n🔎 Tìm kiếm: '{keyword}'")
                page.goto("https://muasamcong.mpi.gov.vn/web/guest/contractor-selection?render=index", timeout=60000)
                page.wait_for_timeout(2000)
                
                search_input = 'input[name="keyword"]'
                page.wait_for_selector(search_input)
                page.fill(search_input, keyword)

                # CHỐNG NHẦM: Đợi gói tin phản hồi phải chứa keyword trong response
                try:
                    with page.expect_response(lambda r: "contractor-selection" in r.url and r.status == 200, timeout=45000) as resp:
                        page.keyboard.press("Enter")
                    
                    data = resp.value.json()
                    items = data.get('data') or data.get('page', {}).get('content') or []
                    
                    if not items: continue

                    # KIỂM TRA XÁC SUẤT: Nếu gói đầu tiên hoàn toàn không liên quan, bỏ qua kết quả này
                    first_name = safe_get_text(items[0].get('bidName')).lower()
                    keyword_parts = keyword.lower().split()
                    if not any(part in first_name for part in keyword_parts):
                        print(f"   🚨 Phát hiện lấy nhầm dữ liệu (Băng tải/Cơ khí). Đang bỏ qua...")
                        continue

                    print(f"   📦 Tìm thấy {len(items)} kết quả hợp lệ.")
                    count = 0
                    now = datetime.now()
                    for item in items:
                        if count >= MAX_CARDS_PER_KEYWORD: break
                        bid_code = safe_get_text(item.get('notifyNo') or item.get('bidNo'))
                        if bid_code in processed_ids: continue
                        
                        close_date = parse_date_flexible(item.get('bidCloseDate'))
                        if close_date and close_date < now: continue
                        
                        if create_trello_card(item, keyword): count += 1
                except Exception as e:
                    print(f"   ⚠️ Lỗi tìm kiếm từ khóa '{keyword}': {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    run_bot()
