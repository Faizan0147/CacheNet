# CacheNet (CS-327 CEP, Fall 2026)

A mini web server with a caching proxy, talking a custom HTTP-style protocol (CNTP/1.0) directly over TCP sockets. Built with Python 3 using only the standard library (`socket`, `threading`, `time`; no HTTP libraries or frameworks).

```
Client (H3)  ──CNTP──►  Caching proxy (H2 :9090)  ──CNTP──►  Origin server (H1 :8080)
             ◄─────────  X-Cache: HIT / MISS      ◄─────────  Max-Age: <ttl>
```

| Member | Role | Files | Section |
|---|---|---|---|
| 1. Syed Faizan | Origin server | `server.py`, `www/` | [Member 1](#member-1--origin-server-serverpy) |
| 2. Rameen Sohail | Caching proxy | `proxy.py`, `test_files/test_proxy.py` | [Member 2](#member-2--caching-proxy-proxypy) |
| 3. Muhammad Usman Shahzad | CLI client | *(pending)* | [Member 3](#member-3--cli-client-pending) |
| 4. Syed Aayan Ali | *(fill in)* | | |

## Project Layout

```
CacheNet/
├── server.py              # Member 1: origin server (port 8080)
├── proxy.py               # Member 2: caching proxy (port 9090)
├── www/                   # Member 1: document root
│   ├── index.html         # served for "/"
│   ├── about.html
│   ├── notes.txt          # text object
│   ├── logo.png           # image object (179 B)
│   └── large.txt          # ~200 KB object for throughput / hit-vs-miss timing
└── test_files/
    ├── test_pipeline.py   # Member 1: two pipelined requests to the origin
    ├── test_split.py      # Member 1: request split across two packets
    ├── scratch.py         # Member 1: scratch checks
    └── test_proxy.py      # Member 2: automated proxy test suite (24 checks)
```

---

# Shared: Protocol and Running

## Protocol (CNTP/1.0)

Text-based, HTTP-style messages over TCP. Each message is a start line, header lines ending in CRLF, a blank line, and an optional body whose length is given by `Content-Length`. There is no chunked encoding, so `Content-Length` is the only way the receiver knows where the body ends. The version string on the wire stays `HTTP/1.1` so `curl.exe` can be used for testing.

```
GET /index.html HTTP/1.1\r\n            HTTP/1.1 200 OK\r\n
Host: 192.168.1.20:9090\r\n             Content-Type: text/html\r\n
Connection: keep-alive\r\n              Content-Length: 30\r\n
\r\n                                     Connection: keep-alive\r\n
                                         Max-Age: 30\r\n
                                         X-Cache: HIT\r\n
                                         \r\n
                                         <h1>Hello from CacheNet</h1>
```

| Method | Handled by | Meaning |
|---|---|---|
| `GET` | proxy, then origin | Fetch an object |
| `HEAD` | proxy, then origin | Headers only, with the real `Content-Length` and no body |
| `PURGE` | proxy only | Remove `/path` from the cache, or everything with `PURGE *` |

| Header | Set by | Meaning |
|---|---|---|
| `Host` | client / proxy | Target host |
| `Content-Length` | everyone | Body size in bytes (always present on responses) |
| `Content-Type` | origin | Chosen by file extension |
| `Connection` | everyone | `keep-alive` (persistent, the default) or `close` (non-persistent) |
| `Max-Age` | origin | How long the proxy may cache the object, in seconds |
| `X-Cache` | proxy | `HIT` (served from cache) or `MISS` (fetched from origin) |
| `Allow` | origin / proxy | Sent with 405 |

| Code | Sent by | When |
|---|---|---|
| 200 OK | both | Success; also a successful PURGE |
| 400 Bad Request | both | Malformed request line or header |
| 404 Not Found | origin; proxy for PURGE | File missing or outside `www/`; PURGE of a path that isn't cached |
| 405 Method Not Allowed | both | Origin allows `GET, HEAD`; proxy allows `GET, HEAD, PURGE` |
| 408 Request Timeout | both | Client idle for 15 s; the connection is then closed |
| 502 Bad Gateway | proxy | Origin unreachable, closed early, or sent a malformed or incomplete response |
| 504 Gateway Timeout | proxy | Origin didn't answer within 5 s |

## Running

**One machine:**
```powershell
python server.py        # Listening on 0.0.0.0:8080
python proxy.py         # Proxy listening on 0.0.0.0:9090, origin 127.0.0.1:8080, default TTL 30s
```

**Three hosts, as in the proposal:**

| Host | Role | IP (example) | Command |
|---|---|---|---|
| H1 | Origin | 192.168.1.10 | `python server.py` |
| H2 | Proxy | 192.168.1.20 | `python proxy.py --origin-host 192.168.1.10` |
| H3 | Client | 192.168.1.30 | connects to `192.168.1.20:9090` |

Use `ipconfig` / `ip addr` to get the real addresses, and allow TCP ports 8080 (H1) and 9090 (H2) through the firewall.

> **Port 8080 already in use?** On some PCs a local Apache (XAMPP/WAMP) holds 8080 and answers instead of `server.py`. If `server.py` fails with `WinError 10013`, or a response has `Server: Apache`, stop that service or change `PORT` in `server.py` and start the proxy with the matching `--origin-port`.

---

# Member 1 — Origin Server (`server.py`)

Serves files from `www/`. Each client gets its own thread.

## Configuration

| Setting | Value |
|---|---|
| Host | `0.0.0.0` (all interfaces) |
| Port | `8080` |
| `MAX_AGE` | `30` s, sent as the `Max-Age` header on 200 responses |
| `IDLE_TIMEOUT` | `15` s, then 408 and close |
| Doc root | `www/` next to `server.py` |

## Status

| Component | Status |
|---|---|
| Socket accept loop | Done (one thread per client) |
| `read_requests` | Done (buffered, handles pipelined and split requests) |
| `parse_request` | Done (method, path, version, lowercase headers) |
| `build_response` | Done (status line, headers, body, `Content-Length`, `Connection`) |
| `resolve_path` | Done (decode, normalize, traversal check, `isfile`) |
| GET / HEAD | Done |
| 400 / 404 / 405 | Done |
| `Max-Age` header | Done |
| Content-Type by extension | Done (`.html`, `.txt`, `.png`, `.jpg`, otherwise `application/octet-stream`) |
| `Connection: close` honored | Done |
| Idle timeout (408) | Done |
| Client reset mid-transfer | Handled (logged as `Connection lost`) |

`/` is mapped to `index.html`. Paths that escape `www/` are treated as not found (404). HEAD returns the same headers as GET, including the real `Content-Length`, with no body.

## Changes made to Member 1's code by Member 2

These were needed so the origin works with the proxy and matches the proposal:

| # | Change | Reason |
|---|---|---|
| A1 | Port `9999` → `8080` (also in the README and the two test scripts) | Proposal, section 4 |
| A2 | `Max-Age: 30` on 200 responses (`MAX_AGE` constant) | Proposal, section 2: the TTL is set by the origin |
| A3 | `DOC_ROOT` set relative to `server.py`, not the folder it's started from | Previously, starting it from another folder gave 404 for everything |
| A4 | `Content-Type` chosen by file extension | The proposal serves HTML, text and images |
| A5 | `Connection: close` honored: reply with `close`, then close the connection | Persistent vs. non-persistent comparison |
| A6 | Idle timeout: 408 after 15 s, then close | Proposal R7 |
| A7 | `HOST = '0.0.0.0'` | So H2 can reach H1 |
| A8 | 404 reason `Not Found`, no `Allow` header | Correct status line |
| A9 | `Allow: GET, HEAD` (with the space) | Standard format |
| A10 | Catch `ConnectionResetError` / `ConnectionAbortedError` / `BrokenPipeError` | A client dropping mid-transfer no longer crashes its thread |
| A12 | Added `about.html`, `notes.txt`, `logo.png`, `large.txt` to `www/` | Text and image objects; page fetch time; `test_pipeline.py` requests `/about.html` |

## Testing (origin directly)

```powershell
curl.exe -v http://127.0.0.1:8080/              # 200, Max-Age: 30
curl.exe -v -I http://127.0.0.1:8080/logo.png   # HEAD, Content-Type: image/png
curl.exe -v -X POST http://127.0.0.1:8080/      # 405, Allow: GET, HEAD
curl.exe -v http://127.0.0.1:8080/missing.html  # 404
```
On Windows use `curl.exe`, since `curl` in PowerShell is a different command. `test_files/test_pipeline.py` and `test_files/test_split.py` test pipelined and split requests.

| Test | Result |
|---|---|
| GET `/`, `/notes.txt` | 200 with correct `Content-Type` and `Max-Age: 30` |
| HEAD `/logo.png` | Headers only, `image/png` |
| GET `/missing` | 404 `Not Found` |
| POST `/` | 405, `Allow: GET, HEAD` |
| `Connection: close` | Reply says `close`, then the connection is closed |
| Idle connection | 408 after 15 s, then closed |
| Client reset | Logged `Connection lost`, no crash |

## Known Limitations

- On Windows, `server.py` doesn't stop on Ctrl+C while it's waiting for connections, because its blocking `accept()` isn't interrupted. Use Ctrl+Break or close the window. (The fix would be `server.settimeout(1)` plus `except socket.timeout: pass`, as in `proxy.py`.)
- No directory listings; only files under `www/` are served.

---

# Member 2 — Caching Proxy (`proxy.py`)

Sits between the client and the origin, caches responses and manages both connections.

## Configuration

| Setting | Default | Command-line flag |
|---|---|---|
| Listen address | `0.0.0.0` | |
| Port | `9090` | `--port` |
| Origin | `127.0.0.1:8080` | `--origin-host`, `--origin-port` |
| `DEFAULT_TTL` | `30` s, used only when the origin sends no `Max-Age` | `--ttl` |
| `IDLE_TIMEOUT` | `15` s, then 408 to the client | |
| `ORIGIN_TIMEOUT` | `5` s, then 504 | |

## Request Forwarding
1. Read the request from the client and parse it (400 if malformed).
2. **PURGE:** handled locally (see below). It never reaches the origin.
3. Any method other than GET, HEAD or PURGE: 405 with `Allow: GET, HEAD, PURGE`.
4. **Cache lookup:** a fresh entry is a **HIT**.
5. On a **MISS**, forward to the origin with its own `Host` header, and read the status line, the headers and exactly `Content-Length` body bytes (none for HEAD).
6. Origin failures:
   - connection refused → **502**
   - closed early or incomplete body → **502**
   - malformed response → **502**
   - no answer within 5 s → **504**

## Cache Lookup
- A dict keyed by path, holding `{status, reason, headers, body, expires}` and protected by a `threading.Lock`, since each client has its own thread.
- `/` and `/index.html` share one entry.
- Only GET responses with status 200 are cached; errors are always passed through.
- Every response gets `X-Cache: HIT` or `X-Cache: MISS`. A HEAD hit returns headers only.

## TTL Expiry
- `expires = now + Max-Age` from the origin, or `--ttl` if the header is missing. `Max-Age: 0` means don't cache.
- Expired entries are deleted the next time they're looked up (logged as `Expired: /path`), so the request becomes a MISS and is fetched again.

## PURGE
- `PURGE /path` returns **200** `Purged` if the entry was removed, or **404** `Not cached` if it wasn't cached.
- `PURGE *` clears the whole cache, which is useful between measurement runs.

## Connection Management
- **Client to proxy:** persistent by default and pipelining works. `Connection: close` is honored. A client idle for 15 s gets a 408 and is closed. A client that resets the connection doesn't crash the proxy.
- **Proxy to origin:** each client thread keeps one origin connection and reuses it. If the origin has closed it while idle (EOF, reset or a 408), the proxy opens a new connection and retries once.
- The `Connection` header is replaced on each hop, since it describes that hop only.

## Logging and Stats
```
127.0.0.1:63261 GET / MISS 200 17.28 ms
127.0.0.1:63263 GET / HIT 200 0.17 ms
Expired: /index.html
```
Press **Ctrl+C** to stop the proxy and print a summary:
```
Hits: 2  Misses: 3  Hit ratio: 40.0%  Bytes saved: 200010
```
`Bytes saved` is the total body bytes served from the cache instead of fetched from the origin.

## Testing

**Automated tests.** This starts its own origin, proxy and fake origins on spare ports (8180–8189, 9190), so nothing else needs to be running:
```powershell
python test_files/test_proxy.py
```
Last result: **24/24 passed**

| Area | Checks |
|---|---|
| Cache | First GET is a MISS; `/` and `/index.html` share an entry (HIT); a HEAD hit has no body; after `Max-Age` it's a MISS again |
| PURGE | Cached path → 200; uncached path → 404; GET after PURGE is a MISS; `PURGE *` clears everything |
| Requests | POST → 405 with `Allow`; 404 isn't cached; malformed request → 400; 200 KB body arrives complete; `Content-Type` passed through |
| Connections | `Connection: close` honored; 3 pipelined requests get 3 responses; a stale origin connection is replaced; 5 concurrent clients; idle client → 408 and close; proxy survives a client reset |
| Origin failures | Origin down → 502; slow origin → 504; incomplete body → 502; no `Max-Age` falls back to `--ttl` |

**Manual tests with curl:**
```powershell
curl.exe -v http://127.0.0.1:9090/              # X-Cache: MISS, then run again for HIT
curl.exe -v -I http://127.0.0.1:9090/           # HEAD
curl.exe -v -X PURGE http://127.0.0.1:9090/     # remove from cache
curl.exe -v -X POST http://127.0.0.1:9090/      # 405
```

**Ctrl+C summary:** verified. After 5 requests (2 hits) the proxy printed `Hits: 2  Misses: 3  Hit ratio: 40.0%  Bytes saved: 200010` and exited with code 0.

## Known Limitations
- On a cache hit, `Max-Age` shows the original TTL, not the time remaining.
- The cache has no size limit; entries are removed only by TTL or PURGE.
- Request bodies aren't supported (GET, HEAD and PURGE don't need them).
- The proxy forwards to a single, fixed origin.

---

# Member 3 — CLI Client *(pending)*

Not implemented yet. What the client must do to work with the proxy:
- Connect to the **proxy** (`<H2>:9090`), not the origin.
- Send `GET`, `HEAD` or `PURGE` with a `Host` header. Add `Connection: close` for non-persistent mode; leave it out (or send `keep-alive`) for persistent mode.
- Read a response as: status line, headers up to the blank line, then exactly `Content-Length` bytes. Don't read a body for HEAD.
- In persistent mode, send the next request on the same socket. The proxy closes it after 15 s idle (408).
- Record `X-Cache` and the timing for each request (`time.perf_counter()`).

---

# Evaluation Plan (team, to do)

| Requirement | What to measure | How |
|---|---|---|
| R6 RTT | Time per request, hit vs. miss | Client timing; the proxy log also gives a per-request time |
| R6 Throughput | Bytes/s for `large.txt`, hit vs. miss | `Content-Length` divided by transfer time |
| R6 Page fetch time | Fetch `index.html` + `about.html` + `notes.txt` + `logo.png`, persistent vs. non-persistent | Client in both modes |
| Repetition | Each measurement 5 or more times | Report mean and spread; plot with Matplotlib |
| R7 Failures | Origin down (502), client disconnect, idle timeout (408) | Covered by `test_proxy.py`; capture in Wireshark |
| TTL tension | Hit ratio vs. freshness for TTL 0 / 5 / 30 / 120 s | Change `MAX_AGE` (or `--ttl`); read hit ratio from the proxy's Ctrl+C summary |
| Sustainability | Bytes saved per hit, scaled to a realistic user population | `Bytes saved` from the proxy's Ctrl+C summary |
| Wireshark | Message framing, TCP handshakes (1 per page when persistent, 1 per object when not) | Filter `tcp.port == 9090 \|\| tcp.port == 8080` |
