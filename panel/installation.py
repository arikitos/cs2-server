"""Deferred server provisioning using the installer-resolved Compose model."""

from pathlib import Path

from docker.types import LogConfig, Mount

from maintenance_guard import maintenance_operation, run_updater_container


def installation_status(panel) -> dict:
    installed = panel.read_json(
        panel.SERVER_DIR / "game/csgo/addons/.cs2-manager-versions.json", {}
    )
    versions = panel.manager_versions()
    frameworks = all(
        installed.get(name) == versions.get(name, {}).get("version")
        and bool(installed.get(name))
        for name in ("metamod", "counterstrikesharp")
    )
    checks = {
        "game_files": (panel.SERVER_DIR / "game/bin/linuxsteamrt64/cs2").is_file()
        and (panel.SERVER_DIR / "game/csgo/gameinfo.gi").is_file(),
        "frameworks": frameworks,
        "metamod_active": panel.gameinfo_has_metamod() is True,
        "container_created": panel.container_state()["status"] != "not-created",
    }
    return {"ready": all(checks.values()), **checks}


def _configuration(panel) -> dict:
    config = panel.read_json(panel.RUNTIME_DIR / "compose-runtime.json", {})
    if not all(
        name in config.get("services", {})
        for name in ("panel", "cs2-game", "cs2-updater", "cs2-modinstaller", "cs2-init")
    ):
        raise RuntimeError(
            "Server installation configuration is missing. Run "
            "server/scripts/run-setup.cmd or bash server/scripts/setup.sh once, "
            "then retry Install server. This starts only the panel."
        )
    if config["services"]["cs2-game"].get("container_name") != panel.GAME_CONTAINER:
        raise RuntimeError("Game container name changed. Re-run the panel setup script.")
    return config


def _normal_path(value: str) -> str:
    return value.replace("\\", "/").rstrip("/")


def _mount_sources(panel, config: dict) -> list[tuple[str, str, str]]:
    """Use inspected mounts to resolve Docker Desktop's daemon-side paths."""
    actual = panel.client.containers.get(panel.PANEL_CONTAINER).attrs.get("Mounts", [])
    sources = []
    for declared in config["services"]["panel"].get("volumes", []):
        if declared.get("type") != "bind":
            continue
        for mount in actual:
            if mount.get("Destination") == declared["target"] and mount.get("Type") == "bind":
                sources.append((
                    _normal_path(declared["source"]), mount["Source"], mount["Destination"]
                ))
                break
    return sorted(sources, key=lambda item: len(item[0]), reverse=True)


def _mapped_source(source: str, sources, *, local: bool = False) -> str:
    path = _normal_path(source)
    for original, daemon_path, panel_path in sources:
        if path == original or path.startswith(original + "/"):
            root = panel_path if local else daemon_path
            return root.rstrip("/") + path[len(original):]
    raise RuntimeError(f"Installation path is not mounted into the panel: {source}")


def game_data_mounts(panel) -> dict:
    """Allow Steam jobs before the game container has been created."""
    mounts = panel.client.containers.get(panel.PANEL_CONTAINER).attrs.get("Mounts", [])
    for mount in mounts:
        if mount.get("Destination") == str(panel.SERVER_DIR):
            source = mount.get("Name") if mount.get("Type") == "volume" else mount.get("Source")
            if source:
                return {source: {"bind": "/home/steam/cs2-dedicated", "mode": "rw"}}
    raise RuntimeError("The panel's CS2 data mount is missing. Re-run panel setup.")


def _ensure_image(panel, job, config: dict, service: str, sources):
    spec = config["services"][service]
    build = spec["build"]
    context = Path(_mapped_source(build["context"], sources, local=True))
    if not (context / build.get("dockerfile", "Dockerfile")).is_file():
        raise RuntimeError(f"Missing build context for {service}: {context}")
    for row in panel.client.api.build(
        path=str(context), tag=spec["image"],
        dockerfile=build.get("dockerfile", "Dockerfile"),
        buildargs=build.get("args", {}), platform=spec.get("platform", "linux/amd64"),
        rm=True, pull=False, decode=True,
    ):
        if row.get("error"):
            raise RuntimeError(row["error"])
        text = row.get("stream") or row.get("status")
        if text:
            job.emit(str(text).rstrip())
    return panel.client.images.get(spec["image"])


