#!/usr/bin/env python3
"""
飞书多维表格物流查询工具（双接口并发版）

用法:
    python3 feishu_query_v4.py                    # 只查询未签收的记录
    python3 feishu_query_v4.py --force            # 查询所有记录
    python3 feishu_query_v4.py --limit 5          # 只查询前 5 条
    python3 feishu_query_v4.py --workers 20       # 设置并发线程数（默认 10）
    python3 feishu_query_v4.py --source auto      # 自动选择（默认，先 yhwl 失败后 html）
    python3 feishu_query_v4.py --source yhwl      # 只用 yhwl 接口
    python3 feishu_query_v4.py --source html      # 只用 html 解析接口
"""

import requests
import time
import sys
import argparse
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup
from datetime import datetime

# ========== 飞书配置 ==========
APP_ID = "cli_a928eacb367cdcc4"
APP_SECRET = "Vyf0n0BxRwqgsYh2PmD6NcVhLwYmagKf"
APP_TOKEN = "YvLabDvpdaOpYHsW682cFZU4nlf"
TABLE_ID = "tblnsbG3mglNPoQr"

FIELD_ORDER_ID = "入库单号"
FIELD_STATUS = "最新状态"
FIELD_TIME = "最新时间"
FIELD_DELIVERED = "是否送到"
FIELD_SUMMARY = "物流摘要"

# ========== 物流查询配置 - 接口 1 (yhwl) ==========
TRACK_URL_YHWL = "https://www.yhwl.com/index.php?s=zhimatongapi&c=home&m=index"
TRACK_HEADERS_YHWL = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.yhwl.com/list-ddcx.html",
    "Origin": "https://www.yhwl.com",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
}

# ========== 物流查询配置 - 接口 2 (HTML 解析) ==========
TRACK_URL_HTML = "http://124.222.204.239:8082/trackIndex.htm"
TRACK_HEADERS_HTML = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Referer": TRACK_URL_HTML,
}

DELIVER_KEYS = ["DELIVERED", "送达", "签收", "已签收", "运单签收"]
REQUEST_TIMEOUT = 10

# 线程安全打印锁
_print_lock = threading.Lock()
# 进度计数器
_counter = {"done": 0, "total": 0}

# ============================
# 线程安全的打印函数
# ============================

def safe_print(*args, **kwargs):
    with _print_lock:
        print(*args, **kwargs)
        sys.stdout.flush()

# ============================
# 飞书 API 函数
# ============================

def get_tenant_access_token():
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal/"
    resp = requests.post(url, json={"app_id": APP_ID, "app_secret": APP_SECRET}, timeout=10)
    data = resp.json()
    if "tenant_access_token" not in data:
        raise Exception(f"获取 token 失败：{data}")
    return data["tenant_access_token"]

def get_table_records(token, limit=None):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records"
    headers = {"Authorization": f"Bearer {token}"}
    all_records = []
    page_token = None

    while True:
        params = {"page_size": 100}
        if page_token:
            params["page_token"] = page_token

        resp = requests.get(url, headers=headers, params=params, timeout=15)
        result = resp.json()

        if result.get("code") != 0:
            raise Exception(f"获取记录失败：{result}")

        records = result.get("data", {}).get("items", [])
        all_records.extend(records)

        if limit and len(all_records) >= limit:
            return all_records[:limit]

        page_token = result.get("data", {}).get("page_token")
        if not page_token or not result.get("data", {}).get("has_more"):
            break

    return all_records

def update_records_batch(token, updates):
    if not updates:
        return True

    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records/batch_update"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    records = [{"record_id": rid, "fields": fields} for rid, fields in updates]

    CHUNK = 500
    total_success = 0
    for i in range(0, len(records), CHUNK):
        chunk = records[i:i + CHUNK]
        resp = requests.post(url, headers=headers, json={"records": chunk}, timeout=30)
        result = resp.json()
        if result.get("code") != 0:
            print(f"❌ 批量更新失败：{result}")
            return False
        total_success += result.get("data", {}).get("total", 0)

    print(f"✅ 批量更新成功：{total_success}/{len(records)}")
    return True

# ============================
# 物流查询 - 接口 1 (yhwl API)
# ============================

def query_tracking_yhwl(order_id, retry=2):
    """yhwl 接口查询"""
    session = requests.Session()
    for attempt in range(retry):
        try:
            response = session.post(
                TRACK_URL_YHWL,
                data={"id": order_id},
                headers=TRACK_HEADERS_YHWL,
                timeout=REQUEST_TIMEOUT
            )
            if response.status_code == 200:
                return response.json()
        except requests.Timeout:
            pass
        except Exception:
            pass
        time.sleep(1)
    return None

def parse_tracking_yhwl(html):
    """解析 yhwl 返回的物流轨迹"""
    try:
        soup = BeautifulSoup(html, "html.parser")
        items = soup.select("ul.timetree li")
        results = []
        for item in items:
            divs = item.find_all("div")
            if len(divs) >= 2:
                time_str = divs[0].text.replace("操作时间：", "").strip()
                status = divs[1].text.strip()
                results.append({"time": time_str, "status": status})
        return results
    except Exception:
        return []

