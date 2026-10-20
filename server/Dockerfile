# Rise of Incarnates revival: the shared lobby server, the only piece that runs on a server machine.
# Players' PCs run the game and their own profile server; see README.md.
#   docker build -t roi-lobby .        (or: podman build -t roi-lobby .)
ARG PYTHON_BASE
FROM ${PYTHON_BASE}

WORKDIR /app
COPY nrt_server.py nrt_logic.py nrt_rooms.py nrt_security.py server_state.py paths.py network_defaults.py lobby_settings.py player_names.py profile_relay.py commendations.py circles.py ./

ENV ROI_LOBBY_MODE=server \
    ROI_LOBBY_LISTEN=any \
    ROI_QUIET=1 \
    ROI_AUTH_FILE=/run/secrets/roi-lobby-auth.json \
    ROI_COMMENDATION_DB=/app/data/commendations.sqlite3 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN groupadd --gid 10001 roi && useradd --system --uid 10001 --gid roi roi && mkdir -p /app/logs /app/data && chown roi:roi /app/logs /app/data
USER roi

EXPOSE 52711/tcp 52713/tcp
CMD ["python", "nrt_server.py"]
