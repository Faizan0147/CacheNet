import socket
import threading

HOST='0.0.0.0' #listen on all interfaces so other hosts can connect
PORT=8080
MAX_AGE=30 #TTL in seconds sent to the proxy in the Max-Age header
IDLE_TIMEOUT=15 #seconds to wait for the next request before sending 408

def read_requests(conn,buffer):
    """Return (request_bytes,leftover_buffer) once a full header block is available
       Return (None,buffer) if the client closed the connection"""
    

    while True:


        delimeter_index=buffer.find(b"\r\n\r\n")#check if the marker is in the buffer

        if delimeter_index!= -1:
            header_end=delimeter_index+len(b"\r\n\r\n")

            request_bytes=bytes(buffer[:header_end])
            leftover_buffer=bytearray(buffer[header_end:])

            return request_bytes,leftover_buffer
        else:
            new_data=conn.recv(4096)#marker not found,fall thhrough to read more data from the network
        

        if not new_data:#handle explicit client connection
            return None,buffer #the client closed the connection without sending a full header

        buffer=buffer+new_data #append the freshly recieved bytes to our streaming buffer and loop again



def handle_client(conn, addr):
    """Calls read_requests then print the request and the address, Stop the loop when read_requests reports 
#         client closed"""
    buffer = b""
    conn.settimeout(IDLE_TIMEOUT)
    with conn:
        try:
            while True:
                try:
                    request, buffer = read_requests(conn, buffer)
                except socket.timeout: #client sent nothing for IDLE_TIMEOUT seconds
                    print("Idle timeout:", addr)
                    conn.sendall(build_response(408, "Request Timeout", "text/plain", b"Request Timeout", connection="close"))
                    break
                if request is None:
                    print("Client disconnected:", addr)
                    break

                try:
                    parsed = parse_request(request)
                except ValueError as e:
                    print("Bad request:", e)
                    conn.sendall(build_response(400, "Bad Request", "text/plain", b"Bad Request"))
                    continue

                conn.sendall(handle_request(parsed))

                if parsed["headers"].get(b"connection", b"").lower() == b"close": #non-persistent mode
                    break
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError): #client dropped mid-transfer
            print("Connection lost:", addr)
                    
            

        
    
def parse_request(raw):
    """
    raw: the request bytes up to and including the blank line.
    Return (method, path, version, headers) or raise ValueError for a malformed request.
    """

    info=raw.split(b"\r\n") #extracting request line(method,path and version) and headers from the request
    if not info or not info[0]:#if request is empty or request line is missing 
        raise ValueError("Missing request line")
    parts=info[0].split(b" ") #extracting method,path and version from request line
    if len(parts)!=3:
        raise ValueError("Missing method, path or version from the request line") #if any of that is missing raise VAluerror

    method,path,version=info[0].split(b" ")

    headers={} #collecting headers into a dictionary
    for line in info[1:]: #everything except for the request line
        
        if line==b"":   
            break
        if b":" not in line:
            raise ValueError("Malformed header line")

            
        key,value=line.split(b":",1)
        headers[key.strip().lower()]=value.strip()

    return {
            "method":method,
            "path":path,
            "version":version,
            "headers":headers}



def main():
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        server.bind((HOST,PORT))
        server.listen()
        print(f"Listening on {HOST}:{PORT}")
        while True:
            conn,addr=server.accept()
            threading.Thread(target=handle_client,args=(conn,addr),daemon=True).start()


def build_response(status_code, reason, content_type, body, extra_headers=None, connection="keep-alive"):
    """
    Return the full HTTP response as bytes: status line, headers, blank line, body.
    body must be bytes. Content-Length is computed from it.
    extra_headers: optional list of (name, value) string pairs, e.g. [("Allow", "GET, HEAD")].
    connection: "keep-alive" or "close".
    """

    status_line=f'HTTP/1.1 {status_code} {reason}' # creating the status line with status code and reason
    response=[status_line]
    response.append(f"Content-Type: {content_type}")
    response.append(f"Content-Length: {len(body)}")
    response.append(f"Connection: {connection}")
    if extra_headers:
        for name,value in extra_headers:
            response.append(f"{name}: {value}")  #extra headers wxist as tuples

    response_block="\r\n".join(response)+"\r\n\r\n" #joining everything with a blankline

    full_response=response_block.encode("utf-8")+body #encoding in byte form


    return full_response

import os

DOC_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "www") #www/ next to server.py

CONTENT_TYPES = {
    ".html": "text/html",
    ".txt": "text/plain",
    ".png": "image/png",
    ".jpg": "image/jpeg",
}
import urllib.parse
from pathlib import Path
def resolve_path(url_path):
    """
    url_path: the path from the request line, as bytes, e.g. b"/index.html".
    Return the absolute file path under DOC_ROOT, or None if the path is unsafe
    or the file does not exist.
    """
    #  1: decode url_path to a string. Map b"/" to "index.html".
    try:
        
        decoded_path = urllib.parse.unquote(url_path.decode('utf-8'))

    except UnicodeDecodeError:
        return None
    
    
    # 2. Map the root path b"/" (or an empty string) to "index.html"
    if decoded_path == "/" or decoded_path == "":
        decoded_path = "/index.html"


   
    #  strip the leading "/" so the path is relative to DOC_ROOT.
    relative=decoded_path.lstrip("/")

    #
    # 3: build the full path with os.path.join(DOC_ROOT, relative),
    #         then normalize it with os.path.abspath.

    full_path=os.path.join(DOC_ROOT,relative)
    normalized_path=os.path.abspath(full_path)
    #
    #4: check that the normalized path still starts with DOC_ROOT + os.sep.
    #         If it doesn't, the path escaped the document root. Return None.

    prefix=DOC_ROOT+os.sep

    if not normalized_path.startswith(prefix) and normalized_path!=DOC_ROOT:
        return None
    #
    #  if the file doesn't exist or isn't a regular file
    #         (os.path.isfile), return None. Otherwise return the path.
    if not os.path.isfile(normalized_path):
        return None

    return normalized_path

def handle_request(parsed):
    method = parsed["method"]
    #echo back "close" if the client asked for a non-persistent connection
    connection = "close" if parsed["headers"].get(b"connection", b"").lower() == b"close" else "keep-alive"
    if method not in (b"GET", b"HEAD"):
        #1: 405 response with extra_headers=[("Allow", "GET, HEAD")]

        return build_response(405,"Method Not Allowed","text/plain",b"Method Not Allowed",extra_headers=[("Allow","GET, HEAD")],connection=connection)



    # : call resolve_path(parsed["path"]).
    #         If it returns None, return a 404 response
    path=resolve_path(parsed["path"])
    if not path:
        return build_response(404,"Not Found","text/plain",b"Not Found",connection=connection)


    #  read the file in binary mode: open(path, "rb").read()
    with open (path,"rb") as f:
        body=f.read()

    # pick Content-Type from the file extension
    content_type=CONTENT_TYPES.get(os.path.splitext(path)[1].lower(),"application/octet-stream")

    # \ for GET, return build_response(200, "OK", content_type, body).
    #         For HEAD, build the same response, then drop the body.
    #
    full = build_response(200, "OK", content_type, body, extra_headers=[("Max-Age", str(MAX_AGE))], connection=connection)
    if method==b"HEAD":
        return full[: full.find(b"\r\n\r\n") + 4]
    return full
    
if __name__=="__main__":
    
    main()



    

    

