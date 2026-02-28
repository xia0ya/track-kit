#!/usr/bin/env python3
"""
飞书多维表格物流查询工具

用法:
    python3 feishu_query_v2.py           # 只查询未签收的记录
    python3 feishu_query_v2.py --force   # 查询所有记录
    python3 feishu_query_v2.py --limit 5 # 只查询前 5 条
"""

import requests
import time
import sys
import argparse
from bs4 import BeautifulSoup
from datetime import datetime

# ========== 飞书配置 ==========
APP_ID = "cli_a928eacb367cdcc4"
APP_SECRET = "Vyf0n0BxRwqgsYh2PmD6NcVhLwYmagKf"
APP_TOKEN = "YvLabDvpdaOpYHsW682cFZU4nlf"
TABLE_ID = "tblnsbG3mglNPoQr"

# 字段映射（根据实际表格字段）
FIELD_ORDER_ID = "入库单号"
FIELD_STATUS = "最新状态"      # 需要先在飞书表格中创建这些字段
FIELD_TIME = "最新时间"
FIELD_DELIVERED = "是否送到"
FIELD_SUMMARY = "物流摘要"      # 如果字段不存在，更新会失败

# 备用字段名（如果上面的是错的）
# FIELD_STATUS = "最新状态"
# FIELD_TIME = "查询时间"
# FIELD_SUMMARY = "摘要"

# 物流查询配置
TRACK_URL = "https://www.yhwl.com/index.php?s=zhimatongapi&c=home&m=index"
TRACK_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.yhwl.com/list-ddcx.html",
    "Origin": "https://www.yhwl.com",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
}
DELIVER_KEYS = ["DELIVERED", "送达", "签收", "已签收", "运单签收"]
REQUEST_TIMEOUT = 10
# ============================


def get_tenant_access_token():
    """获取 tenant_access_token"""
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal/"
    resp = requests.post(url, json={"app_id": APP_ID, "app_secret": APP_SECRET}, timeout=10)
    data = resp.json()
    if "tenant_access_token" not in data:
        raise Exception(f"获取 token 失败：{data}")
    return data["tenant_access_token"]


def get_table_records(token, limit=None):
    """获取表格记录"""
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records"
    headers = {"Authorization": f"Bearer {token}"}
    
    all_records = []
    page_token = None
    page_size = 100
    
    while True:
        params = {"page_size": page_size}
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
    """批量更新记录"""
    if not updates:
        return True
    
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records/batch_update"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    records = [{"record_id": rid, "fields": fields} for rid, fields in updates]
    data = {"records": records}
    
    resp = requests.post(url, headers=headers, json=data, timeout=30)
    result = resp.json()
    
    if result.get("code") != 0:
        print(f"❌ 批量更新失败：{result}")
        return False
    
    success = result.get("data", {}).get("total", 0)
    print(f"✅ 批量更新成功：{success}/{len(records)}")
    return True


def query_tracking(order_id, retry=2):
    """查询物流轨迹"""
    session = requests.Session()
    for attempt in range(retry):
        try:
            response = session.post(
                TRACK_URL,
                data={"id": order_id},
                headers=TRACK_HEADERS,
                timeout=REQUEST_TIMEOUT
            )
            if response.status_code == 200:
                return response.json()
        except requests.Timeout:
            print(f"⏱️  超时 ({attempt+1}/{retry})")
        except Exception as e:
            print(f"❌ 错误：{e}")
        time.sleep(0.5)
    return None


def parse_tracking(html):
    """解析轨迹 HTML"""
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
    except Exception as e:
        return []


def extract_logistics_summary(tracking_list):
    """提取三节点摘要"""
    order_date = None
    yiwu_date = None
    delivered_date = None
    
    for row in reversed(tracking_list):
        status = row["status"]
        date = row["time"][:10]
        try:
            dt = datetime.strptime(date, "%Y-%m-%d")
            short_date = f"{dt.month}.{dt.day}"
        except:
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


