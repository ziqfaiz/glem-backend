CREATE TABLE IF NOT EXISTS public.input (
    uuid UUID NOT NULL,
    sender_id TEXT,
    sender_name TEXT,
    trx_date TIMESTAMP,
    receiver_id TEXT,
    receiver_name TEXT,
    type TEXT,
    dc TEXT,
    amount INTEGER,
    status TEXT,
    created_dt DATE NOT NULL
) PARTITION BY RANGE (created_dt);

CREATE TABLE IF NOT EXISTS public.input_default
    PARTITION OF public.input DEFAULT;

CREATE TABLE IF NOT EXISTS public.output (
    uuid UUID NOT NULL,
    sender_id TEXT,
    sender_name TEXT,
    trx_date TIMESTAMP,
    receiver_id TEXT,
    receiver_name TEXT,
    type TEXT,
    dc TEXT,
    amount INTEGER,
    status TEXT,
    created_dt DATE NOT NULL,
    CONSTRAINT output_uuid_created_dt_key UNIQUE (uuid, created_dt)
) PARTITION BY RANGE (created_dt);

CREATE TABLE IF NOT EXISTS public.output_default
    PARTITION OF public.output DEFAULT;

CREATE INDEX IF NOT EXISTS input_uuid_idx ON public.input (uuid);
CREATE INDEX IF NOT EXISTS input_created_dt_idx ON public.input (created_dt);
CREATE INDEX IF NOT EXISTS output_uuid_idx ON public.output (uuid);
CREATE INDEX IF NOT EXISTS output_created_dt_idx ON public.output (created_dt);
