import requests
import pandas as pd
import time
import re
from bs4 import BeautifulSoup
from datetime import datetime

URL = "https://www.yhwl.com/index.php?s=zhimatongapi&c=home&m=index"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.yhwl.com/list-ddcx.html",
    "Origin": "https://www.yhwl.com",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
}

session = requests.Session()

# ===============================
# 可选输出字段（默认关闭）
# ===============================
EXPORT_FULL_TRACK = False
EXPORT_SUMMARY_ROUTE = False
EXPORT_TOTAL_DAYS = False
EXPORT_TRACK_COUNT = False


# ===============================
# 查询接口
# ===============================
def query_tracking(order_id, retry=3):
    for _ in range(retry):
        try:
            response = session.post(
                URL,
                data={"id": order_id},
                headers=HEADERS,
                timeout=15
            )
            if response.status_code == 200:
                return response.json()
        except:
            time.sleep(2)
    return None


# ===============================
# 解析轨迹
# ===============================
def parse_tracking(html):
    soup = BeautifulSoup(html, "html.parser")
    items = soup.select("ul.timetree li")

    results = []

    for item in items:
        divs = item.find_all("div")
        if len(divs) >= 2:
            time_str = divs[0].text.replace("操作时间：", "").strip()
            status = divs[1].text.strip()

            results.append({
                "time": time_str,
                "status": status
            })

    return results


# ===============================
# 日期格式
# ===============================
def format_md(date_str):
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
        return f"{dt.month}.{dt.day}"
    except:
        return ""


# ===============================
# 精简节点（只保留下单-义乌入库-送达）
# ===============================
def extract_logistics_summary(tracking_list):

    order_date = None
    yiwu_date = None
    delivered_date = None

    # 轨迹是倒序的，所以反过来找最早
    for row in reversed(tracking_list):

        status = row["status"]
        date = row["time"][:10]

        dt = datetime.strptime(date, "%Y-%m-%d")
        short_date = f"{dt.month}.{dt.day}"

        # 下单
        if not order_date and any(k in status for k in [
            "创建运单", "运单已确认", "Shipper created"
        ]):
            order_date = short_date

        # 义乌入库（必须是扫描入库类）
        if not yiwu_date and any(k in status for k in [
            "扫描入库", "过机扫描入库", "入仓"
        ]):
            yiwu_date = short_date

        # 送达
        if not delivered_date and any(k in status for k in [
            "DELIVERED", "送达", "签收", "已签收", "运单签收"
        ]):
            delivered_date = short_date

    parts = []

    if order_date:
        parts.append(f"{order_date}下单")

    if yiwu_date:
        parts.append(f"{yiwu_date}义乌入库")

    if delivered_date:
        parts.append(f"{delivered_date}送达")

    return "-".join(parts)


# ===============================
# 分析函数
# ===============================
def analyze_tracking(tracking_list):

    if not tracking_list:
        return {
            "latest_status": "无数据",
            "latest_time": "",
            "first_time": "",
            "delivered": "否",
            "smart_summary": ""
        }

    latest = tracking_list[0]
    earliest = tracking_list[-1]

    # 严谨判断送达
    delivered = False
    delivery_time = ""

    for row in tracking_list:
        if any(k in row["status"] for k in [
            "DELIVERED", "送达", "签收", "已签收", "运单签收"
        ]):
            delivered = True
            delivery_time = row["time"]
            break

    # 计算天数
    total_days = ""
    try:
        fmt = "%Y-%m-%d %H:%M"
        start = datetime.strptime(earliest["time"], fmt)
        end = datetime.strptime(latest["time"], fmt)
        total_days = (end - start).days
    except:
        pass

    # 精简节点
    smart_summary = extract_logistics_summary(tracking_list)

    result = {
        "latest_status": latest["status"],
        "latest_time": latest["time"],
        "first_time": earliest["time"],
        "delivered": "是" if delivered else "否",
        "smart_summary": smart_summary
    }

    if EXPORT_TOTAL_DAYS:
        result["total_days"] = total_days

    if EXPORT_TRACK_COUNT:
        result["track_count"] = len(tracking_list)

    if EXPORT_FULL_TRACK:
        result["full_track"] = " | ".join(
            [f'{r["time"]} {r["status"]}' for r in tracking_list]
        )

    return result


# ===============================
# 主程序
# ===============================
def main():

    df = pd.read_excel("input.xlsx", engine="openpyxl", dtype=str)

    output_data = []

    for _, row in df.iterrows():

        order_id = str(row["order_id"]).strip()
        print("查询:", order_id)

        result = query_tracking(order_id)

        if result and result.get("code") == 1:
            tracking_list = parse_tracking(result["data"])
            analysis = analyze_tracking(tracking_list)

            output_data.append({
                "order_id": order_id,
                **analysis
            })
        else:
            output_data.append({
                "order_id": order_id,
                "latest_status": "查询失败"
            })

        time.sleep(0.8)

    pd.DataFrame(output_data).to_excel("output.xlsx", index=False)
    print("完成 ✅ 已生成 output.xlsx")


if __name__ == "__main__":
    main()