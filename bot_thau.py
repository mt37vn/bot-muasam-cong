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

if not TRELLO_API_KEY:
    raise ValueError("LỖI: Thiếu biến môi trường TRELLO_API_KEY! Hãy kiểm tra cấu hình .env hoặc biến môi trường hệ thống.")

KEYWORDS = [
    "âm thanh", "hội nghị truyền hình", "phòng họp", "màn hình led",
    "thiết bị hội thảo", "micro", "máy tính", "thiết bị công nghệ thông tin",
    "phần mềm", "máy chủ"
]

VERSION = "1.2.0"
MAX_CARDS_PER_KEYWORD = 5
MAX_BID_PRICE = 2_000_000_000
HISTORY_FILE = "processed_ids.txt"
DISCARD_FILE = "discarded_ids.txt"

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# ==========================================
# 2. HÀM HỖ TRỢ
# ==========================================
def load_processed_ids() -> set:
    if not os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "w") as f:
            pass
        return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def save_processed_id(bid_id):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(f"{bid_id}\n")

def load_discarded_ids() -> set:
    if not os.path.exists(DISCARD_FILE):
        return set()
    with open(DISCARD_FILE, "r", encoding="utf-8") as f:
        return set(line.split("|")[0].strip() for line in f if line.strip())

def save_discarded_id(bid_id, reason, discarded_set):
    if bid_id in discarded_set:
        return
    discarded_set.add(bid_id)
    try:
        with open(DISCARD_FILE, "a", encoding="utf-8") as f:
            f.write(f"{bid_id} | {reason}\n")
    except:
        pass

def parse_date_flexible(date_str):
    if not date_str:
        return None
    formats = ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%d/%m/%Y %H:%M", "%d/%m/%Y"]
    for fmt in formats:
        try:
            s = date_str
            if "T" in s and "." not in s:
                s = s[:19]
            return datetime.strptime(s, fmt)
        except:
            continue
    return None

def safe_get_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(map(str, value))
    return str(value)

def format_vnd(x):
    if x is None:
        return ""
    if isinstance(x, (int, float)):
        return f"{x:,.0f} VND"
    try:
        n = float(str(x).replace(",", "").strip())
        return f"{n:,.0f} VND"
    except:
        return str(x)

def normalize_price(x):
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    try:
        cleaned = str(x).replace(",", "").replace("VND", "").strip()
        return float(cleaned)
    except:
        return None

def _try_parse_json_maybe(s):
    if not s:
        return None
    if isinstance(s, dict):
        return s
    if isinstance(s, str):
        ss = s.strip()
        try:
            return json.loads(ss)
        except:
            return None
    return None

# ==========================================
# 3. KHLCNT LOOKUP LOGIC
# ==========================================
def build_khlcnt_detail_url(plan_no: str, plan_id: str) -> str:
    """URL trang chi tiết KHLCNT"""
    # Nếu có ID thì dùng kèm, nếu không thì chỉ dùng planNo (hy vọng web tự redirect)
    base_url = (
        "https://muasamcong.mpi.gov.vn/en/web/guest/contractor-selection?"
        "p_p_id=egpportalcontractorselectionv2_WAR_egpportalcontractorselectionv2"
        "&p_p_lifecycle=0&p_p_state=normal&p_p_mode=view"
        "&_egpportalcontractorselectionv2_WAR_egpportalcontractorselectionv2_render=detail-v2"
        "&type=es-plan-project-p&step=tbmt&stepCode=plan-step-1"
        f"&planNo={plan_no}"
    )
    if plan_id:
        base_url += f"&id={plan_id}"
        
    return base_url + "&notifyId=undefined&notifyNo=undefined&bidMode=undefined&bidForm=undefined"

def fetch_khlcnt_detail_json(page, plan_no: str, plan_id: str):
    url = build_khlcnt_detail_url(plan_no, plan_id)
    def is_target_xhr(resp):
        try:
            return (
                resp.status == 200
                and "application/json" in (resp.headers or {}).get("content-type", "")
                and "contractor-selection" in resp.url
            )
        except:
            return False
            
    # Capture Plan Detail Response
    captured_plan_data = []
    def handle_plan_response(response):
        try:
             if is_target_xhr(response):
                # print(f"      📡 Captured Plan API: {response.url}")
                json_data = response.json()
                captured_plan_data.append(json_data)
        except:
            pass

    page.on("response", handle_plan_response)

    try:
        page.goto(url, timeout=20000)
        page.wait_for_timeout(2000)
    except Exception as e:
        print(f"      ⚠️ Fetch Plan Nav Warning: {e}")
        # Don't return None yet, check if we captured data!

    try:
        if captured_plan_data:
            return captured_plan_data[0]
            
        return None
    finally:
        page.remove_listener("response", handle_plan_response)

