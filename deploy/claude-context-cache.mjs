#!/usr/bin/env node
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

let raw = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => { raw += chunk; });
process.stdin.on("end", () => {
  let input;
  try {
    input = JSON.parse(raw);
  } catch {
    process.exitCode = 1;
    return;
  }
  const percent = input.context_window?.used_percentage;
  const size = input.context_window?.context_window_size;
  if (
    typeof input.session_id === "string"
    && typeof percent === "number"
    && typeof size === "number"
  ) {
    const root = path.join(os.homedir(), ".claude", "context-window-cache");
    fs.mkdirSync(root, { recursive: true, mode: 0o700 });
    const target = path.join(root, `${input.session_id}.json`);
    const temporary = `${target}.${process.pid}.part`;
    fs.writeFileSync(temporary, JSON.stringify({
      updated_at: new Date().toISOString(),
      used_percent: percent,
      context_window_size: size,
      tmux_pane: process.env.TMUX_PANE || null,
    }), { mode: 0o600 });
    fs.renameSync(temporary, target);
    process.stdout.write(`ctx: ${Math.round(percent)}%`);
  }
});
