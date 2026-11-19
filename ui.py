"""CacheNet Lab: browser UI for the CacheNet experiment.

The browser cannot open raw TCP sockets, so it cannot speak CNTP itself.
ui.py is the adapter on the client host (H3):

    browser --HTTP (localhost:3000)--> ui.py --CNTP/1.0 over TCP--> proxy (H2) --CNTP--> origin (H1)

The small HTTP server below is written directly on sockets too (no http.server
framework), and every CNTP exchange goes through the same socket code as
client.py. Nothing here talks HTTP to the proxy or the origin.

Single machine:
    python server.py
    python proxy.py
    python ui.py                      then open http://127.0.0.1:3000

Three hosts (run ui.py on the client host H3):
    python ui.py --proxy-host <H2-IP> --origin-host <H1-IP>
"""

import argparse
import base64
import contextlib
import csv
import glob
import io
import json
import os
import re
import select
import socket
import struct
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, unquote, urlsplit

import client

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(ROOT, "static")
RESULTS_DIR = os.path.join(ROOT, "results")

UI_HOST = "127.0.0.1"
UI_PORT = 3000
ORIGIN_HOST = "127.0.0.1"  # used only for the origin reachability check
ORIGIN_PORT = 8080
CNTP_TIMEOUT = 8
METHODS = ("GET", "HEAD", "PURGE")
LARGE_PATH = "/large.txt"

MIME = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
        ".json": "application/json", ".ico": "image/x-icon"}

STATUS_TEXT = {200: "OK", 400: "Bad Request", 404: "Not Found", 405: "Method Not Allowed",
               409: "Conflict", 413: "Payload Too Large", 500: "Internal Server Error", 502: "Bad Gateway"}


# ---------------------------------------------------------------- CNTP side (talks to the proxy)

