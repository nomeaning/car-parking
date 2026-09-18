// supabase/functions/send-push-notification/index.ts
//
// Deploy with: supabase functions deploy send-push-notification --no-verify-jwt

import { serve } from "https://deno.land/std@0.201.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const supabaseAdmin = createClient(
  Deno.env.get("SUPABASE_URL")!,
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
);

// Helper function to sign a JWT assertion manually for Google OAuth2 v1 API auth token access
async function getGoogleAccessToken(serviceAccount: any): Promise<string> {
  const jwtHeader = { alg: "RS256", typ: "JWT" };
  const now = Math.floor(Date.now() / 1000);
  const jwtPayload = {
    iss: serviceAccount.client_email,
    scope: "https://www.googleapis.com/auth/firebase.messaging",
    aud: "https://oauth2.googleapis.com/token",
    exp: now + 3600,
    iat: now,
  };

  const base64UrlEncode = (str: string) =>
    btoa(str).replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");

  const unsignedToken = `${base64UrlEncode(JSON.stringify(jwtHeader))}.${base64UrlEncode(JSON.stringify(jwtPayload))}`;

  // Import the RSA private key
  const pemHeader = "-----BEGIN PRIVATE KEY-----";
  const pemFooter = "-----END PRIVATE KEY-----";
  const pemContents = serviceAccount.private_key
    .replace(pemHeader, "")
    .replace(pemFooter, "")
    .replace(/\s/g, "");
  const binaryDerString = atob(pemContents);
  const binaryDer = new Uint8Array(binaryDerString.length);
  for (let i = 0; i < binaryDerString.length; i++) {
    binaryDer[i] = binaryDerString.charCodeAt(i);
  }

  const cryptoKey = await crypto.subtle.importKey(
    "pkcs8",
    binaryDer,
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
    false,
    ["sign"]
  );

  const signature = await crypto.subtle.sign(
    "RSASSA-PKCS1-v1_5",
    cryptoKey,
    new TextEncoder().encode(unsignedToken)
  );

  const signedToken = `${unsignedToken}.${base64UrlEncode(
    String.fromCharCode(...new Uint8Array(signature))
  )}`;

  const res = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer",
      assertion: signedToken,
    }),
  });

  const data = await res.json();
  if (!res.ok) throw new Error(`OAuth token fetch failed: ${JSON.stringify(data)}`);
  return data.access_token;
}

serve(async (req) => {
  if (req.method !== "POST") {
    return new Response("Method not allowed", { status: 405 });
  }

  try {
    const { free_spaces } = await req.json();

    // 1. Fetch all registered user device device notification push tokens
    const { data: subscribers, error: dbError } = await supabaseAdmin
      .from("parking_subscribers")
      .select("fcm_token");

    if (dbError || !subscribers || subscribers.length === 0) {
      return new Response(JSON.stringify({ success: true, message: "No active subscribers found." }), { status: 200 });
    }

    // 2. Extract service account secret configuration
    const saString = Deno.env.get("FCM_SERVICE_ACCOUNT");
    if (!saString) {
      return new Response("FCM_SERVICE_ACCOUNT environment variable secret is missing", { status: 500 });
    }
    const serviceAccount = JSON.parse(saString);
    const accessToken = await getGoogleAccessToken(serviceAccount);

    // 3. Dispatch parallel FCM Push payload calls to all devices
    const projectId = serviceAccount.project_id;
    const fcmUrl = `https://fcm.googleapis.com/v1/projects/${projectId}/messages:send`;

    const sendPromises = subscribers.map(async (sub) => {
      const messagePayload = {
        message: {
          token: sub.fcm_token,
          notification: {
            title: "Звільнилось паркомісце! 🚗",
            body: `З'явились нові вільні місця на парковці: ${free_spaces} вільних місць доступно.`,
          },
          android: {
            priority: "high",
            notification: {
              sound: "default",
              channel_id: "parking_alerts"
            }
          },
          apns: { payload: { aps: { sound: "default" } } },
        },
      };

      return fetch(fcmUrl, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${accessToken}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(messagePayload),
      });
    });

    await Promise.all(sendPromises);

    return new Response(JSON.stringify({ success: true, sent_count: subscribers.length }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  } catch (error: any) {
    return new Response(JSON.stringify({ error: error.message }), { status: 500 });
  }
});
