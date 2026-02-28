import requests
import pandas as pd
import json
import sys
import os

# 早上还不行，，中午吃过饭了又好了，真是玄学
# ========== 填写你的信息 ==========
APP_ID = "cli_a928eacb367cdcc4"
APP_SECRET = "Vyf0n0BxRwqgsYh2PmD6NcVhLwYmagKf"

APP_TOKEN = "YvLabDvpdaOpYHsW682cFZU4nlf"
TABLE_ID = "tblnsbG3mglNPoQr"

# 使用脚本所在目录作为基准路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EXCEL_PATH = os.path.join(SCRIPT_DIR, "input_updated.xlsx")
# ==================================

def get_tenant_access_token():
    """获取 tenant_access_token"""
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal/"
    
    payload = {
        "app_id": APP_ID,
        "app_secret": APP_SECRET
    }
    
    print(f"📡 请求 token... (APP_ID: {APP_ID})")
    response = requests.post(url, json=payload)
    
    print(f"📥 响应状态码：{response.status_code}")
    
    try:
        data = response.json()
    except Exception as e:
        print("❌ 返回数据不是 JSON：", response.text)
        print("❌ 错误:", e)
        sys.exit(1)
    
    if "tenant_access_token" not in data:
        print("❌ 获取 tenant_access_token 失败")
        print("返回内容:", data)
        sys.exit(1)
    
    print("✅ 获取 tenant_access_token 成功")
    return data["tenant_access_token"]


def read_excel():
    """读取 Excel"""
    print(f"📂 读取 Excel: {EXCEL_PATH}")
    try:
        df = pd.read_excel(EXCEL_PATH)
        print(f"✅ Excel 读取成功，共 {len(df)} 条数据")
        print(f"📋 列名：{df.columns.tolist()}")
        return df
    except Exception as e:
        print("❌ 读取 Excel 失败:", e)
        sys.exit(1)


def upload_to_feishu(df, tenant_access_token):
    """批量上传数据到飞书多维表格"""
    
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records/batch_create"
    
    headers = {
        "Authorization": f"Bearer {tenant_access_token}",
        "Content-Type": "application/json"
    }
    
    # 将 Excel 列名映射到飞书字段（需要确认字段 ID）
    # 如果 Excel 列名和飞书字段名一致，可以直接用
    # 如果不一致，需要手动映射，例如：{'order_id': 'fldxxx1', 'latest_status': 'fldxxx2'}
    
    records = []
    for _, row in df.iterrows():
        fields = {}
        for col in df.columns:
            value = row[col]
            # 处理空值
            if pd.isna(value):
                value = None
            # 处理布尔值（飞书用 1/0 或 true/false）
            elif isinstance(value, (bool,)):
                value = 1 if value else 0
            fields[col] = value
        
        records.append({
            "fields": fields
        })
    
    total = len(records)
    batch_size = 500  # 飞书限制每次最多 500 条
    
    print("🚀 开始上传数据...")
    print(f"📦 总计 {total} 条，分 {(total + batch_size - 1) // batch_size} 批上传")
    
    success_count = 0
    for i in range(0, total, batch_size):
        batch = records[i:i + batch_size]
        
        data = {
            "records": batch
        }
        
        response = requests.post(url, headers=headers, json=data)
        
        try:
            result = response.json()
        except Exception as e:
            print(f"❌ 上传返回异常：{response.text}")
            print(f"❌ 错误：{e}")
            continue
        
        if result.get("code") != 0:
            print(f"❌ 上传失败 (批次 {i//batch_size + 1}):")
            print(f"   错误码：{result.get('code')}")
            print(f"   错误信息：{result.get('msg')}")
            print(f"   详情：{result}")
            continue
        
        success_count += len(batch)
        print(f"✅ 成功上传 {success_count} / {total}")
    
    print(f"🎉 上传完成！成功：{success_count} / {total}")


def main():
    print("=" * 50)
    print("🚀 飞书多维表格数据上传工具")
    print("=" * 50)
    
    token = get_tenant_access_token()
    df = read_excel()
    upload_to_feishu(df, token)


if __name__ == "__main__":
    main()
