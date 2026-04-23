import os
import requests
from datetime import datetime, timedelta, timezone
import anthropic

# ── Config ──────────────────────────────────────────────────────────────────
NOTION_TOKEN        = os.environ["NOTION_TOKEN"]
IG_ACCESS_TOKEN     = os.environ["IG_ACCESS_TOKEN"]
IG_USER_ID          = os.environ["IG_USER_ID"]
ANTHROPIC_API_KEY   = os.environ["ANTHROPIC_API_KEY"]
IG_APP_ID           = os.environ.get("IG_APP_ID", "")
IG_APP_SECRET       = os.environ.get("IG_APP_SECRET", "")

DB_IG_VIDEO         = os.environ["DB_IG_VIDEO"]
DB_LINKEDIN         = os.environ["DB_LINKEDIN"]
DB_HOOKS            = os.environ["DB_HOOKS"]
DB_SUGGESTIONS      = os.environ["DB_SUGGESTIONS"]

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ── Helpers ──────────────────────────────────────────────────────────────────
def now_utc():
    return datetime.now(timezone.utc)

def is_older_than_24h(timestamp_str):
    dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
    return (now_utc() - dt) > timedelta(hours=24)

def is_monday():
    return now_utc().weekday() == 0

def get_performance_label(views):
    if views is None:
        return "En cours"
    if views >= 2000:
        return "Winner"
    elif views >= 1000:
        return "Correcte"
    else:
        return "Flop"

def notion_get_all_pages(db_id):
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    pages, cursor = [], None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        r = requests.post(url, headers=NOTION_HEADERS, json=body)
        data = r.json()
        pages.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return pages

def notion_update_page(page_id, properties):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    r = requests.patch(url, headers=NOTION_HEADERS, json={"properties": properties})
    return r.json()

def notion_create_page(db_id, properties, children=None):
    url = "https://api.notion.com/v1/pages"
    body = {"parent": {"database_id": db_id}, "properties": properties}
    if children:
        body["children"] = children
    r = requests.post(url, headers=NOTION_HEADERS, json=body)
    return r.json()

def prop_text(value):
    return {"rich_text": [{"text": {"content": str(value)[:2000]}}]}

def prop_title(value):
    return {"title": [{"text": {"content": str(value)[:2000]}}]}

def prop_number(value):
    return {"number": value}

def prop_select(value):
    return {"select": {"name": value}}

def prop_date(value):
    return {"date": {"start": value}}

def make_text_block(content):
    return {
        "object": "block", "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": str(content)[:2000]}}]}
    }

def make_heading_block(content, level=2):
    htype = f"heading_{level}"
    return {
        "object": "block", "type": htype,
        htype: {"rich_text": [{"type": "text", "text": {"content": str(content)}}]}
    }

def make_divider_block():
    return {"object": "block", "type": "divider", "divider": {}}

def parse_claude_response(text, keys):
    result = {}
    for key in keys:
        for line in text.split("\n"):
            if line.upper().startswith(key.upper() + " :") or line.upper().startswith(key.upper() + ":"):
                result[key] = line.split(":", 1)[1].strip()
                break
    return result

# ── Token Instagram auto-refresh ──────────────────────────────────────────────
def refresh_ig_token():
    url = "https://graph.instagram.com/refresh_access_token"
    params = {"grant_type": "ig_refresh_token", "access_token": IG_ACCESS_TOKEN}
    r = requests.get(url, params=params)
    data = r.json()
    if "access_token" in data:
        days = data.get("expires_in", 0) // 86400
        print(f"✅ Token Instagram rafraîchi — expire dans {days} jours")
        update_railway_token(data["access_token"])
    else:
        print(f"⚠️  Refresh token échoué : {data}")

def update_railway_token(new_token):
    railway_token = os.environ.get("RAILWAY_API_TOKEN")
    service_id = os.environ.get("RAILWAY_SERVICE_ID")
    env_id = os.environ.get("RAILWAY_ENV_ID")
    if not railway_token or not service_id or not env_id:
        print("ℹ️  Token rafraîchi — mets à jour IG_ACCESS_TOKEN sur Railway manuellement dans 60j")
        return
    url = "https://backboard.railway.app/graphql/v2"
    headers = {"Authorization": f"Bearer {railway_token}", "Content-Type": "application/json"}
    query = """mutation UpsertVariables($input: VariableUpsertInput!) { variableUpsert(input: $input) }"""
    variables = {"input": {"serviceId": service_id, "environmentId": env_id, "name": "IG_ACCESS_TOKEN", "value": new_token}}
    r = requests.post(url, headers=headers, json={"query": query, "variables": variables})
    if r.status_code == 200:
        print("✅ Token mis à jour automatiquement sur Railway")

