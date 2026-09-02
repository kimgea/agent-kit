def run(command):
    return command


def routine_checks():
    return [
        run("ruff check ."),
        run("python -m mypy src"),
        run("ruff check ."),
    ]
