# Glem destination backend

A Dockerized FastAPI service for writing transformed Glem records to PostgreSQL RDS.

## Start

```bash
docker compose up --build
```

Then open:

- API documentation: http://localhost:8002/docs
- Health check: http://localhost:8002/health
Copy `.env.example` to `.env`, replace `CHANGE_ME` with the RDS password, and keep
the resulting `.env` file private. It is excluded from Git.

## API

The backend exposes two endpoints: `GET /health` checks the database connection,
and `POST /tables/upsert` creates a keyed table or upserts its rows.

```bash
curl -X POST http://localhost:8002/tables/upsert \
  -H "Content-Type: application/json" \
  -d '{"schema":"public","table_name":"glem_transactions","primary_key":"transaction_id","rows":[{"transaction_id":"TX001","amount":1250,"status":"COMPLETED"},{"transaction_id":"TX002","amount":850,"status":"PENDING"}]}'
```

`schema` selects an existing PostgreSQL schema, such as `public`. For a new table,
`primary_key` is required and becomes its primary-key column. If the table already
exists, `primary_key` may be omitted and the API discovers the table's single
primary key automatically. Incoming rows are inserted or updated by that key; rows
not included in the request remain unchanged. New-table columns keep the order in
which their names first appear in `rows`. Schema, table, field, and primary-key names
must use lowercase letters, digits, and underscores only.

## Database tables

The RDS database contains `public.input` and `public.output`. Both tables share the
same transaction columns and are range-partitioned by `created_dt`. The SQL used to
create them is in `migrations/001_create_public_tables.sql`.
