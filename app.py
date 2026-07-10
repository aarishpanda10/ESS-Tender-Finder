from __future__ import annotations

import base64
import io
import re
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from typing import Iterable

import requests
import streamlit as st
import streamlit.components.v1 as components
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import pytesseract
from pytesseract import Output

APP_NAME = "ESS Tender Finder"
COMPANY = "Executive Security Services Pvt Ltd"
LOGO_URL = "https://executivesecurity.in/uploads/logo.png"

TENDER_TERMS = [
    "TENDER", "CORRIGENDUM", "NOTICE INVITING TENDER", "E-TENDER", "E TENDER",
    "EXPRESSION OF INTEREST", "REQUEST FOR PROPOSAL", "REQUEST FOR QUOTATION",
    "INVITATION FOR BIDS", "INVITATION OF BIDS", "TENDER CALL NOTICE",
    "SELECTION OF AGENCY", "EMPANELMENT", "BID DOCUMENT", "ADDENDUM",
    "NIT", "EOI", "RFP", "RFQ", "IFB",
]
SERVICE_TERMS = [
    "SECURITY", "HOUSEKEEPING", "HOUSE KEEPING", "MANPOWER", "WATCHMAN",
    "WATCHMEN", "GUARD", "GUARDS", "OUTSOURCING", "OUTSOURCED",
    "FACILITY MANAGEMENT", "SECURITY GUARD", "SECURITY PERSONNEL", "CFMS",
    "UPKEEPING", "CLEANING", "SANITATION", "SWEEPER", "SUPPORT STAFF",
    "MULTI TASKING STAFF", "DATA ENTRY OPERATOR", "ATTENDANT", "DRIVER",
    "WARD BOY", "SERVICE PROVIDER", "MTS", "DEO",
]

SAMAJA_EDITIONS = {
    "Bhubaneswar": "bh", "Cuttack": "ct", "Sambalpur": "sa",
    "Balasore": "ba", "Berhampur": "br", "Rourkela": "ro",
    "Angul-Dhenkanal": "an", "Koraput": "ko",
}
SAMBAD_EDITIONS = {"Bhubaneswar": "hr"}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
}


@dataclass(frozen=True)
class PageSource:
    paper: str
    edition: str
    page: int
    url: str


@dataclass
class Result:
    paper: str
    edition: str
    page: int
    full_image: Image.Image
    crop: Image.Image
    tender_hits: list[str]
    service_hits: list[str]
    source_url: str
    elapsed: float


def css() -> None:
    st.markdown(
        """
        <style>
        .stApp {background:linear-gradient(135deg,#f8fafc,#eef4fa)}
        .hero {padding:22px 24px;border-radius:22px;background:linear-gradient(120deg,#062449,#185789);color:white;box-shadow:0 14px 36px #0a31552b;margin-bottom:15px}
        .hero-row{display:flex;align-items:center;gap:17px}.hero img{width:68px;height:68px;object-fit:contain;background:white;border-radius:15px;padding:6px}
        .hero h1{margin:0;font-size:2rem}.hero p{margin:6px 0 0;color:#dbe9f7}.eyebrow{color:#ffc400;font-size:.76rem;font-weight:800;letter-spacing:.09em}
        div[data-testid="stButton"] button[kind="primary"]{background:linear-gradient(90deg,#072b55,#185789);border:0;border-radius:13px;min-height:48px;font-weight:750}
        .chip{display:inline-block;padding:4px 9px;border:1px solid #d6e3f0;border-radius:999px;background:#eef5fb;color:#123c67;font-size:.75rem;font-weight:700;margin:2px 3px 2px 0}
        .note{padding:12px 14px;border-radius:13px;background:#edf6ff;border:1px solid #cfe5fa;color:#123b61}
        </style>
        """,
        unsafe_allow_html=True,
    )


def hero() -> None:
    st.markdown(
        f"""
        <div class="hero"><div class="hero-row">
          <img src="{LOGO_URL}"><div><div class="eyebrow">FAST OCR · LOCAL NOTICE CROPPING</div>
          <h1>{APP_NAME}</h1><p>{COMPANY}</p></div>
        </div></div>
        """,
        unsafe_allow_html=True,
    )


