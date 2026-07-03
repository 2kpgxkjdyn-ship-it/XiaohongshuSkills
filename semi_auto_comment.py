import argparse
import csv
import json
import random
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote


BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config" / "semi_auto_comment.json"
DEFAULT_TEMPLATES_FILE = BASE_DIR / "comment_templates.txt"
DEFAULT_LOG_FILE = BASE_DIR / "comment_log.csv"
DEFAULT_QUEUE_FILE = BASE_DIR / "review_queue.csv"
DEFAULT_STATUS_FILE = BASE_DIR / "run_status.log"
CDP_SCRIPT = BASE_DIR / "scripts" / "cdp_publish.py"


DEFAULT_CONFIG = {
    "templates_file": "comment_templates.txt",
    "log_file": "comment_log.csv",
    "good_title_keywords": [
        "找品", "选品", "求货源", "货源", "品牌方", "渠道", "私域",
        "招商", "代理", "分销", "供货", "合作", "产品", "蓝海",
        "电商", "小红书", "抖音", "快手", "视频号", "找经销商",
        "供应链", "源头工厂", "资源对接", "私域产品",
    ],
    "bad_title_keywords": [
        "招聘", "找工作", "兼职", "避雷", "曝光", "骗子", "求助",
        "闲置", "二手", "租房", "相亲", "旅游", "美甲", "穿搭",
        "减肥打卡", "日常", "vlog", "情感",
    ],
    "required_title_keywords": [],
    "blocked_title_keywords": [],
    "min_score": 0,
    "skip_logged_notes": True,
    "daily_success_limit": 20,
    "queue_file": "review_queue.csv",
    "status_file": "run_status.log",
    "search_filters": {},
}

LOG_FIELDNAMES = [
    "timestamp",
    "keyword",
    "note_url",
    "comment",
    "status",
]

QUEUE_FIELDNAMES = [
    "approve",
    "keyword",
    "note_id",
    "note_url",
    "xsec_token",
    "score",
    "suggested_comment",
    "status",
    "last_error",
    "created_at",
    "published_at",
]


def resolve_path(value, default_path):
    if not value:
        return default_path
    path = Path(value)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def load_config(path=CONFIG_FILE):
    config = dict(DEFAULT_CONFIG)
    if not path.exists():
        return config

    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"配置文件读取失败，将使用默认配置：{path} ({exc})")
        return config

    if not isinstance(loaded, dict):
        print(f"配置文件不是 JSON object，将使用默认配置：{path}")
        return config

    for key, value in loaded.items():
        if key == "search_filters" and isinstance(value, dict):
            merged = dict(config["search_filters"])
            merged.update(value)
            config[key] = merged
        else:
            config[key] = value
    return config


