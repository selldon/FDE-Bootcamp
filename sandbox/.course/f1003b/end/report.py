"""The weekly update for the sponsor: our words, the dashboard's numbers."""
from metrics import numbers

with open("report-template.md") as f:
    template = f.read()

with open("sponsor-report.md", "w") as f:
    f.write(template.format(**numbers()))
print("sponsor-report.md is ready")