def extract_logistics_summary_yhwl(tracking_list):
    """提取物流摘要（订单日期 - 义乌入库 - 送达）"""
    order_date = yiwu_date = delivered_date = None
    for row in reversed(tracking_list):
        status = row["status"]
        date = row["time"][:10] if row["time"] else ""
        try:
            dt = datetime.strptime(date, "%Y-%m-%d")
            short_date = f"{dt.month}.{dt.day}"
        except Exception:
            continue
        if not order_date and any(k in status for k in ["创建运单", "运单已确认", "Shipper created"]):
            order_date = short_date
        if not yiwu_date and any(k in status for k in ["扫描入库", "过机扫描入库", "入仓"]):
            yiwu_date = short_date
        if not delivered_date and any(k in status for k in DELIVER_KEYS):
            delivered_date = short_date

    parts = []
    if order_date:
        parts.append(f"{order_date}下单")
    if yiwu_date:
        parts.append(f"{yiwu_date}义乌入库")
    if delivered_date:
        parts.append(f"{delivered_date}送达")
    return "-".join(parts)

# ============================
# 物流查询 - 接口 2 (HTML 解析)
# ============================

def query_tracking_html(ordesr_id, retry=3):
    """HTML 接口查询；如果解析不到轨迹，s会自动重试几次，缓解反爬/偶发空页"""
    session = requests.Session()
    for attempt in range(retry):
        try:
            # 先 GET 一次页面，模拟正常浏览器访问
            session.get(TRACK_URL_HTML, timeout=10)
            response = session.post(
                TRACK_URL_HTML,
                data={"documentCode": order_id},
                headers=TRACK_HEADERS_HTML,
                timeout=REQUEST_TIMEOUT
            )
            if response.status_code == 200:
                response.encoding = response.apparent_encoding or "utf-8"
                parsed = parse_tracking_html(response.text)
                safe_print(f"  [HTML DEBUG] {order_id} 尝试{attempt+1}/{retry}: 解析到{len(parsed)}条记录")
                # 真正拿到轨迹再返回；空结果视为失败，继续重试
                if parsed:
                    return response.text
        except Exception as e:
            safe_print(f"  [HTML ERROR] {order_id} 尝试{attempt+1}/{retry}: {e}")
        # 简单退避，避免请求过于密集
        time.sleep(0.8 * (attempt + 1))
    return None


def parse_tracking_html(html: str):
    """解析 HTML 物流追踪页面，返回统一格式：[{time, status}, ...]"""
    results = []
    try:
        soup = BeautifulSoup(html, "html.parser")

        # 优先从详细轨迹区域 div.difmeam 中的 table 提取
        dif = soup.find("div", class_="difmeam")
        if dif:
            table = dif.find("table")
        else:
            table = None
            # 兜底：页面中所有 table 里，找出包含 3 列 td 的行，视为轨迹表
            for t in soup.find_all("table"):
                if any(len(tr.find_all("td")) == 3 for tr in t.find_all("tr")):
                    table = t
                    break

        if not table:
            return results

        for tr in table.find_all("tr"):
            cells = tr.find_all("td")
            if len(cells) != 3:
                continue
            date = cells[0].get_text(strip=True)
            loc = cells[1].get_text(strip=True)
            detail = cells[2].get_text(strip=True)
            if not date or not detail:
                continue

            status = f"{loc} {detail}" if loc else detail
            results.append({"time": date, "status": status})
    except Exception:
        pass

    return results


def extract_logistics_summary_html(tracking_list):
    """提取物流摘要（HTML 接口）"""
    order_date = yiwu_date = delivered_date = None
    for row in reversed(tracking_list):
        status = row["status"]
        date = row["time"][:10] if row["time"] else ""
        try:
            dt = datetime.strptime(date, "%Y-%m-%d")
            short_date = f"{dt.month}.{dt.day}"
        except Exception:
            continue
        if not order_date and any(k in status for k in ["创建运单", "运单已确认", "Shipper created", "创建标签"]):
            order_date = short_date
        if not yiwu_date and any(k in status for k in ["扫描入库", "过机扫描入库", "入仓", "温州", "收货点"]):
            yiwu_date = short_date
        if not delivered_date and any(k in status for k in DELIVER_KEYS):
            delivered_date = short_date

    parts = []
    if order_date:
        parts.append(f"{order_date}下单")
    if yiwu_date:
        parts.append(f"{yiwu_date}义乌入库")
    if delivered_date:
        parts.append(f"{delivered_date}送达")
    return "-".join(parts)

# ============================
# 处理单个订单（线程工作函数）
# ============================

