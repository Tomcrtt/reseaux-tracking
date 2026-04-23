import os
import requests
from datetime import datetime, timedelta, timezone
import anthropic

# ── Config ──────────────────────────────────────────────────────────────────
NOTION_TOKEN        = os.environ["NOTION_TOKEN"]
IG_ACCESS_TOKEN     = os.environ["IG_ACCESS_TOKEN"]
IG_USER_ID          = os.environ["IG_USER_ID"]          # ton ID numérique Instagram
ANTHROPIC_API_KEY   = os.environ["ANTHROPIC_API_KEY"]

DB_IG_VIDEO         = os.environ["DB_IG_VIDEO"]         # ID base Notion IG vidéo
DB_LINKEDIN         = os.environ["DB_LINKEDIN"]         # ID base Notion LinkedIn
DB_HOOKS            = os.environ["DB_HOOKS"]            # ID base Notion Hooks

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

def notion_create_page(db_id, properties):
    url = "https://api.notion.com/v1/pages"
    body = {"parent": {"database_id": db_id}, "properties": properties}
    r = requests.post(url, headers=NOTION_HEADERS, json=body)
    return r.json()

def prop_text(value):
    return {"rich_text": [{"text": {"content": str(value)}}]}

def prop_title(value):
    return {"title": [{"text": {"content": str(value)}}]}

def prop_number(value):
    return {"number": value}

def prop_select(value):
    return {"select": {"name": value}}

def prop_date(value):
    return {"date": {"start": value}}