def run_cmd(args, timeout=None):
    result = subprocess.run(
        args,
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    return result.returncode, result.stdout, result.stderr


def run_cdp_json(command_args, timeout=None):
    cmd = [
        sys.executable,
        str(CDP_SCRIPT),
        "--json-output",
        "--reuse-existing-tab",
        *command_args,
    ]
    code, stdout, stderr = run_cmd(cmd, timeout=timeout)
    stdout = (stdout or "").strip()
    if not stdout:
        return code, None, stderr

    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        parsed = extract_json_objects(stdout)

    if isinstance(parsed, dict) and "payload" in parsed:
        return code, parsed.get("payload"), stderr
    return code, parsed, stderr


def load_templates(path):
    if not path.exists():
        print(f"找不到评论模板文件：{path}")
        print("请先创建 comment_templates.txt，或在 config/semi_auto_comment.json 里指定 templates_file。")
        sys.exit(1)

    templates = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            templates.append(line)

    if not templates:
        print(f"{path} 是空的。请至少放入一条评论模板。")
        sys.exit(1)

    return templates


def build_note_url(note_id, xsec_token):
    token = quote(xsec_token or "", safe="")
    return f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={token}&xsec_source=pc_search"


def extract_note_id_from_url(note_url):
    if not note_url:
        return ""
    match = re.search(r"/explore/([^?/#]+)", note_url)
    return match.group(1) if match else ""


def read_csv_header(path):
    try:
        rows, encoding = read_mixed_encoding_csv(path)
        if not rows:
            return [], encoding
        return list(rows[0].keys()), encoding
    except Exception:
        pass

    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            with path.open("r", encoding=encoding, newline="") as f:
                reader = csv.reader(f)
                return next(reader, []), encoding
        except UnicodeDecodeError:
            continue
        except Exception:
            return [], encoding
    return [], ""


def decode_csv_line(raw_line):
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return raw_line.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw_line.decode("utf-8", errors="replace"), "mixed-replace"


def read_mixed_encoding_csv(path):
    raw_lines = [line for line in path.read_bytes().splitlines() if line.strip()]
    if not raw_lines:
        return [], "mixed"

    header_text, header_encoding = decode_csv_line(raw_lines[0])
    header = next(csv.reader([header_text]))
    rows = []
    used_encodings = {header_encoding}
    for raw_line in raw_lines[1:]:
        line_text, encoding = decode_csv_line(raw_line)
        used_encodings.add(encoding)
        values = next(csv.reader([line_text]))
        row = {key: values[index] if index < len(values) else "" for index, key in enumerate(header)}
        rows.append(row)
    encoding_label = "mixed" if len(used_encodings) > 1 else next(iter(used_encodings))
    return rows, encoding_label


def read_csv_dict_rows(path):
    last_error = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            with path.open("r", encoding=encoding, newline="") as f:
                return list(csv.DictReader(f)), encoding
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
        except Exception as exc:
            last_error = exc
            break
    try:
        return read_mixed_encoding_csv(path)
    except Exception:
        raise last_error or UnicodeDecodeError("unknown", b"", 0, 1, "unknown csv encoding")


def choose_active_log_file(configured_path):
    if not configured_path.exists():
        return configured_path

    header, _ = read_csv_header(configured_path)

    if not header or header == LOG_FIELDNAMES:
        return configured_path

    return configured_path.with_name(f"{configured_path.stem}_v2{configured_path.suffix}")


def read_log_rows(*paths):
    rows = []
    seen_paths = set()
    for path in paths:
        if not path or not path.exists():
            continue
        resolved = str(path.resolve())
        if resolved in seen_paths:
            continue
        seen_paths.add(resolved)
        try:
            loaded_rows, _ = read_csv_dict_rows(path)
            rows.extend(loaded_rows)
        except Exception as exc:
            print(f"读取日志失败，已跳过：{path} ({exc})")
    return rows


def get_logged_note_ids(rows):
    note_ids = set()
    for row in rows:
        note_id = (row.get("note_id") or "").strip()
        if not note_id:
            note_id = extract_note_id_from_url(row.get("note_url") or "")
        if note_id:
            note_ids.add(note_id)
    return note_ids


def count_today_success(rows):
    today = datetime.now().date().isoformat()
    count = 0
    for row in rows:
        timestamp = row.get("timestamp") or ""
        status = row.get("status") or row.get("published") or ""
        if timestamp.startswith(today) and status in {"confirmed", "success", "成功"}:
            count += 1
    return count


def write_log(log_file, row):
    row = {key: row.get(key, "") for key in LOG_FIELDNAMES}

    def append_to_csv(path):
        exists = path.exists()
        with path.open("a", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=LOG_FIELDNAMES)
            if not exists:
                writer.writeheader()
            writer.writerow(row)

    try:
        append_to_csv(log_file)
        return str(log_file)
    except PermissionError:
        fallback = BASE_DIR / f"comment_log_fallback_{time.strftime('%Y%m%d_%H%M%S')}.csv"
        append_to_csv(fallback)
        print()
        print("主记录文件被占用，可能是 Excel / WPS / 记事本正在打开。")
        print(f"本次记录已写入备用文件：{fallback}")
        return str(fallback)


def read_queue_rows(queue_file):
    if not queue_file.exists():
        return []
    try:
        rows, encoding = read_csv_dict_rows(queue_file)
        if encoding not in {"utf-8", "utf-8-sig"}:
            print(f"检测到队列文件编码为 {encoding}，已兼容读取。建议保存为 UTF-8 CSV。")
        return rows
    except Exception as exc:
        print(f"读取队列失败：{queue_file} ({exc})")
        return []


def write_queue_rows(queue_file, rows):
    queue_file.parent.mkdir(parents=True, exist_ok=True)
    with queue_file.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=QUEUE_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in QUEUE_FIELDNAMES})
    return str(queue_file)


def write_status(status_file, message, **fields):
    status_file.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().isoformat(timespec="seconds")
    detail = " ".join(
        f"{key}={str(value).replace(chr(10), ' ')[:160]}"
        for key, value in fields.items()
        if value not in (None, "")
    )
    line = f"{timestamp} {message}"
    if detail:
        line = f"{line} | {detail}"
    with status_file.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    return line


def is_approved(value):
    return str(value or "").strip().lower() in {"1", "yes", "y", "true", "approved", "发"}


def is_pending_queue_status(value):
    return str(value or "").strip().lower() in {"", "pending"}


def is_unreviewed_queue_row(row):
    return is_pending_queue_status(row.get("status")) and not is_approved(row.get("approve"))


def is_approved_pending_queue_row(row):
    return is_pending_queue_status(row.get("status")) and is_approved(row.get("approve"))


def queue_status_counts(rows):
    return {
        "total": len(rows),
        "review": sum(1 for row in rows if is_unreviewed_queue_row(row)),
        "approved": sum(1 for row in rows if is_approved_pending_queue_row(row)),
        "success": sum(1 for row in rows if str(row.get("status") or "").strip().lower() == "success"),
        "failed": sum(1 for row in rows if str(row.get("status") or "").strip().lower() == "failed"),
        "skipped": sum(1 for row in rows if str(row.get("status") or "").strip().lower() == "skipped"),
    }


