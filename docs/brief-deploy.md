# Brief: deploy on merge, and shadow mode on live chats

Day 9. The pilot runs in containers, and every change reaches `main` only through a pull request with green checks. It
still runs only on our laptops. Now it runs on one server in the cloud, and every merge to `main` updates it. On that
server the assistant meets real traffic for the first time, in shadow mode: it answers every new live chat, and nobody
sees the answer. The support team works as before.

## What to build

1. **Deploy on merge** (`.github/workflows/deploy.yml`), on every push to `main`:
   - build the two images (the Python code and the widget), tag them with the commit, push them to Amazon ECR
     (`fde-course/demostore-app`, `fde-course/demostore-widget`);
   - make sure the one server runs: an EC2 instance with the tag `project=fde-course`, started if there is none;
   - on the server: DemoStore's systems from `sandbox/systems/compose.yaml` (they stand in for the systems in DemoStore's
     network), then our services with the images of this commit;
   - a check at the end: one real chat through the widget's address on the server, and the shadow worker running. The
     workflow is red when the check fails.
2. **Rollback**: the same workflow, started by hand with an older commit, puts that commit's images back.
3. **Shadow mode**: a worker, one more service in `compose.yaml`, the same image.
   - Every 30 seconds it reads the new live chats in ServiceNow with the read-only account.
   - For each new chat, the assistant prepares the answer it would give. Nothing leaves our database: no reply to the
     customer, no refund draft, no task, no hand-off case. What it would have done is stored next to the answer.
   - In a ServiceNow chat the customer is signed in: `opened_for` is their account's email, so it counts as verified.
   - When the agent closes the chat, the agent's reply is stored next to the assistant's answer.
   - The stand-in opens a new chat every `SNOW_INCOMING_EVERY` seconds (0 = off, the default); on the server we use 120.
4. **A shadow report**: a command that prints the last 20 rows: the customer's message, the assistant's action and
   answer, the agent's reply. Day 10 builds the dashboard from the same rows.
5. **Teardown**: a short list of commands a person runs at the end, in order, and what each one removes.

## The cloud account

- GitHub gets into AWS without a key: the role in the repository variable `AWS_DEPLOY_ROLE_ARN`, only for `main` of
  this repository (OpenID Connect; a GitHub environment would change the identity the role trusts, so none). Region
  `us-east-1`.
- The role may: push to the two ECR repositories; start a `t3.medium` or `t3.large` instance only with the tag
  `project=fde-course` on the instance and on its disk; run commands on such an instance through SSM Run Command; stop
  and terminate it; read (describe) EC2. Nothing else: it cannot create users, keys, roles, policies or security group
  rules, and it cannot read SSM parameters itself.
- The server's own role is `fde-course-ec2` (instance profile of the same name): it pulls from ECR, talks to SSM, and
  reads the Claude API key from SSM Parameter Store, `/fde-course/anthropic-api-key` (SecureString).
- DemoStore's systems need about 7 GB of memory and 15 GB of disk: a `t3.large` with a 30 GB disk.

## Limits

- The key is read on the server when our services start. It is never in an image, in GitHub, in a workflow log or in
  a file in the repository.
- No port is open to the internet: the pilot is not public until day 11. We look at it through the workflow's check and
  the shadow report. No SSH: commands go through SSM.
- Shadow mode writes nothing into DemoStore's systems.
- Money: the server runs only while we work on it, and costs a few cents an hour. A person terminates it at the end.
- Anything the role cannot do is a person's job: write down the exact command, and stop.
- Fast tests still pass: `python -m pytest -q -m "not live"`.
