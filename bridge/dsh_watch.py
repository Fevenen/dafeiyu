"""dsh_watch.py — 盯 DSH 的会话文件，把它新吐出来的回复让桌宠念出来。

原理：DSH 把每轮对话写在
    C:\\Users\\<你>\\.dsh\\storages\\session_projcache\\sessions\\session-*.json
其中 record.rows.turnOutline.val.turns[] 里每条有 prompt 和 response。
这个脚本轮询该文件，发现新的 response → 切句 → 调桌宠 /api/say。

用法：
    python dsh_watch.py --list                     列出所有会话（挑一个）
    python dsh_watch.py --session <id>             盯指定会话
    python dsh_watch.py --latest                   盯最新的会话
    python dsh_watch.py --session <id> --dry       只看不念（调试）
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PET_ROOT = os.path.dirname(HERE)
if PET_ROOT not in sys.path:
    sys.path.insert(0, PET_ROOT)  # 让 `import bridge.x` 能工作


def _read_cfg() -> dict:
    try:
        with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


_CFG = _read_cfg()

STATE = os.path.join(HERE, "state", "dsh_watch.json")
PET_API = str(_CFG.get("pet_api") or os.environ.get("PET_API") or "http://127.0.0.1:12393").rstrip("/")
SESSIONS = _CFG.get("dsh_sessions") or os.path.join(
    os.path.expanduser("~"), ".dsh", "storages", "session_projcache", "sessions"
)


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def session_turns(path):
    """读一个会话文件，返回 (标题, 工作目录, turns 列表)。"""
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        rows = (d.get("record") or {}).get("rows") or {}
        title = ((rows.get("title") or {}).get("val")) or ""
        cwd = ((rows.get("workingDirectory") or {}).get("val")) or ""
        turns = (((rows.get("turnOutline") or {}).get("val")) or {}).get("turns") or []
        return title, cwd, turns
    except Exception:
        return "", "", []


def list_sessions():
    files = [
        os.path.join(SESSIONS, f)
        for f in os.listdir(SESSIONS)
        if f.endswith(".json")
    ]
    files.sort(key=os.path.getmtime, reverse=True)
    for f in files:
        title, cwd, turns = session_turns(f)
        print(
            "%s\n    标题: %s\n    目录: %s\n    轮数: %d"
            % (os.path.basename(f), title, cwd, len(turns)),
            flush=True,
        )


def clean(text):
    """把 Markdown / 表情符号去掉，只留能念的文字。"""
    t = text or ""
    t = re.sub(r"```.*?```", " ", t, flags=re.S)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"^\s{0,3}#{1,6}\s*", "", t, flags=re.M)
    t = re.sub(r"#{1,6}\s*", "", t)
    t = re.sub(r"[*_~>]+", "", t)
    t = re.sub(r"\[[^\]]{1,12}\]", "", t)
    t = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]", "", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{2,}", "\n", t)
    return t.strip()


def split_sentences(text, limit=45):
    parts = re.split(r"(?<=[。！？!?；;\n])", text)
    out, buf = [], ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(buf) + len(p) <= limit:
            buf += p
        else:
            if buf:
                out.append(buf)
            buf = p
    if buf:
        out.append(buf)
    return [x for x in out if re.search(r"[\u4e00-\u9fffA-Za-z0-9]", x)]


def say(text):
    body = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        PET_API + "/api/say", data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


SEND_CLAIM = re.compile(r"(已发送|已经发送|发出去了|发过去了|已经发出去|消息已发|已经发了|发好了|已送达)")
TOOL_LOG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "tool_calls.jsonl"
)


def _recent_send_call(seconds: float = 240.0) -> bool:
    """最近几分钟内有没有真的调用过发送/确认工具。"""
    try:
        now = time.time()
        with open(TOOL_LOG, encoding="utf-8") as f:
            lines = f.readlines()[-40:]
        for line in lines:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("tool") not in ("send_qq_message", "confirm_send"):
                continue
            ts = time.mktime(time.strptime(rec.get("ts", ""), "%Y-%m-%d %H:%M:%S"))
            if now - ts <= seconds:
                return True
    except Exception:
        pass
    return False


def fake_success_guard(text: str) -> str:
    """她说"已经发出去了"，但工具日志里没有记录 → 换成纠正的话。"""
    if SEND_CLAIM.search(text) and not _recent_send_call():
        print("   [拦截假成功] 她说发了，但工具没调用：%s" % text[:40], flush=True)
        return "（突然停住）等等……本鲸刚才其实没发出去，工具根本没调起来。主人你再说一次？"
    return text


def _router(prompt: str) -> str:
    """明确指令（发消息 / 确认 / 取消 / 提醒 / 查联系人）直接用代码执行。

    返回要说的话；不归它管就返回空字符串，交给模型正常回复。
    """
    p = (prompt or "").strip()
    if not p:
        return ""
    try:
        from bridge import fastpath, safety, tools
    except Exception as e:
        print("   [路由] 导入 bridge 失败：%s" % e, flush=True)
        return ""
    try:
        if safety.get_pending():
            if safety.is_confirm(p):
                return tools.confirm_send()
            if safety.is_cancel(p):
                return tools.cancel_send()
        handled, reply = fastpath.try_handle(p)
        if handled and reply:
            return reply
    except Exception as e:
        print("   [路由] 执行失败：%s" % e, flush=True)
    return ""


def main():
    # 输出被重定向到文件时，默认编码可能是 GBK，打印中文会崩
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--session", default="")
    ap.add_argument("--latest", action="store_true")
    ap.add_argument("--dir", default="", help="盯这个工作区里最新的会话（换会话时自动跟随）")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    if args.list:
        list_sessions()
        return

    if not os.path.isdir(SESSIONS):
        print("找不到 DSH 会话目录：%s" % SESSIONS, flush=True)
        return

    def newest_for_dir(folder: str):
        cands = []
        for f in os.listdir(SESSIONS):
            if not f.endswith(".json"):
                continue
            p = os.path.join(SESSIONS, f)
            _, cwd, _ = session_turns(p)
            if os.path.normcase(os.path.normpath(cwd or "")) == os.path.normcase(
                os.path.normpath(folder)
            ):
                cands.append(p)
        return max(cands, key=os.path.getmtime) if cands else None

    if args.dir:
        path = newest_for_dir(args.dir) or ""
        if not path:
            print("「%s」下还没有会话文件，等一会儿…" % args.dir, flush=True)
    elif args.session:
        target = args.session
        if not target.startswith("session-"):
            target = "session-%s.json" % target
        if not target.endswith(".json"):
            target += ".json"
        path = os.path.join(SESSIONS, target)
    else:
        files = [
            os.path.join(SESSIONS, f)
            for f in os.listdir(SESSIONS)
            if f.endswith(".json")
        ]
        if not files:
            print("没有会话文件", flush=True)
            return
        path = max(files, key=os.path.getmtime)

    print("盯会话：%s" % (os.path.basename(path) if path else "（等新会话）"), flush=True)
    state = load_json(STATE, {})
    last_turn = state.get(path, {}).get("turn", 0)
    spoken = state.get(path, {}).get("spoken", "")
    last_resp = ""
    stable = 0
    handled_turn = 0
    last_check = 0.0
    ENDS = "。！？!?；;\n"

    def emit(chunk: str, turn_no: int) -> None:
        pieces = split_sentences(clean(chunk))
        if not pieces:
            return
        print("第 %d 轮：念 %d 句" % (turn_no, len(pieces)), flush=True)
        if args.dry:
            for p in pieces:
                print("   [dry]", p, flush=True)
            return
        for p in pieces:
            p = fake_success_guard(p)
            try:
                say(p)
            except Exception as e:
                print("   念失败：%s" % str(e)[:80], flush=True)
            time.sleep(0.15)

    while True:
        # --dir 模式：每 3 秒看看有没有新会话，有就切过去
        if args.dir and time.time() - last_check > 3:
            last_check = time.time()
            new_path = newest_for_dir(args.dir) or ""
            if new_path and new_path != path:
                path = new_path
                last_turn = state.get(path, {}).get("turn", 0)
                spoken = state.get(path, {}).get("spoken", "")
                last_resp, stable, handled_turn = "", 0, 0
                print("切换到新会话：%s" % os.path.basename(path), flush=True)
        if not path:
            time.sleep(1)
            continue

        _, _, turns = session_turns(path)
        if turns:
            cur = turns[-1]
            resp = (cur.get("response") or "").strip()
            turn_no = cur.get("turn") or 0

            if turn_no != last_turn:
                last_turn = turn_no
                spoken = ""
                stable = 0
                # 明确的指令（发消息/确认/提醒）由代码直接做，不信模型的嘴
                router_reply = _router(cur.get("prompt") or "")
                if router_reply:
                    print("[路由] 代码处理：%s" % router_reply.replace("\n", " ")[:50], flush=True)
                    emit(router_reply, turn_no)
                    handled_turn = turn_no

            # 回复被改写（不是继续变长）→ 重新念
            if resp and not resp.startswith(spoken):
                spoken = ""

            new_text = resp[len(spoken):]
            if new_text:
                # 只念"已经结束"的句子，剩下半句等下一次
                cut = max(new_text.rfind(c) for c in ENDS)
                if cut >= 0:
                    chunk = new_text[: cut + 1]
                    if handled_turn != turn_no:
                        emit(chunk, turn_no)
                    spoken += chunk
                    state[path] = {"turn": last_turn, "spoken": spoken}
                    save_json(STATE, state)

            # 回复不再变化了 → 把最后半句补上
            if resp == last_resp:
                stable += 1
            else:
                stable = 0
            if resp and stable >= 2 and resp != spoken:
                tail = resp[len(spoken):]
                if tail.strip() and handled_turn != turn_no:
                    emit(tail, turn_no)
                spoken = resp
                state[path] = {"turn": last_turn, "spoken": spoken}
                save_json(STATE, state)

            last_resp = resp

        time.sleep(0.3)


if __name__ == "__main__":
    # 挂了就自己重启，别一声不响地死掉
    while True:
        try:
            main()
            break
        except KeyboardInterrupt:
            break
        except SystemExit:
            break
        except Exception as e:
            print("监听器异常，3 秒后重启：%s: %s" % (type(e).__name__, e), flush=True)
            time.sleep(3)