def print_queue_summary(rows):
    counts = queue_status_counts(rows)
    print(
        "队列统计："
        f"总数 {counts['total']} | "
        f"待审 {counts['review']} | "
        f"已批准待发布 {counts['approved']} | "
        f"成功 {counts['success']} | "
        f"失败 {counts['failed']} | "
        f"跳过 {counts['skipped']}"
    )


def print_finished_queue_rows(rows, limit=8):
    finished_rows = [
        row
        for row in rows
        if str(row.get("status") or "").strip().lower() in {"success", "failed"}
    ]
    if not finished_rows:
        return

    print("最近完成记录：")
    for row in finished_rows[-limit:]:
        status = str(row.get("status") or "").strip().lower()
        status_label = "成功" if status == "success" else "失败"
        finished_at = row.get("published_at") or "-"
        reason = row.get("last_error") or ""
        reason_text = f" reason={reason}" if reason else ""
        print(f"- {status_label} {finished_at} note_id={row.get('note_id', '')}{reason_text}")


def make_queue_rows(keyword, feeds, templates, config):
    rows = []
    created_at = datetime.now().isoformat(timespec="seconds")
    for feed in feeds:
        note_id = get_feed_id(feed)
        xsec_token = get_xsec_token(feed)
        if not note_id or not xsec_token:
            continue
        rows.append(
            {
                "approve": "0",
                "keyword": keyword,
                "note_id": note_id,
                "note_url": build_note_url(note_id, xsec_token),
                "xsec_token": xsec_token,
                "score": score_feed(feed, config),
                "suggested_comment": choose_comment(templates),
                "status": "pending",
                "last_error": "",
                "created_at": created_at,
                "published_at": "",
            }
        )
    return rows


def publish_approved_queue(
    queue_file,
    log_file,
    status_file,
    config,
    wait_min,
    wait_max,
    no_wait,
    daily_limit,
    today_success,
):
    rows = read_queue_rows(queue_file)
    if not rows:
        print(f"队列为空或不存在：{queue_file}")
        write_status(status_file, "队列为空或不存在", queue_file=queue_file)
        return

    approved_rows = [
        row
        for row in rows
        if is_approved_pending_queue_row(row)
    ]
    if not approved_rows:
        print("没有找到 approve=1 且未发布的队列行。")
        write_status(status_file, "没有找到已批准待发布队列行", queue_file=queue_file)
        return

    print(f"准备发布已批准队列：{len(approved_rows)} 条")
    write_status(status_file, "开始发布已批准队列", queue_file=queue_file, count=len(approved_rows))
    published_count = 0

    for row_index, row in enumerate(approved_rows, start=1):
        if daily_limit > 0 and today_success >= daily_limit:
            print(f"今日成功发布数已达到上限：{today_success}/{daily_limit}")
            write_status(status_file, "今日成功发布数达到上限", today_success=today_success, daily_limit=daily_limit)
            break

        note_id = (row.get("note_id") or "").strip()
        xsec_token = (row.get("xsec_token") or "").strip()
        comment = (row.get("suggested_comment") or "").strip()

        if not note_id or not xsec_token or not comment:
            now = datetime.now().isoformat(timespec="seconds")
            row["status"] = "failed"
            row["last_error"] = "missing_note_token_or_comment"
            row["published_at"] = now
            write_queue_rows(queue_file, rows)
            write_status(status_file, "队列行缺少发布参数", note_id=note_id, status="failed")
            continue

        latest_logged_note_ids = get_logged_note_ids(read_log_rows(log_file))
        if config.get("skip_logged_notes", True) and note_id in latest_logged_note_ids:
            now = datetime.now().isoformat(timespec="seconds")
            row["approve"] = "0"
            row["status"] = "skipped"
            row["last_error"] = "duplicate_logged_note"
            row["published_at"] = now
            write_queue_rows(queue_file, rows)
            print(f"跳过已触达笔记：{note_id}")
            write_status(status_file, "发布前跳过已触达队列笔记", note_id=note_id)
            continue

        print(f"正在发布：{note_id}")
        write_status(status_file, "正在发布队列笔记", note_id=note_id, keyword=row.get("keyword"))
        result = post_comment(note_id, xsec_token, comment, config)
        now = datetime.now().isoformat(timespec="seconds")
        row["status"] = result["status"]
        row["last_error"] = result["reason"]
        row["published_at"] = now

        write_log(
            log_file,
            {
                "timestamp": now,
                "keyword": row.get("keyword", ""),
                "note_id": note_id,
                "note_url": row.get("note_url") or build_note_url(note_id, xsec_token),
                "title": row.get("title", ""),
                "author": row.get("author", ""),
                "score": row.get("score", ""),
                "comment": comment,
                "status": result["status"],
                "published": "成功" if result["published"] else "失败",
                "failure_reason": result["reason"],
            },
        )
        write_queue_rows(queue_file, rows)
        write_status(
            status_file,
            "队列笔记发布完成",
            note_id=note_id,
            status=result["status"],
            published="成功" if result["published"] else "失败",
            reason=result["reason"],
        )

        if result["status"] == "success":
            today_success += 1
            published_count += 1

        has_more_approved_rows = row_index < len(approved_rows)
        if result["published"] and has_more_approved_rows:
            maybe_wait(wait_min, wait_max, no_wait)
        elif result["published"]:
            write_status(status_file, "最后一条队列记录已发布，不再等待", note_id=note_id)

    print(f"队列发布完成，成功记录：{published_count} 条")
    print(f"队列文件：{queue_file}")
    write_status(status_file, "队列发布完成", success_count=published_count, queue_file=queue_file)


