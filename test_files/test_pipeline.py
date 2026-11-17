import socket

two_requests = (
    b"GET /index.html CNTP/1.0\r\nHost: localhost\r\n\r\n"
    b"GET /about.html CNTP/1.0\r\nHost: localhost\r\n\r\n"
)

with socket.create_connection(("127.0.0.1", 8080)) as s:
    s.sendall(two_requests)
    input("Press Enter to close the connection...")