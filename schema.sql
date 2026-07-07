-- schema.sql
-- ------------
-- Run this ONCE in your Supabase project's SQL Editor (Dashboard -> SQL Editor -> New query).
-- Creates all tables, indexes, and the two aggregate RPC functions the bot needs.

-- ---------------------------------------------------------------- --
-- USERS
-- ---------------------------------------------------------------- --
create table if not exists users (
    user_id     bigint primary key,
    username    text,
    first_name  text,
    last_name   text,
    is_vip      boolean not null default false
);

-- ---------------------------------------------------------------- --
-- BOT ADMINS (bot-wide - separate from a group's real Telegram admins)
-- ---------------------------------------------------------------- --
create table if not exists bot_admins (
    user_id     bigint primary key,
    added_by    bigint,
    created_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------- --
-- MESSAGE LOG (one row per message -> powers آمار روزانه / آمار کل / پروفایل)
-- ---------------------------------------------------------------- --
create table if not exists message_log (
    id         bigserial primary key,
    user_id    bigint not null,
    chat_id    bigint not null,
    created_at timestamptz not null default now()
);
create index if not exists idx_message_log_chat_user_time
    on message_log (chat_id, user_id, created_at);

-- ---------------------------------------------------------------- --
-- MEMBER LOG (one row per member added -> credits whoever invited them)
-- ---------------------------------------------------------------- --
create table if not exists member_log (
    id             bigserial primary key,
    adder_id       bigint not null,
    new_member_id  bigint not null,
    chat_id        bigint not null,
    created_at     timestamptz not null default now()
);
create index if not exists idx_member_log_chat_adder_time
    on member_log (chat_id, adder_id, created_at);

-- ---------------------------------------------------------------- --
-- PER-CHAT ANTI-SPAM SETTINGS (admins tune these from inside Telegram)
-- ---------------------------------------------------------------- --
create table if not exists chat_settings (
    chat_id                    bigint primary key,
    spam_message_limit         int not null default 6,
    spam_time_window_seconds   int not null default 8,
    spam_mute_minutes          int not null default 30
);

-- ---------------------------------------------------------------- --
-- AGGREGATE RPC FUNCTIONS
-- (Postgres GROUP BY isn't reachable through the plain REST query builder,
--  so these small SQL functions are called via supabase-py's .rpc())
-- ---------------------------------------------------------------- --

create or replace function top_message_senders(
    p_chat_id bigint,
    p_since timestamptz default null,
    p_limit int default 15
)
returns table(user_id bigint, message_count bigint)
language sql
stable
as $$
    select user_id, count(*) as message_count
    from message_log
    where chat_id = p_chat_id
      and (p_since is null or created_at >= p_since)
    group by user_id
    order by message_count desc
    limit p_limit;
$$;

create or replace function top_member_adders(
    p_chat_id bigint,
    p_since timestamptz default null,
    p_limit int default 15
)
returns table(adder_id bigint, added_count bigint)
language sql
stable
as $$
    select adder_id, count(*) as added_count
    from member_log
    where chat_id = p_chat_id
      and (p_since is null or created_at >= p_since)
    group by adder_id
    order by added_count desc
    limit p_limit;
$$;