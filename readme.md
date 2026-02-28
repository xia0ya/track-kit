前端测试

uvicorn app:app --reload --host 127.0.0.1 --port 8001

## 新增功能：批量 Excel 查询

项目中新增加了一个独立的脚本 `excel_query.py`，用于从 Excel 中读取订单号并批量查询。

该脚本具有以下行为：

1. **读取指定 Excel 文件**，必须包含 `order_id` 列。
2. 如果某行的 `delivered` 列已经是 **`是`**，则跳过该行不再查询。
3. 对其他行调用 `tracker.process_single` 获取最新状态并将结果写回表格。
4. 将更新后的内容输出为新文件（默认在原文件名后添加 `_updated`）。

### 命令行示例

```bash
# 请确保当前目录下存在 orders.xlsx，或提供完整路径
python excel_query.py orders.xlsx             # 读 orders.xlsx 并生成 orders_updated.xlsx
python excel_query.py /path/to/orders.xlsx    # 使用绝对或相对路径均可
python excel_query.py orders.xlsx -o result.xlsx  # 指定输出路径

# 如果指定的输入文件不存在，脚本会报错并提示
```

## 定时调度脚本

脚本 `excel_scheduler.py` 提供了一个简单的循环调度器，可以按固定间隔执行
`excel_query` 的功能。调度器通过当前目录下的 `scheduler_state.json` 文件进行
启停控制，文件内容示例：

```json
{"enabled": true}
```

可通过命令行或手动编辑该文件来启动/暂停。

### 使用示例

```bash
# 启动调度器，每小时执行一次
python excel_scheduler.py start --input orders.xlsx --interval 3600

# 暂停（或从另一个终端执行）
python excel_scheduler.py stop

# 查看状态
python excel_scheduler.py status
```

当调度器正在运行时，按 <kbd>Ctrl</kbd>+<kbd>C</kbd> 可以停止进程，随后可以
通过 `start` 再次启动或编辑 state 文件设置 `"enabled": false` 来暂停。

手动修改 `scheduler_state.json` 并保存也会影响正在运行的循环，下次间隔到达
时生效。


t-g1042qggQ55DTFCYWASG2IZHGOXNM3WTU4CHZ4EU# track-kit


# 飞书传入并并发写入
 feishu_query_v3.py，这是核心代码