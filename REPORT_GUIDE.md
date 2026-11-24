# CacheNet report: handover guide

All data is collected. This guide says what goes in each section of the report, where its material is in this repo, and what is still missing. The section order is the one required by Section 9 of the problem description.

## Rules for the report (Sections 10–11 of the problem description)

- **Length:** at most 10 pages, not counting the rubric page, the references and the code appendix.
- **Font:** Times New Roman, 12 pt for body text and 14 pt for headings.
- **Title page:** the provided rubric, with every name and roll number filled in. No separate title page.
- **Must appear somewhere:** the network diagram, the IP addressing plan, the protocol message formats, and the configuration of each host.
- **Required appendix:** a declaration of AI assistance, saying what was used and for which part. Claude (Claude Code) was used for the UI, the benchmark and analysis scripts, and the R6/Section 6/Section 7 calculations. Each member should add their own use.
- **Submission:** each member uploads the PDF as `CS24XXX.pdf` (their own roll number) from their own account, and the group also hands in a printed copy.

## Still to do before writing

| Item | Needed for | How |
|---|---|---|
| Export the **network diagram** as a PNG | R3 | Open `evidence/network_diagram_R3.drawio` at app.diagrams.net (File → Open from device), then use File → Export as → PNG and paste the image into the report. |
| Restore H1 | Demo | Restart `python server.py` with no `--max-age`, so the default of 60 s is used again. |
| Proxy and server console logs | R7 | Copy `evidence\proxy.log` from H2 (written by `Tee-Object` when the proxy was started) and any saved server log from H1 into `evidence/`. They show the proxy's side of each failure, e.g. "Connection lost" and the 502/504 lines. |
| Remove the ping firewall rule | After the demo | On H1 and H2: `Remove-NetFirewallRule -DisplayName "CacheNet ping"` |
| Contributions table | Report | Fill in and get it signed by all 4 members. |

## Hosts (for R3 and the IP plan)

| Host | Role | IP | Port | Network |
|---|---|---|---|---|
| H1 | Origin server (`server.py`) | 192.168.1.103 | 8080 | Wi-Fi, 192.168.1.0/24, gateway 192.168.1.1 |
| H2 | Caching proxy (`proxy.py --origin-host 192.168.1.103`) | 192.168.1.63 | 9090 | Wi-Fi, same subnet |
| H3 | Client (`client.py`, `ui.py`, `bench.py`) | 192.168.1.11 | ephemeral | Wi-Fi, 2.4 GHz 802.11n, 72.2 Mbps |

---

## Section by section

### 1. Introduction and the option selected
Option C: mini web server with a caching proxy. Copy the application paragraph from the proposal and add 2–3 sentences on what was built: three hosts, CNTP/1.0 over TCP, a cache with a TTL, persistent and non-persistent connection modes.

### 2. Protocol specification (R1)
- **Source:** `README.md`, section "Protocol (CNTP/1.0)", plus the status codes table.
- **Must include:**
  - the message types (GET, HEAD, PURGE, STATS)
  - the exact request and response format, with every header field and its meaning (Host, Content-Length, Content-Type, Connection, Max-Age, X-Cache)
  - the legal exchange order (request → response; keep-alive allows more requests; 15 s idle → 408 and close)
  - what each side does on receipt of each message
  - every status code (200, 400, 404, 405, 408, 502, 504, 505) and when it is sent
- **Test for this section:** could another group implement CNTP from it without seeing our code?

### 3. System and deployment architecture (R3)
The network diagram (`evidence/network_diagram_R3.drawio`), the hosts table above, and the `ipconfig` screenshots: `evidence/H1(server)_R3.png`, `evidence/H2(proxy)_R3.jpg` and `evidence/H3(client)_R3.png`. Add the start-up screenshots `evidence/server_R3.png` and `evidence/proxy_R3.png`, and one request shown at all three hosts: `GET1_R3.png`, `GET2_R3.png`, `GET_proxy_R3.png` and `GET_server_R3.png`.

### 4. Implementation notes (R2, R4)
- **R2:** Python 3 using only `socket`, `threading` and `time`, with no HTTP library. The cache is a dict with per-entry expiry. There is one thread per client connection, and the proxy reuses one origin connection per client connection.
- **R4: TCP for every message.** The justification must cover all four requirements from Lecture 04:
  - **Reliable data transfer:** Content-Length framing breaks if a single byte is lost or reordered, and cached objects would be stored corrupted.
  - **Throughput:** objects of up to 200 KB need TCP's flow and congestion control. We measured 15.2 Mbps on a cache HIT.
  - **Timing:** moderate needs. The cost of TCP is the handshake (≈ 1 RTT ≈ 7 ms), which persistent mode pays only once per page.
  - **Security:** none in either TCP or UDP. TLS would require TCP, so TCP keeps that option open.
