import json
import os
import socket
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


PORT = int(os.environ.get("PORT", "3000"))
HOST = os.environ.get("HOST", "127.0.0.1")
ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
DATA_FILE = DATA_DIR / "store.json"
PUBLIC_DIR = ROOT_DIR / "public"
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_BODY_SYSTEM_PROMPT = "\n".join(
    [
        "你是小说协作写作助手。",
        "直接输出章节正文，不要输出标题，不要输出摘要，不要输出 JSON，不要输出 Markdown 代码块。",
        "正文必须使用中文，目标长度 2500 到 3500 字。",
        "重要设定只在必要处提及，避免解释腔和设定堆砌。",
    ]
)


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def ensure_data_file():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not DATA_FILE.exists():
        DATA_FILE.write_text(
            json.dumps(
                {
                    "projects": [],
                    "meta": {"nextId": 1},
                    "settings": {
                        "model": {
                            "apiKey": "",
                            "baseUrl": "https://api.openai.com/v1",
                            "model": "gpt-4.1-mini",
                        }
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            "utf-8",
        )


def read_store():
    ensure_data_file()
    store = json.loads(DATA_FILE.read_text("utf-8"))
    if "settings" not in store:
        store["settings"] = {}
    if "model" not in store["settings"]:
        store["settings"]["model"] = {
            "apiKey": "",
            "baseUrl": "https://api.openai.com/v1",
            "model": "gpt-4.1-mini",
        }
    if "prompts" not in store["settings"]:
        store["settings"]["prompts"] = {}
    return store


def write_store(store):
    DATA_FILE.write_text(json.dumps(store, ensure_ascii=False, indent=2), "utf-8")


def next_id(store):
    value = str(store["meta"]["nextId"])
    store["meta"]["nextId"] += 1
    return value


def normalize_text(value):
    return str(value or "").strip()


def summarize_text(text, max_length=320):
    normalized = " ".join(normalize_text(text).split())
    if len(normalized) > max_length:
        return f"{normalized[:max_length]}..."
    return normalized


def parse_json_text(text, context_label):
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        snippet = summarize_text(text, 240) or "<empty response>"
        raise RuntimeError(f"{context_label} returned non-JSON content: {snippet}") from error


def stream_chunks(text, chunk_size=120):
    normalized = str(text or "")
    for start in range(0, len(normalized), chunk_size):
        yield normalized[start : start + chunk_size]


def unique_by_id(items):
    result = []
    seen = set()
    for item in items:
        item_id = item["id"]
        if item_id in seen:
            continue
        seen.add(item_id)
        result.append(item)
    return result


def get_project(store, project_id):
    return next((project for project in store["projects"] if project["id"] == project_id), None)


def get_chapter(project, chapter_id):
    return next((chapter for chapter in project["chapters"] if chapter["id"] == chapter_id), None)


def default_related_chapters(project, new_chapter_id):
    related = []
    for chapter in project["chapters"][-3:]:
        if chapter["id"] == new_chapter_id:
            continue
        related.append({"chapterId": chapter["id"], "useBody": True, "useSummary": False})
    return related


def merge_dynamic_info(existing, additions):
    segments = [item.strip() for item in normalize_text(existing).splitlines() if item.strip()]
    for addition in additions:
        value = normalize_text(addition)
        if value and value not in segments:
            segments.append(value)
    return "\n".join(segments[-8:])


def extract_auto_loaded_cards(project, chapter_input):
    combined = "\n".join(
        normalize_text(chapter_input.get(field))
        for field in ["title", "plot", "relationships", "styleGuide", "body", "summary"]
    )
    selected_character_ids = set(str(item) for item in chapter_input.get("selectedCharacterIds", []))
    selected_entry_ids = set(str(item) for item in chapter_input.get("selectedEntryIds", []))

    auto_characters = [
        character
        for character in project["characters"]
        if character["id"] not in selected_character_ids and character.get("name") and character["name"] in combined
    ]
    auto_entries = [
        entry
        for entry in project["entries"]
        if entry["id"] not in selected_entry_ids and entry.get("name") and entry["name"] in combined
    ]
    return {"autoCharacters": auto_characters, "autoEntries": auto_entries}


def get_related_chapter_context(project, chapter, chapter_id):
    related_context = []
    for relation in chapter.get("relatedChapters", []):
        related = get_chapter(project, relation["chapterId"])
        if not related or related["id"] == chapter_id:
            continue
        related_context.append(
            {
                "id": related["id"],
                "title": related.get("title", ""),
                "useBody": bool(relation.get("useBody")),
                "useSummary": bool(relation.get("useSummary")),
                "body": related.get("body", "") if relation.get("useBody") else "",
                "summary": related.get("summary", "") if relation.get("useSummary") else "",
            }
        )
    return related_context


def build_generation_payload(project, chapter, chapter_id):
    selected_character_ids = set(chapter.get("selectedCharacterIds", []))
    selected_entry_ids = set(chapter.get("selectedEntryIds", []))
    selected_characters = [item for item in project["characters"] if item["id"] in selected_character_ids]
    selected_entries = [item for item in project["entries"] if item["id"] in selected_entry_ids]
    auto_loaded = extract_auto_loaded_cards(project, chapter)
    used_characters = unique_by_id(selected_characters + auto_loaded["autoCharacters"])
    used_entries = unique_by_id(selected_entries + auto_loaded["autoEntries"])

    return {
        "usedCharacters": used_characters,
        "usedEntries": used_entries,
        "autoLoadedCharacterIds": [item["id"] for item in auto_loaded["autoCharacters"]],
        "autoLoadedEntryIds": [item["id"] for item in auto_loaded["autoEntries"]],
        "relatedContext": get_related_chapter_context(project, chapter, chapter_id),
    }


def build_body_user_prompt(project, chapter, payload):
    return json.dumps(
        {
            "chapter": {
                "id": chapter.get("id", ""),
                "title": chapter.get("title", ""),
                "plot": chapter.get("plot", ""),
                "relationships": chapter.get("relationships", ""),
                "styleGuide": chapter.get("styleGuide", ""),
            },
            "usedCharacters": [
                {
                    "id": item["id"],
                    "name": item.get("name", ""),
                    "gender": item.get("gender", ""),
                    "personality": item.get("personality", ""),
                    "relatedInfo": item.get("relatedInfo", ""),
                }
                for item in payload["usedCharacters"]
            ],
            "usedEntries": [
                {"id": item["id"], "name": item.get("name", ""), "relatedInfo": item.get("relatedInfo", "")}
                for item in payload["usedEntries"]
            ],
            "relatedContext": payload["relatedContext"],
            "requirements": {
                "outputLanguage": "zh-CN",
                "bodyLength": "2500-3500 Chinese characters",
                "regenerateReplacesBodyAndSummary": True,
            },
        },
        ensure_ascii=False,
        indent=2,
    )


def get_body_system_prompt(store):
    return normalize_text(store.get("settings", {}).get("prompts", {}).get("chapterBodySystemPrompt")) or DEFAULT_BODY_SYSTEM_PROMPT


def build_body_prompt(project, chapter, payload, store):
    signature = build_body_prompt_source_signature(project, chapter, payload)
    saved_user_prompt = normalize_text(chapter.get("bodyUserPrompt"))
    if chapter.get("bodyUserPromptSourceSignature") != signature:
        saved_user_prompt = ""
    return {
        "systemPrompt": get_body_system_prompt(store),
        "userPrompt": saved_user_prompt or build_body_user_prompt(project, chapter, payload),
    }


def build_body_prompt_source_signature(project, chapter, payload):
    source = {
        "chapter": {
            "id": chapter.get("id", ""),
            "title": chapter.get("title", ""),
            "plot": chapter.get("plot", ""),
            "relationships": chapter.get("relationships", ""),
            "styleGuide": chapter.get("styleGuide", ""),
            "selectedCharacterIds": chapter.get("selectedCharacterIds", []),
            "selectedEntryIds": chapter.get("selectedEntryIds", []),
            "relatedChapters": chapter.get("relatedChapters", []),
        },
        "usedCharacters": [
            {
                "id": item["id"],
                "name": item.get("name", ""),
                "gender": item.get("gender", ""),
                "personality": item.get("personality", ""),
                "relatedInfo": item.get("relatedInfo", ""),
            }
            for item in payload["usedCharacters"]
        ],
        "usedEntries": [
            {"id": item["id"], "name": item.get("name", ""), "relatedInfo": item.get("relatedInfo", "")}
            for item in payload["usedEntries"]
        ],
        "relatedContext": payload["relatedContext"],
    }
    return json.dumps(source, ensure_ascii=False, sort_keys=True)


def refresh_chapter_user_prompt_if_source_changed(project, chapter):
    payload = build_generation_payload(project, chapter, chapter["id"])
    signature = build_body_prompt_source_signature(project, chapter, payload)
    if chapter.get("bodyUserPromptSourceSignature") != signature:
        chapter["bodyUserPrompt"] = build_body_user_prompt(project, chapter, payload)
        chapter["bodyUserPromptSourceSignature"] = signature


def build_card_updates(chapter, payload, body, summary):
    body_summary = summarize_text(body, 180)
    change_hint = summarize_text(chapter.get("plot") or summary, 180)
    return {
        "characterUpdates": [
            {
                "id": character["id"],
                "relatedInfo": merge_dynamic_info(
                    character.get("relatedInfo", ""),
                    [f"最近章节进展：{change_hint}", f"本章涉及摘要：{summary}"],
                ),
            }
            for character in payload["usedCharacters"]
        ],
        "entryUpdates": [
            {
                "id": entry["id"],
                "relatedInfo": merge_dynamic_info(
                    entry.get("relatedInfo", ""),
                    [f"最新关联内容：{change_hint}", f"章节片段：{body_summary}"],
                ),
            }
            for entry in payload["usedEntries"]
        ],
    }


def fallback_finalize(chapter, payload, body):
    summary = summarize_text(
        f"{normalize_text(chapter.get('title')) or '本章'}：{summarize_text(body, 120) or normalize_text(chapter.get('plot')) or '生成完成。'}",
        180,
    )
    return {"summary": summary, "cardUpdates": build_card_updates(chapter, payload, body, summary), "model": "local-fallback"}


def fallback_generate(project, chapter, payload):
    title = normalize_text(chapter.get("title")) or "未命名章节"
    style = normalize_text(chapter.get("styleGuide")) or "自然、连贯的中文小说风格"
    character_line = (
        f"本章涉及角色：{'、'.join(item['name'] for item in payload['usedCharacters'])}。"
        if payload["usedCharacters"]
        else "本章未显式选择角色。"
    )
    entry_line = (
        f"本章涉及词条：{'、'.join(item['name'] for item in payload['usedEntries'])}。"
        if payload["usedEntries"]
        else "本章未显式选择词条。"
    )
    relationship_line = (
        f"角色关系与作用：{chapter['relationships']}" if normalize_text(chapter.get("relationships")) else ""
    )
    related_line = ""
    if payload["relatedContext"]:
        labels = []
        for item in payload["relatedContext"]:
            tag = f"{'正文' if item['useBody'] else ''}{'摘要' if item['useSummary'] else ''}"
            labels.append(f"{item['title'] or item['id']}({tag})")
        related_line = f"关联历史章节：{'、'.join(labels)}。"

    body = "\n".join(
        [
            f"《{title}》",
            "",
            f"写作风格要求：{style}",
            character_line,
            entry_line,
            relationship_line,
            related_line,
            "",
            "剧情展开：",
            normalize_text(chapter.get("plot")) or "暂无剧情描述。",
            "",
            "这一版为本地回退草稿，用于在未配置模型时验证工作流。正式写作时请配置 OpenAI 兼容接口，以获得完整的章节正文与摘要。",
            "",
            "夜色沉下来的时候，故事沿着既定的矛盾缓慢推进。人物带着各自的动机进入场景，彼此试探、误判，再在冲突中逼近真正的问题。叙事需要围绕当前章节目标展开，既回应前文，也为下一章保留余量。作者可以在右侧工作区继续扩写、细化场面、补充对白与节奏。",
            "",
            "随着关键事件被逐步揭开，角色之间的关系会发生可见但克制的变化。重要设定只在必要处被提及，避免堆砌说明。章节结尾应留下新的悬念、压力或选择，让后续章节可以自然衔接。",
        ]
    ).strip()

    summary = summarize_text(
        f"{title}：{normalize_text(chapter.get('plot')) or '根据章节配置生成了一个可继续编辑的草稿。'} 角色与词条已按需装配。"
    )
    return {
        "body": body,
        "summary": summary,
        "model": "local-fallback",
        "cardUpdates": build_card_updates(chapter, payload, body, summary),
    }


def call_model(project, chapter, payload):
    store = read_store()
    runtime_config = get_runtime_model_config(store)
    api_key = runtime_config["apiKey"]
    model = runtime_config["model"]
    base_url = runtime_config["baseUrl"].rstrip("/")
    timeout_seconds = runtime_config["timeoutSeconds"]

    if not api_key:
        return fallback_generate(project, chapter, payload)

    system_prompt = "\n".join(
        [
            "你是小说协作写作助手。",
            "请严格输出 JSON，不要输出 Markdown 代码块。",
            "JSON 结构必须是：",
            '{"body":"章节正文","summary":"章节摘要","character_updates":[{"id":"角色ID","related_info":"角色相关信息"}],"entry_updates":[{"id":"词条ID","related_info":"词条相关信息"}]}',
            "正文必须使用中文，目标长度 2500 到 3500 字。",
            "摘要使用中文，控制在 80 到 180 字。",
            "角色和词条更新必须遵循最小必要更新原则，只更新动态信息，不要重写整个卡片。",
        ]
    )

    user_prompt = json.dumps(
        {
            "chapter": {
                "id": chapter.get("id", ""),
                "title": chapter.get("title", ""),
                "plot": chapter.get("plot", ""),
                "relationships": chapter.get("relationships", ""),
                "styleGuide": chapter.get("styleGuide", ""),
            },
            "usedCharacters": [
                {
                    "id": item["id"],
                    "name": item.get("name", ""),
                    "gender": item.get("gender", ""),
                    "personality": item.get("personality", ""),
                    "relatedInfo": item.get("relatedInfo", ""),
                }
                for item in payload["usedCharacters"]
            ],
            "usedEntries": [
                {"id": item["id"], "name": item.get("name", ""), "relatedInfo": item.get("relatedInfo", "")}
                for item in payload["usedEntries"]
            ],
            "relatedContext": payload["relatedContext"],
            "requirements": {
                "outputLanguage": "zh-CN",
                "bodyLength": "2500-3500 Chinese characters",
                "regenerateReplacesBodyAndSummary": True,
            },
        },
        ensure_ascii=False,
        indent=2,
    )

    payload_body = json.dumps(
        {
            "model": model,
            "temperature": 0.9,
            "max_tokens": 5000,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }
    ).encode("utf-8")

    request = Request(
        f"{base_url}/chat/completions",
        data=payload_body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw_result = response.read().decode("utf-8", errors="replace")
            result = parse_json_text(raw_result, "Model API")
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Model API failed: {error.code} {detail}") from error
    except URLError as error:
        raise RuntimeError(f"Model API unavailable: {error.reason}") from error
    except socket.timeout as error:
        raise RuntimeError(
            f"Model API timed out after {timeout_seconds}s. 当前请求会生成约 3000 字正文和摘要，"
            "如果你接的是较慢模型或中转站，建议提高超时秒数或换更快模型。"
        ) from error

    content = (
        result.get("choices", [{}])[0]
        .get("message", {})
        .get("content")
    )
    if not content:
        raise RuntimeError("Model API returned empty content.")

    parsed = parse_json_text(content, "Model content")

    return {
        "body": normalize_text(parsed.get("body")),
        "summary": normalize_text(parsed.get("summary")),
        "model": model,
        "cardUpdates": {
            "characterUpdates": [
                {"id": str(item.get("id", "")), "relatedInfo": normalize_text(item.get("related_info"))}
                for item in parsed.get("character_updates", [])
            ],
            "entryUpdates": [
                {"id": str(item.get("id", "")), "relatedInfo": normalize_text(item.get("related_info"))}
                for item in parsed.get("entry_updates", [])
            ],
        },
    }


def stream_model_body(project, chapter, payload, emit_body_delta):
    store = read_store()
    runtime_config = get_runtime_model_config(store)
    api_key = runtime_config["apiKey"]
    model = runtime_config["model"]
    base_url = runtime_config["baseUrl"].rstrip("/")
    timeout_seconds = runtime_config["timeoutSeconds"]

    if not api_key:
        fallback = fallback_generate(project, chapter, payload)
        for chunk in stream_chunks(fallback["body"]):
            emit_body_delta(chunk)
        return {"body": fallback["body"], "model": fallback["model"], "cardUpdates": fallback["cardUpdates"], "summary": fallback["summary"]}

    prompts = build_body_prompt(project, chapter, payload, store)

    payload_body = json.dumps(
        {
            "model": model,
            "temperature": 0.9,
            "max_tokens": 5000,
            "stream": True,
            "messages": [
                {"role": "system", "content": prompts["systemPrompt"]},
                {"role": "user", "content": prompts["userPrompt"]},
            ],
        }
    ).encode("utf-8")

    request = Request(
        f"{base_url}/chat/completions",
        data=payload_body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )

    body_parts = []
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            while True:
                raw_line = response.readline()
                if not raw_line:
                    break
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                event_data = line[5:].strip()
                if event_data == "[DONE]":
                    break
                event = parse_json_text(event_data, "Model stream")
                choice = event.get("choices", [{}])[0]
                delta = choice.get("delta", {}).get("content")
                if isinstance(delta, str) and delta:
                    body_parts.append(delta)
                    emit_body_delta(delta)
                finish_reason = choice.get("finish_reason")
                if finish_reason in {"stop", "length"}:
                    break
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Model API failed: {error.code} {detail}") from error
    except URLError as error:
        raise RuntimeError(f"Model API unavailable: {error.reason}") from error
    except socket.timeout as error:
        raise RuntimeError(f"Model API timed out after {timeout_seconds}s.") from error

    body = normalize_text("".join(body_parts))
    if not body:
        raise RuntimeError("Model API returned empty streamed content.")
    return {"body": body, "model": model}


def finalize_generated_chapter(project, chapter, payload, body, model):
    store = read_store()
    runtime_config = get_runtime_model_config(store)
    api_key = runtime_config["apiKey"]
    base_url = runtime_config["baseUrl"].rstrip("/")
    timeout_seconds = runtime_config["timeoutSeconds"]

    if not api_key:
        return fallback_finalize(chapter, payload, body)

    system_prompt = "\n".join(
        [
            "你是小说协作写作助手。",
            "请严格输出 JSON，不要输出 Markdown 代码块。",
            "JSON 结构必须是：",
            '{"summary":"章节摘要","character_updates":[{"id":"角色ID","related_info":"角色相关信息"}],"entry_updates":[{"id":"词条ID","related_info":"词条相关信息"}]}',
            "摘要使用中文，控制在 80 到 180 字。",
            "角色和词条更新必须遵循最小必要更新原则，只更新动态信息，不要重写整个卡片。",
        ]
    )
    user_prompt = json.dumps(
        {
            "chapter": {
                "id": chapter.get("id", ""),
                "title": chapter.get("title", ""),
                "plot": chapter.get("plot", ""),
                "relationships": chapter.get("relationships", ""),
                "styleGuide": chapter.get("styleGuide", ""),
                "body": body,
            },
            "usedCharacters": [
                {
                    "id": item["id"],
                    "name": item.get("name", ""),
                    "gender": item.get("gender", ""),
                    "personality": item.get("personality", ""),
                    "relatedInfo": item.get("relatedInfo", ""),
                }
                for item in payload["usedCharacters"]
            ],
            "usedEntries": [
                {"id": item["id"], "name": item.get("name", ""), "relatedInfo": item.get("relatedInfo", "")}
                for item in payload["usedEntries"]
            ],
        },
        ensure_ascii=False,
        indent=2,
    )
    payload_body = json.dumps(
        {
            "model": model,
            "temperature": 0.4,
            "max_tokens": 1200,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }
    ).encode("utf-8")
    request = Request(
        f"{base_url}/chat/completions",
        data=payload_body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw_result = response.read().decode("utf-8", errors="replace")
            result = parse_json_text(raw_result, "Model API")
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        if detail:
            return fallback_finalize(chapter, payload, body)
        raise RuntimeError(f"Model API failed: {error.code} {detail}") from error
    except URLError as error:
        return fallback_finalize(chapter, payload, body)
    except socket.timeout as error:
        return fallback_finalize(chapter, payload, body)

    content = result.get("choices", [{}])[0].get("message", {}).get("content")
    if not content:
        return fallback_finalize(chapter, payload, body)
    try:
        parsed = parse_json_text(content, "Model content")
    except RuntimeError:
        return fallback_finalize(chapter, payload, body)
    return {
        "summary": normalize_text(parsed.get("summary")),
        "model": model,
        "cardUpdates": {
            "characterUpdates": [
                {"id": str(item.get("id", "")), "relatedInfo": normalize_text(item.get("related_info"))}
                for item in parsed.get("character_updates", [])
            ],
            "entryUpdates": [
                {"id": str(item.get("id", "")), "relatedInfo": normalize_text(item.get("related_info"))}
                for item in parsed.get("entry_updates", [])
            ],
        },
    }


def apply_card_updates(project, updates):
    for update in updates.get("characterUpdates", []):
        for character in project["characters"]:
            if character["id"] == update["id"] and update.get("relatedInfo"):
                character["relatedInfo"] = update["relatedInfo"]
                character["updatedAt"] = now()
                break

    for update in updates.get("entryUpdates", []):
        for entry in project["entries"]:
            if entry["id"] == update["id"] and update.get("relatedInfo"):
                entry["relatedInfo"] = update["relatedInfo"]
                entry["updatedAt"] = now()
                break


def sanitize_project(project):
    sanitized = dict(project)
    sanitized.pop("world", None)
    sanitized["chapters"] = sorted(project["chapters"], key=lambda item: item["order"])
    sanitized["characters"] = sorted(project["characters"], key=lambda item: item.get("name", ""))
    sanitized["entries"] = sorted(project["entries"], key=lambda item: item.get("name", ""))
    return sanitized


def get_runtime_model_config(store):
    saved = store.get("settings", {}).get("model", {})
    api_key = normalize_text(saved.get("apiKey")) or normalize_text(os.environ.get("OPENAI_API_KEY"))
    base_url = normalize_text(saved.get("baseUrl")) or normalize_text(os.environ.get("OPENAI_BASE_URL")) or "https://api.openai.com/v1"
    model = normalize_text(saved.get("model")) or normalize_text(os.environ.get("OPENAI_MODEL")) or "gpt-4.1-mini"
    return {"apiKey": api_key, "baseUrl": base_url, "model": model, "timeoutSeconds": DEFAULT_TIMEOUT_SECONDS}


def get_config_response(store):
    runtime_config = get_runtime_model_config(store)
    return {
        "modelConfigured": bool(runtime_config["apiKey"]),
        "model": runtime_config["model"],
        "baseUrl": runtime_config["baseUrl"],
        "hasSavedApiKey": bool(normalize_text(store.get("settings", {}).get("model", {}).get("apiKey"))),
    }


class AppHandler(BaseHTTPRequestHandler):
    server_version = "AINovelPython/1.0"

    def do_GET(self):
        self.handle_request()

    def do_POST(self):
        self.handle_request()

    def do_PUT(self):
        self.handle_request()

    def handle_request(self):
        try:
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/"):
                self.handle_api(parsed.path)
            else:
                self.handle_static(parsed.path)
        except Exception as error:
            self.send_json(500, {"error": "Internal server error", "detail": str(error)})

    def read_json_body(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length) if content_length else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def begin_sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()

    def send_sse(self, event, payload):
        data = json.dumps(payload, ensure_ascii=False)
        message = f"event: {event}\ndata: {data}\n\n".encode("utf-8")
        self.wfile.write(message)
        self.wfile.flush()

    def finish_sse(self):
        self.close_connection = True

    def send_bytes(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def not_found(self):
        self.send_json(404, {"error": "Not found"})

    def handle_static(self, request_path):
        relative = "index.html" if request_path == "/" else request_path.lstrip("/")
        file_path = (PUBLIC_DIR / relative).resolve()
        if not str(file_path).startswith(str(PUBLIC_DIR.resolve())) or not file_path.exists() or file_path.is_dir():
            self.not_found()
            return

        content_type = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
        }.get(file_path.suffix, "application/octet-stream")
        self.send_bytes(200, file_path.read_bytes(), content_type)

    def handle_api(self, path):
        store = read_store()
        parts = [part for part in path.split("/") if part]

        if self.command == "GET" and path == "/api/config":
            self.send_json(200, get_config_response(store))
            return

        if self.command == "GET" and path == "/api/settings/model":
            settings = store.get("settings", {}).get("model", {})
            self.send_json(
                200,
                {
                    "baseUrl": settings.get("baseUrl", "https://api.openai.com/v1"),
                    "model": settings.get("model", "gpt-4.1-mini"),
                    "hasApiKey": bool(normalize_text(settings.get("apiKey"))),
                },
            )
            return

        if self.command == "PUT" and path == "/api/settings/model":
            body = self.read_json_body()
            existing = store.get("settings", {}).get("model", {})
            api_key_value = existing.get("apiKey", "")
            if "apiKey" in body:
                incoming_api_key = normalize_text(body.get("apiKey"))
                api_key_value = incoming_api_key

            store.setdefault("settings", {})
            store["settings"]["model"] = {
                "apiKey": api_key_value,
                "baseUrl": normalize_text(body.get("baseUrl")) or existing.get("baseUrl") or "https://api.openai.com/v1",
                "model": normalize_text(body.get("model")) or existing.get("model") or "gpt-4.1-mini",
            }
            write_store(store)
            self.send_json(200, get_config_response(store))
            return

        if self.command == "GET" and path == "/api/projects":
            self.send_json(
                200,
                [
                    {
                        "id": project["id"],
                        "title": project["title"],
                        "description": project.get("description", ""),
                        "chapterCount": len(project["chapters"]),
                        "updatedAt": project["updatedAt"],
                    }
                    for project in store["projects"]
                ],
            )
            return

        if self.command == "POST" and path == "/api/projects":
            body = self.read_json_body()
            project = {
                "id": next_id(store),
                "title": normalize_text(body.get("title")) or "未命名作品",
                "description": normalize_text(body.get("description")),
                "createdAt": now(),
                "updatedAt": now(),
                "characters": [],
                "entries": [],
                "chapters": [],
                "generationLogs": [],
            }
            store["projects"].append(project)
            write_store(store)
            self.send_json(201, project)
            return

        if len(parts) < 3 or parts[0] != "api" or parts[1] != "projects":
            self.not_found()
            return

        project = get_project(store, parts[2])
        if not project:
            self.not_found()
            return

        if self.command == "GET" and len(parts) == 3:
            self.send_json(200, sanitize_project(project))
            return

        if self.command == "PUT" and len(parts) == 3:
            body = self.read_json_body()
            project["title"] = normalize_text(body.get("title")) or project["title"]
            project["description"] = normalize_text(body.get("description"))
            project["updatedAt"] = now()
            write_store(store)
            self.send_json(200, sanitize_project(project))
            return

        if self.command == "POST" and len(parts) == 4 and parts[3] == "characters":
            body = self.read_json_body()
            character = {
                "id": next_id(store),
                "name": normalize_text(body.get("name")),
                "gender": normalize_text(body.get("gender")),
                "personality": normalize_text(body.get("personality")),
                "relatedInfo": normalize_text(body.get("relatedInfo")),
                "createdAt": now(),
                "updatedAt": now(),
            }
            project["characters"].append(character)
            project["updatedAt"] = now()
            write_store(store)
            self.send_json(201, character)
            return

        if self.command == "PUT" and len(parts) == 5 and parts[3] == "characters":
            character = next((item for item in project["characters"] if item["id"] == parts[4]), None)
            if not character:
                self.not_found()
                return
            body = self.read_json_body()
            character["name"] = normalize_text(body.get("name"))
            character["gender"] = normalize_text(body.get("gender"))
            character["personality"] = normalize_text(body.get("personality"))
            character["relatedInfo"] = normalize_text(body.get("relatedInfo"))
            character["updatedAt"] = now()
            project["updatedAt"] = now()
            write_store(store)
            self.send_json(200, character)
            return

        if self.command == "POST" and len(parts) == 4 and parts[3] == "entries":
            body = self.read_json_body()
            entry = {
                "id": next_id(store),
                "name": normalize_text(body.get("name")),
                "relatedInfo": normalize_text(body.get("relatedInfo")),
                "createdAt": now(),
                "updatedAt": now(),
            }
            project["entries"].append(entry)
            project["updatedAt"] = now()
            write_store(store)
            self.send_json(201, entry)
            return

        if self.command == "PUT" and len(parts) == 5 and parts[3] == "entries":
            entry = next((item for item in project["entries"] if item["id"] == parts[4]), None)
            if not entry:
                self.not_found()
                return
            body = self.read_json_body()
            entry["name"] = normalize_text(body.get("name"))
            entry["relatedInfo"] = normalize_text(body.get("relatedInfo"))
            entry["updatedAt"] = now()
            project["updatedAt"] = now()
            write_store(store)
            self.send_json(200, entry)
            return

        if self.command == "POST" and len(parts) == 4 and parts[3] == "chapters":
            body = self.read_json_body()
            chapter_id = next_id(store)
            chapter = {
                "id": chapter_id,
                "order": len(project["chapters"]) + 1,
                "title": normalize_text(body.get("title")) or f"第{len(project['chapters']) + 1}章",
                "plot": "",
                "relationships": "",
                "styleGuide": "",
                "body": "",
                "summary": "",
                "selectedCharacterIds": [],
                "selectedEntryIds": [],
                "autoLoadedCharacterIds": [],
                "autoLoadedEntryIds": [],
                "relatedChapters": default_related_chapters(project, chapter_id),
                "bodyUserPrompt": "",
                "bodyUserPromptSourceSignature": "",
                "updatedAt": now(),
                "createdAt": now(),
            }
            project["chapters"].append(chapter)
            project["updatedAt"] = now()
            write_store(store)
            self.send_json(201, chapter)
            return

        if self.command == "PUT" and len(parts) == 5 and parts[3] == "chapters":
            chapter = get_chapter(project, parts[4])
            if not chapter:
                self.not_found()
                return
            body = self.read_json_body()
            chapter["title"] = normalize_text(body.get("title")) or chapter["title"]
            chapter["plot"] = normalize_text(body.get("plot"))
            chapter["relationships"] = normalize_text(body.get("relationships"))
            chapter["styleGuide"] = normalize_text(body.get("styleGuide"))
            if "body" in body and isinstance(body["body"], str):
                chapter["body"] = body["body"]
            if "summary" in body and isinstance(body["summary"], str):
                chapter["summary"] = body["summary"]
            if isinstance(body.get("selectedCharacterIds"), list):
                chapter["selectedCharacterIds"] = [str(item) for item in body["selectedCharacterIds"]]
            if isinstance(body.get("selectedEntryIds"), list):
                chapter["selectedEntryIds"] = [str(item) for item in body["selectedEntryIds"]]
            if isinstance(body.get("relatedChapters"), list):
                chapter["relatedChapters"] = [
                    {
                        "chapterId": str(item["chapterId"]),
                        "useBody": bool(item.get("useBody")),
                        "useSummary": bool(item.get("useSummary")),
                    }
                    for item in body["relatedChapters"]
                    if item and item.get("chapterId")
                ]
            refresh_chapter_user_prompt_if_source_changed(project, chapter)
            chapter["updatedAt"] = now()
            project["updatedAt"] = now()
            write_store(store)
            self.send_json(200, chapter)
            return

        if self.command == "GET" and len(parts) == 6 and parts[3] == "chapters" and parts[5] == "generation-prompt":
            chapter = get_chapter(project, parts[4])
            if not chapter:
                self.not_found()
                return
            payload = build_generation_payload(project, chapter, chapter["id"])
            self.send_json(200, build_body_prompt(project, chapter, payload, store))
            return

        if self.command == "PUT" and len(parts) == 6 and parts[3] == "chapters" and parts[5] == "generation-prompt":
            chapter = get_chapter(project, parts[4])
            if not chapter:
                self.not_found()
                return
            body = self.read_json_body()
            system_prompt = normalize_text(body.get("systemPrompt"))
            user_prompt = normalize_text(body.get("userPrompt"))
            payload = build_generation_payload(project, chapter, chapter["id"])
            signature = build_body_prompt_source_signature(project, chapter, payload)
            store.setdefault("settings", {}).setdefault("prompts", {})["chapterBodySystemPrompt"] = (
                system_prompt or DEFAULT_BODY_SYSTEM_PROMPT
            )
            chapter["bodyUserPrompt"] = user_prompt or build_body_user_prompt(project, chapter, payload)
            chapter["bodyUserPromptSourceSignature"] = signature
            chapter["updatedAt"] = now()
            project["updatedAt"] = now()
            write_store(store)
            self.send_json(200, build_body_prompt(project, chapter, payload, store))
            return

        if self.command == "POST" and len(parts) == 6 and parts[3] == "chapters" and parts[5] == "generate":
            chapter = get_chapter(project, parts[4])
            if not chapter:
                self.not_found()
                return
            payload = build_generation_payload(project, chapter, chapter["id"])
            try:
                generated = call_model(project, chapter, payload)
            except RuntimeError as error:
                self.send_json(500, {"error": "Generation failed", "detail": str(error)})
                return

            chapter["body"] = generated["body"]
            chapter["summary"] = generated["summary"]
            chapter["autoLoadedCharacterIds"] = payload["autoLoadedCharacterIds"]
            chapter["autoLoadedEntryIds"] = payload["autoLoadedEntryIds"]
            chapter["updatedAt"] = now()
            project["updatedAt"] = now()
            apply_card_updates(project, generated["cardUpdates"])
            project["generationLogs"].append(
                {
                    "id": next_id(store),
                    "chapterId": chapter["id"],
                    "createdAt": now(),
                    "input": {
                        "title": chapter["title"],
                        "plot": chapter["plot"],
                        "relationships": chapter["relationships"],
                        "styleGuide": chapter["styleGuide"],
                        "selectedCharacterIds": chapter["selectedCharacterIds"],
                        "selectedEntryIds": chapter["selectedEntryIds"],
                        "relatedChapters": chapter["relatedChapters"],
                    },
                    "output": {
                        "body": chapter["body"],
                        "summary": chapter["summary"],
                        "autoLoadedCharacterIds": chapter["autoLoadedCharacterIds"],
                        "autoLoadedEntryIds": chapter["autoLoadedEntryIds"],
                        "model": generated["model"],
                    },
                }
            )
            write_store(store)
            self.send_json(
                200,
                {
                    "chapter": chapter,
                    "autoLoadedCharacterIds": chapter["autoLoadedCharacterIds"],
                    "autoLoadedEntryIds": chapter["autoLoadedEntryIds"],
                    "model": generated["model"],
                },
            )
            return

        if self.command == "POST" and len(parts) == 6 and parts[3] == "chapters" and parts[5] == "generate-stream":
            chapter = get_chapter(project, parts[4])
            self.begin_sse()
            if not chapter:
                self.send_sse("error", {"detail": "Chapter not found"})
                return

            payload = build_generation_payload(project, chapter, chapter["id"])
            self.send_sse("status", {"message": "正在生成正文..."})
            try:
                streamed = stream_model_body(project, chapter, payload, lambda chunk: self.send_sse("body_delta", {"content": chunk}))
                self.send_sse("status", {"message": "正在整理摘要与卡片更新..."})
                finalized = finalize_generated_chapter(project, chapter, payload, streamed["body"], streamed["model"])
            except RuntimeError as error:
                self.send_sse("error", {"detail": str(error)})
                return

            chapter["body"] = streamed["body"]
            chapter["summary"] = finalized["summary"]
            chapter["autoLoadedCharacterIds"] = payload["autoLoadedCharacterIds"]
            chapter["autoLoadedEntryIds"] = payload["autoLoadedEntryIds"]
            chapter["updatedAt"] = now()
            project["updatedAt"] = now()
            apply_card_updates(project, finalized["cardUpdates"])
            project["generationLogs"].append(
                {
                    "id": next_id(store),
                    "chapterId": chapter["id"],
                    "createdAt": now(),
                    "input": {
                        "title": chapter["title"],
                        "plot": chapter["plot"],
                        "relationships": chapter["relationships"],
                        "styleGuide": chapter["styleGuide"],
                        "selectedCharacterIds": chapter["selectedCharacterIds"],
                        "selectedEntryIds": chapter["selectedEntryIds"],
                        "relatedChapters": chapter["relatedChapters"],
                    },
                    "output": {
                        "body": chapter["body"],
                        "summary": chapter["summary"],
                        "autoLoadedCharacterIds": chapter["autoLoadedCharacterIds"],
                        "autoLoadedEntryIds": chapter["autoLoadedEntryIds"],
                        "model": finalized["model"],
                    },
                }
            )
            write_store(store)
            self.send_sse("summary", {"summary": chapter["summary"]})
            self.send_sse(
                "complete",
                {
                    "chapter": chapter,
                    "autoLoadedCharacterIds": chapter["autoLoadedCharacterIds"],
                    "autoLoadedEntryIds": chapter["autoLoadedEntryIds"],
                    "model": finalized["model"],
                },
            )
            self.finish_sse()
            return

        self.not_found()


def main():
    ensure_data_file()
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    print(f"AI Novel running at http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server.server_close()


if __name__ == "__main__":
    try:
        main()
    except OSError as error:
        print(f"Failed to start server: {error}", file=sys.stderr)
        sys.exit(1)
