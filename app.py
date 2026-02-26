from fastapi import FastAPI, Request, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import pandas as pd
import os
import tracker
from datetime import datetime
from feishu import write_batch_orders_to_feishu

progress_status = {
    "total": 0,
    "current": 0,
    "done": False,
    "results": []
}
app = FastAPI()
templates = Jinja2Templates(directory="templates")

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ===============================
# 首页
# ===============================
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    # 如果最近一次处理已完成，则将结果注入模板以显示表格
    if progress_status.get("done") and progress_status.get("results"):
        results = progress_status.get("results")
        total = progress_status.get("total", 0)
        delivered_count = progress_status.get("delivered_count", 0)
        rate = progress_status.get("rate", 0)
        return templates.TemplateResponse("index.html", {"request": request, "results": results, "total": total, "delivered_count": delivered_count, "rate": rate})
    return templates.TemplateResponse("index.html", {"request": request})


# ===============================
# 上传并处理
# ===============================
@app.post("/upload", response_class=HTMLResponse)
async def upload(request: Request, file: UploadFile = File(...)):

    filepath = os.path.join(UPLOAD_DIR, file.filename)

    # 保存文件
    with open(filepath, "wb") as f:
        f.write(await file.read())
    # 仅保存文件并返回路径，实际处理由 WebSocket 发起（便于实时进度推送）
    return JSONResponse({"filename": filepath})


# ===============================
# 单号查询
# ===============================
@app.post("/lookup", response_class=HTMLResponse)
async def lookup(request: Request, order_id: str = None):
    # 支持表单字段或 JSON
    form = await request.form()
    if not order_id:
        order_id = form.get("order_id")
    if not order_id:
        return templates.TemplateResponse("index.html", {"request": request, "error": "请输入运单号"})

    # 同步调用 tracker.process_single，属于轻量级
    result = tracker.process_single(order_id)
    result_df = pd.DataFrame([result])
    total = 1
    delivered_count = 1 if result.get("delivered") == "是" else 0
    rate = round(delivered_count / total * 100, 2)
    # 保存输出也方便下载
    output_path = os.path.join(UPLOAD_DIR, "single_output.xlsx")
    result_df.to_excel(output_path, index=False)

    return templates.TemplateResponse(
        "index.html",
        {"request": request, "results": result_df.to_dict(orient="records"), "total": total, "delivered_count": delivered_count, "rate": rate}
    )


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        msg = await websocket.receive_json()
        filepath = msg.get("file")
        feishu_enabled = bool(msg.get("feishu", False))

        # 读取订单号
        try:
            df = pd.read_excel(filepath, dtype=str)
        except Exception as e:
            await websocket.send_json({"error": f"读取文件失败: {e}"})
            await websocket.close()
            return

        if "order_id" not in df.columns:
            await websocket.send_json({"error": "Excel 必须包含 order_id 列"})
            await websocket.close()
            return

        order_ids = df["order_id"].dropna().astype(str).tolist()

        async def progress_cb(done, total, order_id, status):
            await websocket.send_json({"done": done, "total": total, "order_id": order_id, "status": status})

        # 调用异步处理
        results = await tracker.process_orders_async(order_ids, progress_callback=progress_cb, concurrency=10, rate=2.0, feishu_enabled=feishu_enabled)

        # 写出最终结果
        result_df = pd.DataFrame(results)
        keep_columns = ["order_id", "latest_status", "latest_time", "delivered", "smart_summary"]
        final_df = result_df[keep_columns]
        output_path = os.path.join(UPLOAD_DIR, "output.xlsx")
        final_df.to_excel(output_path, index=False)

        # 保存到全局状态以便主页渲染
        progress_status["results"] = final_df.to_dict(orient="records")
        progress_status["total"] = len(final_df)
        delivered_count = 0
        if "delivered" in final_df.columns:
            delivered_count = sum(final_df["delivered"] == "是")
        progress_status["delivered_count"] = int(delivered_count)
        progress_status["rate"] = round(int(delivered_count) / max(len(final_df), 1) * 100, 2)
        progress_status["done"] = True

        # 如果启用飞书，批量推送最终结果
        if feishu_enabled:
            try:
                await write_batch_orders_to_feishu(results)
                await websocket.send_json({"feishu_status": "success"})
            except Exception as e:
                print(f"[WebSocket] Feishu batch push failed: {e}")
                await websocket.send_json({"feishu_status": f"error: {e}"})

        await websocket.send_json({"complete": True, "result": output_path})

    except WebSocketDisconnect:
        return
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ===============================
# 下载结果
# ===============================
@app.get("/download")
def download():
    file_path = os.path.join(UPLOAD_DIR, "output.xlsx")
    return FileResponse(file_path, filename="物流查询结果.xlsx")