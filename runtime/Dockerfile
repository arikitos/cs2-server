FROM mcr.microsoft.com/dotnet/sdk:10.0 AS plugins
WORKDIR /src
COPY plugins/ /src/
RUN dotnet publish LocalManager/LocalManager.csproj -c Release -o /built/LocalManager \
    && dotnet publish retakes-allocator/RetakesAllocator/RetakesAllocator.csproj -c Release -o /built/RetakesAllocator

FROM registry.gitlab.steamos.cloud/steamrt/steamrt4/sdk
USER root
ENV DEBIAN_FRONTEND=noninteractive HOME=/home/steam DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl lib32z1 python3 util-linux socat && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --user-group --uid 1000 steam \
    && mkdir -p /opt/steamcmd /home/steam/.steam/sdk64 /game \
    && curl --fail --location --retry 3 https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz \
       | tar -xz -C /opt/steamcmd \
    && chown -R steam:steam /opt/steamcmd /home/steam /game \
    && runuser -u steam -- /opt/steamcmd/steamcmd.sh +quit
COPY . /opt/cs2/
COPY --from=plugins /built /built
RUN python3 /opt/cs2/assets.py && rm -rf /built /opt/cs2/plugins \
    && chmod 755 /opt/cs2/entrypoint.sh
EXPOSE 27015/udp 27015/tcp
ENTRYPOINT ["/opt/cs2/entrypoint.sh"]
CMD ["server"]
