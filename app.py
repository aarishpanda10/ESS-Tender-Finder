
from __future__ import annotations

import base64
import io
import re
import urllib.parse
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, Iterable

import fitz
import requests
import streamlit as st
import streamlit.components.v1 as components
from bs4 import BeautifulSoup
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import pytesseract
from pytesseract import Output


APP_NAME = "ESS Tender Intelligence"
COMPANY = "Executive Security Services Pvt Ltd"
COMPANY_URL = "https://executivesecurity.in/"
LOGO_URL = "https://executivesecurity.in/uploads/logo.png"

TENDER_TERMS = [
    "TENDER", "CORRIGENDUM", "NIT", "NOTICE INVITING TENDER",
    "E-TENDER", "E TENDER", "EXPRESSION OF INTEREST", "EOI",
    "RFP", "REQUEST FOR PROPOSAL", "RFQ", "REQUEST FOR QUOTATION",
    "INVITATION FOR BIDS", "INVITATION OF BIDS", "IFB", "ADDENDUM",
    "TENDER CALL NOTICE", "AWARD OF CONTRACT", "SELECTION OF AGENCY",
    "EMPANELMENT", "BID DOCUMENT",
]

SERVICE_TERMS = [
    "SECURITY", "HOUSEKEEPING", "HOUSE KEEPING", "MANPOWER",
    "WATCHMAN", "WATCHMEN", "GUARD", "GUARDS", "OUTSOURCING",
    "OUTSOURCED", "FACILITY MANAGEMENT", "SECURITY GUARD",
    "SECURITY PERSONNEL", "CFMS", "UPKEEPING", "CLEANING",
    "MAINTENANCE", "SANITATION", "SWEEPER", "PEON", "PARAMEDIC",
    "NURSING", "TECHNO-MANAGERIAL", "SUPPORT STAFF",
    "MULTI TASKING STAFF", "MTS", "DATA ENTRY OPERATOR", "DEO",
    "ATTENDANT", "DRIVER", "WARD BOY", "SERVICE PROVIDER",
]

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Referer": "https://www.google.com/",
}

SAMAJA_EDITIONS = {
    "Bhubaneswar": "bh", "Cuttack": "ct", "Sambalpur": "sa",
    "Balasore": "ba", "Berhampur": "br", "Rourkela": "ro",
    "Angul-Dhenkanal": "an", "Koraput": "ko",
}

SAMBAD_EDITIONS = {
    "Bhubaneswar": "hr",
}

DHARITRI_EDITIONS = {
    "Bhubaneswar": (4, "bhubaneswar"),
    "Sambalpur": (5, "sambalpur"),
    "Berhampur": (6, "berhampur"),
    "Angul-Dhenkanal": (7, "angul-dhenkanal"),
    "Balasore": (8, "balasore"),
    "Rayagada": (9, "rayagada"),
    "Upakula Odisha": (10, "upakula-odisha"),
}


@dataclass
class PageSource:
    paper: str
    edition: str
    page: int
    url: str


@dataclass
class ScanResult:
    paper: str
    edition: str
    page: int
    image: Image.Image
    crop: Image.Image | None
    tender_hits: list[str]
    service_hits: list[str]
    confidence: float
    source_url: str = ""

    @property
    def matched(self) -> bool:
        return bool(self.tender_hits and self.service_hits)


