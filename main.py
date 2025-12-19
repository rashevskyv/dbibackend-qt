#!/usr/bin/env python3
"""
DBI Backend Qt - Main Entry Point
Enhanced GUI for DBI file transfer to Nintendo Switch
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent)) # Add parent directory of src to path
from PyQt6.QtWidgets import QApplication
from src.main_window import MainWindow
from src.single_instance import SingleInstanceManager


def main():
    """Main application entry point"""
    app = QApplication(sys.argv)
    app.setApplicationName('DBI Backend Qt')
    app.setStyle('Fusion') 
    app.setOrganizationName('DBI Backend')

    # Setup single instance manager
    instance_manager = SingleInstanceManager()

    # Try to start as primary instance
    args = sys.argv[1:] if len(sys.argv) > 1 else None
    if not instance_manager.try_start(args):
        # Another instance is running, we sent the files and can exit
        print("Another instance is already running. Files sent to existing instance.")
        sys.exit(0)

    # Create main window
    window = MainWindow()

    # Connect instance manager to window
    instance_manager.message_received.connect(window.handle_external_files)

    # Process command line arguments (for "Send to" integration)
    if args:
        window.handle_external_files("\n".join(args))

    window.show()

    # Cleanup on exit
    app.aboutToQuit.connect(instance_manager.cleanup)

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