class KeepAlive:
    """One persistent CNTP connection from this UI to the proxy, reused across requests
    in Keep-alive mode. Reconnects when the proxy has closed it (idle 408 or Connection: close)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.sock = None
        self.conn_id = 0
        self.uses = 0

    def drop(self):
        if self.sock:
            with contextlib.suppress(OSError):
                self.sock.close()
        self.sock = None

    def stale(self):
        # A healthy idle connection has nothing to read. Readable means the proxy
        # sent its 408 idle timeout or closed the connection.
        try:
            readable, _, _ = select.select([self.sock], [], [], 0)
            return bool(readable)
        except (OSError, ValueError):
            return True


KEEP = KeepAlive()
CONN_COUNTER = [0]


def _connect():
    start = time.perf_counter()
    # Blocking connect (accurate timing on Windows, see bench.py), then a read timeout.
    sock = socket.create_connection((client.PROXY_HOST, client.PROXY_PORT))
    sock.settimeout(CNTP_TIMEOUT)
    CONN_COUNTER[0] += 1
    return sock, (time.perf_counter() - start) * 1000, CONN_COUNTER[0]


def build_request(method, path, connection):
    return (f"{method} {path} {client.VERSION}\r\n"
            f"Host: {client.PROXY_HOST}:{client.PROXY_PORT}\r\n"
            f"Connection: {connection}\r\n\r\n").encode("latin-1")


def _exchange(sock, raw, method):
    start = time.perf_counter()
    sock.sendall(raw)
    resp = client.read_one_response(sock, method)
    return resp, (time.perf_counter() - start) * 1000


def check_path(path):
    if path == "*":
        return
    if not path.startswith("/") or len(path) > 200 or any(c in path for c in "\r\n \t"):
        raise ValueError("Path must be one CNTP path such as /index.html (no spaces).")


def cntp_request(method, path, mode="close"):
    """Send one CNTP request to the proxy and describe exactly what went out and came back."""
    method = method.upper()
    if method not in METHODS:
        raise ValueError("Method must be GET, HEAD or PURGE.")
    check_path(path)
    if path == "*" and method != "PURGE":
        raise ValueError("* is only valid with PURGE (clear the whole cache).")
    keep = mode == "keep-alive"
    raw = build_request(method, path, "keep-alive" if keep else "close")
    connect_ms, reused, conn_id = 0.0, False, None

    if keep:
        with KEEP.lock:
            if KEEP.sock is not None and KEEP.stale():
                KEEP.drop()
            for attempt in range(2):
                reused = KEEP.sock is not None
                if not reused:
                    KEEP.sock, connect_ms, KEEP.conn_id = _connect()
                    KEEP.uses = 0
                try:
                    resp, xfer_ms = _exchange(KEEP.sock, raw, method)
                    if b"\r\n\r\n" not in resp and reused:
                        raise ConnectionError("stale connection")
                    break
                except OSError:
                    KEEP.drop()
                    if not reused or attempt:
                        raise
            KEEP.uses += 1
            conn_id, uses = KEEP.conn_id, KEEP.uses
            if b"connection: close" in resp.split(b"\r\n\r\n", 1)[0].lower():
                KEEP.drop()
    else:
        sock, connect_ms, conn_id = _connect()
        try:
            resp, xfer_ms = _exchange(sock, raw, method)
        finally:
            sock.close()
        uses = 1

    return describe(method, path, mode, raw, resp, connect_ms, xfer_ms, reused, conn_id, uses)


def describe(method, path, mode, raw, resp, connect_ms, xfer_ms, reused, conn_id, uses):
    base = {"ok": True, "method": method, "path": path, "mode": mode,
            "target": f"{client.PROXY_HOST}:{client.PROXY_PORT}",
            "request_raw": raw.decode("latin-1"), "request_bytes": len(raw),
            "connect_ms": round(connect_ms, 3), "transfer_ms": round(xfer_ms, 3),
            "ms": round(connect_ms + xfer_ms, 2), "reused": reused, "conn_id": conn_id,
            "conn_requests": uses, "time": time.strftime("%H:%M:%S"),
            "cache": client.get_cache_status(resp)}
    if b"\r\n\r\n" not in resp:
        base.update(status=None, status_line="Incomplete response", headers=resp.decode("latin-1", "replace"),
                    header_list=[], body="", body_encoding="text", content_type="", body_bytes=0,
                    response_head_raw=resp.decode("latin-1", "replace"), response_bytes=len(resp))
        return base
    head, body = resp.split(b"\r\n\r\n", 1)
    text = head.decode("latin-1", "replace")
    lines = text.split("\r\n")
    header_list = [[n.strip(), v.strip()] for n, _, v in (l.partition(":") for l in lines[1:])]
    hmap = {n.lower(): v for n, v in header_list}
    parts = lines[0].split(" ", 2)
    ctype = hmap.get("content-type", "")
    textual = ctype.startswith("text/") or ctype in ("application/json",) or (not ctype and body.isascii())
    base.update(
        status=int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None,
        reason=parts[2] if len(parts) > 2 else "",
        status_line=lines[0], headers=text, header_list=header_list,
        content_type=ctype, content_length=hmap.get("content-length"), max_age=hmap.get("max-age"),
        connection_header=hmap.get("connection"),
        body=body.decode("utf-8", "replace") if textual else base64.b64encode(body).decode("ascii"),
        body_encoding="text" if textual else "base64", body_bytes=len(body),
        response_head_raw=text + "\r\n\r\n", response_bytes=len(resp))
    if base["cache"] in ("N/A", "Unknown"):
        base["cache"] = None
    return base


def proxy_stats():
    """Global proxy counters through the proxy's STATS method (CNTP, never forwarded to the origin).
       Also returns the address this host (H3) used for the connection."""
    sock, _, _ = _connect()
    try:
        local = sock.getsockname()
        sock.sendall(build_request("STATS", "*", "close"))
        resp = client.read_one_response(sock, "GET")
    finally:
        sock.close()
    head, _, body = resp.partition(b"\r\n\r\n")
    status = head.split(b" ", 2)[1:2]
    if status != [b"200"]:
        return {"ok": True, "supported": False, "status_line": head.split(b"\r\n", 1)[0].decode("latin-1"),
                "h3": local[0]}
    out = {"ok": True, "supported": True, "entries": [], "h3": local[0]}
    for line in body.decode("latin-1").splitlines():
        name, _, value = line.partition(":")
        value = value.strip()
        if name == "entry":
            m = re.match(r"(\S+) ttl=(\d+) bytes=(\d+)", value)
            if m:
                out["entries"].append({"path": m.group(1), "ttl": int(m.group(2)), "bytes": int(m.group(3))})
        elif name == "entries":
            out["entry_count"] = int(value)
        elif name in ("hits", "misses", "bytes_saved"):
            out[name] = int(value)
        elif name in ("origin", "origin_reachable", "proxy", "client"):
            out[name] = value
    return out


# ---------------------------------------------------------------- host setup and host check

CONFIG_SOURCE = ["default"]
HOST_RE = re.compile(r"^[A-Za-z0-9.\-:]{1,253}$")
LOOPBACK = ("127.", "localhost", "::1")


def _split(addr):
    host, _, port = (addr or "").rpartition(":")
    return host, port


def set_config(p):
    """Point this UI (and the benchmark runners) at a new proxy/origin without restarting."""
    global ORIGIN_HOST, ORIGIN_PORT
    proxy_host, origin_host = str(p.get("proxy_host", "")).strip(), str(p.get("origin_host", "")).strip()
    try:
        proxy_port, origin_port = int(p.get("proxy_port", 9090)), int(p.get("origin_port", 8080))
    except (TypeError, ValueError):
        raise ValueError("Ports must be whole numbers.")
    for label, h in (("Proxy (H2)", proxy_host), ("Origin (H1)", origin_host)):
        if not HOST_RE.match(h):
            raise ValueError(f"{label} address: type an IP such as 192.168.1.20.")
    for label, port in (("Proxy", proxy_port), ("Origin", origin_port)):
        if not 1 <= port <= 65535:
            raise ValueError(f"{label} port must be between 1 and 65535.")
    with KEEP.lock:
        KEEP.drop()  # a keep-alive connection to the old proxy must not be reused
    client.PROXY_HOST, client.PROXY_PORT = proxy_host, proxy_port
    ORIGIN_HOST, ORIGIN_PORT = origin_host, origin_port
    CONFIG_SOURCE[0] = "set in the UI"
    return config()


def host_check():
    """Evidence that client, proxy and origin are three separate hosts, from what each side reports."""
    proxy = tcp_probe(client.PROXY_HOST, client.PROXY_PORT)
    origin = tcp_probe(ORIGIN_HOST, ORIGIN_PORT)
    checks, stats = [], None
    if proxy["reachable"]:
        try:
            stats = proxy_stats()
        except OSError as e:
            proxy["error"] = str(e)
    h3 = stats["h3"] if stats else None
    h2 = _split(stats.get("proxy"))[0] if stats and stats.get("proxy") else client.PROXY_HOST
    up_host, up_port = _split(stats.get("origin")) if stats and stats.get("origin") else (None, None)
    h1 = ORIGIN_HOST

    def add(cid, ok, text, detail=""):
        checks.append({"id": cid, "ok": ok, "text": text, "detail": detail})

    add("proxy", proxy["reachable"] and bool(stats), "Proxy (H2) answers CNTP",
        f"{client.PROXY_HOST}:{client.PROXY_PORT}" + ("" if proxy["reachable"] else f" · {proxy.get('error', 'no answer')}"))
    if stats and not stats.get("supported"):
        add("stats", None, "Proxy does not answer STATS", "Update proxy.py on H2 for the full host check.")
    if stats and stats.get("supported"):
        add("upstream", up_host == ORIGIN_HOST and str(up_port) == str(ORIGIN_PORT),
            "Proxy forwards misses to the origin you entered",
            f"proxy reports origin {up_host}:{up_port}; this UI expects {ORIGIN_HOST}:{ORIGIN_PORT}")
        add("h2h1", stats.get("origin_reachable") == "yes", "Proxy can reach its origin (H2 → H1)",
            f"TCP connect from H2 to {up_host}:{up_port}: {stats.get('origin_reachable')}")
    add("origin", origin["reachable"], "Origin (H1) reachable from this host",
        f"{ORIGIN_HOST}:{ORIGIN_PORT}" + ("" if origin["reachable"] else " · allow TCP 8080 from H3 in H1's firewall (only the top-bar check needs it)"))
    loop = [name for name, ip in (("H3", h3), ("H2", h2), ("H1", h1)) if ip and ip.startswith(LOOPBACK)]
    add("loopback", not loop, "No role runs on loopback (127.0.0.1)",
        "loopback: " + ", ".join(loop) if loop else "every address is a network address")
    ips = [ip for ip in (h3, h2, h1) if ip]
    add("distinct", len(ips) == 3 and len(set(ips)) == 3, "Three different IP addresses",
        f"H3 {h3 or '?'} · H2 {h2 or '?'} · H1 {h1 or '?'}")
    seen = _split(stats.get("client"))[0] if stats and stats.get("client") else None
    if seen and h3:
        add("nat", seen == h3, "Proxy sees this host at the same address",
            f"proxy sees {seen}; this host used {h3}" + ("" if seen == h3 else " (NAT in between?)"))
    required = [c for c in checks if c["id"] in ("proxy", "upstream", "h2h1", "loopback", "distinct")]
    verdict = "three-hosts" if required and all(c["ok"] for c in required) else \
              "local" if loop and len(loop) == 3 else "incomplete"
    return {"ok": True, "verdict": verdict, "hosts": {"h3": h3, "h2": h2, "h1": h1},
            "checks": checks, "checked": time.strftime("%H:%M:%S")}


# ---------------------------------------------------------------- failure lab (client-side faults)

def _raw_exchange(payload, wait=CNTP_TIMEOUT, read_limit=4096):
    """Send raw bytes on a new connection and collect what comes back until the proxy closes or `wait` passes."""
    sock, connect_ms, _ = _connect()
    start = time.perf_counter()
    got, closed = b"", False
    sock.settimeout(wait)
    try:
        if payload:
            sock.sendall(payload)
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                closed = True
                break
            got += chunk
            if b"\r\n\r\n" in got:
                head, _, body = got.partition(b"\r\n\r\n")
                m = re.search(rb"content-length:\s*(\d+)", head, re.I)
                if m and len(body) >= int(m.group(1)) and payload:
                    break
    except socket.timeout:
        pass
    finally:
        sock.close()
    return {"sent": payload.decode("latin-1"), "received": got[:read_limit].decode("latin-1", "replace"),
            "received_bytes": len(got), "closed_by_proxy": closed,
            "elapsed_s": round(time.perf_counter() - start, 2), "connect_ms": round(connect_ms, 2),
            "status_line": got.split(b"\r\n", 1)[0].decode("latin-1", "replace") if got else ""}


def _status(line):
    parts = line.split(" ")
    return int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None


def run_fault(kind, path="/about.html"):
    check_path(path)
    host = f"Host: {client.PROXY_HOST}:{client.PROXY_PORT}\r\n"
    if kind == "idle":
        r = _raw_exchange(b"", wait=25)
        r.update(expected="408 Request Timeout after about 15 s, then the proxy closes the connection",
                 passed=_status(r["status_line"]) == 408 and r["closed_by_proxy"])
    elif kind == "malformed":
        r = _raw_exchange(b"GARBAGE\r\n\r\n")
        r.update(expected="400 Bad Request", passed=_status(r["status_line"]) == 400)
    elif kind == "version":
        r = _raw_exchange(f"GET /index.html HTTP/1.1\r\n{host}\r\n".encode())
        r.update(expected="505 Version Not Supported (only CNTP/1.0 is accepted)", passed=_status(r["status_line"]) == 505)
    elif kind == "method":
        r = _raw_exchange(f"DELETE /index.html CNTP/1.0\r\n{host}Connection: close\r\n\r\n".encode())
        r.update(expected="405 Method Not Allowed with an Allow header",
                 passed=_status(r["status_line"]) == 405 and "Allow:" in r["received"])
    elif kind == "reset":
        cntp_request("PURGE", LARGE_PATH)  # make it a MISS so the proxy is mid-transfer
        sock, connect_ms, _ = _connect()
        req = f"GET {LARGE_PATH} CNTP/1.0\r\n{host}\r\n".encode()
        sock.sendall(req)
        got = sock.recv(1000)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        sock.close()  # linger 0: the OS sends RST instead of FIN
        time.sleep(0.3)
        after = cntp_request("GET", "/index.html")
        r = {"sent": req.decode("latin-1"), "received": got.decode("latin-1", "replace") + "\n…connection reset by client…",
             "received_bytes": len(got), "closed_by_proxy": False, "elapsed_s": 0, "connect_ms": round(connect_ms, 2),
             "status_line": got.split(b"\r\n", 1)[0].decode("latin-1", "replace"),
             "followup": f"GET /index.html straight after: {after.get('status_line')} ({after.get('cache')})",
             "expected": "Client resets mid-body; the proxy logs 'Connection lost' and keeps serving others",
             "passed": after.get("status") == 200}
    elif kind in ("miss", "cached"):
        if kind == "miss":
            cntp_request("PURGE", path)
        start = time.perf_counter()
        res = cntp_request("GET", path if kind == "miss" else "/index.html")
        r = {"sent": res["request_raw"], "received": res.get("response_head_raw", ""), "received_bytes": res.get("response_bytes", 0),
             "closed_by_proxy": True, "elapsed_s": round(time.perf_counter() - start, 2), "connect_ms": res["connect_ms"],
             "status_line": res.get("status_line", ""), "cache": res.get("cache"),
             "expected": "Origin up: 200 MISS. Origin stopped: 502. Origin started with --delay 6: 504 after 5 s"
             if kind == "miss" else "200 HIT while the object is still fresh, even with the origin stopped",
             "passed": None}
    else:
        raise ValueError("Unknown failure test.")
    r.update(ok=True, kind=kind, time=time.strftime("%H:%M:%S"), target=f"{client.PROXY_HOST}:{client.PROXY_PORT}")
    return r


def tcp_probe(host, port):
    start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=0.8):
            return {"host": host, "port": port, "reachable": True,
                    "ms": round((time.perf_counter() - start) * 1000, 2)}
    except OSError as e:
        return {"host": host, "port": port, "reachable": False, "error": e.strerror or str(e)}


def health():
    proxy = tcp_probe(client.PROXY_HOST, client.PROXY_PORT)
    origin = tcp_probe(ORIGIN_HOST, ORIGIN_PORT)
    return {"ok": True, "proxy": proxy["reachable"], "origin": origin["reachable"],
            "detail": {"proxy": proxy, "origin": origin}, "checked": time.strftime("%H:%M:%S")}


def config():
    loops = [h.startswith(LOOPBACK) for h in (client.PROXY_HOST, ORIGIN_HOST)]
    setup = "LOCAL LAB" if all(loops) else "PARTLY LOCAL" if any(loops) else "3-HOST SETUP"
    return {"ok": True, "version": client.VERSION, "ui": f"{UI_HOST}:{UI_PORT}",
            "proxy": {"host": client.PROXY_HOST, "port": client.PROXY_PORT},
            "origin": {"host": ORIGIN_HOST, "port": ORIGIN_PORT},
            "setup": setup, "source": CONFIG_SOURCE[0],
            "python": sys.version.split()[0]}


# ---------------------------------------------------------------- benchmarks

def run_quick_bench(persistent):
    """The existing client.py comparison: 1 warm-up GET, then 10 GETs of /index.html."""
    path = os.path.join(ROOT, client.CSV_FILE)
    before = os.path.getsize(path) if os.path.exists(path) else 0
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with contextlib.redirect_stdout(io.StringIO()):  # main() already chdir'd to ROOT, where CSV_FILE is relative
        client.send_multiple_requests(bool(persistent))
    with open(path, newline="", encoding="utf-8") as handle:
        handle.seek(before)
        added = handle.read()
    fields = ["Mode", "Request", "Response_Time_Seconds", "Cache_Status"]
    rows = list(csv.DictReader(io.StringIO(added), fieldnames=None if added.startswith("Mode,") else fields))
    total = sum(float(r["Response_Time_Seconds"]) for r in rows)
    return {"ok": True, "runner": "client.py", "mode": rows[0]["Mode"] if rows else "",
            "count": len(rows), "total": f"{total:.6f}",
            "average": f"{(total / len(rows)):.6f}" if rows else "0", "rows": rows,
            "file": client.CSV_FILE, "finished": time.strftime("%Y-%m-%d %H:%M:%S")}


FORMAL = {"state": "idle", "lines": [], "label": None, "runs": None, "started": None,
          "finished": None, "files": [], "returncode": None}
FORMAL_LOCK = threading.Lock()


def start_formal(label, runs):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,24}", label or ""):
        raise ValueError("Label: 1-24 letters, digits, - or _ (e.g. wifi, wired).")
    if not (isinstance(runs, int) and 1 <= runs <= 50):
        raise ValueError("Runs must be a whole number from 1 to 50 (R6 asks for at least 5).")
    with FORMAL_LOCK:
        if FORMAL["state"] == "running":
            raise RuntimeError("A benchmark is already running.")
        FORMAL.update(state="running", lines=[], label=label, runs=runs, returncode=None,
                      started=time.strftime("%Y-%m-%d %H:%M:%S"), finished=None, files=[])
    cmd = [sys.executable, "-u", os.path.join(ROOT, "bench.py"), "--proxy-host", client.PROXY_HOST,
           "--proxy-port", str(client.PROXY_PORT), "--runs", str(runs), "--label", label]
    threading.Thread(target=_run_formal, args=(cmd,), daemon=True).start()
    return formal_status()


def _run_formal(cmd):
    try:
        proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace")
        for line in proc.stdout:
            with FORMAL_LOCK:
                FORMAL["lines"].append(line.rstrip())
                m = re.match(r"(Raw data|Summary):\s+(.+)", line.strip())
                if m:
                    FORMAL["files"].append(os.path.basename(m.group(2)))
        proc.wait()
        with FORMAL_LOCK:
            FORMAL.update(state="completed" if proc.returncode == 0 else "failed",
                          returncode=proc.returncode, finished=time.strftime("%Y-%m-%d %H:%M:%S"))
    except Exception as e:  # noqa: BLE001 - report any failure to the page
        with FORMAL_LOCK:
            FORMAL["lines"].append(f"Could not start bench.py: {e}")
            FORMAL.update(state="failed", finished=time.strftime("%Y-%m-%d %H:%M:%S"))


def formal_status():
    with FORMAL_LOCK:
        return {"ok": True, **{k: (list(v) if isinstance(v, list) else v) for k, v in FORMAL.items()}}


def list_results():
    out = []
    for path in sorted(glob.glob(os.path.join(RESULTS_DIR, "bench_*_raw.csv")), reverse=True):
        name = os.path.basename(path)
        m = re.match(r"bench_(.+)_(\d{8})_(\d{6})_raw\.csv$", name)
        if not m:
            continue
        d, t = m.group(2), m.group(3)
        out.append({"id": name, "label": m.group(1),
                    "stamp": f"{d[:4]}-{d[4:6]}-{d[6:]} {t[:2]}:{t[2:4]}:{t[4:]}"})
    return {"ok": True, "datasets": out}


def read_results(ids):
    known = {d["id"]: d for d in list_results()["datasets"]}
    sets = []
    for i in ids:
        if i not in known:
            raise ValueError(f"Unknown dataset {i}")
        tests = {}
        with open(os.path.join(RESULTS_DIR, i), newline="") as f:
            for row in csv.DictReader(f):
                key = (row["test"], row["condition"])
                cell = tests.setdefault(key, {"test": row["test"], "condition": row["condition"],
                                              "ms": [], "bytes": [], "x_cache": []})
                cell["ms"].append(float(row["time_ms"]))
                cell["bytes"].append(int(row["bytes"] or 0))
                cell["x_cache"].append(row.get("x_cache", ""))
        sets.append({**known[i], "tests": list(tests.values())})
    return {"ok": True, "datasets": sets}


# ---------------------------------------------------------------- HTTP side (talks to the browser)

def http_response(status, body, ctype="application/json"):
    head = (f"HTTP/1.1 {status} {STATUS_TEXT.get(status, 'OK')}\r\n"
            f"Content-Type: {ctype}\r\nContent-Length: {len(body)}\r\n"
            "Cache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\n"
            "Connection: close\r\n\r\n")
    return head.encode("latin-1") + body


def json_response(data, status=200):
    return http_response(status, json.dumps(data).encode("utf-8"))


def static_file(url_path):
    rel = unquote(url_path).lstrip("/") or "index.html"
    if rel.startswith("static/"):
        rel = rel[len("static/"):]
    full = os.path.abspath(os.path.join(STATIC_DIR, rel))
    if not full.startswith(STATIC_DIR + os.sep) or not os.path.isfile(full):
        return None
    with open(full, "rb") as f:
        return http_response(200, f.read(), MIME.get(os.path.splitext(full)[1].lower(), "application/octet-stream"))


def route(method, target, body):
    url = urlsplit(target)
    path, query = url.path, parse_qs(url.query)
    try:
        payload = json.loads(body or b"{}") if method == "POST" else {}
    except json.JSONDecodeError:
        return json_response({"ok": False, "error": "Request body is not JSON."}, 400)
    try:
        if method == "GET" and path == "/api/health":
            return json_response(health())
        if method == "GET" and path == "/api/config":
            return json_response(config())
        if method == "POST" and path == "/api/config":
            return json_response(set_config(payload))
        if method == "GET" and path == "/api/hostcheck":
            return json_response(host_check())
        if method == "POST" and path == "/api/fault":
            return json_response(run_fault(payload.get("kind", ""), payload.get("path", "/about.html")))
        if method == "GET" and path == "/api/stats":
            return json_response(proxy_stats())
        if method == "POST" and path == "/api/request":
            return json_response(cntp_request(payload.get("method", "GET"), payload.get("path", "/index.html"),
                                              payload.get("mode", "close")))
        if method == "POST" and path == "/api/bench":
            return json_response(run_quick_bench(payload.get("persistent", False)))
        if path == "/api/benchmark/formal":
            if method == "POST":
                return json_response(start_formal(payload.get("label", ""), payload.get("runs")))
            return json_response(formal_status())
        if method == "GET" and path == "/api/benchmark/results":
            ids = [i for i in query.get("ids", [""])[0].split(",") if i]
            return json_response(read_results(ids) if ids else list_results())
        if method == "GET" and not path.startswith("/api/"):
            resp = static_file(path)
            if resp:
                return resp
        return json_response({"ok": False, "error": "Not found"}, 404)
    except ValueError as e:
        return json_response({"ok": False, "error": str(e)}, 400)
    except RuntimeError as e:
        return json_response({"ok": False, "error": str(e)}, 409)
    except OSError as e:
        return json_response({"ok": False, "error": f"Proxy at {client.PROXY_HOST}:{client.PROXY_PORT} "
                              f"did not answer: {e.strerror or e}", "unreachable": True}, 502)


def serve_browser(conn):
    """One HTTP/1.1 request from the browser, then close."""
    with conn:
        conn.settimeout(10)
        try:
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(65536)
                if not chunk or len(data) > 65536:
                    return
                data += chunk
            head, body = data.split(b"\r\n\r\n", 1)
            lines = head.decode("latin-1").split("\r\n")
            parts = lines[0].split(" ")
            if len(parts) != 3:
                conn.sendall(json_response({"ok": False, "error": "Bad request"}, 400))
                return
            method, target, _ = parts
            headers = {n.strip().lower(): v.strip() for n, _, v in (l.partition(":") for l in lines[1:])}
            length = int(headers.get("content-length", "0") or 0)
            if length > 1_000_000:
                conn.sendall(json_response({"ok": False, "error": "Body too large"}, 413))
                return
            while len(body) < length:
                chunk = conn.recv(65536)
                if not chunk:
                    return
                body += chunk
            conn.sendall(route(method, target, body[:length]))
        except (OSError, ValueError):
            pass


def main():
    global UI_HOST, UI_PORT, ORIGIN_HOST, ORIGIN_PORT
    parser = argparse.ArgumentParser(description="CacheNet Lab browser UI")
    parser.add_argument("--proxy-host", default=client.PROXY_HOST, help="IP of the proxy host (H2)")
    parser.add_argument("--proxy-port", type=int, default=client.PROXY_PORT)
    parser.add_argument("--origin-host", default=ORIGIN_HOST, help="IP of the origin host (H1), for the reachability check")
    parser.add_argument("--origin-port", type=int, default=ORIGIN_PORT)
    parser.add_argument("--ui-host", default=UI_HOST, help="address the UI listens on (keep 127.0.0.1)")
    parser.add_argument("--ui-port", type=int, default=UI_PORT)
    args = parser.parse_args()
    client.PROXY_HOST, client.PROXY_PORT = args.proxy_host, args.proxy_port
    ORIGIN_HOST, ORIGIN_PORT = args.origin_host, args.origin_port
    UI_HOST, UI_PORT = args.ui_host, args.ui_port
    if (args.proxy_host, args.origin_host) != ("127.0.0.1", "127.0.0.1"):
        CONFIG_SOURCE[0] = "command line"
    os.chdir(ROOT)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((UI_HOST, UI_PORT))
        server.listen()
        server.settimeout(1)  # wake up every second so Ctrl+C works on Windows
        print(f"CacheNet Lab on http://{UI_HOST}:{UI_PORT}")
        print(f"Proxy {client.PROXY_HOST}:{client.PROXY_PORT}, origin check {ORIGIN_HOST}:{ORIGIN_PORT}")
        if client.PROXY_HOST in ("127.0.0.1", "localhost"):
            print("WARNING: proxy is 127.0.0.1 (this machine). For a 3-host run pass --proxy-host <H2-IP>.")
        try:
            while True:
                try:
                    conn, _ = server.accept()
                    conn.settimeout(None)
                    threading.Thread(target=serve_browser, args=(conn,), daemon=True).start()
                except socket.timeout:
                    pass
        except KeyboardInterrupt:
            print("\nUI stopped")
        finally:
            KEEP.drop()


if __name__ == "__main__":
    main()
