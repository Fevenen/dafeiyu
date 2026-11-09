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


def split_sentences(text, limit=200):
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


PSEUDO_CALL = re.compile(r"（调用\s*[A-Za-z_]+）|（使用.{0,12}工具）|正在调用\s*\w+|（正在调用）")
NEGATIVE_CLAIM = re.compile(r"(没有待确认|没发出去|发不出去|发失败|没有待办|没找到)")


def fake_success_guard(text: str, turn_action: str = "", turn_result: str = "") -> str:
    """双向校验：模型说的和代码做的不一致时，纠正成代码的事实。

    · 说"已发送"但代码没执行 → 纠正
    · 写"（调用 xxx）"但没真调用 → 纠正
    · 代码已执行成功，模型却说"没有/没发" → 纠正成代码结果
    """
    if PSEUDO_CALL.search(text) and not _recent_send_call():
        print("   [拦截伪调用] %s" % text[:40], flush=True)
        return "（停住）等等，本鲸刚才是演给你看的，工具根本没调起来。"

    if SEND_CLAIM.search(text) and not _recent_send_call():
        print("   [拦截假成功] 她说发了，但工具没调用：%s" % text[:40], flush=True)
        return "（突然停住）等等……本鲸刚才其实没发出去，工具根本没调起来。主人你再说一次？"

    if turn_action and turn_result and NEGATIVE_CLAIM.search(text):
        if "已发送" in turn_result or "准备发给" in turn_result:
            print("   [纠正反向] 代码已处理，模型说没做：%s" % text[:40], flush=True)
            return turn_result.replace("\n", " ")

    # 模型照抄"准备发给…确认吗"的模板，但根本没有挂起的东西 → 纠正
    if ("确认吗" in text or "确认发送" in text) and not turn_action:
        try:
            from bridge import safety

            pending = safety.get_pending()
        except Exception:
            pending = None
        if not pending:
            print("   [拦截假挂起] 她说准备好了，但没 pending：%s" % text[:40], flush=True)
            return "（摊手）本鲸刚才其实没真的准备好，你再说一次：发给谁、说什么？"

    return text


def _proxy_alive() -> bool:
    """KVMem 修复代理在跑的话，命令由它直通执行（这里就不重复执行）。"""
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        return s.connect_ex(("127.0.0.1", 18080)) == 0
    except Exception:
        return False
    finally:
        s.close()


def _router(prompt: str):
    """明确指令（发消息 / 确认 / 取消 / 提醒 / 查联系人）直接用代码执行。

    返回 (action, result)。不归它管时返回 ("", "")。
    注意：这里只执行、不发声 —— 发声统一交给模型（避免两边各说一套）。
    如果修复代理在跑，执行权归代理（避免同一条命令执行两次）。
    """
    p = (prompt or "").strip()
    if not p:
        return "", ""
    if _proxy_alive():
        return "", ""
    try:
        from bridge import fastpath, safety, tools
    except Exception as e:
        print("   [路由] 导入 bridge 失败：%s" % e, flush=True)
        return "", ""
    try:
        if safety.get_pending():
            if safety.is_confirm(p):
                reply = tools.confirm_send()
                _log_action(p, "confirm_send", reply)
                return "confirm_send", reply
            if safety.is_cancel(p):
                reply = tools.cancel_send()
                _log_action(p, "cancel_send", reply)
                return "cancel_send", reply
        handled, reply = fastpath.try_handle(p)
        if handled and reply:
            _log_action(p, "fastpath", reply)
            return "fastpath", reply
    except Exception as e:
        print("   [路由] 执行失败：%s" % e, flush=True)
    return "", ""


def _log_action(prompt: str, action: str, result: str) -> None:
    """把代码已经做过的动作记下来，供模型通过 recent_actions 查询。"""
    try:
        path = os.path.join(HERE, "state", "router_log.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        rec = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "prompt": prompt[:120],
            "action": action,
            "result": (result or "")[:200],
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


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
    last_check = 0.0
    ENDS = "。！？!?；;\n"
    turn_action, turn_result = "", ""
    handled_turn = 0
    emitted = set()

    def emit(chunk: str, turn_no: int) -> None:
        piece_key = (turn_no, hash(chunk))
        if piece_key in emitted:
            return
        emitted.add(piece_key)
        pieces = split_sentences(clean(chunk))
        if not pieces:
            return
        # 第一句立刻念（尽早出声），后面按 70 字左右合并（减少调用次数、句间不空档）
        batches = [pieces[0]]
        buf = ""
        for p in pieces[1:]:
            if buf and len(buf) + len(p) > 70:
                batches.append(buf)
                buf = p
            else:
                buf = (buf + p) if buf else p
        if buf:
            batches.append(buf)

        print("第 %d 轮：念 %d 块（%d 句）" % (turn_no, len(batches), len(pieces)), flush=True)
        if args.dry:
            for b in batches:
                print("   [dry]", b, flush=True)
            return
        for b in batches:
            b = fake_success_guard(b, turn_action, turn_result)
            try:
                say(b)
            except Exception as e:
                print("   念失败：%s" % str(e)[:80], flush=True)
            time.sleep(0.05)

    while True:
        # --dir 模式：每 3 秒看看有没有新会话，有就切过去
        if args.dir and time.time() - last_check > 3:
            last_check = time.time()
            new_path = newest_for_dir(args.dir) or ""
            if new_path and new_path != path:
                path = new_path
                last_turn = state.get(path, {}).get("turn", 0)
                spoken = state.get(path, {}).get("spoken", "")
                last_resp, stable = "", 0
                turn_action, turn_result = "", ""
                handled_turn = 0
                emitted.clear()
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
                emitted.clear()
                handled_turn = 0
                # 明确指令由代码执行；执行了就由代码发声（模型那轮的文字不念）
                turn_action, turn_result = _router(cur.get("prompt") or "")
                if turn_action:
                    print("[路由] 已执行：%s -> %s" % (turn_action, turn_result.replace("\n", " ")[:60]), flush=True)
                    emit(turn_result, turn_no)
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
