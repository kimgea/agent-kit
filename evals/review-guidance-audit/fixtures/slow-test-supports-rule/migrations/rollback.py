def rollback(database):
    database.execute("ALTER TABLE account DROP COLUMN nickname")