def inject_css() -> None:
    st.markdown(
        """
        <style>
        :root {
            --navy: #071b35;
            --blue: #123c6a;
            --gold: #f5b700;
            --red: #d81b32;
            --paper: rgba(255,255,255,.94);
        }
        .stApp {
            background:
              radial-gradient(circle at 10% 20%, rgba(245,183,0,.12), transparent 26%),
              radial-gradient(circle at 88% 12%, rgba(26,105,173,.14), transparent 28%),
              linear-gradient(135deg, #f7f9fc 0%, #eef3f8 48%, #f9fbfd 100%);
        }
        .stApp:before {
            content: "";
            position: fixed;
            inset: 0;
            pointer-events: none;
            opacity: .20;
            background-image:
              linear-gradient(115deg, transparent 0 45%, rgba(7,27,53,.04) 46% 47%, transparent 48% 100%);
            background-size: 75px 75px;
            animation: drift 18s linear infinite;
        }
        @keyframes drift { from {background-position:0 0;} to {background-position:300px 0;} }

        .hero {
            position: relative;
            overflow: hidden;
            border-radius: 26px;
            padding: 24px 26px;
            background: linear-gradient(125deg, #061b37 0%, #113b69 70%, #174f84 100%);
            color: white;
            box-shadow: 0 18px 45px rgba(5,26,53,.22);
            border: 1px solid rgba(255,255,255,.12);
            margin-bottom: 15px;
        }
        .hero:after {
            content:"";
            position:absolute;
            width:260px;height:260px;
            border-radius:50%;
            right:-80px;top:-110px;
            border:35px solid rgba(245,183,0,.16);
        }
        .hero-grid {display:flex;align-items:center;gap:18px;position:relative;z-index:2;}
        .hero-logo {
            width:78px;height:78px;object-fit:contain;padding:7px;
            background:white;border-radius:18px;
            box-shadow:0 10px 25px rgba(0,0,0,.22);
        }
        .hero h1 {margin:0;font-size:2rem;line-height:1.05;letter-spacing:-.03em;}
        .hero p {margin:7px 0 0;color:#dbe8f6;}
        .gold {color:#ffc400;font-weight:800;letter-spacing:.07em;font-size:.78rem;}
        .metric-card {
            background:rgba(255,255,255,.95);
            border:1px solid rgba(12,49,86,.10);
            border-radius:18px;padding:16px;
            box-shadow:0 9px 24px rgba(15,45,75,.08);
        }
        div[data-testid="stButton"] button[kind="primary"] {
            background:linear-gradient(100deg,#082c55,#174f84)!important;
            border:none!important;border-radius:14px!important;
            min-height:49px;font-weight:750;
            box-shadow:0 8px 22px rgba(8,44,85,.20);
        }
        div[data-testid="stDownloadButton"] button {border-radius:12px!important;}
        .result-title {font-size:1.08rem;font-weight:800;color:#09294c;}
        .chip {
            display:inline-block;padding:4px 9px;margin:3px 4px 3px 0;
            border-radius:999px;background:#eef4fb;color:#123c6a;
            border:1px solid #d7e5f4;font-size:.76rem;font-weight:700;
        }
        .warnbox {
            padding:12px 14px;border-radius:14px;
            background:#fff8dc;border:1px solid #f1dc87;color:#5d4a00;
        }
        .small-note {font-size:.83rem;color:#657587;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def hero() -> None:
    st.markdown(
        f"""
        <div class="hero">
          <div class="hero-grid">
            <img class="hero-logo" src="{LOGO_URL}" alt="ESS logo">
            <div>
              <div class="gold">AUTOMATED E-PAPER SCREENING</div>
              <h1>{APP_NAME}</h1>
              <p>{COMPANY} · Security, manpower and facility-service opportunities</p>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update(REQUEST_HEADERS)
    return s


def samaja_sources(d: date, edition: str, max_pages: int) -> list[PageSource]:
    code = SAMAJA_EDITIONS[edition]
    ds = d.strftime("%d%m%Y")
    return [
        PageSource(
            "Samaja", edition, page,
            f"https://www.samajaepaper.in/epaperimages/{ds}/{ds}-md-{code}-{page}.jpg"
        )
        for page in range(1, max_pages + 1)
    ]


def sambad_sources(d: date, edition: str, max_pages: int) -> list[PageSource]:
    code = SAMBAD_EDITIONS[edition]
    ds = d.strftime("%d%m%Y")
    return [
        PageSource(
            "Sambad", edition, page,
            f"https://sambadepaper.com/epaperimages/{ds}/{ds}-md-{code}-{page}ss.jpg"
        )
        for page in range(1, max_pages + 1)
    ]


def _find_dharitri_edition_id(
    d: date, city_id: int, slug: str, s: requests.Session
) -> str | None:
    for listing_page in range(1, 8):
        url = f"https://dharitriepaper.in/category/{city_id}/{slug}"
        if listing_page > 1:
            url += f"/page/{listing_page}"
        try:
            r = s.get(url, timeout=18)
        except requests.RequestException:
            continue
        if r.status_code != 200:
            continue

        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=re.compile(r"/edition/\d+/")):
            href = a.get("href", "")
            match_id = re.search(r"/edition/(\d+)/", href)
            if not match_id:
                continue
            node = a
            card_text = ""
            for _ in range(6):
                card_text = node.get_text(" ", strip=True)
                if re.search(r"[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}", card_text):
                    break
                if node.parent is None:
                    break
                node = node.parent
            dm = re.search(r"[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}", card_text)
            if not dm:
                continue
            try:
                found_date = datetime.strptime(dm.group(0), "%b %d, %Y").date()
            except ValueError:
                continue
            if found_date == d:
                return match_id.group(1)
    return None


