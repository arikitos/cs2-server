# Runtime image for one CS2 process with transactional mode deployment.
ARG CS2_BASE_IMAGE=joedwards32/cs2@sha256:41b826d6280d1aa9e41c866a6d88cc7f523e027f16c47a313b20c2d7a17f2680
FROM ${CS2_BASE_IMAGE}

USER root
COPY runtime-launcher.sh /usr/local/bin/runtime-launcher.sh
COPY mode_applier.py /usr/local/bin/mode-applier
RUN chmod +x /usr/local/bin/runtime-launcher.sh /usr/local/bin/mode-applier \
    && mkdir -p /addons \
    && chown 1000:1000 /addons

USER 1000:1000
WORKDIR /home/steam
ENTRYPOINT ["/usr/local/bin/runtime-launcher.sh"]
CMD []
