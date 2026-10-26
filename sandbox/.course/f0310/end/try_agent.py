from agent import answer

MAYA = "maya.ross@example.com"
QUESTION = "Hi, where is my order DS-20417? It was due on Monday."
print(answer(QUESTION, MAYA))
print(answer("Where is order DS-20433?", MAYA))
print(answer(QUESTION, None))
