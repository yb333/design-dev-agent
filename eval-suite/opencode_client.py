"""OpenCode HTTP API client for eval execution."""
from __future__ import annotations

import json
import time
import urllib.request
import urllib.error
from dataclasses import dataclass


@dataclass
class SessionInfo:
    id: str
    status: str  # "idle", "busy"
    title: str


class OpenCodeClient:
    """Minimal HTTP client for OpenCode sidecar."""

    def __init__(self, base_url: str = "http://localhost:4096", timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def health_check(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.base_url}/global/health", method="GET")
            resp = urllib.request.urlopen(req, timeout=5)
            data = json.loads(resp.read())
            return data.get("healthy", False)
        except Exception:
            return False

    def create_session(self, title: str = "Eval Session", directory: str | None = None) -> str:
        """Create a new session, return session ID."""
        url = f"{self.base_url}/session"
        params = []
        if directory:
            params.append(f"directory={directory}")
        if params:
            url += "?" + "&".join(params)

        body = json.dumps({"title": title}).encode()
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=self.timeout)
        data = json.loads(resp.read())
        return data["id"]

    def send_prompt_async(self, session_id: str, content: str, directory: str | None = None) -> None:
        url = f"{self.base_url}/session/{session_id}/prompt_async"
        params = []
        if directory:
            params.append(f"directory={directory}")
        if params:
            url += "?" + "&".join(params)

        body = json.dumps({
            "parts": [{"type": "text", "text": content}]
        }).encode()
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            resp.read()
        except urllib.error.HTTPError as e:
            if e.code != 204:
                raise

    def send_command(self, session_id: str, command: str, arguments: str = "",
                     directory: str | None = None) -> None:
        url = f"{self.base_url}/session/{session_id}/command"
        params = []
        if directory:
            params.append(f"directory={directory}")
        if params:
            url += "?" + "&".join(params)

        body = json.dumps({
            "command": command,
            "arguments": arguments,
        }).encode()
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=10)
        resp.read()

    def get_session(self, session_id: str) -> SessionInfo | None:
        try:
            req = urllib.request.Request(
                f"{self.base_url}/session/{session_id}",
                method="GET",
            )
            resp = urllib.request.urlopen(req, timeout=self.timeout)
            data = json.loads(resp.read())
            return SessionInfo(
                id=data.get("id", session_id),
                status="unknown",
                title=data.get("title", ""),
            )
        except Exception:
            return None

    def get_session_status(self, session_id: str, directory: str | None = None) -> str:
        try:
            url = f"{self.base_url}/session/status"
            params = []
            if directory:
                params.append(f"directory={directory}")
            if params:
                url += "?" + "&".join(params)
            req = urllib.request.Request(url, method="GET")
            resp = urllib.request.urlopen(req, timeout=self.timeout)
            data = json.loads(resp.read())
            entry = data.get(session_id, {})
            return entry.get("type", "unknown")
        except Exception:
            return "unknown"

    def get_pending_questions(self, session_id: str, directory: str | None = None) -> list[dict]:
        try:
            url = f"{self.base_url}/question"
            params = []
            if directory:
                params.append(f"directory={directory}")
            if params:
                url += "?" + "&".join(params)
            req = urllib.request.Request(url, method="GET")
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read())
            return [q for q in data if q.get("sessionID") == session_id]
        except Exception:
            return []

    def reply_question(self, request_id: str, answers: list[list[str]],
                       directory: str | None = None) -> None:
        url = f"{self.base_url}/question/{request_id}/reply"
        params = []
        if directory:
            params.append(f"directory={directory}")
        if params:
            url += "?" + "&".join(params)
        body = json.dumps({"answers": answers}).encode()
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            resp.read()
        except urllib.error.HTTPError as e:
            if e.code != 204:
                raise

    def _auto_reply(self, session_id: str, directory: str | None) -> None:
        pending = self.get_pending_questions(session_id, directory=directory)
        for q in pending:
            qid = q.get("id", "")
            questions = q.get("questions", [])
            if not questions:
                continue
            first_q = questions[0]
            options = first_q.get("options", [])
            if options:
                answer = options[0]["label"]
            else:
                answer = "确认"
            print(f"  [eval] Auto-replying question {qid}: {answer}")
            try:
                self.reply_question(qid, [[answer]], directory=directory)
            except Exception as exc:
                print(f"  [WARN] Failed to reply question: {exc}")

    def wait_for_completion(self, session_id: str, poll_interval: int = 5,
                            timeout: int = 600, directory: str | None = None) -> bool:
        start = time.time()
        while time.time() - start < timeout:
            elapsed = int(time.time() - start)
            self._auto_reply(session_id, directory)
            status = self.get_session_status(session_id, directory=directory)
            if status == "idle":
                return True
            if status == "unknown":
                print(f"  [WARN] Session {session_id} status unknown, stopping poll")
                return False
            print(f"  [eval] Waiting... ({elapsed}s elapsed, status={status})")
            time.sleep(poll_interval)
        print(f"  [WARN] Timeout after {timeout}s, session still busy")
        return False
