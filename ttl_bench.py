"""TTL experiment for the design tension "caching freshness vs traffic reduction" (Section 6).

The origin decides the TTL with its Max-Age header, so for each TTL value restart
server.py on H1 with --max-age, then run this on H3:

    python server.py --max-age 0        (on H1)
    python ttl_bench.py --proxy-host <H2-IP>       (on H3)

Workload: simulated page views (index.html, about.html, notes.txt, logo.png on one
keep-alive connection) arriving at random, exponentially distributed intervals with a
fixed seed, so every TTL sees exactly the same request sequence. The cache is cleared
(PURGE *) before the run.

For each run it records the hit ratio, the bytes the proxy had to fetch from the
origin (MISS responses), the mean page fetch time, and the worst-case staleness (= TTL).
Appends one row to results/ttl_summary.csv and writes every request to
results/ttl_<max-age>_<time>_raw.csv.
"""

import argparse
import csv
import os
import random
import statistics
import time

import bench

PAGE = bench.PAGE


def page_view(writer, view, t0):
    rows = []
    start = bench.now()
    with bench.connect() as s:
        for i, p in enumerate(PAGE):
            bench.send(s, "GET", p, keep_alive=i < len(PAGE) - 1)
            status, h, nbytes = bench.recv_response(s, "GET")
            rows.append((p, status, h.get("x-cache", "?"), nbytes, h.get("max-age", "")))
    elapsed = (bench.now() - start) * 1000
    for p, status, xc, nbytes, ma in rows:
        writer.writerow([view, round(time.time() - t0, 3), p, status, xc, nbytes, ma, round(elapsed, 3)])
    return rows, elapsed


def main():
    ap = argparse.ArgumentParser(description="CacheNet TTL sweep (one TTL per run)")
    ap.add_argument("--proxy-host", required=True)
    ap.add_argument("--proxy-port", type=int, default=9090)
    ap.add_argument("--duration", type=float, default=120, help="seconds of page views")
    ap.add_argument("--mean-gap", type=float, default=2.0, help="mean seconds between page views")
    ap.add_argument("--seed", type=int, default=327)
    ap.add_argument("--out", default="results")
    args = ap.parse_args()

    bench.PROXY = (args.proxy_host, args.proxy_port)
    bench.one_shot("PURGE", "*")

    # Fixed arrival times, identical for every TTL.
    rng = random.Random(args.seed)
    arrivals, t = [], 0.0
    while True:
        t += rng.expovariate(1 / args.mean_gap)
        if t >= args.duration:
            break
        arrivals.append(t)

    stamp = time.strftime("%Y%m%d_%H%M%S")
    os.makedirs(args.out, exist_ok=True)
    hits = misses = origin_bytes = total_bytes = 0
    times, max_age = [], "?"
    t0 = time.time()
    raw_path = None
    with open(os.path.join(args.out, f"ttl_tmp_{stamp}.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["view", "t_s", "path", "status", "x_cache", "bytes", "max_age", "page_ms"])
        for view, at in enumerate(arrivals, 1):
            wait = t0 + at - time.time()
            if wait > 0:
                time.sleep(wait)
            rows, ms = page_view(w, view, t0)
            times.append(ms)
            for _, _, xc, nbytes, ma in rows:
                max_age = ma or max_age
                total_bytes += nbytes
                if xc == "HIT":
                    hits += 1
                else:
                    misses += 1
                    origin_bytes += nbytes
        raw_path = f.name
    final = os.path.join(args.out, f"ttl_{max_age}_{stamp}_raw.csv")
    os.replace(raw_path, final)

    n = hits + misses
    row = {
        "max_age_s": max_age,
        "page_views": len(arrivals),
        "requests": n,
        "hits": hits,
        "misses": misses,
        "hit_ratio": round(hits / n, 4),
        "bytes_to_client": total_bytes,
        "bytes_from_origin": origin_bytes,
        "origin_traffic_saved_pct": round(100 * (1 - origin_bytes / total_bytes), 2),
        "mean_page_ms": round(statistics.mean(times), 3),
        "median_page_ms": round(statistics.median(times), 3),
        "stdev_page_ms": round(statistics.stdev(times), 3),
        "worst_staleness_s": max_age,
        "duration_s": args.duration,
        "mean_gap_s": args.mean_gap,
        "seed": args.seed,
        "time": stamp,
    }
    summary = os.path.join(args.out, "ttl_summary.csv")
    new = not os.path.exists(summary)
    with open(summary, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        if new:
            w.writeheader()
        w.writerow(row)
    print(", ".join(f"{k}={v}" for k, v in row.items()))
    print("wrote", final, "and appended to", summary)


if __name__ == "__main__":
    main()
