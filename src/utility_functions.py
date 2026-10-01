"""
Utility Functions for DBI Backend
"""

def format_size(size: int) -> str:
    """Format file size in human-readable format"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f'{size:.1f} {unit}'
        size /= 1024.0
    return f'{size:.1f} PB'

def format_time(seconds: int) -> str:
    """Format time in HH:MM:SS format"""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f'{hours:02d}:{minutes:02d}:{secs:02d}'


def format_sphaira_eta(seconds: int) -> str:
    """Format ETA in Sphaira style: 'Xh Ym' (>=1h) or 'Xm Ys' (<1h)."""
    if seconds <= 0:
        return ""
    if seconds >= 3600:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
    return f"{seconds // 60}m {seconds % 60}s"