- **What we would lose with UDP:** we would have to write our own retransmission, ordering and reassembly for 200 KB objects (about 137 datagrams). A lost datagram would silently corrupt a cached object that is then served to every client. UDP is connectionless, so there would be no connection to keep alive, and the persistent vs non-persistent comparison would not exist.

### 5. Packet capture and encapsulation (R5)
- **Evidence:** `evidence/Packet1_R5.png`, `Packet2_R5.png` and `stream_R5.png`.
- **Annotate one packet with four layers:**
  - **Ethernet / 802.11 frame header:** source and destination MAC
  - **IP datagram:** source and destination IP, e.g. 192.168.1.11 → 192.168.1.63
  - **TCP segment:** ports, e.g. ephemeral → 9090
  - **CNTP message in the payload:** e.g. `GET /index.html CNTP/1.0`
- Relate it to the Lecture 03 model: each layer adds its own header in front of the one above.
- **Extra evidence, if useful:** `results/wire_bytes_20261124_162110.pcapng` shows 1 handshake per page in persistent mode and 4 in non-persistent mode.

### 6. Performance measurement (R6)
- **Source:** `results/R6_calculations.md`, sections 1–5. Every number and the delay-model explanation are already written there; copy and condense them.
- **Graphs** in `results/plots/` (R6 needs at least one; use 2–3):
  - `r6_page_fetch.png`: persistent vs non-persistent. This is the main comparison for Option C.
  - `r6_small_object_miss_hit.png` or `r6_large_object_time.png`: cache MISS vs HIT.
  - `r6_throughput.png` and `r6_rtt.png` if there is room.
- **Required content:**
  - RTT: 7.00 ± 2.09 ms
  - throughput: 15.24 vs 6.33 Mbps
  - page fetch time: the representative operation
  - every measurement repeated 10 times and reported as mean ± SD
  - at least 2 conditions compared, as a table and a graph
  - an explanation using d_nodal = d_proc + d_queue + d_trans + d_prop. This is already worked out in section 5 of the calculations file.
- **Be upfront about two things:**
  - RTT is the TCP connect time (7.0 ms). ICMP ping (`results/ping_H3_20261124.csv`) agrees when the radios are awake (median 6 ms), but 29 of 80 pings took 64–86 ms because an idle laptop's Wi-Fi was in power-save mode. That is queueing at the access point; the explanation is in section 2 of the calculations file.
  - Two runs of "persistent, warm cache" are Wi-Fi outliers, so that row uses the median.

### 7. Design tensions (Section 6: at least 3; this section carries a lot of marks)
For each tension: name it, state the position we took, and defend it with our own numbers.

1. **Caching freshness vs traffic reduction.** Source: section 7 of `R6_calculations.md`, plus the graph `r6_ttl.png`.
   - Hit ratio was 0%, 75%, 94%, 97% and 99% for TTL 0, 5, 30, 60 and 120 s, matching the model λT/(1+λT).
   - Position: Max-Age 60 s, with PURGE for content that changes.
2. **Connection reuse vs server resources.**
   - Persistent mode makes a page fetch 45% faster (median 60.0 → 32.9 ms warm, mean 113 → 67 ms cold) and uses 37% fewer bytes.
   - The cost is one thread and one socket held open per idle client, plus a second socket to the origin.
   - Position: keep-alive with a 15 s idle timeout that sends 408 and closes, so idle clients release their resources. Evidence: R7 idle-client test, 408 after 15.08 s.
3. **Compactness vs readability.**
   - Text headers are ≈ 111 B, against ≈ 11 B for binary. That is 71% of the message for index.html but only 0.05% for large.txt.
   - Each extra TCP connection costs ≈ 392 B, more than the text headers do.
   - Position: text format. It's easy to read in Wireshark and to test with a one-line Python command. See section 6 of the calculations file.
4. **Optional fourth: state vs simplicity.**
   - The proxy keeps state: the cache, and one origin connection per client.
   - Cost: after a crash the cache is empty, so a burst of misses follows, and a reused origin connection can go stale. That is why `forward()` retries once on a fresh connection.

### 8. Sustainability and efficiency (Section 7)
- **Source:** section 6 of `R6_calculations.md`, which already has the full paragraph of arithmetic.
- **Key numbers:**
  - Connection reuse saves 1,176 B per page view (37.2%), measured with tshark.
  - A cache hit at TTL 60 s removes 97.1% of origin traffic.
  - For 10,000 users: about 1.8 TB/year saved on the origin link, plus 215 GB/year saved by connection reuse.
  - Energy: about 12–121 kWh/year at 0.006–0.06 kWh/GB.
