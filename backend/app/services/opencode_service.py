import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal


@dataclass(frozen=True)
class OpencodeBlock:
    id: str
    kind: Literal["user", "agent", "activity"]
    content: str
    timestamp: datetime


@dataclass(frozen=True)
class OpencodeHistory:
    session_id: str
    opencode_session_id: str
    title: str | None
    directory: str
    collected_at: datetime
    blocks: list[OpencodeBlock]


def _format_tool_content(tool_name: str, state: Any) -> str:
    if not isinstance(state, dict):
        return f"Tool [{tool_name}]"
    
    inp = state.get("input")
    out = state.get("output")
    parts: list[str] = []
    
    if isinstance(inp, dict):
        if tool_name == "bash" and "command" in inp:
            parts.append(f"$ {inp['command']}")
        elif tool_name == "read" and "filePath" in inp:
            parts.append(f"Read {inp['filePath']}")
        elif tool_name == "edit" and "filePath" in inp:
            parts.append(f"Edit {inp['filePath']}")
        elif tool_name == "websearch" and "query" in inp:
            parts.append(f"Search: {inp['query']}")
        elif tool_name == "webfetch" and "url" in inp:
            parts.append(f"Fetch: {inp['url']}")
        else:
            formatted_inp = ", ".join(f"{k}={v!r}" for k, v in inp.items() if v is not None)
            parts.append(f"Tool [{tool_name}] {formatted_inp}".strip())
    else:
        parts.append(f"Tool [{tool_name}]")

    if isinstance(out, str) and out.strip():
        parts.append(out.strip())
        
    return "\n\n".join(parts)


class OpencodeService:
    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)

    def read_history(
        self,
        directory: str,
        session_id: str,
        max_blocks: int = 500,
        min_timestamp: datetime | None = None,
    ) -> OpencodeHistory | None:
        if not self.db_path.exists() or not self.db_path.is_file():
            return None

        # Normalizza la directory per matchare con la colonna directory in sqlite
        norm_dir = str(Path(directory).resolve())

        try:
            conn = sqlite3.connect(
                f"file:{self.db_path.resolve()}?mode=ro",
                uri=True,
                timeout=2.0,
            )
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            query = """
                SELECT id, title, directory, time_created, time_updated
                FROM session
                WHERE (directory = ? OR directory = ?)
            """
            params: list[Any] = [directory, norm_dir]

            if min_timestamp is not None:
                min_ms = int(min_timestamp.timestamp() * 1000)
                query += " AND time_created >= ?"
                params.append(min_ms)

            # A parita' di directory, la conversazione appartiene al pane tmux
            # che era attivo alla sua nascita: scegliere la prima nata dopo
            # l'avvio del pane e non quella con time_updated piu' recente, che
            # potrebbe appartenere a una sessione diversa (anche gia' chiusa).
            query += " ORDER BY time_created ASC LIMIT 1"

            session_row = cursor.execute(query, tuple(params)).fetchone()

            if not session_row:
                conn.close()
                return OpencodeHistory(
                    session_id=session_id,
                    opencode_session_id="",
                    title=None,
                    directory=norm_dir,
                    collected_at=datetime.now(UTC),
                    blocks=[],
                )

            opencode_session_id = str(session_row["id"])
            title = session_row["title"]

            # Recupera messaggi e parti
            messages = cursor.execute(
                """
                SELECT id, time_created, data
                FROM message
                WHERE session_id = ?
                ORDER BY time_created ASC
                """,
                (opencode_session_id,),
            ).fetchall()

            parts = cursor.execute(
                """
                SELECT id, message_id, time_created, data
                FROM part
                WHERE session_id = ?
                ORDER BY time_created ASC
                """,
                (opencode_session_id,),
            ).fetchall()

            conn.close()
        except (sqlite3.Error, OSError):
            return None

        parts_by_msg: dict[str, list[dict[str, Any]]] = {}
        for row in parts:
            try:
                p_data = json.loads(row["data"])
                if isinstance(p_data, dict):
                    parts_by_msg.setdefault(str(row["message_id"]), []).append(p_data)
            except json.JSONDecodeError:
                continue

        blocks: list[OpencodeBlock] = []

        for row in messages:
            msg_id = str(row["id"])
            t_ms = row["time_created"]
            timestamp = (
                datetime.fromtimestamp(t_ms / 1000.0, tz=UTC)
                if isinstance(t_ms, (int, float))
                else datetime.now(UTC)
            )

            try:
                m_data = json.loads(row["data"])
            except json.JSONDecodeError:
                continue

            if not isinstance(m_data, dict):
                continue

            role = m_data.get("role", "assistant")
            msg_parts = parts_by_msg.get(msg_id, [])

            if role == "user":
                user_texts: list[str] = []
                for p in msg_parts:
                    if p.get("type") == "text" and isinstance(p.get("text"), str):
                        user_texts.append(p["text"])
                body = "\n\n".join(t.strip() for t in user_texts if t.strip())
                if body:
                    blocks.append(
                        OpencodeBlock(
                            id=msg_id,
                            kind="user",
                            content=body,
                            timestamp=timestamp,
                        )
                    )
            else:
                for idx, p in enumerate(msg_parts):
                    p_type = p.get("type")
                    part_id = f"{msg_id}-{idx}"

                    if p_type == "text" and isinstance(p.get("text"), str):
                        text = p["text"].strip()
                        if text:
                            blocks.append(
                                OpencodeBlock(
                                    id=part_id,
                                    kind="agent",
                                    content=text,
                                    timestamp=timestamp,
                                )
                            )
                    elif p_type == "tool":
                        tool_name = str(p.get("tool", "tool"))
                        tool_content = _format_tool_content(tool_name, p.get("state"))
                        if tool_content:
                            blocks.append(
                                OpencodeBlock(
                                    id=part_id,
                                    kind="activity",
                                    content=tool_content,
                                    timestamp=timestamp,
                                )
                            )

        if max_blocks and len(blocks) > max_blocks:
            blocks = blocks[-max_blocks:]

        return OpencodeHistory(
            session_id=session_id,
            opencode_session_id=opencode_session_id,
            title=title,
            directory=norm_dir,
            collected_at=datetime.now(UTC),
            blocks=blocks,
        )
