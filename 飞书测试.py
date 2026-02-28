import requests
import pandas as pd
import json

# ========== 填写你的信息 ==========
APP_ID = "cli_a928eacb367cdcc4"
APP_SECRET = "Vyf0n0BxRwqgsYh2PmD6NcVhLwYmagKf"

APP_TOKEN = "YvLabDvpdaOpYHsW682cFZU4nlf"
TABLE_ID = "tblnsbG3mglNPoQr"

EXCEL_PATH = "input_updated.xlsx"
# ==================================



def get_tenant_access_token():
    """获取 tenant_access_token"""
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal/"

    payload = {
        "app_id": APP_ID,
        "app_secret": APP_SECRET
    }

    response = requests.post(url, json=payload)

    try:
        data = response.json()
    except:
        print("❌ 返回数据不是JSON：", response.text)
        sys.exit()

    if "tenant_access_token" not in data:
        print("❌ 获取 tenant_access_token 失败")
        print("状态码:", response.status_code)
        print("返回内容:", data)
        sys.exit()

    print("✅ 获取 tenant_access_token 成功")
    return data["tenant_access_token"]


def read_excel():
    """读取Excel"""
    try:
        df = pd.read_excel(EXCEL_PATH)
        print(f"✅ Excel读取成功，共 {len(df)} 条数据")
        return df
    except Exception as e:
        print("❌ 读取Excel失败:", e)
        sys.exit()


def upload_to_feishu(df, tenant_access_token):
    """批量上传数据到飞书多维表格"""

    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records/batch_create"

    headers = {
        "Authorization": f"Bearer {tenant_access_token}",
        "Content-Type": "application/json"
    }

    records = []
    for _, row in df.iterrows():
        records.append({
            "fields": row.to_dict()
        })

    total = len(records)
    batch_size = 500

    print("🚀 开始上传数据...")

    for i in range(0, total, batch_size):
        batch = records[i:i + batch_size]

        data = {
            "records": batch
        }

        response = requests.post(url, headers=headers, json=data)

        try:
            result = response.json()
        except:
            print("❌ 上传返回异常:", response.text)
            continue

        if result.get("code") != 0:
            print("❌ 上传失败:")
            print(result)
            continue

        print(f"✅ 成功上传 {i + len(batch)} / {total}")

    print("🎉 所有数据上传完成")


def main():
    token = get_tenant_access_token()
    df = read_excel()
    upload_to_feishu(df, token)


if __name__ == "__main__":
    main()