# ── Claude AI ─────────────────────────────────────────────────────────────────
def extract_hook_cta_from_caption(caption):
    if not caption:
        return None, None
    prompt = f"""Caption Instagram :
\"\"\"{caption[:500]}\"\"\"
Extrait le HOOK (première phrase) et le CTA (fin).
Format :
HOOK : [hook]
CTA : [cta]"""
    msg = claude.messages.create(model="claude-opus-4-5", max_tokens=150,
                                  messages=[{"role": "user", "content": prompt}])
    parsed = parse_claude_response(msg.content[0].text, ["HOOK", "CTA"])
    return parsed.get("HOOK"), parsed.get("CTA")

def generate_lesson_ig(hook, cta, views, likes, retention, theme, tof):
    prompt = f"""Expert Instagram e-commerce. Analyse ces métriques :
- Hook : {hook or 'non renseigné'} | CTA : {cta or 'non renseigné'}
- Vues : {views} | Likes : {likes} | Rétention : {retention or 'N/A'}
- Thème : {theme or 'N/A'} | Funnel : {tof or 'N/A'} | Perf : {get_performance_label(views)}

Format :
LEÇON : [leçon courte]
RECOMMANDATION : [action concrète]"""
    msg = claude.messages.create(model="claude-opus-4-5", max_tokens=300,
                                  messages=[{"role": "user", "content": prompt}])
    return msg.content[0].text

def generate_lesson_linkedin(titre, hook, impressions, likes, format_, thematique):
    prompt = f"""Expert LinkedIn B2B. Analyse :
- Titre : {titre} | Hook : {hook or 'N/A'}
- Impressions : {impressions} | Likes : {likes}

Format :
LEÇON : [leçon]
RECOMMANDATION : [action]
THÉMATIQUE : [Branding/Autorité/Éducation/Prospection/Storytelling]
FORMAT : [Texte long/Image/Carrousel/Vidéo]"""
    msg = claude.messages.create(model="claude-opus-4-5", max_tokens=300,
                                  messages=[{"role": "user", "content": prompt}])
    return msg.content[0].text

# ── Analyse hooks ─────────────────────────────────────────────────────────────
def analyze_hooks():
    pages = notion_get_all_pages(DB_HOOKS)
    hooks_data = []
    for p in pages:
        props = p.get("properties", {})
        title = props.get("Hook", {}).get("title", [])
        hook_text = title[0]["text"]["content"] if title else ""
        impact = props.get("Impact en vue", {}).get("number") or 0
        status = props.get("Use or not ?", {}).get("select", {})
        if hook_text and status and status.get("name") == "utilisé":
            hooks_data.append({"hook": hook_text, "vues": impact})

    if len(hooks_data) < 2:
        return None

    hooks_data.sort(key=lambda x: x["vues"], reverse=True)
    summary = "\n".join([f"- \"{h['hook']}\" → {h['vues']} vues" for h in hooks_data])

    prompt = f"""Expert copywriting Instagram e-commerce.
Hooks et leurs performances :
{summary}

Format :
PATTERNS GAGNANTS : [analyse]
CE QUI NE MARCHE PAS : [analyse]
NOUVEAUX HOOKS À TESTER :
1. [hook]
2. [hook]
3. [hook]
4. [hook]
5. [hook]
TYPE GAGNANT : [type]"""

    msg = claude.messages.create(model="claude-opus-4-5", max_tokens=600,
                                  messages=[{"role": "user", "content": prompt}])
    return {"analysis": msg.content[0].text, "total": len(hooks_data)}

