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
