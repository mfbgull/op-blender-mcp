"""
Telemetry configuration for op-blender-mcp
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class TelemetryConfig:
    """Configuration for telemetry collection"""

    enabled: bool = True
    supabase_url: str = "https://example.supabase.co"
    supabase_anon_key: str = "anon-key-placeholder"
    max_prompt_length: int = 2000


# Global telemetry configuration
telemetry_config = TelemetryConfig()


def get_telemetry_config() -> TelemetryConfig:
    """Get the global telemetry configuration"""
    return telemetry_config


def set_telemetry_enabled(enabled: bool) -> None:
    """Enable or disable telemetry"""
    global telemetry_config
    telemetry_config.enabled = enabled


def set_supabase_config(url: str, anon_key: str) -> None:
    """Configure Supabase for telemetry"""
    global telemetry_config
    telemetry_config.supabase_url = url
    telemetry_config.supabase_anon_key = anon_key
