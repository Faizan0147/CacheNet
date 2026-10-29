from server import build_response

resp = build_response(200, "OK", "text/plain", b"hello")
print(resp)
print(resp.decode())
print("Length check:", len(b"hello"))

from server import build_response

print(build_response(200, "OK", "text/plain", b"hello").decode())
print()
print(build_response(405, "Method Not Allowed", "text/plain", b"no",
                     extra_headers=[("Allow", "GET, HEAD")]).decode())