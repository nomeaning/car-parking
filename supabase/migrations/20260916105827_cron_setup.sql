-- ============================================================
-- SCHEDULE HOURLY CLEANUP OF OLD PARKING SNAPSHOTS
-- ============================================================
-- Option A (recommended, easiest): Supabase Dashboard > Edge Functions >
-- your "cleanup-old-snapshots" function > Cron tab > add a schedule like
-- "0 * * * *" and set the x-cron-secret header there. No SQL needed.
--
-- Option B: schedule it yourself with pg_cron + pg_net, run once in the
-- SQL editor. Replace <project-ref> and <CRON_SECRET_VALUE> below.

create extension if not exists pg_cron;
create extension if not exists pg_net;

select cron.schedule(
  'cleanup-old-parking-snapshots',
  '0 * * * *',  -- every hour, on the hour
  $$
  select net.http_post(
    url := 'https://tlsvizqmjdasvnwztlum.functions.supabase.co/cleanup-old-snapshots',
    headers := jsonb_build_object(
      'Content-Type', 'application/json',
      'x-cron-secret', '7f8b2c4e9a1d3f6e8b5a2c9d4f1e7a3b6c8d2e5f9a1b4c7d3e6f8a2b5c9d1e4f'
    ),
    body := '{}'::jsonb
  );
  $$
);

-- To inspect scheduled jobs:
-- select * from cron.job;

-- To remove it later:
-- select cron.unschedule('cleanup-old-parking-snapshots');
