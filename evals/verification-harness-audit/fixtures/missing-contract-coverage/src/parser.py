def parse_port(value):
    port = int(value)
    if port < 1 or port > 65535:
        raise ValueError("port out of range")
    return port
