# The course image: Python 3.12 on Debian bookworm. The image ships an apt source for Yarn whose signing key is no
# longer published, so `apt-get update` fails and the docker-in-docker feature cannot install (Codespaces, 26.10.2026).
# Nothing in the course needs Yarn from apt (the widget uses npm), so the source goes.
FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm
RUN rm -f /etc/apt/sources.list.d/yarn.list
