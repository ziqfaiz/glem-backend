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

The backend exposes three endpoints: `GET /health` checks the database connection,
`POST /tables` creates a table, and `POST /tables/upsert` writes rows to an
existing table.

```bash
curl -X POST http://localhost:8002/tables \
  -H "Content-Type: application/json" \
  -d '{"schema":"public","table_name":"glem_transactions","primary_key":["transaction_id"],"columns":[{"column_name":"transaction_id","ordinal_position":1,"data_type":"VARCHAR","is_nullable":"NO"},{"column_name":"amount","ordinal_position":2,"data_type":"DOUBLE","is_nullable":"YES"}]}'
```

`POST /tables` requires `schema`, `table_name`, a `primary_key` array, and source
column metadata in `columns`. It creates the table only and returns `409` when the
table already exists. Each column uses `column_name`, `ordinal_position`, `data_type`,
and `is_nullable`; unrelated metadata fields are ignored. Column order follows
`ordinal_position`. Composite primary keys are supported.

```bash
curl -X POST http://localhost:8002/tables/upsert \
  -H "Content-Type: application/json" \
  -d '{"schema":"public","table_name":"glem_transactions","rows":[{"transaction_id":"TX001","amount":1250,"status":"COMPLETED"}]}'
```

`POST /tables/upsert` requires an existing table and does not accept `primary_key`.
It discovers the table's single primary key, then inserts new rows or updates matching
rows. Schema, table, field, and primary-key names must start with a letter and may
contain letters, digits, and underscores.

## Database tables

The RDS database contains `public.input` and `public.output`. Both tables share the
same transaction columns and are range-partitioned by `created_dt`. The SQL used to
create them is in `migrations/001_create_public_tables.sql`.
