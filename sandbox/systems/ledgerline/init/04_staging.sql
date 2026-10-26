-- LL_RTN_REQ_STG: the staging table Ledgerline's owner made for return drafts from other programs (the assistant's
-- middleware). Nothing in it is official: Ledgerline's own job checks each approved draft and books it in the real tables.
ALTER SESSION SET CONTAINER = FREEPDB1;

CREATE TABLE LEDGERLINE.LL_RTN_REQ_STG (
  REQ_ID       NUMBER(10)    GENERATED ALWAYS AS IDENTITY (START WITH 1001) PRIMARY KEY,
  ORD_NO       VARCHAR2(12)  NOT NULL,
  LN_NO        NUMBER(3)     NOT NULL,
  RFND_AMT     NUMBER(10,2)  NOT NULL,
  REQ_KEY      VARCHAR2(64)  UNIQUE,                 -- the sender's idempotency key: one draft per key
  STG_STAT_CD  CHAR(1)       DEFAULT 'W' NOT NULL,   -- W waiting, A approved, R rejected (set by Ledgerline's job)
  CRT_TS       TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL
);

-- sandbox only: Ledgerline on a sale day. Each write into the staging table waits SLOW_WRITE_SEC seconds (0 = off);
-- the return lesson (FDE 1-7-7) sets 3 before its take and 0 after it
CREATE TABLE LEDGERLINE.LL_SBX_CFG (
  CFG_NM       VARCHAR2(30)  PRIMARY KEY,
  CFG_VAL      NUMBER        NOT NULL
);
INSERT INTO LEDGERLINE.LL_SBX_CFG VALUES ('SLOW_WRITE_SEC', 0);
COMMIT;

CREATE OR REPLACE TRIGGER LEDGERLINE.LL_RTN_REQ_STG_SLOW BEFORE INSERT ON LEDGERLINE.LL_RTN_REQ_STG FOR EACH ROW
DECLARE
  secs NUMBER;
BEGIN
  SELECT CFG_VAL INTO secs FROM LEDGERLINE.LL_SBX_CFG WHERE CFG_NM = 'SLOW_WRITE_SEC';
  IF secs > 0 THEN DBMS_SESSION.SLEEP(secs); END IF;
END;
/

-- LL_WRITER: the account for the staging table only, the one write Ledgerline's owner agreed to (no updates, no deletes,
-- no other tables). "writer" is a test password of the local sandbox
CREATE USER LL_WRITER IDENTIFIED BY "writer";
GRANT CREATE SESSION TO LL_WRITER;
GRANT INSERT, SELECT ON LEDGERLINE.LL_RTN_REQ_STG TO LL_WRITER;
