-- Optional Supabase/PostgreSQL schema - only used if SUPABASE_ENABLED=true
-- App runs without DB; create these when persistence needed

-- Enable UUID
create extension if not exists "uuid-ossp";

-- Projects / sessions
create table if not exists projects (
  id uuid primary key default uuid_generate_v4(),
  name text not null,
  description text,
  created_at timestamptz default now()
);

-- Documents (RAG metadata)
create table if not exists documents (
  id uuid primary key default uuid_generate_v4(),
  project_id uuid references projects(id) on delete cascade,
  filename text not null,
  storage_path text,
  mime_type text,
  created_at timestamptz default now()
);

-- Queries / solves
create table if not exists interactions (
  id uuid primary key default uuid_generate_v4(),
  project_id uuid references projects(id) on delete cascade,
  query text not null,
  answer text,
  sources jsonb,
  metadata jsonb,
  created_at timestamptz default now()
);

-- Indexes
create index if not exists idx_interactions_project on interactions(project_id);
create index if not exists idx_documents_project on documents(project_id);

-- ===========================================================================
-- FoodLink Predict (append-only; existing tables above are untouched)
-- ===========================================================================
-- The offline default is SQLite via backend/data/foodlink_predict.db, created by
-- SQLAlchemy on first use (see app/projects/foodlink_predict/models.py). This
-- file is the equivalent DDL for a Postgres/Supabase deployment.
--
-- Multi-tenancy: every tenant-owned table is keyed on (org_id, id) so the same
-- natural id (e.g. 'loc_main_canteen') can exist independently per organization.
-- With SUPABASE_ENABLED=true, add the RLS policies shown at the end of this file.

create table if not exists flp_organizations (
  id text primary key,
  name text not null,
  type text not null default 'cafeteria',   -- restaurant | supermarket | cafeteria | hotel | demo
  timezone text not null default 'UTC',
  created_at timestamptz not null default now()
);

create table if not exists flp_locations (
  id text not null,
  org_id text not null references flp_organizations(id) on delete cascade,
  name text not null,
  lat double precision not null default 0,
  lng double precision not null default 0,
  timezone text not null default 'UTC',
  created_at timestamptz not null default now(),
  primary key (org_id, id)
);

create table if not exists flp_items (
  id text not null,
  org_id text not null references flp_organizations(id) on delete cascade,
  name text not null,
  category text not null default 'other',
  unit text not null default 'portion',
  shelf_life_hours double precision not null default 24,
  food_class text not null default 'cooked',   -- cooked | chilled | packaged | produce
  unit_cost double precision not null default 0,
  unit_price double precision not null default 0,
  unit_weight_kg double precision not null default 0.35,
  created_at timestamptz not null default now(),
  primary key (org_id, id)
);

create table if not exists flp_batches (
  id text not null,
  org_id text not null references flp_organizations(id) on delete cascade,
  item_id text not null,
  location_id text not null,
  qty double precision not null default 0,
  received_or_prepared_at timestamptz not null,
  expires_at timestamptz not null,
  storage text not null default 'ambient',     -- hot | chilled | ambient | frozen
  created_at timestamptz not null default now(),
  primary key (org_id, id)
);

create table if not exists flp_sales_daily (
  id bigserial primary key,
  org_id text not null references flp_organizations(id) on delete cascade,
  date date not null,
  item_id text not null,
  location_id text not null,
  qty_sold double precision not null default 0,
  promo_flag boolean not null default false,
  revenue double precision not null default 0,
  source text not null default 'uploaded',     -- uploaded | synthetic
  unique (org_id, date, item_id, location_id)
);

create table if not exists flp_calendar_days (
  id bigserial primary key,
  org_id text not null references flp_organizations(id) on delete cascade,
  date date not null,
  region text not null default 'default',
  is_holiday boolean not null default false,
  holiday_name text,
  day_of_week integer not null default 0,
  weather text,
  unique (org_id, date)
);

create table if not exists flp_forecasts (
  id bigserial primary key,
  org_id text not null references flp_organizations(id) on delete cascade,
  item_id text not null,
  location_id text not null,
  target_date date not null,
  p10 double precision not null default 0,
  p50 double precision not null default 0,
  p90 double precision not null default 0,
  model_version text not null default 'unknown',
  method text not null default 'model',        -- model | cold_start
  created_at timestamptz not null default now(),
  unique (org_id, item_id, location_id, target_date, model_version)
);

create table if not exists flp_waste_risk (
  id bigserial primary key,
  org_id text not null references flp_organizations(id) on delete cascade,
  batch_id text not null,
  computed_at timestamptz not null,
  expected_unsold double precision not null default 0,
  risk double precision not null default 0,
  urgency_hours double precision not null default 0,
  donate_by timestamptz,
  priority double precision not null default 0,
  detail jsonb not null default '{}'::jsonb
);

