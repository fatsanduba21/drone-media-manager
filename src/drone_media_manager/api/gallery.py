"""Small server-rendered browser gallery for the editorial catalog."""

from __future__ import annotations

from collections.abc import Callable
from html import escape
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from drone_media_manager.api.auth import require_browser_identity
from drone_media_manager.api.routes.catalog import (
    _asset,
    _asset_payload,
    _assets,
    _group_names,
    _trip,
)
from drone_media_manager.api.routes.downloads import selected_originals
from drone_media_manager.catalog.downloads import resolve_original
from drone_media_manager.catalog.selection import selected_count
from drone_media_manager.config import ServerSettings
from drone_media_manager.db.models.catalog import CatalogAsset
from drone_media_manager.db.models.ingest import Trip

_STYLE = """
:root{color-scheme:dark;--ink:#ede9df;--muted:#aaa9a3;--line:#343735;--accent:#e6a75b;--panel:#1b201f;--ground:#111615}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--ground);color:var(--ink);font:16px/1.5 'Trebuchet MS',sans-serif}
body:before{content:'';position:fixed;inset:0;pointer-events:none;opacity:.18;background:radial-gradient(ellipse at 90% 0%,#3c473b,transparent 47%)}
a{color:inherit;text-decoration:none}a:hover{color:var(--accent)}a:focus-visible,select:focus-visible,button:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
.shell{position:relative;max-width:1420px;padding:0 clamp(18px,4vw,72px) 90px;margin:auto}
header{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:29px 0;border-bottom:1px solid var(--line)}
.brand{font:700 17px/1 Georgia,serif;letter-spacing:.18em;text-transform:uppercase}.brand span{color:var(--accent)}
.edition{font-size:11px;letter-spacing:.22em;text-transform:uppercase;color:var(--muted)}
.eyebrow{display:block;margin:60px 0 12px;color:var(--accent);font-size:11px;font-weight:700;letter-spacing:.24em;text-transform:uppercase}
h1{font:normal clamp(42px,6vw,86px)/1.02 Georgia,serif;letter-spacing:-.045em;margin:0 0 20px;max-width:1000px}
h2{font:normal 27px/1.1 Georgia,serif;margin:0}p{margin:0}.intro{color:var(--muted);max-width:650px;font-size:17px}
.rule{border:0;border-top:1px solid var(--line);margin:42px 0 22px}
.section-head{display:flex;justify-content:space-between;align-items:end;gap:18px;margin:0 0 22px}
.count,.crumb,.back{color:var(--muted);font-size:13px}.crumb{margin:34px 0 0}.crumb a,.back{color:var(--accent)}
.trip-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px}
.trip{min-height:270px;padding:25px;background:linear-gradient(140deg,#263029,#1b201f 60%,#222824);border:1px solid #485048;display:flex;flex-direction:column;justify-content:space-between;transition:transform .2s,border-color .2s}
.trip:hover{transform:translateY(-4px);border-color:var(--accent)}.trip .index{color:var(--accent);font:14px Georgia,serif}
.trip h2{font-size:35px}.trip footer{display:flex;justify-content:space-between;border-top:1px solid #485048;padding-top:14px;font-size:12px;color:var(--muted);letter-spacing:.13em;text-transform:uppercase}
.filters{display:grid;grid-template-columns:repeat(5,minmax(130px,1fr)) auto;gap:12px;align-items:end;margin:30px 0 32px;padding:20px;background:var(--panel);border:1px solid var(--line)}
.filters label{display:block;color:var(--muted);font-size:11px;letter-spacing:.13em;text-transform:uppercase}.filters select{display:block;width:100%;margin-top:7px;padding:10px 8px;border:1px solid #4a504b;background:#141917;color:var(--ink);font:14px 'Trebuchet MS',sans-serif}
.filters button{padding:11px 17px;border:1px solid var(--accent);background:var(--accent);color:#191713;font-weight:700;cursor:pointer}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:28px 16px}
.card{display:block;background:var(--panel);border:1px solid var(--line);transition:transform .2s,border-color .2s}.card:hover{transform:translateY(-4px);border-color:var(--accent)}
.thumb{height:230px;background:linear-gradient(130deg,#292f2c,#111715);display:flex;align-items:center;justify-content:center;overflow:hidden}
.thumb img{width:100%;height:100%;object-fit:contain}.thumb .missing{color:var(--muted);font:italic 18px Georgia,serif}
.card-body{padding:16px}.badge{display:inline-block;padding:3px 7px;border:1px solid #7d694c;color:var(--accent);font-size:10px;letter-spacing:.1em}
.card h3{font:normal 21px/1.15 Georgia,serif;margin:13px 0 5px;overflow-wrap:anywhere}.card dl,.facts{display:grid;grid-template-columns:1fr 1fr;gap:8px 14px;margin:14px 0 0}
dt{color:var(--muted);font-size:10px;letter-spacing:.12em;text-transform:uppercase}dd{margin:2px 0 0;font-size:13px;overflow-wrap:anywhere}
.empty{padding:52px 25px;border:1px dashed var(--line);color:var(--muted);text-align:center}
.detail{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(260px,.7fr);gap:clamp(24px,5vw,70px);margin-top:30px;align-items:start}
.player-frame{display:flex;align-items:center;justify-content:center;background:#080b0a;border:1px solid var(--line);min-height:300px;max-height:72vh;overflow:hidden}
.player-frame.portrait{max-width:490px;margin:auto}.player-frame video,.player-frame img{display:block;max-width:100%;max-height:72vh;object-fit:contain}
.player-frame video{width:100%;height:auto}.detail aside{border-top:1px solid var(--accent);padding-top:20px}.detail h1{font-size:clamp(32px,4vw,56px)}
.facts{grid-template-columns:1fr 1fr;gap:20px;margin:35px 0}.detail .back{display:inline-block;margin-top:25px;border-bottom:1px solid var(--accent);padding-bottom:4px}
.selection-bar{margin:0 0 20px;padding:15px 18px;border:1px solid #665238;background:#28241d;color:var(--accent);font-weight:700}
.selection-form{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:12px 16px;border-top:1px solid var(--line)}
.selection-form button{padding:8px 12px;border:1px solid var(--accent);background:transparent;color:var(--accent);font:700 13px 'Trebuchet MS',sans-serif;cursor:pointer}
.selection-form button:hover{background:var(--accent);color:#191713}
.selected-status{color:var(--accent);font-size:12px;font-weight:700}
.detail .selection-form{padding:0 0 18px;border-top:0}.download-panel{margin:0 0 28px;padding:18px;border:1px solid var(--line);background:var(--panel)}
.download-panel strong{display:block;margin-bottom:10px;color:var(--accent)}
.download-panel p{margin:8px 0;color:var(--muted);font-size:13px}
.download-panel button{padding:10px 16px;border:1px solid var(--accent);background:var(--accent);color:#191713;font-weight:700;cursor:pointer}
.download-list{margin:14px 0 0;padding-left:19px}.download-list li{margin:5px 0}
.original-link,.original-missing{display:inline-block;margin:8px 16px 15px;color:var(--accent);font-size:13px}
.original-missing{color:var(--muted)}
.logout-form button{padding:8px 12px;border:1px solid var(--line);background:transparent;color:var(--ink);cursor:pointer}
@media(max-width:900px){.filters{grid-template-columns:repeat(2,minmax(0,1fr))}.detail{grid-template-columns:1fr}.player-frame.portrait{margin:0}}
@media(max-width:550px){header{align-items:start}.edition{display:none}.filters{grid-template-columns:1fr 1fr;padding:14px}.filters button{grid-column:1/-1}.thumb{height:210px}}
"""


