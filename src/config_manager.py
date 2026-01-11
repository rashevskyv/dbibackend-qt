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
        'theme': 'auto',
        'auto_connect': True,
        'http_port': 8080,
        # Separate directories for different actions
        'last_file_directory': '',
        'last_folder_directory': '',
        'last_preset_directory': '',
        'window_geometry': None,
        'splitter_sizes': None,
        'file_tree_zoom': 0,
    }

    def __init__(self, config_path: Optional[Path] = None):
        """Initialize configuration manager"""
        if config_path is None:
            import sys
            if getattr(sys, 'frozen', False):
                app_dir = Path(sys.executable).parent
            else:
                app_dir = Path(__file__).parent.parent.parent
            
            if app_dir.name == 'src': 
                app_dir = app_dir.parent
                
            self.config_path = app_dir / 'config.json'
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
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            print(f'Failed to save config: {e}')

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value with fallback to default"""
        return self.config.get(key, default if default is not None else self.DEFAULT_CONFIG.get(key))

    def set(self, key: str, value: Any):
        """Set configuration value"""
        self.config[key] = value