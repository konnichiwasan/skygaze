#!/usr/bin/env python3
"""
SkyGaze - a ceiling planetarium + live flight tracker.

* Pulls LIVE aircraft from the OpenSky Network around your chosen location.
* Renders a "look straight up" (zenith-centred) dome showing:
    - real stars + constellation stick-figures currently above your horizon
    - the Moon (with approximate phase) and the 5 bright planets
    - the live aircraft, plotted at their REAL bearing + elevation in the sky
* Also offers a top-down RADAR scope (the original Toasty-style geographic view).
* A live FLIGHT STATUS panel lists every tracked flight with altitude, speed,
  heading, climb/descent and distance/bearing from you.
* Soothing pentatonic chimes play when a flight climbs into your overhead sky.
* Pick your location by map picker or preset (Chennai only).
* Aesthetic DARK (night ceiling) and LIGHT (day) themes.
* Ask-AI assistant (server-side OpenRouter proxy; key never reaches the browser)
  plus an auto-rotating "Tonight's Wonder" fun-fact card. Free models only.

Zero pip installs needed - only the Python standard library. Visuals use HTML5
canvas + Leaflet (loaded from CDN) for the map picker.
"""

import math
import json
import datetime
import os
import time
import urllib.request
import urllib.parse
import threading
import webbrowser
import http.server
import socketserver

# ----------------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------------
OBSERVER_DEFAULT = {"lat": 13.0500, "lon": 80.2824, "city": "Marina Beach, Chennai"}  # neutral public landmark; change via the in-app map picker
RADIUS_KM = 250                                   # how far out to grab aircraft
REFRESH_S = 15                                    # aircraft poll interval
PORT = 8753
OBS_LOCK = threading.Lock()
OBS = dict(OBSERVER_DEFAULT)

# ----------------------------------------------------------------------------
# LOCAL SECRETS  (gitignored, chmod 600 -- never commit config.json)
# ----------------------------------------------------------------------------
# OpenRouter key lives ONLY here and is read server-side. It is never sent to
# the browser; the frontend is told merely whether a key is configured.
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

