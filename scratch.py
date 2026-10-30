# from server import build_response

# resp = build_response(200, "OK", "text/plain", b"hello")
# print(resp)
# print(resp.decode())
# print("Length check:", len(b"hello"))

# from server import build_response

# print(build_response(200, "OK", "text/plain", b"hello").decode())
# print()
# print(build_response(405, "Method Not Allowed", "text/plain", b"no",
#                      extra_headers=[("Allow", "GET, HEAD")]).decode())

# from server import resolve_path
# print(resolve_path(b"/"))
# print(resolve_path(b"/index.html"))
# print(resolve_path(b"/../secret.txt"))
# print(resolve_path(b"/missing.html"))

import os
from server import DOC_ROOT
print(DOC_ROOT)
print(os.path.isfile(os.path.join(DOC_ROOT, "index.html")))

# import os
# from server import DOC_ROOT
# print("DOC_ROOT:", DOC_ROOT)
# print("index exists:", os.path.isfile(os.path.join(DOC_ROOT, "index.html")))