import os, sys, socket, threading, time, mimetypes

HOST = "0.0.0.0"
PORT = 8080
VERSION = b"CNTP/1.0"
MAX_AGE = 60
DOC_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "www")
LOG_LOCK = threading.Lock()
class VersionError(ValueError):
    pass

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

def log_request(addr, request_line, status, nbytes):
    line = f'{time.strftime("%Y-%m-%d %H:%M:%S")} {addr[0]}:{addr[1]} "{request_line}" {status} {nbytes}'
    print(line)
    with LOG_LOCK:
        with open("server.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")

def handle_client(conn, addr):
    """Calls read_requests then print the request and the address, Stop the loop when read_requests reports 
#         client closed"""
    buffer = b""
    conn.settimeout(15)
    with conn:
        try:

            while True:
                try:
                    request, buffer = read_requests(conn, buffer)
                except socket.timeout:
                    response=build_response(408,"Request Timeout","text/plain",b"Request Timeout",connection="close")
                    conn.sendall(response)
                    log_request(addr,"-",408,len(response))
                    break
                if request is None:
                    print("Client disconnected:", addr)
                    break
                request_line=request.split(b"\r\n",1)[0].decode("latin-1","replace")
                close=False
                try:
                    parsed = parse_request(request)
                    #non-persistent mode: answer, then close this connection
                    close=parsed["headers"].get(b"connection", b"").lower()==b"close"
                    response=handle_request(parsed)
                except VersionError:
                    response=build_response(505,"Version Not supported","text/plain",b"Version Not supported")
                except ValueError as e:
                    print("Bad request:", e)
                    response=build_response(400, "Bad Request", "text/plain", b"Bad Request")

                status=int(response.split(b" ",2)[1])
                conn.sendall(response)
                log_request(addr,request_line,status,len(response))
                if close:
                    break

        except OSError as e:
            print("Connection error",addr,e)

                    
                    
            

        
    
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

    if version != VERSION:
        raise VersionError("unsupported version")

    headers = {}
    for line in info[1:]:
        if line == b"":
            break
        if b":" not in line:
            raise ValueError("Malformed header line")
        name, value = line.split(b":", 1)
        name = name.strip().lower()
        if name == b"content-length" and name in headers:
            raise ValueError("duplicate Content-Length")
        headers[name] = value.strip()
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
        server.settimeout(1) #wake up every second so Ctrl+C works on Windows
        print(f"Listening on {HOST}:{PORT}")
        try:
            while True:
                try:
                    conn,addr=server.accept()
                    conn.settimeout(None) #accepted sockets must not inherit the 1 s accept timeout
                    threading.Thread(target=handle_client,args=(conn,addr),daemon=True).start()
                except socket.timeout:
                    pass
        except KeyboardInterrupt:
            print("\nServer stopped")


def build_response(status_code, reason, content_type, body, extra_headers=None, connection="keep-alive"):
    """
    Return the full HTTP response as bytes: status line, headers, blank line, body.
    body must be bytes. Content-Length is computed from it.
    extra_headers: optional list of (name, value) string pairs, e.g. [("Allow", "GET, HEAD")].
    connection: "keep-alive" or "close".
    """
  
    status_line = f"CNTP/1.0 {status_code} {reason}" # creating the status line with status code and reason
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
    url_path = url_path.split(b"?", 1)[0]
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
            return build_response(404, "Not Found", "text/plain", b"Not Found", connection=connection)
    

    #  read the file in binary mode: open(path, "rb").read()
    with open (path,"rb") as f:
        body=f.read()

    # pick Content-Type from the file extension
    content_type=CONTENT_TYPES.get(os.path.splitext(path)[1].lower(),"application/octet-stream")

    # \ for GET, return build_response(200, "OK", content_type, body).
    #         For HEAD, build the same response, then drop the body.
    #        
    #the fixed table first, so every host sends the same type (mimetypes reads the Windows registry)
    ctype = CONTENT_TYPES.get(os.path.splitext(path)[1].lower()) or mimetypes.guess_type(path)[0] or "application/octet-stream"
    full = build_response(200, "OK", ctype, body, extra_headers=[("Max-Age", str(MAX_AGE))], connection=connection)
    if method==b"HEAD":
        return full[: full.find(b"\r\n\r\n") + 4]
    return full




    
if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser(description="CacheNet origin server")
    parser.add_argument("port",nargs="?",type=int,help="same as --port (kept so 'python server.py 8080' still works)")
    parser.add_argument("--port",dest="port_opt",type=int,default=PORT)
    parser.add_argument("--max-age",type=int,default=MAX_AGE,help="Max-Age (TTL seconds) sent with every 200 response")
    args=parser.parse_args()
    PORT=args.port if args.port is not None else args.port_opt
    MAX_AGE=args.max_age
    print(f"Max-Age: {MAX_AGE}s, document root: {DOC_ROOT}")
    main()



    

    

