import requests

tenant_access_token = "t-g1042qggQ55DTFCYWASG2IZHGOXNM3WTU4CHZ4EU"
spreadsheet_token = "AZQEsPicbhZIgwt89SkcGnA3nxe"
sheet_id = "Sheet1"

url = f"https://open.feishu.cn/open-apis/sheets/v3/spreadsheets/{spreadsheet_token}/values"

headers = {
    "Authorization": f"Bearer {tenant_access_token}",
    "Content-Type": "application/json"
}

body = {
    "valueRange": {
        "range": f"{sheet_id}!A201:C201",
        "majorDimension": "ROWS",
        "values": [
            ["v3写入测试", "PUT方式", "成功"]
        ]
    }
}

resp = requests.put(url, headers=headers, json=body)

print("状态码:", resp.status_code)
print("返回:", resp.text)