def load_cfg():
    """Return local config dict from config.json (gitignored). Empty on any error."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}

def openrouter_key():
    """Server-side only. Returns the OpenRouter key or '' if unset/missing."""
    return load_cfg().get("openrouter_key", "") or ""

# Free models only. The chosen OpenRouter key has guardrail / data-policy
# restrictions, so most free chat models (e.g. llama-3.3-70b, hermes-405b)
# return 404. The chain below is constrained to the FREE models that this
# key can actually reach (verified live). DEFAULT_MODEL is tried first; if it
# is rate-limited or retires, we fall through to the others so the assistant
# and the "Tonight's Wonder" card keep working without any paid key.
DEFAULT_MODEL = "openai/gpt-oss-20b:free"
FALLBACK_MODELS = [
    "tencent/hy3:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "poolside/laguna-xs-2.1:free",
    "openrouter/free",
    "google/gemma-4-26b-a4b-it:free",
    "cohere/north-mini-code:free",
]

# ----------------------------------------------------------------------------
# STAR CATALOG  (name, RA in hours, Dec in degrees, visual magnitude) ~ J2000
# ----------------------------------------------------------------------------
STAR_DATA = [
    ["Dubhe",11.062,61.75,1.79],["Merak",11.031,56.38,2.37],["Phecda",11.897,53.69,2.44],
    ["Megrez",12.257,57.03,3.31],["Alioth",12.900,55.96,1.77],["Mizar",13.399,54.93,2.23],
    ["Alkaid",13.792,49.31,1.86],
    ["Betelgeuse",5.919,7.41,0.45],["Bellatrix",5.418,6.35,1.64],["Alnitak",5.679,-1.94,1.74],
    ["Alnilam",5.604,-1.20,1.69],["Mintaka",5.533,-0.30,2.23],["Saiph",5.796,-9.67,2.07],
    ["Rigel",5.242,-8.20,0.13],["Meissa",5.585,9.93,3.39],
    ["Caph",0.153,59.15,2.28],["Schedar",0.675,56.54,2.24],["GammaCas",0.945,60.72,2.47],
    ["Ruchbah",1.430,60.24,2.68],["Segin",1.906,63.67,3.35],
    ["Deneb",20.690,45.28,1.25],["Sadr",20.371,40.26,2.23],["Gienah",20.770,33.97,2.48],
    ["DeltaCyg",19.749,45.13,2.87],["Albireo",19.512,27.96,3.05],
    ["Regulus",10.139,11.97,1.35],["Algieba",10.333,19.84,2.08],["Zosma",11.235,20.52,2.56],
    ["Denebola",11.818,14.57,2.11],["Chort",11.237,15.43,3.33],
    ["Acrux",12.443,-63.10,0.77],["Mimosa",12.795,-59.69,1.25],["Gacrux",12.519,-57.11,1.63],
    ["Imai",12.252,-58.75,2.79],
    ["Polaris",2.530,89.26,1.98],["Kochab",14.808,74.16,2.07],["Pherkad",15.869,71.83,3.00],
    ["Arcturus",14.261,19.18,-0.05],["Izar",14.749,27.07,2.37],["Muphrid",13.919,18.40,2.69],
    ["Kornephoros",15.387,21.49,2.78],["Nekkar",14.957,40.39,3.49],
    ["Vega",18.616,38.78,0.03],["Sheliak",18.835,33.36,3.52],["Sulafat",18.981,32.69,3.25],
    ["ZetaLyr",18.748,37.60,4.36],
    ["Altair",19.846,8.87,0.77],["Tarazed",19.769,10.61,2.72],["Alshain",19.923,6.38,3.71],
    ["Markab",23.079,15.21,2.49],["Scheat",23.284,28.08,2.44],["Algenib",0.644,15.18,2.83],
    ["Alpheratz",0.139,29.09,2.06],["Enif",21.738,9.88,2.39],
    ["Mirach",1.001,35.62,2.05],["Almach",2.065,42.33,2.26],
    ["Dschubba",16.005,-22.62,2.29],["Acrab",16.089,-19.81,2.56],["PiSco",16.287,-26.11,2.89],
    ["DeltaSco",16.504,-28.22,2.82],["Antares",16.490,-26.43,0.96],["Shaula",17.560,-37.10,1.62],
    ["Sargas",17.619,-42.99,1.86],["Lesath",17.622,-37.04,3.37],
    ["KausBorealis",18.245,-25.42,2.81],["KausMedia",18.210,-21.06,2.45],["KausAustralis",18.406,-34.39,1.85],
    ["Ascella",18.495,-29.88,2.59],["Nunki",18.795,-26.30,2.05],["Albaldah",18.915,-21.04,2.89],["Rukbat",18.128,-40.62,3.77],
    ["Sirius",6.752,-16.72,-1.46],["Mirzam",6.378,-14.27,1.98],["Wezen",7.156,-26.39,1.83],
    ["Adhara",7.074,-28.97,1.50],["Aludra",7.400,-29.30,2.45],
    ["Aldebaran",4.599,16.51,0.85],["Elnath",5.438,28.61,1.65],["Alcyone",3.791,24.11,2.87],
    ["Castor",7.577,31.89,1.58],["Pollux",7.755,28.03,1.14],["Alhena",6.626,16.40,1.93],
    ["Mebsuta",6.480,25.13,2.91],["Wasat",7.577,22.51,3.47],
    ["Capella",5.278,45.998,0.08],["Menkalinan",5.955,44.95,1.90],
    ["Procyon",7.655,5.225,0.34],["Gomeisa",7.759,8.29,2.89],
    ["Spica",13.420,-11.16,0.98],["Zaniah",11.278,-0.60,4.04],["Porrima",12.414,-1.45,2.74],
    ["Vindemiatrix",13.033,10.96,2.85],
    ["RigilKent",14.660,-60.83,-0.27],["Hadar",14.064,-60.37,0.61],
    ["Alphecca",15.589,26.71,2.22],["Nusakan",15.348,29.11,3.66],["ThetaCrB",15.787,31.36,4.14],
    ["Alphard",9.459,-8.66,1.98],
    ["Rasalhague",17.583,12.56,2.08],["RasAlgethi",17.441,14.39,3.35],
    ["Achernar",1.629,-57.24,0.46],["Canopus",6.399,-52.70,-0.72],["Fomalhaut",22.961,-29.62,1.16],
]

CONSTELLATION_LINES = [
    ["Dubhe","Merak"],["Merak","Phecda"],["Phecda","Megrez"],["Megrez","Dubhe"],
    ["Megrez","Alioth"],["Alioth","Mizar"],["Mizar","Alkaid"],
    ["Betelgeuse","Bellatrix"],["Betelgeuse","Alnitak"],["Bellatrix","Mintaka"],
    ["Alnitak","Alnilam"],["Alnilam","Mintaka"],["Alnitak","Saiph"],["Mintaka","Rigel"],["Saiph","Rigel"],
    ["Caph","Schedar"],["Schedar","GammaCas"],["GammaCas","Ruchbah"],["Ruchbah","Segin"],
    ["Deneb","Sadr"],["Sadr","Albireo"],["Sadr","Gienah"],["Sadr","DeltaCyg"],
    ["Regulus","Algieba"],["Algieba","Zosma"],["Zosma","Chort"],["Chort","Regulus"],["Zosma","Denebola"],
    ["Acrux","Gacrux"],["Mimosa","Imai"],
    ["Kochab","Pherkad"],["Pherkad","Polaris"],
    ["Arcturus","Izar"],["Izar","Muphrid"],["Izar","Kornephoros"],["Kornephoros","Nekkar"],
    ["Vega","Sheliak"],["Sheliak","Sulafat"],["Sulafat","ZetaLyr"],["ZetaLyr","Vega"],
    ["Tarazed","Altair"],["Altair","Alshain"],
    ["Markab","Scheat"],["Scheat","Alpheratz"],["Alpheratz","Algenib"],["Algenib","Markab"],["Markab","Enif"],
    ["Alpheratz","Mirach"],["Mirach","Almach"],
    ["Dschubba","Acrab"],["Acrab","PiSco"],["PiSco","DeltaSco"],["DeltaSco","Antares"],
    ["Antares","Shaula"],["Shaula","Lesath"],["Shaula","Sargas"],
    ["KausBorealis","KausMedia"],["KausMedia","KausAustralis"],["KausMedia","Ascella"],
    ["KausAustralis","Ascella"],["Nunki","Ascella"],["Nunki","KausBorealis"],
    ["Albaldah","Rukbat"],["Rukbat","KausAustralis"],
    ["Sirius","Mirzam"],["Sirius","Wezen"],["Wezen","Adhara"],["Adhara","Aludra"],
    ["Aldebaran","Elnath"],["Aldebaran","Alcyone"],
    ["Castor","Pollux"],["Castor","Mebsuta"],["Pollux","Alhena"],
    ["Capella","Menkalinan"],
    ["Procyon","Gomeisa"],
    ["Spica","Zaniah"],["Zaniah","Porrima"],["Porrima","Vindemiatrix"],
    ["RigilKent","Hadar"],
    ["Alphecca","Nusakan"],["Nusakan","ThetaCrB"],
    ["Rasalhague","RasAlgethi"],
]

# ----------------------------------------------------------------------------
# ASTRONOMY
# ----------------------------------------------------------------------------
def julian_day(dt):
    y = dt.year; m = dt.month
    if m <= 2:
        y -= 1; m += 12
    a = y // 100; b = 2 - a + a // 4
    jd = math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1)) + dt.day + b - 1524.5
    frac = (dt.hour + dt.minute / 60.0 + dt.second / 3600.0) / 24.0
    return jd + frac

def gmst_deg(jd):
    D = jd - 2451545.0
    return (280.46061837 + 360.98564736629 * D) % 360.0

def eq_to_horiz(ra_deg, dec_deg, lat_deg, lst_deg):
    ra = math.radians(ra_deg); dec = math.radians(dec_deg); lat = math.radians(lat_deg)
    H = math.radians((lst_deg - ra_deg) % 360.0)
    sin_alt = math.sin(dec) * math.sin(lat) + math.cos(dec) * math.cos(lat) * math.cos(H)
    sin_alt = max(-1.0, min(1.0, sin_alt))
    alt = math.asin(sin_alt)
    denom = math.cos(lat) * math.cos(alt)
    cos_az = 0.0 if abs(denom) < 1e-8 else (math.sin(dec) - math.sin(lat) * sin_alt) / denom
    cos_az = max(-1.0, min(1.0, cos_az))
    az = math.acos(cos_az)
    if math.sin(H) > 0:
        az = 2 * math.pi - az
    return math.degrees(alt), math.degrees(az)

def sun_radec(jd):
    D = jd - 2451545.0
    g = math.radians((357.529 + 0.98560028 * D) % 360.0)
    q = math.radians((280.460 + 0.9856474 * D) % 360.0)
    lam = q + math.radians(1.915) * math.sin(g) + math.radians(0.020) * math.sin(2 * g)
    eps = math.radians(23.439 - 0.00000036 * D)
    x = math.cos(lam); y = math.cos(eps) * math.sin(lam); z = math.sin(eps) * math.sin(lam)
    return math.degrees(math.atan2(y, x)) % 360, math.degrees(math.asin(z))

def moon_radec(jd):
    D = jd - 2451545.0
    Lp = math.radians(218.316 + 13.176396 * D)
    M = math.radians(134.963 + 13.064993 * D)
    F = math.radians(93.272 + 13.229350 * D)
    lam = Lp + math.radians(6.289) * math.sin(M)
    lat = math.radians(5.128) * math.sin(F)
    eps = math.radians(23.439 - 0.00000036 * D)
    x = math.cos(lat) * math.cos(lam); y = math.cos(lat) * math.sin(lam); z = math.sin(lat)
    y2 = y * math.cos(eps) - z * math.sin(eps); z2 = y * math.sin(eps) + z * math.cos(eps)
    return math.degrees(math.atan2(y2, x)) % 360, math.degrees(math.asin(z2))

PLANET_ELEM = {
    "Mercury": dict(a=0.38709927, e=0.20563593, I=7.00497902, Om=48.330765, w=77.45779, L0=252.25032, dL=149472.674),
    "Venus":   dict(a=0.72333566, e=0.00677672, I=3.39467605, Om=76.679843, w=131.60246, L0=181.97910, dL=58517.815),
    "Earth":   dict(a=1.00000011, e=0.016709,   I=0.0,         Om=0.0,       w=102.94719, L0=100.46435, dL=35999.373),
    "Mars":    dict(a=1.52371034, e=0.09339410, I=1.84969142, Om=49.559538, w=-23.94363, L0=-4.55343,  dL=19140.302),
    "Jupiter": dict(a=5.20288700, e=0.04838624, I=1.30439695, Om=100.473909,w=14.72847,  L0=34.39644,  dL=3034.746),
    "Saturn":  dict(a=9.53667594, e=0.05386179, I=2.48599187, Om=113.662424,w=92.59887,  L0=49.95424,  dL=1222.493),
}

def _heliocentric(el, T):
    a = el["a"]; e = el["e"]; I = math.radians(el["I"]); Om = math.radians(el["Om"]); w = math.radians(el["w"])
    L = math.radians(el["L0"] + el["dL"] * T)
    M = (L - w + math.pi) % (2 * math.pi) - math.pi
    E = M
    for _ in range(6):
        E = M + e * math.sin(E)
    nu = 2 * math.atan2(math.sqrt(1 + e) * math.sin(E / 2), math.sqrt(1 - e) * math.cos(E / 2))
    r = a * (1 - e * math.cos(E))
    lon = w + nu
    x = r * (math.cos(Om) * math.cos(lon) - math.sin(Om) * math.sin(lon) * math.cos(I))
    y = r * (math.sin(Om) * math.cos(lon) + math.cos(Om) * math.sin(lon) * math.cos(I))
    z = r * (math.sin(lon) * math.sin(I))
    return x, y, z

def planet_radec(jd):
    T = (jd - 2451545.0) / 36525.0
    ex, ey, ez = _heliocentric(PLANET_ELEM["Earth"], T)
    eps = math.radians(23.439 - 0.00000036 * (jd - 2451545.0))
    out = {}
    for name in ["Mercury", "Venus", "Mars", "Jupiter", "Saturn"]:
        x, y, z = _heliocentric(PLANET_ELEM[name], T)
        gx, gy, gz = x - ex, y - ey, z - ez
        lon = math.atan2(gy, gx); lat = math.atan2(gz, math.hypot(gx, gy))
        xq = math.cos(lat) * math.cos(lon); yq = math.cos(lat) * math.sin(lon); zq = math.sin(lat)
        y2 = yq * math.cos(eps) - zq * math.sin(eps); z2 = yq * math.sin(eps) + zq * math.cos(eps)
        out[name] = (math.degrees(math.atan2(y2, xq)) % 360, math.degrees(math.asin(z2)))
    return out

PLANET_COLOR = {"Mercury": "#b9b3a9", "Venus": "#f4e7b6", "Mars": "#e07a5f",
                "Jupiter": "#d8b48a", "Saturn": "#e3c878"}

# ----------------------------------------------------------------------------
# LOCATION + AIRCRAFT
# ----------------------------------------------------------------------------
AIRLINE_PREFIX = {
    "AKJ": "Akasa Air", "AXB": "Air India Express", "AIC": "Air India",
    "IGO": "IndiGo", "SLK": "SpiceJet", "VTI": "Vistara", "AFR": "Air France",
    "BAW": "British Airways", "DLH": "Lufthansa", "UAE": "Emirates", "QTR": "Qatar Airways",
    "SIA": "Singapore Airlines", "THA": "Thai Airways", "ETD": "Etihad", "KAC": "Kuwait Airways",
    "CPA": "Cathay Pacific", "ANA": "All Nippon", "JAL": "Japan Airlines", "SWR": "Swiss",
    "KLM": "KLM", "TAP": "TAP Portugal", "RYR": "Ryanair", "EZY": "EasyJet",
    "UAL": "United", "DAL": "Delta", "AAL": "American", "SVA": "Saudia",
    "OMA": "Oman Air", "GTI": "Garuda Indonesia", "MAS": "Malaysia Airlines",
    "NWS": "Norwegian", "ICE": "Icelandair", "FIN": "Finnair", "AUA": "Austrian",
    "TUR": "Turkish Airlines", "MSR": "EgyptAir", "ETH": "Ethiopian",
}

def airline_of(callsign):
    if not callsign:
        return ""
    for i in range(2, min(4, len(callsign)) + 1):
        pref = callsign[:i].upper()
        if pref in AIRLINE_PREFIX:
            return AIRLINE_PREFIX[pref]
    return callsign[:3].upper() + "…"

def airport_name(iata):
    # tiny common set; expand as needed
    D = {"DEL": "Delhi", "BOM": "Mumbai", "MAA": "Chennai", "BLR": "Bengaluru",
          "HYD": "Hyderabad", "CCU": "Kolkata", "COK": "Kochi", "GOI": "Goa",
          "DXB": "Dubai", "SIN": "Singapore", "LHR": "London", "CDG": "Paris",
          "BKK": "Bangkok", "DOH": "Doha", "AUH": "Abu Dhabi", "KUL": "Kuala Lumpur",
          "FRA": "Frankfurt", "AMS": "Amsterdam", "JFK": "New York", "SXR": "Srinagar"}
    return D.get(iata.upper(), iata.upper())

def aviationstack_key():
    """Server-side only. AviationStack access key from config.json, or ''."""
    return load_cfg().get("aviationstack_key", "") or ""

# --- zero-cost route lookups -------------------------------------------------
# AviationStack's FREE tier allows only 100 requests/month (HTTP-only). To keep
# the running cost strictly ZERO we (a) persist a callsign->route cache to disk
# so each flight number is looked up at most once (routes don't change mid-air,
# and tomorrow's repeat of the same flight is free), and (b) keep a persistent
# monthly budget counter that HARD-STOPS lookups before the free 100 is reached,
# so the paid tier is never touched. No key configured => we simply skip and
# fall back to the live-heading guess (also free).
ROUTE_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "route_cache.json")
AVSTACK_FREE_BUDGET = 95            # stay safely under the 100/month free cap
_ROUTE_LOCK = threading.Lock()

def _load_route_store():
    try:
        with open(ROUTE_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}

def _save_route_store(store):
    try:
        tmp = ROUTE_CACHE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(store, f)
        os.replace(tmp, ROUTE_CACHE_PATH)
    except Exception:
        pass

def route_of(callsign):
    """Best-effort 'from -> to' for a callsign, at ZERO running cost.

    Order: disk cache -> AviationStack FREE tier (budget-guarded) -> ''.
    Falls back to '' (the frontend then shows the live compass heading).
    Configure by adding "aviationstack_key" to config.json (gitignored).
    """
    if not callsign:
        return ""
    cs = callsign.strip().upper()
    if not cs:
        return ""
    with _ROUTE_LOCK:
        store = _load_route_store()
        month = time.strftime("%Y-%m")
        budget = store.get("_budget", {})
        cache = store.get("routes", {})
        # served from cache (free, instant) -- covers repeats forever
        if cs in cache:
            return cache[cs] or ""
        key = aviationstack_key()
        if not key:
            return ""
        # reset the monthly counter when the month rolls over
        if budget.get("month") != month:
            budget = {"month": month, "used": 0}
        if budget.get("used", 0) >= AVSTACK_FREE_BUDGET:
            return ""  # HARD STOP: never exceed the free tier -> guaranteed $0
        route = ""
        try:
            url = ("http://api.aviationstack.com/v1/flights?access_key=%s&flight_iata=%s"
                   % (key, cs))
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}),
                    timeout=6) as r:
                d = json.loads(r.read())
            f = (d.get("data") or [{}])[0]
            dep = (f.get("departure") or {}).get("iata")
            arr = (f.get("arrival") or {}).get("iata")
            if dep and arr:
                route = airport_name(dep) + " → " + airport_name(arr)
        except Exception:
            route = ""
        # count the call against the free budget regardless of outcome, and
        # cache the result (even "" for ~a day) so we don't re-spend on it
        budget["used"] = budget.get("used", 0) + 1
        cache[cs] = route
        store["_budget"] = budget
        store["routes"] = cache
        _save_route_store(store)
        return route

def get_location():
    # No IP-based geolocation: that sends the viewer's IP to a third party and
    # can reveal their real city. We only ever use the fixed Chennai default.
    return None

def bearing_distance(lat1, lon1, lat2, lon2):
    phi1 = math.radians(lat1); phi2 = math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dl)
    brg = math.degrees(math.atan2(y, x)) % 360
    a = math.sin((phi2 - phi1) / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    d = 6371000 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return brg, d

def get_planes(lat=None, lon=None):
    if lat is None or lon is None:
        with OBS_LOCK:
            lat, lon = OBS["lat"], OBS["lon"]
    dlat = RADIUS_KM / 111.0
    dlon = RADIUS_KM / (111.0 * math.cos(math.radians(lat)) + 1e-9)
    url = ("https://opensky-network.org/api/states/all?lamin=%.4f&lomin=%.4f&lamax=%.4f&lomax=%.4f"
           % (lat - dlat, lon - dlon, lat + dlat, lon + dlon))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            d = json.loads(r.read())
    except Exception:
        return []
    out = []
    route_cache = {}
    for s in (d.get("states") or []):
        if len(s) < 14:
            continue
        icao = s[0]; callsign = (s[1] or "").strip(); country = s[2] or ""
        lon2 = s[5]; lat2 = s[6]; baro = s[7]; onground = s[8]
        vel = s[9]; track = s[10]; vr = s[11]; geo = s[13]
        if lat2 is None or lon2 is None or onground:
            continue
        alt_m = baro if baro is not None else (geo or 0)
        brg, dist = bearing_distance(lat, lon, lat2, lon2)
        elev = math.degrees(math.atan2(alt_m, dist)) if dist > 1 else 90.0
        key = callsign.upper()
        rt = route_cache.get(key)
        if rt is None:
            rt = route_of(callsign)
            route_cache[key] = rt
        out.append({
            "icao": icao, "callsign": callsign or icao.upper(), "country": country,
            "airline": airline_of(callsign), "route": rt,
            "lat": lat2, "lon": lon2, "alt": alt_m,
            "speed": (vel or 0) * 3.6, "track": track or 0, "vr": vr or 0,
            "az": brg, "elev": elev, "dist": dist / 1000.0,
        })
    return out

def body_riseset(jd_now, ra_deg, dec_deg, lat_deg, lon_deg):
    """Coarse 24h scan returning (rise_jds, set_jds) near 'now' (local events via lon)."""
    steps = 144; samples = []
    for i in range(steps + 1):
        jd = jd_now - 0.5 + i / steps
        lst = (gmst_deg(jd) + lon_deg) % 360.0
        alt, _ = eq_to_horiz(ra_deg, dec_deg, lat_deg, lst)
        samples.append(alt)
    rises, sets = [], []
    for i in range(steps):
        a0, a1 = samples[i], samples[i + 1]
        if a0 < 0 <= a1:
            rises.append(jd_now - 0.5 + (i + 0.5) / steps)
        if a0 >= 0 > a1:
            sets.append(jd_now - 0.5 + (i + 0.5) / steps)
    return rises, sets

def jd_to_local_hm(jd, lon_deg):
    local = jd + lon_deg / 360.0          # approx local mean time
    hr = (local % 1) * 24
    h = int(hr); m = int((hr - h) * 60)
    return "%02d:%02d" % (h, m)

def moon_phase_name(illum):
    if illum < 0.04:  return "New"
    if illum < 0.21:  return "Waxing Crescent"
    if illum < 0.29:  return "First Quarter"
    if illum < 0.46:  return "Waxing Gibbous"
    if illum < 0.54:  return "Full"
    if illum < 0.71:  return "Waning Gibbous"
    if illum < 0.79:  return "Last Quarter"
    return "Waning Crescent"

def build_scene(lat=None, lon=None):
    if lat is None or lon is None:
        with OBS_LOCK:
            lat, lon = OBS["lat"], OBS["lon"]
    now = datetime.datetime.now(datetime.timezone.utc)
    jd = julian_day(now)
    lst = (gmst_deg(jd) + lon) % 360.0
    stars = []; idx = {}
    for (nm, ra, dec, mag) in STAR_DATA:
        alt, az = eq_to_horiz(ra * 15.0, dec, lat, lst)
        stars.append({"az": az, "alt": alt, "mag": mag, "name": nm})
        idx[nm] = len(stars) - 1
    lines = [[idx[a], idx[b]] for (a, b) in CONSTELLATION_LINES if a in idx and b in idx]
    sun_ra, sun_dec = sun_radec(jd)
    sun_alt, sun_az = eq_to_horiz(sun_ra, sun_dec, lat, lst)
    sun_rise, sun_set = body_riseset(jd, sun_ra, sun_dec, lat, lon)
    moon_ra, moon_dec = moon_radec(jd)
    moon_alt, moon_az = eq_to_horiz(moon_ra, moon_dec, lat, lst)
    elong = ((moon_ra - sun_ra + 180) % 360) - 180
    illum = (1 - math.cos(math.radians(elong))) / 2.0
    moon_rise, moon_set = body_riseset(jd, moon_ra, moon_dec, lat, lon)
    planets = []
    for nm, (ra, dec) in planet_radec(jd).items():
        alt, az = eq_to_horiz(ra, dec, lat, lst)
        planets.append({"name": nm, "az": az, "alt": alt, "color": PLANET_COLOR[nm]})
    def fmt(lst):
        return jd_to_local_hm(lst[0], lon) if lst else "--:--"
    return {
        "observer": {"lat": lat, "lon": lon}, "stars": stars, "lines": lines,
        "sun": {"az": sun_az, "alt": sun_alt, "rise": fmt(sun_rise), "set": fmt(sun_set)},
        "moon": {"az": moon_az, "alt": moon_alt, "illum": illum,
                  "rise": fmt(moon_rise), "set": fmt(moon_set), "phase": moon_phase_name(illum)},
        "planets": planets, "utc": now.isoformat(), "refresh": REFRESH_S,
    }

# ----------------------------------------------------------------------------
# HTML / FRONTEND
# ----------------------------------------------------------------------------
HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>SkyGaze — observation deck</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  :root{
    --gold:#e9c46a; --cyan:#8fd3ff; --ink:#dde7ff; --muted:#8fa3c9;
    --glass:rgba(10,16,30,.55); --edge:rgba(140,170,230,.18);
    --serif:'Cormorant Garamond',Georgia,'Times New Roman',serif;
    --sans:-apple-system,'Segoe UI',system-ui,Roboto,sans-serif;
  }
  html,body{margin:0;height:100%;background:#05070f;overflow:hidden;color:var(--ink);
    font-family:var(--sans);-webkit-font-smoothing:antialiased}
  #sky{display:block;position:fixed;inset:0;width:100vw;height:100vh}
  .ui{position:fixed;z-index:10;opacity:0;pointer-events:none;transition:opacity .7s ease}
  body.showui .ui{opacity:1;pointer-events:auto}
  .panel{background:var(--glass);border:1px solid var(--edge);border-radius:16px;
    backdrop-filter:blur(16px) saturate(120%);-webkit-backdrop-filter:blur(16px) saturate(120%);
    box-shadow:0 10px 40px rgba(0,0,0,.35)}

  /* title plate */
  #title{top:24px;left:28px;max-width:44vw}
  #title .brand{font-family:var(--serif);font-size:15px;letter-spacing:.46em;
    text-transform:uppercase;color:#cfe0ff;text-shadow:0 0 18px rgba(140,170,255,.25)}
  #title .rule{width:60px;height:1px;background:linear-gradient(90deg,var(--gold),transparent);margin:9px 0}
  #title .sub{font-size:10.5px;letter-spacing:.16em;text-transform:uppercase;color:var(--muted)}

  /* clock */
  #clock{top:22px;left:50%;transform:translateX(-50%);text-align:center}
  #clock .time{font-family:var(--serif);font-size:42px;font-weight:300;letter-spacing:.05em;
    color:#eef3ff;text-shadow:0 0 26px rgba(140,170,255,.28);line-height:1}
  #clock .day{font-size:10px;letter-spacing:.36em;text-transform:uppercase;color:var(--muted);margin-top:6px}
  #clock .date{font-size:12px;letter-spacing:.2em;color:#aab9da;margin-top:2px}
  #clock .asof{font-size:9.5px;letter-spacing:.1em;color:#5f7299;margin-top:7px}

  /* controls — slim pill dock */
  #controls{bottom:20px;left:50%;transform:translateX(-50%);display:flex;gap:7px;flex-wrap:wrap;
    justify-content:center;padding:8px 14px;max-width:92vw}
  #controls button{background:transparent;color:#bcd0f0;border:1px solid rgba(140,170,230,.22);
    border-radius:999px;padding:6px 14px;font-size:11px;letter-spacing:.1em;text-transform:uppercase;
    cursor:pointer;font-family:var(--sans);transition:all .2s}
  #controls button:hover{background:rgba(140,170,230,.12);color:#fff}
  #controls button.on{background:rgba(233,196,106,.16);border-color:rgba(233,196,106,.5);color:#f0d99a}
  #controls .info{width:100%;text-align:center;opacity:.7;font-size:11px;letter-spacing:.04em;margin-top:2px;color:#9fb1d6}

  /* flight status */
  #status{top:90px;right:24px;width:300px;max-height:70vh;overflow:auto;padding:16px 18px}
  #status h3{font-size:10px;letter-spacing:.32em;text-transform:uppercase;color:var(--cyan);margin:0 0 12px}
  .fl{display:flex;justify-content:space-between;gap:10px;padding:8px 0;border-bottom:1px solid rgba(140,170,230,.1);cursor:pointer}
  .fl:last-child{border-bottom:none}
  .fl:hover{background:rgba(140,170,230,.07)}
  .fl .cs{color:#eef3ff;font-weight:600;font-size:13px}
  .fl .det{color:var(--muted);font-size:11px;text-align:right;line-height:1.4}

  /* AI panel */
  #ai{top:90px;right:24px;width:344px;max-height:74vh;display:flex;flex-direction:column;gap:11px;padding:16px 18px}
  #ai h3{font-size:10px;letter-spacing:.32em;text-transform:uppercase;color:var(--cyan);margin:0}
  #aiLog{overflow:auto;max-height:48vh;display:flex;flex-direction:column;gap:9px;font-size:13px;line-height:1.5}
  .aiMsg{padding:9px 11px;border-radius:11px;max-width:100%;white-space:pre-wrap;word-wrap:break-word}
  .aiMsg.user{background:rgba(143,211,255,.14);color:#eaf3ff;align-self:flex-end}
  .aiMsg.bot{background:rgba(16,24,42,.72);color:#dbe6ff;border:1px solid var(--edge)}
  #aiInputRow{display:flex;gap:7px}
  #aiInput{flex:1;background:rgba(8,12,22,.7);color:#eaf3ff;border:1px solid var(--edge);
    border-radius:10px;padding:9px 11px;font-size:13px;font-family:var(--sans)}
  #aiInput:focus{outline:none;border-color:var(--cyan)}
  #aiSend,#aiSurprise{border-radius:10px;padding:9px 13px;cursor:pointer;font-size:12px;
    letter-spacing:.04em;border:1px solid rgba(143,211,255,.4);background:rgba(143,211,255,.16);color:#eaf3ff}
  #aiSurprise{width:100%;border-color:rgba(233,196,106,.5);background:rgba(233,196,106,.16);color:#f0d99a}
  #ai.ai-open{opacity:1;pointer-events:auto}

  /* fun-fact / wonder card */
  #fact{bottom:88px;left:28px;width:340px;padding:16px 20px}
  #fact .kick{font-size:10px;letter-spacing:.34em;text-transform:uppercase;color:var(--gold);
    display:flex;align-items:center;gap:9px;margin-bottom:9px}
  #fact .kick:before{content:'';width:16px;height:1px;background:var(--gold)}
  #factText{font-family:var(--serif);font-size:17px;line-height:1.5;color:#e3ecff;font-style:italic;
    transition:opacity .8s ease}

  /* sound + altitude legend */
  #sound{bottom:22px;right:24px;display:flex;align-items:center;gap:9px;font-size:11px;
    letter-spacing:.06em;color:#9fb1d6}
  #sound button{background:transparent;color:#cdd9f5;border:1px solid rgba(140,170,230,.24);
    border-radius:999px;padding:6px 13px;cursor:pointer;font-size:11px;letter-spacing:.08em;text-transform:uppercase}
  #legend{bottom:60px;right:24px;font-size:10px;letter-spacing:.06em;color:var(--muted);
    display:flex;gap:12px;align-items:center}
  .badge{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:5px;vertical-align:middle}

  #hint{position:fixed;bottom:14px;left:50%;transform:translateX(-50%);z-index:20;font-size:11px;
    letter-spacing:.1em;color:rgba(200,220,255,.5);opacity:1;transition:opacity 1s;pointer-events:none}

  /* map modal */
  #mapModal{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:50;display:none;align-items:center;justify-content:center}
  #mapBox{background:var(--glass);border:1px solid var(--edge);border-radius:16px;width:min(92vw,560px);
    padding:16px;backdrop-filter:blur(16px)}
  #map{height:340px;border-radius:10px;margin:10px 0}
  #mapBox h3{margin:0 0 4px;font-family:var(--serif);font-size:18px;color:#eef3ff;letter-spacing:.04em}
  #mapBox .presets{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:4px}
  #mapBox .presets button{background:rgba(140,170,230,.12);color:#cdd9f5;border:1px solid var(--edge);
    border-radius:999px;padding:6px 12px;cursor:pointer;font-size:11px;letter-spacing:.06em}
  #mapBox .row{display:flex;justify-content:flex-end;gap:8px;margin-top:6px}
  #mapBox .row button{padding:8px 16px;border-radius:10px;cursor:pointer;border:1px solid var(--edge);font-size:12px}
  #useLoc{background:rgba(143,211,255,.18);color:#eaf3ff;border-color:rgba(143,211,255,.5)}

  /* light theme */
  body.light{background:#cfe0ff;color:#16335f}
  body.light .panel,body.light #mapBox{background:rgba(255,255,255,.78);border-color:#b9cbe6}
  body.light #title .brand,body.light #clock .time,body.light #status h3,body.light #ai h3{color:#1f4a86}
  body.light #title .sub,body.light #clock .day,body.light #clock .asof,body.light .fl .det,body.light #legend{color:#4a6191}
  body.light #clock .date,body.light .fl .cs,body.light #factText,body.light #aiInput{color:#16335f}
  body.light .aiMsg.user{background:rgba(31,74,134,.12)}
  body.light .aiMsg.bot{background:rgba(255,255,255,.85);border-color:#b9cbe6;color:#16335f}
  body.light #controls button,body.light #sound button{background:transparent;color:#1f4a86;border-color:#b9cbe6}
  body.light #controls button.on{background:rgba(233,196,106,.22);border-color:var(--gold);color:#7a5a16}
  body.light #mapBox h3,body.light #mapBox .presets button,body.light #sound{color:#1f4a86}
</style>
</head>
<body>
<canvas id="sky"></canvas>

<div id="title" class="ui">
  <div class="brand">SkyGaze</div>
  <div class="rule"></div>
  <div class="sub" id="tSub">Marina Beach · Chennai</div>
</div>

<div id="clock" class="ui">
  <div class="time" id="cTime">--:--:--</div>
  <div class="day" id="cDay">--</div>
  <div class="date" id="cDate">--</div>
  <div class="asof" id="cAsof">as of --</div>
</div>

<div id="status" class="ui panel"></div>

<div id="fact" class="ui panel">
  <div class="kick">Tonight's Wonder</div>
  <div id="factText">The light you see from these stars began its journey long before tonight — some of it before you were born.</div>
</div>

<div id="ai" class="ui panel">
  <h3>Ask the sky</h3>
  <div id="aiLog"></div>
  <div id="aiInputRow">
    <input id="aiInput" type="text" placeholder="Ask about a star, the Moon, a flight…" autocomplete="off">
    <button id="aiSend">Send</button>
  </div>
  <button id="aiSurprise">✨ What's overhead right now?</button>
</div>

<div id="controls" class="ui panel">
  <button id="bSky" class="on">Sky</button>
  <button id="bRadar">Radar</button>
  <button id="bFlip">Ceiling flip</button>
  <button id="bConst" class="on">Lines</button>
  <button id="bLabels" class="on">Stars</button>
  <button id="bStatus">Status</button>
  <button id="bSound">Sound</button>
  <button id="bTheme">Light</button>
  <button id="bLoc">Location</button>
  <button id="bAI">Ask AI</button>
  <button id="bFull">Full</button>
  <button id="bRefresh">Refresh</button>
  <span class="info" id="info"></span>
</div>

<div id="sound" class="ui">
  <button id="bSound">Sound: off</button>
  <input id="vol" type="range" min="0" max="100" value="45">
</div>

<div id="legend" class="ui">
  <span><span class="badge" style="background:#7CFC8A"></span>low</span>
  <span><span class="badge" style="background:#FFE066"></span>mid</span>
  <span><span class="badge" style="background:#FF9F45"></span>high</span>
  <span><span class="badge" style="background:#FF6B6B"></span>cruise</span>
</div>

<div id="hint">move to reveal · A ask · click a plane to explain · L stars · C lines · S sound</div>

<div id="mapModal">
  <div id="mapBox">
    <h3>Choose your location</h3>
    <div class="presets">
      <button data-lat="13.0500" data-lon="80.2824">Marina Beach, Chennai</button>
    </div>
    <div id="map"></div>
    <div class="row">
      <button id="cancelLoc">Cancel</button>
      <button id="useLoc">Use this location</button>
    </div>
  </div>
</div>

<script>
const SCENE = __SCENE__;
const CFG = __CONFIG__;
let mode='sky', flip=false, showConst=true, showLabels=true, showStatus=false, theme='dark';
let obs = {lat:SCENE.observer.lat, lon:SCENE.observer.lon, city:''};
let planes=[]; let selected=null; let lastAsof='';
let soundOn=false, masterVol=0.45, announced=new Set();
let prevPlanes=[], prevMap={}, curT=null, prevT=null, dispPlanes=[];
let lastFetch=Date.now();

const THEME = {
  dark:{ bg1:'#05070f',bg2:'#05070f',ring:'rgba(90,140,220,.5)',ringFaint:'rgba(80,120,200,.22)',
    card:'rgba(150,190,255,.7)',star:'#ffffff',starGlow:'rgba(255,255,255,.95)',
    cons:'rgba(140,175,255,.32)',label:'rgba(206,222,255,.9)',moon:'#d7d7d7',
    planetLabel:'rgba(230,235,255,.9)',planeStroke:'rgba(0,0,0,0)'},
  light:{ bg1:'#eaf3ff',bg2:'#cfe1ff',ring:'rgba(40,90,150,.55)',ringFaint:'rgba(40,90,150,.25)',
    card:'#16335f',star:'#15315c',starGlow:'rgba(255,255,255,.95)',
    cons:'rgba(40,80,150,.4)',label:'rgba(20,45,90,.95)',moon:'#5b6b82',
    planetLabel:'rgba(20,45,90,.95)',planeStroke:'rgba(12,28,56,.95)'}
};
const TH=()=>THEME[theme];

const cv=document.getElementById('sky'), ctx=cv.getContext('2d');
let W=0,H=0,DPR=Math.min(window.devicePixelRatio||1,2);
function resize(){W=window.innerWidth;H=window.innerHeight;cv.style.width=W+'px';cv.style.height=H+'px';cv.width=W*DPR;cv.height=H*DPR;ctx.setTransform(DPR,0,0,DPR,0,0);}
window.addEventListener('resize',()=>{resize();render();}); resize();

function rad(d){return d*Math.PI/180;}
function altColor(altm){ if(altm<2000)return '#7CFC8A'; if(altm<6000)return '#FFE066'; if(altm<11000)return '#FF9F45'; return '#FF6B6B';}
function domeXY(az,alt,cx,cy,R){ const r=R*(1-alt/90); return [cx+r*Math.sin(rad(az)), cy-r*Math.cos(rad(az))]; }

function planeGlyph(x,y,track,scale,fill,stroke,glow,label,sub){
  ctx.save();ctx.translate(x,y);ctx.rotate(rad(track));
  ctx.beginPath();
  ctx.moveTo(0,-7*scale); ctx.lineTo(2*scale,-1*scale); ctx.lineTo(7*scale,2*scale);
  ctx.lineTo(2*scale,1.5*scale); ctx.lineTo(2*scale,5*scale); ctx.lineTo(5*scale,7*scale);
  ctx.lineTo(0,5.5*scale); ctx.lineTo(-5*scale,7*scale); ctx.lineTo(-2*scale,5*scale);
  ctx.lineTo(-2*scale,1.5*scale); ctx.lineTo(-7*scale,2*scale); ctx.lineTo(-2*scale,-1*scale);
  ctx.closePath();
  ctx.fillStyle=fill; if(glow){ctx.shadowColor=glow;ctx.shadowBlur=14;} ctx.fill(); ctx.shadowBlur=0;
  if(stroke){ctx.lineWidth=1.3;ctx.strokeStyle=stroke;ctx.stroke();}
  ctx.restore();
  if(label){ctx.fillStyle=theme==='dark'?'rgba(223,234,255,.92)':'rgba(13,35,71,.95)';ctx.font='10px -apple-system,Segoe UI,sans-serif';ctx.textAlign='center';ctx.textBaseline='middle';
    ctx.fillText(label,x,y+16*scale);
    if(sub){ctx.fillStyle=theme==='dark'?'rgba(190,210,255,.72)':'rgba(20,45,90,.82)';ctx.font='9px -apple-system,Segoe UI,sans-serif';ctx.fillText(sub,x,y+28*scale);}}
}

function mixColor(a,b,t){return [Math.round(a[0]+(b[0]-a[0])*t),Math.round(a[1]+(b[1]-a[1])*t),Math.round(a[2]+(b[2]-a[2])*t)];}
function rgb(c){return 'rgb('+c[0]+','+c[1]+','+c[2]+')';}
function skyBrightness(){ const a=SCENE.sun? SCENE.sun.alt : -10; return Math.max(0,Math.min(1,(a+6)/18)); }

function drawMoon(x,y,r,illum,vis){
  ctx.save(); ctx.globalAlpha=vis;
  ctx.beginPath();ctx.arc(x,y,r,0,7);ctx.fillStyle=TH().moon;ctx.fill();
  const a=illum*2-1;
  ctx.beginPath();ctx.arc(x,y,r,Math.PI/2,-Math.PI/2,false);
  if(a>0)ctx.ellipse(x,y,r*(1-a),r,0,-Math.PI/2,Math.PI/2,true);
  else ctx.ellipse(x,y,r*(1+a),r,0,-Math.PI/2,Math.PI/2,false);
  ctx.closePath();ctx.fillStyle=theme==='dark'?'rgba(5,7,15,.97)':'rgba(220,233,255,.96)';ctx.fill();
  ctx.restore();
}

function bgFill(){
  const b=skyBrightness();
  const top=mixColor([5,7,15],[40,120,230],b);
  const mid=mixColor([14,34,72],[120,180,250],b);
  let hor = (b>0.15&&b<0.5) ? (b<0.32?[252,150,70]:[255,170,95]) : mixColor([10,22,55],[150,200,255],b);
  const g=ctx.createLinearGradient(0,0,0,H);
  g.addColorStop(0,rgb(top)); g.addColorStop(0.7,rgb(mid)); g.addColorStop(1,rgb(hor));
  ctx.fillStyle=g; ctx.fillRect(0,0,W,H);
}

function horizonGlow(){
  const b=skyBrightness(); if(b<0.1||b>0.55)return;
  const cx=W/2,cy=H/2,R=Math.min(W,H)*0.46;
  const[x,y]=domeXY(SCENE.sun.az,0,cx,cy,R);
  const inten=Math.max(0,1-Math.abs(b-0.3)/0.25);
  const g=ctx.createRadialGradient(x,y,0,x,y,R*0.95);
  g.addColorStop(0,'rgba(255,150,60,'+(0.35*inten).toFixed(3)+')');
  g.addColorStop(0.4,'rgba(255,120,40,'+(0.12*inten).toFixed(3)+')');
  g.addColorStop(1,'rgba(255,120,40,0)');
  ctx.fillStyle=g; ctx.fillRect(0,0,W,H);
}

// constellation name lookup (member star -> constellation)
const CONS_NAME={
  Dubhe:'Ursa Major',Merak:'Ursa Major',Phecda:'Ursa Major',Megrez:'Ursa Major',Alioth:'Ursa Major',Mizar:'Ursa Major',Alkaid:'Ursa Major',
  Betelgeuse:'Orion',Bellatrix:'Orion',Alnitak:'Orion',Alnilam:'Orion',Mintaka:'Orion',Saiph:'Orion',Rigel:'Orion',
  Caph:'Cassiopeia',Schedar:'Cassiopeia',GammaCas:'Cassiopeia',Ruchbah:'Cassiopeia',Segin:'Cassiopeia',
  Deneb:'Cygnus',Sadr:'Cygnus',Gienah:'Cygnus',DeltaCyg:'Cygnus',Albireo:'Cygnus',
  Regulus:'Leo',Algieba:'Leo',Zosma:'Leo',Chort:'Leo',Denebola:'Leo',
  Acrux:'Crux',Mimosa:'Crux',Gacrux:'Crux',Imai:'Crux',
  Kochab:'Ursa Minor',Pherkad:'Ursa Minor',Polaris:'Ursa Minor',
  Arcturus:'Bootes',Izar:'Bootes',Muphrid:'Bootes',Kornephoros:'Bootes',Nekkar:'Bootes',
  Vega:'Lyra',Sheliak:'Lyra',Sulafat:'Lyra',ZetaLyr:'Lyra',
  Tarazed:'Aquila',Altair:'Aquila',Alshain:'Aquila',
  Markab:'Pegasus',Scheat:'Pegasus',Alpheratz:'Pegasus',Algenib:'Pegasus',Enif:'Pegasus',
  Mirach:'Andromeda',Almach:'Andromeda',
  Dschubba:'Scorpius',Acrab:'Scorpius',PiSco:'Scorpius',DeltaSco:'Scorpius',Antares:'Scorpius',Shaula:'Scorpius',Lesath:'Scorpius',Sargas:'Scorpius',
  KausBorealis:'Sagittarius',KausMedia:'Sagittarius',KausAustralis:'Sagittarius',Ascella:'Sagittarius',Nunki:'Sagittarius',Albaldah:'Sagittarius',Rukbat:'Sagittarius',
  Sirius:'Canis Major',Mirzam:'Canis Major',Wezen:'Canis Major',Adhara:'Canis Major',Aludra:'Canis Major',
  Aldebaran:'Taurus',Elnath:'Taurus',Alcyone:'Taurus',
  Castor:'Gemini',Pollux:'Gemini',Alhena:'Gemini',Mebsuta:'Gemini',Wasat:'Gemini',
  Capella:'Auriga',Menkalinan:'Auriga',
  Procyon:'Canis Minor',Gomeisa:'Canis Minor',
  Spica:'Virgo',Zaniah:'Virgo',Porrima:'Virgo',Vindemiatrix:'Virgo',
  RigilKent:'Centaurus',Hadar:'Centaurus',
  Alphecca:'Corona Borealis',Nusakan:'Corona Borealis',ThetaCrB:'Corona Borealis',
  Rasalhague:'Ophiuchus',RasAlgethi:'Ophiuchus',
  Achernar:'Eridanus',Fomalhaut:'Piscis Austrinus'
};
let CONS_GROUPS=[];
function buildConsGroups(){
  const stars=SCENE.stars, lines=SCENE.lines;
  const parent=stars.map((_,i)=>i);
  const find=x=>{while(parent[x]!==x){parent[x]=parent[parent[x]];x=parent[x];}return x;};
  const uni=(a,b)=>{parent[find(a)]=find(b);};
  for(const [a,b] of lines) uni(a,b);
  const comp={};
  stars.forEach((s,i)=>{ if(s.alt<=0)return; const r=find(i); (comp[r]=comp[r]||[]).push(i); });
  CONS_GROUPS=Object.values(comp).filter(g=>g.length>=3 && g.some(i=>CONS_NAME[stars[i].name]));
}

function drawSun(){
  const a=SCENE.sun? SCENE.sun.alt : -10; if(a< -6)return;
  const cx=W/2,cy=H/2,R=Math.min(W,H)*0.46;
  const[x,y]=domeXY(SCENE.sun.az,Math.max(a,0),cx,cy,R);
  const b=skyBrightness();
  const glow=ctx.createRadialGradient(x,y,2,x,y,70);
  glow.addColorStop(0,'rgba(255,240,180,0.95)');
  glow.addColorStop(0.3,'rgba(255,210,120,0.5)');
  glow.addColorStop(1,'rgba(255,200,100,0)');
  ctx.fillStyle=glow; ctx.beginPath(); ctx.arc(x,y,70,0,7); ctx.fill();
  ctx.fillStyle='rgba(255,250,220,'+(0.85+0.15*Math.sin(Date.now()/900)).toFixed(2)+')';
  ctx.beginPath(); ctx.arc(x,y,15,0,7); ctx.fill();
  ctx.fillStyle=b>0.4?'rgba(40,60,90,.9)':'rgba(255,235,190,.95)';
  ctx.font='11px Georgia, serif'; ctx.textAlign='left'; ctx.textBaseline='middle';
  ctx.fillText('Sun '+a.toFixed(0)+'°',x+18,y);
}

function drawSky(){
  const t=TH(); const cx=W/2,cy=H/2,R=Math.min(W,H)*0.62;
  const b=skyBrightness();
  bgFill(); horizonGlow();
  if(flip){ctx.save();ctx.translate(W,H);ctx.rotate(Math.PI);}
  // corner filler stars (no wasted dark space at night)
  if(b<0.5){
    ctx.save();ctx.globalAlpha=(0.5-b)*0.8;ctx.fillStyle=t.star;
    let seed=1; const rnd=()=>{seed=(seed*9301+49297)%233280;return seed/233280;};
    for(let i=0;i<140;i++){const x=rnd()*W,y=rnd()*H;const rr=Math.hypot(x-cx,y-cy);
      if(rr<R*0.98)continue; const s=rnd()*1.1+0.2;
      ctx.beginPath();ctx.arc(x,y,s,0,7);ctx.fill();}
    ctx.restore();
  }
  if(flip){ctx.save();ctx.translate(W,H);ctx.rotate(Math.PI);}

  // faint horizon ring + cardinal reference (observation-deck aid)
  if(b<0.62){
    ctx.save();
    ctx.strokeStyle='rgba(150,180,240,'+(0.10*(1-b)).toFixed(3)+')';
    ctx.lineWidth=1; ctx.beginPath(); ctx.arc(cx,cy,R,0,7); ctx.stroke();
    ctx.fillStyle='rgba(175,198,245,'+(0.5*(1-b)).toFixed(3)+')';
    ctx.font='11px Georgia, serif'; ctx.textAlign='center'; ctx.textBaseline='middle';
    for(const [az,lab] of [[0,'N'],[90,'E'],[180,'S'],[270,'W']]){
      const [x,y]=domeXY(az,0,cx,cy,R); ctx.fillText(lab,x,y);
    }
    ctx.restore();
  }

  // constellation lines + names
  if(showConst){
    ctx.strokeStyle='rgba(140,175,255,'+(0.32*(1-b)).toFixed(2)+')'; ctx.lineWidth=1;
    for(const[a,b2]of SCENE.lines){const s1=SCENE.stars[a],s2=SCENE.stars[b2];
      if(s1.alt<=0||s2.alt<=0)continue;
      const[x1,y1]=domeXY(s1.az,s1.alt,cx,cy,R),[x2,y2]=domeXY(s2.az,s2.alt,cx,cy,R);
      ctx.beginPath();ctx.moveTo(x1,y1);ctx.lineTo(x2,y2);ctx.stroke();}
    ctx.save();
    ctx.fillStyle='rgba(233,196,106,'+(0.55*(1-b)).toFixed(3)+')';
    ctx.font='11px Georgia, serif'; ctx.textAlign='center'; ctx.textBaseline='middle';
    if(ctx.letterSpacing!==undefined) ctx.letterSpacing='2px';
    for(const g of CONS_GROUPS){
      let ax=0,ay=0,n=0;
      for(const i of g){ const s=SCENE.stars[i]; const [x,y]=domeXY(s.az,s.alt,cx,cy,R); ax+=x; ay+=y; n++; }
      ax/=n; ay/=n;
      const rep=g.find(i=>CONS_NAME[SCENE.stars[i].name]);
      if(rep!==undefined){ ctx.fillText(CONS_NAME[SCENE.stars[rep].name].toUpperCase(), ax, ay); }
    }
    ctx.restore();
  }

  // stars + their names (helpful, on by default)
  const tw=Date.now()/700;
  const starVis=Math.max(0.03,1-b);
  for(const s of SCENE.stars){ if(s.alt<=0)continue;
    const[x,y]=domeXY(s.az,s.alt,cx,cy,R);
    const size=Math.max(0.7,3.2-s.mag*0.9);
    ctx.save();ctx.globalAlpha=starVis*tw;ctx.shadowColor=t.starGlow;ctx.shadowBlur=size*2.6;ctx.fillStyle=t.star;
    ctx.beginPath();ctx.arc(x,y,size,0,7);ctx.fill();ctx.restore();
  }
  if(showLabels){
    ctx.save(); ctx.globalAlpha=starVis; ctx.fillStyle=t.label;
    ctx.font='10px Georgia, serif'; ctx.textAlign='left'; ctx.textBaseline='middle';
    for(const s of SCENE.stars){ if(s.alt<=0||s.mag>2.4)continue;
      const[x,y]=domeXY(s.az,s.alt,cx,cy,R);
      const sz=Math.max(0.7,3.2-s.mag*0.9);
      ctx.fillText(s.name.toUpperCase(), x+sz+5, y);
    }
    ctx.restore();
  }

  drawSun();
  const m=SCENE.moon; if(m.alt>0){const[x,y]=domeXY(m.az,m.alt,cx,cy,R);drawMoon(x,y,11,m.illum,Math.max(0.06,1-b*0.9));}
  for(const p of SCENE.planets){ if(p.alt<=0)continue;
    const[x,y]=domeXY(p.az,p.alt,cx,cy,R);
    ctx.fillStyle=p.color;ctx.beginPath();ctx.arc(x,y,4,0,7);ctx.fill();
    ctx.fillStyle=t.planetLabel;ctx.font='11px Georgia, serif';ctx.textAlign='left';ctx.textBaseline='middle';ctx.fillText(p.name,x+7,y);}
  for(const p of dispPlanes){ if(p.elev<=0)continue;
    const[x,y]=domeXY(p.az,p.elev,cx,cy,R); const col=altColor(p.alt);
    const label=p.airline||p.callsign;
    const sub=(p.route||'bound '+compass(p.track))+(p.vr>1.5?' ▲':(p.vr<-1.5?' ▼':''));
    if(selected===p.icao){ctx.strokeStyle='#ffffff';ctx.lineWidth=2;ctx.beginPath();ctx.arc(x,y,16,0,7);ctx.stroke();}
    if(p.approaching){ const pulse=0.5+0.5*Math.sin(Date.now()/260);
      ctx.strokeStyle='rgba(255,196,92,'+(0.45+0.45*pulse).toFixed(3)+')'; ctx.lineWidth=2.2;
      ctx.beginPath();ctx.arc(x,y,13,0,7);ctx.stroke();
      ctx.fillStyle='rgba(255,210,130,.95)';ctx.font='11px Georgia,serif';ctx.textAlign='center';ctx.textBaseline='middle';
      ctx.fillText('→ '+p.approachRate+' km',x,y-22*1.2);
    }
    planeGlyph(x,y,p.track,1.2,col,t.planeStroke,col,label,(Math.round(p.alt*3.281))+'ft · '+sub);}
  if(flip)ctx.restore();
}
function compass(deg){const d=['N','NE','E','SE','S','SW','W','NW'];return d[Math.round(deg/45)%8];}

function drawRadar(){
  const t=TH(); const cx=W/2,cy=H/2,R=Math.min(W,H)*0.62;
  bgFill();
  if(flip){ctx.save();ctx.translate(W,H);ctx.rotate(Math.PI);}
  ctx.strokeStyle=t.ringFaint;ctx.fillStyle=t.card;ctx.font='11px Georgia, serif';ctx.textAlign='center';ctx.textBaseline='middle';
  const maxR=CFG.radius;
  for(let i=1;i<=4;i++){const rr=R*i/4;ctx.beginPath();ctx.arc(cx,cy,rr,0,7);ctx.stroke();
    ctx.fillText((maxR*i/4).toFixed(0)+'km',cx,cy-rr-2);}
  for(let az=0;az<360;az+=30){const[x,y]=domeXY(az,0,cx,cy,R);
    ctx.strokeStyle=t.ringFaint;ctx.beginPath();ctx.moveTo(cx,cy);ctx.lineTo(x,y);ctx.stroke();
    const[lx,ly]=domeXY(az,4,cx,cy,R);ctx.fillStyle=t.card;ctx.fillText(az+'',lx,ly);}
  ctx.fillStyle=theme==='dark'?'#7CFC8A':'#1f7a4d';ctx.beginPath();ctx.arc(cx,cy,4,0,7);ctx.fill();
  const rng=R/maxR;
  for(const p of dispPlanes){ if(p.dist>maxR)continue;
    const[x,y]=domeXY(p.az,0,cx,cy,R);
    const px=cx+(x-cx)*(p.dist/maxR), py=cy+(y-cy)*(p.dist/maxR); const col=altColor(p.alt);
    const label=p.airline||p.callsign;
    if(selected===p.icao){ctx.strokeStyle='#fff';ctx.lineWidth=2;ctx.beginPath();ctx.arc(px,py,16,0,7);ctx.stroke();}
    if(p.approaching){ const pulse=0.5+0.5*Math.sin(Date.now()/260);
      ctx.strokeStyle='rgba(255,196,92,'+(0.45+0.45*pulse).toFixed(3)+')'; ctx.lineWidth=2.2;
      ctx.beginPath();ctx.arc(px,py,13,0,7);ctx.stroke();
    }
    planeGlyph(px,py,p.track,1.2,col,t.planeStroke,col,label,(Math.round(p.alt*3.281))+'ft · '+p.dist.toFixed(0)+'km');}
  if(flip)ctx.restore();
}

function render(){ if(mode==='sky')drawSky(); else drawRadar(); }

function fmtStatus(){
  const el=document.getElementById('status');
  if(!showStatus){el.style.display='none';return;}
  el.style.display='block';
  const su=SCENE.sun||{}, mo=SCENE.moon||{};
  let h='<h3>Sky &amp; Flights ('+planes.length+')</h3>';
  h+='<div class="fl"><span class="cs">☀ Sun</span><span class="det">rise '+su.rise+' · set '+su.set+'</span></div>';
  h+='<div class="fl"><span class="cs">☾ Moon ('+(mo.phase||'')+')</span><span class="det">rise '+mo.rise+' · set '+mo.set+'</span></div>';
  h+='<div style="height:8px"></div>';
  const sorted=planes.slice().sort((a,b)=> (b.approaching?1:0)-(a.approaching?1:0) || a.dist-b.dist);
  for(const p of sorted){
    const vr=p.vr>1.5?'CLIMB':(p.vr<-1.5?'DESC':'LEVEL');
    const where=p.route||('bound '+compass(p.track));
    const appr=p.approaching?' <span style="color:#ffc46a">▸ approaching −'+p.approachRate+'km</span>':'';
    h+='<div class="fl" data-icao="'+p.icao+'"><span class="cs">'+p.callsign+(p.airline?' <span style="opacity:.6">'+p.airline+'</span>':'')+'</span>'+
       '<span class="det">'+where+appr+'<br>'+
       Math.round(p.alt*3.281).toLocaleString()+'ft '+Math.round(p.speed)+
       'km/h '+vr+' '+p.dist.toFixed(0)+'km</span></div>';
  }
  el.innerHTML=h;
  el.querySelectorAll('.fl').forEach(d=>d.onclick=()=>{if(d.dataset.icao){selected=d.dataset.icao;render(); explainFlight(d.dataset.icao);}});
}

// ---- audio: soothing pentatonic chimes on overhead arrival ----
let actx=null, masterGain=null;
const SCALE=[220.00,261.63,293.66,329.63,392.00,440.00];
function ensureAudio(){ if(!actx){actx=new (window.AudioContext||window.webkitAudioContext)();masterGain=actx.createGain();masterGain.gain.value=masterVol;masterGain.connect(actx.destination);} if(actx.state==='suspended')actx.resume(); }
function chime(alt){
  if(!soundOn||!actx)return;
  const idx=Math.max(0,Math.min(SCALE.length-1,Math.floor(alt/4000)));
  const f=SCALE[idx];
  const o=actx.createOscillator(),g=actx.createGain();
  o.type='sine';o.frequency.value=f;
  const t0=actx.currentTime;
  g.gain.setValueAtTime(0,t0);g.gain.linearRampToValueAtTime(0.9,t0+0.03);
  g.gain.exponentialRampToValueAtTime(0.001,t0+1.6);
  o.connect(g);g.connect(masterGain);o.start(t0);o.stop(t0+1.7);
}
// distinct gentle rising two-note tone when a flight begins approaching
function approachTone(){
  if(!soundOn||!actx)return;
  const t0=actx.currentTime;
  [ [329.63,0.0], [493.88,0.22] ].forEach(([f,dt])=>{
    const o=actx.createOscillator(),g=actx.createGain();
    o.type='triangle';o.frequency.value=f;
    const s=t0+dt;
    g.gain.setValueAtTime(0,s);g.gain.linearRampToValueAtTime(0.55,s+0.03);
    g.gain.exponentialRampToValueAtTime(0.001,s+0.5);
    o.connect(g);g.connect(masterGain);o.start(s);o.stop(s+0.55);
  });
}
const OVERHEAD=35;
let approachAnnounced=new Set();
function checkSounds(){
  if(!soundOn)return;
  for(const p of dispPlanes){
    if(p.elev>OVERHEAD){ if(!announced.has(p.icao)){announced.add(p.icao);chime(p.alt);} }
    else announced.delete(p.icao);
  }
  // approach alert: fire once when a flight starts closing in
  const cur=new Set();
  for(const p of planes){ if(p.approaching){ cur.add(p.icao);
    if(!approachAnnounced.has(p.icao)) approachTone();
  }}
  approachAnnounced=cur;
}

// ---- data ----
function fetchScene(){
  fetch('/scene?lat='+obs.lat+'&lon='+obs.lon).then(r=>r.json()).then(d=>{
    SCENE.stars=d.stars;SCENE.lines=d.lines;SCENE.moon=d.moon;SCENE.planets=d.planets;SCENE.utc=d.utc;
    buildConsGroups();
    if(!factStarted){ factStarted=true; fetchFunFact(); setInterval(fetchFunFact,75000); }
    render();
  }).catch(()=>{});
}
function fetchPlanes(){
  fetch('/planes?lat='+obs.lat+'&lon='+obs.lon).then(r=>r.json()).then(d=>{
    // compute approaching state: compare to previously-seen distance per icao
    const prevDist={};
    for(const p of planes) prevDist[p.icao]=p.dist;
    const now=Date.now();
    for(const p of d){
      const pd=prevDist[p.icao];
      if(pd!=null && isFinite(pd)){
        const dkm=pd - p.dist;                 // +ve = got closer
        p.approaching = dkm > 0.4;            // meaningful closure (>~0.4km/poll)
        p.approachRate = +dkm.toFixed(1);     // km closer this poll
      } else { p.approaching=false; p.approachRate=0; }
    }
    prevPlanes=planes.map(p=>[p.icao,p.az,p.elev,p.alt,p.dist,p.track,p.vr,p.speed]);
    prevMap={}; for(const p of planes) prevMap[p.icao]=p;
    planes=d; lastAsof=SCENE.utc.slice(11,19);
    lastFetch=Date.now();
    curT=performance.now(); if(!prevT)prevT=curT;
    const appr=d.filter(p=>p.approaching).length;
    document.getElementById('info').textContent=(obs.city?obs.city+', ':'')+'planes: '+planes.length+(appr?(' · '+appr+' approaching'):'')+' · data UTC '+lastAsof+' · refresh '+CFG.refresh+'s';
    fmtStatus();checkSounds();
  }).catch(()=>{});
}
// smoothly interpolate displayed planes between API polls
function lerp(a,b,t){return a+(b-a)*t;}
function dispStep(){
  if(curT&&prevT){
    const t=Math.min(1,(performance.now()-prevT)/(curT-prevT||1));
    const out=[];
    for(const p of planes){
      const pv=prevMap[p.icao];
      if(pv && !isNaN(pv.az)){
        let azd=p.az-pv.az; while(azd>180)azd-=360; while(azd<-180)azd+=360;
        const da=lerp(pv.az,pv.az+azd,t);
        const el=lerp(pv.elev,p.elev,t), al=lerp(pv.alt,p.alt,t),
              di=Math.abs(pv.dist)+ (Math.abs(p.dist)-Math.abs(pv.dist))*t,
              tr=lerp(pv.track,p.track,t), vr=lerp(pv.vr,p.vr,t), sp=lerp(pv.speed,p.speed,t);
        out.push({icao:p.icao,callsign:p.callsign,country:p.country,az:da,elev:el,alt:al,dist:Math.abs(di),track:tr,vr:vr,speed:sp});
      } else out.push(p);
    }
    dispPlanes=out;
    if(t>=1) prevT=curT;
  } else dispPlanes=planes;
  render();
  requestAnimationFrame(dispStep);
}

// ---- clock ----
const DAYS=['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
const MON=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
function tickClock(){
  const n=new Date();
  document.getElementById('cDay').textContent=DAYS[n.getDay()];
  document.getElementById('cDate').textContent=n.getDate()+' '+MON[n.getMonth()]+' '+n.getFullYear();
  document.getElementById('cTime').textContent=n.toLocaleTimeString();
  document.getElementById('cAsof').textContent='as of '+lastAsof+' UTC · next refresh in '+Math.max(0,CFG.refresh-Math.round((Date.now()-lastFetch)/1000))+'s';
}

// ---- controls ----
const $=id=>document.getElementById(id);
$('bSky').onclick=()=>{mode='sky';$('bSky').classList.add('on');$('bRadar').classList.remove('on');render();};
$('bRadar').onclick=()=>{mode='radar';$('bRadar').classList.add('on');$('bSky').classList.remove('on');render();};
$('bFlip').onclick=()=>{flip=!flip;$('bFlip').classList.toggle('on',flip);render();};
$('bConst').onclick=()=>{showConst=!showConst;$('bConst').classList.toggle('on',showConst);render();};
$('bLabels').onclick=()=>{showLabels=!showLabels;$('bLabels').classList.toggle('on',showLabels);render();};
$('bStatus').onclick=()=>{showStatus=!showStatus;$('bStatus').classList.toggle('on',showStatus);fmtStatus();};
$('bFull').onclick=()=>{if(!document.fullscreenElement)document.documentElement.requestFullscreen();else document.exitFullscreen();};
$('bRefresh').onclick=fetchPlanes;
$('bTheme').onclick=()=>{theme=theme==='dark'?'light':'dark';document.body.classList.toggle('light',theme==='light');$('bTheme').textContent=theme==='dark'?'Light':'Dark';render();};
$('bSound').onclick=()=>{soundOn=!soundOn;ensureAudio();$('bSound').textContent='Sound: '+(soundOn?'on':'off');$('bSound').classList.toggle('on',soundOn);if(!soundOn)announced.clear();};
$('vol').oninput=e=>{masterVol=e.target.value/100;if(masterGain)masterGain.gain.value=masterVol;};

// ---- immersive mode ----
let hintTimer=null;
function showUI(){ document.body.classList.add('showui'); const h=$('hint'); if(h)h.style.opacity='0'; clearTimeout(hintTimer); }
function scheduleHide(){ clearTimeout(hintTimer); hintTimer=setTimeout(()=>document.body.classList.remove('showui'),2600); }
let uiBusy=false;
window.onmousemove=()=>{ if(uiBusy)return; showUI(); scheduleHide(); };
window.addEventListener('keydown',e=>{
  const k=e.key.toLowerCase();
  if(k==='h'){ document.body.classList.toggle('showui'); const h=$('hint'); if(h)h.style.opacity='0'; if(document.body.classList.contains('showui'))scheduleHide(); }
  else if(k==='c'){ showConst=!showConst; $('bConst').classList.toggle('on',showConst); render(); }
  else if(k==='l'){ showLabels=!showLabels; $('bLabels').classList.toggle('on',showLabels); render(); }
  else if(k==='f'){ $('bFull').click(); }
  else if(k==='s'){ $('bSound').click(); }
  else if(k==='a'){ toggleAI(); }
} );
document.addEventListener('mouseleave',()=>document.body.classList.remove('showui'));

// ---- location map ----
let map=null,marker=null,mapInited=false;
function applyLoc(lat,lon,city){ obs={lat:+lat,lon:+lon,city:city||''}; fetchScene(); fetchPlanes(); $('info').textContent=(city?city+', ':'')+'lat '+lat.toFixed(3)+', lon '+lon.toFixed(3); }
function openMap(){
  $('mapModal').style.display='flex'; uiBusy=true;
  if(!mapInited){
    map=L.map('map').setView([obs.lat,obs.lon],12);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:18}).addTo(map);
    marker=L.marker([obs.lat,obs.lon],{draggable:true}).addTo(map);
    map.on('click',e=>marker.setLatLng(e.latlng));
    mapInited=true;
  } else { map.setView([obs.lat,obs.lon],12); marker.setLatLng([obs.lat,obs.lon]); }
  setTimeout(()=>map.invalidateSize(),60);
}
function closeMap(){ $('mapModal').style.display='none'; uiBusy=false; }
$('bLoc').onclick=openMap;
$('cancelLoc').onclick=closeMap;
$('useLoc').onclick=()=>{const ll=marker.getLatLng();applyLoc(ll.lat,ll.lng,'');closeMap();};
document.querySelectorAll('#mapBox .presets button[data-lat]').forEach(b=>b.onclick=()=>{const la=+b.dataset.lat,lo=+b.dataset.lon;marker.setLatLng([la,lo]);map.setView([la,lo],12);});

// ---- AI assistant (server-side /ai/ask proxy; key never reaches the browser) ----
let aiOpen=false, aiBusy=false, aiMessages=[];
const aiLog=document.getElementById('aiLog');
let factStarted=false, factBusy=false;
function aiAdd(role,text){
  const d=document.createElement('div');
  d.className='aiMsg '+(role==='user'?'user':'bot');
  d.textContent=text;
  aiLog.appendChild(d); aiLog.scrollTop=aiLog.scrollHeight;
}
function toggleAI(){
  aiOpen=!aiOpen;
  $('ai').classList.toggle('ai-open',aiOpen);
  showUI();
  if(aiOpen){ scheduleHide(); $('aiInput').focus();
    if(!aiLog.childElementCount) aiAdd('bot','Ask me about a star, the Moon, or a flight — or hit “What’s overhead right now?” for a live tour.'); }
}
async function aiRaw(messages){
  try{
    const r=await fetch('/ai/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({messages})});
    const d=await r.json();
    return (d.choices&&d.choices[0]&&d.choices[0].message&&d.choices[0].message.content)||'';
  }catch(e){ return ''; }
}
async function aiSend(text){
  text=(text||'').trim(); if(!text||aiBusy)return;
  aiBusy=true;
  aiAdd('user',text); aiMessages.push({role:'user',content:text});
  const ans=await aiRaw(aiMessages.slice());
  aiBusy=false;
  const out=ans||'(no reply)';
  aiMessages.push({role:'assistant',content:out}); aiAdd('bot',out);
}
async function explainFlight(icao){
  const p=planes.find(x=>x.icao===icao) || (dispPlanes.find(x=>x.icao===icao));
  if(!p) return;
  selected=icao; render();
  aiOpen=true; $('ai').classList.add('ai-open'); showUI(); scheduleHide();
  const near = p.dist.toFixed(0);
  const bearing = (p.az).toFixed(0);
  const info =
    'A live aircraft is being tracked. Facts only:\n'+
    'Callsign: '+p.callsign+'\n'+
    'Airline: '+(p.airline||'unknown (callsign prefix not in table)')+'\n'+
    'Altitude: '+Math.round(p.alt*3.281).toLocaleString()+' ft ('+Math.round(p.alt)+' m)\n'+
    'Ground speed: '+Math.round(p.speed)+' km/h\n'+
    'Heading: '+p.track.toFixed(0)+'° ('+compass(p.track)+')\n'+
    'Vertical rate: '+(p.vr>1.5?'climbing':(p.vr<-1.5?'descending':'level'))+' ('+p.vr.toFixed(1)+' m/s)\n'+
    'Distance from observer: '+near+' km, bearing '+bearing+'°\n'+
    (p.approaching?('Trend: APPROACHING — closing at ~'+p.approachRate+' km per refresh.\n'):'Trend: roughly steady range.\n')+
    (p.route?('Published-style route guess from callsign: '+p.route+'.\n'):'No booked-route feed (OpenSky free has none); heading above is live.\n')+
    'Observer is at Marina Beach, Chennai (13.0500, 80.2824).';
  const sys='You are a calm, knowledgeable flight observer. Given ONLY the tracked-aircraft data, explain in ~110 words what this flight is and what it is doing. Mention the airline, altitude band (e.g. cruise/climb/descent), direction of travel, and whether it is coming closer to the observer. Do NOT invent a city pair unless the data gives a route. Plain friendly prose, no headers or markdown.';
  aiAdd('user','Explain this flight: '+p.callsign+' ('+near+' km, '+(p.airline||'')+')');
  aiMessages.push({role:'user',content:'Explain this flight.\n'+info});
  const ans=await aiRaw([{role:'system',content:sys},{role:'user',content:info}]);
  const out=ans||'(no reply)';
  aiMessages.push({role:'assistant',content:out}); aiAdd('bot',out);
}
function skyContext(){
  const s=SCENE, out=[];
  out.push('Location: '+(obs.city||'')+' ('+obs.lat.toFixed(4)+', '+obs.lon.toFixed(4)+').');
  out.push('Local time ~ '+new Date().toLocaleString()+'.');
  const su=s.sun||{}, mo=s.moon||{};
  out.push('Sun altitude '+su.alt.toFixed(1)+'°, rise '+su.rise+' set '+su.set+'.');
  out.push('Moon: '+(mo.phase||'?')+' ('+((mo.illum||0)*100).toFixed(0)+'% lit), altitude '+mo.alt.toFixed(1)+'°, rise '+mo.rise+' set '+mo.set+'.');
  const pl=(s.planets||[]).filter(p=>p.alt>0).sort((a,b)=>b.alt-a.alt);
  out.push('Planets above horizon: '+(pl.length?pl.map(p=>p.name+' ('+p.alt.toFixed(0)+'° alt)').join(', '):'none'));
  const st=(s.stars||[]).filter(x=>x.alt>0).sort((a,b)=>a.mag-b.mag).slice(0,12);
  out.push('Brightest stars up: '+st.map(x=>x.name+' (mag '+x.mag+')').join(', ')+'.');
  const pp=planes.slice().sort((a,b)=>a.dist-b.dist).slice(0,8);
  out.push('Nearest live flights: '+(pp.length?pp.map(p=>(p.airline||p.callsign)+' '+Math.round(p.alt*3.281)+'ft '+p.dist.toFixed(0)+'km').join('; '):'none'));
  return out.join('\n');
}
function skyContextShort(){
  const s=SCENE, out=[];
  const mo=s.moon||{};
  out.push('Moon: '+(mo.phase||'?')+' '+((mo.illum||0)*100).toFixed(0)+'% lit.');
  const pl=(s.planets||[]).filter(p=>p.alt>0).map(p=>p.name);
  if(pl.length) out.push('Planets up: '+pl.join(', ')+'.');
  const st=(s.stars||[]).filter(x=>x.alt>0).sort((a,b)=>a.mag-b.mag).slice(0,6).map(x=>x.name);
  if(st.length) out.push('Brightest stars up: '+st.join(', ')+'.');
  const pp=planes.slice().sort((a,b)=>a.dist-b.dist)[0];
  if(pp) out.push('A nearby flight: '+(pp.airline||pp.callsign)+' at '+Math.round(pp.alt*3.281)+' ft.');
  return out.join(' ');
}
async function surpriseMe(){
  if(aiBusy)return;
  aiOpen=true; $('ai').classList.add('ai-open'); showUI();
  aiAdd('user','✨ surprise me');
  const sys='You are a warm, curious night-sky guide talking to someone lying on their back looking straight up. Use ONLY the live data provided. Write a vivid ~140-word tour a beginner would love: name real stars/constellations/planets/Moon they can see, where to look, and one delightfully true fact. Plain friendly prose, no headers or markdown.';
  const ctx=skyContext();
  const ans=await aiRaw([{role:'system',content:sys},{role:'user',content:'Live sky right now:\n'+ctx+'\n\nGive me tonight’s tour.'}]);
  const out=ans||'(no reply)';
  aiMessages.push({role:'user',content:'✨ what’s overhead?'});
  aiMessages.push({role:'assistant',content:out});
  aiAdd('bot',out);
}
function setFact(text){
  const el=document.getElementById('factText');
  el.style.opacity='0';
  setTimeout(()=>{ el.textContent=text; el.style.opacity='1'; }, 450);
}
async function fetchFunFact(){
  if(factBusy)return; factBusy=true;
  const s=SCENE, out=[];
  const mo=s.moon; out.push("Moon: "+(mo.phase||'?')+' '+((mo.illum||0)*100).toFixed(0)+'% lit.');
  const pl=(s.planets||[]).filter(p=>p.alt>0).map(p=>p.name);
  if(pl.length) out.push("Planets up: "+pl.join(', ')+'.');
  const st=(s.stars||[]).filter(x=>x.alt>0).sort((a,b)=>a.mag-b.mag).slice(0,6).map(x=>x.name);
  if(st.length) out.push("Brightest stars up: "+st.join(', ')+'.');
  const appr=planes.filter(p=>p.approaching).sort((a,b)=>a.dist-b.dist).slice(0,2);
  if(appr.length) out.push("Flights approaching you: "+appr.map(p=>(p.airline||p.callsign)+' ('+p.dist.toFixed(0)+' km, closing '+p.approachRate+' km/refresh)').join('; ')+'.');
  const ctx=out.join(' ');
  const sys='You are a playful astronomy + aviation educator. Given live sky/aircraft data, share ONE delightful, TRUE, lesser-known fun fact (~25 words) about something currently visible or approaching. Plain prose, no quotes, no headers. If nothing notable, share a timeless sky fact.';
  const ans=await aiRaw([{role:'system',content:sys},{role:'user',content:'Now visible:\n'+ctx+'\nOne fun fact please.'}]);
  if(ans) setFact(ans.trim());
  factBusy=false;
}
$('bAI').onclick=toggleAI;
$('aiSend').onclick=()=>{const v=$('aiInput').value; $('aiInput').value=''; aiSend(v);};
$('aiInput').addEventListener('keydown',e=>{ if(e.key==='Enter'){const v=$('aiInput').value; $('aiInput').value=''; aiSend(v);} });
$('aiSurprise').onclick=surpriseMe;

// click a plane on the dome to select + let the AI explain it
cv.addEventListener('click',e=>{
  const rect=cv.getBoundingClientRect();
  const mx=e.clientX-rect.left, my=e.clientY-rect.top;
  let best=null, bestD=1e9;
  for(const p of dispPlanes){ if(p.elev<=0)continue;
    const [x,y]=domeXY(p.az,p.elev,W/2,H/2,Math.min(W,H)*0.62);
    const d=Math.hypot(x-mx,y-my);
    if(d<22 && d<bestD){bestD=d;best=p;}
  }
  if(best){ selected=best.icao; render(); explainFlight(best.icao); }
});

// init
$('tSub').textContent=(obs.city||'')+' · '+obs.lat.toFixed(4)+', '+obs.lon.toFixed(4);
render();fetchScene();fetchPlanes();tickClock();
requestAnimationFrame(dispStep);
setInterval(tickClock,1000);
setInterval(fetchPlanes,CFG.refresh*1000);
setInterval(fetchScene,120000);
setTimeout(()=>{try{document.documentElement.requestFullscreen();}catch(e){}},1200);
setTimeout(()=>{const h=$('hint'); if(h)h.style.opacity='0';},6000);
</script>
</body>
</html>
"""

