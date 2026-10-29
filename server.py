import socket
import threading

HOST='127.0.0.1'
PORT=9999

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

        buffer.extend(new_data) #append the freshly recieved bytes to our streaming buffer and loop again


def handle_client(conn,addr):
    """Calls read_requests then print the request and the address, Stop the loop when read_requests reports 
        client closed"""
    buffer=bytearray()
    with conn:
        while True:
            
            request,buffer=read_requests(conn,buffer)
            if request is None:
                print("Client disconnected",buffer)
                break
                    
            print("Request: ",request)
            print("Address: ",addr)
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


def build_response(status_code, reason, content_type, body, extra_headers=None):
    """
    Return the full HTTP response as bytes: status line, headers, blank line, body.
    body must be bytes. Content-Length is computed from it.
    extra_headers: optional list of (name, value) string pairs, e.g. [("Allow", "GET, HEAD")].
    """
  
    status_line=f'HTTP/1.1 {status_code} {reason}'
    response=[status_line]
    response.append(f"Content-Type: {content_type}")
    response.append(f"Content-Length: {len(body)}")
    response.append(f"Connection: keep-alive")
    if extra_headers:
        for name,value in extra_headers:
            response.append(f"{name}: {value}")

    response_block="\r\n".join(response)+"\r\n\r\n"

    full_response=response_block.encode("utf-8")+body


    return full_response
            
if __name__=="__main__":
    
    main()



    

    

