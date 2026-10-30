BEGIN;

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
    agent_id text NOT NULL REFERENCES agents (agent_id),
    title text NOT NULL,
    last_sequence bigint NOT NULL DEFAULT 0 CHECK (last_sequence >= 0),
    continuation jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX chat_sessions_list ON chat_sessions (agent_id, updated_at DESC, session_id DESC);

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
    version integer NOT NULL CHECK (version = 2)
);
INSERT INTO chat_schema_version VALUES (true, 2);
COMMIT;