def normalise(text: str) -> str:
    text = text.upper().replace("–", "-").replace("—", "-")
    text = re.sub(r"[^A-Z0-9&/+-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def phrase_hits(text: str, terms: Iterable[str]) -> list[str]:
    cleaned = normalise(text)
    hits = []
    for term in terms:
        target = normalise(term)
        if re.search(rf"(?<![A-Z0-9]){re.escape(target)}(?![A-Z0-9])", cleaned):
            hits.append(term)
    return sorted(set(hits))


def term_tokens(terms: Iterable[str]) -> set[str]:
    out = set()
    for phrase in terms:
        for token in normalise(phrase).split():
            if len(token) >= 4 or token in {"NIT", "EOI", "RFP", "RFQ", "IFB", "CFMS", "MTS", "DEO"}:
                out.add(token)
    return out


TENDER_TOKENS = term_tokens(TENDER_TERMS)
SERVICE_TOKENS = term_tokens(SERVICE_TERMS)


def source_list(paper: str, edition: str, d: date, pages: int) -> list[PageSource]:
    ds = d.strftime("%d%m%Y")
    if paper == "Samaja":
        code = SAMAJA_EDITIONS.get(edition)
        if not code:
            return []
        return [
            PageSource(paper, edition, p, f"https://www.samajaepaper.in/epaperimages/{ds}/{ds}-md-{code}-{p}.jpg")
            for p in range(1, pages + 1)
        ]
    if paper == "Sambad":
        code = SAMBAD_EDITIONS.get(edition)
        if not code:
            return []
        return [
            PageSource(paper, edition, p, f"https://sambadepaper.com/epaperimages/{ds}/{ds}-md-{code}-{p}ss.jpg")
            for p in range(1, pages + 1)
        ]
    return []


@st.cache_data(ttl=3600, show_spinner=False)
def download_page(url: str) -> bytes | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=(5, 12))
        ctype = r.headers.get("content-type", "")
        if r.status_code != 200 or len(r.content) < 12000 or "image" not in ctype:
            return None
        return r.content
    except requests.RequestException:
        return None


def preview_image(img: Image.Image, width: int = 1000) -> tuple[Image.Image, float]:
    rgb = img.convert("RGB")
    scale = min(1.0, width / rgb.width)
    if scale < 1:
        rgb = rgb.resize((width, max(1, int(rgb.height * scale))), Image.Resampling.BILINEAR)
    gray = ImageOps.grayscale(rgb)
    gray = ImageEnhance.Contrast(gray).enhance(1.7)
    gray = gray.filter(ImageFilter.SHARPEN)
    return gray, scale


def rows_from_tsv(data: dict) -> list[dict]:
    rows = []
    for i, raw in enumerate(data.get("text", [])):
        token = normalise(str(raw))
        if not token:
            continue
        try:
            conf = float(data["conf"][i])
        except (ValueError, TypeError, KeyError):
            conf = -1
        if conf < 24:
            continue
        rows.append(
            {
                "text": token,
                "x": int(data["left"][i]),
                "y": int(data["top"][i]),
                "w": int(data["width"][i]),
                "h": int(data["height"][i]),
                "conf": conf,
            }
        )
    return rows


def token_matches(word: str, vocab: set[str]) -> bool:
    if word in vocab:
        return True
    return any(
        len(v) >= 7
        and abs(len(word) - len(v)) <= 1
        and (word.startswith(v[:-1]) or v.startswith(word[:-1]))
        for v in vocab
    )


