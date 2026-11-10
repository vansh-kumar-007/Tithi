-- ============================================================================
-- Tithi V1.1 Migration — Freemium Entitlements, 14-Day Plus Trial & Google Calendar Sync
-- ============================================================================
-- Execute manually in Supabase Dashboard -> SQL Editor AFTER V1 schema.sql.
-- Safe & idempotent: preserves all existing saved_birth_profiles and calculation_history rows.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

-- ----------------------------------------------------------------------------
-- 1. user_entitlements (Server-managed Free / 14-Day Trial / Plus state)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.user_entitlements (
  user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  plan text NOT NULL DEFAULT 'free' CHECK (plan IN ('free', 'plus')),
  trial_status text NOT NULL DEFAULT 'eligible' CHECK (trial_status IN ('eligible', 'active', 'expired')),
  trial_started_at timestamptz NULL,
  trial_expires_at timestamptz NULL,
  trial_used boolean NOT NULL DEFAULT false,
  subscription_status text NOT NULL DEFAULT 'none' CHECK (
    subscription_status IN ('none', 'active', 'past_due', 'cancelled', 'expired')
  ),
  subscription_provider text NULL,
  subscription_reference text NULL,
  current_period_start timestamptz NULL,
  current_period_end timestamptz NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT user_entitlements_trial_dates CHECK (
    trial_expires_at IS NULL
    OR trial_started_at IS NULL
    OR trial_expires_at > trial_started_at
  )
);

CREATE INDEX IF NOT EXISTS idx_user_entitlements_plan_trial
  ON public.user_entitlements (plan, trial_status, trial_expires_at);

DROP TRIGGER IF EXISTS trg_user_entitlements_updated_at ON public.user_entitlements;
CREATE TRIGGER trg_user_entitlements_updated_at
  BEFORE UPDATE ON public.user_entitlements
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

REVOKE ALL ON public.user_entitlements FROM anon, PUBLIC;
REVOKE ALL ON public.user_entitlements FROM authenticated;
GRANT SELECT ON public.user_entitlements TO authenticated;
GRANT ALL ON TABLE public.user_entitlements TO service_role;

-- Ensure server-side backend operations retain explicit service_role access on V1 tables
GRANT ALL ON TABLE public.saved_birth_profiles TO service_role;
GRANT ALL ON TABLE public.calculation_history TO service_role;

ALTER TABLE public.user_entitlements ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view own entitlements" ON public.user_entitlements;
CREATE POLICY "Users can view own entitlements"
  ON public.user_entitlements
  FOR SELECT
  TO authenticated
  USING (auth.uid() = user_id);

-- ----------------------------------------------------------------------------
-- 2. Entitlement Helper Functions & Free 3-Profile Limit Enforcement
-- ----------------------------------------------------------------------------
-- Internal 1-arg lookup (service_role / SECURITY DEFINER triggers only; never
-- directly callable by anon or authenticated via PostgREST RPC)
CREATE OR REPLACE FUNCTION public.has_active_plus_access(p_user_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.user_entitlements e
    WHERE e.user_id = p_user_id
      AND (
        (
          e.plan = 'plus'
          AND e.subscription_status = 'active'
          AND (e.current_period_end IS NULL OR e.current_period_end > now())
        )
        OR (
          e.trial_used = true
          AND e.trial_started_at IS NOT NULL
          AND e.trial_expires_at IS NOT NULL
          AND now() < e.trial_expires_at
        )
      )
  );
$$;

