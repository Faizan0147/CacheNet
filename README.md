# CacheNet: Origin Server (CS-327 CEP, Fall 2026)

Origin server for the CacheNet project: a mini web server that serves files over a custom HTTP-style protocol (CNTP/1.0), built with only Python's built-in `socket` and `threading` modules.



## Project Layout

```
cache-net/
├── server.py          # origin server
├── www/
│   └── index.html     # document root; served for "/"
└── test files         # test_pipeline.py, test_split.py (client-side tests)
```

## Configuration

| Setting   | Value                          |
|-----------|--------------------------------|
| Host      | `127.0.0.1`                    |
| Port      | `9999`                         |
| Doc root  | `www/` (next to `server.py`)   |

## Running

```powershell
python server.py
```

Expected output: `Listening on 127.0.0.1:9999`

## Implementation Progress

| Component            | Status                                    |
|----------------------|-------------------------------------------|
| Socket accept loop   | Done (one thread per client)              |
| `read_request`       | Done (buffered, handles pipelined requests) |
| `parse_request`      | Done (method, path, version, lowercase headers) |
| `build_response`     | Done (status line, headers, body, `Content-Length`) |
| `resolve_path`       | Done (decode, normalize, traversal check, `isfile`) |
| `handle_request`     | GET and HEAD verified; POST 405 and 404 pending verification |
| 400 for malformed    | Implemented; not yet tested                |
| Keep-alive close     | Not implemented (connection stays open)    |
| Idle timeout (408)   | Not implemented                            |

## Response Format

Every response follows this shape:

```
HTTP/1.1 <code> <reason>\r\n
Content-Type: <type>\r\n
Content-Length: <bytes>\r\n
Connection: keep-alive\r\n
[extra headers]\r\n
\r\n
<body>
```

- `Content-Length` is always present and counts body bytes.
- A 405 response includes `Allow: GET, HEAD`.
- HEAD responses contain the same headers as GET, including the real `Content-Length`, with no body.

## Supported Behavior

| Request                      | Response                                  |
|------------------------------|-------------------------------------------|
| `GET /` or `GET /<file>`     | `200 OK` with file contents               |
| `HEAD /` or `HEAD /<file>`   | `200 OK` headers only                     |
| Other methods (e.g. `POST`)  | `405 Method Not Allowed` with `Allow`     |
| Missing file                 | `404 Not Found`                           |
| Malformed request line       | `400 Bad Request`                         |
| Path escaping `www/`         | Treated as not found (`404`)              |

`/` is mapped to `index.html`.

## Testing

With the server running, from a second window:

```powershell
curl.exe -v http://127.0.0.1:9999/
curl.exe -v -I http://127.0.0.1:9999/
curl.exe -v -X POST http://127.0.0.1:9999/
curl.exe -v http://127.0.0.1:9999/missing.html
```

Use `curl.exe` on Windows PowerShell, since `curl` is an alias for a different command.

| Test                | Result        |
|---------------------|---------------|
| GET `/`             | Verified: 200, `Content-Length: 30` |
| HEAD `/`            | Verified: headers only, no hang     |
| POST `/`            | Pending       |
| GET `/missing.html` | Pending       |

## Known Limitations

- Connections are never closed by the server, so keep-alive is effectively unlimited. The idle timeout and 408 response are not yet built.
- `Connection: keep-alive` is always sent, even if the client asks to close.
- Only `index.html` and files under `www/` are served; no directory listings.

## Notes for the Proxy Team

- Parse responses by reading the status line, then headers until the blank line, then exactly `Content-Length` bytes.
- Use `Content-Length` to know where the body ends, since the server does not use chunked encoding.
- Send HEAD when you only need headers; the server still returns the correct `Content-Length`.