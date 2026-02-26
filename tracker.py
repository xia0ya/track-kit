import requests
import time
from bs4 import BeautifulSoup
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import asyncio
import inspect
from feishu import write_to_feishu, write_to_feishu_sync

URL = "https://www.yhwl.com/index.php?s=zhimatongapi&c=home&m=index"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.yhwl.com/list-ddcx.html",
    "Origin": "https://www.yhwl.com",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
}

MAX_WORKERS = 10   # 🔥 线程数（建议 15-30 之间）


# ===============================
# 查询接口
# ===============================
def query_tracking(order_id, retry=2):

    session = requests.Session()

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
            time.sleep(0.5)

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
# 三节点摘要
# ===============================
def extract_logistics_summary(tracking_list):

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

        if not order_date and any(k in status for k in [
            "创建运单", "运单已确认", "Shipper created"
        ]):
            order_date = short_date

        if not yiwu_date and any(k in status for k in [
            "扫描入库", "过机扫描入库", "入仓"
        ]):
            yiwu_date = short_date

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
# 单条处理
# ===============================
DELIVER_KEYS = ["DELIVERED", "送达", "签收", "已签收", "运单签收"]

def process_single(order_id):

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

    delivered = False
    for row in tracking_list:
        if any(k in row["status"] for k in DELIVER_KEYS):
            delivered = True
            break

    smart_summary = extract_logistics_summary(tracking_list)

    return {
        "order_id": order_id,
        "latest_status": latest["status"],
        "latest_time": latest["time"],
        "delivered": "是" if delivered else "否",
        "smart_summary": smart_summary
    }

# ===============================
# 多线程批量处理
# ===============================
def process_orders(order_ids):

    results = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:

        futures = {
            executor.submit(process_single, order_id): order_id
            for order_id in order_ids
        }

        for future in as_completed(futures):
            result = future.result()
            results.append(result)

    # 保持原顺序
    results.sort(key=lambda x: order_ids.index(x["order_id"]))

    return results


async def process_orders_async(order_ids, progress_callback=None, concurrency=10, rate=2.0, feishu_enabled=False, push_interval=30):
    """
    异步批量处理，内部会把阻塞的 `process_single` 放到线程池中执行。

    - order_ids: 列表
    - progress_callback(done, total, order_id, status): 可为 async 或 sync callable
    - concurrency: 最大并发线程数
    - rate: 每秒允许的请求数（粗略）
    - feishu_enabled: 是否启用飞书周期性推送（短消息）
    - push_interval: 飞书推送间隔（秒）
    """
    total = len(order_ids)
    semaphore = asyncio.Semaphore(concurrency)
    loop = asyncio.get_running_loop()
    results = []
    processed = 0
    last_push = 0

    async def call_progress(done, total, order_id, status):
        if progress_callback is None:
            return
        try:
            if inspect.iscoroutinefunction(progress_callback):
                await progress_callback(done, total, order_id, status)
            else:
                # run sync callback in default loop executor
                await loop.run_in_executor(None, lambda: progress_callback(done, total, order_id, status))
        except Exception:
            pass

    async def worker(order_id):
        nonlocal processed, last_push
        async with semaphore:
            # 简单均摊限流
            await asyncio.sleep(1.0 / max(rate, 1e-6))
            try:
                res = await loop.run_in_executor(None, process_single, order_id)
                status = "ok"
            except Exception as e:
                res = {
                    "order_id": order_id,
                    "latest_status": f"error: {e}",
                    "latest_time": "",
                    "delivered": "否",
                    "smart_summary": ""
                }
                status = "error"

            results.append(res)
            processed += 1
            await call_progress(processed, total, order_id, status)

            if feishu_enabled and (time.time() - last_push >= push_interval or processed == total):
                # 推送简短文本到飞书（异步）
                summary = f"已处理 {processed}/{total}，最近订单 {order_id} 状态 {status}"
                try:
                    await write_to_feishu(summary)
                except Exception:
                    # 如果异步推送出错，尝试同步方式（防止未安装 asyncio loop）
                    try:
                        write_to_feishu_sync([[datetime.now().strftime("%Y-%m-%d %H:%M:%S"), summary]])
                    except Exception:
                        pass
                last_push = time.time()

    tasks = [asyncio.create_task(worker(oid)) for oid in order_ids]
    await asyncio.gather(*tasks)

    # 保持原始顺序
    results.sort(key=lambda x: order_ids.index(x["order_id"]))
    return results