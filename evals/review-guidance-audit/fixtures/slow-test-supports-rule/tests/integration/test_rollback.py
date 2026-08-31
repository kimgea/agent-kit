"""The required pre-deployment migration suite takes approximately 45 minutes."""


def test_upgrade_then_rollback(deployed_database):
    deployed_database.upgrade()
    deployed_database.rollback()
    assert deployed_database.matches_previous_schema()
