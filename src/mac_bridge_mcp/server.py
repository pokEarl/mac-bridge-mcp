"""Mac Bridge MCP - bridges AI agents to local macOS capabilities."""

import json
import subprocess
import sys
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

PROJECT_DIR = Path("/Users/jarlesandnes/ai-projects/mac-bridge-mcp")
CONFIG_PATH = PROJECT_DIR / "config.json"

_http_mode = "--http" in sys.argv

if _http_mode:
    mcp = FastMCP(
        "mac-bridge",
        host="0.0.0.0",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        ),
    )
else:
    mcp = FastMCP("mac-bridge")


def _load_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {}


def _hue_config() -> tuple[str, str] | None:
    """Return (bridge_ip, app_key) or None if not configured."""
    hue = _load_config().get("hue", {})
    bridge_ip = hue.get("bridge_ip")
    app_key = hue.get("app_key")
    if not bridge_ip or not app_key:
        return None
    return bridge_ip, app_key


# ---------------------------------------------------------------------------
# macOS tools
# ---------------------------------------------------------------------------


@mcp.tool()
def run_url_scheme(url: str) -> str:
    """Open a macOS URL scheme. Works with any registered URL scheme on the host Mac.

    Examples:
    - neewerlite://turnOnLight
    - neewerlite://turnOffLight
    - neewerlite://toggleLight
    - shortcuts://run-shortcut?name=MyShortcut
    """
    result = subprocess.run(["open", url], capture_output=True, text=True)
    if result.returncode != 0:
        return f"Error: {result.stderr}"
    return f"Opened: {url}"


@mcp.tool()
def open_application(app_name: str) -> str:
    """Open a macOS application by name.

    Examples: Safari, NeewerLite, Finder, Terminal
    """
    result = subprocess.run(["open", "-a", app_name], capture_output=True, text=True)
    if result.returncode != 0:
        return f"Error opening {app_name}: {result.stderr}"
    return f"Opened: {app_name}"


@mcp.tool()
def run_shortcut(name: str, input_text: str | None = None) -> str:
    """Run a macOS Shortcut by name.

    Args:
        name: The name of the Shortcut to run.
        input_text: Optional text input to pass to the Shortcut.
    """
    cmd = ["shortcuts", "run", name]
    stdin_data = None
    if input_text is not None:
        stdin_data = input_text
    result = subprocess.run(cmd, input=stdin_data, capture_output=True, text=True, timeout=30)
    output = result.stdout.strip()
    if result.returncode != 0:
        return f"Error: {result.stderr}"
    return output if output else f"Shortcut '{name}' executed"


@mcp.tool()
def list_shortcuts() -> str:
    """List all available macOS Shortcuts."""
    result = subprocess.run(["shortcuts", "list"], capture_output=True, text=True)
    if result.returncode != 0:
        return f"Error: {result.stderr}"
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Philips Hue tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def hue_list_lights() -> str:
    """List all Philips Hue lights and their current state."""
    cfg = _hue_config()
    if not cfg:
        return "Error: Hue not configured. Set bridge_ip and app_key in config.json"
    bridge_ip, app_key = cfg

    async with httpx.AsyncClient(verify=False) as client:
        resp = await client.get(
            f"https://{bridge_ip}/clip/v2/resource/light",
            headers={"hue-application-key": app_key},
        )
        if resp.status_code != 200:
            return f"Error {resp.status_code}: {resp.text}"

        lights = resp.json().get("data", [])
        results = []
        for light in lights:
            name = light.get("metadata", {}).get("name", "Unknown")
            lid = light.get("id", "?")
            is_on = light.get("on", {}).get("on", False)
            brightness = light.get("dimming", {}).get("brightness", 0)
            results.append(
                f"- {name} (id: {lid}) — {'ON' if is_on else 'OFF'}, brightness: {brightness}%"
            )
        return "\n".join(results) if results else "No lights found"


