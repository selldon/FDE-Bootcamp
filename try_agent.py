from agent import answer

MAYA = "maya.ross@example.com"
QUESTION = "Hi, where is my order DS-20417? It was due on Monday."
print(answer(QUESTION, MAYA).reply)
print(answer("Where is order DS-20433?", MAYA).reply)
print(answer(QUESTION, None).reply)
