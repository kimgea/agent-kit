# Billing review policy

Every billing storage query must constrain `tenant_id` from authenticated
context. A touched query that can cross tenant boundaries must not ship.