@mcp.tool()
async def hue_set_light(
    light_id: str,
    on: bool | None = None,
    brightness: int | None = None,
    color_temp: int | None = None,
) -> str:
    """Control a Philips Hue light.

    Args:
        light_id: The Hue light ID (UUID from hue_list_lights).
        on: Turn the light on (true) or off (false).
        brightness: Brightness 0-100.
        color_temp: Color temperature in mirek (153=cool daylight, 500=warm candlelight).
    """
    cfg = _hue_config()
    if not cfg:
        return "Error: Hue not configured. Set bridge_ip and app_key in config.json"
    bridge_ip, app_key = cfg

    body: dict = {}
    if on is not None:
        body["on"] = {"on": on}
    if brightness is not None:
        body["dimming"] = {"brightness": max(0, min(100, brightness))}
    if color_temp is not None:
        body["color_temperature"] = {"mirek": max(153, min(500, color_temp))}

    if not body:
        return "Error: Specify at least one of: on, brightness, color_temp"

    async with httpx.AsyncClient(verify=False) as client:
        resp = await client.put(
            f"https://{bridge_ip}/clip/v2/resource/light/{light_id}",
            headers={"hue-application-key": app_key},
            json=body,
        )
        if resp.status_code == 200:
            return f"Light {light_id} updated: {json.dumps(body)}"
        return f"Error {resp.status_code}: {resp.text}"


@mcp.tool()
async def hue_list_scenes() -> str:
    """List all available Philips Hue scenes."""
    cfg = _hue_config()
    if not cfg:
        return "Error: Hue not configured. Set bridge_ip and app_key in config.json"
    bridge_ip, app_key = cfg

    async with httpx.AsyncClient(verify=False) as client:
        resp = await client.get(
            f"https://{bridge_ip}/clip/v2/resource/scene",
            headers={"hue-application-key": app_key},
        )
        if resp.status_code != 200:
            return f"Error {resp.status_code}: {resp.text}"

        scenes = resp.json().get("data", [])
        results = []
        for scene in scenes:
            name = scene.get("metadata", {}).get("name", "Unknown")
            sid = scene.get("id", "?")
            results.append(f"- {name} (id: {sid})")
        return "\n".join(results) if results else "No scenes found"


@mcp.tool()
async def hue_activate_scene(scene_id: str) -> str:
    """Activate a Philips Hue scene.

    Args:
        scene_id: The scene ID (UUID from hue_list_scenes).
    """
    cfg = _hue_config()
    if not cfg:
        return "Error: Hue not configured. Set bridge_ip and app_key in config.json"
    bridge_ip, app_key = cfg

    async with httpx.AsyncClient(verify=False) as client:
        resp = await client.put(
            f"https://{bridge_ip}/clip/v2/resource/scene/{scene_id}",
            headers={"hue-application-key": app_key},
            json={"recall": {"action": "active"}},
        )
        if resp.status_code == 200:
            return f"Scene {scene_id} activated"
        return f"Error {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# Vaillant heating tools
# ---------------------------------------------------------------------------


def _vaillant_config() -> tuple[str, str, str, str] | None:
    """Return (email, password, brand, country) or None if not configured."""
    v = _load_config().get("vaillant", {})
    email = v.get("email")
    password = v.get("password")
    if not email or not password:
        return None
    return email, password, v.get("brand", "vaillant"), v.get("country", "czechrepublic")


@mcp.tool()
async def vaillant_status() -> str:
    """Get current status of the Vaillant heating system.

    Returns water pressure, outdoor temperature, zone temperatures,
    hot water status, and holiday mode status.
    """
    cfg = _vaillant_config()
    if not cfg:
        return "Error: Vaillant not configured. Set email and password in config.json"
    email, password, brand, country = cfg

    from myPyllant.api import MyPyllantAPI

    lines = []
    async with MyPyllantAPI(email, password, brand, country) as api:
        async for system in api.get_systems():
            lines.append(f"System: {system.home.home_name or system.home.nomenclature}")
            lines.append(f"Water pressure: {system.water_pressure} bar")
            lines.append(f"Outdoor temp: {system.outdoor_temperature}°C")
            # Check if any zone is in holiday/away mode
            for z in system.zones:
                if z.current_special_function and z.current_special_function != "NONE":
                    lines.append(f"Special function: {z.current_special_function}")
                    break
            else:
                lines.append("Holiday mode: off")
            for z in system.zones:
                mode = z.current_special_function or z.heating.operation_mode_heating
                lines.append(
                    f"Zone '{z.name}': {z.current_room_temperature}°C "
                    f"(target: {z.desired_room_temperature_setpoint}°C, mode: {mode})"
                )
            for dhw in system.domestic_hot_water:
                dhw_temp = f"{dhw.current_dhw_temperature}°C" if dhw.current_dhw_temperature else "N/A"
                lines.append(
                    f"Hot water: {dhw_temp} "
                    f"(target: {dhw.tapping_setpoint}°C, mode: {dhw.operation_mode_dhw}, boosting: {dhw.is_cylinder_boosting})"
                )
    return "\n".join(lines) if lines else "No systems found"


