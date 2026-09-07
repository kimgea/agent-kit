def deadline(now: int, job: dict[str, int]) -> int:
    return now + job["timeout_seconds"]

