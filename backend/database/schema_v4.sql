CREATE TABLE users (
    user_id uuid PRIMARY KEY,
    username text NOT NULL UNIQUE CHECK (username ~ '^[a-z][a-z0-9_]{2,31}$'),
    display_name text NOT NULL CHECK (char_length(display_name) BETWEEN 1 AND 50),
    password_hash text NOT NULL CHECK (password_hash <> ''),
    role text NOT NULL CHECK (role IN ('admin','user')),
    status text NOT NULL CHECK (status IN ('active','disabled')),
    must_change_password boolean NOT NULL,
    avatar_path text,
    email text,
    gender text,
    birthday date,
    phone_number text,
    address text,
    bio text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((username = 'admin' AND role = 'admin' AND status = 'active')
        OR (username <> 'admin' AND role = 'user')),
    CONSTRAINT users_profile_avatar_path_check CHECK (avatar_path IS NULL OR char_length(btrim(avatar_path)) > 0),
    CONSTRAINT users_profile_email_length_check CHECK (email IS NULL OR char_length(email) BETWEEN 1 AND 254),
    CONSTRAINT users_profile_gender_check CHECK (gender IS NULL OR gender IN ('male','female','other','undisclosed')),
    CONSTRAINT users_profile_phone_length_check CHECK (phone_number IS NULL OR char_length(phone_number) BETWEEN 1 AND 32),
    CONSTRAINT users_profile_address_length_check CHECK (address IS NULL OR char_length(address) BETWEEN 1 AND 500),
    CONSTRAINT users_profile_bio_length_check CHECK (bio IS NULL OR char_length(bio) BETWEEN 1 AND 200)
);
CREATE INDEX users_list ON users(created_at DESC,user_id DESC);
CREATE TABLE auth_sessions (
    auth_session_id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(user_id),
    token_hash bytea NOT NULL UNIQUE CHECK (octet_length(token_hash) = 32),
    csrf_token text NOT NULL CHECK (csrf_token <> ''),
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    CHECK (expires_at > created_at),
    CHECK (revoked_at IS NULL OR revoked_at >= created_at)
);
CREATE INDEX auth_sessions_user ON auth_sessions(user_id);
CREATE INDEX auth_sessions_expiry ON auth_sessions(expires_at);

CREATE TABLE agents (
    agent_id text PRIMARY KEY,
    name text NOT NULL,
    description text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO agents(agent_id,name,description) VALUES
    ('conversation_assistant','会话助手','讨论问题、起草文字、整理材料。围绕上下文连续交流，让思路逐渐清楚。'),
    ('institution_review','制度审核','上传制度草稿，选择标准或知识库。查看条款问题、相关依据与完整报告。');

CREATE TABLE chat_sessions (
    session_id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(user_id),
    agent_id text NOT NULL REFERENCES agents (agent_id),
    title text NOT NULL,
    last_sequence bigint NOT NULL DEFAULT 0 CHECK (last_sequence >= 0),
    memory_checkpoint_id text CHECK (memory_checkpoint_id IS NULL OR memory_checkpoint_id <> ''),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX chat_sessions_list ON chat_sessions (user_id, agent_id, updated_at DESC, session_id DESC);

CREATE TABLE runs (
    run_id uuid PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES chat_sessions (session_id),
    client_message_id varchar(128) NOT NULL,
    status text NOT NULL CHECK (status IN ('queued','running','succeeded','failed','cancelled')),
    error_code text,
    error_message text,
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz,
    UNIQUE (session_id, run_id),
    UNIQUE (session_id, client_message_id),
    CHECK ((status IN ('succeeded','failed','cancelled')) = (finished_at IS NOT NULL))
);
CREATE UNIQUE INDEX session_one_active_run ON runs (session_id)
    WHERE status IN ('queued','running');

CREATE TABLE messages (
    message_id uuid PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES chat_sessions (session_id),
    run_id uuid NOT NULL,
    sequence bigint NOT NULL CHECK (sequence > 0),
    role text NOT NULL CHECK (role IN ('user','assistant')),
    content text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (session_id, message_id),
    UNIQUE (session_id, sequence),
    UNIQUE (run_id, role),
    FOREIGN KEY (session_id, run_id) REFERENCES runs (session_id, run_id)
);

CREATE TABLE files (
    file_id uuid PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES chat_sessions (session_id),
    original_name text NOT NULL,
    source_path text NOT NULL UNIQUE CHECK (source_path <> ''),
    content_path text NOT NULL UNIQUE CHECK (content_path <> ''),
    size_bytes bigint NOT NULL CHECK (size_bytes > 0),
    content_chars integer NOT NULL CHECK (content_chars >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (session_id, file_id)
);
CREATE INDEX files_list ON files (session_id, created_at, file_id);

CREATE TABLE message_files (
    session_id uuid NOT NULL,
    message_id uuid NOT NULL,
    file_id uuid NOT NULL,
    position integer NOT NULL CHECK (position >= 0),
    PRIMARY KEY (message_id, file_id),
    UNIQUE (message_id, position),
    FOREIGN KEY (session_id, message_id) REFERENCES messages (session_id, message_id),
    FOREIGN KEY (session_id, file_id) REFERENCES files (session_id, file_id)
);
CREATE INDEX file_references ON message_files (file_id);

CREATE TABLE agent_calls (
    call_id uuid PRIMARY KEY,
    message_id uuid NOT NULL UNIQUE REFERENCES messages (message_id),
    agent_id text NOT NULL REFERENCES agents (agent_id),
    agent_name text NOT NULL,
    invocation_id text NOT NULL,
    output_type text NOT NULL CHECK (output_type IN ('markdown','text','json')),
    output text NOT NULL
);

CREATE TABLE chat_schema_version (
    singleton boolean PRIMARY KEY CHECK (singleton),
    version integer NOT NULL CHECK (version = 4)
);
INSERT INTO chat_schema_version VALUES (true, 4);

-- 开发/测试默认账号：admin / 123456，密码以 Argon2id 哈希保存。
INSERT INTO users (
    user_id, username, display_name, password_hash, role, status, must_change_password
) VALUES (
    gen_random_uuid(), 'admin', '管理员',
    '$argon2id$v=19$m=65536,t=3,p=4$fj7MWjmNrASgE4ND/P6zHQ$1JMks/gT+sruRk1gEP+8f9/wv5gscrYS4YlPy+CVT5Q',
    'admin', 'active', false
);
