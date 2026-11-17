"""CacheNet benchmark for R6 (performance measurement).

Run on the client host (H3) while server.py runs on H1 and proxy.py on H2:

    python bench.py --proxy-host <H2-IP> --label wifi
    python bench.py --proxy-host <H2-IP> --label wired --runs 10

Every test is repeated --runs times (default 5). Each run writes one row to
results/bench_<label>_<time>_raw.csv, and the mean, standard deviation, min and
max of every test go to results/bench_<label>_<time>_summary.csv.

Timers start before the TCP connection is opened whenever a test opens one,
so handshake cost is included exactly where a real client would pay it.

Tests (conditions compared):
  1. TCP connect time to the proxy, which is about 1 RTT (SYN -> SYN-ACK)
  2. Application RTT: HEAD of a cached object on an already open connection
  3. Single object, cache MISS vs HIT        (/index.html, small)
  4. Throughput,   cache MISS vs HIT        (/large.txt, about 200 KB)
  5. Page fetch (4 objects), persistent vs non-persistent, warm and cold cache
"""

import argparse
import csv
import os
import socket
import statistics
import time

VERSION = "CNTP/1.0"
PAGE = ["/index.html", "/about.html", "/notes.txt", "/logo.png"]
SMALL = "/index.html"
LARGE = "/large.txt"
TIMEOUT = 10

PROXY = ("127.0.0.1", 9090)


def now():
    return time.perf_counter()


def connect():
    return socket.create_connection(PROXY, timeout=TIMEOUT)


def send(sock, method, path, keep_alive=True):
    conn = "keep-alive" if keep_alive else "close"
    sock.sendall(
        f"{method} {path} {VERSION}\r\nHost: {PROXY[0]}:{PROXY[1]}\r\nConnection: {conn}\r\n\r\n".encode()
    )


def recv_response(sock, method="GET"):
    """Read exactly one response. Returns (status, headers, total_bytes)."""
    buf = b""
    while b"\r\n\r\n" not in buf:
        data = sock.recv(65536)
        if not data:
            raise ConnectionError("proxy closed the connection before sending headers")
        buf += data
    head, body = buf.split(b"\r\n\r\n", 1)
    lines = head.decode("latin-1").split("\r\n")
    status = int(lines[0].split(" ", 2)[1])
    headers = {}
    for line in lines[1:]:
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    length = 0 if method == "HEAD" else int(headers.get("content-length", "0"))
    while len(body) < length:
        data = sock.recv(65536)
        if not data:
            raise ConnectionError("proxy closed the connection mid-body")
        body += data
    return status, headers, len(head) + 4 + length


def one_shot(method, path):
    """Open a connection, send one request with Connection: close, return (status, headers, bytes)."""
    with connect() as s:
        send(s, method, path, keep_alive=False)
        return recv_response(s, method)


def purge(path):
    one_shot("PURGE", path)  # 404 just means it was not cached, which is fine


def warm(paths):
    for p in paths:
        one_shot("GET", p)


def check(headers, expected, test):
    got = headers.get("x-cache", "?")
    if expected and got != expected:
        print(f"  ! {test}: expected X-Cache {expected}, got {got} (is the TTL too short?)")
    return got


# ---------------------------------------------------------------- tests

def t_connect():
    start = now()
    s = connect()
    elapsed = now() - start
    s.close()
    return elapsed, 0, "-"


def t_app_rtt():
    warm([SMALL])
    with connect() as s:
        send(s, "HEAD", SMALL)          # first request opens the proxy's origin path too
        recv_response(s, "HEAD")
        start = now()
        send(s, "HEAD", SMALL)
        _, h, nbytes = recv_response(s, "HEAD")
        elapsed = now() - start
    return elapsed, nbytes, check(h, "HIT", "app RTT")


def t_object(path, cached):
    if cached:
        warm([path])
    else:
        purge(path)
    start = now()
    with connect() as s:
        send(s, "GET", path, keep_alive=False)
        status, h, nbytes = recv_response(s)
    elapsed = now() - start
    if status != 200:
        raise RuntimeError(f"GET {path} returned {status}")
    return elapsed, nbytes, check(h, "HIT" if cached else "MISS", f"GET {path}")


