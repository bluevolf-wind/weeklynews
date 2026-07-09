#!/usr/bin/env python3
"""
관심 주제별로 최근 1주일 뉴스·임상·회사 소식을 모아
Gemini가 선별·요약한 뒤 매주 목요일 Slack에 업로드하는 스크립트.
"""

import os
import re
import json
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote
from datetime import datetime, timezone, timedelta

import requests
import feedparser

# ---------- 설정 ----------
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
SEEN_FILE = "seen_urls.json"

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)
SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]
NCBI_EMAIL = os.environ.get("NCBI_EMAIL", "example@example.com")

NEWS_PER_QUERY = 6          # 검색어당 가져올 뉴스 수
MAX_ITEMS_PER_TOPIC = 12    # 주제당 Gemini에 넘길 후보 수
SLACK_PICKS_PER_TOPIC = 5   # 주제당 Slack에 올릴 최종 수
SEEN_LIMIT = 3000           # 중복방지 목록 최대 크기

# ---------- 관심 주제 정의 ----------
# name: 표시 이름 / news_ko·news_en: 뉴스 검색어 / pubmed: (선택) 임상 검색어
TOPICS = [
    {
        "name": "🔥 이번 주 핫한 건강기능식품 뉴스",
        "news_ko": ["건강기능식품", "건기식 트렌드"],
        "news_en": ["dietary supplement industry", "nutraceutical trends"],
    },
    {
        "name": "피크노제놀 & 호팍사(Horphag)",
        "news_ko": ["피크노제놀"],
        "news_en": ["Pycnogenol", "Horphag Research", "Robuvit"],
        "pubmed": "Pycnogenol OR Pinus pinaster bark extract",
    },
    {
        "name": "아쿠아셀 코큐텐 (Aquacelle CoQ10)",
        "news_ko": ["아쿠아셀 코큐텐", "코엔자임Q10"],
        "news_en": ["Aquacelle CoQ10", "coenzyme Q10 bioavailability"],
        "pubmed": "Coenzyme Q10 AND (bioavailability OR absorption)",
    },
    {
        "name": "HN019 유산균 (B. lactis HN019)",
        "news_en": ["Bifidobacterium lactis HN019", "HN019 probiotic"],
        "pubmed": "Bifidobacterium animalis lactis HN019",
    },
    {
        "name": "빌베리 & 루테인 (눈 건강)",
        "news_ko": ["빌베리 루테인", "루테인 임상"],
        "news_en": ["bilberry lutein eye health", "lutein clinical trial"],
        "pubmed": "(Bilberry OR Vaccinium myrtillus OR Lutein) AND (vision OR eye OR retina)",
    },
    {
        "name": "🆕 새로운 건강기능식품 원료",
        "news_ko": ["신규 건강기능식품 원료", "개별인정형 원료"],
        "news_en": ["new supplement ingredient launch", "novel nutraceutical ingredient"],
    },
]


# ---------- 수집 ----------
def google_news(query, lang="en"):
    """Google News RSS로 최근 7일 뉴스 검색 (키 불필요)."""
    if lang == "ko":
        base = "hl=ko&gl=KR&ceid=KR:ko"
    else:
        base = "hl=en-US&gl=US&ceid=US:en"
    url = f"https://news.google.com/rss/search?q={quote(query)}+when:7d&{base}"
    try:
        feed = feedparser.parse(url)
    except Exception as e:
        print(f"뉴스 검색 오류({query}): {e}")
        return []

    items = []
    for e in feed.entries[:NEWS_PER_QUERY]:
        source = ""
        if "source" in e and hasattr(e.source, "get"):
            source = e.source.get("title", "")
        snippet = re.sub(r"<[^>]+>", "", e.get("summary", "")).strip()
        items.append({
            "title": e.get("title", "").strip(),
            "link": e.get("link", ""),
            "source": source,
            "snippet": snippet[:300],
        })
    return items


def pubmed_recent(term):
    """최근 8일 관련 임상·논문 (제목+초록 일부)."""
    common = {"tool": "topics-digest", "email": NCBI_EMAIL}
    try:
        r = requests.get(f"{EUTILS}/esearch.fcgi", params={
            **common, "db": "pubmed",
            "term": f"({term}) AND humans[MeSH Terms] AND English[Language]",
            "retmax": 6, "retmode": "json",
            "datetype": "pdat", "reldate": 8, "sort": "date",
        }, timeout=30)
        r.raise_for_status()
        ids = r.json()["esearchresult"]["idlist"]
        if not ids:
            return []
        r2 = requests.get(f"{EUTILS}/efetch.fcgi", params={
            **common, "db": "pubmed", "id": ",".join(ids), "retmode": "xml",
        }, timeout=60)
        r2.raise_for_status()
        root = ET.fromstring(r2.text)

        out = []
        for art in root.findall(".//PubmedArticle"):
            pmid = art.findtext(".//PMID")
            t_el = art.find(".//ArticleTitle")
            title = "".join(t_el.itertext()).strip() if t_el is not None else "(제목 없음)"
            ab = " ".join("".join(a.itertext()) for a in art.findall(".//Abstract/AbstractText"))
            out.append({
                "title": title,
                "link": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                "source": "PubMed",
                "snippet": ab.strip()[:300],
            })
        return out
    except Exception as e:
        print(f"PubMed 오류({term}): {e}")
        return []


