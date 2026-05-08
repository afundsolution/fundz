-- FUNDz live memory schema for Supabase/Postgres.
--
-- This schema stores the same operational client brain that FUNDz builds from
-- local DisputeFox exports, plus a durable event log for future live workflows.

create table if not exists fundz_memory_snapshots (
  id bigserial primary key,
  generated_at timestamptz not null default now(),
  source text not null default 'fundz_operational_state',
  source_hash text not null unique,
  state jsonb not null,
  summary jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists fundz_client_memory (
  client_key text primary key,
  client_name text not null default '',
  normalized_name text not null default '',
  email text not null default '',
  is_active_client boolean not null default false,
  status text not null default '',
  stage_in_process text not null default '',
  next_import text not null default '',
  next_import_days integer,
  assigned_to text not null default '',
  dispute_round jsonb not null default '{}'::jsonb,
  operational_flags text[] not null default '{}'::text[],
  recommended_next_action text not null default '',
  send_history jsonb not null default '{}'::jsonb,
  dispute_items jsonb not null default '{}'::jsonb,
  sources text[] not null default '{}'::text[],
  profile jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create index if not exists fundz_client_memory_normalized_name_idx
  on fundz_client_memory (normalized_name);

create index if not exists fundz_client_memory_email_idx
  on fundz_client_memory (email);

create index if not exists fundz_client_memory_active_idx
  on fundz_client_memory (is_active_client);

create index if not exists fundz_client_memory_flags_gin_idx
  on fundz_client_memory using gin (operational_flags);

create table if not exists fundz_memory_events (
  id bigserial primary key,
  event_time timestamptz not null default now(),
  event_type text not null,
  client_key text references fundz_client_memory(client_key) on delete set null,
  source text not null default '',
  payload jsonb not null default '{}'::jsonb
);

create index if not exists fundz_memory_events_time_idx
  on fundz_memory_events (event_time desc);

create index if not exists fundz_memory_events_client_idx
  on fundz_memory_events (client_key);

create or replace view fundz_active_client_memory as
select
  client_key,
  client_name,
  email,
  status,
  stage_in_process,
  next_import,
  next_import_days,
  assigned_to,
  operational_flags,
  recommended_next_action,
  updated_at
from fundz_client_memory
where is_active_client = true;