def make_html():
    return HTML.replace("__SCENE__", json.dumps(build_scene())).replace("__CONFIG__", json.dumps({"radius": RADIUS_KM, "refresh": REFRESH_S, "openrouter": bool(openrouter_key())}))

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(parsed.query)
        if parsed.path == "/planes":
            try:
                lat = float(q["lat"][0]) if q.get("lat") else None
                lon = float(q["lon"][0]) if q.get("lon") else None
            except Exception:
                lat = lon = None
            self._json(json.dumps(get_planes(lat, lon)).encode())
        elif parsed.path == "/scene":
            try:
                lat = float(q["lat"][0]) if q.get("lat") else None
                lon = float(q["lon"][0]) if q.get("lon") else None
            except Exception:
                lat = lon = None
            self._json(json.dumps(build_scene(lat, lon)).encode())
        elif parsed.path == "/location":
            loc = get_location()
            if loc:
                body = json.dumps(loc).encode()
            else:
                with OBS_LOCK:
                    body = json.dumps(dict(OBS)).encode()
            self._json(body)
        else:
            body = make_html().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    def _json(self, body, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/ai/ask":
            self._ai_ask()
        else:
            self.send_error(405)

    def _ai_ask(self):
        """Server-side proxy to OpenRouter chat completions (FREE models only).

        The OpenRouter key stays on the server (read from config.json); it is
        NEVER exposed to the browser. Frontend POSTs
        {"messages":[...], "model":"<optional>"} and we forward it, trying
        DEFAULT_MODEL then FALLBACK_MODELS so a rate-limited/free model
        degrades gracefully instead of failing.
        """
        key = openrouter_key()
        if not key:
            self._json(json.dumps({"error": "no_openrouter_key",
                                   "hint": "set config.json openrouter_key"}).encode(),
                       status=503)
            return
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw or b"{}")
        except Exception:
            payload = {}
        messages = payload.get("messages") or []
        model = payload.get("model") or DEFAULT_MODEL
        cands = []
        if model != DEFAULT_MODEL:
            cands.append(model)
        cands.append(DEFAULT_MODEL)
        for fb in FALLBACK_MODELS:
            if fb not in cands:
                cands.append(fb)
        last_err = None
        for m in cands:
            data = {"model": m, "messages": messages, "stream": False}
            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/chat/completions",
                data=json.dumps(data).encode("utf-8"),
                headers={"Authorization": "Bearer " + key,
                         "Content-Type": "application/json",
                         "HTTP-Referer": "local",
                         "X-Title": "SkyGaze"},
                method="POST")
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    self._json(r.read())          # forward upstream JSON verbatim
                    return
            except urllib.error.HTTPError as e:
                last_err = e
                detail = b""
                try:
                    detail = e.read()
                except Exception:
                    pass
                if e.code in (400, 403, 404, 429):
                    continue                        # try next free model
                self._json(json.dumps({"error": "openrouter_http_%d" % e.code,
                                       "detail": detail.decode("utf-8", "replace")[:1000]}).encode(),
                           status=e.code)
                return
            except Exception as e:
                last_err = e
                continue
        self._json(json.dumps({"error": "all_models_failed",
                               "detail": str(last_err)}).encode(), status=502)
    def log_message(self, *a):
        pass

def main():
    print("Default location: %s (%.3f, %.3f) - use the in-app map picker to fine-tune." % (OBS["city"], OBS["lat"], OBS["lon"]))
    print("(Location is fixed to Chennai; no IP-based geolocation is used.)")
    url = "http://localhost:%d/" % PORT
    print("SkyGaze running -> %s" % url)
    print("Controls: SKY/RADAR, Ceiling flip, Location (Chennai map), Light theme, Sound, Fullscreen, Ask AI.")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("0.0.0.0", PORT), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nbye")

if __name__ == "__main__":
    main()