def review_queue(queue_file, status_file):
    rows = read_queue_rows(queue_file)
    if not rows:
        print(f"队列为空或不存在：{queue_file}")
        write_status(status_file, "队列为空或不存在", queue_file=queue_file)
        return

    pending_indexes = [
        index
        for index, row in enumerate(rows)
        if is_pending_queue_status(row.get("status"))
    ]
    if not pending_indexes:
        print("没有待审队列行。")
        write_status(status_file, "没有待审队列行", queue_file=queue_file)
        return

    print(f"队列文件：{queue_file}")
    print(f"待审记录：{len(pending_indexes)} 条")
    print("操作：a=批准当前 all=全部批准 s=跳过 e=改评论 n=下一条 q=退出")
    write_status(status_file, "开始审查队列", queue_file=queue_file, count=len(pending_indexes))

    cursor = 0
    while cursor < len(pending_indexes):
        row_index = pending_indexes[cursor]
        row = rows[row_index]
        print()
        print("-" * 80)
        print(f"[{cursor + 1}/{len(pending_indexes)}] keyword={row.get('keyword', '')}")
        print(f"note_id={row.get('note_id', '')}")
        print(f"url={row.get('note_url', '')}")
        print(f"score={row.get('score', '')} approve={row.get('approve', '')} status={row.get('status', '')}")
        print(f"comment={row.get('suggested_comment', '')}")

        action = input("操作 [a/all/s/e/n/q]：").strip().lower()
        if action in {"", "n", "next"}:
            cursor += 1
            continue
        if action in {"q", "quit", "exit"}:
            break
        if action in {"all", "aa"}:
            current_pending_indexes = [
                index
                for index, queue_row in enumerate(rows)
                if is_pending_queue_status(queue_row.get("status"))
            ]
            for index in current_pending_indexes:
                rows[index]["approve"] = "1"
            write_queue_rows(queue_file, rows)
            print(f"已全部批准：{len(current_pending_indexes)} 条待处理记录。")
            write_status(status_file, "已全部批准待处理队列", queue_file=queue_file, count=len(current_pending_indexes))
            return
        if action in {"a", "approve", "1"}:
            row["approve"] = "1"
            write_queue_rows(queue_file, rows)
            print("已批准当前记录。")
            write_status(status_file, "已批准队列记录", note_id=row.get("note_id"))
            cursor += 1
            continue
        if action in {"s", "skip", "0"}:
            row["approve"] = "0"
            row["status"] = "skipped"
            row["last_error"] = "review_skipped"
            write_queue_rows(queue_file, rows)
            print("已跳过当前记录。")
            write_status(status_file, "已跳过队列记录", note_id=row.get("note_id"))
            cursor += 1
            continue
        if action in {"e", "edit"}:
            new_comment = input("新评论：").strip()
            if new_comment:
                row["suggested_comment"] = new_comment
                write_queue_rows(queue_file, rows)
                print("已更新评论。")
                write_status(status_file, "已编辑队列评论", note_id=row.get("note_id"))
            continue

        print("无法识别操作，请输入 a/all/s/e/n/q。")

    write_status(status_file, "结束审查队列", queue_file=queue_file)


