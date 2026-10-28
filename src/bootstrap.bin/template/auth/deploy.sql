BEGIN;

-- Users and password hashes. Hashing and checks stay in SQL with pgcrypto.
-- After deployment, append a new version instead of editing this file.

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;

CREATE SCHEMA IF NOT EXISTS auth;
CREATE SCHEMA IF NOT EXISTS auth_private;

CREATE TABLE IF NOT EXISTS auth.users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email citext NOT NULL UNIQUE CHECK (email ~* '^.+@.+\..+$'),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS auth_private.users (
    user_id uuid PRIMARY KEY REFERENCES auth.users (id) ON DELETE CASCADE,
    password_hash text NOT NULL
);

-- bcrypt ignores bytes past 72, so longer passwords are rejected.
CREATE OR REPLACE FUNCTION auth.register(email citext, password text)
RETURNS auth.users
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    new_user auth.users;
BEGIN
    IF password IS NULL OR length(password) < 8 OR octet_length(password) > 72 THEN
        RAISE EXCEPTION 'password must be 8 to 72 characters'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    INSERT INTO auth.users (email) VALUES (register.email) RETURNING * INTO new_user;
    INSERT INTO auth_private.users (user_id, password_hash)
        VALUES (new_user.id, crypt(password, gen_salt('bf')));
    RETURN new_user;
END;
$$;

CREATE OR REPLACE FUNCTION auth.authenticate(email citext, password text)
RETURNS auth.users
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT u.*
    FROM auth.users u
    JOIN auth_private.users p ON p.user_id = u.id
    WHERE u.email = authenticate.email
      AND p.password_hash = crypt(authenticate.password, p.password_hash);
$$;

COMMIT;
