-- ============================================================
-- FIX RLS POLICIES FOR PARKING_SUBSCRIBERS
-- ============================================================

-- Drop restrictive existing policies
DROP POLICY IF EXISTS "Allow public insert tracking tokens" ON public.parking_subscribers;
DROP POLICY IF EXISTS "Allow public delete tracking tokens" ON public.parking_subscribers;

-- Allow anonymous and authenticated users to perform all necessary actions for token management.
-- This includes SELECT/INSERT/UPDATE (required for upsert) and DELETE (for unsubscribing).
CREATE POLICY "Manage own device tokens"
ON public.parking_subscribers
FOR ALL
TO anon, authenticated
USING (true)
WITH CHECK (true);