def review_queue_v2(queue_file, status_file):
    rows = read_queue_rows(queue_file)
    if not rows:
        print(f"队列为空或不存在：{queue_file}")
        write_status(status_file, "队列为空或不存在", queue_file=queue_file)
        return

    print(f"队列文件：{queue_file}")
    print_queue_summary(rows)
    print_finished_queue_rows(rows)
    print()
    print("操作：a=批准当前 all=全部批准 s=跳过 e=改评论 n=下一条 q=退出")
    write_status(status_file, "开始审查队列", queue_file=queue_file, count=queue_status_counts(rows)["review"])

    cursor = 0
    while True:
        pending_indexes = [
            index
            for index, row in enumerate(rows)
            if is_unreviewed_queue_row(row)
        ]
        if not pending_indexes:
            print("没有待审队列行。")
            print_queue_summary(rows)
            print_finished_queue_rows(rows)
            break

        if cursor >= len(pending_indexes):
            cursor = 0

        row_index = pending_indexes[cursor]
        row = rows[row_index]
        print()
        print("-" * 80)
        print_queue_summary(rows)
        print(f"[{cursor + 1}/{len(pending_indexes)}] keyword={row.get('keyword', '')}")
        print(f"note_id={row.get('note_id', '')}")
        print(f"url={row.get('note_url', '')}")
        print(f"approve={row.get('approve', '')} status={row.get('status', '')}")
        print(f"comment={row.get('suggested_comment', '')}")

        action = input("操作 [a/all/s/e/n/q]：").strip().lower()
        if action in {"", "n", "next"}:
            cursor += 1
            continue
        if action in {"q", "quit", "exit"}:
            break
        if action in {"all", "aa"}:
            current_pending_indexes = [
                index
                for index, queue_row in enumerate(rows)
                if is_unreviewed_queue_row(queue_row)
            ]
            for index in current_pending_indexes:
                rows[index]["approve"] = "1"
            write_queue_rows(queue_file, rows)
            print(f"已全部批准：{len(current_pending_indexes)} 条待审记录。")
            print_queue_summary(rows)
            write_status(status_file, "已全部批准待处理队列", queue_file=queue_file, count=len(current_pending_indexes))
            return
        if action in {"a", "approve", "1"}:
            row["approve"] = "1"
            write_queue_rows(queue_file, rows)
            print("已批准当前记录。")
            print_queue_summary(rows)
            write_status(status_file, "已批准队列记录", note_id=row.get("note_id"))
            continue
        if action in {"s", "skip", "0"}:
            now = datetime.now().isoformat(timespec="seconds")
            row["approve"] = "0"
            row["status"] = "skipped"
            row["last_error"] = "review_skipped"
            row["published_at"] = now
            write_queue_rows(queue_file, rows)
            print("已跳过当前记录。")
            print_queue_summary(rows)
            write_status(status_file, "已跳过队列记录", note_id=row.get("note_id"))
            continue
        if action in {"e", "edit"}:
            new_comment = input("新评论：").strip()
            if new_comment:
                row["suggested_comment"] = new_comment
                write_queue_rows(queue_file, rows)
                print("已更新评论。")
                write_status(status_file, "已编辑队列评论", note_id=row.get("note_id"))
            continue

        print("无法识别操作，请输入 a/all/s/e/n/q。")

    write_status(status_file, "结束审查队列", queue_file=queue_file)


def extract_json_objects(text):
    text = text.strip()
    if not text:
        return None

    try:
        return json.loads(text)
    except Exception:
        pass

    array_match = re.search(r"(\[\s*{.*}\s*\])", text, flags=re.S)
    if array_match:
        try:
            return json.loads(array_match.group(1))
        except Exception:
            pass

    object_match = re.search(r"({.*})", text, flags=re.S)
    if object_match:
        try:
            return json.loads(object_match.group(1))
        except Exception:
            pass

    return None


def normalize_feeds(data):
    if data is None:
        return []

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ["data", "items", "feeds", "notes", "result"]:
            value = data.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                for sub_key in ["items", "feeds", "notes", "list"]:
                    sub_value = value.get(sub_key)
                    if isinstance(sub_value, list):
                        return sub_value

    return []


def get_nested(d, *keys, default=""):
    cur = d
    for key in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
    return cur if cur is not None else default


def get_feed_id(feed):
    return (
        feed.get("id")
        or feed.get("noteId")
        or feed.get("note_id")
        or feed.get("feedId")
        or feed.get("feed_id")
        or get_nested(feed, "note", "id")
        or ""
    )


def get_xsec_token(feed):
    return (
        feed.get("xsecToken")
        or feed.get("xsec_token")
        or feed.get("xsec")
        or get_nested(feed, "note", "xsecToken")
        or ""
    )


def get_title(feed):
    return (
        feed.get("displayTitle")
        or feed.get("title")
        or feed.get("desc")
        or get_nested(feed, "note", "displayTitle")
        or get_nested(feed, "note", "title")
        or ""
    )


def get_author(feed):
    user = feed.get("user") or feed.get("author") or {}
    if isinstance(user, dict):
        return user.get("nickname") or user.get("name") or user.get("nickName") or ""
    return ""


def get_liked_count(feed):
    return (
        feed.get("likedCount")
        or feed.get("likeCount")
        or feed.get("likes")
        or get_nested(feed, "interactInfo", "likedCount")
        or get_nested(feed, "interactInfo", "likeCount")
        or ""
    )


def get_note_type(feed):
    return feed.get("type") or feed.get("noteType") or feed.get("modelType") or ""


