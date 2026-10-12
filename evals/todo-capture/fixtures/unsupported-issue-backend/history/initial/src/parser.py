def parse_ids(raw):
    return [part.strip() for part in raw.split(",")]

def parse_tags(raw):
    return [part.strip() for part in raw.split(",")]
