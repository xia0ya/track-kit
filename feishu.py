"""
飞书多维表格（Bitable）集成

配置说明：
- APP_ID / APP_SECRET：飞书应用凭证
- APP_TOKEN：多维表格 Base ID（从 URL 中的 /base/xxx 提取）
- TABLE_ID：表格 ID（从 URL 中的 ?table=xxx 提取）
- FIELD_MAP：字段映射（根据实际表格字段名调整）
"""

import asyncio
import httpx
from datetime import datetime
import json

APP_ID = "cli_a901606cbcb85bc2"
APP_SECRET = "IWryutyBvOOUHfRwnYQ3Af77yXRWQLT4"
APP_TOKEN = "AEbNbFWKWaQrZQs1E3HcEnsLnBh"  # Base ID
TABLE_ID = "tbl5hQNZV9V6QbWI"  # Table ID
VIEW_ID = "vew3sQj3iU"  # View ID

# 如果无法通过多维表格写入，可设置飞书群 webhook
WEBHOOK_URL = None  # e.g. "https://open.feishu.cn/open-apis/bot/v2/hook/xxx"

async def post_webhook(text):
    if not WEBHOOK_URL:
        return
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(WEBHOOK_URL, json={"msg_type": "text", "content": {"text": text}})

# 字段映射：飞书多维表格中的字段名
# 如果你的表格字段名就是键（例如 'order_id'），可以保持一致
FIELD_MAP = {
    "order_id": "order_id",
    "latest_status": "latest_status",
    "latest_time": "latest_time",
    "delivered": "delivered",
    "smart_summary": "smart_summary",
    "push_time": "push_time"
}


async def get_tenant_token():
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, json={"app_id": APP_ID, "app_secret": APP_SECRET})
        resp.raise_for_status()
        return resp.json().get("tenant_access_token")


async def get_sheet_info():
    """诊断：获取多维表格信息"""
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/fields"
    try:
        token = await get_tenant_token()
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            print("[Feishu] Table Fields:", json.dumps(data, indent=2, ensure_ascii=False))
            if "data" in data and "items" in data["data"]:
                fields = data["data"]["items"]
                print("\n[Feishu] 表格字段列表:")
                for field in fields:
                    print(f"  - {field.get('field_name')} (id: {field.get('field_id')}, type: {field.get('type')})")
            return data
    except Exception as e:
        print(f"[Feishu] Failed to get table info: {e}")
        print("[Feishu] 提示：请确保 APP_TOKEN 和 TABLE_ID 正确，且应用有该表格权限")


# cache field names to avoid repeated API calls
_field_name_cache = None
async def fetch_table_field_names():
    global _field_name_cache
    if _field_name_cache is not None:
        return _field_name_cache
    data = await get_sheet_info()
    names = []
    if data and "data" in data and "items" in data["data"]:
        for f in data["data"]["items"]:
            names.append(f.get("field_name"))
    _field_name_cache = set(names)
    return _field_name_cache


async def write_to_feishu(message):
    """
    将简短消息追加到飞书多维表格。支持传入字符串或一个字典。
    
    Args:
        message: 字符串（自动加时间戳）或 {"field_name": value, ...} 字段数据格式
    """
    # for single record we use /records endpoint with top-level fields key
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records"
    try:
        token = await get_tenant_token()
    except Exception as e:
        print(f"[Feishu] Failed to get token: {e}")
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # 支持传入字典（单条记录）或字符串（简短消息）
    if isinstance(message, str):
        fields = {FIELD_MAP.get("push_time", "push_time"): datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                  FIELD_MAP.get("latest_status", "latest_status"): message}
    else:
        fields = {}
        for key, value in message.items():
            field_name = FIELD_MAP.get(key, key)
            fields[field_name] = value

    field_names = await fetch_table_field_names()
    filtered = {k: v for k, v in fields.items() if k in field_names}
    if not filtered:
        print("[Feishu] No valid fields to write, skipping")
        return

    payload = {"fields": filtered}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 403:
                msg = "feishu record write forbidden (check app permissions)"
                print(f"[Feishu] {msg}")
                await post_webhook(msg)  # also notify via webhook if available
                return
            if resp.status_code not in [200, 201]:
                error_body = resp.text
                print(f"[Feishu] API Error {resp.status_code}: {error_body}")
                resp.raise_for_status()
            print(f"[Feishu] Successfully appended record")
    except Exception as e:
        print(f"[Feishu] Error appending to table: {e}")


def write_to_feishu_sync(message):
    """方便在同步上下文使用（可在线程中调用）。"""
    try:
        return asyncio.run(write_to_feishu(message))
    except Exception as e:
        print(f"[Feishu] Sync write failed: {e}")


async def write_batch_orders_to_feishu(results):
    """
    批量推送订单结果到飞书多维表格。
    
    Args:
        results: [{"order_id": "...", "latest_status": "...", "latest_time": "...", "delivered": "...", "smart_summary": "..."}, ...]
    """
    if not results:
        return
    
    print(f"[Feishu] Pushing {len(results)} orders to feishu...")
    # batch create uses special endpoint
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records/batch_create"
    
    try:
        token = await get_tenant_token()
    except Exception as e:
        print(f"[Feishu] Failed to get token: {e}")
        return
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # 转换为飞书多维表格记录格式
    records = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    for row in results:
        fields = {
            FIELD_MAP.get("order_id", "order_id"): row.get("order_id", ""),
            FIELD_MAP.get("latest_status", "latest_status"): row.get("latest_status", ""),
            FIELD_MAP.get("latest_time", "latest_time"): row.get("latest_time", ""),
            FIELD_MAP.get("delivered", "delivered"): row.get("delivered", ""),
            FIELD_MAP.get("smart_summary", "smart_summary"): row.get("smart_summary", ""),
            FIELD_MAP.get("push_time", "push_time"): now
        }
        records.append({"fields": fields})
    
    payload = {"records": records}
    
    try:
        print(f"[Feishu DEBUG] POST {url} payload={json.dumps(payload, ensure_ascii=False)}")
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 403:
                msg = "feishu batch write forbidden (check app permissions)"
                print(f"[Feishu] {msg}")
                await post_webhook(msg)
                return
            if resp.status_code not in [200, 201]:
                error_body = resp.text
                print(f"[Feishu] API Error {resp.status_code}: {error_body}")
                resp.raise_for_status()
            print(f"[Feishu] Successfully appended {len(records)} records")
    except Exception as e:
        print(f"[Feishu] Error appending batch records: {e}")