def collect_topic(topic, seen):
    """한 주제의 뉴스+임상을 모아 중복 제거."""
    raw = []
    for q in topic.get("news_ko", []):
        raw += google_news(q, "ko")
        time.sleep(1)
    for q in topic.get("news_en", []):
        raw += google_news(q, "en")
        time.sleep(1)
    if topic.get("pubmed"):
        raw += pubmed_recent(topic["pubmed"])
        time.sleep(1)

    uniq, local = [], set()
    for it in raw:
        key = it["link"]
        if not key or key in seen or key in local:
            continue
        local.add(key)
        uniq.append(it)
    return uniq[:MAX_ITEMS_PER_TOPIC]


# ---------- Gemini 선별·요약 ----------
def gemini_generate(prompt, json_mode=False, max_tokens=1500):
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.2},
    }
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"

    for attempt in range(5):
        r = requests.post(GEMINI_URL, params={"key": GEMINI_API_KEY},
                          json=body, timeout=60)
        if r.status_code == 429 or r.status_code >= 500:
            wait = min(5 * (2 ** attempt), 60)
            print(f"{r.status_code} 응답, {wait}초 대기 후 재시도 ({attempt + 1}/5)")
            time.sleep(wait)
            continue
        r.raise_for_status()
        data = r.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except (KeyError, IndexError):
            return None
    return None


def curate(topic_name, items):
    """관련 있는 항목만 골라 (항목, 한국어요약) 목록으로 반환."""
    if not items:
        return []
    listing = "\n".join(
        f'{i}. [{it["source"] or "출처미상"}] {it["title"]} — {it["snippet"]}'
        for i, it in enumerate(items)
    )
    prompt = (
        f'주제: "{topic_name}"\n\n'
        "아래는 최근 일주일간 수집된 뉴스·논문 후보 목록입니다. "
        "이 주제와 실제로 관련 있고 의미 있는 항목만 고르세요. "
        "광고, 쇼핑몰 판매글, 주제와 무관하거나 홍보성인 항목은 반드시 제외하세요.\n"
        "**중요: 여러 언론사가 동일한 사건·발표를 각각 보도한 경우(제목·내용이 사실상 같은 기사들)는 "
        "하나의 사건으로 보고, 그중 가장 상세하거나 신뢰도 높은 기사 1건만 대표로 고르세요. "
        "같은 내용의 중복 기사를 여러 개 고르지 마세요.**\n"
        "고른 항목마다 한국어로 1~2문장 핵심 요약을 작성하세요. "
        "같은 사건을 여러 곳이 보도했다면 요약 끝에 '(여러 매체 보도)'라고 덧붙여도 됩니다.\n"
        "아래 JSON 배열 형식으로만 답하세요. 관련 항목이 없으면 빈 배열 []을 반환하세요.\n"
        '[{"index": 번호, "summary": "한국어 요약"}]\n\n'
        f"후보 목록:\n{listing}"
    )
    raw = gemini_generate(prompt, json_mode=True)
    if not raw:
        return []
    try:
        picks = json.loads(raw)
    except json.JSONDecodeError:
        return []

    out = []
    for p in picks:
        idx = p.get("index")
        if isinstance(idx, int) and 0 <= idx < len(items):
            out.append((items[idx], p.get("summary", "").strip()))
    return out[:SLACK_PICKS_PER_TOPIC]


# ---------- Slack ----------
def post_to_slack(sections):
    kst = timezone(timedelta(hours=9))
    today = datetime.now(kst).strftime("%Y-%m-%d")
    blocks = [
        {"type": "header",
         "text": {"type": "plain_text", "text": "📰 이번 주 관심 주제 업데이트"}},
        {"type": "context",
         "elements": [{"type": "mrkdwn", "text": f"{today} (목) · 최근 7일"}]},
        {"type": "divider"},
    ]
    for name, picks in sections:
        lines = [f"*{name}*"]
        for it, summary in picks:
            src = f" _({it['source']})_" if it["source"] else ""
            lines.append(f"• <{it['link']}|{it['title']}>\n   {summary}{src}")
        blocks.append({"type": "section",
                       "text": {"type": "mrkdwn", "text": "\n".join(lines)[:2900]}})
        blocks.append({"type": "divider"})

    # Slack 한 메시지당 블록 50개 제한 → 분할 전송
    for i in range(0, len(blocks), 50):
        resp = requests.post(SLACK_WEBHOOK_URL, json={"blocks": blocks[i:i + 50]}, timeout=30)
        resp.raise_for_status()


# ---------- 메인 ----------
def main():
    seen = set(json.loads(open(SEEN_FILE).read())) if os.path.exists(SEEN_FILE) else set()

    sections, posted = [], []
    for topic in TOPICS:
        items = collect_topic(topic, seen)
        if not items:
            print(f"[{topic['name']}] 새 후보 없음")
            continue
        picks = curate(topic["name"], items)
        if not picks:
            print(f"[{topic['name']}] 선별 결과 없음")
            continue
        sections.append((topic["name"], picks))
        posted += [it["link"] for it, _ in picks]

    if sections:
        post_to_slack(sections)
        print(f"{len(sections)}개 주제 업로드 완료.")
    else:
        print("이번 주 업로드할 소식이 없습니다.")

    seen.update(posted)
    trimmed = sorted(seen)[-SEEN_LIMIT:]  # 목록 크기 제한
    with open(SEEN_FILE, "w") as f:
        json.dump(trimmed, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
