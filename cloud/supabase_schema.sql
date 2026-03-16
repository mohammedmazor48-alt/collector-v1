create extension if not exists pgcrypto;

create table if not exists tasks (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  status text not null default 'pending',
  task_type text not null,
  source_url text,
  storage_path text,
  title text,
  tags jsonb not null default '[]'::jsonb,
  note text,
  submitted_by text,
  priority int not null default 100,
  result_doc_id text,
  result_note_path text,
  result_meta_path text,
  result_summary text,
  error_message text
);

create index if not exists idx_tasks_status_priority_created
on tasks(status, priority, created_at);

create index if not exists idx_tasks_created_at
on tasks(created_at desc);

create or replace function set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

drop trigger if exists trg_tasks_updated_at on tasks;
create trigger trg_tasks_updated_at
before update on tasks
for each row
execute function set_updated_at();

create table if not exists task_logs (
  id bigserial primary key,
  task_id uuid not null references tasks(id) on delete cascade,
  created_at timestamptz not null default now(),
  level text not null,
  message text not null
);

create index if not exists idx_task_logs_task_id_created_at
on task_logs(task_id, created_at);

comment on table tasks is 'collector-v1 remote submission tasks';
comment on table task_logs is 'collector-v1 task processing logs';