@mcp.tool()
async def vaillant_set_temperature(temperature: float, duration_hours: float = 3.0) -> str:
    """Set a temporary temperature override (quick veto) on the heating zone.

    Args:
        temperature: Target temperature in °C (e.g. 22.0).
        duration_hours: How long the override lasts (default 3 hours).
    """
    cfg = _vaillant_config()
    if not cfg:
        return "Error: Vaillant not configured"
    email, password, brand, country = cfg

    from myPyllant.api import MyPyllantAPI

    async with MyPyllantAPI(email, password, brand, country) as api:
        async for system in api.get_systems():
            if not system.zones:
                return "Error: No heating zones found"
            zone = system.zones[0]
            await api.quick_veto_zone_temperature(zone, temperature, duration_hours)
            return f"Temperature set to {temperature}°C for {duration_hours}h on zone '{zone.name}'"
    return "Error: No systems found"


@mcp.tool()
async def vaillant_cancel_temperature_override() -> str:
    """Cancel any active temporary temperature override."""
    cfg = _vaillant_config()
    if not cfg:
        return "Error: Vaillant not configured"
    email, password, brand, country = cfg

    from myPyllant.api import MyPyllantAPI

    async with MyPyllantAPI(email, password, brand, country) as api:
        async for system in api.get_systems():
            if not system.zones:
                return "Error: No heating zones found"
            zone = system.zones[0]
            await api.cancel_quick_veto_zone_temperature(zone)
            return f"Temperature override cancelled on zone '{zone.name}'"
    return "Error: No systems found"


@mcp.tool()
async def vaillant_set_holiday(start_date: str, end_date: str) -> str:
    """Set holiday mode on the heating system. Reduces heating while away.

    Args:
        start_date: Start date in YYYY-MM-DD format.
        end_date: End date in YYYY-MM-DD format.
    """
    cfg = _vaillant_config()
    if not cfg:
        return "Error: Vaillant not configured"
    email, password, brand, country = cfg

    from datetime import datetime, timezone

    from myPyllant.api import MyPyllantAPI

    start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    async with MyPyllantAPI(email, password, brand, country) as api:
        async for system in api.get_systems():
            await api.set_holiday(system, start, end)
            return f"Holiday mode set: {start_date} to {end_date}"
    return "Error: No systems found"


@mcp.tool()
async def vaillant_cancel_holiday() -> str:
    """Cancel holiday mode on the heating system."""
    cfg = _vaillant_config()
    if not cfg:
        return "Error: Vaillant not configured"
    email, password, brand, country = cfg

    from myPyllant.api import MyPyllantAPI

    async with MyPyllantAPI(email, password, brand, country) as api:
        async for system in api.get_systems():
            await api.cancel_holiday(system)
            return "Holiday mode cancelled"
    return "Error: No systems found"


@mcp.tool()
async def vaillant_boost_hot_water() -> str:
    """Trigger a one-time hot water boost (heats the water tank now)."""
    cfg = _vaillant_config()
    if not cfg:
        return "Error: Vaillant not configured"
    email, password, brand, country = cfg

    from myPyllant.api import MyPyllantAPI

    async with MyPyllantAPI(email, password, brand, country) as api:
        async for system in api.get_systems():
            if not system.domestic_hot_water:
                return "Error: No hot water tank found"
            dhw = system.domestic_hot_water[0]
            await api.boost_domestic_hot_water(dhw)
            return "Hot water boost started"
    return "Error: No systems found"


@mcp.tool()
async def vaillant_set_hot_water_temperature(temperature: float) -> str:
    """Set the hot water target temperature.

    Args:
        temperature: Target temperature in °C (typically 40-65).
    """
    cfg = _vaillant_config()
    if not cfg:
        return "Error: Vaillant not configured"
    email, password, brand, country = cfg

    from myPyllant.api import MyPyllantAPI

    async with MyPyllantAPI(email, password, brand, country) as api:
        async for system in api.get_systems():
            if not system.domestic_hot_water:
                return "Error: No hot water tank found"
            dhw = system.domestic_hot_water[0]
            await api.set_domestic_hot_water_temperature(dhw, temperature)
            return f"Hot water temperature set to {temperature}°C"
    return "Error: No systems found"


def main():
    import sys

    if "--http" in sys.argv:
        port = 18791
        for i, arg in enumerate(sys.argv):
            if arg == "--port" and i + 1 < len(sys.argv):
                port = int(sys.argv[i + 1])
        mcp.settings.port = port
        mcp.settings.host = "0.0.0.0"
        mcp.run(transport="streamable-http")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
