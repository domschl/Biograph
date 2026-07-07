import socket
import urllib.request
import urllib.error
import json
import os
from datetime import datetime
from typing import Any
import xbmc

# Handle datetime UTC compatibility for older Python versions
try:
    from datetime import UTC
except ImportError:
    import datetime as dt
    class UTC_TZ(dt.tzinfo):
        def utcoffset(self, dt: Any) -> dt.timedelta: return dt.timedelta(0)
        def tzname(self, dt: Any) -> str: return "UTC"
        def dst(self, dt: Any) -> dt.timedelta: return dt.timedelta(0)
    UTC = UTC_TZ()


def parse_config() -> dict[str, str] | None:
    candidates = [
        os.path.expanduser("~/.config/biograph/config.toml"),
        "./config.toml",
        "/etc/biograph/config.toml"
    ]
    if os.environ.get("BIOGRAPH_CONFIG"):
        candidates.insert(0, os.environ.get("BIOGRAPH_CONFIG"))
    for path in candidates:
        if os.path.exists(path):
            try:
                server_url = None
                token = None
                in_server_section = False
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if line.startswith("[") and line.endswith("]"):
                            section = line[1:-1].strip()
                            in_server_section = (section == "server")
                            continue
                        if in_server_section and "=" in line:
                            key, val = line.split("=", 1)
                            key = key.strip()
                            val = val.strip().strip('"').strip("'")
                            if key == "url":
                                server_url = val.rstrip("/")
                            elif key == "token":
                                token = val
                if server_url and token:
                    return {"url": server_url, "token": token}
            except Exception as e:
                xbmc.log(f"[Biograph] Error reading config at {path}: {e}", level=xbmc.LOGERROR)
    return None


def send_event(server_url: str, token: str, event: dict[str, Any]) -> bool:
    url = f"{server_url}/events/"
    data = json.dumps(event).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {token}'
        },
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status == 201
    except Exception as e:
        xbmc.log(f"[Biograph] Failed to send event to server: {e}", level=xbmc.LOGERROR)
        return False


