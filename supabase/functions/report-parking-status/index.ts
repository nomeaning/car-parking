// supabase/functions/report-parking-status/index.ts
//
// Deploy with: supabase functions deploy report-parking-status
//
// Called by the Raspberry Pi with a device-role JWT (see the "Device auth"
// notes from the earlier schema). Accepts multipart/form-data:
//   - time         : ISO 8601 timestamp string
//   - free_spaces  : integer, number of currently free spots
//   - image        : the snapshot file (jpeg/png)
//
// Assumes the "parking_slots" table has columns:
//   captured_at (timestamptz), free_spaces (int), snapshot_path (text)
// Rename below if your actual column names differ.

import { serve } from "https://deno.land/std@0.201.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const supabaseAdmin = createClient(
  Deno.env.get("SUPABASE_URL")!,
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
);

// Decode the JWT payload to check the custom "role" claim.
// Signature is already verified by the Supabase gateway before this
// function runs (verify_jwt = true, the default), so a plain decode is safe.
function decodeJwtPayload(token: string) {
  const payload = token.split(".")[1];
  const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
  return JSON.parse(json);
}

serve(async (req) => {
  if (req.method !== "POST") {
    return new Response("Method not allowed", { status: 405 });
  }

  const authHeader = req.headers.get("Authorization") || "";
  const token = authHeader.replace("Bearer ", "");
  if (!token) return new Response("Missing Authorization header", { status: 401 });

  let claims: Record<string, unknown>;
  try {
    claims = decodeJwtPayload(token);
  } catch {
    return new Response("Invalid token", { status: 401 });
  }

  // Accept either the custom "device" role OR standard Supabase "authenticated" users.
  // This allows the Raspberry Pi to authenticate as a user with a long-lived session.
  if (claims.role !== "device" && claims.role !== "authenticated" && claims.role !== "service_role") {
    return new Response("Forbidden: authorized role required", { status: 403 });
  }

  const form = await req.formData();
  const time = form.get("time") as string | null;
  const freeSpacesRaw = form.get("free_spaces") as string | null;
  const imageFile = form.get("image") as File | null;

  if (!time || freeSpacesRaw === null || !imageFile) {
    return new Response(
      "Missing required fields: time, free_spaces, image",
      { status: 400 },
    );
  }

  const capturedAt = new Date(time);
  if (isNaN(capturedAt.getTime())) {
    return new Response("Invalid time format, expected ISO 8601", { status: 400 });
  }

  const freeSpaces = parseInt(freeSpacesRaw, 10);
  if (isNaN(freeSpaces) || freeSpaces < 0) {
    return new Response("free_spaces must be a non-negative integer", { status: 400 });
  }

  const fileExt = (imageFile.name.split(".").pop() || "jpg").toLowerCase();
  const fileName = `${capturedAt.toISOString().replace(/[:.]/g, "-")}.${fileExt}`;
  const imageBytes = new Uint8Array(await imageFile.arrayBuffer());

  const { error: uploadError } = await supabaseAdmin.storage
    .from("parking_slots")
    .upload(fileName, imageBytes, {
      contentType: imageFile.type || "image/jpeg",
      upsert: false,
    });

  if (uploadError) {
    return new Response(`Storage upload failed: ${uploadError.message}`, { status: 500 });
  }

  const { error: insertError } = await supabaseAdmin
    .from("parking_slots")
    .insert({
      captured_at: capturedAt.toISOString(),
      free_spaces: freeSpaces,
      snapshot_path: fileName,
    });

  if (insertError) {
    // Keep storage and DB consistent if the insert fails
    await supabaseAdmin.storage.from("parking_slots").remove([fileName]);
    return new Response(`DB insert failed: ${insertError.message}`, { status: 500 });
  }

  return new Response(
    JSON.stringify({ success: true, snapshot_path: fileName }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
});
