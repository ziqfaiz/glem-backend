# Glem destination backend

A Dockerized FastAPI service for writing transformed Glem records to PostgreSQL RDS.

## Start

```bash
docker compose up --build
```

Then open:

- API documentation: http://localhost:8000/docs
- Health check: http://localhost:8000/health
Copy `.env.example` to `.env`, replace `CHANGE_ME` with the RDS password, and keep
the resulting `.env` file private. It is excluded from Git.

## API

The backend exposes two endpoints: `GET /health` checks the database connection,
and `POST /output/upsert` inserts or updates transformed output rows.

```bash
curl -X POST http://localhost:8000/output/upsert \
  -H "Content-Type: application/json" \
  -d '{"$items":[{"uuid":"2aaad9ed-b503-49da-9c74-e15294db42b6","sender_id":"S001","sender_name":"Alice Tan","trx_date":"2026-09-09T09:15:00","receiver_id":"R001","receiver_name":"Bob Lee","type":"TRANSFER","dc":"D","amount":1250,"status":"COMPLETED","created_dt":"2026-09-09"}]}'
```

Rows are uniquely identified by `(uuid, created_dt)`. Sending that key again updates
the existing row. Each request accepts between 1 and 1,000 items.

## Database tables

The RDS database contains `public.input` and `public.output`. Both tables share the
same transaction columns and are range-partitioned by `created_dt`. The SQL used to
create them is in `migrations/001_create_public_tables.sql`.
