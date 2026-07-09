# 관심 주제 주간 업데이트 봇 (목요일)

관심 주제별로 최근 1주일 **뉴스·임상결과·회사 소식**을 모아,
Gemini가 관련 있는 것만 **선별·요약**한 뒤 매주 목요일 Slack에 업로드합니다.
1번 봇(건기식 논문, 월요일)과는 **별개 저장소**로 운영하세요.

## 다루는 주제 (기본값)
1. 🔥 이번 주 핫한 건강기능식품 뉴스
2. 피크노제놀 & 호팍사(Horphag)
3. 아쿠아셀 코큐텐 (Aquacelle CoQ10)
4. HN019 유산균 (B. lactis HN019)
5. 빌베리 & 루테인 (눈 건강)
6. 🆕 새로운 건강기능식품 원료

## 1번 봇과 무엇이 다른가
- **데이터 출처**: PubMed만이 아니라 **Google News RSS(키 불필요)** + PubMed를 함께 사용
- **AI 역할**: 단순 요약이 아니라 **선별 + 요약** (뉴스엔 광고·무관 기사가 섞이므로 Gemini가 걸러냄)
- **중복 방지**: 논문 ID 대신 **기사 URL**(`seen_urls.json`)로 관리

---

## 설정

### 1. 저장소 만들기
이 폴더를 **새 저장소**(1번과 다른 저장소)에 올립니다.
`.github/workflows/weekly.yml`은 파일명에 경로째 입력해 만드세요.

### 2. Secrets 등록
저장소 → Settings → Secrets and variables → Actions

| 이름 | 값 |
|------|-----|
| `GEMINI_API_KEY` | 1번에서 쓰던 것과 동일한 키 재사용 가능 |
| `SLACK_WEBHOOK_URL` | 올릴 채널의 Webhook URL |

> 별도 채널에 올리고 싶으면 Slack에서 Webhook을 새로 만들어 그 URL을 넣으세요.

### 3. 실행 권한
Settings → Actions → General → **Read and write permissions**

### 4. 테스트
Actions 탭 → *Weekly Topics Digest* → **Run workflow**

---

## 커스터마이징 (`main.py` 상단 `TOPICS`)

주제 추가·수정은 `TOPICS` 리스트만 손보면 됩니다.

```python
{
    "name": "표시할 제목",
    "news_ko": ["한글 검색어1", "한글 검색어2"],   # 국내 뉴스
    "news_en": ["English query1"],                # 해외 뉴스·회사 소식
    "pubmed": "임상 검색어",                        # (선택) 임상결과
},
```

| 항목 | 위치 | 기본값 |
|------|------|--------|
| 검색어당 뉴스 수 | `NEWS_PER_QUERY` | 6 |
| 주제당 최종 게시 수 | `SLACK_PICKS_PER_TOPIC` | 5 |
| 요약 모델 | `GEMINI_MODEL` | gemini-2.5-flash-lite |
| 실행 요일·시간 | `weekly.yml`의 cron | 목 09:00 KST |

## 팁 & 한계
- **회사 발표**(호팍사 보도자료 등)는 대부분 뉴스·업계지로 잡히지만, 100% 포착은 어렵습니다.
  더 확실히 보려면 `news_en`에 `"Horphag Research press release"` 같은 검색어를 추가하세요.
- 원료·업계 소식의 핵심 매체: **NutraIngredients, Nutraceuticals World, NutritionInsight**.
  특정 매체만 보고 싶으면 검색어에 `site:nutraingredients.com` 등을 넣어 좁힐 수 있습니다.
- "가장 핫한"은 Google News 관련도순 + 최근 7일 + Gemini 선별로 근사합니다(완벽한 랭킹 아님).
- 요약은 기사 제목·발췌 기반입니다. 중요한 건 원문 확인을 권장합니다.