def t_page(persistent, cached):
    if cached:
        warm(PAGE)
    else:
        purge("*")
    expected = "HIT" if cached else "MISS"
    total_bytes, tags = 0, []
    start = now()
    if persistent:
        with connect() as s:
            for i, p in enumerate(PAGE):
                send(s, "GET", p, keep_alive=i < len(PAGE) - 1)
                _, h, n = recv_response(s)
                total_bytes += n
                tags.append(check(h, expected, f"page {p}"))
    else:
        for p in PAGE:
            with connect() as s:
                send(s, "GET", p, keep_alive=False)
                _, h, n = recv_response(s)
            total_bytes += n
            tags.append(check(h, expected, f"page {p}"))
    elapsed = now() - start
    return elapsed, total_bytes, "/".join(sorted(set(tags)))


TESTS = [
    ("TCP connect (~1 RTT)", "client->proxy", t_connect),
    ("App RTT (HEAD, open conn)", "cached", t_app_rtt),
    ("Object " + SMALL, "MISS", lambda: t_object(SMALL, False)),
    ("Object " + SMALL, "HIT", lambda: t_object(SMALL, True)),
    ("Throughput " + LARGE, "MISS", lambda: t_object(LARGE, False)),
    ("Throughput " + LARGE, "HIT", lambda: t_object(LARGE, True)),
    ("Page fetch (4 objects)", "persistent, warm cache", lambda: t_page(True, True)),
    ("Page fetch (4 objects)", "non-persistent, warm cache", lambda: t_page(False, True)),
    ("Page fetch (4 objects)", "persistent, cold cache", lambda: t_page(True, False)),
    ("Page fetch (4 objects)", "non-persistent, cold cache", lambda: t_page(False, False)),
]


def main():
    global PROXY
    parser = argparse.ArgumentParser(description="CacheNet R6 benchmark")
    parser.add_argument("--proxy-host", default=PROXY[0], help="IP of the proxy host (H2)")
    parser.add_argument("--proxy-port", type=int, default=PROXY[1])
    parser.add_argument("--runs", type=int, default=5, help="repetitions per test (at least 5 for R6)")
    parser.add_argument("--label", default="lan", help="name of this network condition, e.g. wifi, wired, vm")
    parser.add_argument("--out", default="results", help="output folder")
    args = parser.parse_args()
    PROXY = (args.proxy_host, args.proxy_port)

    os.makedirs(args.out, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    raw_path = os.path.join(args.out, f"bench_{args.label}_{stamp}_raw.csv")
    sum_path = os.path.join(args.out, f"bench_{args.label}_{stamp}_summary.csv")

    print(f"CacheNet benchmark: proxy {PROXY[0]}:{PROXY[1]}, {args.runs} runs per test, label '{args.label}'")
    try:
        one_shot("HEAD", SMALL)
    except OSError as e:
        raise SystemExit(f"Cannot reach the proxy at {PROXY[0]}:{PROXY[1]}: {e}")

    raw_rows, summary = [], []
    for name, cond, fn in TESTS:
        times, sizes = [], []
        for run in range(1, args.runs + 1):
            elapsed, nbytes, tag = fn()
            ms = elapsed * 1000
            mbps = (nbytes * 8 / elapsed / 1e6) if nbytes else ""
            times.append(ms)
            sizes.append(nbytes)
            raw_rows.append({
                "label": args.label, "test": name, "condition": cond, "run": run,
                "time_ms": round(ms, 3), "bytes": nbytes,
                "throughput_mbps": round(mbps, 3) if mbps != "" else "", "x_cache": tag,
            })
        mean = statistics.mean(times)
        sd = statistics.stdev(times) if len(times) > 1 else 0.0
        mean_bytes = statistics.mean(sizes)
        summary.append({
            "label": args.label, "test": name, "condition": cond, "runs": len(times),
            "mean_ms": round(mean, 3), "stdev_ms": round(sd, 3),
            "min_ms": round(min(times), 3), "max_ms": round(max(times), 3),
            "mean_bytes": round(mean_bytes),
            "mean_throughput_mbps": round(mean_bytes * 8 / (mean / 1000) / 1e6, 3) if mean_bytes else "",
        })
        print(f"  {name:<28} {cond:<28} {mean:9.3f} ms  +/- {sd:7.3f}")

    with open(raw_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(raw_rows[0]))
        w.writeheader()
        w.writerows(raw_rows)
    with open(sum_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0]))
        w.writeheader()
        w.writerows(summary)
    print(f"\nRaw data: {raw_path}\nSummary:  {sum_path}")


if __name__ == "__main__":
    main()
