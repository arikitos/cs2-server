# CS2 Manager, Updater image
# ==========================
# SteamCMD lives only in this maintenance image. The updater is built from the
# same pinned base as the runtime image so the steam user and install paths match.
ARG CS2_BASE_IMAGE=joedwards32/cs2@sha256:41b826d6280d1aa9e41c866a6d88cc7f523e027f16c47a313b20c2d7a17f2680
FROM ${CS2_BASE_IMAGE}

USER root
COPY updater.sh /usr/local/bin/updater.sh
RUN sed -i 's/\r$//' /usr/local/bin/updater.sh \
    && chmod +x /usr/local/bin/updater.sh

USER 1000:1000
WORKDIR /home/steam

# Runs the controlled update, then exits. Never launches the game server.
ENTRYPOINT ["/usr/local/bin/updater.sh"]
CMD []
