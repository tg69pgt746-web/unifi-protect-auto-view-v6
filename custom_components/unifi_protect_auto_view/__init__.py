"""The UniFi Protect Auto-View integration."""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

from .const import (
    DOMAIN,
    CONF_MEDIA_PLAYERS,
    CONF_NOTIFY_SERVICES,
    CONF_TIMEOUT,
    CONF_ENABLE_POPUP,
    CONF_TRIGGER_ON_PERSON,
    CONF_TRIGGER_ON_RING,
    CONF_TURN_OFF_AFTER,
    CONF_ENABLE_VIEWER,
    EVENT_DETECTION,
)
from .panel import async_register_viewer, async_remove_viewer

_LOGGER = logging.getLogger(__name__)

RING_TOKENS = {"doorbell", "ring"}
PERSON_TOKENS = {"person"}
# Player states that mean someone is using the player; we never turn these off.
ACTIVE_PLAYER_STATES = {"on", "playing", "paused", "buffering"}
COOLDOWN_SECONDS = 5
DISCOVERY_DEBOUNCE_SECONDS = 10


def _tokens(value: str) -> set[str]:
    """Split a string into lowercase word tokens."""
    return {t for t in re.split(r"[^a-z0-9]+", value.lower()) if t}


def _clean_name(name: str) -> str:
    """Drop the stream-quality suffix from a camera entity's friendly name."""
    return re.sub(
        r"\s+(high|medium|low)(\s+resolution)?(\s+channel)?(\s+\(insecure\))?$",
        "",
        name,
        flags=re.IGNORECASE,
    )


def _pick_camera(cameras: list[str]) -> str:
    """Pick the best camera: high-res stream, never the package camera if avoidable."""
    usable = sorted(c for c in cameras if "package" not in c) or sorted(cameras)
    high = [c for c in usable if "high" in _tokens(c)]
    return (high or usable)[0]


