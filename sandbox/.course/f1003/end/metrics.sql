-- The pilot's numbers, read from the traces of every call to Claude.
DROP VIEW IF EXISTS outcomes, topics, chats;

-- One row per chat, from the calls with its conversation.
CREATE VIEW chats AS
SELECT conversation, min(at) AS started, sum(cost) AS cost
  , bool_or(answer LIKE '%"needs_human":true%') AS handed
  , (array_agg(answer ORDER BY id DESC))[1] AS last_reply
  , bool_or(sent LIKE '%tool_result%'
      AND sent NOT LIKE '%"error"%') AS answered
FROM traces
WHERE conversation IS NOT NULL
GROUP BY conversation;

-- What each chat was about: its order, and why a person took over.
CREATE VIEW topics AS
SELECT conversation
  , max(answer::jsonb ->> 'order_number') AS order_number
  , min(answer::jsonb ->> 'intent')
      FILTER (WHERE answer LIKE '%"needs_human":true%') AS reason
FROM traces
WHERE answer LIKE '{"summary"%'
GROUP BY conversation;

-- Exactly one of three outcomes for every chat.
CREATE VIEW outcomes AS
SELECT chats.*, order_number, reason,
  CASE
    WHEN handed THEN 'handed to a person'
    WHEN NOT answered THEN 'left without an answer'
    WHEN EXISTS (
      SELECT 1 FROM chats later JOIN topics again USING (conversation)
      WHERE again.order_number = topics.order_number
        AND later.started > chats.started
        AND later.started < chats.started + interval '7 days')
      THEN 'left without an answer'
    ELSE 'resolved'
  END AS outcome
FROM chats JOIN topics USING (conversation);
