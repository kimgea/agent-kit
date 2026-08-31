def parse_value(text):
    try:
        return int(text)
    except ValueError:
        return None
