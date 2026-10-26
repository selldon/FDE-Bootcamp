# The sandbox: your lab folder

The labs of the course are typed here, one small program at a time. The product, the chat that Claude Code builds in
the build lessons, lives one level up, in the root of this repository. Both use the same DemoStore systems.

## What is here

- `data/` - what DemoStore and its partners give us: the 40 labeled conversations and the 20 held out, orders, the
  carrier's file, the old chats' export, return cases, attachments, the catalog. Files that a lab's run writes
  (for example `data/chats.json`) appear when you run that lab.
- `systems/` - DemoStore's systems for the course, in containers: Ledgerline (the ERP, Oracle), the carrier's SFTP
  server, Mailpit, our PostgreSQL, and small stand-ins for ServiceNow, Atlas and Confluence.
- `.env.example` - the settings of the labs. Copy it to `.env` (Codespaces does this for you). Your API key comes from
  the Codespaces secret, or from this `.env` on your own computer. Never commit `.env`.
- `catchup.py` and `.course/` - the files of every lab, at its start and at its end.

## Start the systems

    docker compose -f sandbox/systems/compose.yaml up -d
    python doctor.py

The first start takes a few minutes (Ledgerline creates its schema and test data). Codespaces starts them for you.
The labs run from this folder: `cd sandbox`.

## Catch up

Missed a lab, or want to start one from a clean state?

    python sandbox/catchup.py --list          the labs, in course order
    python sandbox/catchup.py 1-7-2           the files as they are when lesson 1-7-2 starts
    python sandbox/catchup.py 1-7-2 --end     ... and after it

It never deletes a file. A file of yours that it replaces is copied to `sandbox/.backup/` first.
