"""CNTP/1.0 shared helpers: message framing, parsing and building."""

CRLF = "\r\n"
VERSION = "CNTP/1.0"
MAX_HEADER_BYTES = 64 * 1024

REASONS = {
    200: "OK",
    400: "Bad Request",
    404: "Not Found",
    405: "Method Not Allowed",
    408: "Request Timeout",
    502: "Bad Gateway",
    504: "Gateway Timeout",
    505: "Version Not Supported",
}


class BadMessage(Exception):
    pass


def recv_message(sock, buf=b"", no_body=False):
    """Return (start_line, headers, body, leftover), or None if the peer closed cleanly.
    Raises BadMessage on malformed input."""
    while b"\r\n\r\n" not in buf:
        if len(buf) > MAX_HEADER_BYTES:
            raise BadMessage("headers too large")
        chunk = sock.recv(4096)
        if not chunk:
            if not buf:
                return None
            raise BadMessage("connection closed in the middle of headers")
        buf += chunk

    head, _, rest = buf.partition(b"\r\n\r\n")
    lines = head.decode("iso-8859-1").split(CRLF)
    start_line = lines[0]
    headers = {}
    for line in lines[1:]:
        if ":" not in line:
            raise BadMessage("malformed header line: %r" % line)
        name, value = line.split(":", 1)
        headers[name.strip().lower()] = value.strip()

    try:
        length = int(headers.get("content-length", "0"))
    except ValueError:
        raise BadMessage("Content-Length is not an integer")
    if length < 0:
        raise BadMessage("negative Content-Length")
    if no_body:
        length = 0

    while len(rest) < length:
        chunk = sock.recv(min(65536, length - len(rest)))
        if not chunk:
            raise BadMessage("connection closed in the middle of the body")
        rest += chunk

    return start_line, headers, rest[:length], rest[length:]


def _build(start_line, headers, body, content_length):
    h = dict(headers or {})
    h["Content-Length"] = str(len(body) if content_length is None else content_length)
    text = start_line + CRLF
    for name, value in h.items():
        text += "%s: %s%s" % (name, value, CRLF)
    text += CRLF
    return text.encode("iso-8859-1") + body


def build_request(method, path, headers=None, body=b""):
    return _build("%s %s %s" % (method, path, VERSION), headers, body, None)


def build_response(status, headers=None, body=b"", content_length=None):
    start = "%s %d %s" % (VERSION, status, REASONS.get(status, "Unknown"))
    return _build(start, headers, body, content_length)


def parse_request_line(line):
    parts = line.split(" ")
    if len(parts) != 3 or not parts[1].startswith("/"):
        raise BadMessage("malformed request line: %r" % line)
    return parts[0], parts[1], parts[2]


def parse_status_line(line):
    parts = line.split(" ", 2)
    if len(parts) < 2 or not parts[1].isdigit():
        raise BadMessage("malformed status line: %r" % line)
    return parts[0], int(parts[1]), (parts[2] if len(parts) > 2 else "")
