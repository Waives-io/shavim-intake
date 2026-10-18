-- Minimal stand-in for the Supabase parts setup.sql relies on
create role anon nologin; create role authenticated nologin; create role service_role nologin;
-- Supabase grants everything in public to these roles by default; setup.sql must take it back
alter default privileges in schema public grant all on tables to anon, authenticated, service_role;
alter default privileges in schema public grant all on functions to anon, authenticated, service_role;
grant usage on schema public to anon, authenticated, service_role;
create schema auth;
create function auth.jwt() returns jsonb language sql stable as $$ select coalesce(nullif(current_setting('request.jwt.claims', true), ''), '{}')::jsonb $$;
grant usage on schema auth to anon, authenticated;
create schema storage;
create table storage.buckets(id text primary key, name text, public boolean, file_size_limit bigint, allowed_mime_types text[]);
create table storage.objects(id uuid primary key default gen_random_uuid(), bucket_id text, name text, metadata jsonb);
alter table storage.objects enable row level security;
create function storage.foldername(name text) returns text[] language plpgsql immutable as $$
declare _parts text[]; begin _parts := string_to_array(name, '/'); return _parts[1:array_length(_parts,1)-1]; end $$;
grant usage on schema storage to anon, authenticated;
grant select, insert, delete on storage.objects to anon, authenticated;