def score_feed(feed, config):
    title = get_title(feed)
    score = 0

    for kw in config.get("good_title_keywords", []):
        if kw and kw in title:
            score += 3

    for kw in config.get("bad_title_keywords", []):
        if kw and kw in title:
            score -= 5

    if get_feed_id(feed):
        score += 1

    if get_xsec_token(feed):
        score += 1

    return score


def is_blocked_by_config(feed, config):
    title = get_title(feed)
    required = [kw for kw in config.get("required_title_keywords", []) if kw]
    blocked = [kw for kw in config.get("blocked_title_keywords", []) if kw]

    if required and not any(kw in title for kw in required):
        return True, "missing_required_keyword"

    if any(kw in title for kw in blocked):
        return True, "blocked_title_keyword"

    min_score = int(config.get("min_score") or 0)
    if score_feed(feed, config) < min_score:
        return True, "below_min_score"

    return False, ""


def search_feeds(keyword, limit, config, logged_note_ids, allow_repeat):
    command_args = ["search-feeds", "--keyword", keyword]
    filter_arg_names = {
        "sort_by": "--sort-by",
        "note_type": "--note-type",
        "publish_time": "--publish-time",
        "search_scope": "--search-scope",
        "location": "--location",
    }
    for key, arg_name in filter_arg_names.items():
        value = (config.get("search_filters") or {}).get(key)
        if value:
            command_args.extend([arg_name, str(value)])

    code, payload, stderr = run_cdp_json(command_args, timeout=90)

    if code != 0:
        print("搜索命令执行失败。")
        if stderr:
            print(stderr)
        return []

    feeds = normalize_feeds(payload)

    if not feeds:
        print("没有解析到搜索结果。")
        return []

    cleaned = []
    seen = set()
    skipped_logged = 0
    skipped_config = 0

    for feed in feeds:
        if not isinstance(feed, dict):
            continue

        note_id = get_feed_id(feed)
        xsec_token = get_xsec_token(feed)

        if not note_id or not xsec_token:
            continue

        if note_id in seen:
            continue

        seen.add(note_id)

        if (
            config.get("skip_logged_notes", True)
            and not allow_repeat
            and note_id in logged_note_ids
        ):
            skipped_logged += 1
            continue

        blocked, _ = is_blocked_by_config(feed, config)
        if blocked:
            skipped_config += 1
            continue

        cleaned.append(feed)

    cleaned.sort(key=lambda item: score_feed(item, config), reverse=True)
    if skipped_logged:
        print(f"已跳过历史触达笔记：{skipped_logged} 条")
    if skipped_config:
        print(f"已按配置过滤候选：{skipped_config} 条")
    return cleaned[:limit]


def open_detail(note_id, xsec_token):
    code, payload, stderr = run_cdp_json(
        ["get-feed-detail", "--feed-id", note_id, "--xsec-token", xsec_token],
        timeout=90,
    )

    combined = json.dumps(payload, ensure_ascii=False) if payload is not None else ""
    combined += "\n" + (stderr or "")

    if code != 0:
        print("打开详情页失败，自动跳过。")
        if combined.strip():
            print(combined.strip()[:1200])
        return False

    if "暂时无法浏览" in combined or "扫码" in combined or "二维码" in combined:
        print("详情页被限制访问，自动跳过。")
        if combined.strip():
            print(combined.strip()[:1200])
        return False

    print("详情页已自动打开。")
    return True


def post_comment(note_id, xsec_token, comment, config):
    code, payload, stderr = run_cdp_json(
        [
            "post-comment-to-feed",
            "--feed-id",
            note_id,
            "--xsec-token",
            xsec_token,
            "--content",
            comment,
        ],
        timeout=120,
    )

    combined = json.dumps(payload, ensure_ascii=False) if payload is not None else ""
    combined += "\n" + (stderr or "")

    if code != 0:
        print("发布命令返回失败。")
        if combined.strip():
            print(combined.strip()[:2000])
        return {"published": False, "status": "failed", "reason": "post_command_failed"}

    if "二维码" in combined or "扫码" in combined or "手机端查看" in combined:
        print("发布时触发扫码/二维码限制。本条按失败记录，建议跳过。")
        if combined.strip():
            print(combined.strip()[:2000])
        return {"published": False, "status": "failed", "reason": "qr_or_mobile_gate"}

    if isinstance(payload, dict) and payload.get("success") is False:
        return {"published": False, "status": "failed", "reason": "payload_success_false"}

    print("发布命令已完成，按成功记录。")
    return {"published": True, "status": "success", "reason": ""}


def choose_comment(templates):
    return random.choice(templates)


def maybe_wait(wait_min, wait_max, no_wait):
    if no_wait:
        return

    if wait_min < 0 or wait_max < 0:
        return

    if wait_max < wait_min:
        wait_min, wait_max = wait_max, wait_min

    seconds = random.randint(wait_min, wait_max)
    print(f"等待 {seconds} 秒后继续。按 Ctrl + C 可提前退出。")
    time.sleep(seconds)


