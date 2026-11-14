# CacheNet: CLI Client

CLI client for the CacheNet project: a command-line application that communicates with the caching proxy over TCP sockets using the custom text-based protocol (CNTP/1.0), built using Python's built-in `socket`, `time`, `csv`, and `os` modules.

## Project Layout

```text
CacheNet/
├── client.py                    # CLI client
├── server.py                    # Origin server
├── proxy.py                     # Caching proxy
├── www/
│   └── index.html               # Test web page
└── results/
    ├── performance_results.csv  # Performance test data
    └── performance_comparison.png
```

## Configuration

| **Setting** | **Value** |
| ----------- | --------- |
| Proxy Host | `127.0.0.1` |
| Proxy Port | `9090` |
| Protocol | `CNTP/1.0` |
| Total Performance Requests | `10` |
| Results File | `results/performance_results.csv` |

## Running

Start the origin server in the first terminal:

```bash
python server.py 8080
```

Start the caching proxy in the second terminal:

```bash
python proxy.py
```

Start the CLI client in the third terminal:

```bash
python client.py
```

The client connects to the caching proxy at `127.0.0.1:9090`.

## CLI Menu

The client provides the following options:

| **Option** | **Function** |
| ---------- | ------------ |
| 1 | GET Request |
| 2 | HEAD Request |
| 3 | PURGE Request |
| 4 | Non-Persistent Performance Test |
| 5 | Persistent Performance Test |

## Implementation Details

| **Component** | **Status** |
| -------------- | ---------- |
| TCP socket connection to proxy | Done |
| CNTP/1.0 request formatting | Done |
| GET request | Done and tested |
| HEAD request | Done and tested |
| PURGE request | Done and tested |
| Response header parsing | Done |
| Content-Length based body reading | Done |
| HEAD response body handling | Done |
| X-Cache status extraction | Done |
| Persistent connections | Done and tested |
| Non-persistent connections | Done and tested |
| Automated performance testing | Done |
| CSV performance logging | Done |

## Supported Requests

| **Request** | **Purpose** |
| ----------- | ----------- |
| GET `/index.html` | Retrieves the web page through the proxy |
| HEAD `/index.html` | Retrieves response headers without the body |
| PURGE `/index.html` | Removes the cached entry for the requested resource |

## Response Handling

The client reads responses using the following approach:

1. Reads response headers until `\r\n\r\n` is received.
2. Extracts the `Content-Length` header.
3. Reads exactly the specified number of body bytes.
4. For HEAD requests, reads only the response headers.
5. Extracts the `X-Cache` header to identify cache status.

The client supports the CNTP/1.0 response format and does not rely on external HTTP libraries.

## Cache Status

| **Status** | **Meaning** |
| ---------- | ----------- |
| HIT | Response served from the proxy cache |
| MISS | Requested content was not available in the cache |
| N/A | X-Cache header was not present |

## Performance Testing

The CLI client performs two performance experiments, each containing 10 GET requests.

### 1. Non-Persistent Mode

- Creates a new TCP connection for every request.
- Sends the request with `Connection: close`.
- Measures the request-response time for each request.
- Closes the connection after receiving the response.

### 2. Persistent Mode

- Reuses a single TCP connection for all 10 requests.
- Sends requests using `Connection: keep-alive`.
- Measures the request-response time for each request.
- Closes the connection after all requests are completed.

The cache is warmed up before each performance experiment to make sure the measured requests use cached content.

## Performance Results

| **Metric** | **Non-Persistent** | **Persistent** |
| ---------- | ------------------ | -------------- |
| Total Requests | 10 | 10 |
| Total Time | 0.009638 seconds | 0.003978 seconds |
| Average Response Time | 0.000964 seconds | 0.000398 seconds |
| Cache HIT | 10 | 10 |

The persistent mode achieved approximately 58.7% lower average request-response time compared with non-persistent mode in this test run.

**Note:** The performance timer starts after the TCP socket connection is created. Therefore, the connection establishment time is not included in the measured response time.

## Performance Data

Performance results are stored in:

```text
results/performance_results.csv
```

The CSV file contains the following fields:

- `Mode`
- `Request`
- `Response_Time_Seconds`
- `Cache_Status`

A graphical comparison of persistent and non-persistent performance is available at:

```text
results/performance_comparison.png
```

## Testing Summary

| **Test** | **Result** |
| -------- | ---------- |
| GET Request | Verified: 200 OK |
| GET Cache MISS | Verified |
| GET Cache HIT | Verified |
| HEAD Request | Verified: headers only |
| PURGE Request | Verified: 200 OK |
| GET after PURGE | Verified: MISS |
| Non-Persistent Test | Verified: 10 requests |
| Persistent Test | Verified: 10 requests |
| CSV Logging | Verified |

## Known Limitations

- Performance measurements represent a single test run and may vary between runs.
- TCP connection establishment time is not included in the benchmark.
- Performance tests use cached GET responses after warming up the cache.
- The client is configured for the local proxy address `127.0.0.1:9090`.