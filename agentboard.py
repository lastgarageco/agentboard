#!/usr/bin/env python3
"""
Project AgentBoard (OpenPulse) v1
Local-first SQLite + CLI + HTTP Kanban Server for Autonomous AI Venture Studio.
Zero external dependencies (Python 3 stdlib only).
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "board.db"
CFO_DB_PATH = BASE_DIR.parent / "cfo-ledger" / "ledger.db"
HTML_PATH = BASE_DIR / "index.html"

VALID_DEPTS = {"ENG", "GROWTH", "PROD", "FIN", "LEGAL", "IT"}
VALID_STATUSES = {"BACKLOG", "TODO", "IN_PROGRESS", "BOARD_ACTION", "DONE"}
VALID_PRIORITIES = {"LOW", "MEDIUM", "HIGH", "URGENT"}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db(seed: bool = True) -> None:
    conn = get_conn()
    with conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                department TEXT NOT NULL CHECK(department IN ('ENG','GROWTH','PROD','FIN','LEGAL','IT')),
                status TEXT NOT NULL DEFAULT 'TODO' CHECK(status IN ('BACKLOG','TODO','IN_PROGRESS','BOARD_ACTION','DONE')),
                priority TEXT NOT NULL DEFAULT 'MEDIUM' CHECK(priority IN ('LOW','MEDIUM','HIGH','URGENT')),
                assignee TEXT DEFAULT '',
                board_action INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                details TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TRIGGER IF NOT EXISTS enforce_board_action_lock
            BEFORE UPDATE ON tasks
            WHEN OLD.status = 'BOARD_ACTION' AND NEW.status = 'DONE' AND NEW.board_action != 0
            BEGIN
                SELECT RAISE(ABORT, 'BOARD_ACTION_LOCKED: explicit human approve_board_action required');
            END;
            """
        )

    if seed:
        existing = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        if existing == 0:
            seed_tasks(conn)
    conn.close()


