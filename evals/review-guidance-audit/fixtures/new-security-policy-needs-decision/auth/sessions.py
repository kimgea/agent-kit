SESSION_HOURS = 24


def expires_at(created_at):
    return created_at.add_hours(SESSION_HOURS)
