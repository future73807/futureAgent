"""清理构建、测试与运行过程留下的产物。

这些文件全部在 .gitignore 里（git 从来不跟踪），但**会被重新生成**：
`npm run build` 写 dist/、E2E 套件写截图与失败现场、解释器写 __pycache__、
本地跑一次 API 就多出日志与临时库。所以清理要能随时重跑，不用靠记忆去删。

    py scripts/clean_artifacts.py            # 干跑，只列出会删什么
    py scripts/clean_artifacts.py --apply    # 真正删除

保留：node_modules（依赖，重装很贵）、.env、futureagent.db（开发库数据）、
mcp_server/workspace（联调素材，可用 scripts/seed_python_demo.py 重放）。
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# 目录：整棵删掉
TARGET_DIRS = (
    "frontend/dist",
    "admin-frontend/dist",
    "frontend/e2e/screens",
    "frontend/e2e/failures",
    "admin-frontend/e2e/screens",
    "admin-frontend/e2e/failures",
    "htmlcov",
    ".pytest_cache",
    ".ruff_cache",
)
# 文件：按名字或后缀删
TARGET_FILES = (
    "admin-frontend/e2e/last-run.json",
    "admin-frontend/e2e/sweep.log",
    "mock_llm.log",
    "frontend/e2e/narrow-last.png",
)
TARGET_GLOBS = (
    "frontend/e2e/*.png",
    "*.log",
    "**/__pycache__",
    "*.pyc",
)
# 空目录（git 看不到，但文件管理器里碍眼）
EMPTY_DIRS = (".v2c", "out")


def _iter_targets() -> list[Path]:
    targets: list[Path] = []
    for relative in TARGET_DIRS:
        path = BASE_DIR / relative
        if path.exists():
            targets.append(path)
    for relative in TARGET_FILES:
        path = BASE_DIR / relative
        if path.exists():
            targets.append(path)
    for pattern in TARGET_GLOBS:
        for path in BASE_DIR.glob(pattern):
            if "node_modules" in path.parts or ".git" in path.parts:
                continue
            if path not in targets:
                targets.append(path)
    for relative in EMPTY_DIRS:
        path = BASE_DIR / relative
        if path.is_dir() and not any(path.iterdir()):
            targets.append(path)
    return targets


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def main() -> int:
    parser = argparse.ArgumentParser(description="清理可再生成的产物")
    parser.add_argument("--apply", action="store_true", help="真正删除（默认只列出）")
    args = parser.parse_args()

    targets = _iter_targets()
    if not targets:
        print("没有需要清理的产物。")
        return 0

    total = 0
    for path in sorted(targets):
        size = _size(path)
        total += size
        marker = "删除" if args.apply else "将删除"
        print(f"  {marker} {path.relative_to(BASE_DIR)}（{size / 1024:.0f} KB）")
        if args.apply:
            shutil.rmtree(path, ignore_errors=True) if path.is_dir() else path.unlink(missing_ok=True)

    print(f"\n{'已清理' if args.apply else '待清理'} {len(targets)} 项，合计 {total / 1024 / 1024:.1f} MB")
    if not args.apply:
        print("加 --apply 真正执行。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