def fetch_tbmt_detail_json(page, tbmt_id):
    """
    Vào trang chi tiết TBMT để lấy thông tin (đặc biệt là ID của KHLCNT).
    """
    # URL detail TBMT (dùng render=detail-v2)
    # Tuy nhiên để nhẹ, ta có thể gọi thẳng API nếu biết endpoint. 
    # Nhưng để an toàn (bắt chước user), ta navigate vào trang detail.
    url = (
        "https://muasamcong.mpi.gov.vn/web/guest/contractor-selection?"
        "p_p_id=egpportalcontractorselectionv2_WAR_egpportalcontractorselectionv2"
        "&p_p_lifecycle=0&p_p_state=normal&p_p_mode=view"
        "&_egpportalcontractorselectionv2_WAR_egpportalcontractorselectionv2_render=detail-v2"
        "&type=es-notify-contractor&step=tbmt"
        f"&id={tbmt_id}&notifyId={tbmt_id}"
    )
    
    # Predicate bắt JSON detail
    # Predicate bắt JSON detail
    # Update: Dùng list để hứng tất cả response JSON
    captured_data = []
    
    def handle_response(response):
        try:
            if (
                response.status == 200 
                and "application/json" in (response.headers or {}).get("content-type", "")
                and "contractor-selection" in response.url
            ):
                # print(f"      📡 Captured: {response.url}")
                json_data = response.json()
                captured_data.append(json_data)
                
                # DEBUG: Nếu là API tiềm năng, in luôn ra màn hình
                if "lcnt_tbmt_ttc_ldt" in response.url:
                    # print("      📡 Captured TBMT Detail API")
                    pass
        except:
            pass

    # Attach listener
    page.on("response", handle_response)

    try:
        # Không dùng expect_response nữa mà dùng wait
        # page.goto có thể timeout nhưng ta vẫn muốn check captured_data
        page.goto(url, timeout=20000)
        page.wait_for_timeout(3000) # Đợi thêm tí cho chắc
    except Exception as e:
        print(f"      ⚠️ Page load warning: {e}")
        # Không return None ngay, mà check captured_data xem vớt vát được gì không
    
    try:
        # Detach listener (optional)
        page.remove_listener("response", handle_response)
        
        if captured_data:
            # Tìm JSON xịn nhất trong đống captured
            # Ưu tiên 1: Có bidpPlanDetail (là cái ta cần)
            for d in captured_data:
                if d.get('bidpPlanDetail') or (d.get('data') and d.get('data').get('bidpPlanDetail')):
                    return d
            
            # Ưu tiên 2: Có planId ở root hoặc data (backup cũ)
            for d in captured_data:
                data_obj = d.get('data') or d
                if data_obj.get('planId') or data_obj.get('idKhlcnt'):
                    return d
        
        # Fallback return anything
        return captured_data[0] if captured_data else None

    except Exception as e:
        print(f"      ⚠️ Processing TBMT Detail failed: {e}")
        return None

def find_plan_id_by_no(page, plan_no):
    """
    Search tìm Plan ID từ Plan No (Fallback logic - Homepage).
    """
    print(f"      🔎 [Fallback] Looking up Plan info for: {plan_no}")
    try:
        # 1. Vào trang chủ (render=index) chứa selector radio-khlcnt như user cung cấp
        search_url = "https://muasamcong.mpi.gov.vn/web/guest/contractor-selection?render=index"
        page.goto(search_url, wait_until="domcontentloaded")
        
        # 2. Click Radio Button KHLCNT
        # Selector user cung cấp: <label for="radio-khlcnt"><input id="radio-khlcnt" ...></label>
        try:
            # Click vào label là chuẩn nhất
            page.locator("label[for='radio-khlcnt']").first.click(timeout=5000)
            
            # Double check: kiểm tra xem input có checked không
            is_checked = page.evaluate("document.querySelector('#radio-khlcnt').checked")
            if not is_checked:
                print("        ⚠️ Radio not checked after label click. Forcing JS click...")
                page.evaluate("document.querySelector('#radio-khlcnt').click()")
                
        except Exception as e:
            print(f"        ⚠️ Click radio KHLCNT failed: {e}")
            # Fallback cuối cùng: Force click input
            try:
                page.locator("#radio-khlcnt").click(timeout=2000, force=True)
            except:
                pass
            
        page.wait_for_timeout(2000) # Chờ UI switch mode
            
        # 3. Nhập từ khóa
        search_input = 'input[name="keyword"]'
        page.wait_for_selector(search_input, timeout=15000)
        page.fill(search_input, plan_no)
        
        # 4. Trigger Search
        with page.expect_response(lambda r: "contractor-selection" in r.url and r.status == 200, timeout=15000) as resp:
            page.keyboard.press("Enter")
            
        data = resp.value.json()
        items = data.get('data') or data.get('page', {}).get('content') or []
        
        # 5. Tìm chính xác planNo
        for item in items:
            p_no = safe_get_text(item.get('planNo') or item.get('notifyNo')).strip()
            if p_no == plan_no:
                return safe_get_text(item.get('id')), item
                
        return None, None
    except Exception as e:
        print(f"      ⚠️ Lookup failed: {e}")
        return None, None

