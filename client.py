
import socket
import time
import csv
import os

PROXY_HOST = "127.0.0.1"
PROXY_PORT = 9090

VERSION = "CNTP/1.0"

TOTAL_REQUESTS = 10
CSV_FILE = "results/performance_results.csv"


# Read one complete CNTP response
def read_one_response(client_socket, method="GET"):

    response = b""

    # Read headers
    while b"\r\n\r\n" not in response:

        data = client_socket.recv(4096)

        if not data:
            return response

        response += data

    headers, body = response.split(b"\r\n\r\n", 1)

    # HEAD responses have no body
    if method == "HEAD":
        return headers + b"\r\n\r\n"

    content_length = 0

    for line in headers.decode(errors="replace").split("\r\n"):

        if line.lower().startswith("content-length:"):

            content_length = int(
                line.split(":", 1)[1].strip()
            )

    # Read remaining body bytes
    while len(body) < content_length:

        data = client_socket.recv(4096)

        if not data:
            break

        body += data

    return headers + b"\r\n\r\n" + body[:content_length]


# Extract X-Cache status
def get_cache_status(response):

    if b"\r\n\r\n" not in response:
        return "Unknown"

    headers = response.split(b"\r\n\r\n", 1)[0]

    for line in headers.decode(errors="replace").split("\r\n"):

        if line.lower().startswith("x-cache:"):

            return line.split(":", 1)[1].strip()

    return "N/A"


# Send GET, HEAD or PURGE request
def send_request(request, method="GET"):

    client_socket = socket.create_connection(
        (PROXY_HOST, PROXY_PORT)
    )

    client_socket.sendall(request.encode())

    response = read_one_response(client_socket, method)

    client_socket.close()

    if b"\r\n\r\n" in response:

        headers, body = response.split(b"\r\n\r\n", 1)

        print("\n========== RESPONSE HEADERS ==========")
        print(headers.decode(errors="replace"))

        print("\n========== RESPONSE BODY ==========")

        if body:
            print(body.decode(errors="replace"))
        else:
            print("No response body.")

    else:

        print("Invalid response received.")
        print(response.decode(errors="replace"))


# GET request
def send_get_request():

    request = (
        f"GET /index.html {VERSION}\r\n"
        f"Host: {PROXY_HOST}:{PROXY_PORT}\r\n"
        "Connection: close\r\n"
        "\r\n"
    )

    send_request(request, "GET")


# HEAD request
def send_head_request():

    request = (
        f"HEAD /index.html {VERSION}\r\n"
        f"Host: {PROXY_HOST}:{PROXY_PORT}\r\n"
        "Connection: close\r\n"
        "\r\n"
    )

    send_request(request, "HEAD")


# PURGE request
def send_purge_request():

    request = (
        f"PURGE /index.html {VERSION}\r\n"
        f"Host: {PROXY_HOST}:{PROXY_PORT}\r\n"
        "Connection: close\r\n"
        "\r\n"
    )

    send_request(request, "PURGE")


# Automated performance testing
def send_multiple_requests(persistent):

    results = []

    total_time = 0

    mode = "Persistent" if persistent else "Non-Persistent"

    print(f"\nStarting {mode} Performance Test")
    print(f"Total requests: {TOTAL_REQUESTS}")

    # Warm up cache before measuring
    warmup_socket = socket.create_connection(
        (PROXY_HOST, PROXY_PORT)
    )

    warmup_request = (
        f"GET /index.html {VERSION}\r\n"
        f"Host: {PROXY_HOST}:{PROXY_PORT}\r\n"
        "Connection: close\r\n"
        "\r\n"
    )

    warmup_socket.sendall(warmup_request.encode())
    read_one_response(warmup_socket, "GET")
    warmup_socket.close()

    # Persistent mode uses one socket
    if persistent:

        client_socket = socket.create_connection(
            (PROXY_HOST, PROXY_PORT)
        )

    for i in range(TOTAL_REQUESTS):

        # Non-persistent creates a new socket per request
        if not persistent:

            client_socket = socket.create_connection(
                (PROXY_HOST, PROXY_PORT)
            )

        connection_type = (
            "keep-alive" if persistent else "close"
        )

        request = (
            f"GET /index.html {VERSION}\r\n"
            f"Host: {PROXY_HOST}:{PROXY_PORT}\r\n"
            f"Connection: {connection_type}\r\n"
            "\r\n"
        )

        start_time = time.perf_counter()

        client_socket.sendall(request.encode())

        response = read_one_response(client_socket, "GET")

        end_time = time.perf_counter()

        elapsed = end_time - start_time

        total_time += elapsed

        cache_status = get_cache_status(response)

        results.append({
            "Mode": mode,
            "Request": i + 1,
            "Response_Time_Seconds": round(elapsed, 8),
            "Cache_Status": cache_status
        })

        print(f"\nRequest {i + 1}")
        print(f"X-Cache: {cache_status}")
        print(f"Time: {elapsed:.6f} seconds")

        if not persistent:

            client_socket.close()

    if persistent:

        client_socket.close()

    average_time = total_time / TOTAL_REQUESTS

    print("\n========== PERFORMANCE RESULTS ==========")

    print(f"Mode: {mode}")
    print(f"Total requests: {TOTAL_REQUESTS}")
    print(f"Total time: {total_time:.6f} seconds")
    print(f"Average time: {average_time:.6f} seconds")

    # Save results to CSV
    save_results(results)

    print(f"\nResults saved to {CSV_FILE}")


# Save benchmark data
def save_results(results):

    file_exists = os.path.exists(CSV_FILE)

    with open(CSV_FILE, "a", newline="") as file:

        fieldnames = [
            "Mode",
            "Request",
            "Response_Time_Seconds",
            "Cache_Status"
        ]

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames
        )

        if not file_exists or os.path.getsize(CSV_FILE) == 0:

            writer.writeheader()

        writer.writerows(results)


# Main menu
if __name__ == "__main__":

    import argparse

    parser = argparse.ArgumentParser(description="CacheNet CLI client")
    parser.add_argument("--proxy-host", default=PROXY_HOST,
                        help="IP of the proxy host (H2)")
    parser.add_argument("--proxy-port", type=int, default=PROXY_PORT)
    args = parser.parse_args()
    PROXY_HOST, PROXY_PORT = args.proxy_host, args.proxy_port

    print("\n===== CacheNet CLI Client =====")
    print(f"Proxy: {PROXY_HOST}:{PROXY_PORT}")

    print("1. GET Request")
    print("2. HEAD Request")
    print("3. PURGE Request")
    print("4. Non-Persistent Performance Test")
    print("5. Persistent Performance Test")

    choice = input("\nEnter your choice: ")

    if choice == "1":

        send_get_request()

    elif choice == "2":

        send_head_request()

    elif choice == "3":

        send_purge_request()

    elif choice == "4":

        send_multiple_requests(False)

    elif choice == "5":

        send_multiple_requests(True)

    else:

        print("Invalid choice!")
