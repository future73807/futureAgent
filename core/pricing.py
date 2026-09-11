"""模型单价与成本换算。

本模块刻意不内置任何猜测的价格。``PRICE_PER_MILLION_TOKENS`` 初始为空，
只有部署方按自己与供应商的实际合约填入后，成本才会被计算；未登记的模型
返回 ``None``，界面显示“未定价”，而不是给出一个看似精确实则编造的数字。
"""
from __future__ import annotations


# 模型 ID -> (每百万输入 token 单价, 每百万输出 token 单价)，货币单位由部署方约定。
# 示例（请按实际合约填写后再启用）：
#   "gpt-4o-mini": (0.15, 0.60),
PRICE_PER_MILLION_TOKENS: dict[str, tuple[float, float]] = {}


def is_priced(model_id: str) -> bool:
    """该模型是否已登记单价。"""
    return model_id in PRICE_PER_MILLION_TOKENS


def estimate_cost(
    model_id: str, input_tokens: int, output_tokens: int
) -> float | None:
    """按已登记单价换算成本；模型未定价时返回 ``None``。

    名称保留 estimate 前缀是因为它依赖登记的单价是否准确，但输入 token 数
    始终来自模型真实上报，不做任何本地估算。
    """
    price = PRICE_PER_MILLION_TOKENS.get(model_id)
    if not price:
        return None
    input_price, output_price = price
    return round(
        (max(0, input_tokens) * input_price + max(0, output_tokens) * output_price)
        / 1_000_000,
        6,
    )


def aggregate_cost(rows: list[dict[str, object]]) -> tuple[float | None, int]:
    """汇总多行成本，返回 ``(总额, 可定价行数)``。

    全部未定价时总额为 ``None``。调用方必须同时使用可定价行数，才能区分
    “成本确实为 0”与“有若干行无法定价”——后者不是完整账单。
    """
    total = 0.0
    priced_rows = 0
    for row in rows:
        cost = row.get("cost")
        if isinstance(cost, (int, float)):
            total += float(cost)
            priced_rows += 1
    return (round(total, 6) if priced_rows else None), priced_rows