def get_khlcnt_price_from_plan(kh_page, plan_cache, plan_no, tbmt_notify_no, tbmt_id):
    """
    Tìm giá dự toán trong Plan.
    Flow mới:
    1. Vào chi tiết TBMT (dùng tbmt_id) -> Lấy planId.
    2. Vào chi tiết Plan (dùng planId hoặc planNo nếu không có ID) -> Lấy giá.
    """
    if not plan_no and not tbmt_id:
        return None, None, None
        
    # Check cache
    guarantee_val = None
    if plan_no and plan_no in plan_cache:
        plan_detail = plan_cache[plan_no]
    else:
        # 1. Tìm ID của Plan từ chi tiết TBMT (Cố gắng lấy ID xịn)
        plan_id = None
        
        # Thử lấy ID từ tbmt detail
        try:
            print(f"      🔗 Fetching TBMT Detail to get Plan ID...")
            tbmt_detail = fetch_tbmt_detail_json(kh_page, tbmt_id)
            if tbmt_detail:
                data_obj = tbmt_detail.get('data') or tbmt_detail
                
                # Extract Guarantee Value (Bid Security)
                # Check bidNotification or bidoNotifyContractorM (older/variant structures)
                bid_notif = (
                    data_obj.get('bidNoContractorResponse', {}).get('bidNotification') 
                    or data_obj.get('bidoNotifyContractorM')
                    or data_obj.get('bidNotification')
                )
                if bid_notif:
                    guarantee_val = bid_notif.get('guaranteeValue')

                plan_id = data_obj.get('planId') or data_obj.get('idKhlcnt')
                
                # Check for nested bidpPlanDetail (common in new API)
                if data_obj.get('bidpPlanDetail'):
                    plan_inner = data_obj['bidpPlanDetail']
                    
                    # Try to extract Price directly!
                    direct_price, direct_unit = _extract_price(plan_inner)
                    direct_price = normalize_price(direct_price)
                    if direct_price is not None:
                        print(f"      💰 Info: Found Price in TBMT Detail. Skipping Plan fetch.")
                        # Simulate plan detail for cache if needed, or just return
                        return direct_price, direct_unit, guarantee_val
                    
                    if not plan_id:
                        plan_id = plan_inner.get('planId') or plan_inner.get('id')
        except Exception as e:
            print(f"      ⚠️ TBMT Detail parse error: {e}")
            
        if not plan_id:
            print(f"      ⚠️ Missing Plan ID. Switching to Search Fallback (Homepage)...")
            # Fallback: Search thủ công
            plan_id, _ = find_plan_id_by_no(kh_page, plan_no)
            
        if not plan_id:
            print("      ❌ Fallback failed. Cannot find Plan ID.")
            return None, None, guarantee_val
        
        print(f"      ✅ Plan ID Found: {plan_id}")
        print(f"      📂 Fetching Plan Detail (No: {plan_no}, ID: {plan_id})...")
        plan_detail = fetch_khlcnt_detail_json(kh_page, plan_no, plan_id)
        if plan_no:
            plan_cache[plan_no] = plan_detail # Save to cache
        
    if not plan_detail:
        return None, None, guarantee_val

    # 3. Tìm gói thầu trong Plan detail khớp notifyNo
    # Flatten list packages
    candidates = []
    for k in ["bidpPlanDetailToProjectList", "bidpPlanDetailList", "bidpPlanDetails"]:
        v = plan_detail.get(k)
        if isinstance(v, list): candidates = v; break
    if not candidates:
        for w in ["detailKhlcntRes", "data", "result"]:
            v = plan_detail.get(w, {})
            if isinstance(v, dict):
                for k in ["bidpPlanDetailToProjectList", "bidpPlanDetailList"]:
                    vv = v.get(k)
                    if isinstance(vv, list): candidates = vv; break
    
    # Matching
    tbmt_notify_no = tbmt_notify_no.strip()
    price, unit = None, None
    for pkg in candidates:
        # Check notifyNo directly
        if safe_get_text(pkg.get('notifyNo')).strip() == tbmt_notify_no:
            price, unit = _extract_price(pkg)
            price = normalize_price(price)
            break
            
        # Check inside linkNotifyInfo
        link_info = _try_parse_json_maybe(pkg.get('linkNotifyInfo'))
        if isinstance(link_info, dict):
            if safe_get_text(link_info.get('notifyNo')).strip() == tbmt_notify_no:
                price, unit = _extract_price(pkg)
                price = normalize_price(price)
                break
                
    return price, unit, guarantee_val

