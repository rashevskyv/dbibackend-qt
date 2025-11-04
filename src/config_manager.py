"""
Configuration Manager
Handles application settings and persistence
"""

import json
from pathlib import Path
from typing import Any, Optional


class ConfigManager:
    """Manages application configuration"""

    DEFAULT_CONFIG = {
        'theme': 'light',
        'auto_connect': True,
        'buffer_size': 1048576,  # 1 MB
        'file_filters': ['.nsp', '.nsz', '.xci', '.nca'],
        'last_directory': '',
        'window_geometry': None,
        'max_log_lines': 1000,
        'reconnect_interval': 2000,  # ms
    }

    def __init__(self, config_path: Optional[Path] = None):
        """Initialize configuration manager"""
        if config_path is None:
            # Use default path in user's home directory
            self.config_path = Path.home() / '.dbibackend-qt' / 'config.json'
        else:
            self.config_path = config_path

        self.config = {}
        self.load()

    def load(self):
        """Load configuration from file"""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
            except Exception as e:
                print(f'Failed to load config: {e}')
                self.config = self.DEFAULT_CONFIG.copy()
        else:
            self.config = self.DEFAULT_CONFIG.copy()

    def save(self):
        """Save configuration to file"""
        try:
            # Create directory if it doesn't exist
            self.config_path.parent.mkdir(parents=True, exist_ok=True)

            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            print(f'Failed to save config: {e}')

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value"""
        return self.config.get(key, default)

    def set(self, key: str, value: Any):
        """Set configuration value"""
        self.config[key] = value

    def reset(self):
        """Reset configuration to defaults"""
        self.config = self.DEFAULT_CONFIG.copy()
        self.save()