def process_single(item, source="auto"):
    """处理单个订单（线程工作函数）"""
    order_id = item["order_id"]
    
    with _print_lock:
        _counter["done"] += 1
        idx = _counter["done"]
        total = _counter["total"]
    
    # 根据 source 选择查询方式
    tracking_list = None
    source_used = source
    
    if source == "yhwl":
        raw = query_tracking_yhwl(order_id)
        if raw and raw.get("code") == 1:
            tracking_list = parse_tracking_yhwl(raw.get("data", ""))
    elif source == "html":
        html = query_tracking_html(order_id)
        if html:
            tracking_list = parse_tracking_html(html)
    else:  # auto - 先试 yhwl，失败后试 html（包括 yhwl 返回空轨迹时）
        raw = query_tracking_yhwl(order_id)
        if raw and raw.get("code") == 1:
            tracking_list = parse_tracking_yhwl(raw.get("data", ""))
            source_used = "yhwl"
            # 如果 yhwl 返回的内容解析不到任何轨迹，则自动降级到 HTML 接口
            if not tracking_list:
                html = query_tracking_html(order_id)
                if html:
                    tracking_list = parse_tracking_html(html)
                    source_used = "html"
        else:
            html = query_tracking_html(order_id)
            if html:
                tracking_list = parse_tracking_html(html)
                source_used = "html"
    
    if not tracking_list:
        safe_print(f"[{idx}/{total}] {order_id} ... ❌ 查询失败")
        return item["record_id"], None

    latest = tracking_list[0]
    delivered = any(any(k in row["status"] for k in DELIVER_KEYS) for row in tracking_list)
    smart_summary = extract_logistics_summary_yhwl(tracking_list) if source_used == "yhwl" else extract_logistics_summary_html(tracking_list)

    icon = "✅" if delivered else "📦"
    safe_print(f"[{idx}/{total}] {order_id} ... {icon} {latest['status'][:40]}")

    return item["record_id"], {
        FIELD_STATUS: latest["status"],
        FIELD_TIME: latest["time"],
        FIELD_DELIVERED: "已签收" if delivered else "运输中",
        FIELD_SUMMARY: smart_summary
    }

# ============================
# 主函数
# ============================

def main():
    parser = argparse.ArgumentParser(description="飞书多维表格物流查询工具（双接口并发版）")
    parser.add_argument("--force", action="store_true", help="强制查询所有记录（包括已签收）")
    parser.add_argument("--limit", type=int, help="限制查询记录数")
    parser.add_argument("--no-update", action="store_true", help="只查询不更新")
    parser.add_argument("--workers", type=int, default=10, help="并发线程数（默认 10）")
    parser.add_argument("--source", type=str, default="auto", choices=["auto", "yhwl", "html"], 
                        help="查询接口选择：auto=自动，yhwl=只用 yhwl，html=只用 HTML 解析")
    args = parser.parse_args()

    print("=" * 60)
    print("🚀 飞书多维表格物流查询工具（双接口并发版）")
    print(f"📡 接口模式：{args.source}")
    print("=" * 60)

    try:
        print("\n📡 获取访问令牌...")
        token = get_tenant_access_token()
        print("✅ Token 获取成功")

        print("\n📊 读取表格数据...")
        t0 = time.time()
        records = get_table_records(token, limit=args.limit)
        print(f"✅ 获取到 {len(records)} 条记录 (耗时：{time.time()-t0:.2f}s)")

        # 筛选待查询记录
        to_query = []
        skipped = 0
        for rec in records:
            fields = rec.get("fields", {})
            order_id = fields.get(FIELD_ORDER_ID)
            if not order_id or not str(order_id).strip():
                continue
            if not args.force and fields.get(FIELD_DELIVERED, "") in ["已签收", "是"]:
                skipped += 1
                continue
            to_query.append({"record_id": rec["record_id"], "order_id": str(order_id).strip()})

        print(f"📦 待查询：{len(to_query)} 条 (已跳过：{skipped})")

        if not to_query:
            print("✅ 没有需要查询的记录")
            return

        # 初始化进度计数
        _counter["done"] = 0
        _counter["total"] = len(to_query)

        # 并发查询
        workers = min(args.workers, len(to_query))
        print(f"\n⚡ 启动并发查询（{workers} 线程）...\n")
        t1 = time.time()

        updates = []
        success_count = error_count = 0

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(process_single, item, args.source): item for item in to_query}
            for future in as_completed(futures):
                record_id, fields = future.result()
                if fields:
                    updates.append((record_id, fields))
                    success_count += 1
                else:
                    error_count += 1

        elapsed = time.time() - t1
        qps = len(to_query) / elapsed if elapsed > 0 else 0
        print(f"\n⏱️  查询耗时：{elapsed:.1f}s（{qps:.1f} 单/秒）")

        # 批量更新飞书
        if updates and not args.no_update:
            print(f"\n📤 批量更新飞书表格（{len(updates)} 条）...")
            update_records_batch(token, updates)
        elif updates and args.no_update:
            print(f"\n⚠️  跳过更新 (--no-update)")

        print("\n" + "=" * 60)
        print(f"🎉 完成！  成功：{success_count} | 失败：{error_count}")
        print("=" * 60)

    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ 程序异常：{e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()