def dharitri_sources(d: date, edition: str, max_pages: int) -> list[PageSource]:
    city_id, slug = DHARITRI_EDITIONS[edition]
    s = session()
    edition_id = _find_dharitri_edition_id(d, city_id, slug, s)
    if not edition_id:
        return []

    url = f"https://dharitriepaper.in/edition/{edition_id}/{slug}"
    try:
        r = s.get(url, timeout=20)
        r.raise_for_status()
    except requests.RequestException:
        return []

    candidates: list[str] = []
    patterns = [
        r'imageprocessor\?image=([^&"\']+)',
        r'(https?://[^"\']+\.(?:jpg|jpeg|png|webp))',
    ]
    for pattern in patterns:
        for raw in re.findall(pattern, r.text, flags=re.I):
            actual = urllib.parse.unquote(raw).replace("&amp;", "&")
            if actual.startswith("//"):
                actual = "https:" + actual
            if actual not in candidates:
                candidates.append(actual)

    return [
        PageSource("Dharitri", edition, i, u)
        for i, u in enumerate(candidates[:max_pages], 1)
    ]


def get_sources(paper: str, d: date, edition: str, max_pages: int) -> list[PageSource]:
    if paper == "Samaja" and edition in SAMAJA_EDITIONS:
        return samaja_sources(d, edition, max_pages)
    if paper == "Sambad" and edition in SAMBAD_EDITIONS:
        return sambad_sources(d, edition, max_pages)
    if paper == "Dharitri" and edition in DHARITRI_EDITIONS:
        return dharitri_sources(d, edition, max_pages)
    return []


def normalize_for_ocr(img: Image.Image, max_width: int = 1050) -> tuple[Image.Image, float]:
    rgb = img.convert("RGB")
    scale = 1.0
    if rgb.width > max_width:
        scale = max_width / rgb.width
        rgb = rgb.resize((max_width, int(rgb.height * scale)), Image.Resampling.LANCZOS)
    gray = ImageOps.grayscale(rgb)
    gray = ImageEnhance.Contrast(gray).enhance(1.45)
    gray = gray.filter(ImageFilter.SHARPEN)
    return gray, scale


def term_hits(text: str, terms: Iterable[str]) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text.upper())
    return sorted({t for t in terms if t in cleaned})


