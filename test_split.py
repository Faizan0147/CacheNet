import socket
import time

with socket.create_connection(("127.0.0.1", 9999)) as s:
    s.sendall(b"GET /index.html HTTP/1.1\r\nHost: lo")
    time.sleep(1)
    s.sendall(b"calhost\r\n\r\n")
    time.sleep(1)#h