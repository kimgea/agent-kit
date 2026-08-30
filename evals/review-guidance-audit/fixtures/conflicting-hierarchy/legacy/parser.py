def parse(value):
    try:
        return decode(value)
    except ValueError:
        return {}