def process_single(order_id):
    """处理单个订单"""
    result = query_tracking(order_id)
    
    if not result or result.get("code") != 1:
        return {
            "latest_status": "查询失败",
            "latest_time": "",
            "delivered": False,
            "smart_summary": ""
        }
    
    tracking_list = parse_tracking(result["data"])
    
    if not tracking_list:
        return {
            "latest_status": "无数据",
            "latest_time": "",
            "delivered": False,
            "smart_summary": ""
        }
    
    latest = tracking_list[0]
    delivered = any(any(k in row["status"] for k in DELIVER_KEYS) for row in tracking_list)
    smart_summary = extract_logistics_summary(tracking_list)
    
    return {
        "latest_status": latest["status"],
        "latest_time": latest["time"],
        "delivered": delivered,
        "smart_summary": smart_summary
    }


def main():
    parser = argparse.ArgumentParser(description="飞书多维表格物流查询工具")
    parser.add_argument("--force", action="store_true", help="强制查询所有记录（包括已签收）")
    parser.add_argument("--limit", type=int, help="限制查询记录数")
    parser.add_argument("--no-update", action="store_true", help="只查询不更新")
    args = parser.parse_args()
    
    print("=" * 60)
    print("🚀 飞书多维表格物流查询工具")
    print("=" * 60)
    
    try:
        # 获取 token
        print("\n📡 获取访问令牌...")
        token = get_tenant_access_token()
        print("✅ Token 获取成功")
        
        # 获取表格记录
        print("\n📊 读取表格数据...")
        start_time = time.time()
        records = get_table_records(token, limit=args.limit)
        elapsed = time.time() - start_time
        print(f"✅ 获取到 {len(records)} 条记录 (耗时：{elapsed:.2f}s)")
        
        # 筛选需要查询的记录
        to_query = []
        skipped = 0
        
        for rec in records:
            fields = rec.get("fields", {})
            order_id = fields.get(FIELD_ORDER_ID)
            delivered_status = fields.get(FIELD_DELIVERED, "")
            
            # 跳过空单号
            if not order_id or not str(order_id).strip():
                continue
            
            # 跳过已签收（除非 --force）
            if not args.force and delivered_status in ["已签收", "是"]:
                skipped += 1
                continue
            
            to_query.append({
                "record_id": rec.get("record_id"),
                "order_id": str(order_id).strip(),
            })
        
        print(f"📦 待查询：{len(to_query)} 条 (已跳过：{skipped})\n")
        
        if not to_query:
            print("✅ 没有需要查询的记录")
            return
        
        # 查询并收集更新
        updates = []
        success_count = 0
        error_count = 0
        
        for i, item in enumerate(to_query, 1):
            print(f"[{i}/{len(to_query)}] {item['order_id']}", end=" ... ")
            sys.stdout.flush()
            
            result = process_single(item["order_id"])
            
            if result["latest_status"] == "查询失败":
                print("❌ 查询失败")
                error_count += 1
            else:
                status_text = "✅" if result["delivered"] else "📦"
                status_summary = result['latest_status'][:40]
                print(f"{status_text} {status_summary}")
                
                updates.append((item["record_id"], {
                    FIELD_STATUS: result["latest_status"],
                    FIELD_TIME: result["latest_time"],
                    FIELD_DELIVERED: "已签收" if result["delivered"] else "运输中",
                    FIELD_SUMMARY: result["smart_summary"]
                }))
                success_count += 1
            
            # 限流
            time.sleep(0.3)
        
        # 批量更新
        if updates and not args.no_update:
            print(f"\n📤 批量更新飞书表格...")
            update_records_batch(token, updates)
        elif updates and args.no_update:
            print(f"\n⚠️  跳过更新 (--no-update)")
        
        print("\n" + "=" * 60)
        print(f"🎉 完成！")
        print(f"   成功：{success_count} | 失败：{error_count}")
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
