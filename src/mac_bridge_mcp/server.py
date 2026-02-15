"""Mac Bridge MCP - bridges AI agents to local macOS capabilities."""

import json
import subprocess
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP

CONFIG_PATH = Path(__file__).parent.parent.parent / "config.json"

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