def _page(title: str, content: str, csrf_token: str) -> HTMLResponse:
    logout_form = (
        '<form class="logout-form" method="post" action="/logout">'
        f'<input type="hidden" name="csrf_token" value="{escape(csrf_token, quote=True)}">'
        '<button type="submit">Sair</button></form>'
    )
    return HTMLResponse(
        '<!doctype html><html lang="pt-BR"><head>'
        '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(title)} · Atlas de voo</title><style>{_STYLE}</style></head>"
        '<body><div class="shell"><header><a class="brand" href="/gallery">'
        'ATLAS <span>DE VOO</span></a><span class="edition">Catálogo editorial / 01</span>'
        + logout_form
        + f"</header><main>{content}</main></div></body></html>",
        headers={"Cache-Control": "private, no-store"},
    )


def _duration(value: int | None) -> str:
    if value is None:
        return "—"
    hours, remainder = divmod(value // 1000, 3600)
    minutes, seconds = divmod(remainder, 60)
    return (
        f"{hours:02}:{minutes:02}:{seconds:02}"
        if hours
        else f"{minutes:02}:{seconds:02}"
    )


def _label(value: object) -> str:
    return escape(str(value)) if value not in (None, "") else "—"


def _field(name: str, value: object) -> str:
    return f"<div><dt>{escape(name)}</dt><dd>{_label(value)}</dd></div>"


def _select(name: str, label: str, options: set[str], selected: str | None) -> str:
    items = ['<option value="">Todos</option>']
    for option in sorted(options):
        choice = " selected" if option == selected else ""
        items.append(
            f'<option value="{escape(option, quote=True)}"{choice}>'
            f"{escape(option)}</option>"
        )
    return (
        f'<label>{escape(label)}<select name="{name}">'
        + "".join(items)
        + "</select></label>"
    )


def _selection_form(
    slug: str, asset_id: str, csrf_token: str, selected: bool, *, detail: bool = False
) -> str:
    next_value = '<input type="hidden" name="next" value="detail">' if detail else ""
    return (
        f'<form class="selection-form" method="post" action="/gallery/{quote(slug, safe="")}/assets/{quote(asset_id, safe="")}/selection">'
        f'<input type="hidden" name="csrf_token" value="{escape(csrf_token, quote=True)}">'
        f'<input type="hidden" name="selected" value="{"false" if selected else "true"}">'
        + next_value
        + ('<span class="selected-status">Selecionado</span>' if selected else "")
        + f'<button type="submit">{"Desmarcar" if selected else "Selecionar"}</button></form>'
    )


def _size_label(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    if size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{size / (1024 * 1024 * 1024):.1f} GB"


def _download_link(
    session: Session, settings: ServerSettings, asset: CatalogAsset
) -> str:
    try:
        resolve_original(session, settings, asset)
    except HTTPException:
        return '<span class="original-missing">Original indisponível</span>'
    url = f"/api/catalog/assets/{quote(asset.asset_id, safe='')}/download"
    return (
        f'<a class="original-link" href="{escape(url, quote=True)}">Baixar original</a>'
    )


def _batch_panel(
    session: Session, settings: ServerSettings, user_id: str, trip: Trip
) -> str:
    try:
        originals = selected_originals(session, settings, user_id, trip.id)
    except HTTPException as error:
        code = error.detail.get("code") if isinstance(error.detail, dict) else None
        if code == "selection_empty":
            return '<div class="download-panel">Selecione assets para baixar os originais.</div>'
        return '<div class="download-panel">Original indisponível. Revise a seleção antes de baixar.</div>'
    total = sum(original.size_bytes for _, original in originals)
    links = "".join(
        '<li><a class="download-item" data-download-url="'
        + f"/api/catalog/assets/{quote(asset.asset_id, safe='')}/download"
        + '" href="'
        + f"/api/catalog/assets/{quote(asset.asset_id, safe='')}/download"
        + '">Baixar '
        + escape(original.filename)
        + "</a></li>"
        for asset, original in originals
    )
    return (
        '<div class="download-panel">'
        f"<strong>{len(originals)} originais · {_size_label(total)}</strong>"
        '<button id="download-selected" type="button">Baixar selecionados</button>'
        "<p>O Chrome pode pedir permissão para baixar vários arquivos. Confira os downloads; se algum for bloqueado, use os links abaixo.</p>"
        f'<ul class="download-list">{links}</ul>'
        '<p id="download-status" role="status"></p></div>'
        "<script>"
        'document.getElementById("download-selected").addEventListener("click",function(){'
        'const links=document.querySelectorAll("[data-download-url]");'
        'for(const link of links){const a=document.createElement("a");'
        'a.href=link.getAttribute("data-download-url");a.download="";'
        "document.body.appendChild(a);a.click();a.remove();}"
        'document.getElementById("download-status").textContent='
        '"Downloads solicitados. Confirme no Chrome; os links individuais ficam disponíveis acima.";'
        "});</script>"
    )


def _card(
    session: Session,
    asset: CatalogAsset,
    slug: str,
    settings: ServerSettings,
    user_id: str,
    csrf_token: str,
    group_names: dict[str, str],
) -> str:
    payload = _asset_payload(session, asset, settings, user_id, group_names)
    asset_url = (
        f"/gallery/{quote(slug, safe='')}/assets/{quote(asset.asset_id, safe='')}"
    )
    thumb = payload["thumbnail_url"]
    preview = (
        f'<img src="{escape(str(thumb), quote=True)}" alt="Prévia do asset">'
        if thumb
        else '<span class="missing">Prévia indisponível</span>'
    )
    kind = "Vídeo" if asset.media_type == "VIDEO" else "Foto"
    title = payload["location_group_name"] or payload["poi"] or kind
    return (
        f'<div class="card"><a href="{asset_url}"><div class="thumb">{preview}</div>'
        '<div class="card-body">'
        f'<span class="badge">{escape(asset.classification)}</span>'
        f"<h3>{_label(title)}</h3><dl>"
        + _field("Duração", _duration(asset.duration_ms))
        + _field("POI", payload["poi"])
        + _field("Grupo confirmado", payload["location_group_name"])
        + _field("Movimento", asset.movement)
        + _field("Pessoas", asset.people)
        + "</dl></div></a>"
        + _selection_form(slug, asset.asset_id, csrf_token, bool(payload["selected"]))
        + _download_link(session, settings, asset)
        + "</div>"
    )


def gallery_router(
    settings: ServerSettings, session_factory: Callable[[], Session]
) -> APIRouter:
    router = APIRouter()

    @router.get("/", response_model=None)
    def home() -> RedirectResponse:
        return RedirectResponse("/gallery")

    @router.get("/gallery", response_model=None)
    def trips_page(request: Request) -> HTMLResponse:
        identity = require_browser_identity(request)
        with session_factory() as session:
            rows = session.execute(
                select(Trip, func.count(CatalogAsset.id))
                .join(CatalogAsset, CatalogAsset.trip_id == Trip.id)
                .group_by(Trip.id)
                .order_by(Trip.name, Trip.slug)
            ).all()
        cards = "".join(
            '<a class="trip" href="/gallery/'
            + quote(trip.slug, safe="")
            + '"><span class="index">VIAGEM / '
            + f"{index:02}</span><h2>{escape(trip.name)}</h2>"
            + f"<footer><span>{count} assets</span><span>Abrir acervo →</span></footer></a>"
            for index, (trip, count) in enumerate(rows, 1)
        )
        content = (
            '<span class="eyebrow">O acervo / viagens</span>'
            "<h1>Histórias vistas de cima.</h1>"
            '<p class="intro">Explore as viagens, reveja os enquadramentos e encontre a cena certa.</p>'
            '<hr class="rule"><div class="section-head"><h2>Viagens</h2>'
            f'<span class="count">{len(rows)} no catálogo</span></div>'
            + (
                '<div class="trip-grid">' + cards + "</div>"
                if rows
                else '<div class="empty">Nenhuma viagem no catálogo.</div>'
            )
        )
        return _page("Viagens", content, identity.csrf_token)

    @router.get("/gallery/{slug}", response_model=None)
    def assets_page(
        slug: str,
        request: Request,
        classification: str | None = None,
        poi: str | None = None,
        movement: str | None = None,
        people: str | None = None,
        media_type: str | None = None,
        group_id: str | None = None,
    ) -> HTMLResponse:
        with session_factory() as session:
            trip = _trip(session, slug)
            all_assets = _assets(session, trip)
            shown = _assets(
                session,
                trip,
                classification=classification,
                poi=poi,
                movement=movement,
                people=people,
                media_type=media_type,
                group_id=group_id,
            )
            group_names = _group_names(session, trip.id)
            group_options = [
                '<option value="">Todos</option>',
                '<option value="ungrouped"'
                + (" selected" if group_id == "ungrouped" else "")
                + ">Sem grupo</option>",
            ]
            group_options.extend(
                f'<option value="{escape(key, quote=True)}"{" selected" if key == group_id else ""}>{escape(value)}</option>'
                for key, value in sorted(
                    group_names.items(), key=lambda pair: pair[1].casefold()
                )
            )
            fields = (
                _select(
                    "classification",
                    "Classificação",
                    {a.classification for a in all_assets},
                    classification,
                )
                + _select(
                    "poi",
                    "POI",
                    {p for a in all_assets if (p := a.poi_final or a.poi_suggested)},
                    poi,
                )
                + _select(
                    "movement",
                    "Movimento",
                    {a.movement for a in all_assets if a.movement},
                    movement,
                )
                + _select(
                    "people",
                    "Pessoas",
                    {a.people for a in all_assets if a.people},
                    people,
                )
                + _select(
                    "media_type",
                    "Mídia",
                    {a.media_type for a in all_assets},
                    media_type,
                )
                + '<label>Grupo confirmado<select name="group_id">'
                + "".join(group_options)
                + "</select></label>"
            )
            identity = require_browser_identity(request)
            count = selected_count(session, identity.user_id, trip.id)
            cards = "".join(
                _card(
                    session,
                    asset,
                    slug,
                    settings,
                    identity.user_id,
                    identity.csrf_token,
                    group_names,
                )
                for asset in shown
            )
            download_panel = _batch_panel(session, settings, identity.user_id, trip)
        content = (
            '<nav class="crumb"><a href="/gallery">Viagens</a> / '
            + escape(trip.name)
            + "</nav>"
            '<span class="eyebrow">Viagem / catálogo</span>'
            f"<h1>{escape(trip.name)}</h1>"
            '<p class="intro">Filtre o acervo pelos metadados editoriais e abra uma prévia.</p>'
            f'<form class="filters" method="get" action="/gallery/{quote(slug, safe="")}">'
            + fields
            + '<button type="submit">Filtrar</button></form>'
            + f'<div class="selection-bar">{count} selecionado{"s" if count != 1 else ""}</div>'
            + download_panel
            + '<div class="section-head"><h2>Galeria</h2>'
            + f'<span class="count">{len(shown)} de {len(all_assets)} assets</span></div>'
            + (
                '<div class="grid">' + cards + "</div>"
                if cards
                else '<div class="empty">Nenhum asset corresponde aos filtros.</div>'
            )
        )
        return _page(trip.name, content, identity.csrf_token)

    @router.get("/gallery/{slug}/assets/{asset_id}", response_model=None)
    def asset_page(slug: str, asset_id: str, request: Request) -> HTMLResponse:
        with session_factory() as session:
            trip = _trip(session, slug)
            asset = _asset(session, asset_id)
            if asset.trip_id != trip.id:
                raise HTTPException(status_code=404, detail={"code": "asset_not_found"})
            identity = require_browser_identity(request)
            payload = _asset_payload(session, asset, settings, identity.user_id)
            download_link = _download_link(session, settings, asset)
        thumb = payload["thumbnail_url"]
        proxy = payload["proxy_url"]
        portrait = (
            asset.display_width is not None
            and asset.display_height is not None
            and asset.display_height > asset.display_width
        )
        frame_class = "player-frame portrait" if portrait else "player-frame"
        poster = f' poster="{escape(str(thumb), quote=True)}"' if thumb else ""
        if proxy:
            media = (
                f'<video controls playsinline preload="metadata"{poster} '
                f'src="{escape(str(proxy), quote=True)}">'
                "Seu navegador não reproduz esta prévia.</video>"
            )
        elif thumb:
            media = (
                f'<img src="{escape(str(thumb), quote=True)}" alt="Prévia do asset">'
            )
        else:
            media = '<span class="missing">Prévia indisponível</span>'
        content = (
            '<nav class="crumb"><a href="/gallery">Viagens</a> / '
            f'<a href="/gallery/{quote(slug, safe="")}">{escape(trip.name)}</a> / Detalhe</nav>'
            '<div class="detail"><div>'
            f'<div class="{frame_class}">{media}</div></div><aside>'
            '<span class="eyebrow">Prévia / asset</span>'
            f"<h1>{_label(payload['location_group_name'] or payload['poi'] or asset.media_type)}</h1>"
            f'<span class="badge">{escape(asset.classification)}</span>'
            '<dl class="facts">'
            + _field("Duração", _duration(asset.duration_ms))
            + _field("POI", payload["poi"])
            + _field("Grupo confirmado", payload["location_group_name"])
            + _field("Movimento", asset.movement)
            + _field("Pessoas", asset.people)
            + _field("Tipo", asset.media_type)
            + _field("Captura", asset.capture_date)
            + "</dl>"
            + _selection_form(
                slug,
                asset.asset_id,
                identity.csrf_token,
                bool(payload["selected"]),
                detail=True,
            )
            + download_link
            + f'<a class="back" href="/gallery/{quote(slug, safe="")}">← Voltar à galeria</a>'
            + "</aside></div>"
        )
        return _page(str(payload["poi"] or "Detalhe"), content, identity.csrf_token)

    return router