class BiographPlayer(xbmc.Player):
    def __init__(self) -> None:
        super().__init__()
        self.active_item: dict[str, Any] | None = None
        self.last_position: float = 0.0

    def onAVStarted(self) -> None:
        self.check_playback()

    def onPlayBackStarted(self) -> None:
        self.check_playback()

    def check_playback(self) -> None:
        if not self.isPlayingVideo():
            return
        self.last_position = 0.0
        
        try:
            tag = self.getVideoInfoTag()
            media_type = tag.getMediaType()
            if media_type == 'movie':
                self.active_item = {
                    'type': 'movie',
                    'title': tag.getTitle(),
                    'year': tag.getYear(),
                    'imdb_id': tag.getIMDBNumber(),
                    'db_id': tag.getDbId(),
                    'file': self.getPlayingFile(),
                    'duration': self.getTotalTime(),
                    'started_at': datetime.now(UTC).isoformat()
                }
                xbmc.log(f"[Biograph] Started tracking movie: {self.active_item['title']}", level=xbmc.LOGINFO)
            elif media_type == 'episode':
                self.active_item = {
                    'type': 'episode',
                    'title': tag.getTitle(),
                    'tvshow_title': tag.getTVShowTitle(),
                    'season': tag.getSeason(),
                    'episode': tag.getEpisode(),
                    'year': tag.getYear(),
                    'imdb_id': tag.getIMDBNumber(),
                    'db_id': tag.getDbId(),
                    'file': self.getPlayingFile(),
                    'duration': self.getTotalTime(),
                    'started_at': datetime.now(UTC).isoformat()
                }
                season = self.active_item.get('season')
                episode = self.active_item.get('episode')
                season_str = f"S{season:02d}" if isinstance(season, int) else f"S{season}"
                episode_str = f"E{episode:02d}" if isinstance(episode, int) else f"E{episode}"
                xbmc.log(f"[Biograph] Started tracking TV show: {self.active_item['tvshow_title']} {season_str}{episode_str} - {self.active_item['title']}", level=xbmc.LOGINFO)
            else:
                self.active_item = None
        except Exception as e:
            xbmc.log(f"[Biograph] Error getting video info tag: {e}", level=xbmc.LOGERROR)
            self.active_item = None

    def onPlayBackEnded(self) -> None:
        if self.active_item:
            item_name = self.active_item.get('tvshow_title') if self.active_item.get('type') == 'episode' else self.active_item.get('title')
            xbmc.log(f"[Biograph] Playback ended naturally for: {item_name}", level=xbmc.LOGINFO)
            self.log_watched(finished=True)
        self.active_item = None

    def onPlayBackStopped(self) -> None:
        if self.active_item:
            try:
                try:
                    current_time = self.getTime()
                except Exception:
                    current_time = getattr(self, 'last_position', 0.0)

                total_time = self.active_item['duration']
                if total_time > 0:
                    progress = (current_time / total_time) * 100
                    item_name = self.active_item.get('tvshow_title') if self.active_item.get('type') == 'episode' else self.active_item.get('title')
                    xbmc.log(f"[Biograph] Playback stopped for: {item_name} at {progress:.1f}%", level=xbmc.LOGINFO)
                    if progress >= 85:
                        is_finished = progress >= 99.0
                        self.log_watched(finished=is_finished, progress=progress)
            except Exception as e:
                xbmc.log(f"[Biograph] Error checking playback progress: {e}", level=xbmc.LOGERROR)
        self.active_item = None

    def log_watched(self, finished: bool = True, progress: float = 100.0) -> None:
        if not self.active_item:
            return

        config = parse_config()
        if not config:
            xbmc.log("[Biograph] Configuration not found, skipping event logging.", level=xbmc.LOGWARNING)
            return

        item_type = self.active_item.get('type', 'movie')
        if item_type == 'episode':
            event_type = "kodi-tvshow"
            content = {
                "title": self.active_item["title"],
                "tvshow_title": self.active_item["tvshow_title"],
                "season": self.active_item["season"],
                "episode": self.active_item["episode"],
                "year": self.active_item["year"],
                "imdb_id": self.active_item["imdb_id"],
                "db_id": self.active_item["db_id"],
                "file": self.active_item["file"],
                "duration_seconds": int(self.active_item["duration"]),
                "progress_percent": round(progress, 1),
                "finished": finished
            }
            tags = ["media", "tvshow", "kodi"]
            season = self.active_item.get('season')
            episode = self.active_item.get('episode')
            season_str = f"S{season:02d}" if isinstance(season, int) else f"S{season}"
            episode_str = f"E{episode:02d}" if isinstance(episode, int) else f"E{episode}"
            display_title = f"{self.active_item['tvshow_title']} {season_str}{episode_str} - {self.active_item['title']}"
        else:
            event_type = "kodi-movie"
            content = {
                "title": self.active_item["title"],
                "year": self.active_item["year"],
                "imdb_id": self.active_item["imdb_id"],
                "db_id": self.active_item["db_id"],
                "file": self.active_item["file"],
                "duration_seconds": int(self.active_item["duration"]),
                "progress_percent": round(progress, 1),
                "finished": finished
            }
            tags = ["media", "movie", "kodi"]
            display_title = self.active_item["title"]

        event = {
            "timestamp": datetime.now(UTC).isoformat(),
            "ev_type": event_type,
            "source_host": socket.gethostname(),
            "source_app": "kodi-addon",
            "content": content,
            "tags": tags
        }

        xbmc.log(f"[Biograph] Sending watched event: {display_title}", level=xbmc.LOGINFO)
        success = send_event(config["url"], config["token"], event)
        if success:
            xbmc.log(f"[Biograph] Event logged successfully for: {display_title}", level=xbmc.LOGINFO)
        else:
            xbmc.log(f"[Biograph] Failed to log event for: {display_title}", level=xbmc.LOGWARNING)


if __name__ == '__main__':
    monitor = xbmc.Monitor()
    player = BiographPlayer()
    
    xbmc.log("[Biograph] Background service started", level=xbmc.LOGINFO)
    
    while not monitor.abortRequested():
        if player.active_item:
            try:
                if player.isPlayingVideo():
                    player.last_position = player.getTime()
            except Exception:
                pass
        if monitor.waitForAbort(2):
            break
            
    xbmc.log("[Biograph] Background service shutting down", level=xbmc.LOGINFO)
