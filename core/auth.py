import ubinascii


def check_basic_auth(headers, expected_user, expected_password):
    auth_header = headers.get("authorization") or headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Basic "):
        return False
    try:
        decoded = ubinascii.a2b_base64(auth_header[6:]).decode()
        user, password = decoded.split(":", 1)
    except Exception:
        return False
    return user == expected_user and password == expected_password
