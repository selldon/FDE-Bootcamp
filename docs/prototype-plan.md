# The assistant prototype - plan

**Assumption.** With order data in hand, the assistant answers "where is my order" correctly and passes the right
chats to a person.

**The number.** At least 36 of the 40 labeled conversations get the right action, and no chat that needs a person
stays with the assistant.

**Days.** Five, agreed with Lena Brandt before the work starts. A no is a useful answer.

**Real:** the model, the prompt, the tool descriptions and the 40 labeled conversations from Marco's team.

**Fake, with the real shape, behind the same tools:** Ledgerline (a small file of test orders), the carrier's nightly
file (a few fixed statuses), the email with the one-time code, ServiceNow cases.

**Never faked:** safety. The API key stays out of the code, customer data stays where Sofia Lindqvist agreed it may be,
and no tool moves money.

**At the end:** quick fixes are listed in `docs/quick-fixes.md`. We keep the clean, tested parts (tool definitions,
prompt, fakes, the replay), and every quick fix is written again, with a test.
