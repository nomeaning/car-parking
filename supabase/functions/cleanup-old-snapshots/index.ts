// supabase/functions/cleanup-old-snapshots/index.ts
//
// Deploy with: supabase functions deploy cleanup-old-snapshots --no-verify-jwt
//
// This is a maintenance job, not something the Pi or the app calls directly,
// so it's protected by a shared secret header instead of a user JWT.
// Set the secret with: supabase secrets set CRON_SECRET=<some-long-random-value>
//
// It is triggered on a schedule (see cron_setup.sql) rather than run inline
// on every ingest request, so a busy ingest path never pays for cleanup work.

import { serve } from "https://deno.land/std@0.201.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const supabaseAdmin = createClient(
  Deno.env.get("SUPABASE_URL")!,
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
);

serve(async (req) => {
  const providedSecret = req.headers.get("x-cron-secret");
  if (providedSecret !== Deno.env.get("CRON_SECRET")) {
    return new Response("Forbidden", { status: 403 });
  }

  const cutoff = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();

  const { data: oldRows, error: selectError } = await supabaseAdmin
    .from("parking_slots")
    .select("id, snapshot_path")
    .lt("captured_at", cutoff);

  if (selectError) {
    return new Response(`Select failed: ${selectError.message}`, { status: 500 });
  }

  if (!oldRows || oldRows.length === 0) {
    return new Response(JSON.stringify({ deleted: 0 }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }

  const paths = oldRows.map((r) => r.snapshot_path).filter(Boolean) as string[];
  if (paths.length > 0) {
    const { error: removeError } = await supabaseAdmin.storage
      .from("parking_slots")
      .remove(paths);
    if (removeError) {
      return new Response(`Storage cleanup failed: ${removeError.message}`, { status: 500 });
    }
  }

  const ids = oldRows.map((r) => r.id);
  const { error: deleteError } = await supabaseAdmin
    .from("parking_slots")
    .delete()
    .in("id", ids);

  if (deleteError) {
    return new Response(`Row delete failed: ${deleteError.message}`, { status: 500 });
  }

  return new Response(JSON.stringify({ deleted: ids.length }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
});