def locate_notice(
    img: Image.Image, data: dict, scale: float
) -> tuple[Image.Image, list[str], list[str]] | None:
    rows = rows_from_tsv(data)
    if not rows:
        return None

    page_w = int(img.width * scale)
    page_h = int(img.height * scale)
    trows = [r for r in rows if token_matches(r["text"], TENDER_TOKENS)]
    srows = [r for r in rows if token_matches(r["text"], SERVICE_TOKENS)]
    if not trows or not srows:
        return None

    candidates = []
    for t in trows:
        tx, ty = t["x"] + t["w"] / 2, t["y"] + t["h"] / 2
        for s in srows:
            sx, sy = s["x"] + s["w"] / 2, s["y"] + s["h"] / 2
            dx, dy = abs(tx - sx) / page_w, abs(ty - sy) / page_h
            if dx > 0.30 or dy > 0.20:
                continue

            cx, cy = (tx + sx) / 2, (ty + sy) / 2
            ww = max(page_w * 0.30, abs(tx - sx) + page_w * 0.15)
            hh = max(page_h * 0.18, abs(ty - sy) + page_h * 0.12)
            ww, hh = min(ww, page_w * 0.58), min(hh, page_h * 0.42)
            x1, y1 = max(0, cx - ww / 2), max(0, cy - hh / 2)
            x2, y2 = min(page_w, cx + ww / 2), min(page_h, cy + hh / 2)

            local = [
                r
                for r in rows
                if x1 <= r["x"] + r["w"] / 2 <= x2
                and y1 <= r["y"] + r["h"] / 2 <= y2
            ]
            local_text = " ".join(r["text"] for r in local)
            th = phrase_hits(local_text, TENDER_TERMS)
            sh = phrase_hits(local_text, SERVICE_TERMS)
            if not th or not sh:
                continue

            score = 8 * len(th) + 7 * len(sh) + min(len(local) / 20, 4)
            candidates.append((score, x1, y1, x2, y2, th, sh))

    if not candidates:
        return None

    _, x1, y1, x2, y2, th, sh = max(candidates, key=lambda z: z[0])
    inv = 1 / scale
    left, top, right, bottom = map(int, (x1 * inv, y1 * inv, x2 * inv, y2 * inv))
    pad_x, pad_y = int(img.width * 0.025), int(img.height * 0.025)
    left, top = max(0, left - pad_x), max(0, top - pad_y)
    right, bottom = min(img.width, right + pad_x), min(img.height, bottom + pad_y)
    crop = img.crop((left, top, right, bottom))
    return crop, th, sh


def ocr_page(source: PageSource, payload: bytes) -> tuple[Result | None, str]:
    started = time.monotonic()
    try:
        img = Image.open(io.BytesIO(payload)).convert("RGB")
        small, scale = preview_image(img)
        data = pytesseract.image_to_data(
            small,
            lang="eng",
            config="--oem 1 --psm 11",
            output_type=Output.DICT,
            timeout=18,
        )
        found = locate_notice(img, data, scale)
        if not found:
            return None, "no local tender/service pair"
        crop, th, sh = found
        return (
            Result(
                source.paper,
                source.edition,
                source.page,
                img,
                crop,
                th,
                sh,
                source.url,
                time.monotonic() - started,
            ),
            "matched",
        )
    except RuntimeError:
        return None, "OCR timeout"
    except Exception as exc:
        return None, type(exc).__name__


def image_bytes(img: Image.Image) -> bytes:
    b = io.BytesIO()
    img.convert("RGB").save(b, "JPEG", quality=93, optimize=True)
    return b.getvalue()


def zip_bytes(results: list[Result], d: date) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        summary = [f"ESS Tender Finder — {d}", ""]
        for r in results:
            name = f"{d}_{r.paper}_{r.edition}_page-{r.page}.jpg".replace(" ", "_")
            z.writestr(name, image_bytes(r.crop))
            summary.append(
                f"{r.paper} page {r.page}: {', '.join(r.tender_hits)} | {', '.join(r.service_hits)}"
            )
        z.writestr("scan-summary.txt", "\n".join(summary))
    return b.getvalue()


