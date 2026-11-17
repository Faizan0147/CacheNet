"""Browser UI for CacheNet.

Serves one page on 127.0.0.1:3000 and sends CNTP through the functions
in client.py.

Single machine (development):
    python server.py
    python proxy.py
    python ui.py

Three hosts (run ui.py on the client host H3):
    python ui.py --proxy-host <H2-IP> --origin-host <H1-IP>
"""

import base64
import contextlib
import csv
import io
import json
import os
import socket
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import client

UI_HOST = "127.0.0.1"
UI_PORT = 3000
ORIGIN_HOST = "127.0.0.1"  # only used for the status pill
ORIGIN_PORT = 8080

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CacheNet</title>
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font: 15px/1.45 ui-sans-serif, system-ui, sans-serif;
    color: #1c1917;
    background: #f4f1ea;
  }
  header, main { width: min(960px, calc(100% - 32px)); margin: 0 auto; }
  header { padding: 28px 0 8px; display: flex; justify-content: space-between; gap: 16px; align-items: end; flex-wrap: wrap; }
  h1 { font-size: 22px; margin: 0; letter-spacing: -0.02em; }
  .sub { margin: 4px 0 0; color: #57534e; font-size: 13px; }
  .pills { display: flex; gap: 8px; }
  .pill { font-size: 12px; padding: 4px 8px; border-radius: 999px; background: #e7e5e4; color: #44403c; }
  .pill.up { background: #dcfce7; color: #166534; }
  .pill.down { background: #fee2e2; color: #991b1b; }
  main { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; padding-bottom: 40px; }
  section { background: #fff; border: 1px solid #e7e5e4; border-radius: 10px; padding: 16px; }
  h2 { font-size: 14px; margin: 0 0 12px; }
  label { display: block; font-size: 12px; color: #57534e; margin-bottom: 4px; }
  input { width: 100%; font: inherit; padding: 8px 10px; border: 1px solid #d6d3d1; border-radius: 8px; background: #fff; }
  .paths, .row { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
  button {
    font: inherit; font-size: 13px; padding: 7px 12px; border-radius: 8px;
    border: 1px solid #1c1917; background: #1c1917; color: #fff; cursor: pointer;
  }
  button.alt { background: #fff; color: #1c1917; }
  button:disabled { opacity: 0.5; cursor: wait; }
  .meta { display: flex; gap: 8px; align-items: center; min-height: 28px; margin-bottom: 8px; font-size: 13px; }
  .badge { font-size: 12px; font-weight: 650; padding: 2px 8px; border-radius: 999px; background: #e7e5e4; }
  .badge.HIT { background: #dcfce7; color: #166534; }
  .badge.MISS { background: #ffedd5; color: #9a3412; }
  pre, .frame {
    margin: 0; white-space: pre-wrap; word-break: break-word;
    background: #fafaf9; border-radius: 8px; padding: 10px; max-height: 240px; overflow: auto;
    font: 12px/1.4 ui-monospace, monospace;
  }
  iframe { width: 100%; height: 120px; border: 1px solid #e7e5e4; border-radius: 8px; background: #fff; }
  img.preview { display: block; margin-top: 8px; max-width: 160px; background: #fafaf9; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 4px 6px; border-bottom: 1px solid #f5f5f4; }
  .span { grid-column: 1 / -1; }
  .note { color: #57534e; font-size: 12px; margin: 8px 0 0; }
  @media (max-width: 760px) { main { grid-template-columns: 1fr; } .span { grid-column: auto; } }
</style>
</head>
<body>
<header>
  <div>
    <h1>CacheNet</h1>
    <p class="sub">Browser client. Requests go through client.py to the caching proxy.</p>
  </div>
  <div class="pills">
    <span class="pill" id="origin">Origin</span>
    <span class="pill" id="proxy">Proxy</span>
  </div>
</header>
<main>
  <section>
    <h2>Request</h2>
    <label for="path">Path</label>
    <input id="path" value="/index.html" spellcheck="false">
    <div class="paths" id="paths"></div>
    <div class="row">
      <button data-method="GET">GET</button>
      <button data-method="HEAD" class="alt">HEAD</button>
      <button data-method="PURGE" class="alt">PURGE</button>
    </div>
    <p class="note">Same CNTP request shape as the CLI: Host set to the proxy address, Connection close.</p>
  </section>
  <section>
    <h2>Response</h2>
    <div class="meta" id="meta">Send a request.</div>
    <pre id="headers"></pre>
    <pre id="body"></pre>
    <iframe id="page" hidden title="HTML body"></iframe>
    <img id="image" class="preview" hidden alt="">
  </section>
  <section class="span">
    <h2>Performance</h2>
    <p class="note">Uses client.py: 1 warmup GET, then 10 GETs of /index.html. Results are appended to results/performance_results.csv.</p>
    <div class="row">
      <button id="non" class="alt">Non-persistent</button>
      <button id="per" class="alt">Persistent</button>
    </div>
    <p class="meta" id="bench"></p>
    <table id="table" hidden>
      <thead><tr><th>#</th><th>Time (s)</th><th>X-Cache</th></tr></thead>
      <tbody></tbody>
    </table>
  </section>
</main>
<script>
const pathInput = document.getElementById("path");
const meta = document.getElementById("meta");
const headersEl = document.getElementById("headers");
const bodyEl = document.getElementById("body");
const frame = document.getElementById("page");
const image = document.getElementById("image");
const benchEl = document.getElementById("bench");
const table = document.getElementById("table");

["/index.html", "/about.html", "/notes.txt", "/logo.png", "/large.txt", "*"].forEach((p) => {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "alt";
  b.textContent = p;
  b.addEventListener("click", () => { pathInput.value = p; });
  document.getElementById("paths").appendChild(b);
});

document.querySelectorAll("[data-method]").forEach((btn) => {
  btn.addEventListener("click", () => send(btn.dataset.method));
});
document.getElementById("non").addEventListener("click", () => bench(false));
document.getElementById("per").addEventListener("click", () => bench(true));

function setBusy(on) {
  document.querySelectorAll("button").forEach((b) => { b.disabled = on; });
}

async function send(method) {
  setBusy(true);
  meta.textContent = "Waiting…";
  headersEl.textContent = "";
  bodyEl.textContent = "";
  frame.hidden = true;
  image.hidden = true;
  try {
    const res = await fetch("/api/request", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ method, path: pathInput.value.trim() || "/index.html" })
    });
    const data = await res.json();
    if (!data.ok) {
      meta.textContent = data.error;
      return;
    }
    const badge = data.cache ? `<span class="badge ${data.cache}">${data.cache}</span>` : "";
    meta.innerHTML = `${data.status_line} ${badge} <span>${data.ms} ms</span>`;
    headersEl.textContent = data.headers;
    if (data.body_encoding === "base64") {
      image.hidden = false;
      image.src = `data:${data.content_type};base64,${data.body}`;
      bodyEl.textContent = "";
    } else if ((data.content_type || "").startsWith("text/html") && data.body) {
      frame.hidden = false;
      frame.srcdoc = data.body;
      bodyEl.textContent = data.body;
    } else {
      bodyEl.textContent = data.body || "No response body.";
    }
  } catch (err) {
    meta.textContent = "UI request failed.";
  } finally {
    setBusy(false);
  }
}

async function bench(persistent) {
  setBusy(true);
  benchEl.textContent = "Running 10 requests…";
  table.hidden = true;
  try {
    const res = await fetch("/api/bench", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ persistent })
    });
    const data = await res.json();
    if (!data.ok) {
      benchEl.textContent = data.error;
      return;
    }
    benchEl.textContent = `${data.mode}: ${data.count} requests, total ${data.total}s, average ${data.average}s`;
    const body = table.querySelector("tbody");
    body.replaceChildren();
    data.rows.forEach((row) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${row.Request}</td><td>${row.Response_Time_Seconds}</td><td>${row.Cache_Status}</td>`;
      body.appendChild(tr);
    });
    table.hidden = false;
  } catch (err) {
    benchEl.textContent = "UI request failed.";
  } finally {
    setBusy(false);
  }
}

async function health() {
  try {
    const data = await (await fetch("/api/health")).json();
    for (const name of ["origin", "proxy"]) {
      const el = document.getElementById(name);
      el.textContent = `${name} ${data[name] ? "up" : "down"}`;
      el.className = "pill " + (data[name] ? "up" : "down");
    }
  } catch (err) {
    document.getElementById("origin").textContent = "origin ?";
    document.getElementById("proxy").textContent = "proxy ?";
  }
}
health();
</script>
</body>
</html>
"""


def _port_open(host, port):
    try:
        with socket.create_connection((host, port), timeout=0.4):
            return True
    except OSError:
        return False


def health():
    return {
        "ok": True,
        "origin": _port_open(ORIGIN_HOST, ORIGIN_PORT),
        "proxy": _port_open(client.PROXY_HOST, client.PROXY_PORT),
    }


def _check_path(path):
    if path == "*":
        return
    if not path.startswith("/") or any(c in path for c in "\r\n "):
        raise ValueError("Path must be a single CNTP path, such as /index.html")


def cntp_request(method, path):
    method = method.upper()
    if method not in ("GET", "HEAD", "PURGE"):
        raise ValueError("Method must be GET, HEAD, or PURGE")
    _check_path(path)
    request = (
        f"{method} {path} {client.VERSION}\r\n"
        f"Host: {client.PROXY_HOST}:{client.PROXY_PORT}\r\n"
        "Connection: close\r\n"
        "\r\n"
    )
    sock = socket.create_connection((client.PROXY_HOST, client.PROXY_PORT), timeout=8)
    sock.settimeout(8)
    try:
        start = time.perf_counter()
        sock.sendall(request.encode())
        raw = client.read_one_response(sock, method)
        elapsed = time.perf_counter() - start
    finally:
        sock.close()

    if b"\r\n\r\n" not in raw:
        return {
            "ok": True,
            "status_line": "Incomplete response",
            "headers": raw.decode("latin-1", "replace"),
            "body": "",
            "body_encoding": "text",
            "content_type": "",
            "cache": client.get_cache_status(raw),
            "ms": round(elapsed * 1000, 2),
        }

    header_bytes, body = raw.split(b"\r\n\r\n", 1)
    header_text = header_bytes.decode("latin-1", "replace")
    lines = header_text.split("\r\n")
    content_type = "application/octet-stream"
    for line in lines[1:]:
        if line.lower().startswith("content-type:"):
            content_type = line.split(":", 1)[1].strip()
    text_type = content_type.startswith("text/") or content_type.startswith("application/")
    if text_type:
        shown = body.decode("utf-8", "replace")
        encoding = "text"
    else:
        shown = base64.b64encode(body).decode("ascii")
        encoding = "base64"
    return {
        "ok": True,
        "status_line": lines[0] if lines else "",
        "headers": header_text,
        "body": shown,
        "body_encoding": encoding,
        "content_type": content_type,
        "cache": client.get_cache_status(raw),
        "ms": round(elapsed * 1000, 2),
    }


def run_bench(persistent):
    path = client.CSV_FILE
    before = os.path.getsize(path) if os.path.exists(path) else 0
    with contextlib.redirect_stdout(io.StringIO()):
        client.send_multiple_requests(bool(persistent))
    with open(path, newline="", encoding="utf-8") as handle:
        handle.seek(before)
        added = handle.read()
    fieldnames = ["Mode", "Request", "Response_Time_Seconds", "Cache_Status"]
    if added.startswith("Mode,"):
        rows = list(csv.DictReader(io.StringIO(added)))
    else:
        rows = list(csv.DictReader(io.StringIO(added), fieldnames=fieldnames))
    total = sum(float(row["Response_Time_Seconds"]) for row in rows) if rows else 0
    mode = rows[0]["Mode"] if rows else ("Persistent" if persistent else "Non-Persistent")
    return {
        "ok": True,
        "mode": mode,
        "count": len(rows),
        "total": f"{total:.6f}",
        "average": f"{(total / len(rows)):.6f}" if rows else "0",
        "rows": rows,
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        route = self.path.split("?", 1)[0]
        if route == "/":
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if route == "/api/health":
            self._json(health())
            return
        self.send_error(404)

    def do_POST(self):
        route = self.path.split("?", 1)[0]
        try:
            payload = json.loads(self._body() or b"{}")
        except json.JSONDecodeError:
            self._json({"ok": False, "error": "Request body is not JSON."}, 400)
            return
        try:
            if route == "/api/request":
                self._json(cntp_request(payload.get("method", "GET"), payload.get("path", "/index.html")))
            elif route == "/api/bench":
                self._json(run_bench(payload.get("persistent", False)))
            else:
                self.send_error(404)
        except ValueError as exc:
            self._json({"ok": False, "error": str(exc)}, 400)
        except OSError:
            self._json({"ok": False, "error": f"Proxy is not accepting connections on {client.PROXY_HOST}:{client.PROXY_PORT}."}, 502)

    def _body(self):
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length) if length else b""

    def _json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print("%s %s" % (self.address_string(), fmt % args))


def main():
    global UI_HOST, UI_PORT, ORIGIN_HOST, ORIGIN_PORT
    import argparse

    parser = argparse.ArgumentParser(description="CacheNet browser UI")
    parser.add_argument("--proxy-host", default=client.PROXY_HOST, help="IP of the proxy host (H2)")
    parser.add_argument("--proxy-port", type=int, default=client.PROXY_PORT)
    parser.add_argument("--origin-host", default=ORIGIN_HOST, help="IP of the origin host (H1), for the status pill")
    parser.add_argument("--origin-port", type=int, default=ORIGIN_PORT)
    parser.add_argument("--ui-host", default=UI_HOST, help="address the UI itself listens on")
    parser.add_argument("--ui-port", type=int, default=UI_PORT)
    args = parser.parse_args()
    client.PROXY_HOST, client.PROXY_PORT = args.proxy_host, args.proxy_port
    ORIGIN_HOST, ORIGIN_PORT = args.origin_host, args.origin_port
    UI_HOST, UI_PORT = args.ui_host, args.ui_port

    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    server = ThreadingHTTPServer((UI_HOST, UI_PORT), Handler)
    print(f"CacheNet UI on http://{UI_HOST}:{UI_PORT}")
    print(f"Origin expected on {ORIGIN_HOST}:{ORIGIN_PORT}, proxy on {client.PROXY_HOST}:{client.PROXY_PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nUI stopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
