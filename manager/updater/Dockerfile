# CS2 Manager — Updater image
# ============================
# Improvment.md section 16.5 (acceptable alternative): SteamCMD lives ONLY in this
# maintenance image, kept separate from the runtime image. Built from the same
# pinned base so SteamCMD, the steam user, and paths match the runtime exactly.
ARG CS2_BASE_IMAGE=joedwards32/cs2@sha256:41b826d6280d1aa9e41c866a6d88cc7f523e027f16c47a313b20c2d7a17f2680
FROM ${CS2_BASE_IMAGE}

USER root
COPY updater.sh /usr/local/bin/updater.sh
RUN chmod +x /usr/local/bin/updater.sh

USER 1000:1000
WORKDIR /home/steam

# Runs the controlled update, then exits. Never launches the game server.
ENTRYPOINT ["/usr/local/bin/updater.sh"]
CMD []