REVOKE ALL ON FUNCTION public.has_active_plus_access(uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.has_active_plus_access(uuid) TO service_role;

-- Zero-argument caller-scoped helper for authenticated users (uses auth.uid() only)
CREATE OR REPLACE FUNCTION public.has_active_plus_access()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT COALESCE(
    auth.uid() IS NOT NULL AND public.has_active_plus_access(auth.uid()),
    false
  );
$$;

REVOKE ALL ON FUNCTION public.has_active_plus_access() FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.has_active_plus_access() TO authenticated, service_role;

-- Zero-argument caller-scoped helper for RLS and authenticated RPC checks
CREATE OR REPLACE FUNCTION public.can_create_birth_profile()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT
    auth.uid() IS NOT NULL
    AND (
      public.has_active_plus_access(auth.uid())
      OR (
        SELECT count(*)
        FROM public.saved_birth_profiles p
        WHERE p.user_id = auth.uid()
      ) < 3
    );
$$;

REVOKE ALL ON FUNCTION public.can_create_birth_profile() FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.can_create_birth_profile() TO authenticated, service_role;

-- Atomic once-per-account 14-day Plus trial activator (service_role only)
CREATE OR REPLACE FUNCTION public.activate_plus_trial(p_user_id uuid)
RETURNS SETOF public.user_entitlements
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  IF p_user_id IS NULL THEN
    RETURN;
  END IF;

  INSERT INTO public.user_entitlements (user_id)
  VALUES (p_user_id)
  ON CONFLICT (user_id) DO NOTHING;

  RETURN QUERY
  UPDATE public.user_entitlements
  SET
    trial_used = true,
    trial_status = 'active',
    trial_started_at = now(),
    trial_expires_at = now() + interval '14 days'
  WHERE user_id = p_user_id
    AND trial_used = false
    AND trial_started_at IS NULL
    AND NOT (
      plan = 'plus'
      AND subscription_status = 'active'
      AND (current_period_end IS NULL OR current_period_end > now())
    )
  RETURNING *;
END;
$$;

REVOKE ALL ON FUNCTION public.activate_plus_trial(uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.activate_plus_trial(uuid) TO service_role;

-- Enforce Free max 3 profiles in both RLS policy and concurrent-safe trigger.
-- Existing users with > 3 profiles keep all existing rows intact and can edit/delete them.
CREATE OR REPLACE FUNCTION public.enforce_saved_birth_profile_limit()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_count integer;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext(NEW.user_id::text));

  IF public.has_active_plus_access(NEW.user_id) THEN
    RETURN NEW;
  END IF;

  SELECT count(*) INTO v_count
  FROM public.saved_birth_profiles
  WHERE user_id = NEW.user_id;

  IF v_count >= 3 THEN
    RAISE EXCEPTION 'FREE_PROFILE_LIMIT_REACHED: Free plan allows a maximum of 3 saved birth profiles.'
      USING ERRCODE = 'P0001';
  END IF;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_enforce_saved_birth_profile_limit ON public.saved_birth_profiles;
CREATE TRIGGER trg_enforce_saved_birth_profile_limit
  BEFORE INSERT ON public.saved_birth_profiles
  FOR EACH ROW
  EXECUTE FUNCTION public.enforce_saved_birth_profile_limit();

REVOKE ALL ON FUNCTION public.enforce_saved_birth_profile_limit() FROM PUBLIC, anon, authenticated;

DROP POLICY IF EXISTS "Users can insert own birth profiles" ON public.saved_birth_profiles;
CREATE POLICY "Users can insert own birth profiles"
  ON public.saved_birth_profiles
  FOR INSERT
  TO authenticated
  WITH CHECK (
    auth.uid() = user_id
    AND public.can_create_birth_profile()
  );

-- Remove legacy 1-arg RPC overload after policy update so users cannot probe other UUIDs
DROP FUNCTION IF EXISTS public.can_create_birth_profile(uuid);

-- ----------------------------------------------------------------------------
-- 3. google_calendar_connections (Non-secret connection metadata; SELECT only)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.google_calendar_connections (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  google_account_sub text NOT NULL,
  google_email text NULL,
  calendar_id text NOT NULL DEFAULT 'primary',
  scope text NULL,
  status text NOT NULL DEFAULT 'connected' CHECK (status IN ('connected', 'disconnected', 'revoked')),
  connected_at timestamptz NOT NULL DEFAULT now(),
  disconnected_at timestamptz NULL,
  last_synced_at timestamptz NULL,
  last_sync_status text NULL CHECK (last_sync_status IS NULL OR last_sync_status IN ('success', 'partial', 'error')),
  last_sync_error text NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_google_conn_user_sub UNIQUE (user_id, google_account_sub)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_google_conn_one_active_per_user
  ON public.google_calendar_connections (user_id)
  WHERE status = 'connected';

CREATE INDEX IF NOT EXISTS idx_google_conn_user_status
  ON public.google_calendar_connections (user_id, status);

DROP TRIGGER IF EXISTS trg_google_calendar_connections_updated_at ON public.google_calendar_connections;
CREATE TRIGGER trg_google_calendar_connections_updated_at
  BEFORE UPDATE ON public.google_calendar_connections
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

REVOKE ALL ON public.google_calendar_connections FROM anon, PUBLIC;
REVOKE ALL ON public.google_calendar_connections FROM authenticated;
GRANT SELECT ON public.google_calendar_connections TO authenticated;
GRANT ALL ON TABLE public.google_calendar_connections TO service_role;

ALTER TABLE public.google_calendar_connections ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view own Google calendar connections" ON public.google_calendar_connections;
CREATE POLICY "Users can view own Google calendar connections"
  ON public.google_calendar_connections
  FOR SELECT
  TO authenticated
  USING (auth.uid() = user_id);

-- ----------------------------------------------------------------------------
-- 4. google_oauth_credentials (SERVER-ONLY encrypted tokens — ZERO browser access)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.google_oauth_credentials (
  connection_id uuid PRIMARY KEY REFERENCES public.google_calendar_connections(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  encrypted_refresh_token text NULL,
  encrypted_access_token text NULL,
  token_expires_at timestamptz NULL,
  token_type text NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_google_oauth_creds_user
  ON public.google_oauth_credentials (user_id);

DROP TRIGGER IF EXISTS trg_google_oauth_credentials_updated_at ON public.google_oauth_credentials;
CREATE TRIGGER trg_google_oauth_credentials_updated_at
  BEFORE UPDATE ON public.google_oauth_credentials
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

REVOKE ALL ON public.google_oauth_credentials FROM anon, authenticated, PUBLIC;
GRANT ALL ON TABLE public.google_oauth_credentials TO service_role;
ALTER TABLE public.google_oauth_credentials ENABLE ROW LEVEL SECURITY;

-- ----------------------------------------------------------------------------
-- 5. oauth_states (SERVER-ONLY single-use OAuth CSRF states — ZERO browser access)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.oauth_states (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  state_hash text NOT NULL UNIQUE,
  browser_nonce_hash text NOT NULL,
  expires_at timestamptz NOT NULL,
  consumed_at timestamptz NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_oauth_states_user_expires
  ON public.oauth_states (user_id, expires_at);

REVOKE ALL ON public.oauth_states FROM anon, authenticated, PUBLIC;
GRANT ALL ON TABLE public.oauth_states TO service_role;
ALTER TABLE public.oauth_states ENABLE ROW LEVEL SECURITY;

-- ----------------------------------------------------------------------------
-- 6. google_calendar_events (Tracked Tithi-managed Google events)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.google_calendar_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  google_connection_id uuid NOT NULL REFERENCES public.google_calendar_connections(id) ON DELETE CASCADE,
  saved_birth_profile_id uuid NULL REFERENCES public.saved_birth_profiles(id) ON DELETE SET NULL,
  profile_label_snapshot text NOT NULL,
  google_calendar_id text NOT NULL DEFAULT 'primary',
  google_event_id text NOT NULL,
  hindu_year integer NOT NULL CHECK (hindu_year BETWEEN 1583 AND 2500),
  candidate_index integer NOT NULL DEFAULT 0 CHECK (candidate_index >= 0),
  gregorian_date date NOT NULL,
  lunar_month_en text NULL,
  tithi_label text NULL,
  observance_status text NULL,
  sync_status text NOT NULL DEFAULT 'synced' CHECK (sync_status IN ('synced', 'error', 'deleted', 'missing_in_google')),
  last_error text NULL,
  last_synced_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_google_event_profile_year_active
  ON public.google_calendar_events (user_id, google_connection_id, saved_birth_profile_id, hindu_year)
  WHERE saved_birth_profile_id IS NOT NULL AND sync_status <> 'deleted';

CREATE INDEX IF NOT EXISTS idx_google_events_user_year
  ON public.google_calendar_events (user_id, hindu_year);

CREATE INDEX IF NOT EXISTS idx_google_events_user_profile
  ON public.google_calendar_events (user_id, saved_birth_profile_id);

CREATE INDEX IF NOT EXISTS idx_google_events_user_conn_status
  ON public.google_calendar_events (user_id, google_connection_id, sync_status);

CREATE INDEX IF NOT EXISTS idx_google_events_google_id
  ON public.google_calendar_events (google_event_id);

DROP TRIGGER IF EXISTS trg_google_calendar_events_updated_at ON public.google_calendar_events;
CREATE TRIGGER trg_google_calendar_events_updated_at
  BEFORE UPDATE ON public.google_calendar_events
  FOR EACH ROW
  EXECUTE FUNCTION public.set_updated_at();

REVOKE ALL ON public.google_calendar_events FROM anon, PUBLIC;
REVOKE ALL ON public.google_calendar_events FROM authenticated;
GRANT SELECT ON public.google_calendar_events TO authenticated;
GRANT ALL ON TABLE public.google_calendar_events TO service_role;

ALTER TABLE public.google_calendar_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view own Google calendar events" ON public.google_calendar_events;
CREATE POLICY "Users can view own Google calendar events"
  ON public.google_calendar_events
  FOR SELECT
  TO authenticated
  USING (auth.uid() = user_id);

-- ----------------------------------------------------------------------------
-- 7. google_sync_logs (Synchronization history & error log)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.google_sync_logs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  google_connection_id uuid NULL REFERENCES public.google_calendar_connections(id) ON DELETE SET NULL,
  action_type text NOT NULL CHECK (action_type IN ('sync', 'delete', 'connect', 'disconnect')),
  sync_mode text NULL,
  profile_count integer NOT NULL DEFAULT 0,
  year_start integer NULL,
  year_end integer NULL,
  created_count integer NOT NULL DEFAULT 0,
  updated_count integer NOT NULL DEFAULT 0,
  deleted_count integer NOT NULL DEFAULT 0,
  failed_count integer NOT NULL DEFAULT 0,
  status text NOT NULL CHECK (status IN ('success', 'partial', 'error')),
  error_message text NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_google_sync_logs_user_created
  ON public.google_sync_logs (user_id, created_at DESC);

REVOKE ALL ON public.google_sync_logs FROM anon, PUBLIC;
REVOKE ALL ON public.google_sync_logs FROM authenticated;
GRANT SELECT ON public.google_sync_logs TO authenticated;
GRANT ALL ON TABLE public.google_sync_logs TO service_role;

ALTER TABLE public.google_sync_logs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view own Google sync logs" ON public.google_sync_logs;
CREATE POLICY "Users can view own Google sync logs"
  ON public.google_sync_logs
  FOR SELECT
  TO authenticated
  USING (auth.uid() = user_id);