# ── Analyse thèmes ────────────────────────────────────────────────────────────
def analyze_themes():
    pages = notion_get_all_pages(DB_IG_VIDEO)
    themes_data = {}
    for p in pages:
        props = p.get("properties", {})
        title = props.get("Thème vidéo (Pain Point)", {}).get("title", [])
        theme = title[0]["text"]["content"] if title else ""
        views = props.get("Vues", {}).get("number") or 0
        tof_prop = props.get("TOF - MOF - BOF", {}).get("select", {})
        tof = tof_prop.get("name", "") if tof_prop else ""
        perf_prop = props.get("Performance", {}).get("select", {})
        perf = perf_prop.get("name", "") if perf_prop else ""

        if theme and views > 0:
            if theme not in themes_data:
                themes_data[theme] = {"total": 0, "count": 0, "tof": tof, "winners": 0}
            themes_data[theme]["total"] += views
            themes_data[theme]["count"] += 1
            if perf == "Winner":
                themes_data[theme]["winners"] += 1

    if len(themes_data) < 2:
        return None

    themes_list = [{"theme": t, "avg": d["total"] // d["count"], "count": d["count"],
                    "winners": d["winners"], "tof": d["tof"]} for t, d in themes_data.items()]
    themes_list.sort(key=lambda x: x["avg"], reverse=True)
    summary = "\n".join([f"- \"{t['theme']}\" ({t['tof']}) → {t['avg']} vues moy. | {t['winners']} Winners"
                         for t in themes_list])

    prompt = f"""Expert stratégie contenu Instagram e-commerce.
Thèmes et performances :
{summary}

Format :
THÈMES GAGNANTS : [analyse]
THÈMES À ÉVITER : [analyse]
NOUVEAUX ANGLES :
1. [thème]
2. [thème]
3. [thème]
RÉPARTITION OPTIMALE : [recommandation TOF/MOF/BOF]"""

    msg = claude.messages.create(model="claude-opus-4-5", max_tokens=500,
                                  messages=[{"role": "user", "content": prompt}])
    return {"analysis": msg.content[0].text, "total": len(themes_list)}

# ── Suggestions quotidiennes ──────────────────────────────────────────────────
def generate_daily_suggestions():
    print("💡 Génération des suggestions...")
    hooks_analysis = analyze_hooks()
    themes_analysis = analyze_themes()

    if not hooks_analysis and not themes_analysis:
        print("  ℹ️  Pas assez de données pour les suggestions")
        return

    today_str = now_utc().strftime("%d/%m/%Y")
    children = []

    if hooks_analysis:
        children += [
            make_heading_block("🪝 Analyse & suggestions hooks", 2),
            make_text_block(f"Basé sur {hooks_analysis['total']} hooks analysés"),
            make_text_block(hooks_analysis["analysis"]),
            make_divider_block(),
        ]
    if themes_analysis:
        children += [
            make_heading_block("🎯 Analyse & suggestions thèmes", 2),
            make_text_block(f"Basé sur {themes_analysis['total']} thèmes analysés"),
            make_text_block(themes_analysis["analysis"]),
        ]

    notion_create_page(DB_SUGGESTIONS, {
        "Titre": prop_title(f"Suggestions du {today_str}"),
        "Date": prop_date(now_utc().strftime("%Y-%m-%d")),
        "Date de l'analyse": prop_date(now_utc().strftime("%Y-%m-%d")),
        "Type": prop_select("Suggestions quotidiennes"),
    }, children)
    print(f"  ✅ Suggestions créées pour le {today_str}")

