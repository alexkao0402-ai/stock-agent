-- Applied and verified 2026-10-08 UTC on the approved project.
-- Backend service_role only, never browser access. Not idempotent: do not rerun.
-- One row is the authority for the published archive, not a mutable bucket file.
begin;
create table public.v3_writer_head (
  stream text primary key check (stream = 'V3_ACCOUNTING'),
  owner uuid,
  fence bigint not null default 0,
  expires_at timestamptz,
  revision bigint not null default 0,
  archive_sha256 text check (archive_sha256 ~ '^[0-9a-f]{64}$'),
  ledger_head_sha256 text check (ledger_head_sha256 ~ '^[0-9a-f]{64}$')
);
insert into public.v3_writer_head(stream) values ('V3_ACCOUNTING');
alter table public.v3_writer_head enable row level security;
revoke all on public.v3_writer_head from public, anon, authenticated, service_role;

create function public.v3_acquire(p_owner uuid, p_ttl integer)
returns public.v3_writer_head language plpgsql security definer set search_path = '' as $$
declare h public.v3_writer_head;
begin
  if p_owner is null or p_ttl is null or p_ttl not between 30 and 300 then
    raise exception 'Invalid lease request';
  end if;
  select * into strict h from public.v3_writer_head where stream='V3_ACCOUNTING' for update;
  if h.expires_at > clock_timestamp() then raise exception 'Writer busy'; end if;
  update public.v3_writer_head set owner=p_owner, fence=fence+1,
    expires_at=clock_timestamp()+make_interval(secs=>p_ttl)
    where stream='V3_ACCOUNTING' returning * into h;
  return h;
end $$;

create function public.v3_renew(p_owner uuid, p_fence bigint, p_ttl integer)
returns public.v3_writer_head language plpgsql security definer set search_path = '' as $$
declare h public.v3_writer_head;
begin
  if p_ttl is null or p_ttl not between 30 and 300 then raise exception 'Invalid TTL'; end if;
  select * into strict h from public.v3_writer_head where stream='V3_ACCOUNTING' for update;
  if p_owner is null or p_fence is null or h.owner is distinct from p_owner
     or h.fence<>p_fence or h.expires_at is null or h.expires_at<=clock_timestamp() then
    raise exception 'Expired or fenced writer';
  end if;
  update public.v3_writer_head set expires_at=clock_timestamp()+make_interval(secs=>p_ttl)
    where stream='V3_ACCOUNTING' returning * into h;
  return h;
end $$;

create function public.v3_publish(p_owner uuid, p_fence bigint, p_revision bigint,
  p_archive_sha256 text, p_ledger_head_sha256 text)
returns public.v3_writer_head language plpgsql security definer set search_path = '' as $$
declare h public.v3_writer_head;
begin
  if p_archive_sha256 is null or p_ledger_head_sha256 is null
    or p_archive_sha256 !~ '^[0-9a-f]{64}$' or p_ledger_head_sha256 !~ '^[0-9a-f]{64}$' then
    raise exception 'Invalid hashes';
  end if;
  select * into strict h from public.v3_writer_head where stream='V3_ACCOUNTING' for update;
  if p_owner is null or p_fence is null or p_revision is null
    or h.owner is distinct from p_owner or h.fence<>p_fence
    or h.expires_at is null or h.expires_at<=clock_timestamp() then
    raise exception 'Expired or fenced writer';
  end if;
  -- A lost response may safely retry the exact same publication.
  if h.revision=p_revision+1 and h.archive_sha256=p_archive_sha256
    and h.ledger_head_sha256=p_ledger_head_sha256 then return h; end if;
  if h.revision<>p_revision then raise exception 'Stale cloud revision'; end if;
  update public.v3_writer_head set revision=revision+1,
    archive_sha256=p_archive_sha256, ledger_head_sha256=p_ledger_head_sha256
    where stream='V3_ACCOUNTING' returning * into h;
  return h;
end $$;

revoke all on function public.v3_acquire(uuid,integer) from public,anon,authenticated;
revoke all on function public.v3_renew(uuid,bigint,integer) from public,anon,authenticated;
revoke all on function public.v3_publish(uuid,bigint,bigint,text,text) from public,anon,authenticated;
grant execute on function public.v3_acquire(uuid,integer) to service_role;
grant execute on function public.v3_renew(uuid,bigint,integer) to service_role;
grant execute on function public.v3_publish(uuid,bigint,bigint,text,text) to service_role;
commit;
