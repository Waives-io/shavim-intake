-- =====================================================================
-- עמותת שווים · קליטת מתמודד חדש · Supabase setup
-- Run once in Supabase → SQL Editor → New query → Run.
-- Safe to re-run (idempotent).
-- =====================================================================

create extension if not exists pgcrypto;

-- ---------- Staff (who may open the dashboard) ----------
create table if not exists public.staff (
  email text primary key
);
insert into public.staff(email) values ('noa@amutatshavim.co.il') on conflict do nothing;

create or replace function public.is_staff()
returns boolean language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from public.staff
    where lower(email) = lower(coalesce(auth.jwt() ->> 'email', ''))
  );
$$;

-- ---------- Requests ----------
create table if not exists public.requests (
  id                  uuid primary key default gen_random_uuid(),
  token               uuid not null unique default gen_random_uuid(),  -- secret, in the referrer's personal link
  participant_name    text not null,
  participant_id      text not null,
  ref_name            text not null,
  ref_email           text not null,
  ref_phone           text not null,
  status              text not null default 'in_progress'
                      check (status in ('in_progress','submitted','approved')),
  possible_duplicate  boolean not null default false,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  submitted_at        timestamptz,
  approved_at         timestamptz,
  thanks_sent_at      timestamptz,
  last_reminder_at    timestamptz,
  folder_name         text,
  last_download_at    timestamptz,
  fully_downloaded_at timestamptz,
  purged_at           timestamptz
);
create index if not exists requests_participant_id_idx on public.requests(participant_id);

-- ---------- Files ----------
create table if not exists public.files (
  id            uuid primary key default gen_random_uuid(),
  request_id    uuid not null references public.requests(id) on delete cascade,
  doc_type      text not null check (doc_type in ('committee','psychiatric','social','medical','idcard')),
  original_name text not null,
  storage_path  text not null unique,
  size_bytes    bigint,
  mime          text,
  uploaded_at   timestamptz not null default now(),
  downloaded_at timestamptz
);
create index if not exists files_request_idx on public.files(request_id);

-- ---------- Row level security: only staff read/write tables directly ----------
alter table public.staff    enable row level security;
alter table public.requests enable row level security;
alter table public.files    enable row level security;

drop policy if exists staff_read_staff on public.staff;
create policy staff_read_staff on public.staff for select to authenticated using (public.is_staff());

drop policy if exists staff_all_requests on public.requests;
create policy staff_all_requests on public.requests for all to authenticated
  using (public.is_staff()) with check (public.is_staff());

drop policy if exists staff_all_files on public.files;
create policy staff_all_files on public.files for all to authenticated
  using (public.is_staff()) with check (public.is_staff());

-- =====================================================================
-- Referrer API (anonymous). Access only through the secret token.
-- =====================================================================

create or replace function public._req_json(r public.requests)
returns jsonb language sql stable security definer set search_path = public as $$
  select jsonb_build_object(
    'token', r.token,
    'participant_name', r.participant_name,
    'participant_id', r.participant_id,
    'ref_name', r.ref_name,
    'ref_email', r.ref_email,
    'ref_phone', r.ref_phone,
    'status', r.status,
    'created_at', r.created_at,
    'files', coalesce((
      select jsonb_agg(jsonb_build_object(
        'id', f.id, 'doc_type', f.doc_type, 'original_name', f.original_name,
        'size_bytes', f.size_bytes, 'uploaded_at', f.uploaded_at,
        'locked', f.downloaded_at is not null) order by f.uploaded_at)
      from public.files f where f.request_id = r.id), '[]'::jsonb)
  );
$$;

create or replace function public._check_details(p jsonb)
returns void language plpgsql immutable as $$
begin
  if coalesce(trim(p->>'participant_name'),'') = '' or length(p->>'participant_name') > 120 then raise exception 'bad_participant_name'; end if;
  if coalesce(p->>'participant_id','') !~ '^\d{9}$' then raise exception 'bad_participant_id'; end if;
  if coalesce(trim(p->>'ref_name'),'') = '' or length(p->>'ref_name') > 120 then raise exception 'bad_ref_name'; end if;
  if coalesce(p->>'ref_email','') !~* '^[^@\s]+@[^@\s]+\.[^@\s]+$' or length(p->>'ref_email') > 200 then raise exception 'bad_ref_email'; end if;
  if coalesce(p->>'ref_phone','') !~ '^05\d-\d{7}$' then raise exception 'bad_ref_phone'; end if;
end $$;