def block_crop(
    original: Image.Image,
    data: dict,
    tender_terms: list[str],
    service_terms: list[str],
    scale: float,
) -> Image.Image:
    rows = []
    n = len(data.get("text", []))
    for i in range(n):
        token = (data["text"][i] or "").strip()
        if not token:
            continue
        conf_raw = str(data.get("conf", ["-1"] * n)[i])
        try:
            conf = float(conf_raw)
        except ValueError:
            conf = -1
        if conf < 18:
            continue
        rows.append({
            "text": token.upper(),
            "left": int(data["left"][i]),
            "top": int(data["top"][i]),
            "width": int(data["width"][i]),
            "height": int(data["height"][i]),
            "block": int(data.get("block_num", [0] * n)[i]),
            "par": int(data.get("par_num", [0] * n)[i]),
        })

    if not rows:
        return original

    target_words = {
        w for phrase in (tender_terms + service_terms)
        for w in re.findall(r"[A-Z0-9-]{3,}", phrase.upper())
    }
    selected = [r for r in rows if any(w in r["text"] or r["text"] in w for w in target_words)]
    if not selected:
        return original

    # Prefer a newspaper OCR block containing both kinds of vocabulary.
    grouped: dict[tuple[int, int], list[dict]] = {}
    for r in rows:
        grouped.setdefault((r["block"], r["par"]), []).append(r)

    best_group = None
    best_score = -1
    for group in grouped.values():
        text = " ".join(r["text"] for r in group)
        th = term_hits(text, tender_terms)
        sh = term_hits(text, service_terms)
        score = 5 * bool(th) + 5 * bool(sh) + min(len(th) + len(sh), 6)
        if th and sh and score > best_score:
            best_group, best_score = group, score

    use = best_group if best_group else selected
    x1 = min(r["left"] for r in use)
    y1 = min(r["top"] for r in use)
    x2 = max(r["left"] + r["width"] for r in use)
    y2 = max(r["top"] + r["height"] for r in use)

    inv = 1 / scale
    pad_x, pad_y = 90, 180
    left = max(int(x1 * inv) - pad_x, 0)
    top = max(int(y1 * inv) - pad_y, 0)
    right = min(int(x2 * inv) + pad_x, original.width)
    bottom = min(int(y2 * inv) + pad_y, original.height)

    # Keep enough context for address, dates and eligibility.
    if right - left < original.width * 0.35:
        extra = int(original.width * 0.12)
        left, right = max(0, left - extra), min(original.width, right + extra)
    if bottom - top < original.height * 0.18:
        extra = int(original.height * 0.10)
        top, bottom = max(0, top - extra), min(original.height, bottom + extra)

    return original.crop((left, top, right, bottom))


def scan_image(
    image: Image.Image,
    paper: str,
    edition: str,
    page: int,
    source_url: str = "",
) -> ScanResult:
    prepared, scale = normalize_for_ocr(image)
    cfg = "--oem 1 --psm 11"
    text = pytesseract.image_to_string(prepared, lang="eng", config=cfg)
    tender = term_hits(text, TENDER_TERMS)
    service = term_hits(text, SERVICE_TERMS)

    crop = None
    confidence = 0.0
    if tender and service:
        data = pytesseract.image_to_data(
            prepared, lang="eng", config=cfg, output_type=Output.DICT
        )
        confs = []
        for value in data.get("conf", []):
            try:
                v = float(value)
                if v >= 0:
                    confs.append(v)
            except (TypeError, ValueError):
                pass
        confidence = sum(confs) / len(confs) if confs else 0.0
        crop = block_crop(image, data, tender, service, scale)

    return ScanResult(
        paper=paper, edition=edition, page=page, image=image,
        crop=crop, tender_hits=tender, service_hits=service,
        confidence=confidence, source_url=source_url,
    )


def download_and_scan(src: PageSource) -> ScanResult | None:
    s = session()
    try:
        r = s.get(src.url, timeout=25)
        if r.status_code != 200 or len(r.content) < 6000:
            return None
        content_type = r.headers.get("content-type", "")
        if "image" not in content_type and not src.url.lower().endswith(
            (".jpg", ".jpeg", ".png", ".webp")
        ):
            return None
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        if img.width < 500 or img.height < 700:
            return None
        return scan_image(img, src.paper, src.edition, src.page, src.url)
    except Exception:
        return None


