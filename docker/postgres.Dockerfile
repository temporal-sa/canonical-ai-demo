# Postgres, seeded on first boot. Deployed as a single in-cluster pod; data is
# ephemeral (resets if the pod is replaced) — fine for a demo. Orders are scoped
# per-conversation (keyed by workflow ID, see activities/db.py), so concurrent
# demoers stay isolated and back-to-back runs start clean with no reset needed.
#
# NOTE: don't set POSTGRES_DB=music — seed.sql CREATEs the database itself
# (it can't DROP the DB it's connected to). Leave the default and let it run.
FROM postgres:16

COPY db/seed.sql  /docker-entrypoint-initdb.d/01-seed.sql
