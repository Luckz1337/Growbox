import json


def url_decode(s):
    """Generic percent-decoding (RFC 3986) instead of a fixed lookup table -
    handles any encoded byte/UTF-8 sequence, not just a hardcoded subset."""
    if not s:
        return s
    result = bytearray()
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == '+':
            result.append(0x20)
            i += 1
        elif c == '%' and i + 2 < n:
            try:
                result.append(int(s[i + 1:i + 3], 16))
                i += 3
            except ValueError:
                result.append(ord(c))
                i += 1
        else:
            result.append(ord(c))
            i += 1
    return result.decode('utf-8')


def parse_query(path):
    """'/api/foo?a=1&b=2' -> ('/api/foo', {'a': '1', 'b': '2'}), values url-decoded."""
    if "?" not in path:
        return path, {}
    route, query = path.split("?", 1)
    params = {}
    for pair in query.split("&"):
        if "=" in pair:
            key, value = pair.split("=", 1)
            params[key] = url_decode(value)
    return route, params


async def send_json(writer, data, status=200, status_text="OK"):
    body = json.dumps(data).encode()
    headers = (
        f"HTTP/1.1 {status} {status_text}\r\n"
        "Content-Type: application/json\r\n"
        "Access-Control-Allow-Origin: *\r\n"
        f"Content-Length: {len(body)}\r\n\r\n"
    )
    writer.write(headers.encode())
    writer.write(body)
    await writer.drain()


async def send_plain(writer, status, status_text, body=""):
    headers = f"HTTP/1.1 {status} {status_text}\r\nContent-Type: text/plain\r\nContent-Length: {len(body)}\r\n\r\n"
    writer.write(headers.encode() + body.encode())
    await writer.drain()


async def send_unauthorized(writer):
    body = "Unauthorized"
    headers = (
        "HTTP/1.1 401 Unauthorized\r\n"
        'WWW-Authenticate: Basic realm="Growbox"\r\n'
        f"Content-Length: {len(body)}\r\n\r\n"
    )
    writer.write(headers.encode() + body.encode())
    await writer.drain()


async def send_file_chunked(writer, filename, content_type):
    headers = (
        "HTTP/1.1 200 OK\r\n"
        f"Content-Type: {content_type}\r\n"
        "Transfer-Encoding: chunked\r\n\r\n"
    )
    writer.write(headers.encode())
    await writer.drain()
    with open(filename, "rb") as f:
        while True:
            chunk = f.read(1024)
            if not chunk:
                break
            size = hex(len(chunk))[2:]
            writer.write(f"{size}\r\n".encode())
            writer.write(chunk)
            writer.write(b"\r\n")
            await writer.drain()
    writer.write(b"0\r\n\r\n")
    await writer.drain()
