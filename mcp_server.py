#!/usr/bin/env python3
"""
Project AgentBoard — Stdio MCP Server (JSON-RPC 2.0)
Allows AI agents (Gemini, Antigravity, Claude Code, Cursor) to read/write board.db
with minimal token overhead.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agentboard  # noqa: E402

TOOLS = [
    {
        "name": "board_list",
        "description": "List tasks from AgentBoard SQLite database, optionally filtered by department or status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "department": {"type": "string", "enum": ["ENG", "GROWTH", "PROD", "FIN", "LEGAL", "IT"]},
                "status": {"type": "string", "enum": ["BACKLOG", "TODO", "IN_PROGRESS", "BOARD_ACTION", "DONE"]},
            },
        },
    },
    {
        "name": "board_add",
        "description": "Create a new task ticket on AgentBoard.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "title": {"type": "string"},
                "department": {"type": "string", "enum": ["ENG", "GROWTH", "PROD", "FIN", "LEGAL", "IT"]},
                "status": {"type": "string", "enum": ["BACKLOG", "TODO", "IN_PROGRESS", "BOARD_ACTION", "DONE"]},
                "priority": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH", "URGENT"]},
                "assignee": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["id", "title", "department"],
        },
    },
    {
        "name": "board_move",
        "description": "Move an existing task to a new Kanban status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "status": {"type": "string", "enum": ["BACKLOG", "TODO", "IN_PROGRESS", "BOARD_ACTION", "DONE"]},
            },
            "required": ["id", "status"],
        },
    },
    {
        "name": "board_flag_board",
        "description": "Flag a task as BOARD_ACTION for sole Board Member approval.",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
    },
]


def call_tool(name: str, args: dict) -> dict:
    agentboard.init_db(seed=True)
    conn = agentboard.get_conn()
    try:
        if name == "board_list":
            q = "SELECT id, department, status, priority, assignee, title FROM tasks WHERE 1=1"
            params = []
            if args.get("department"):
                q += " AND department = ?"
                params.append(args["department"].upper())
            if args.get("status"):
                q += " AND status = ?"
                params.append(args["status"].upper())
            rows = [dict(r) for r in conn.execute(q + " ORDER BY department, id", params).fetchall()]
            return {"content": [{"type": "text", "text": json.dumps(rows, indent=2)}]}

        if name == "board_add":
            tid = args["id"].upper()
            dept = args["department"].upper()
            status = args.get("status", "TODO").upper()
            priority = args.get("priority", "MEDIUM").upper()
            assignee = args.get("assignee", f"{dept} Agent")
            desc = args.get("description", "")
            ts = agentboard.now_iso()
            ba = 1 if status == "BOARD_ACTION" else 0
            with conn:
                conn.execute(
                    "INSERT INTO tasks (id, title, description, department, status, priority, assignee, board_action, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (tid, args["title"], desc, dept, status, priority, assignee, ba, ts, ts),
                )
                agentboard.log_activity(conn, tid, "MCP", "CREATE_TASK", args["title"])
            return {"content": [{"type": "text", "text": f"Created {tid} in {dept}/{status}"}]}

        if name == "board_move":
            tid = args["id"].upper()
            status = args["status"].upper()
            ba = 1 if status == "BOARD_ACTION" else 0
            with conn:
                cur = conn.execute(
                    "UPDATE tasks SET status=?, board_action=?, updated_at=? WHERE id=?",
                    (status, ba, agentboard.now_iso(), tid),
                )
                if cur.rowcount == 0:
                    return {"isError": True, "content": [{"type": "text", "text": f"Task {tid} not found"}]}
                agentboard.log_activity(conn, tid, "MCP", "MOVE_TASK", status)
            return {"content": [{"type": "text", "text": f"Moved {tid} -> {status}"}]}

        if name == "board_flag_board":
            tid = args["id"].upper()
            with conn:
                cur = conn.execute(
                    "UPDATE tasks SET status='BOARD_ACTION', board_action=1, updated_at=? WHERE id=?",
                    (agentboard.now_iso(), tid),
                )
                if cur.rowcount == 0:
                    return {"isError": True, "content": [{"type": "text", "text": f"Task {tid} not found"}]}
                agentboard.log_activity(conn, tid, "MCP", "FLAG_BOARD_ACTION", "")
            return {"content": [{"type": "text", "text": f"Flagged {tid} for BOARD_ACTION"}]}

        return {"isError": True, "content": [{"type": "text", "text": f"Unknown tool: {name}"}]}
    finally:
        conn.close()


def main() -> None:
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        req = json.loads(line)
        req_id = req.get("id")
        method = req.get("method")
        if method == "initialize":
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "agentboard-mcp", "version": "1.0.0"},
                },
            }
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            resp = {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}
        elif method == "tools/call":
            params = req.get("params", {})
            resp = {"jsonrpc": "2.0", "id": req_id, "result": call_tool(params.get("name", ""), params.get("arguments", {}))}
        else:
            resp = {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
