"""Sidebar camera viewer panel for UniFi Protect Auto-View."""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN, VERSION

_LOGGER = logging.getLogger(__name__)

PANEL_URL_PATH = "unifi-cameras"
STATIC_URL = "/unifi_protect_auto_view_static"


async def async_register_viewer(hass: HomeAssistant, timeout: int) -> None:
    """Serve the viewer JS and add the sidebar panel."""
    store = hass.data.setdefault(DOMAIN, {})
    if not store.get("static_registered"):
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    STATIC_URL, str(Path(__file__).parent / "frontend"), cache_headers=False
                )
            ]
        )
        store["static_registered"] = True

    # Re-registering (after a reload) must not fail on the existing panel.
    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name="unifi-protect-viewer",
        sidebar_title="Cameras",
        sidebar_icon="mdi:cctv",
        module_url=f"{STATIC_URL}/viewer.js?v={VERSION}",
        require_admin=False,
        config={"timeout": timeout},
    )
    _LOGGER.debug("Registered UniFi Protect camera viewer panel")


def async_remove_viewer(hass: HomeAssistant) -> None:
    """Remove the sidebar panel."""
    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
