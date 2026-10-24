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

def main():
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        server.bind((HOST,PORT))
        server.listen()
        print(f"Listening on {HOST}:{PORT}")
        while True:
            conn,addr=server.accept()
            threading.Thread(target=handle_client,args=(conn,addr),daemon=True).start()

            
if __name__=="__main__":
    main()



    

    