def print_feed(index, feed, config):
    note_id = get_feed_id(feed)
    xsec_token = get_xsec_token(feed)
    title = get_title(feed)
    author = get_author(feed)
    liked = get_liked_count(feed)
    note_type = get_note_type(feed)
    note_url = build_note_url(note_id, xsec_token)

    print()
    print("=" * 80)
    print(f"[{index}] 标题：{title}")
    print(f"作者：{author}")
    print(f"类型：{note_type}")
    print(f"点赞：{liked}")
    print(f"评分：{score_feed(feed, config)}")
    print(f"feed-id：{note_id}")
    print(f"链接：{note_url}")
    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(description="小红书半自动评论脚本")
    parser.add_argument("--keyword", default="找品", help="搜索关键词，默认：找品")
    parser.add_argument("--limit", type=int, default=10, help="候选笔记数量，默认：10")
    parser.add_argument("--wait-min", type=int, default=120, help="成功发布后的最小等待秒数，默认：120")
    parser.add_argument("--wait-max", type=int, default=300, help="成功发布后的最大等待秒数，默认：300")
    parser.add_argument("--no-wait", action="store_true", help="发布后不等待，不建议频繁使用")
    parser.add_argument("--config", default=str(CONFIG_FILE), help="半自动评论配置文件路径")
    parser.add_argument("--allow-repeat", action="store_true", help="允许处理日志中已经触达过的笔记")
    parser.add_argument("--make-queue", action="store_true", help="只生成 review_queue.csv，不发布")
    parser.add_argument("--append-queue", action="store_true", help="生成队列时追加到现有队列")
    parser.add_argument("--review-queue", action="store_true", help="在终端审查待处理队列")
    parser.add_argument("--publish-approved", action="store_true", help="只发布队列中 approve=1 的记录")
    parser.add_argument("--queue-file", help="队列 CSV 路径，默认 review_queue.csv")
    args = parser.parse_args()

    if not CDP_SCRIPT.exists():
        print(f"找不到 cdp_publish.py：{CDP_SCRIPT}")
        print("请确认当前脚本放在 XiaohongshuSkills 项目根目录。")
        sys.exit(1)

    config = load_config(Path(args.config))

    templates_file = resolve_path(config.get("templates_file"), DEFAULT_TEMPLATES_FILE)
    configured_log_file = resolve_path(config.get("log_file"), DEFAULT_LOG_FILE)
    queue_file = resolve_path(args.queue_file or config.get("queue_file"), DEFAULT_QUEUE_FILE)
    status_file = resolve_path(config.get("status_file"), DEFAULT_STATUS_FILE)
    active_log_file = choose_active_log_file(configured_log_file)
    log_rows = read_log_rows(configured_log_file, active_log_file)
    logged_note_ids = get_logged_note_ids(log_rows)
    today_success = count_today_success(log_rows)
    daily_limit = int(config.get("daily_success_limit") or 0)

    if active_log_file != configured_log_file:
        print(f"检测到旧版日志表头，新记录将写入：{active_log_file}")

    write_status(
        status_file,
        "脚本启动",
        keyword=args.keyword,
        limit=args.limit,
        make_queue=args.make_queue,
        review_queue=args.review_queue,
        publish_approved=args.publish_approved,
        queue_file=queue_file,
        log_file=active_log_file,
    )

    if args.review_queue:
        review_queue_v2(queue_file=queue_file, status_file=status_file)
        return

    if not args.make_queue and daily_limit > 0 and today_success >= daily_limit:
        print(f"今日成功发布数已达到上限：{today_success}/{daily_limit}")
        write_status(status_file, "今日成功发布数达到上限", today_success=today_success, daily_limit=daily_limit)
        return

    templates = load_templates(templates_file)

    if args.publish_approved:
        publish_approved_queue(
            queue_file=queue_file,
            log_file=active_log_file,
            status_file=status_file,
            config=config,
            wait_min=args.wait_min,
            wait_max=args.wait_max,
            no_wait=args.no_wait,
            daily_limit=daily_limit,
            today_success=today_success,
        )
        return

    print(f"当前关键词：{args.keyword}")
    print(f"候选数量：{args.limit}")
    print(f"已记录触达笔记：{len(logged_note_ids)} 条")
    if daily_limit > 0:
        print(f"今日成功发布：{today_success}/{daily_limit}")
    print("开始搜索笔记...")
    write_status(status_file, "开始搜索笔记", keyword=args.keyword, limit=args.limit)

    feeds = search_feeds(
        keyword=args.keyword,
        limit=args.limit,
        config=config,
        logged_note_ids=logged_note_ids,
        allow_repeat=args.allow_repeat,
    )

    if not feeds:
        print("没有可用候选笔记。")
        write_status(status_file, "没有可用候选笔记", keyword=args.keyword)
        return
    write_status(status_file, "搜索完成", keyword=args.keyword, count=len(feeds))

    if args.make_queue:
        queue_rows = make_queue_rows(args.keyword, feeds, templates, config)
        if args.append_queue:
            existing_rows = read_queue_rows(queue_file)
            existing_ids = {row.get("note_id") for row in existing_rows}
            queue_rows = existing_rows + [
                row for row in queue_rows if row.get("note_id") not in existing_ids
            ]
        path = write_queue_rows(queue_file, queue_rows)
        print(f"已生成待审队列：{path}")
        print(f"候选行数：{len(queue_rows)}")
        print("运行 --review-queue 在终端审查批准后，再运行 --publish-approved。")
        write_status(status_file, "已生成待审队列", queue_file=path, count=len(queue_rows))
        return

    print(f"解析到 {len(feeds)} 条候选笔记。")
    print()
    print("当前流程：")
    print("1. 自动打开详情页")
    print("2. 自动抽取评论模板")
    print("3. 最后只输入一个字母确认")
    print()
    print("可用操作：p 发布 / r 换一句 / e 编辑 / s 跳过 / q 退出")

    for i, feed in enumerate(feeds, start=1):
        note_id = get_feed_id(feed)
        xsec_token = get_xsec_token(feed)
        title = get_title(feed)
        author = get_author(feed)
        note_url = build_note_url(note_id, xsec_token)

        if (
            config.get("skip_logged_notes", True)
            and not args.allow_repeat
            and note_id in logged_note_ids
        ):
            print(f"跳过已触达笔记：{note_id}")
            continue

        if daily_limit > 0 and today_success >= daily_limit:
            print(f"今日成功发布数已达到上限：{today_success}/{daily_limit}")
            write_status(status_file, "今日成功发布数达到上限", today_success=today_success, daily_limit=daily_limit)
            return

        print_feed(i, feed, config)
        write_status(
            status_file,
            "当前候选笔记",
            index=i,
            note_id=note_id,
            keyword=args.keyword,
            title=title,
            score=score_feed(feed, config),
        )

        print("正在自动打开详情页...")
        write_status(status_file, "正在打开详情页", note_id=note_id)
        opened = open_detail(note_id, xsec_token)

        if not opened:
            write_status(status_file, "打开详情页失败或受限，跳过", note_id=note_id)
            continue

        comment = choose_comment(templates)

        while True:
            print()
            print("当前评论：")
            print(comment)
            write_status(status_file, "等待用户输入", note_id=note_id, actions="p/r/e/s/q", comment=comment)
            action = input("输入 p 发布，r 换一句，e 编辑，s 跳过，q 退出：").strip().lower()

            if action == "q":
                print("已退出。")
                write_status(status_file, "用户退出", note_id=note_id)
                return

            if action == "s":
                print("已跳过。")
                write_status(status_file, "用户跳过", note_id=note_id)
                break

            if action == "r":
                comment = choose_comment(templates)
                write_status(status_file, "用户换一句评论", note_id=note_id, comment=comment)
                continue

            if action == "e":
                edited = input("请输入新的评论内容：").strip()
                if edited:
                    comment = edited
                    write_status(status_file, "用户编辑评论", note_id=note_id, comment=comment)
                continue

            if action == "p":
                print("正在发布评论...")
                write_status(status_file, "用户确认发布", note_id=note_id)
                result = post_comment(note_id, xsec_token, comment, config)
                log_path = write_log(
                    active_log_file,
                    {
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                        "keyword": args.keyword,
                        "note_id": note_id,
                        "note_url": note_url,
                        "title": title,
                        "author": author,
                        "score": score_feed(feed, config),
                        "comment": comment,
                        "status": result["status"],
                        "published": "成功" if result["published"] else "失败",
                        "failure_reason": result["reason"],
                    },
                )
                logged_note_ids.add(note_id)
                if result["status"] in {"confirmed", "success"}:
                    today_success += 1
                print(f"记录文件：{log_path}")
                write_status(
                    status_file,
                    "交互发布完成",
                    note_id=note_id,
                    status=result["status"],
                    published="成功" if result["published"] else "失败",
                    log_file=log_path,
                    reason=result["reason"],
                )

                has_more_feeds = i < len(feeds)
                if result["published"] and has_more_feeds:
                    maybe_wait(args.wait_min, args.wait_max, args.no_wait)
                elif result["published"]:
                    write_status(status_file, "最后一条候选已发布，不再等待", note_id=note_id)

                break

            print("输入无效。只能输入 p / r / e / s / q。")

    print()
    print("本轮候选笔记处理完成。")
    write_status(status_file, "本轮候选笔记处理完成", keyword=args.keyword)


if __name__ == "__main__":
    main()