def _container_options(panel, config: dict, service: str, sources) -> dict:
    """Translate this repository's resolved Compose services to Docker SDK options."""
    spec = config["services"][service]
    mounts = []
    for volume in spec.get("volumes", []):
        if volume["type"] != "bind":
            raise RuntimeError("Deferred installation requires bind-mounted server storage.")
        mounts.append(Mount(
            target=volume["target"], source=_mapped_source(volume["source"], sources),
            type="bind", read_only=volume.get("read_only", False),
        ))
    options = {
        "environment": spec.get("environment", {}), "detach": True,
        "platform": spec.get("platform", "linux/amd64"),
    }
    host_options = {"mounts": mounts}
    for key in ("user", "entrypoint", "command", "tty", "stdin_open", "working_dir", "stop_signal"):
        if key in spec:
            options[key] = spec[key]
    for key in ("init", "security_opt", "cpuset", "cap_add", "cap_drop",
                "mem_limit", "mem_reservation", "read_only"):
        if key in spec:
            host_options[{"cpuset": "cpuset_cpus"}.get(key, key)] = spec[key]
    if "stop_grace_period" in spec:
        duration = spec["stop_grace_period"]
        if not duration.endswith("s") or not duration[:-1].isdigit():
            raise RuntimeError("Use whole seconds for stop_grace_period (for example 40s).")
        options["stop_timeout"] = int(duration[:-1])
    ports = {}
    for port in spec.get("ports", []):
        key = f"{port['target']}/{port.get('protocol', 'tcp')}"
        ports.setdefault(key, []).append((port.get("host_ip", "0.0.0.0"), str(port["published"])))
    if ports:
        options["ports"] = list(ports)
        host_options["port_bindings"] = ports
    if "restart" in spec:
        restart = spec["restart"].split(":", 1)
        host_options["restart_policy"] = {"Name": restart[0]}
        if len(restart) == 2:
            host_options["restart_policy"]["MaximumRetryCount"] = int(restart[1])
    if "logging" in spec:
        logging = spec["logging"]
        host_options["log_config"] = LogConfig(type=logging["driver"], config=logging.get("options", {}))
    networks = spec.get("networks", {})
    if len(networks) > 1:
        raise RuntimeError("Deferred installation currently supports one network per service.")
    if networks:
        network = config["networks"][next(iter(networks))]["name"]
        host_options["network_mode"] = network
        aliases = [panel.GAME_CONTAINER, "cs2-game"] if service == "cs2-game" else []
        options["networking_config"] = panel.client.api.create_networking_config({
            network: panel.client.api.create_endpoint_config(aliases=aliases)
        })
    options["host_config"] = panel.client.api.create_host_config(**host_options)
    return options


def _run_service(panel, job, config: dict, service: str, image, sources) -> None:
    options = _container_options(panel, config, service, sources)
    created = panel.client.api.create_container(image.id, name=f"{service}-job-{job.id}", **options)
    container = panel.client.containers.get(created["Id"])
    try:
        container.start()
        for chunk in container.logs(stream=True, follow=True):
            job.emit(chunk.decode("utf-8", errors="replace").rstrip())
        if container.wait().get("StatusCode", -1) != 0:
            raise RuntimeError(f"{service} failed. See the job log above, then retry Install server.")
    finally:
        container.remove(force=True)


def install_server(panel, job) -> None:
    with maintenance_operation(panel):
        config = _configuration(panel)
        sources = _mount_sources(panel, config)
        for service in ("cs2-game", "cs2-init", "cs2-modinstaller"):
            _container_options(panel, config, service, sources)
        job.set(step="Back up configuration and stop the game", percent=5)
        panel.cancel_pending_rcon()
        panel.make_backup(job, "pre-install")
        panel.stop_game()
        job.set(step="Prepare game runtime image", percent=10)
        runtime = _ensure_image(panel, job, config, "cs2-game", sources)
        job.set(step="Prepare SteamCMD image", percent=20)
        _ensure_image(panel, job, config, "cs2-updater", sources)
        job.set(step="Prepare storage permissions", percent=25)
        _run_service(panel, job, config, "cs2-init", runtime, sources)
        job.set(step="Download or update CS2 game files", percent=30)
        if run_updater_container(panel, job, "update", volumes=game_data_mounts(panel)) != 0:
            raise RuntimeError("SteamCMD installation failed. The panel remains available; retry Install server.")
        job.set(step="Install Metamod and CounterStrikeSharp", percent=75)
        _run_service(panel, job, config, "cs2-modinstaller", runtime, sources)
        job.set(step="Activate Metamod", percent=90)
        if run_updater_container(panel, job, "repair-metamod", volumes=game_data_mounts(panel)) != 0:
            raise RuntimeError("Metamod activation failed. Retry Install server.")
        checks = installation_status(panel)
        if not all(checks[key] for key in ("game_files", "frameworks", "metamod_active")):
            raise RuntimeError("Installation verification failed. See Maintenance > Verify installation.")
        job.set(step="Create stopped game container", percent=95)
        try:
            previous = panel.client.containers.get(panel.GAME_CONTAINER)
        except panel.NotFound:
            previous = None
        options = _container_options(panel, config, "cs2-game", sources)
        options["labels"] = {
            **config["services"]["cs2-game"].get("labels", {}),
            "com.docker.compose.project": config.get("name", panel.COMPOSE_PROJECT),
            "com.docker.compose.service": "cs2-game",
            "com.docker.compose.oneoff": "False",
        }
        # Refresh the image, credentials and mounts from the saved configuration.
        # Removing the stopped container does not remove its bind-mounted data.
        if previous is not None:
            previous.remove()
        panel.client.api.create_container(runtime.id, name=panel.GAME_CONTAINER, **options)
        panel.STATE_TIMESTAMPS["last_manual_update"] = panel.now_iso()
        job.result = {"installed": True, "game_started": False}
        job.emit("Server installed. Choose FaceIt or Retakes in Game modes, then Save & start.")
