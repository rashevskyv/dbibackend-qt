import sys
import ctypes
from ctypes import wintypes

# comtypes is an external dependency: pip install comtypes
try:
    import comtypes
    import comtypes.client
    from comtypes import GUID, IUnknown, COMMETHOD
    # HRESULT is typically available in comtypes
    from comtypes import HRESULT
except ImportError:
    comtypes = None
    HRESULT = ctypes.c_long # Fallback

if comtypes:
    # Manual definition of ITaskbarList3 to avoid dependency on generated comtypes.gen
    class ITaskbarList(IUnknown):
        _iid_ = GUID("{56FDF342-FD6D-11D0-958A-006097C9A090}")
        _methods_ = [
            COMMETHOD([], HRESULT, "HrInit"),
            COMMETHOD([], HRESULT, "AddTab", (['in'], wintypes.HWND, "hwnd")),
            COMMETHOD([], HRESULT, "DeleteTab", (['in'], wintypes.HWND, "hwnd")),
            COMMETHOD([], HRESULT, "ActivateTab", (['in'], wintypes.HWND, "hwnd")),
            COMMETHOD([], HRESULT, "SetActiveAlt", (['in'], wintypes.HWND, "hwnd")),
        ]

    class ITaskbarList2(ITaskbarList):
        _iid_ = GUID("{602D4995-B13D-4282-B08B-BA058130740D}")
        _methods_ = [
            COMMETHOD([], HRESULT, "MarkFullscreenWindow", 
                      (['in'], wintypes.HWND, "hwnd"), 
                      (['in'], wintypes.BOOL, "fFullscreen")),
        ]

    class ITaskbarList3(ITaskbarList2):
        _iid_ = GUID("{EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF}")
        _methods_ = [
            COMMETHOD([], HRESULT, "SetProgressValue", 
                      (['in'], wintypes.HWND, "hwnd"), 
                      (['in'], ctypes.c_ulonglong, "ullCompleted"), 
                      (['in'], ctypes.c_ulonglong, "ullTotal")),
            COMMETHOD([], HRESULT, "SetProgressState", 
                      (['in'], wintypes.HWND, "hwnd"), 
                      (['in'], ctypes.c_int, "tbpFlags")),
            COMMETHOD([], HRESULT, "RegisterTab", (['in'], wintypes.HWND, "hwndTab"), (['in'], wintypes.HWND, "hwndMDI")),
            COMMETHOD([], HRESULT, "UnregisterTab", (['in'], wintypes.HWND, "hwndTab")),
            COMMETHOD([], HRESULT, "SetTabOrder", (['in'], wintypes.HWND, "hwndTab"), (['in'], wintypes.HWND, "hwndInsertBefore")),
            COMMETHOD([], HRESULT, "SetTabActive", (['in'], wintypes.HWND, "hwndTab"), (['in'], wintypes.HWND, "hwndMDI"), (['in'], ctypes.c_int, "tbpFlags")),
            COMMETHOD([], HRESULT, "ThumbBarAddButtons", (['in'], wintypes.HWND, "hwnd"), (['in'], ctypes.c_uint, "cButtons"), (['in'], ctypes.c_void_p, "pButton")),
            COMMETHOD([], HRESULT, "ThumbBarUpdateButtons", (['in'], wintypes.HWND, "hwnd"), (['in'], ctypes.c_uint, "cButtons"), (['in'], ctypes.c_void_p, "pButton")),
            COMMETHOD([], HRESULT, "ThumbBarSetImageList", (['in'], wintypes.HWND, "hwnd"), (['in'], ctypes.c_void_p, "himl")),
            COMMETHOD([], HRESULT, "SetOverlayIcon", (['in'], wintypes.HWND, "hwnd"), (['in'], wintypes.HICON, "hIcon"), (['in'], wintypes.LPCWSTR, "pszDescription")),
            COMMETHOD([], HRESULT, "SetThumbnailTooltip", (['in'], wintypes.HWND, "hwnd"), (['in'], wintypes.LPCWSTR, "pszTip")),
            COMMETHOD([], HRESULT, "SetThumbnailClip", (['in'], wintypes.HWND, "hwnd"), (['in'], ctypes.c_void_p, "prcClip")),
        ]

class TaskbarManager:
    """A wrapper for the Windows ITaskbarList3 interface."""

    def __init__(self, window_handle):
        self.taskbar_list = None
        self.hwnd = 0
        if sys.platform != 'win32' or comtypes is None:
            return

        try:
            # Create an instance of the ITaskbarList3 interface using our manual definition
            self.taskbar_list = comtypes.client.CreateObject(
                "{56FDF344-FD6D-11D0-958A-006097C9A090}",
                interface=ITaskbarList3
            )
            self.taskbar_list.HrInit()
            
            # Get the HWND (window handle) of our main window
            if isinstance(window_handle, int):
                self.hwnd = window_handle
            else: # It's a QWindow object
                try:
                    self.hwnd = int(window_handle.winId())
                except:
                    self.hwnd = 0

        except Exception as e:
            # If comtypes fails or is not installed, disable this feature
            self.taskbar_list = None
            print(f"Warning: Failed to initialize Windows taskbar integration: {e}")

    def set_progress_state(self, state: int):
        """
        Sets the state of the taskbar progress.
        States: 0=NoProgress, 1=Indeterminate, 2=Normal, 4=Error, 8=Paused
        """
        if self.taskbar_list and self.hwnd:
            try:
                self.taskbar_list.SetProgressState(self.hwnd, state)
            except:
                pass

    def set_progress_value(self, value: int, total: int = 100):
        """Sets the progress value (0-100)."""
        if self.taskbar_list and self.hwnd:
            try:
                if value >= total:
                    # When done, hide the progress bar
                    self.hide_progress()
                else:
                    self.set_progress_state(2) # Normal (TBPF_NORMAL = 0x2)
                    self.taskbar_list.SetProgressValue(self.hwnd, value, total)
            except:
                pass

    def show_progress(self):
        """Makes the progress bar visible."""
        if self.taskbar_list and self.hwnd:
            self.set_progress_state(2) # Normal

    def hide_progress(self):
        """Hides the progress bar."""
        if self.taskbar_list and self.hwnd:
            self.set_progress_state(0) # NoProgress (TBPF_NOPROGRESS = 0x0)