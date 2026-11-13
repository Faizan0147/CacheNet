"""Automated tests for the caching proxy.
Starts the origin, the proxy and three fake origins in this process on spare ports
(so nothing else needs to be running), then checks each behaviour.
Run from the CacheNet folder:  python test_files/test_proxy.py"""
import os
import sys
import socket
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server
import proxy

ORIGIN_PORT=8180
PROXY_PORT=9190
SLOW_PORT,HALF_PORT,NO_MAX_AGE_PORT,HTTP_PORT=8181,8182,8183,8184

# short timings so the test finishes quickly
server.PORT=ORIGIN_PORT
server.MAX_AGE=2
server.IDLE_TIMEOUT=2
proxy.IDLE_TIMEOUT=3
proxy.ORIGIN_TIMEOUT=3 #above the ~2s Windows takes to report a refused connection, below the slow origin's 5s


def fake_origin(port,reply):
    """Minimal origin that reads one request and runs reply(conn)"""
    s=socket.socket()
    s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
    s.bind(("127.0.0.1",port))
    s.listen()
    while True:
        conn,_=s.accept()
        def handle(conn=conn):
            try:
                conn.recv(4096)
                reply(conn)
            except OSError:
                pass
        threading.Thread(target=handle,daemon=True).start()

def slow(conn):
    time.sleep(5)

def half_body(conn):
    conn.sendall(b"CNTP/1.0 200 OK\r\nContent-Length: 100\r\n\r\nonly-part")
    conn.close()

def no_max_age(conn):
    conn.sendall(b"CNTP/1.0 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 2\r\n\r\nhi")
    conn.close()

def http_version(conn):
    conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 2\r\n\r\nhi")
    conn.close()


leftover={} #socket -> bytes already received that belong to the next (pipelined) response

def recv_response(s,method=b"GET"):
    """Read one response: headers, then Content-Length body bytes. Returns (status,headers,body)."""
    head,buf=proxy.read_requests(s,leftover.pop(s,b""))
    if head is None:
        return None,{},b""
    status,reason,headers=proxy.parse_response(head)
    length=0 if method==b"HEAD" else int(headers.get(b"content-length",b"0"))
    while len(buf)<length:
        buf+=s.recv(65536)
    leftover[s]=bytes(buf[length:])
    return status,headers,bytes(buf[:length])

def request(method,path,s=None,extra=b""):
    """Send one request (on a new connection unless s is given) and return the response"""
    own=s is None
    s=s or socket.create_connection(("127.0.0.1",PROXY_PORT),timeout=10)
    s.sendall(method+b" "+path+b" CNTP/1.0\r\nHost: proxy\r\n"+extra+b"\r\n")
    result=recv_response(s,method)
    if own:
        s.close()
    return result

def xcache(headers):
    return headers.get(b"x-cache",b"").decode()


results=[]
def check(name,condition,detail=""):
    results.append(condition)
    print(f"{'PASS' if condition else 'FAIL'}  {name}  {detail}")