def _extract_price(pkg):
    price = pkg.get("bidPrice") or pkg.get("bidEstimatePrice") or pkg.get("planItemPrice")
    unit = pkg.get("bidPriceUnit") or pkg.get("bidPriceUnitName") or pkg.get("currencyCode")
    return price, unit


# ==========================================
# 4. TẠO CARD TRELLO
# ==========================================
def create_trello_card(item, keyword_tag, kh_price, kh_unit, guarantee_val):
    url_api = "https://api.trello.com/1/cards"
    
    bid_no = safe_get_text(item.get('notifyNo') or item.get('bidNo') or "N/A")
    bid_name = safe_get_text(item.get('bidName') or "Không tên")
    item_id = item.get('id')
    plan_no = safe_get_text(item.get('planNo'))
    
    close_date_str = item.get('bidCloseDate')
    
    # Link TBMT
    link = (
        "https://muasamcong.mpi.gov.vn/web/guest/contractor-selection?"
        "p_p_id=egpportalcontractorselectionv2_WAR_egpportalcontractorselectionv2"
        "&p_p_lifecycle=0&p_p_state=normal&p_p_mode=view"
        "&_egpportalcontractorselectionv2_WAR_egpportalcontractorselectionv2_render=detail-v2"
        "&type=es-notify-contractor&step=tbmt"
        f"&id={item_id}&notifyId={item_id}&notifyNo={bid_no}"
    )

    # Format Giá
    # Số tiền bảo đảm dự thầu
    guarantee_str = format_vnd(guarantee_val) if guarantee_val is not None else "N/A"
    
    # Giá KHLCNT (Giá gói thầu)
    kh_price_str = "N/A"
    if kh_price:
        kh_price_str = format_vnd(kh_price)
        if kh_unit and "VND" not in kh_price_str:
            kh_price_str += f" {kh_unit}"
            
    desc = (
        f"### 🏷️ Từ khóa: {keyword_tag}\n---\n"
        f"- **Mã TBMT:** {bid_no}\n"
        f"- **Mã Plan:** {plan_no}\n"
        f"- **Bên mời thầu:** {item.get('investorName')}\n"
        f"- **Số tiền bảo đảm:** {guarantee_str}\n"
        f"- **Giá Dự Toán (KHLCNT):** {kh_price_str}\n"
        f"- **Đóng thầu:** {close_date_str}\n\n"
        f"[🔗 Xem chi tiết]({link})"
    )

    query = {
        'key': TRELLO_API_KEY,
        'token': TRELLO_TOKEN,
        'idList': TRELLO_LIST_ID,
        'name': f"[{bid_no}] {bid_name}",
        'desc': desc,
        'pos': 'top'
    }
    
    if close_date_str:
        dt = parse_date_flexible(close_date_str)
        if dt: query['due'] = dt.isoformat()

    try:
        r = requests.post(url_api, params=query)
        if r.status_code == 200:
            print(f"   ✅ Trello OK: [{bid_no}]")
            save_processed_id(bid_no)
            return True
        else:
            print(f"   ❌ Trello FAIL [{bid_no}] {r.status_code}")
    except Exception as e:
        print(f"   ❌ Trello Error: {e}")
    return False