def share_button(img: Image.Image, filename: str, key: str) -> None:
    encoded = base64.b64encode(image_bytes(img)).decode()
    html = f"""
    <button id="b{key}" style="width:100%;padding:11px;border:0;border-radius:11px;background:#1fa463;color:white;font-weight:700">Share cutout</button>
    <small id="m{key}" style="font-family:sans-serif;color:#667"></small>
    <script>
    document.getElementById("b{key}").onclick=async()=>{{try{{
      let s=atob("{encoded}"),a=new Uint8Array(s.length);for(let i=0;i<s.length;i++)a[i]=s.charCodeAt(i);
      let f=new File([a],"{filename}",{{type:"image/jpeg"}});
      if(navigator.canShare&&navigator.canShare({{files:[f]}})) await navigator.share({{title:"ESS tender cutout",files:[f]}});
      else document.getElementById("m{key}").innerText="Use Download on this browser.";
    }}catch(e){{}}}};
    </script>
    """
    components.html(html, height=58)


def run_scan(
    paper: str, edition: str, d: date, pages: int, workers: int
) -> tuple[list[Result], list[str]]:
    sources = source_list(paper, edition, d, pages)
    if not sources:
        return [], ["This edition is not supported by the selected newspaper connector."]

    status = st.status("Downloading newspaper pages…", expanded=True)
    download_bar = st.progress(0)
    downloaded: list[tuple[PageSource, bytes]] = []

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(download_page, s.url): s for s in sources}
        for i, future in enumerate(as_completed(futures), 1):
            s = futures[future]
            payload = future.result()
            if payload:
                downloaded.append((s, payload))
            download_bar.progress(
                i / len(sources), text=f"Downloaded {i}/{len(sources)} page links"
            )

    downloaded.sort(key=lambda x: x[0].page)
    if not downloaded:
        status.update(label="No pages could be downloaded", state="error")
        return [], ["The publisher did not return page images for this date/edition."]

    status.update(label=f"Scanning {len(downloaded)} downloaded pages…", state="running")
    ocr_bar = st.progress(0)
    results: list[Result] = []
    notes: list[str] = []

    with ThreadPoolExecutor(max_workers=min(workers, 2)) as pool:
        futures = {pool.submit(ocr_page, s, payload): s for s, payload in downloaded}
        for i, future in enumerate(as_completed(futures), 1):
            s = futures[future]
            result, note = future.result()
            if result:
                results.append(result)
                status.write(f"✅ {s.paper} page {s.page}: notice cutout found")
            elif note == "OCR timeout":
                notes.append(f"Page {s.page}: OCR stopped after 18 seconds")
            ocr_bar.progress(
                i / len(downloaded), text=f"OCR completed {i}/{len(downloaded)} pages"
            )

    results.sort(key=lambda r: r.page)
    status.update(label=f"Finished: {len(results)} cutout(s) found", state="complete")
    return results, notes


def show_results(results: list[Result], d: date) -> None:
    if not results:
        st.warning(
            "No compact notice matched both a tender keyword and a nearby service keyword. "
            "No full newspaper pages are returned as results."
        )
        return

    a, b, c = st.columns(3)
    a.metric("Cutouts", len(results))
    b.metric("Pages with notices", len({r.page for r in results}))
    c.metric(
        "Average OCR time",
        f"{sum(r.elapsed for r in results) / len(results):.1f}s",
    )
    st.download_button(
        "Download all cutouts as ZIP",
        zip_bytes(results, d),
        f"ESS_tender_cutouts_{d}.zip",
        "application/zip",
        use_container_width=True,
    )

    for idx, r in enumerate(results):
        with st.container(border=True):
            st.subheader(f"{r.paper} · {r.edition} · page {r.page}")
            st.markdown(
                "".join(
                    f'<span class="chip">{x}</span>'
                    for x in r.tender_hits + r.service_hits
                ),
                unsafe_allow_html=True,
            )
            st.image(r.crop, caption="Automatically cropped notice", use_container_width=True)
            c1, c2 = st.columns(2)
            name = f"{d}_{r.paper}_page_{r.page}.jpg".replace(" ", "_")
            with c1:
                st.download_button(
                    "Download cutout",
                    image_bytes(r.crop),
                    name,
                    "image/jpeg",
                    key=f"d{idx}",
                    use_container_width=True,
                )
            with c2:
                share_button(r.crop, name, str(idx))
            with st.expander("Verify against original page"):
                st.image(r.full_image, use_container_width=True)
                st.caption(r.source_url)


