"""
Taskbar Manager for Windows
Handles the progress bar on the taskbar icon.
Uses comtypes to interact with the Windows ITaskbarList3 interface.
"""
import sys
import ctypes
from ctypes import wintypes

# comtypes is an external dependency: pip install comtypes
try:
    import comtypes.client
except ImportError:
    comtypes = None

class TaskbarManager:
    """A wrapper for the Windows ITaskbarList3 interface."""

    def __init__(self, window_handle):
        self.taskbar_list = None
        if sys.platform != 'win32' or comtypes is None:
            return

        try:
            # Create an instance of the ITaskbarList3 interface
            self.taskbar_list = comtypes.client.CreateObject(
                "{56FDF344-FD6D-11d0-958A-006097C9A090}",
                interface=comtypes.gen.TaskbarLib.ITaskbarList3
            )
            self.taskbar_list.HrInit()
            
            # Get the HWND (window handle) of our main window
            if isinstance(window_handle, int):
                self.hwnd = window_handle
            else: # It's a QWindow object
                self.hwnd = int(window_handle.winId())

        except (OSError, AttributeError, ImportError):
            # If comtypes fails or is not installed, disable this feature
            self.taskbar_list = None
            print("Warning: Failed to initialize Windows taskbar integration.")

    def set_progress_state(self, state: int):
        """
        Sets the state of the taskbar progress.
        States: 0=NoProgress, 1=Indeterminate, 2=Normal, 4=Error, 8=Paused
        """
        if self.taskbar_list:
            TBPF_NORMAL = 0x2
            self.taskbar_list.SetProgressState(self.hwnd, TBPF_NORMAL)

    def set_progress_value(self, value: int, total: int = 100):
        """Sets the progress value (0-100)."""
        if self.taskbar_list:
            if value >= total:
                # When done, hide the progress bar
                self.hide_progress()
            else:
                self.set_progress_state(2) # Normal
                self.taskbar_list.SetProgressValue(self.hwnd, value, total)

    def show_progress(self):
        """Makes the progress bar visible."""
        if self.taskbar_list:
            self.set_progress_state(2) # Normal

    def hide_progress(self):
        """Hides the progress bar."""
        if self.taskbar_list:
            TBPF_NOPROGRESS = 0x0
            self.taskbar_list.SetProgressState(self.hwnd, TBPF_NOPROGRESS)