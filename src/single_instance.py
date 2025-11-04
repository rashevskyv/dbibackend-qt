"""
Single Instance Manager
Ensures only one instance of the application runs at a time
"""

import sys
from pathlib import Path
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstanceManager(QObject):
    """Manages single instance application behavior"""

    message_received = pyqtSignal(str)  # Emitted when another instance sends a message

    def __init__(self, app_id: str = "dbibackend_qt_instance"):
        super().__init__()
        self.app_id = app_id
        self.server = None
        self.is_primary = False

    def try_start(self, args: list = None) -> bool:
        """
        Try to start as primary instance.
        Returns True if this is the primary instance, False if another exists.
        If another instance exists, sends args to it.
        """
        # Try to connect to existing instance
        socket = QLocalSocket()
        socket.connectToServer(self.app_id)

        if socket.waitForConnected(500):
            # Another instance is running, send message and exit
            if args:
                message = "\n".join(args)
                socket.write(message.encode('utf-8'))
                socket.waitForBytesWritten(1000)
            socket.disconnectFromServer()
            return False

        # No other instance, become the primary
        self.server = QLocalServer()

        # Remove any stale server instance
        QLocalServer.removeServer(self.app_id)

        if not self.server.listen(self.app_id):
            print(f"Warning: Could not start single instance server: {self.server.errorString()}")
            return True  # Continue anyway

        self.server.newConnection.connect(self._on_new_connection)
        self.is_primary = True
        return True

    def _on_new_connection(self):
        """Handle connection from another instance"""
        client = self.server.nextPendingConnection()
        if not client:
            return

        # Read the message
        client.waitForReadyRead(1000)
        data = client.readAll()

        if data:
            try:
                message = bytes(data).decode('utf-8')
                self.message_received.emit(message)
            except Exception as e:
                print(f"Error decoding message: {e}")

        client.disconnectFromServer()
        client.deleteLater()

    def cleanup(self):
        """Cleanup the server"""
        if self.server:
            self.server.close()
            QLocalServer.removeServer(self.app_id)