# ==========================================
# 5. MAIN BOT LOOP
# ==========================================
def run_bot():
    processed_ids: set = load_processed_ids()
    discarded_ids: set = load_discarded_ids()
    HEADLESS_MODE = os.environ.get("HEADLESS_MODE", "True").lower() == "true"
    
    print("🚀 Starting Procurement Bot (Hybrid Strategy)...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS_MODE)
        
        # 2 Tabs: 1 for TBMT Search, 1 for Plan Lookup
        page = browser.new_page(user_agent=UA) 
        kh_page = browser.new_page(user_agent=UA)
        
        plan_cache = {} # Cache Plan Details to avoid re-fetching same plan
        
        try:
            page.set_default_timeout(60000)
            
            # --- LOOP KEYWORDS ---
            for keyword in KEYWORDS:
                print(f"\n🔎 Searching TBMT: '{keyword}'")
                
                # 1. Search TBMT
                page.goto("https://muasamcong.mpi.gov.vn/web/guest/contractor-selection?render=index", wait_until="domcontentloaded")
                try:
                    # Click tab "Thông báo mời thầu" (should be default but safe to click)
                    # page.locator("text='Thông báo mời thầu'").first.click(timeout=3000)
                    pass
                except:
                    pass
                    
                page.fill('input[name="keyword"]', keyword)
                # Define predicate to ensure we catch the actual JSON API, not other requests
                # Update: Check payload must contain keyword to avoid stale results
                def is_tbmt_api(r):
                    if not ("contractor-selection" in r.url and r.status == 200):
                        return False
                    
                    # Check Content-Type
                    ct = (r.headers or {}).get("content-type", "")
                    if "application/json" not in ct:
                        return False
                        
                    # Check Payload matches keyword
                    try:
                        post_data = r.request.post_data or ""
                        # Keyword might be encoded, but typically simple keywords appear as is or close to it.
                        # We check if the keyword is present in the request body.
                        if keyword not in post_data:
                            return False
                    except:
                        pass
                        
                    return True

                try:
                    with page.expect_response(is_tbmt_api, timeout=30000) as resp:
                        page.keyboard.press("Enter")
                    
                    # print(f"      📡 Captured API: {resp.value.url}")
                    data = resp.value.json()
                    # print(f"      📄 Data Keys: {list(data.keys())}")
                except Exception as e:
                    print(f"   ⚠️ Lỗi lấy dữ liệu API: {e}")
                    continue
                
                items = data.get('data') or data.get('page', {}).get('content') or []
                print(f"      📊 Items found: {len(items)}")
                
                if not items:
                    print("   No items found.")
                    continue
                    
                # 2. Process TBMT Items
                count_added = 0
                for item in items:
                    if count_added >= MAX_CARDS_PER_KEYWORD: break
                    
                    bid_no: str = safe_get_text(item.get('notifyNo') or item.get('bidNo')).strip()
                    bid_name: str = safe_get_text(item.get('bidName')).strip()
                    
                    # Check Expiry
                    close_date_str = item.get('bidCloseDate')
                    if close_date_str:
                        close_date = parse_date_flexible(close_date_str)
                        if close_date and close_date < datetime.now():
                            print(f"      ⚠️ Skip: Expired on {close_date_str}")
                            save_discarded_id(bid_no, "expired", discarded_ids)
                            continue
                    
                    # Strict Filter
                    if keyword.lower() not in bid_name.lower():
                        print(f"      ⚠️ Skip: Name '{bid_name}' does not contain '{keyword}'")
                        save_discarded_id(bid_no, "keyword mismatch", discarded_ids)
                        continue
                        
                    if bid_no in processed_ids:
                        print(f"      ⚠️ Skip: '{bid_no}' already processed.")
                        continue
                        
                    print(f"   📦 Processing: [{bid_no}] {bid_name[:20]}...")
                    
                    # 3. Lookup Price from Plan
                    plan_no = safe_get_text(item.get('planNo')).strip()
                    kh_price, kh_unit, guarantee_val = None, None, None
                    
                    if plan_no:
                        # Dùng page phụ (kh_page) để tra cứu Plan theo flow mới (TBMT Detail -> Plan ID)
                        # Cần truyền thêm item['id'] (TBMT ID)
                        tbmt_id = safe_get_text(item.get('id'))
                        kh_price, kh_unit, guarantee_val = get_khlcnt_price_from_plan(kh_page, plan_cache, plan_no, bid_no, tbmt_id)
                        if kh_price is not None:
                            print(f"      💰 Found Plan Price: {format_vnd(kh_price)}")
                        else:
                            print(f"      ⚠️ No Plan Price found.")
                    
                    # 4. Check Price Filter
                    normalized_price = kh_price
                    if kh_price is not None and kh_price > MAX_BID_PRICE:
                        print(f"      ⚠️ Skip: Price {format_vnd(kh_price)} exceeds MAX_BID_PRICE. Marking as processed.")
                        save_discarded_id(bid_no, "price too high", discarded_ids)
                        save_processed_id(bid_no)
                        processed_ids.add(bid_no)
                        continue

                    # 5. Create Card
                    if create_trello_card(item, keyword, kh_price, kh_unit, guarantee_val):
                        count_added += 1
                        processed_ids.add(bid_no)
                        
        finally:
            browser.close()

if __name__ == "__main__":
    run_bot()

