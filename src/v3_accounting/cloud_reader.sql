-- Additive read-only endpoint. No leases, ledger writes or public access.
begin;
create function public.v3_read_head()
returns table(stream text, revision bigint, archive_sha256 text, ledger_head_sha256 text)
language sql stable security definer set search_path = '' as $$
  select stream, revision, archive_sha256, ledger_head_sha256
  from public.v3_writer_head where stream = 'V3_ACCOUNTING';
$$;
revoke all on function public.v3_read_head() from public, anon, authenticated;
grant execute on function public.v3_read_head() to service_role;
commit;
