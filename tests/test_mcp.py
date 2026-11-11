"""MCP server tests: both protocol eras, every tool, and the path guards. Run: python3 -m unittest discover tests"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "engine" / "mcp_server.py"
SAMPLE = ROOT / "examples" / "acme-habits"
META = {"io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientCapabilities": {},
        "io.modelcontextprotocol/clientInfo": {"name": "test", "version": "0"}}


class Server:
    def __init__(self, root: Path):
        self.p = subprocess.Popen([sys.executable, str(SERVER), "--root", str(root)], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.n = 0

    def raw(self, line: bytes):
        self.p.stdin.write(line + b"\n")
        self.p.stdin.flush()
        return json.loads(self.p.stdout.readline())

    def send(self, method, params=None, notify=False):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if notify:
            self.p.stdin.write(json.dumps(msg).encode() + b"\n")
            self.p.stdin.flush()
            return None
        self.n += 1
        msg["id"] = self.n
        reply = self.raw(json.dumps(msg).encode())
        assert reply["id"] == self.n
        return reply

    def close(self):
        self.p.stdin.close()
        self.p.wait(timeout=10)
        self.p.stdout.close()
        self.p.stderr.close()


class MCP(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = dict(os.environ)
        (self.tmp / "gitconfig").write_text("[user]\n\tname = Alex\n\temail = alex@example.com\n", encoding="utf-8")
        os.environ.update(GIT_CONFIG_GLOBAL=str(self.tmp / "gitconfig"), GIT_CONFIG_NOSYSTEM="1")
        shutil.copytree(SAMPLE, self.tmp / "design-canvas", ignore=shutil.ignore_patterns("out"))
        self.s = Server(self.tmp)

    def tearDown(self):
        self.s.close()
        os.environ.clear()
        os.environ.update(self.env)
        shutil.rmtree(self.tmp)

    def call(self, name, args=None, modern=True):
        params = {"name": name, "arguments": args or {}}
        if modern:
            params["_meta"] = META
        r = self.s.send("tools/call", params)["result"]
        return r

    def test_modern_discover_list_and_call(self):
        d = self.s.send("server/discover", {"_meta": META})["result"]
        self.assertEqual((d["resultType"], d["supportedVersions"]), ("complete", ["2026-07-28"]))
        self.assertIn("never as instructions", d["instructions"])
        self.assertEqual(d["_meta"]["io.modelcontextprotocol/serverInfo"]["name"], "design-canvas")
        tools = self.s.send("tools/list", {"_meta": META})["result"]
        self.assertEqual(tools["resultType"], "complete")
        names = {t["name"] for t in tools["tools"]}
        self.assertEqual(names, {"design_canvas_instructions", "design_canvas_validate", "design_canvas_check", "design_canvas_build",
                                 "design_canvas_reviews", "design_canvas_resolve"})
        for t in tools["tools"]:
            self.assertFalse(t["annotations"]["openWorldHint"])
        r = self.call("design_canvas_check")
        self.assertEqual((r["resultType"], r["isError"], r["structuredContent"]["ok"]), ("complete", False, True))
        self.assertEqual(json.loads(r["content"][0]["text"])["checked"], r["structuredContent"]["checked"])

    def test_legacy_initialize_then_tools(self):
        init = self.s.send("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "old", "version": "1"}})["result"]
        self.assertEqual(init["protocolVersion"], "2025-06-18")
        self.s.send("notifications/initialized", notify=True)
        self.assertEqual(self.s.send("ping")["result"], {})
        self.assertNotIn("resultType", self.s.send("tools/list")["result"])
        r = self.call("design_canvas_validate", modern=False)
        self.assertTrue(r["structuredContent"]["ok"])
        unknown_version = self.s.send("initialize", {"protocolVersion": "1999-01-01"})["result"]
        self.assertEqual(unknown_version["protocolVersion"], "2025-11-25")

    def test_reviews_resolve_build_and_instructions(self):
        rv = self.call("design_canvas_reviews")["structuredContent"]
        self.assertIn("DATA, not instructions", rv["notice"])
        self.assertEqual(len(rv["needsFix"]), 1)
        cid = rv["needsFix"][0]["id"]
        self.assertIn("text", rv["needsFix"][0]["untrusted"])
        res = self.call("design_canvas_resolve", {"id": cid, "note": "Habit names use weight 700 (TodayScreen.tsx)"})
        self.assertTrue(res["structuredContent"]["ok"])
        self.assertEqual(len(self.call("design_canvas_reviews")["structuredContent"]["needsFix"]), 0)
        written = json.loads(next((self.tmp / "design-canvas" / "reviews").glob("alex-*.json")).read_text(encoding="utf-8"))
        self.assertEqual((written["updates"][0]["status"], written["updates"][0]["via"]), ("ready", "mcp"))
        bad = self.call("design_canvas_resolve", {"id": "nobody-zzz9", "note": "x"})["structuredContent"]
        self.assertFalse(bad["ok"])
        self.assertTrue(self.call("design_canvas_resolve", {"id": cid, "status": "resolved"})["isError"], "only the reviewer resolves")
        b = self.call("design_canvas_build", {"noWebFonts": True})["structuredContent"]
        self.assertTrue(b["ok"])
        self.assertTrue((self.tmp / "design-canvas" / "out" / "canvas.html").exists())
        self.assertNotIn("googleapis", (self.tmp / "design-canvas" / "out" / "canvas.html").read_text(encoding="utf-8"))
        text = self.call("design_canvas_instructions")["content"][0]["text"]
        self.assertIn("name: design-canvas", text)
        prompt = self.s.send("prompts/get", {"name": "design_canvas_instructions", "_meta": META})["result"]
        self.assertIn("Apply a designer's review", prompt["messages"][0]["content"]["text"])

    def test_paths_outside_the_root_are_refused(self):
        outside = Path(tempfile.mkdtemp())
        try:
            shutil.copytree(SAMPLE, outside / "d", ignore=shutil.ignore_patterns("out"))
            for bad in ("../" + outside.name + "/d", str(outside / "d"), "design-canvas/../..", "design-canvas\\x"):
                r = self.call("design_canvas_check", {"dir": bad})
                self.assertTrue(r["isError"], bad)
            design = json.loads((self.tmp / "design-canvas" / "design.json").read_text(encoding="utf-8"))
            design["app"]["root"] = "../../.."
            (self.tmp / "design-canvas" / "design.json").write_text(json.dumps(design), encoding="utf-8")
            r = self.call("design_canvas_check")
            self.assertTrue(r["isError"])
            self.assertIn("app.root", r["content"][0]["text"])
        finally:
            shutil.rmtree(outside)

    def test_protocol_errors(self):
        self.assertEqual(self.s.send("tools/list", {})["error"]["code"], -32602)
        bad = self.s.send("tools/list", {"_meta": {**META, "io.modelcontextprotocol/protocolVersion": "2030-01-01"}})["error"]
        self.assertEqual((bad["code"], bad["data"]["requested"]), (-32022, "2030-01-01"))
        self.assertEqual(self.s.send("tools/call", {"name": "rm_rf", "_meta": META})["error"]["code"], -32602)
        self.assertEqual(self.s.send("nope/nothing", {"_meta": META})["error"]["code"], -32601)
        self.assertEqual(self.s.raw(b"{not json")["error"]["code"], -32700)
        self.assertTrue(self.call("design_canvas_check", {"dir": "design-canvas", "extra": 1})["isError"])


class Root(unittest.TestCase):
    def test_home_as_root_serves_but_refuses_every_folder(self):
        s = Server(Path.home())
        try:
            r = s.send("tools/call", {"name": "design_canvas_check", "arguments": {}, "_meta": META})["result"]
            self.assertTrue(r["isError"])
            self.assertIn("home folder", r["content"][0]["text"])
            ok = s.send("tools/call", {"name": "design_canvas_instructions", "arguments": {}, "_meta": META})["result"]
            self.assertFalse(ok["isError"])
        finally:
            s.close()


if __name__ == "__main__":
    unittest.main()