def online_tab() -> None:
    st.markdown("### Daily online scan")
    st.markdown(
        '<div class="note">This final build is intentionally bounded: page downloads have 12-second timeouts, OCR has an 18-second timeout per page, and no full page is accepted as a result.</div>',
        unsafe_allow_html=True,
    )
    c1, c2 = st.columns(2)
    with c1:
        d = st.date_input("Edition date", value=date.today())
        paper = st.selectbox("Newspaper", ["Samaja", "Sambad"])
        editions = list(SAMAJA_EDITIONS) if paper == "Samaja" else list(SAMBAD_EDITIONS)
        edition = st.selectbox("Edition", editions)
    with c2:
        pages = st.slider("Pages to scan", 4, 16, 8)
        workers = st.select_slider("OCR workers", options=[1, 2], value=2)
        st.caption(
            "Dharitri and Prameya remain in Upload mode because their interactive readers "
            "are not stable enough for a dependable free-cloud connector."
        )

    if st.button("Start bounded scan", type="primary", use_container_width=True):
        started = time.monotonic()
        results, notes = run_scan(paper, edition, d, pages, workers)
        st.session_state["results"] = results
        st.session_state["scan_date"] = d
        st.session_state["notes"] = notes
        st.session_state["total_time"] = time.monotonic() - started

    if "total_time" in st.session_state:
        st.caption(f"Last scan completed in {st.session_state['total_time']:.1f} seconds.")
    if st.session_state.get("notes"):
        with st.expander("Skipped pages"):
            for n in st.session_state["notes"]:
                st.write("•", n)
    if "results" in st.session_state:
        show_results(st.session_state["results"], st.session_state["scan_date"])


def upload_tab() -> None:
    st.markdown("### Upload e-paper page images")
    st.info(
        "Use this dependable route for Dharitri, Prameya, or any date whose website blocks "
        "automatic access. Upload JPG/PNG page images; the same bounded OCR and local-cropping "
        "engine is used."
    )
    files = st.file_uploader(
        "Upload page images",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
    )
    label = st.text_input("Newspaper label", "Uploaded newspaper")
    d = st.date_input("Edition date", value=date.today(), key="up-date")

    if st.button("Scan uploaded pages", type="primary", use_container_width=True):
        results = []
        bar = st.progress(0)
        for i, f in enumerate(files or [], 1):
            try:
                img = Image.open(io.BytesIO(f.getvalue())).convert("RGB")
                small, scale = preview_image(img)
                data = pytesseract.image_to_data(
                    small,
                    lang="eng",
                    config="--oem 1 --psm 11",
                    output_type=Output.DICT,
                    timeout=18,
                )
                found = locate_notice(img, data, scale)
                if found:
                    crop, th, sh = found
                    results.append(Result(label, f.name, i, img, crop, th, sh, "", 0))
            except Exception:
                pass
            bar.progress(i / max(len(files or []), 1))
        st.session_state["upload_results"] = results
        st.session_state["upload_date"] = d

    if "upload_results" in st.session_state:
        show_results(
            st.session_state["upload_results"], st.session_state["upload_date"]
        )


def main() -> None:
    st.set_page_config(page_title=APP_NAME, page_icon="🔎", layout="wide")
    css()
    hero()
    t1, t2, t3 = st.tabs(["Online scan", "Upload fallback", "Operating rules"])
    with t1:
        online_tab()
    with t2:
        upload_tab()
    with t3:
        st.markdown(
            """
            ### What this build guarantees
            - It cannot remain on one page indefinitely: every network and OCR operation has a hard timeout.
            - A result must contain a tender keyword and a nearby service keyword.
            - A full newspaper page is never exported as a tender cutout.
            - Online mode is limited to stable direct-image connectors; unstable readers use Upload mode.
            - Always verify the original notice before making a commercial decision.
            """
        )


if __name__ == "__main__":
    main()
