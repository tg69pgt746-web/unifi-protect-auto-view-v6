"""Config flow for UniFi Protect Auto-View integration."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

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
)


def _build_schema(current: dict[str, Any]) -> vol.Schema:
    """Build the form schema, pre-filled from current values."""
    return vol.Schema(
        {
            vol.Optional(
                CONF_TRIGGER_ON_RING, default=current.get(CONF_TRIGGER_ON_RING, True)
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_TRIGGER_ON_PERSON, default=current.get(CONF_TRIGGER_ON_PERSON, True)
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_ENABLE_VIEWER, default=current.get(CONF_ENABLE_VIEWER, True)
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_ENABLE_POPUP, default=current.get(CONF_ENABLE_POPUP, True)
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_MEDIA_PLAYERS,
                description={"suggested_value": current.get(CONF_MEDIA_PLAYERS, [])},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="media_player", multiple=True)
            ),
            vol.Optional(
                CONF_NOTIFY_SERVICES,
                description={"suggested_value": current.get(CONF_NOTIFY_SERVICES, "")},
            ): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            ),
            vol.Optional(
                CONF_TURN_OFF_AFTER, default=current.get(CONF_TURN_OFF_AFTER, True)
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_TIMEOUT, default=current.get(CONF_TIMEOUT, 45)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=10,
                    max=300,
                    step=1,
                    unit_of_measurement="seconds",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
        }
    )


def _normalize(user_input: dict[str, Any]) -> dict[str, Any]:
    """Fill keys the form omits when a field is cleared, so stale values never linger."""
    return {
        CONF_MEDIA_PLAYERS: [],
        CONF_NOTIFY_SERVICES: "",
        **user_input,
        CONF_TIMEOUT: int(user_input.get(CONF_TIMEOUT, 45)),
    }


class UnifiProtectAutoViewConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for UniFi Protect Auto-View."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow."""
        return UnifiProtectAutoViewOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle the initial step."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            return self.async_create_entry(
                title="UniFi Protect Auto-View",
                data=_normalize(user_input),
            )

        return self.async_show_form(step_id="user", data_schema=_build_schema({}))


class UnifiProtectAutoViewOptionsFlow(config_entries.OptionsFlow):
    """Let the user change settings after setup."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=_normalize(user_input))

        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init", data_schema=_build_schema(current)
        )
