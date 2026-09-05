"""HNSW 调参基准：在真实 pgvector 上量化召回率/延迟与参数的关系。

用法（需先启动 pgvector Postgres，如 compose 的 25432 或基准容器）：
    py scripts/benchmark_hnsw.py --dsn postgresql://postgres:password@127.0.0.1:25433/bench \
        --rows 20000 --dim 256 --queries 50

流程：
1. 建表并批量插入 N 条随机向量，其中每条查询向量都"埋入"一个已知最近邻
   （对查询向量加微扰），以便计算可校验的召回率@10。
2. 对比三列数据的 top-10：精确扫描（`ORDER BY vec <=> q` 无索引）与
   HNSW（不同 ef_search）——输出召回率与 p50/p95 延迟。
3. 输出调参建议表。
"""
from __future__ import annotations

import argparse
import random
import statistics
import time

import psycopg

DEFAULT_DSN = "postgresql://postgres:password@127.0.0.1:25433/bench"


def parse_args():
    parser = argparse.ArgumentParser(description="pgvector HNSW 调参基准")
    parser.add_argument("--dsn", default=DEFAULT_DSN)
    parser.add_argument("--rows", type=int, default=20000, help="插入的向量总数")
    parser.add_argument("--dim", type=int, default=256, help="向量维度（默认 256 加速基准；生产为 EMBEDDING_DIM）")
    parser.add_argument("--queries", type=int, default=50, help="召回/延迟测量的查询数")
    parser.add_argument("--m", type=int, default=16)
    parser.add_argument("--ef-construction", type=int, default=64)
    parser.add_argument("--ef-search-values", type=int, nargs="+", default=[10, 40, 100, 200])
    return parser.parse_args()


def random_unit_vector(dim, rng):
    vector = [rng.gauss(0, 1) for _ in range(dim)]
    norm = sum(v * v for v in vector) ** 0.5
    return [v / norm for v in vector]


def perturbed(vector, rng, noise=0.02):
    """对向量加微小扰动：作为该向量的"已知最近邻"用于召回校验。"""
    return [v + rng.gauss(0, noise) for v in vector]


def cosine_distance(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 1.0
    return 1.0 - dot / (na * nb)


def main():
    args = parse_args()
    rng = random.Random(42)
    dim = args.dim

    with psycopg.connect(args.dsn) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute("DROP TABLE IF EXISTS hnsw_bench")
            cur.execute(f"CREATE TABLE hnsw_bench (id bigserial PRIMARY KEY, vec vector({dim}))")

            print(f"插入 {args.rows} 条 {dim} 维向量…")
            insert_start = time.perf_counter()
            batch = []
            for i in range(args.rows):
                batch.append("[" + ",".join(f"{v:.6f}" for v in random_unit_vector(dim, rng)) + "]")
                if len(batch) == 1000 or i == args.rows - 1:
                    cur.executemany("INSERT INTO hnsw_bench (vec) VALUES (%s)", [(v,) for v in batch])
                    batch.clear()
            print(f"  插入耗时 {time.perf_counter() - insert_start:.1f}s")

            # 生成查询集：每个查询从库中取一个向量加扰动，其"已知最近邻"即原向量
            source_rows = cur.execute(
                "SELECT id, vec FROM hnsw_bench ORDER BY id LIMIT %s", (args.queries,)
            ).fetchall()
            queries = []
            for _qid, vec in source_rows:
                if isinstance(vec, str):
                    vec = [float(x) for x in vec.strip("[]").split(",")]
                queries.append((perturbed(vec, rng), vec))

            index_name = "ix_hnsw_bench"

            def timed_top10(use_index, ef_search=None):
                # SET 不支持绑定参数；值均为脚本内的受控字面量
                cur.execute(f"SET enable_seqscan = {'off' if use_index else 'on'}")
                if ef_search is not None:
                    cur.execute(f"SET hnsw.ef_search = {int(ef_search)}")
                latencies = []
                hits = 0
                for qvec, expected in queries:
                    qtext = "[" + ",".join(f"{v:.6f}" for v in qvec) + "]"
                    start = time.perf_counter()
                    cur.execute(
                        "SELECT id, vec FROM hnsw_bench ORDER BY vec <=> %s LIMIT 10",
                        (qtext,),
                    )
                    rows = cur.fetchall()
                    latencies.append((time.perf_counter() - start) * 1000)
                    top_ids = [r[0] for r in rows]
                    # 精确最近邻（扰动源向量）在 top-10 中即算命中
                    expected_id = None
                    for rid, vec in expected_pairs:
                        if isinstance(vec, str):
                            vec = [float(x) for x in vec.strip("[]").split(",")]
                        if vec == expected:
                            expected_id = rid
                            break
                    if expected_id and expected_id in top_ids:
                        hits += 1
                latencies.sort()
                recall = hits / len(queries)
                return recall, statistics.median(latencies), latencies[int(len(latencies) * 0.95)]

            # 期望最近邻：扰动源向量（id/vec 与查询集一一对应）
            expected_pairs = [(rid, vec) for (qvec, vec), (rid, vec_text) in zip(queries, source_rows)]

            print(f"\n对 {len(queries)} 条查询测量 top-10 召回与延迟…\n")
            header = f"{'模式':<28}{'recall@10':>10}{'p50(ms)':>10}{'p95(ms)':>10}"
            print(header)
            print("-" * len(header))

            exact_recall, exact_p50, exact_p95 = timed_top10(use_index=False)
            print(f"{'精确扫描（无索引）':<26}{exact_recall:>10.1%}{exact_p50:>10.1f}{exact_p95:>10.1f}")

            cur.execute(
                f"CREATE INDEX {index_name} ON hnsw_bench "
                f"USING hnsw (vec vector_cosine_ops) "
                f"WITH (m = {args.m}, ef_construction = {args.ef_construction})"
            )
            cur.execute("ANALYZE hnsw_bench")

            for ef in args.ef_search_values:
                recall, p50, p95 = timed_top10(use_index=True, ef_search=ef)
                print(f"{'HNSW ef_search=' + str(ef):<26}{recall:>10.1%}{p50:>10.1f}{p95:>10.1f}")

            print(
                "\n调参参考：召回接近精确扫描即可停止加大 ef_search；"
                "p95 延迟显著上升说明 ef_search 过大。\n"
                "索引构建参数 m/ef_construction 变更需重建索引（迁移 20260902_17 读取配置生成）。"
            )


if __name__ == "__main__":
    main()
