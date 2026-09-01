-- VOXScript 001: 계정/사용량 (Supabase 프로젝트 공유, FABLE의 accounts/usage_counters와 이름 충돌 방지)

CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- 이미 FABLE에서 만들어놨을 텐데 IF NOT EXISTS라 안전

CREATE TABLE accounts_vox (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    monthly_credit_limit NUMERIC NOT NULL DEFAULT 5.00,   -- 달러 기준
    failed_login_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE usage_counters_vox (
    account_id UUID NOT NULL REFERENCES accounts_vox(id),
    usage_month DATE NOT NULL DEFAULT date_trunc('month', CURRENT_DATE)::date,
    stt_seconds INTEGER NOT NULL DEFAULT 0,
    gemini_calls INTEGER NOT NULL DEFAULT 0,
    deepl_chars INTEGER NOT NULL DEFAULT 0,
    estimated_cost NUMERIC NOT NULL DEFAULT 0,
    PRIMARY KEY (account_id, usage_month)
);

CREATE TABLE processing_logs_vox (
    id SERIAL PRIMARY KEY,
    account_id UUID REFERENCES accounts_vox(id),
    project_id TEXT,               -- VOXScript .vox 프로젝트 id
    service TEXT NOT NULL,         -- 'whisper' | 'gemini' | 'deepl'
    detail JSONB,
    cost NUMERIC,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);