def main():
    sys.argv=["proxy.py","--port",str(PROXY_PORT),"--origin-port",str(ORIGIN_PORT),"--ttl","60"]
    threading.Thread(target=server.main,daemon=True).start()
    threading.Thread(target=proxy.main,daemon=True).start()
    for port,reply in [(SLOW_PORT,slow),(HALF_PORT,half_body),(NO_MAX_AGE_PORT,no_max_age),(HTTP_PORT,http_version)]:
        threading.Thread(target=fake_origin,args=(port,reply),daemon=True).start()
    time.sleep(1)

    # cache hit / miss and TTL
    st,h,_=request(b"GET",b"/");                check("GET / first time is MISS",st==200 and xcache(h)=="MISS")
    st,h,_=request(b"GET",b"/index.html");      check("GET /index.html is HIT (same entry as /)",xcache(h)=="HIT")
    st,h,b=request(b"HEAD",b"/index.html");     check("HEAD on cached path is HIT with no body",xcache(h)=="HIT" and b==b"")
    time.sleep(2.5)
    st,h,_=request(b"GET",b"/");                check("GET / after Max-Age expired is MISS",xcache(h)=="MISS")

    # PURGE
    st,_,_=request(b"PURGE",b"/");              check("PURGE cached path returns 200",st==200)
    st,_,_=request(b"PURGE",b"/");              check("PURGE uncached path returns 404",st==404)
    st,h,_=request(b"GET",b"/");                check("GET after PURGE is MISS",xcache(h)=="MISS")
    request(b"GET",b"/notes.txt")
    st,_,_=request(b"PURGE",b"*");              check("PURGE * returns 200",st==200)
    st,h,_=request(b"GET",b"/notes.txt");       check("GET after PURGE * is MISS",xcache(h)=="MISS")

    # methods, errors, content
    st,h,_=request(b"POST",b"/");               check("POST returns 405 with Allow",st==405 and h.get(b"allow")==b"GET, HEAD, PURGE")
    st,h,_=request(b"GET",b"/missing.html")
    st2,h2,_=request(b"GET",b"/missing.html");  check("404 is not cached",st==st2==404 and xcache(h2)=="MISS")
    s=socket.create_connection(("127.0.0.1",PROXY_PORT),timeout=10)
    s.sendall(b"GARBAGE\r\n\r\n"); st,_,_=recv_response(s); s.close()
    check("Malformed request returns 400",st==400)
    s=socket.create_connection(("127.0.0.1",PROXY_PORT),timeout=10)
    s.sendall(b"GET / HTTP/1.1\r\nHost: proxy\r\n\r\n"); st,_,_=recv_response(s); s.close()
    check("Non-CNTP request returns 505",st==505)
    st,h,b=request(b"GET",b"/large.txt");       check("Large body arrives complete",len(b)==int(h[b"content-length"]),f"({len(b)} bytes)")
    st,h,_=request(b"GET",b"/logo.png");        check("Content-Type passed through",h.get(b"content-type")==b"image/png")

    # connection management
    s=socket.create_connection(("127.0.0.1",PROXY_PORT),timeout=10)
    st,h,_=request(b"GET",b"/about.html",s=s,extra=b"Connection: close\r\n")
    check("Connection: close is honoured",h.get(b"connection")==b"close" and s.recv(1)==b""); s.close()

    s=socket.create_connection(("127.0.0.1",PROXY_PORT),timeout=10)
    s.sendall(b"".join(b"GET /"+p+b" CNTP/1.0\r\nHost: proxy\r\n\r\n" for p in (b"about.html",b"notes.txt",b"logo.png")))
    statuses=[recv_response(s)[0] for _ in range(3)]; s.close()
    check("3 pipelined requests get 3 responses",statuses==[200,200,200])

    s=socket.create_connection(("127.0.0.1",PROXY_PORT),timeout=10)
    st1,_,_=request(b"GET",b"/about.html",s=s)
    request(b"PURGE",b"/about.html"); time.sleep(2.5) #origin idle-closes the proxy's origin connection meanwhile
    st2,h,_=request(b"GET",b"/about.html",s=s); s.close()
    check("Stale origin connection is replaced (retry)",st1==st2==200 and xcache(h)=="MISS")

    out=[]
    workers=[threading.Thread(target=lambda: out.append(request(b"GET",b"/logo.png")[0])) for _ in range(5)]
    for w in workers: w.start()
    for w in workers: w.join()
    check("5 concurrent clients all get 200",out==[200]*5)

    s=socket.create_connection(("127.0.0.1",PROXY_PORT),timeout=10)
    start=time.time(); st,h,_=recv_response(s); closed=s.recv(1)==b""; s.close()
    check("Idle client gets 408 then close",st==408 and closed,f"(after {time.time()-start:.1f}s)")

    s=socket.create_connection(("127.0.0.1",PROXY_PORT),timeout=10)
    s.sendall(b"GET /large.txt CNTP/1.0\r\n\r\n")
    s.setsockopt(socket.SOL_SOCKET,socket.SO_LINGER,b"\x01\x00\x00\x00\x00\x00\x00\x00"); s.close() #reset
    time.sleep(0.5)
    st,_,_=request(b"GET",b"/");                check("Proxy still serves after a client reset",st==200)

    # origin failures
    request(b"PURGE",b"*")
    for port,expected,name in [(8189,502,"Origin down returns 502"),
                               (SLOW_PORT,504,"Slow origin returns 504"),
                               (HALF_PORT,502,"Incomplete origin response returns 502")]:
        proxy.ORIGIN_PORT=port
        st,_,_=request(b"GET",b"/x");           check(name,st==expected)
    proxy.ORIGIN_PORT=HTTP_PORT
    st,_,_=request(b"GET",b"/z")
    st2,_,_=request(b"GET",b"/z");              check("Non-CNTP origin response returns 502 and is not cached",st==st2==502)
    proxy.ORIGIN_PORT=NO_MAX_AGE_PORT
    request(b"GET",b"/y")
    st,h,_=request(b"GET",b"/y");               check("No Max-Age falls back to --ttl (cached)",xcache(h)=="HIT")

    print(f"\n{sum(results)}/{len(results)} passed")
    sys.exit(0 if all(results) else 1)


if __name__=="__main__":
    main()