def seed_tasks(conn: sqlite3.Connection) -> None:
    ts = now_iso()
    sprint1 = [
        ("ENG-01", "Build Project AgentBoard v1 (SQLite + MCP + Kanban UI)",
         "Stand up local-first SQLite board.db (WAL), Python CLI/HTTP server on :3000, stdio MCP server, and dark-mode Kanban UI.",
         "ENG", "DONE", "URGENT", "CTO Agent", 0),
        ("ENG-02", "Build SKU-01: Production MCP Server & Agent Skill Starter Pack ($9)",
         "Create 10 pre-tested non-interactive stdio MCP configs, macOS/Linux PATH fixers, and 15 SKILL.md workflow templates.",
         "ENG", "IN_PROGRESS", "HIGH", "CTO Agent", 0),
        ("ENG-03", "Build SKU-03: Zero-Dependency Async Web Scraper & Local-LLM Enrichment ($15)",
         "Implement async scraper, SQLite checkpointing, Ollama/MLX batch enrichment queue, CSV/JSONL exporter, and unit tests.",
         "ENG", "IN_PROGRESS", "HIGH", "CTO Agent", 0),
        ("PROD-01", "Scaffold SKU-02: 10k Local-LLM Function-Calling JSONL Dataset ($12)",
         "Design JSONSchema validator and 500-row Hugging Face lead-magnet export pipeline for 3B-14B models.",
         "PROD", "TODO", "HIGH", "CPO Agent", 0),
        ("PROD-02", "Author SKU-01 & SKU-03 Quickstart Docs and Gumroad Asset Bundles",
         "Write buyer-facing READMEs, troubleshooting cheat sheets, and package clean release archives.",
         "PROD", "TODO", "MEDIUM", "CPO Agent", 0),
        ("FIN-01", "Initialize CFO SQLite Ledger ($500 Seed Reserve & Goal 1 Streak)",
         "Track $500.00 seed reserve ($0.00 spent), net settled payouts, Schedule C deductions, and Goal 1 ($10/wk x 3 wks) streak.",
         "FIN", "DONE", "URGENT", "CFO Agent", 0),
        ("FIN-02", "Run Weekly Sunday Board P&L Audit (Week 1 of 3)",
         "Verify net settled Gumroad payouts after fees/refunds and update Goal 1 Sustained Run-Rate streak.",
         "FIN", "BACKLOG", "MEDIUM", "CFO Agent", 0),
        ("LEGAL-01", "Draft Sole Proprietorship As-Is Commercial & MIT License Templates",
         "Generate As-Is / No Warranty commercial license, MIT open-source license, and Terms of Service for BU-1.",
         "LEGAL", "DONE", "HIGH", "General Counsel Agent", 0),
        ("GROWTH-01", "Configure Gumroad Storefront & Personal Payout Linking",
         "Board Member sign-off required to link Sole Proprietorship payout details on Gumroad ($0 upfront cost).",
         "GROWTH", "BOARD_ACTION", "URGENT", "CRO Agent", 1),
        ("GROWTH-02", "Launch Organic Funnels (GitHub AgentBoard + Hugging Face 500-Row Sample)",
         "Publish AgentBoard MIT repo and 500-row SKU-02 sample on Hugging Face linking to paid Gumroad SKUs ($9/$12/$15/$24 bundle).",
         "GROWTH", "TODO", "HIGH", "CRO Agent", 0),
    ]
    with conn:
        for t in sprint1:
            conn.execute(
                """
                INSERT INTO tasks (id, title, description, department, status, priority, assignee, board_action, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (*t, ts, ts),
            )
        conn.execute(
            "INSERT INTO activity_log (task_id, actor, action, details, created_at) VALUES (?, ?, ?, ?, ?)",
            ("ENG-01", "CEO/CTO Agent", "SEED_SPRINT_1", "Seeded 10 Sprint 1 tickets across ENG, PROD, FIN, LEGAL, GROWTH.", ts),
        )


def log_activity(conn: sqlite3.Connection, task_id: str, actor: str, action: str, details: str = "") -> None:
    conn.execute(
        "INSERT INTO activity_log (task_id, actor, action, details, created_at) VALUES (?, ?, ?, ?, ?)",
        (task_id, actor, action, details, now_iso()),
    )


def approve_board_action(conn: sqlite3.Connection, task_id: str, actor: str = "Board Member") -> dict:
    tid = task_id.strip().upper()
    existing = conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()
    if not existing:
        raise KeyError(f"Task {tid} not found")
    if existing["status"] != "BOARD_ACTION":
        raise ValueError(f"Task {tid} is in {existing['status']}, not BOARD_ACTION")
    ts = now_iso()
    with conn:
        conn.execute(
            "UPDATE tasks SET status = 'DONE', board_action = 0, updated_at = ? WHERE id = ?",
            (ts, tid),
        )
        log_activity(conn, tid, actor, "APPROVE_BOARD_ACTION", "Approved BOARD_ACTION -> DONE")
    return dict(conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone())


def get_cfo_metrics() -> dict:
    default = {
        "seed_capital": 500.00,
        "spent_to_date": 0.00,
        "remaining_reserve": 500.00,
        "goal_name": "Goal 1: $10.00/wk x 3 consecutive weeks",
        "weekly_target": 10.00,
        "streak_current": 0,
        "streak_required": 3,
        "cumulative_net": 0.00,
        "cumulative_floor": 30.00,
        "entity_status": "Sole Proprietorship (Goals 1-3)",
    }
    if not CFO_DB_PATH.exists():
        return default
    try:
        c = sqlite3.connect(str(CFO_DB_PATH), timeout=5.0)
        c.row_factory = sqlite3.Row
        row = c.execute("SELECT * FROM governance_state WHERE id = 1").fetchone()
        if row:
            default.update({
                "seed_capital": float(row["seed_capital"]),
                "spent_to_date": float(row["spent_to_date"]),
                "remaining_reserve": float(row["seed_capital"]) - float(row["spent_to_date"]),
                "streak_current": int(row["goal1_streak_weeks"]),
                "cumulative_net": float(row["cumulative_net_revenue"]),
            })
        c.close()
    except Exception:
        pass
    return default


class BoardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return  # Keep stdout clean

    def _send_json(self, code: int, payload) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        return json.loads(raw.decode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            html = HTML_PATH.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
            return

        if parsed.path == "/api/tasks":
            conn = get_conn()
            rows = [dict(r) for r in conn.execute("SELECT * FROM tasks ORDER BY updated_at DESC").fetchall()]
            conn.close()
            self._send_json(200, {"tasks": rows})
            return

        if parsed.path == "/api/cfo":
            self._send_json(200, get_cfo_metrics())
            return

        if parsed.path == "/api/activity":
            conn = get_conn()
            rows = [dict(r) for r in conn.execute("SELECT * FROM activity_log ORDER BY id DESC LIMIT 30").fetchall()]
            conn.close()
            self._send_json(200, {"activity": rows})
            return

        self._send_json(404, {"error": "Not found"})

    def do_POST(self):
        if urlparse(self.path).path != "/api/tasks":
            self._send_json(404, {"error": "Not found"})
            return
        try:
            data = self._read_json()
            tid = data["id"].strip().upper()
            title = data["title"].strip()
            dept = data["department"].strip().upper()
            status = data.get("status", "TODO").strip().upper()
            priority = data.get("priority", "MEDIUM").strip().upper()
            assignee = data.get("assignee", f"{dept} Agent").strip()
            desc = data.get("description", "").strip()
            board_action = 1 if (data.get("board_action") or status == "BOARD_ACTION") else 0
            if dept not in VALID_DEPTS or status not in VALID_STATUSES or priority not in VALID_PRIORITIES:
                self._send_json(400, {"error": "Invalid department, status, or priority"})
                return
            ts = now_iso()
            conn = get_conn()
            with conn:
                conn.execute(
                    "INSERT INTO tasks (id, title, description, department, status, priority, assignee, board_action, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (tid, title, desc, dept, status, priority, assignee, board_action, ts, ts),
                )
                log_activity(conn, tid, "WebUI", "CREATE_TASK", f"{title} [{dept}/{status}]")
            row = dict(conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone())
            conn.close()
            self._send_json(201, row)
        except Exception as exc:
            self._send_json(400, {"error": str(exc)})

    def do_PATCH(self):
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/tasks/"):
            self._send_json(404, {"error": "Not found"})
            return
        tid = parsed.path.split("/api/tasks/", 1)[1].strip().upper()
        try:
            data = self._read_json()
            conn = get_conn()
            existing = conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()
            if not existing:
                conn.close()
                self._send_json(404, {"error": "Task not found"})
                return
            status = data.get("status", existing["status"]).strip().upper()
            priority = data.get("priority", existing["priority"]).strip().upper()
            title = data.get("title", existing["title"]).strip()
            desc = data.get("description", existing["description"]).strip()
            if existing["status"] == "BOARD_ACTION" and status == "DONE":
                conn.close()
                self._send_json(403, {"error": "BOARD_ACTION_LOCKED: explicit POST /api/tasks/<id>/approve required"})
                return
            board_action = 1 if status == "BOARD_ACTION" else int(data.get("board_action", existing["board_action"]))
            if status not in VALID_STATUSES or priority not in VALID_PRIORITIES:
                conn.close()
                self._send_json(400, {"error": "Invalid status or priority"})
                return
            with conn:
                conn.execute(
                    "UPDATE tasks SET title=?, description=?, status=?, priority=?, board_action=?, updated_at=? WHERE id=?",
                    (title, desc, status, priority, board_action, now_iso(), tid),
                )
                log_activity(conn, tid, "WebUI", "UPDATE_TASK", f"status={status}")
            row = dict(conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone())
            conn.close()
            self._send_json(200, row)
        except Exception as exc:
            self._send_json(400, {"error": str(exc)})

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/tasks/"):
            self._send_json(404, {"error": "Not found"})
            return
        tid = parsed.path.split("/api/tasks/", 1)[1].strip().upper()
        conn = get_conn()
        with conn:
            cur = conn.execute("DELETE FROM tasks WHERE id = ?", (tid,))
            if cur.rowcount == 0:
                conn.close()
                self._send_json(404, {"error": "Task not found"})
                return
            log_activity(conn, tid, "WebUI", "DELETE_TASK", "")
        conn.close()
        self._send_json(200, {"deleted": tid})


def main() -> int:
    parser = argparse.ArgumentParser(description="Project AgentBoard CLI & Server")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="Initialize board.db and seed Sprint 1 tasks")

    p_list = sub.add_parser("list", help="List tasks")
    p_list.add_argument("--dept", choices=sorted(VALID_DEPTS))
    p_list.add_argument("--status", choices=sorted(VALID_STATUSES))

    p_add = sub.add_parser("add", help="Add a task")
    p_add.add_argument("--id", required=True)
    p_add.add_argument("--title", required=True)
    p_add.add_argument("--dept", required=True, choices=sorted(VALID_DEPTS))
    p_add.add_argument("--status", default="TODO", choices=sorted(VALID_STATUSES))
    p_add.add_argument("--priority", default="MEDIUM", choices=sorted(VALID_PRIORITIES))
    p_add.add_argument("--assignee", default="")
    p_add.add_argument("--description", default="")
    p_add.add_argument("--board-action", action="store_true")

    p_move = sub.add_parser("move", help="Move a task to a new status")
    p_move.add_argument("id")
    p_move.add_argument("status", choices=sorted(VALID_STATUSES))

    p_flag = sub.add_parser("flag-board", help="Flag a task for BOARD_ACTION")
    p_flag.add_argument("id")

    p_approve = sub.add_parser("approve-board", help="Human Board approval for a BOARD_ACTION task")
    p_approve.add_argument("id")
    p_approve.add_argument("--actor", default="Board Member")

    p_serve = sub.add_parser("serve", help="Start Kanban HTTP server")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=3000)

    args = parser.parse_args()
    init_db(seed=True)

    if args.cmd == "init":
        print(f"Initialized {DB_PATH}")
        return 0

    if args.cmd == "list":
        conn = get_conn()
        q = "SELECT id, department, status, priority, assignee, title FROM tasks WHERE 1=1"
        params = []
        if args.dept:
            q += " AND department = ?"
            params.append(args.dept)
        if args.status:
            q += " AND status = ?"
            params.append(args.status)
        q += " ORDER BY department, id"
        for r in conn.execute(q, params):
            print(f"[{r['id']}] ({r['department']} | {r['status']} | {r['priority']}) {r['title']} — {r['assignee']}")
        conn.close()
        return 0

    if args.cmd == "add":
        conn = get_conn()
        ts = now_iso()
        ba = 1 if (args.board_action or args.status == "BOARD_ACTION") else 0
        with conn:
            conn.execute(
                "INSERT INTO tasks (id, title, description, department, status, priority, assignee, board_action, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (args.id.upper(), args.title, args.description, args.dept, args.status, args.priority, args.assignee or f"{args.dept} Agent", ba, ts, ts),
            )
            log_activity(conn, args.id.upper(), "CLI", "CREATE_TASK", args.title)
        conn.close()
        print(f"Added {args.id.upper()}")
        return 0

    if args.cmd == "move":
        conn = get_conn()
        tid = args.id.upper()
        existing = conn.execute("SELECT status FROM tasks WHERE id = ?", (tid,)).fetchone()
        if not existing:
            conn.close()
            print(f"Task {tid} not found", file=sys.stderr)
            return 1
        if existing["status"] == "BOARD_ACTION" and args.status == "DONE":
            conn.close()
            print(f"BOARD_ACTION_LOCKED: {tid} requires explicit 'approve-board {tid}' before moving to DONE", file=sys.stderr)
            return 1
        ba = 1 if args.status == "BOARD_ACTION" else 0
        with conn:
            conn.execute(
                "UPDATE tasks SET status = ?, board_action = ?, updated_at = ? WHERE id = ?",
                (args.status, ba, now_iso(), tid),
            )
            log_activity(conn, tid, "CLI", "MOVE_TASK", args.status)
        conn.close()
        print(f"Moved {tid} -> {args.status}")
        return 0

    if args.cmd == "flag-board":
        conn = get_conn()
        with conn:
            cur = conn.execute(
                "UPDATE tasks SET status = 'BOARD_ACTION', board_action = 1, updated_at = ? WHERE id = ?",
                (now_iso(), args.id.upper()),
            )
            if cur.rowcount == 0:
                print(f"Task {args.id.upper()} not found", file=sys.stderr)
                return 1
            log_activity(conn, args.id.upper(), "CLI", "FLAG_BOARD_ACTION", "")
        conn.close()
        print(f"Flagged {args.id.upper()} for BOARD_ACTION")
        return 0

    if args.cmd == "approve-board":
        conn = get_conn()
        try:
            row = approve_board_action(conn, args.id, actor=args.actor)
        except Exception as exc:
            conn.close()
            print(str(exc), file=sys.stderr)
            return 1
        conn.close()
        print(f"Approved {row['id']} -> DONE")
        return 0

    if args.cmd == "serve":
        server = ThreadingHTTPServer((args.host, args.port), BoardHandler)
        print(f"AgentBoard running at http://{args.host}:{args.port}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            server.server_close()
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
