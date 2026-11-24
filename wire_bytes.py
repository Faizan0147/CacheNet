"""Measure what each fetch really costs on the wire (frames and bytes), for Section 7 and R6.

Run on the client host (H3) with Wireshark's tshark installed:

    python wire_bytes.py --proxy-host <H2-IP> --iface Wi-Fi --runs 5

tshark captures client<->proxy traffic while this script runs each scenario --runs times:
  page, persistent       : 4 objects on one TCP connection (warm cache)
  page, non-persistent   : 4 objects, a new TCP connection per object (warm cache)
  large.txt              : one ~200 KB object on its own connection (warm cache)
  index.html             : one small object on its own connection (warm cache)

Only connections opened by this script are counted (matched by local port), so other
traffic to the proxy, such as ui.py's status checks, does not pollute the numbers.
Frame bytes are as captured on this host (Ethernet II framing as Npcap reports it).
Writes results/wire_bytes_<time>.csv with one row per run.
"""

import argparse
import csv
import os
import subprocess
import time
from collections import defaultdict

import bench

TSHARK = r"C:\Program Files\Wireshark\tshark.exe"
PAGE = bench.PAGE


def fetch_on(sock, path, keep_alive):
    bench.send(sock, "GET", path, keep_alive=keep_alive)
    return bench.recv_response(sock, "GET")


def page_persistent():
    s = bench.connect()
    ports = [s.getsockname()[1]]
    for i, p in enumerate(PAGE):
        fetch_on(s, p, keep_alive=i < len(PAGE) - 1)
    s.close()
    return ports


def page_non_persistent():
    ports = []
    for p in PAGE:
        s = bench.connect()
        ports.append(s.getsockname()[1])
        fetch_on(s, p, keep_alive=False)
        s.close()
    return ports


def single(path):
    def run():
        s = bench.connect()
        port = s.getsockname()[1]
        fetch_on(s, path, keep_alive=False)
        s.close()
        return [port]
    return run


SCENARIOS = [
    ("page, persistent", page_persistent),
    ("page, non-persistent", page_non_persistent),
    ("object /large.txt", single("/large.txt")),
    ("object /index.html", single("/index.html")),
]


def main():
    ap = argparse.ArgumentParser(description="CacheNet on-wire byte counter")
    ap.add_argument("--proxy-host", required=True)
    ap.add_argument("--proxy-port", type=int, default=9090)
    ap.add_argument("--iface", default="Wi-Fi", help="tshark interface name or number")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--tshark", default=TSHARK)
    ap.add_argument("--out", default="results")
    args = ap.parse_args()

    bench.PROXY = (args.proxy_host, args.proxy_port)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    os.makedirs(args.out, exist_ok=True)
    pcap = os.path.join(args.out, f"wire_bytes_{stamp}.pcapng")

    bench.warm(PAGE + ["/large.txt"])  # warm cache, so every scenario is a HIT

    duration = 15 + 3 * args.runs
    cap = subprocess.Popen([args.tshark, "-i", args.iface, "-q", "-w", pcap, "-a", f"duration:{duration}",
                            "-f", f"tcp port {args.proxy_port} and host {args.proxy_host}"])
    time.sleep(5)  # tshark needs a few seconds before it captures anything
    started = time.time()

    owners = {}  # local port -> (scenario, run)
    for name, fn in SCENARIOS:
        for run in range(1, args.runs + 1):
            for port in fn():
                owners[port] = (name, run)
            time.sleep(0.3)
    if time.time() - started > duration - 6:
        print("warning: scenarios ran close to the capture limit; raise duration")
    cap.wait()

    out = subprocess.run([args.tshark, "-r", pcap, "-T", "fields", "-E", "separator=,",
                          "-e", "tcp.srcport", "-e", "tcp.dstport", "-e", "frame.len",
                          "-e", "tcp.len", "-e", "tcp.flags.syn", "-e", "tcp.flags.ack", "-e", "tcp.flags.fin"],
                         capture_output=True, text=True, check=True).stdout

    acc = defaultdict(lambda: defaultdict(int))
    for line in out.splitlines():
        sp, dp, flen, tlen, syn, ack, fin = line.split(",")
        sp, dp = int(sp), int(dp)
        local = sp if dp == args.proxy_port else dp
        if local not in owners:
            continue
        a = acc[owners[local]]
        a["frames"] += 1
        a["bytes"] += int(flen)
        a["payload"] += int(tlen or 0)
        if int(tlen or 0) == 0:
            a["control_frames"] += 1
            a["control_bytes"] += int(flen)
        if syn in ("1", "True") and ack in ("0", "False"):
            a["connections"] += 1
        a["up_bytes" if dp == args.proxy_port else "down_bytes"] += int(flen)

    path = os.path.join(args.out, f"wire_bytes_{stamp}.csv")
    fields = ["frames", "bytes", "payload", "control_frames", "control_bytes", "connections", "up_bytes", "down_bytes"]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scenario", "run"] + fields)
        for name, _ in SCENARIOS:
            for run in range(1, args.runs + 1):
                a = acc[(name, run)]
                w.writerow([name, run] + [a[k] for k in fields])
                print(f"{name:22s} run {run}: {a['connections']} conn, {a['frames']:4d} frames, "
                      f"{a['bytes']:7d} B on wire, {a['payload']:7d} B CNTP")
    print("wrote", path, "and", pcap)


if __name__ == "__main__":
    main()