def _discover(
    hass: HomeAssistant, trigger_ring: bool, trigger_person: bool
) -> dict[str, tuple[str, bool]]:
    """Map each ring/person sensor to its device's camera: {sensor: (camera, is_ring)}."""
    entity_reg = er.async_get(hass)
    device_cameras: dict[str, list[str]] = {}
    device_sensors: dict[str, list[tuple[str, bool]]] = {}

    for entity in entity_reg.entities.values():
        if entity.platform != "unifiprotect" or not entity.device_id or entity.disabled:
            continue

        eid = entity.entity_id
        if eid.startswith("camera."):
            device_cameras.setdefault(entity.device_id, []).append(eid)
        elif eid.startswith(("binary_sensor.", "event.")):
            # Current UniFi Protect exposes doorbell rings as an event entity
            # (event_type "ring"); older versions used a binary sensor. Person
            # detection is a binary sensor. Match on unique_id / sensor name only:
            # the entity_id contains the camera's name, so a camera called
            # "Front Doorbell" would wrongly match every sensor.
            tokens = _tokens(entity.unique_id or "") | _tokens(entity.original_name or "")
            if not tokens:
                tokens = _tokens(eid.split(".", 1)[1])

            is_ring = bool(tokens & RING_TOKENS)
            is_person = (
                eid.startswith("binary_sensor.")
                and not is_ring
                and bool(tokens & PERSON_TOKENS)
            )

            if (trigger_ring and is_ring) or (trigger_person and is_person):
                device_sensors.setdefault(entity.device_id, []).append((eid, is_ring))

    sensor_meta: dict[str, tuple[str, bool]] = {}
    for device_id, sensors in device_sensors.items():
        cameras = device_cameras.get(device_id)
        if not cameras:
            continue
        chosen = _pick_camera(cameras)
        for sensor_eid, is_ring in sensors:
            sensor_meta[sensor_eid] = (chosen, is_ring)
    return sensor_meta


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up UniFi Protect Auto-View from a config entry."""
    conf: dict[str, Any] = {**entry.data, **entry.options}

    trigger_ring = conf.get(CONF_TRIGGER_ON_RING, True)
    trigger_person = conf.get(CONF_TRIGGER_ON_PERSON, True)
    enable_popup = conf.get(CONF_ENABLE_POPUP, True)
    turn_off_after = conf.get(CONF_TURN_OFF_AFTER, True)
    enable_viewer = conf.get(CONF_ENABLE_VIEWER, True)
    media_players: list[str] = conf.get(CONF_MEDIA_PLAYERS) or []
    notify_raw: str = conf.get(CONF_NOTIFY_SERVICES) or ""
    timeout = int(conf.get(CONF_TIMEOUT, 45))

    notify_services = [
        s.strip().removeprefix("notify.") for s in notify_raw.split(",") if s.strip()
    ]

    sensor_meta = _discover(hass, trigger_ring, trigger_person)
    if sensor_meta:
        _LOGGER.info(
            "UniFi Protect Auto-View tracking %d sensors: %s", len(sensor_meta), sensor_meta
        )
    else:
        _LOGGER.warning("No enabled UniFi Protect ring or person sensors found yet.")

    # One timer per target so a new event restarts the timeout instead of racing it.
    timers: dict[str, asyncio.Task] = {}
    player_was_active: dict[str, bool] = {}
    last_triggered: dict[str, float] = {}

    def _is_running(key: str) -> bool:
        task = timers.get(key)
        return task is not None and not task.done()

    def _schedule(key: str, coro) -> None:
        old = timers.pop(key, None)
        if old is not None and not old.done():
            old.cancel()
        timers[key] = entry.async_create_background_task(hass, coro, f"{DOMAIN}_{key}")

    async def _cast(camera: str, player: str) -> None:
        try:
            await hass.services.async_call(
                "camera",
                "play_stream",
                {"entity_id": camera, "media_player": player},
                blocking=True,
            )
        except HomeAssistantError as err:
            _LOGGER.warning("Could not cast %s to %s: %s", camera, player, err)
            return
        await asyncio.sleep(timeout)
        if turn_off_after and not player_was_active.get(player, False):
            try:
                await hass.services.async_call(
                    "media_player", "turn_off", {"entity_id": player}, blocking=False
                )
            except HomeAssistantError as err:
                _LOGGER.debug("Could not turn off %s: %s", player, err)

    async def _popup(camera: str, title: str) -> None:
        try:
            await hass.services.async_call(
                "browser_mod",
                "popup",
                {
                    "title": title,
                    "size": "wide",
                    "content": {
                        "type": "picture-entity",
                        "entity": camera,
                        "camera_view": "live",
                    },
                },
                blocking=True,
            )
        except HomeAssistantError as err:
            _LOGGER.warning("Could not open popup for %s: %s", camera, err)
            return
        await asyncio.sleep(timeout)
        try:
            await hass.services.async_call(
                "browser_mod", "close_popup", {}, blocking=False
            )
        except HomeAssistantError as err:
            _LOGGER.debug("Could not close popup: %s", err)

    @callback
    def async_handle_event(event) -> None:
        """Handle state changes on discovered UniFi Protect sensors."""
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        entity_id = event.data.get("entity_id")

        if new_state is None or old_state is None:
            return

        if entity_id.startswith("event."):
            # Event entity: the state is the timestamp of the last event. Fire only
            # on a real new "ring", not on startup/restore or reconnects.
            if (
                new_state.state in ("unavailable", "unknown")
                or old_state.state == "unavailable"
                or old_state.attributes.get("restored")
                or new_state.state == old_state.state
                or new_state.attributes.get("event_type") != "ring"
            ):
                return
        else:
            # Binary sensor: only a genuine off -> on transition, so attribute
            # updates while a detection is ongoing don't re-trigger.
            if old_state.state != "off" or new_state.state != "on":
                return

        meta = sensor_meta.get(entity_id)
        if not meta:
            return

        camera_entity, is_ring = meta

        # Cooldown per camera so simultaneous ring + person sensors fire only once.
        now = time.monotonic()
        if now - last_triggered.get(camera_entity, 0) < COOLDOWN_SECONDS:
            return
        last_triggered[camera_entity] = now

        cam_state = hass.states.get(camera_entity)
        cam_name = _clean_name(cam_state.name) if cam_state else camera_entity

        title = f"Doorbell Ring: {cam_name}" if is_ring else f"Person Detected: {cam_name}"
        message = (
            f"Someone is at {cam_name}."
            if is_ring
            else f"A person was spotted on {cam_name}."
        )

        # 0. Tell the camera viewer panel (if open) which camera to show
        hass.bus.async_fire(
            EVENT_DETECTION,
            {"camera": camera_entity, "kind": "ring" if is_ring else "person", "title": title},
        )

        # 1. Cast to TVs / Nest Hubs
        for player in media_players:
            key = f"cast:{player}"
            if not _is_running(key):
                # Record prior state only when no cast of ours is already active.
                state = hass.states.get(player)
                player_was_active[player] = (
                    state is not None and state.state in ACTIVE_PLAYER_STATES
                )
            _schedule(key, _cast(camera_entity, player))

        # 2. Mobile push with live video
        for service_name in notify_services:
            if hass.services.has_service("notify", service_name):
                hass.async_create_task(
                    hass.services.async_call(
                        "notify",
                        service_name,
                        {
                            "title": title,
                            "message": message,
                            "data": {
                                "entity_id": camera_entity,
                                "push": {"interruption-level": "time-sensitive"},
                                "ttl": 0,
                                "priority": "high",
                            },
                        },
                        blocking=False,
                    )
                )

        # 3. Dashboard popup (Browser Mod)
        if enable_popup and hass.services.has_service("browser_mod", "popup"):
            _schedule("popup", _popup(camera_entity, title))

    if sensor_meta:
        entry.async_on_unload(
            async_track_state_change_event(hass, list(sensor_meta), async_handle_event)
        )

    # Pick up cameras/sensors added or removed after startup (debounced).
    reload_handle = None

    @callback
    def _async_check_discovery(_now) -> None:
        nonlocal reload_handle
        reload_handle = None
        if _discover(hass, trigger_ring, trigger_person) != sensor_meta:
            _LOGGER.info("UniFi Protect devices changed, reloading Auto-View")
            hass.config_entries.async_schedule_reload(entry.entry_id)

    @callback
    def _async_registry_updated(event) -> None:
        nonlocal reload_handle
        eid = event.data.get("entity_id", "")
        if not eid.startswith(("camera.", "binary_sensor.", "event.")):
            return
        if reload_handle is not None:
            reload_handle()
        reload_handle = async_call_later(
            hass, DISCOVERY_DEBOUNCE_SECONDS, _async_check_discovery
        )

    @callback
    def _cancel_pending_check() -> None:
        if reload_handle is not None:
            reload_handle()

    entry.async_on_unload(
        hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, _async_registry_updated)
    )
    entry.async_on_unload(_cancel_pending_check)

    # Sidebar camera viewer panel (a failure here must never break the alerts).
    if enable_viewer:
        try:
            await async_register_viewer(hass, timeout)
            entry.async_on_unload(lambda: async_remove_viewer(hass))
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Could not register the camera viewer panel")

    # Reload when options change.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the integration when options are changed."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry (listeners and timers are cleaned up via async_on_unload)."""
    return True