create table if not exists flp_recommendations (
  id text not null,
  org_id text not null references flp_organizations(id) on delete cascade,
  batch_id text not null,
  action text not null,
  rationale text not null default '',
  tool_trace jsonb not null default '[]'::jsonb,
  status text not null default 'proposed',     -- proposed | accepted | rejected | done
  quantity double precision not null default 0,
  deadline timestamptz,
  evidence jsonb not null default '{}'::jsonb,
  validation_status text not null default 'unknown',
  validation_errors jsonb not null default '[]'::jsonb,
  model_version text not null default 'unknown',
  created_at timestamptz not null default now(),
  primary key (org_id, id)
);

-- The single FoodLink-facing table. Field names follow the PDF's proposed
-- contract; app/projects/foodlink_predict/adapters/ maps them.
create table if not exists flp_surplus_listings (
  id text not null,
  org_id text not null references flp_organizations(id) on delete cascade,
  recommendation_id text,
  location_id text not null,
  lat double precision not null default 0,
  lng double precision not null default 0,
  items jsonb not null default '[]'::jsonb,
  ready_at timestamptz,
  donate_by timestamptz,
  storage text not null default 'ambient',
  confidence double precision not null default 0,
  status text not null default 'forecast',     -- forecast | confirmed | withdrawn
  source text not null default 'waste-predictor',
  qty_kg double precision not null default 0,
  external_ref text,
  withdrawn_reason text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (org_id, id)
);

create table if not exists flp_impact_events (
  id bigserial primary key,
  org_id text not null references flp_organizations(id) on delete cascade,
  recommendation_id text,
  location_id text,
  kg_saved double precision not null default 0,
  meals double precision not null default 0,
  money_saved double precision not null default 0,
  co2e_kg double precision not null default 0,
  action_type text not null default 'donate',
  recorded_at timestamptz not null default now(),
  detail jsonb not null default '{}'::jsonb
);

-- Observability: one row per FLP run. Metadata only - never prompts or secrets.
create table if not exists flp_runs (
  id text primary key,
  org_id text not null,
  request_id text not null default '',
  stage text not null default '',
  model_version text not null default '',
  status text not null default 'ok',
  duration_ms double precision not null default 0,
  tool_calls jsonb not null default '[]'::jsonb,
  detail jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

-- Indexes for the hot read paths
create index if not exists ix_flp_sales_org_date on flp_sales_daily (org_id, date);
create index if not exists ix_flp_sales_series on flp_sales_daily (org_id, item_id, location_id);
create index if not exists ix_flp_forecast_lookup on flp_forecasts (org_id, item_id, location_id, target_date);
create index if not exists ix_flp_risk_org on flp_waste_risk (org_id, computed_at);
create index if not exists ix_flp_risk_batch on flp_waste_risk (org_id, batch_id);
create index if not exists ix_flp_rec_org_status on flp_recommendations (org_id, status);
create index if not exists ix_flp_listing_org_status on flp_surplus_listings (org_id, status);
create index if not exists ix_flp_impact_org on flp_impact_events (org_id, recorded_at);
create index if not exists ix_flp_batches_item on flp_batches (org_id, item_id);
create index if not exists ix_flp_batches_location on flp_batches (org_id, location_id);

-- ---------------------------------------------------------------------------
-- Supabase row-level security (apply only when SUPABASE_ENABLED=true).
-- Scope every table to the signed-in organization. The API already filters by
-- org_id; RLS is the second, database-enforced layer.
-- ---------------------------------------------------------------------------
-- alter table flp_items enable row level security;
-- alter table flp_locations enable row level security;
-- alter table flp_batches enable row level security;
-- alter table flp_sales_daily enable row level security;
-- alter table flp_calendar_days enable row level security;
-- alter table flp_forecasts enable row level security;
-- alter table flp_waste_risk enable row level security;
-- alter table flp_recommendations enable row level security;
-- alter table flp_surplus_listings enable row level security;
-- alter table flp_impact_events enable row level security;
--
-- create policy flp_items_tenant on flp_items
--   using (org_id = (auth.jwt() ->> 'org_id'));
-- create policy flp_locations_tenant on flp_locations
--   using (org_id = (auth.jwt() ->> 'org_id'));
-- create policy flp_batches_tenant on flp_batches
--   using (org_id = (auth.jwt() ->> 'org_id'));
-- create policy flp_sales_tenant on flp_sales_daily
--   using (org_id = (auth.jwt() ->> 'org_id'));
-- create policy flp_calendar_tenant on flp_calendar_days
--   using (org_id = (auth.jwt() ->> 'org_id'));
-- create policy flp_forecasts_tenant on flp_forecasts
--   using (org_id = (auth.jwt() ->> 'org_id'));
-- create policy flp_risk_tenant on flp_waste_risk
--   using (org_id = (auth.jwt() ->> 'org_id'));
-- create policy flp_recs_tenant on flp_recommendations
--   using (org_id = (auth.jwt() ->> 'org_id'));
-- create policy flp_listings_tenant on flp_surplus_listings
--   using (org_id = (auth.jwt() ->> 'org_id'));
-- create policy flp_impact_tenant on flp_impact_events
--   using (org_id = (auth.jwt() ->> 'org_id'));
