# UniFi Protect Auto-View & Alerts for Home Assistant

Automatically displays live camera streams when a UniFi Protect doorbell is pressed or a person is detected, with **zero manual camera setup**.

## Features
- **Zero-config discovery:** finds all UniFi Protect cameras, doorbells and person sensors from the UniFi Protect integration. New cameras are picked up automatically.
- **Camera viewer panel:** a **Cameras** page in the sidebar with a live grid of every UniFi camera, click-to-enlarge, column and live/snapshot controls, and automatic jump to the right camera on a doorbell ring or person detection.
- **Dashboard / wall tablet popups:** shows the live feed via Browser Mod and closes it after a configurable timeout.
- **TV & smart display casting:** streams to Google TV, Chromecast or Nest Hubs. Optionally turns the player off afterwards (only if it was idle before the cast).
- **Mobile live previews:** high-priority iOS and Android Companion App notifications with the live stream.

## Requirements
- The core **UniFi Protect** integration, set up and working
- Optional: [Browser Mod](https://github.com/thomasloven/hass-browser_mod) for popups
- Optional: the `stream` integration for casting

## Installation
1. Copy the `custom_components/unifi_protect_auto_view` folder into the `custom_components` folder of your Home Assistant config directory (create `custom_components` if it doesn't exist).
2. Restart Home Assistant.
3. Go to **Settings > Devices & services > Add integration**, search for **UniFi Protect Auto-View**, choose your options and click **Submit**.

## Camera viewer
After setup a **Cameras** entry appears in the sidebar (turn it off under Configure if you don't want it). Tiles show each camera's high-resolution stream; click a tile to enlarge it, press Esc or Close to return. Controls: column count, live video vs. refreshing snapshots (lighter on busy networks), package cameras, and "Jump to events". The panel is visible to every Home Assistant user, the same as the camera entities themselves.

## Changing settings later
Open the integration in **Settings > Devices & services** and click **Configure**. The integration reloads automatically.

## Notes
- **Doorbell rings need a local user.** UniFi Protect exposes ring events only when the UniFi Protect integration is set up with "API key and local user". Person detection works in either mode.
- Notify services are entered comma-separated, e.g. `notify.mobile_app_iphone, notify.mobile_app_pixel`.
- If a new event arrives while a popup or cast is still showing, the timeout restarts rather than closing early.
