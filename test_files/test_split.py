import socket
import time

with socket.create_connection(("127.0.0.1", 8080)) as s:
    s.sendall(b"GET /index.html CNTP/1.0\r\nHost: lo")
    time.sleep(1)
    s.sendall(b"calhost\r\n\r\n")
    time.sleep(1)#h