"""把联调用的示例 Python 项目写进「当前工作区」的私有文件目录。

工作区文件目录（``mcp_server/workspace/.futureagent/workspaces/<scope>``）
不入库，所以测试素材用脚本生成，换机器 / 换工作区都能一键重放：

    py scripts/seed_python_demo.py                  # 默认工作区
    py scripts/seed_python_demo.py --workspace <id> # 指定工作区

项目本身：只依赖标准库的销售统计 CLI，故意留了一条失败的用例
（``average_amount`` 把空金额行算进分母），用来验证计划模式与自主模式
能否「读文件 → 定位缺陷 → 改代码 → 跑测试 → 汇总」。
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _workspace_root() -> Path:
    """素材必须落在**当前配置**的工作区根目录下。

    根目录由 ``WORKSPACE_FILES_ROOT``（API 侧）与 ``MCP_WORKSPACE_ROOT``（MCP 服务
    侧）决定，两者必须一致；这里跟随同一个覆盖，否则换了根目录之后素材会写进
    仓库里的默认目录，而智能体的文件工具在别处找文件。
    """
    override = os.getenv("WORKSPACE_FILES_ROOT") or os.getenv("MCP_WORKSPACE_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    try:
        # 以脚本方式运行时 sys.path[0] 是 scripts/ 而不是仓库根，config 不在
        # 其内；先补上仓库根，否则这里永远读不到配置、静默退回默认目录。
        if str(BASE_DIR) not in sys.path:
            sys.path.insert(0, str(BASE_DIR))
        from config import settings

        return Path(settings.workspace_files_root).expanduser().resolve()
    except Exception:  # noqa: BLE001 - 无法读取配置时退回仓库默认目录
        return BASE_DIR / "mcp_server" / "workspace"


WORKSPACE_ROOT = _workspace_root()


def scope_dir(workspace_id: str) -> Path:
    scope = hashlib.sha256(workspace_id.encode("utf-8")).hexdigest()
    return WORKSPACE_ROOT / ".futureagent" / "workspaces" / scope


FILES: dict[str, str] = {
    "README.md": """# python-demo

futureAgent 联调用的示例 Python 项目：一个只依赖标准库的销售数据统计 CLI，用来验证
「计划模式 + 自主模式」下的工作区工具链（读文件 → 改代码 → 跑测试 → 汇总）。

## 约定

- 入口：`py -m sales_report.cli data/sales.csv`
- 测试：`py -m unittest discover -s tests`
- 只允许标准库，不要引入第三方包。
- 金额统一保留两位小数。

## 已知问题

`py -m unittest discover -s tests` 目前有一条用例失败：`average_amount` 把
「金额为空」的行也算进了分母。修复要求：分母只统计金额非空的行，且保持
`total_amount` / `parse_rows` 的现有语义不变。
""",
    "sales_report/__init__.py": '"""sales_report 包。"""\n',
    "sales_report/stats.py": '''"""销售数据的解析与统计（供 CLI 与测试共用）。"""
from __future__ import annotations

import csv
import io


def parse_rows(text: str) -> list[dict[str, str]]:
    """把 CSV 文本解析成字典列表。

    只跳过完全空白的行；金额为空的行会保留（缺数据的记录仍需能被看到）。
    """
    rows: list[dict[str, str]] = []
    for row in csv.DictReader(io.StringIO(text)):
        if not any((value or "").strip() for value in row.values()):
            continue
        rows.append({key: (value or "").strip() for key, value in row.items()})
    return rows


def _amount_of(row: dict[str, str]) -> float:
    """把一行的金额转成浮点数；空值按 0 计。"""
    raw = (row.get("amount") or "").strip()
    return float(raw) if raw else 0.0


def total_amount(rows: list[dict[str, str]]) -> float:
    """金额合计，保留两位小数。"""
    return round(sum(_amount_of(row) for row in rows), 2)


def average_amount(rows: list[dict[str, str]]) -> float:
    """平均金额，保留两位小数。"""
    if not rows:
        return 0.0
    return round(total_amount(rows) / len(rows), 2)
''',
    "sales_report/cli.py": '''"""销售数据统计 CLI：py -m sales_report.cli data/sales.csv"""
from __future__ import annotations

import sys
from pathlib import Path

from sales_report.stats import average_amount, parse_rows, total_amount


def render_report(csv_text: str) -> str:
    rows = parse_rows(csv_text)
    blank = sum(1 for row in rows if not (row.get("amount") or "").strip())
    lines = [
        f"记录数：{len(rows)}",
        f"金额合计：{total_amount(rows):.2f}",
        f"平均金额：{average_amount(rows):.2f}",
        f"缺金额记录：{blank}",
    ]
    return "\\n".join(lines)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("用法：py -m sales_report.cli <csv 路径>", file=sys.stderr)
        return 2
    path = Path(argv[1])
    if not path.exists():
        print(f"找不到文件：{path}", file=sys.stderr)
        return 1
    print(render_report(path.read_text(encoding="utf-8")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
''',
    "tests/test_stats.py": '''import unittest

from sales_report.stats import average_amount, parse_rows, total_amount

CSV_TEXT = """date,region,amount
2026-09-01,华东,100.50
2026-09-02,华北,
2026-09-03,华南,49.50
"""


class StatsTest(unittest.TestCase):
    def test_parse_keeps_blank_amount_row(self):
        rows = parse_rows(CSV_TEXT)
        self.assertEqual(len(rows), 3)

    def test_total_amount(self):
        rows = parse_rows(CSV_TEXT)
        self.assertEqual(total_amount(rows), 150.0)

    def test_average_ignores_blank_amounts(self):
        """空金额的行不应计入分母：150.0 / 2 = 75.0"""
        rows = parse_rows(CSV_TEXT)
        self.assertEqual(average_amount(rows), 75.0)


if __name__ == "__main__":
    unittest.main()
''',
    "data/sales.csv": """date,region,amount
2026-09-01,华东,100.50
2026-09-02,华北,
2026-09-03,华南,49.50
2026-09-04,西南,200.00
2026-09-05,东北,
""",
}


def seed(workspace_id: str, force: bool = False) -> Path:
    target = scope_dir(workspace_id) / "python-demo"
    for relative, content in FILES.items():
        path = target / relative
        if path.exists() and not force:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="写入 python-demo 联调素材")
    parser.add_argument("--workspace", default="b7f94b6c246442c59d19c374136ea79e", help="工作区 id")
    parser.add_argument("--force", action="store_true", help="覆盖已存在的文件")
    args = parser.parse_args()
    target = seed(args.workspace, force=args.force)
    print(f"python-demo 已写入：{target}")
    print("自检：cd 到该目录后执行 `py -m unittest discover -s tests`，应看到 1 条失败用例。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