def run_online_scan(
    papers: list[str],
    d: date,
    edition: str,
    max_pages: int,
    workers: int,
    progress: Callable[[float, str], None],
) -> tuple[list[ScanResult], list[str]]:
    sources: list[PageSource] = []
    notes: list[str] = []

    for paper in papers:
        try:
            found = get_sources(paper, d, edition, max_pages)
        except Exception as exc:
            found = []
            notes.append(f"{paper}: source lookup failed ({type(exc).__name__}).")
        if not found:
            notes.append(f"{paper}: no page links found for {edition} on {d}.")
        sources.extend(found)

    if not sources:
        return [], notes

    results: list[ScanResult] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_map = {pool.submit(download_and_scan, src): src for src in sources}
        total = len(future_map)
        for done, future in enumerate(as_completed(future_map), 1):
            src = future_map[future]
            try:
                result = future.result()
                if result:
                    results.append(result)
            except Exception:
                notes.append(f"{src.paper} page {src.page}: could not process.")
            progress(done / total, f"Reading {done}/{total} candidate pages…")

    results.sort(key=lambda x: (x.paper, x.page))
    return results, notes


def file_to_images(uploaded_file) -> list[Image.Image]:
    payload = uploaded_file.getvalue()
    name = uploaded_file.name.lower()
    if name.endswith(".pdf"):
        doc = fitz.open(stream=payload, filetype="pdf")
        pages = []
        for p in doc:
            pix = p.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), alpha=False)
            pages.append(Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB"))
        return pages
    return [Image.open(io.BytesIO(payload)).convert("RGB")]


def image_bytes(img: Image.Image, fmt: str = "JPEG") -> bytes:
    b = io.BytesIO()
    if fmt == "JPEG":
        img.convert("RGB").save(b, format="JPEG", quality=92, optimize=True)
    else:
        img.save(b, format=fmt)
    return b.getvalue()


def results_zip(matches: list[ScanResult], d: date) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for r in matches:
            filename = f"{d}_{r.paper}_{r.edition}_page-{r.page}.jpg".replace(" ", "_")
            z.writestr(filename, image_bytes(r.crop or r.image))
        summary = ["ESS Tender Intelligence", f"Date: {d}", ""]
        for r in matches:
            summary.append(
                f"{r.paper} page {r.page}: "
                f"tender={', '.join(r.tender_hits)} | "
                f"service={', '.join(r.service_hits)}"
            )
        z.writestr("scan-summary.txt", "\n".join(summary))
    return b.getvalue()


def mobile_share_button(img: Image.Image, filename: str, key: str) -> None:
    data = base64.b64encode(image_bytes(img)).decode()
    html = f"""
    <button id="share-{key}" style="
      width:100%;padding:12px 15px;border:0;border-radius:12px;
      background:#20a464;color:white;font-weight:750;cursor:pointer;">
      Share image from phone
    </button>
    <div id="msg-{key}" style="font:12px sans-serif;margin-top:5px;color:#667"></div>
    <script>
    const btn = document.getElementById("share-{key}");
    const msg = document.getElementById("msg-{key}");
    btn.onclick = async () => {{
      try {{
        const raw = atob("{data}");
        const bytes = new Uint8Array(raw.length);
        for (let i=0; i<raw.length; i++) bytes[i] = raw.charCodeAt(i);
        const file = new File([bytes], "{filename}", {{type:"image/jpeg"}});
        if (navigator.canShare && navigator.canShare({{files:[file]}})) {{
          await navigator.share({{
            title:"ESS tender cutout",
            text:"Relevant tender notice",
            files:[file]
          }});
        }} else {{
          msg.innerText = "File sharing is not supported here. Use Download, then attach it in WhatsApp.";
        }}
      }} catch (e) {{
        msg.innerText = "Sharing was cancelled or is unsupported. Use Download instead.";
      }}
    }};
    </script>
    """
    components.html(html, height=68)


def show_results(results: list[ScanResult], scan_date: date) -> None:
    matches = [r for r in results if r.matched]
    c1, c2, c3 = st.columns(3)
    c1.metric("Pages checked", len(results))
    c2.metric("Relevant pages", len(matches))
    c3.metric("Papers reached", len({r.paper for r in results}))

    if not matches:
        st.success("No page matched both a tender term and a service term.")
        st.info(
            "OCR can miss small or low-quality advertisements. Use the visual-review "
            "section below, or upload a downloaded PDF/image for a second scan."
        )
    else:
        st.download_button(
            "Download all cutouts as ZIP",
            data=results_zip(matches, scan_date),
            file_name=f"ESS_tender_cutouts_{scan_date}.zip",
            mime="application/zip",
            use_container_width=True,
        )
        st.subheader(f"{len(matches)} relevant page(s)")
        for idx, r in enumerate(matches):
            with st.container(border=True):
                st.markdown(
                    f'<div class="result-title">{r.paper} · {r.edition} · page {r.page}</div>',
                    unsafe_allow_html=True,
                )
                chips = "".join(
                    f'<span class="chip">{x}</span>'
                    for x in (r.tender_hits + r.service_hits)
                )
                st.markdown(chips, unsafe_allow_html=True)
                st.image(r.crop or r.image, use_container_width=True)
                if r.source_url:
                    st.caption(f"Source page: {r.source_url}")
                col1, col2 = st.columns(2)
                filename = f"{scan_date}_{r.paper}_page_{r.page}.jpg".replace(" ", "_")
                with col1:
                    st.download_button(
                        "Download cutout",
                        data=image_bytes(r.crop or r.image),
                        file_name=filename,
                        mime="image/jpeg",
                        key=f"download-{idx}-{r.paper}-{r.page}",
                        use_container_width=True,
                    )
                with col2:
                    mobile_share_button(
                        r.crop or r.image, filename,
                        f"{idx}-{re.sub('[^a-zA-Z0-9]', '', r.paper)}-{r.page}"
                    )
                with st.expander("Open full newspaper page"):
                    st.image(r.image, use_container_width=True)

    with st.expander(f"Visual review: all {len(results)} successfully read pages"):
        st.caption("This safety check helps catch notices that OCR may have missed.")
        cols = st.columns(4)
        for i, r in enumerate(results):
            with cols[i % 4]:
                thumb = r.image.copy()
                thumb.thumbnail((360, 470))
                st.image(
                    thumb,
                    caption=f"{'✓ ' if r.matched else ''}{r.paper} p{r.page}",
                    use_container_width=True,
                )


def online_tab() -> None:
    st.markdown("### Scan official e-paper pages")
    left, right = st.columns([1.2, 1])
    with left:
        scan_date = st.date_input("Edition date", value=date.today(), key="online-date")
        papers = st.multiselect(
            "Newspapers",
            ["Samaja", "Sambad", "Dharitri", "Prameya"],
            default=["Samaja", "Sambad", "Dharitri"],
        )
        edition = st.selectbox(
            "Edition",
            [
                "Bhubaneswar", "Cuttack", "Sambalpur", "Balasore",
                "Berhampur", "Rourkela", "Angul-Dhenkanal",
                "Koraput", "Rayagada", "Upakula Odisha",
            ],
        )
    with right:
        max_pages = st.slider("Maximum pages per paper", 6, 24, 10, help="Start with 8–10 pages on free hosting, then increase only if needed.")
        workers = st.slider("Parallel workers", 1, 4, 2, help="Two workers is the safest setting on Streamlit Community Cloud.")
        st.info(
            "Free-hosting safe mode: begin with one newspaper, 8–10 pages and 1–2 workers. "
            "Scanning several papers with 24 pages and six OCR workers can restart the app before results appear."
        )
        st.markdown(
            '<div class="warnbox"><b>Prameya:</b> its reader commonly uses tiled/interactive '
            'pages, so automatic page extraction is not enabled. Download its PDF/images and '
            'use the Upload tab.</div>',
            unsafe_allow_html=True,
        )

    if st.button("Start daily tender scan", type="primary", use_container_width=True):
        active = [p for p in papers if p != "Prameya"]
        if not active:
            st.error("Select at least one connected newspaper.")
            return
        if len(active) > 1 and max_pages > 12:
            st.warning(
                "For the first test, select one newspaper or reduce the page limit to 12. "
                "This prevents the free Streamlit server from restarting during OCR."
            )
        p = st.progress(0, text="Finding newspaper pages…")
        try:
            results, notes = run_online_scan(
                active, scan_date, edition, max_pages, workers,
                lambda frac, text: p.progress(frac, text=text),
            )
            st.session_state["online-results"] = results
            st.session_state["online-date-result"] = scan_date
            st.session_state["online-notes"] = notes
            st.session_state["last_scan_completed"] = True
        except Exception as exc:
            st.session_state["last_scan_completed"] = False
            st.session_state["online-notes"] = [
                f"Scan stopped with {type(exc).__name__}: {exc}"
            ]
            st.error(
                "The scan stopped before completion. Reduce to one newspaper, 8 pages "
                "and one worker, then try again."
            )
        finally:
            p.empty()

    if st.session_state.get("online-notes"):
        with st.expander("Connection report"):
            for note in st.session_state["online-notes"]:
                st.write("•", note)

    if "online-results" in st.session_state:
        if not st.session_state["online-results"]:
            st.error(
                "No newspaper page was successfully downloaded. Open Connection report "
                "below to see which source failed. You can still use Upload fallback."
            )
        else:
            show_results(
                st.session_state["online-results"],
                st.session_state.get("online-date-result", scan_date),
            )


def upload_tab() -> None:
    st.markdown("### Upload PDFs or page images")
    st.caption(
        "This is the reliable fallback whenever a newspaper changes its website, "
        "requires login, blocks cloud servers, or uses an interactive viewer."
    )
    files = st.file_uploader(
        "Drop e-paper PDF/JPG/PNG files here",
        type=["pdf", "jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
    )
    label = st.text_input("Newspaper/edition label", "Manual upload")
    scan_date = st.date_input("Edition date", value=date.today(), key="upload-date")

    if st.button("Scan uploaded files", type="primary", use_container_width=True):
        if not files:
            st.error("Upload at least one file.")
            return
        pages: list[tuple[str, int, Image.Image]] = []
        try:
            for f in files:
                images = file_to_images(f)
                pages.extend((f.name, i, img) for i, img in enumerate(images, 1))
        except Exception as exc:
            st.error(f"Could not open one of the files: {exc}")
            return

        bar = st.progress(0, text="Running OCR…")
        results = []
        for i, (filename, page_num, img) in enumerate(pages, 1):
            results.append(scan_image(img, label, filename, page_num))
            bar.progress(i / len(pages), text=f"Reading page {i}/{len(pages)}…")
        bar.empty()
        st.session_state["upload-results"] = results
        st.session_state["upload-date-result"] = scan_date

    if "upload-results" in st.session_state:
        show_results(
            st.session_state["upload-results"],
            st.session_state.get("upload-date-result", scan_date),
        )


def about_tab() -> None:
    st.markdown("### How the free workflow works")
    st.markdown(
        """
        1. Select the date, newspapers and edition.
        2. The app obtains available page images from the publishers' public e-paper pages.
        3. Tesseract OCR reads English text and requires at least one tender term **and**
           one security/manpower/facility-service term.
        4. It crops the most relevant notice area and creates downloadable JPG files.
        5. On a supported phone browser, **Share image from phone** opens the normal share
           sheet; choose WhatsApp and then your “You” chat.

        **Zero-cost hosting:** GitHub + Streamlit Community Cloud.  
        **No paid API:** OCR runs locally on the Streamlit server using Tesseract.
        """
    )
    st.warning(
        "Newspaper layouts and URLs can change without notice. Respect each publisher's "
        "terms, access controls and copyright. Keep cutouts for internal tender review; "
        "do not republish full newspapers."
    )
    st.markdown(
        f"Company profile used in the interface: [{COMPANY}]({COMPANY_URL}) — "
        "established in 1996 and focused on security and manpower services."
    )


def main() -> None:
    st.set_page_config(
        page_title=APP_NAME,
        page_icon="🔎",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    inject_css()
    hero()
    tab1, tab2, tab3 = st.tabs(
        ["Daily online scan", "Upload fallback", "How it works"]
    )
    with tab1:
        online_tab()
    with tab2:
        upload_tab()
    with tab3:
        about_tab()
    st.divider()
    st.markdown(
        '<div class="small-note">Internal tender-discovery assistant. '
        'Always verify dates, eligibility, EMD, deadlines and the original notice before acting.</div>',
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
