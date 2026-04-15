"""캘린더 — macOS Calendar.app (osascript) / cross-platform ICS 파일.

간이 구현: 이벤트 추가만. 조회/삭제는 macOS만 지원.
"""

from __future__ import annotations

import asyncio
import platform
from datetime import datetime, timedelta
from pathlib import Path


class CalendarTool:
    async def add_event(
        self,
        title: str,
        start: str,        # ISO format "2026-04-15T15:00"
        duration_minutes: int = 60,
        notes: str = "",
        calendar_name: str = "",
    ) -> str:
        try:
            start_dt = datetime.fromisoformat(start)
        except ValueError:
            return f"start 형식 오류 (ISO 8601 필요, 예: 2026-04-15T15:00): {start}"
        end_dt = start_dt + timedelta(minutes=duration_minutes)

        system = platform.system()
        if system == "Darwin":
            return await self._add_macos(title, start_dt, end_dt, notes, calendar_name)
        else:
            return self._add_ics(title, start_dt, end_dt, notes)

    async def _add_macos(self, title, start, end, notes, calendar):
        cal_clause = f'tell calendar "{calendar}"' if calendar else "tell calendar 1"
        script = f'''
tell application "Calendar"
  {cal_clause}
    make new event with properties {{summary:"{title}", start date:date "{start.strftime("%Y-%m-%d %H:%M:%S")}", end date:date "{end.strftime("%Y-%m-%d %H:%M:%S")}", description:"{notes}"}}
  end tell
end tell
'''
        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e", script,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            return f"캘린더 추가 실패: {err.decode('utf-8', errors='replace')}"
        return f"캘린더 이벤트 추가: {title} @ {start}"

    def _add_ics(self, title, start, end, notes):
        path = Path.home() / ".raphael" / f"event_{int(start.timestamp())}.ics"
        path.parent.mkdir(parents=True, exist_ok=True)
        ics = (
            "BEGIN:VCALENDAR\n"
            "VERSION:2.0\n"
            "PRODID:-//Raphael//EN\n"
            "BEGIN:VEVENT\n"
            f"SUMMARY:{title}\n"
            f"DTSTART:{start.strftime('%Y%m%dT%H%M%S')}\n"
            f"DTEND:{end.strftime('%Y%m%dT%H%M%S')}\n"
            f"DESCRIPTION:{notes}\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        path.write_text(ics, encoding="utf-8")
        return f"ICS 파일 생성: {path} (캘린더 앱에 가져오기 하세요)"