# ── Rapport hebdomadaire ──────────────────────────────────────────────────────
def generate_weekly_report():
    print("📊 Génération du rapport hebdomadaire...")
    pages = notion_get_all_pages(DB_IG_VIDEO)
    week_ago = now_utc() - timedelta(days=7)

    week_videos = []
    for p in pages:
        props = p.get("properties", {})
        date_prop = props.get("Date de publication", {}).get("date", {})
        if not date_prop:
            continue
        try:
            pub_date = datetime.fromisoformat(date_prop.get("start", ""))
            if pub_date.tzinfo is None:
                pub_date = pub_date.replace(tzinfo=timezone.utc)
            if pub_date >= week_ago:
                views = props.get("Vues", {}).get("number") or 0
                likes = props.get("Likes", {}).get("number") or 0
                perf_prop = props.get("Performance", {}).get("select", {})
                week_videos.append({"views": views, "likes": likes,
                                    "perf": perf_prop.get("name", "") if perf_prop else ""})
        except:
            continue

    total_views = sum(v["views"] for v in week_videos)
    total_likes = sum(v["likes"] for v in week_videos)
    winners = sum(1 for v in week_videos if v["perf"] == "Winner")
    flops = sum(1 for v in week_videos if v["perf"] == "Flop")

    prompt = f"""Coach stratégie contenu Instagram e-commerce. Stats semaine :
- Vidéos : {len(week_videos)} | Vues : {total_views} | Likes : {total_likes}
- Winners : {winners} | Flops : {flops}

Format :
BILAN SEMAINE : [2-3 phrases]
POINT FORT : [1 point]
POINT À AMÉLIORER : [1 point]
OBJECTIF SEMAINE PROCHAINE : [1 objectif concret]"""

    msg = claude.messages.create(model="claude-opus-4-5", max_tokens=400,
                                  messages=[{"role": "user", "content": prompt}])
    parsed = parse_claude_response(msg.content[0].text,
                                   ["BILAN SEMAINE", "POINT FORT", "POINT À AMÉLIORER", "OBJECTIF SEMAINE PROCHAINE"])

    hooks_analysis = analyze_hooks()
    themes_analysis = analyze_themes()
    week_str = now_utc().strftime("%d/%m/%Y")

    children = [
        make_heading_block("📈 Stats de la semaine", 2),
        make_text_block(f"Vidéos : {len(week_videos)} | Vues : {total_views:,} | Likes : {total_likes:,}"),
        make_text_block(f"Winners : {winners} | Flops : {flops}"),
        make_divider_block(),
        make_heading_block("🧠 Analyse", 2),
        make_text_block(parsed.get("BILAN SEMAINE", "")),
        make_text_block(f"✅ {parsed.get('POINT FORT', '')}"),
        make_text_block(f"⚠️ {parsed.get('POINT À AMÉLIORER', '')}"),
        make_text_block(f"🎯 {parsed.get('OBJECTIF SEMAINE PROCHAINE', '')}"),
        make_divider_block(),
    ]
    if hooks_analysis:
        children += [make_heading_block("🪝 Hooks", 2), make_text_block(hooks_analysis["analysis"]), make_divider_block()]
    if themes_analysis:
        children += [make_heading_block("🎯 Thèmes", 2), make_text_block(themes_analysis["analysis"])]

    notion_create_page(DB_SUGGESTIONS, {
        "Titre": prop_title(f"Rapport semaine du {week_str}"),
        "Date": prop_date(now_utc().strftime("%Y-%m-%d")),
        "Date de l'analyse": prop_date(now_utc().strftime("%Y-%m-%d")),
        "Type": prop_select("Rapport hebdomadaire"),
    }, children)
    print(f"  ✅ Rapport hebdomadaire créé")

# ── Instagram ─────────────────────────────────────────────────────────────────
def fetch_ig_media():
    url = f"https://graph.facebook.com/v21.0/{IG_USER_ID}/media"
    params = {"fields": "id,caption,timestamp,media_type,permalink",
               "access_token": IG_ACCESS_TOKEN, "limit": 50}
    return requests.get(url, params=params).json().get("data", [])

def fetch_ig_insights(media_id):
    url = f"https://graph.facebook.com/v21.0/{media_id}/insights"
    params = {"metric": "plays,likes,reach,saved", "access_token": IG_ACCESS_TOKEN}
    data = requests.get(url, params=params).json().get("data", [])
    result = {}
    for item in data:
        result[item["name"]] = item["values"][0]["value"] if item.get("values") else item.get("value", 0)
    return result

def fetch_ig_retention(media_id):
    url = f"https://graph.facebook.com/v21.0/{media_id}/insights"
    params = {"metric": "video_retention_curve", "access_token": IG_ACCESS_TOKEN}
    data = requests.get(url, params=params).json().get("data", [])
    if not data:
        return None
    values = data[0].get("values", [{}])[0].get("value", {})
    if not values:
        return None
    keys = sorted(values.keys())
    if len(keys) >= 3:
        r2 = round(values.get("2", values[keys[1]]) * 100)
        r3 = round(values.get("3", values[keys[2]]) * 100)
        return f"{r2}%(2s) → {r3}%(3s)"
    return None

