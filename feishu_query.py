#!/usr/bin/env python3
"""
飞书多维表格物流查询工具

功能：
1. 读取飞书表格中的"入库单号"列
2. 调用 tracker 查询物流状态
3. 将结果更新回飞书表格
"""

import requests
import time
import sys
import os

# 添加当前目录到路径，以便导入 tracker
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tracker

# ========== 飞书配置 ==========
APP_ID = "cli_a928eacb367cdcc4"
APP_SECRET = "Vyf0n0BxRwqgsYh2PmD6NcVhLwYmagKf"
APP_TOKEN = "YvLabDvpdaOpYHsW682cFZU4nlf"
TABLE_ID = "tblnsbG3mglNPoQr"

# 字段映射（根据实际表格字段名）
FIELD_ORDER_ID = "入库单号"  # 要查询的单号字段
FIELD_STATUS = "最新状态"    # 存放查询结果
FIELD_TIME = "最新时间"
FIELD_DELIVERED = "是否送到"
FIELD_SUMMARY = "物流摘要"
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


def query_order(order_id):
    """查询单个订单"""
    if not order_id or not str(order_id).strip():
        return None
    
    order_id = str(order_id).strip()
    print(f"  🔍 查询：{order_id}")
    
    result = tracker.process_single(order_id)
    
    if result.get("latest_status") == "查询失败":
        print(f"    ⚠️  查询失败")
    elif result.get("delivered") == "是":
        print(f"    ✅ 已签收：{result.get('latest_status')}")
    else:
        print(f"    📦 运输中：{result.get('latest_status')}")
    
    return result


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
        
        # 如果已有"最新状态"且"是否送到"是"已入库/已上架"或"是"，跳过
        existing_status = fields.get(FIELD_STATUS)
        existing_delivered = fields.get(FIELD_DELIVERED)
        
        # 如果已经查询过且有结果，跳过（可选）
        # if existing_status and existing_delivered in ["是", "已入库/已上架"]:
        #     continue
        
        if order_id:
            to_query.append({
                "record_id": rec.get("record_id"),
                "order_id": order_id,
                "existing_fields": fields
            })
    
    print(f"📦 需要查询 {len(to_query)} 条记录\n")
    
    # 批量查询并更新
    success_count = 0
    error_count = 0
    
    for i, item in enumerate(to_query, 1):
        print(f"[{i}/{len(to_query)}]", end="")
        
        result = query_order(item["order_id"])
        
        if result:
            # 准备更新的字段
            update_fields = {}
            
            # 映射查询结果到飞书字段
            if FIELD_STATUS:
                update_fields[FIELD_STATUS] = result.get("latest_status", "")
            if FIELD_TIME:
                update_fields[FIELD_TIME] = result.get("latest_time", "")
            if FIELD_DELIVERED:
                # 根据 delivered 字段映射到"是否送到"
                delivered = result.get("delivered", "否")
                existing_delivered = item["existing_fields"].get(FIELD_DELIVERED, "")
                
                # 如果已签收，更新为"已签收"，否则保持原样或设为"运输中"
                if delivered == "是":
                    update_fields[FIELD_DELIVERED] = "已签收"
                else:
                    update_fields[FIELD_DELIVERED] = "运输中"
            
            if FIELD_SUMMARY:
                update_fields[FIELD_SUMMARY] = result.get("smart_summary", "")
            
            # 更新飞书
            if update_record(token, item["record_id"], update_fields):
                success_count += 1
            else:
                error_count += 1
        
        # 限流，避免请求过快
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