# ── Claude AI ─────────────────────────────────────────────────────────────────
def generate_lesson_ig(hook, cta, views, likes, retention, theme, tof_mof_bof):
    prompt = f"""Tu es un expert en stratégie de contenu Instagram pour l'e-commerce.
Analyse ces métriques d'une vidéo Instagram et génère :
1. Une leçon retenue courte et actionnable (2-3 phrases max)
2. Une recommandation concrète pour améliorer les prochaines vidéos

Données :
- Hook utilisé : {hook or 'non renseigné'}
- CTA utilisé : {cta or 'non renseigné'}
- Vues : {views}
- Likes : {likes}
- Taux de rétention : {retention or 'non disponible'}
- Thème (Pain Point) : {theme or 'non renseigné'}
- Funnel : {tof_mof_bof or 'non renseigné'}
- Performance : {get_performance_label(views)}

Réponds en français, de façon directe et pratique. Format :
LEÇON : [ta leçon]
RECOMMANDATION : [ta recommandation]"""

    msg = claude.messages.create(
        model="claude-opus-4-5",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text

def generate_lesson_linkedin(titre, hook, impressions, likes, format_, thematique):
    prompt = f"""Tu es un expert en stratégie de contenu LinkedIn B2B.
Analyse ces métriques d'un post LinkedIn et génère :
1. Une leçon retenue courte et actionnable (2-3 phrases max)
2. Une recommandation concrète pour les prochains posts
3. Déduis la thématique parmi : Branding, Autorité, Éducation, Prospection, Storytelling
4. Déduis le format parmi : Texte long, Image, Carrousel, Vidéo

Données :
- Titre/début du post : {titre or 'non renseigné'}
- Hook : {hook or 'non renseigné'}
- Impressions : {impressions}
- Likes : {likes}
- Format actuel : {format_ or 'non renseigné'}
- Thématique actuelle : {thematique or 'non renseigné'}

Réponds en français. Format strict :
LEÇON : [ta leçon]
RECOMMANDATION : [ta recommandation]
THÉMATIQUE : [une seule valeur]
FORMAT : [une seule valeur]"""

    msg = claude.messages.create(
        model="claude-opus-4-5",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text

def parse_claude_response(text, keys):
    result = {}
    for key in keys:
        for line in text.split("\n"):
            if line.upper().startswith(key.upper() + " :") or line.upper().startswith(key.upper() + ":"):
                result[key] = line.split(":", 1)[1].strip()
                break
    return result

def extract_hook_cta_from_caption(caption):
    if not caption:
        return None, None
    prompt = f"""Voici la caption d'une vidéo Instagram :
\"\"\"{caption}\"\"\"

Extrait :
1. Le HOOK (première phrase accrocheuse, généralement au début)
2. Le CTA (call-to-action, généralement à la fin)

Réponds en français. Format strict :
HOOK : [le hook extrait]
CTA : [le cta extrait]"""

    msg = claude.messages.create(
        model="claude-opus-4-5",
        max_tokens=150,
        messages=[{"role": "user", "content": prompt}]
    )
    parsed = parse_claude_response(msg.content[0].text, ["HOOK", "CTA"])
    return parsed.get("HOOK"), parsed.get("CTA")

# ── Instagram ─────────────────────────────────────────────────────────────────
def fetch_ig_media():
    url = f"https://graph.facebook.com/v21.0/{IG_USER_ID}/media"
    params = {
        "fields": "id,caption,timestamp,media_type,permalink",
        "access_token": IG_ACCESS_TOKEN,
        "limit": 50,
    }
    r = requests.get(url, params=params)
    return r.json().get("data", [])

def fetch_ig_insights(media_id):
    url = f"https://graph.facebook.com/v21.0/{media_id}/insights"
    params = {
        "metric": "plays,likes,reach,saved",
        "access_token": IG_ACCESS_TOKEN,
    }
    r = requests.get(url, params=params)
    data = r.json().get("data", [])
    result = {}
    for item in data:
        result[item["name"]] = item["values"][0]["value"] if item.get("values") else item.get("value", 0)
    return result

def fetch_ig_retention(media_id):
    """Tente de récupérer le taux de rétention via video_retention_curve"""
    url = f"https://graph.facebook.com/v21.0/{media_id}/insights"
    params = {
        "metric": "video_retention_curve",
        "access_token": IG_ACCESS_TOKEN,
    }
    r = requests.get(url, params=params)
    data = r.json().get("data", [])
    if not data:
        return None
    values = data[0].get("values", [{}])[0].get("value", {})
    if not values:
        return None
    # Calcule rétention à 2s et 3s si disponible
    keys = sorted(values.keys())
    if len(keys) >= 3:
        r2 = round(values.get("2", values[keys[1]]) * 100)
        r3 = round(values.get("3", values[keys[2]]) * 100)
        return f"{r2}%(2s) → {r3}%(3s)"
    return None

# ── Notion IG Vidéo ───────────────────────────────────────────────────────────
def get_existing_ig_permalinks():
    pages = notion_get_all_pages(DB_IG_VIDEO)
    permalinks = set()
    for p in pages:
        props = p.get("properties", {})
        # On stocke le permalink dans le titre ou un champ dédié
        title_prop = props.get("Thème vidéo (Pain Point)", {})
        rich = title_prop.get("title", [])
        if rich:
            permalinks.add(rich[0]["text"]["content"])
    return permalinks

def process_ig_videos():
    print("📹 Traitement des vidéos Instagram...")
    media_list = fetch_ig_media()
    pages = notion_get_all_pages(DB_IG_VIDEO)

    # Map permalink → page_id existante
    existing = {}
    for p in pages:
        props = p.get("properties", {})
        permalink_prop = props.get("Lien", {}).get("url") or ""
        if permalink_prop:
            existing[permalink_prop] = p["id"]

    for media in media_list:
        if media.get("media_type") not in ["VIDEO", "REEL"]:
            continue

        timestamp = media.get("timestamp", "")
        if not timestamp or not is_older_than_24h(timestamp):
            continue

        permalink = media.get("permalink", "")
        caption = media.get("caption", "")
        media_id = media["id"]

        # Métriques
        insights = fetch_ig_insights(media_id)
        views = insights.get("plays", 0)
        likes = insights.get("likes", 0)
        retention = fetch_ig_retention(media_id)
        performance = get_performance_label(views)

        # Hook & CTA depuis caption
        hook, cta = extract_hook_cta_from_caption(caption)

        # Date de publication
        pub_date = timestamp[:10]  # YYYY-MM-DD

        if permalink in existing:
            # Mise à jour
            page_id = existing[permalink]
            page = next(p for p in pages if p["id"] == page_id)
            props = page.get("properties", {})

            # Récupère valeurs existantes
            theme = ""
            theme_prop = props.get("Thème vidéo (Pain Point)", {}).get("title", [])
            if theme_prop:
                theme = theme_prop[0]["text"]["content"]

            tof = ""
            tof_prop = props.get("TOF - MOF - BOF", {}).get("select", {})
            if tof_prop:
                tof = tof_prop.get("name", "")

            # Génère leçon
            lesson = generate_lesson_ig(hook, cta, views, likes, retention, theme, tof)
            parsed = parse_claude_response(lesson, ["LEÇON", "RECOMMANDATION"])
            lecon = parsed.get("LEÇON", lesson)
            reco = parsed.get("RECOMMANDATION", "")

            update_props = {
                "Vues": prop_number(views),
                "Likes": prop_number(likes),
                "Performance": prop_select(performance),
                "Leçon retenue": prop_text(f"{lecon}\n\n💡 {reco}"),
            }
            if hook:
                update_props["Hook utilisé"] = prop_text(hook)
            if cta:
                update_props["CTA utilisé"] = prop_text(cta)
            if retention:
                update_props["Taux de rétention %"] = prop_text(retention)

            notion_update_page(page_id, update_props)
            print(f"  ✅ Mise à jour : {permalink[:50]} | {views} vues | {performance}")

            # Met à jour le tracker hooks
            if hook:
                update_hook_tracker(hook, views)
        else:
            # Nouvelle entrée
            lesson = generate_lesson_ig(hook, cta, views, likes, retention, "", "")
            parsed = parse_claude_response(lesson, ["LEÇON", "RECOMMANDATION"])
            lecon = parsed.get("LEÇON", lesson)
            reco = parsed.get("RECOMMANDATION", "")

            new_props = {
                "Thème vidéo (Pain Point)": prop_title(caption[:100] if caption else f"Vidéo {pub_date}"),
                "Date de publication": prop_date(pub_date),
                "Vues": prop_number(views),
                "Likes": prop_number(likes),
                "Performance": prop_select(performance),
                "Leçon retenue": prop_text(f"{lecon}\n\n💡 {reco}"),
            }
            if hook:
                new_props["Hook utilisé"] = prop_text(hook)
            if cta:
                new_props["CTA utilisé"] = prop_text(cta)
            if retention:
                new_props["Taux de rétention %"] = prop_text(retention)

            notion_create_page(DB_IG_VIDEO, new_props)
            print(f"  ➕ Nouveau : {pub_date} | {views} vues | {performance}")

            if hook:
                update_hook_tracker(hook, views)

# ── Hook Tracker ──────────────────────────────────────────────────────────────
def update_hook_tracker(hook_text, views):
    pages = notion_get_all_pages(DB_HOOKS)
    existing_hook = None
    for p in pages:
        props = p.get("properties", {})
        title = props.get("Hook", {}).get("title", [])
        if title and title[0]["text"]["content"].strip().lower() == hook_text.strip().lower():
            existing_hook = p
            break

    if existing_hook:
        # Calcule nouvelle moyenne de vues
        current_impact = existing_hook["properties"].get("Impact en vue", {}).get("number") or 0
        # Simple mise à jour avec les nouvelles vues
        notion_update_page(existing_hook["id"], {
            "Use or not ?": prop_select("utilisé"),
            "Impact en vue": prop_number(max(current_impact, views)),
        })
    else:
        notion_create_page(DB_HOOKS, {
            "Hook": prop_title(hook_text),
            "Use or not ?": prop_select("utilisé"),
            "Impact en vue": prop_number(views),
        })

# ── LinkedIn ──────────────────────────────────────────────────────────────────
def fetch_linkedin_posts(li_token, person_urn):
    url = "https://api.linkedin.com/v2/ugcPosts"
    headers = {"Authorization": f"Bearer {li_token}", "X-Restli-Protocol-Version": "2.0.0"}
    params = {"q": "authors", "authors": f"List({person_urn})", "count": 50}
    r = requests.get(url, headers=headers, params=params)
    return r.json().get("elements", [])

def fetch_linkedin_stats(post_urn, li_token):
    url = "https://api.linkedin.com/v2/organizationalEntityShareStatistics"
    headers = {"Authorization": f"Bearer {li_token}"}
    params = {"q": "organizationalEntity", "organizationalEntity": post_urn}
    r = requests.get(url, headers=headers, params=params)
    data = r.json().get("elements", [{}])
    if not data:
        return 0, 0
    stats = data[0].get("totalShareStatistics", {})
    return stats.get("impressionCount", 0), stats.get("likeCount", 0)

def process_linkedin():
    li_token = os.environ.get("LINKEDIN_TOKEN")
    li_urn = os.environ.get("LINKEDIN_URN")  # urn:li:person:XXXXX

    if not li_token or not li_urn:
        print("⏭️  LinkedIn non configuré, on passe.")
        return

    print("💼 Traitement des posts LinkedIn...")
    posts = fetch_linkedin_posts(li_token, li_urn)
    pages = notion_get_all_pages(DB_LINKEDIN)

    existing = {}
    for p in pages:
        props = p.get("properties", {})
        title = props.get("Titre du post", {}).get("title", [])
        if title:
            existing[title[0]["text"]["content"]] = p["id"]

    for post in posts:
        created = post.get("created", {}).get("time", 0)
        if not created:
            continue

        created_dt = datetime.fromtimestamp(created / 1000, tz=timezone.utc)
        if (now_utc() - created_dt) < timedelta(hours=24):
            continue

        pub_date = created_dt.strftime("%Y-%m-%d")
        content = post.get("specificContent", {}).get("com.linkedin.ugc.ShareContent", {})
        text = content.get("shareCommentary", {}).get("text", "")
        titre = text[:100] if text else f"Post {pub_date}"
        hook = text.split("\n")[0][:200] if text else ""

        post_urn = post.get("id", "")
        impressions, likes = fetch_linkedin_stats(post_urn, li_token)

        # Claude analyse
        ai_response = generate_lesson_linkedin(titre, hook, impressions, likes, "", "")
        parsed = parse_claude_response(ai_response, ["LEÇON", "RECOMMANDATION", "THÉMATIQUE", "FORMAT"])

        lecon = parsed.get("LEÇON", "")
        reco = parsed.get("RECOMMANDATION", "")
        thematique = parsed.get("THÉMATIQUE", "")
        format_ = parsed.get("FORMAT", "Texte long")

        props_to_set = {
            "Date de publication": prop_date(pub_date),
            "Hook": prop_text(hook),
            "Impressions": prop_number(impressions),
            "Likes": prop_number(likes),
            "Leçon / À reproduire": prop_text(f"{lecon}\n\n💡 {reco}"),
        }
        if thematique:
            props_to_set["Thématique"] = prop_select(thematique)
        if format_:
            props_to_set["Format"] = prop_select(format_)

        if titre in existing:
            notion_update_page(existing[titre], props_to_set)
            print(f"  ✅ LinkedIn update : {titre[:50]} | {impressions} impressions")
        else:
            props_to_set["Titre du post"] = prop_title(titre)
            notion_create_page(DB_LINKEDIN, props_to_set)
            print(f"  ➕ LinkedIn nouveau : {titre[:50]} | {impressions} impressions")

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n🚀 Démarrage du tracking — {now_utc().strftime('%Y-%m-%d %H:%M UTC')}\n")
    process_ig_videos()
    process_linkedin()
    print("\n✅ Tracking terminé !")
