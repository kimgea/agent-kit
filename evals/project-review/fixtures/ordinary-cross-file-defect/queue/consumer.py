def deadline(now, job):
    return now + job["timeout_seconds"]
