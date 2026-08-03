# CS2 Manager — Runtime image
# ============================
# Preferred design from Improvment.md section 16.5:
#   1. Uses a pinned, tested upstream image as the base (by digest).
#   2. Replaces the upstream entrypoint with a launcher that never runs SteamCMD.
#   3. Starts the installed CS2 binary directly from the persistent install.
#   4. Preserves the unprivileged server user (1000:1000) from the base image.
#
# The base digest is passed from compose (CS2_BASE_IMAGE) so the pinned version
# is declared in one place (.env) and used by both runtime and updater.
ARG CS2_BASE_IMAGE=joedwards32/cs2@sha256:41b826d6280d1aa9e41c866a6d88cc7f523e027f16c47a313b20c2d7a17f2680
FROM ${CS2_BASE_IMAGE}

# Install the no-SteamCMD launcher as root, then drop back to the base user.
USER root
COPY runtime-launcher.sh /usr/local/bin/runtime-launcher.sh
RUN chmod +x /usr/local/bin/runtime-launcher.sh

# Preserve the unprivileged server user baked into the base image.
USER 1000:1000
WORKDIR /home/steam

# Override the upstream `bash entry.sh` (which unconditionally runs app_update).
ENTRYPOINT ["/usr/local/bin/runtime-launcher.sh"]
CMD []