-- Create (token null) or update (token given) a request. Returns the request json.
create or replace function public.intake_save(p_token uuid, p jsonb)
returns jsonb language plpgsql security definer set search_path = public as $$
declare r public.requests; dup boolean;
begin
  perform public._check_details(p);
  if p_token is null then
    -- Same ID + same referrer email on an open request → continue that request (no duplicates)
    select * into r from public.requests
      where participant_id = p->>'participant_id'
        and lower(ref_email) = lower(p->>'ref_email')
        and status <> 'approved'
      order by created_at desc limit 1;
    if not found then
      select exists(select 1 from public.requests where participant_id = p->>'participant_id') into dup;
      insert into public.requests(participant_name, participant_id, ref_name, ref_email, ref_phone, possible_duplicate)
      values (trim(p->>'participant_name'), p->>'participant_id', trim(p->>'ref_name'), lower(trim(p->>'ref_email')), p->>'ref_phone', dup)
      returning * into r;
      return public._req_json(r) || jsonb_build_object('merged', false);
    end if;
    update public.requests set
      participant_name = trim(p->>'participant_name'), ref_name = trim(p->>'ref_name'),
      ref_phone = p->>'ref_phone', updated_at = now()
    where id = r.id returning * into r;
    return public._req_json(r) || jsonb_build_object('merged', true);
  end if;

  update public.requests set
    participant_name = trim(p->>'participant_name'), participant_id = p->>'participant_id',
    ref_name = trim(p->>'ref_name'), ref_email = lower(trim(p->>'ref_email')),
    ref_phone = p->>'ref_phone', updated_at = now()
  where token = p_token and status <> 'approved'
  returning * into r;
  if not found then raise exception 'not_found_or_closed'; end if;
  return public._req_json(r) || jsonb_build_object('merged', false);
end $$;

create or replace function public.intake_get(p_token uuid)
returns jsonb language plpgsql stable security definer set search_path = public as $$
declare r public.requests;
begin
  select * into r from public.requests where token = p_token;
  if not found then raise exception 'not_found'; end if;
  return public._req_json(r);
end $$;

-- Register a file after it was uploaded to storage under "<token>/..."
create or replace function public.intake_add_file(p_token uuid, p_doc_type text, p_path text, p_name text, p_size bigint, p_mime text)
returns jsonb language plpgsql security definer set search_path = public, storage as $$
declare r public.requests;
begin
  select * into r from public.requests where token = p_token and status <> 'approved';
  if not found then raise exception 'not_found_or_closed'; end if;
  if p_path not like p_token::text || '/%' then raise exception 'bad_path'; end if;
  if not exists (select 1 from storage.objects where bucket_id = 'intake' and name = p_path) then raise exception 'file_missing'; end if;
  insert into public.files(request_id, doc_type, original_name, storage_path, size_bytes, mime)
  values (r.id, p_doc_type, left(p_name, 200), p_path, p_size, left(p_mime, 120));
  update public.requests set updated_at = now(), fully_downloaded_at = null where id = r.id returning * into r;
  return public._req_json(r);
end $$;

-- Remove a file the referrer uploaded by mistake (only before Noa downloaded it)
create or replace function public.intake_remove_file(p_token uuid, p_file_id uuid)
returns jsonb language plpgsql security definer set search_path = public as $$
declare r public.requests;
begin
  select * into r from public.requests where token = p_token and status <> 'approved';
  if not found then raise exception 'not_found_or_closed'; end if;
  delete from public.files where id = p_file_id and request_id = r.id and downloaded_at is null;
  update public.requests set updated_at = now() where id = r.id returning * into r;
  return public._req_json(r);
end $$;

-- Send: requires all three mandatory documents
create or replace function public.intake_submit(p_token uuid)
returns jsonb language plpgsql security definer set search_path = public as $$
declare r public.requests; missing int;
begin
  select * into r from public.requests where token = p_token and status <> 'approved';
  if not found then raise exception 'not_found_or_closed'; end if;
  select count(*) into missing from unnest(array['committee','psychiatric','social']) t(d)
    where not exists (select 1 from public.files f where f.request_id = r.id and f.doc_type = t.d);
  if missing > 0 then raise exception 'missing_required'; end if;
  update public.requests set status = 'submitted', submitted_at = coalesce(submitted_at, now()), updated_at = now()
    where id = r.id returning * into r;
  return public._req_json(r);
end $$;

-- Keep-alive ping (used by the GitHub Action so the free project is never paused)
create or replace function public.ping() returns text language sql stable as $$ select 'ok' $$;

revoke all on function public.intake_save(uuid, jsonb), public.intake_get(uuid), public.intake_add_file(uuid,text,text,text,bigint,text),
  public.intake_remove_file(uuid,uuid), public.intake_submit(uuid), public.ping() from public;
grant execute on function public.intake_save(uuid, jsonb), public.intake_get(uuid), public.intake_add_file(uuid,text,text,text,bigint,text),
  public.intake_remove_file(uuid,uuid), public.intake_submit(uuid), public.ping() to anon, authenticated;
revoke all on function public._req_json(public.requests), public._check_details(jsonb) from public, anon, authenticated;

-- =====================================================================
-- Storage: private bucket "intake"
-- =====================================================================
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('intake', 'intake', false, 15728640, array[
  'application/pdf','image/jpeg','image/png','image/webp','image/heic','image/heif',
  'application/msword','application/vnd.openxmlformats-officedocument.wordprocessingml.document'])
on conflict (id) do update set public = false, file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

create or replace function public.is_open_token(t text)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.requests where token::text = t and status <> 'approved');
$$;
grant execute on function public.is_open_token(text) to anon, authenticated;

drop policy if exists intake_upload on storage.objects;
create policy intake_upload on storage.objects for insert to anon, authenticated
  with check (bucket_id = 'intake' and public.is_open_token((storage.foldername(name))[1]));

drop policy if exists intake_staff_read on storage.objects;
create policy intake_staff_read on storage.objects for select to authenticated
  using (bucket_id = 'intake' and public.is_staff());

drop policy if exists intake_staff_delete on storage.objects;
create policy intake_staff_delete on storage.objects for delete to authenticated
  using (bucket_id = 'intake' and public.is_staff());
