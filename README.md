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
and `POST /tables/replace` creates or replaces a table's rows.

```bash
curl -X POST http://localhost:8002/tables/replace \
  -H "Content-Type: application/json" \
  -d '{"table_name":"glem_transactions","fields":[{"sender_id":"S001","amount":1250,"status":"COMPLETED"},{"sender_id":"S002","amount":850,"status":"PENDING"}]}'
```

For a new table, column types are inferred from the supplied values. If the table
already exists, its rows are truncated before the supplied fields are inserted. Table
and field names must use lowercase letters, digits, and underscores only.

## Database tables

The RDS database contains `public.input` and `public.output`. Both tables share the
same transaction columns and are range-partitioned by `created_dt`. The SQL used to
create them is in `migrations/001_create_public_tables.sql`.