- **Keep the honesty note:** our objects are tiny, so the percentages matter more than the absolute numbers.
- **Check before citing:** Aslan, J., Mayers, K., Koomey, J. G. & France, C. (2018), *Electricity Intensity of Internet Data Transmission*, Journal of Industrial Ecology 22(4). Verify the 0.06 kWh/GB figure in the paper before you cite it.

### 9. Behaviour under failure (R7)
- **Evidence:** `evidence/R7-i.png` to `R7-vi.png`.
  - Client-side tests: 408 idle timeout, reset mid-transfer (the proxy keeps serving), 400, 505, 405.
  - Evidence log: 502 with the origin down, 504 with a slow origin, proxy unreachable.
  - The proxy console prints "Connection lost" for the mid-transfer reset.
- **For each case, describe:**
  - what was designed to happen (which timeout, which status code)
  - the evidence that it actually happened
  - how the system recovers: a cached object is still served while the origin is down, the next request succeeds after a restart, and other clients are unaffected
- Automated tests: `python test_files/test_proxy.py`.

### 10. Individual contributions, signed
Use the division of work in the proposal, updated with what each member actually did.

### 11. References
Kurose & Ross, *Computer Networking: A Top-Down Approach* (the lecture textbook), the Aslan et al. 2018 paper, and the Wireshark documentation.

### Appendices
Code (repository link or archive) and the AI-assistance declaration.

---

## All data files

All of these come from the three-host setup (H1 192.168.1.103, H2 192.168.1.63, H3 192.168.1.11).

**`evidence/`: screenshots**

| File | Shows | Report section |
|---|---|---|
| `H1(server)_R3.png`, `H2(proxy)_R3.jpg`, `H3(client)_R3.png` | `ipconfig` of each host | R3 |
| `network_diagram_R3.drawio` | Network diagram (export as PNG) | R3 |
| `server_R3.png`, `proxy_R3.png` | Origin and proxy starting on their hosts | R3 |
| `GET1_R3.png`, `GET2_R3.png`, `GET_proxy_R3.png`, `GET_server_R3.png` | One request seen at client, proxy and origin (MISS then HIT) | R3, R1 |
| `Packet1_R5.png`, `Packet2_R5.png`, `stream_R5.png` | Wireshark: one packet's layers, and the CNTP stream | R5 |
| `R7-i.png` … `R7-v.png` | Client-side failures: 408, mid-transfer reset, 400, 505, 405 | R7 |
| `R7-vi.png` | Evidence log: 502 origin down, 504 slow origin, proxy unreachable, recovery | R7 |

**`results/`: measurements**

| File | Contents | Report section |
|---|---|---|
| `R6_calculations.md` | Every table and worked calculation, ready to condense | R6, Section 6, Section 7 |
| `bench_wifi_20261124_161538_raw.csv` | Every benchmark run (10 per test) | R6 |
| `bench_wifi_20261124_161538_summary.csv` | Mean, SD, min, max per test | R6 |
| `ping_H3_20261124.csv` | ICMP ping from H3 to H2 and H1, 2 runs × 20 | R6 (RTT) |
| `wire_bytes_20261124_162110.csv` | Frames and bytes on the wire per scenario | Section 7, R5 |
| `wire_bytes_20261124_162110.pcapng` | The capture behind it (opens in Wireshark) | R5, Section 7 |
| `ttl_summary.csv` | Hit ratio per TTL (0, 5, 30, 60, 120 s) | Section 6 |
| `ttl_<T>_..._raw.csv` (5 files) | Every request in each TTL run | Section 6 |

**`results/plots/`: graphs**

| File | Graph |
|---|---|
| `r6_page_fetch.png` | Page fetch: persistent vs non-persistent, warm and cold cache |
| `r6_small_object_miss_hit.png` | Small object: MISS vs HIT |
| `r6_large_object_time.png` | Large object transfer time: MISS vs HIT |
| `r6_throughput.png` | Throughput: MISS vs HIT |
| `r6_rtt.png` | TCP connect RTT and CNTP RTT |
| `r6_ttl.png` | Hit ratio vs TTL, measured and model |
| `r6_summary.csv` | The numbers behind the R6 graphs |

## Reproducing any number
Run these on H3 with Python 3.12 and matplotlib, with `server.py` running on H1 and `proxy.py` on H2:

```powershell
python bench.py --proxy-host 192.168.1.63 --label wifi --runs 10
python wire_bytes.py --proxy-host 192.168.1.63 --iface Wi-Fi --runs 5
python ttl_bench.py --proxy-host 192.168.1.63      # once per H1 --max-age value
python plot_results.py results\bench_wifi_<time>_raw.csv
python analyze_r6.py
```
