#!/usr/bin/env python3
"""
飞书多维表格物流查询工具（独立版）

功能：
1. 读取飞书表格中的"入库单号"列
2. 查询物流状态
3. 将结果更新回飞书表格
"""

import requests
import time
import sys
import os
from bs4 import BeautifulSoup
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# ========== 飞书配置 ==========
APP_ID = "cli_a928eacb367cdcc4"
APP_SECRET = "Vyf0n0BxRwqgsYh2PmD6NcVhLwYmagKf"
APP_TOKEN = "YvLabDvpdaOpYHsW682cFZU4nlf"
TABLE_ID = "tblnsbG3mglNPoQr"

# 字段映射（根据实际表格字段名）
FIELD_ORDER_ID = "入库单号"
FIELD_STATUS = "最新状态"
FIELD_TIME = "最新时间"
FIELD_DELIVERED = "是否送到"
FIELD_SUMMARY = "物流摘要"

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
# ============================


def get_tenant_access_token():
    """获取 tenant_access_token"""
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal/"
    resp = requests.post(url, json={"app_id": APP_ID, "app_secret": APP_SECRET})
    data = resp.json()
    if "tenant_access_token" not in data:
        print("❌ 获取 token 失败:", data)
        sys.exit(1)
    return data["tenant_access_token"]


def get_table_records(token, page_size=100):
    """获取表格所有记录"""
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records"
    headers = {"Authorization": f"Bearer {token}"}
    
    all_records = []
    page_token = None
    
    while True:
        params = {"page_size": page_size}
        if page_token:
            params["page_token"] = page_token
        
        resp = requests.get(url, headers=headers, params=params)
        result = resp.json()
        
        if result.get("code") != 0:
            print("❌ 获取记录失败:", result)
            break
        
        records = result.get("data", {}).get("items", [])
        all_records.extend(records)
        
        page_token = result.get("data", {}).get("page_token")
        if not page_token or not result.get("data", {}).get("has_more"):
            break
    
    print(f"✅ 获取到 {len(all_records)} 条记录")
    return all_records


def update_record(token, record_id, fields):
    """更新单条记录"""
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records/{record_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    data = {"fields": fields}
    
    resp = requests.put(url, headers=headers, json=data)
    result = resp.json()
    
    if result.get("code") != 0:
        print(f"❌ 更新记录 {record_id} 失败:", result)
        return False
    return True


def query_tracking(order_id, retry=2):
    """查询物流轨迹"""
    session = requests.Session()
    for _ in range(retry):
        try:
            response = session.post(
                TRACK_URL,
                data={"id": order_id},
                headers=TRACK_HEADERS,
                timeout=15
            )
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"      重试中... ({_+1}/{retry})")
            time.sleep(0.5)
    return None


def parse_tracking(html):
    """解析轨迹 HTML"""
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
        if not delivered_date and any(k in status for k in ["DELIVERED", "送达", "签收", "已签收", "运单签收"]):
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
            "order_id": order_id,
            "latest_status": "查询失败",
            "latest_time": "",
            "delivered": "否",
            "smart_summary": ""
        }
    
    tracking_list = parse_tracking(result["data"])
    
    if not tracking_list:
        return {
            "order_id": order_id,
            "latest_status": "无数据",
            "latest_time": "",
            "delivered": "否",
            "smart_summary": ""
        }
    
    latest = tracking_list[0]
    delivered = any(any(k in row["status"] for k in DELIVER_KEYS) for row in tracking_list)
    smart_summary = extract_logistics_summary(tracking_list)
    
    return {
        "order_id": order_id,
        "latest_status": latest["status"],
        "latest_time": latest["time"],
        "delivered": "是" if delivered else "否",
        "smart_summary": smart_summary
    }


def main():
    print("=" * 60)
    print("🚀 飞书多维表格物流查询工具")
    print("=" * 60)
    
    # 获取 token
    print("\n📡 获取访问令牌...")
    token = get_tenant_access_token()
    print("✅ Token 获取成功")
    
    # 获取表格记录
    print("\n📊 读取表格数据...")
    records = get_table_records(token)
    
    if not records:
        print("❌ 没有记录可处理")
        return
    
    # 筛选需要查询的记录
    to_query = []
    for rec in records:
        fields = rec.get("fields", {})
        order_id = fields.get(FIELD_ORDER_ID)
        
        if order_id and str(order_id).strip():
            to_query.append({
                "record_id": rec.get("record_id"),
                "order_id": str(order_id).strip(),
                "existing_fields": fields
            })
    
    print(f"📦 找到 {len(to_query)} 条待查询记录\n")
    
    if not to_query:
        print("⚠️  没有需要查询的入库单号")
        return
    
    # 批量查询并更新
    success_count = 0
    error_count = 0
    skip_count = 0
    
    for i, item in enumerate(to_query, 1):
        print(f"[{i}/{len(to_query)}] 查询：{item['order_id']}")
        
        result = process_single(item["order_id"])
        
        if result.get("latest_status") == "查询失败":
            print(f"    ⚠️  查询失败")
            error_count += 1
        else:
            # 准备更新的字段
            update_fields = {}
            
            if FIELD_STATUS:
                update_fields[FIELD_STATUS] = result.get("latest_status", "")
            if FIELD_TIME:
                update_fields[FIELD_TIME] = result.get("latest_time", "")
            if FIELD_DELIVERED:
                update_fields[FIELD_DELIVERED] = "已签收" if result.get("delivered") == "是" else "运输中"
            if FIELD_SUMMARY:
                update_fields[FIELD_SUMMARY] = result.get("smart_summary", "")
            
            # 更新飞书
            if update_record(token, item["record_id"], update_fields):
                success_count += 1
                if result.get("delivered") == "是":
                    print(f"    ✅ 已签收：{result.get('latest_status')}")
                else:
                    print(f"    📦 运输中：{result.get('latest_status')}")
            else:
                error_count += 1
        
        # 限流
        time.sleep(0.5)
    
    print("\n" + "=" * 60)
    print(f"🎉 查询完成！")
    print(f"   成功：{success_count}")
    print(f"   失败：{error_count}")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ 程序异常：{e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