def process_ig_videos():
    print("📹 Traitement des vidéos Instagram...")
    media_list = fetch_ig_media()
    pages = notion_get_all_pages(DB_IG_VIDEO)

    existing = {}
    for p in pages:
        url_prop = p.get("properties", {}).get("Lien", {}).get("url") or ""
        if url_prop:
            existing[url_prop] = p["id"]

    for media in media_list:
        if media.get("media_type") not in ["VIDEO", "REEL"]:
            continue
        timestamp = media.get("timestamp", "")
        if not timestamp or not is_older_than_24h(timestamp):
            continue

        permalink = media.get("permalink", "")
        caption = media.get("caption", "")
        media_id = media["id"]
        insights = fetch_ig_insights(media_id)
        views = insights.get("plays", 0)
        likes = insights.get("likes", 0)
        retention = fetch_ig_retention(media_id)
        performance = get_performance_label(views)
        hook, cta = extract_hook_cta_from_caption(caption)
        pub_date = timestamp[:10]

        if permalink in existing:
            page_id = existing[permalink]
            page = next(p for p in pages if p["id"] == page_id)
            props = page.get("properties", {})
            theme_prop = props.get("Thème vidéo (Pain Point)", {}).get("title", [])
            theme = theme_prop[0]["text"]["content"] if theme_prop else ""
            tof_prop = props.get("TOF - MOF - BOF", {}).get("select", {})
            tof = tof_prop.get("name", "") if tof_prop else ""

            lesson = generate_lesson_ig(hook, cta, views, likes, retention, theme, tof)
            parsed = parse_claude_response(lesson, ["LEÇON", "RECOMMANDATION"])

            update_props = {
                "Vues": prop_number(views),
                "Likes": prop_number(likes),
                "Performance": prop_select(performance),
                "Leçon retenue": prop_text(f"{parsed.get('LEÇON', '')}\n\n💡 {parsed.get('RECOMMANDATION', '')}"),
            }
            if hook: update_props["Hook utilisé"] = prop_text(hook)
            if cta: update_props["CTA utilisé"] = prop_text(cta)
            if retention: update_props["Taux de rétention %"] = prop_text(retention)
            notion_update_page(page_id, update_props)
            print(f"  ✅ Update : {permalink[:50]} | {views} vues | {performance}")
        else:
            lesson = generate_lesson_ig(hook, cta, views, likes, retention, "", "")
            parsed = parse_claude_response(lesson, ["LEÇON", "RECOMMANDATION"])

            new_props = {
                "Thème vidéo (Pain Point)": prop_title(caption[:100] if caption else f"Vidéo {pub_date}"),
                "Date de publication": prop_date(pub_date),
                "Vues": prop_number(views),
                "Likes": prop_number(likes),
                "Performance": prop_select(performance),
                "Leçon retenue": prop_text(f"{parsed.get('LEÇON', '')}\n\n💡 {parsed.get('RECOMMANDATION', '')}"),
            }
            if hook: new_props["Hook utilisé"] = prop_text(hook)
            if cta: new_props["CTA utilisé"] = prop_text(cta)
            if retention: new_props["Taux de rétention %"] = prop_text(retention)
            notion_create_page(DB_IG_VIDEO, new_props)
            print(f"  ➕ Nouveau : {pub_date} | {views} vues | {performance}")

        if hook:
            update_hook_tracker(hook, views)

def update_hook_tracker(hook_text, views):
    today = now_utc().strftime("%Y-%m-%d")
    pages = notion_get_all_pages(DB_HOOKS)
    for p in pages:
        title = p.get("properties", {}).get("Hook", {}).get("title", [])
        if title and title[0]["text"]["content"].strip().lower() == hook_text.strip().lower():
            current = p["properties"].get("Impact en vue", {}).get("number") or 0
            notion_update_page(p["id"], {
                "Use or not ?": prop_select("utilisé"),
                "Impact en vue": prop_number(max(current, views)),
                "Date de l'utilisation du hook": prop_date(today),
            })
            return
    notion_create_page(DB_HOOKS, {
        "Hook": prop_title(hook_text),
        "Use or not ?": prop_select("utilisé"),
        "Impact en vue": prop_number(views),
        "Date de l'utilisation du hook": prop_date(today),
    })

# ── LinkedIn ──────────────────────────────────────────────────────────────────
def process_linkedin():
    li_token = os.environ.get("LINKEDIN_TOKEN")
    li_urn = os.environ.get("LINKEDIN_URN")
    if not li_token or not li_urn:
        print("⏭️  LinkedIn non configuré.")
        return
    print("💼 Traitement LinkedIn...")
    # (même logique que avant)

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n🚀 Démarrage — {now_utc().strftime('%Y-%m-%d %H:%M UTC')}\n")
    refresh_ig_token()
    process_ig_videos()
    process_linkedin()
    generate_daily_suggestions()
    if is_monday():
        generate_weekly_report()
    print("\n✅ Tracking terminé !")
    
