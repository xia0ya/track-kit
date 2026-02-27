"""Utility for reading an Excel file of order IDs, querying logistics data and writing results back.

The new requirement:

* Read an Excel file containing at least an ``order_id`` column.
* If a row already has ``delivered`` set to ``\"是\"`` the row is skipped (no request is made).
* For remaining rows the tracker logic from ``tracker.process_single`` is used.
* After the queries the Excel is updated with the results and written to disk.

This module is intentionally standalone and does *not* modify any of the existing project files.
"""

import os
from typing import Optional

import pandas as pd

import tracker


def update_orders_from_excel(
    input_path: str,
    output_path: Optional[str] = None,
    skip_column: str = "delivered",
    delivered_value: str = "是",
) -> str:
    """Read ``input_path`` Excel, query orders and write results back.

    Parameters
    ----------
    input_path : str
        Path to the source Excel file. It must contain a column named ``order_id``.
    output_path : Optional[str]
        Where to write the updated file. If ``None`` the original filename is
        suffixed with ``_updated`` before the extension (eg. ``foo_updated.xlsx``).
    skip_column : str
        Name of the column used to decide whether to skip a row. The row is
        *not* queried if its value exactly matches ``delivered_value`` after
        stripping whitespace.
    delivered_value : str
        The value which indicates the order has already been delivered and
        therefore should be skipped.

    Returns
    -------
    str
        The path to the written Excel file.
    """

    # read the workbook
    df = pd.read_excel(input_path, dtype=str)

    if "order_id" not in df.columns:
        raise ValueError("Excel 必须包含 order_id 列")

    # ensure the columns that will be written exist
    for col in ["latest_status", "latest_time", "delivered", "smart_summary"]:
        if col not in df.columns:
            df[col] = ""

    # iterate rows; using ``iterrows`` because we write back directly to df
    for idx, row in df.iterrows():
        # skip rows that already marked as delivered
        if str(row.get(skip_column, "")).strip() == delivered_value:
            continue

        order_id = str(row["order_id"]).strip()
        if not order_id:
            continue

        res = tracker.process_single(order_id)
        # copy fields back into the dataframe row
        for k, v in res.items():
            df.at[idx, k] = v

    # determine output path
    if output_path is None:
        base, ext = os.path.splitext(input_path)
        output_path = f"{base}_updated{ext or '.xlsx'}"

    df.to_excel(output_path, index=False)
    return output_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Read a spreadsheet of order ids, query statuses (skipping those already delivered) and write an updated file.")
    parser.add_argument("input", help="Path to the source Excel file")
    parser.add_argument("-o", "--output", help="Path to the output file (default: append _updated)")
    parser.add_argument(
        "--skip-column", default="delivered",
        help="Column name that indicates an already-processed row (default: delivered)",
    )
    parser.add_argument(
        "--skip-value", default="是",
        help="Value in the skip column that triggers skipping (default: 是)",
    )

    args = parser.parse_args()

    # ensure input exists before attempting to read it
    if not os.path.isfile(args.input):
        parser.error(f"输入文件不存在: {args.input}")

    try:
        out = update_orders_from_excel(
            args.input,
            output_path=args.output,
            skip_column=args.skip_column,
            delivered_value=args.skip_value,
        )
    except Exception as e:  # catch broad errors to provide feedback
        parser.error(f"处理失败: {e}")

    print(f"写入文件: {out}")
