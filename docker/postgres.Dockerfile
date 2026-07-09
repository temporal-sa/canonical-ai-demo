# Postgres, seeded on first boot. Deployed as a single in-cluster pod;
# data is ephemeral (resets if the pod is replaced) — fine for a demo, and the
# per-email isolation keeps concurrent demoers' orders separate.
#
# NOTE: don't set POSTGRES_DB=music — seed.sql CREATEs the database itself
# (it can't DROP the DB it's connected to). Leave the default and let it run.
FROM postgres:16

COPY db/seed.sql           /docker-entrypoint-initdb.d/01-seed.sql
COPY db/demo-customer.sql  /docker-entrypoint-initdb.d/02-demo-customer.sql
