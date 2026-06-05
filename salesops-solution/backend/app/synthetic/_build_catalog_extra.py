"""Procedural generator for catalog_extra.py.

Run with:
    python -m app.synthetic._build_catalog_extra > app/synthetic/catalog_extra.py

Output is a Python module exporting:
    CUSTOMERS_EXTRA          ~180 customers across AMS / EMEA / APAC / JP
    PRODUCTS_EXTRA           ~70 additional Keysight catalog SKUs
    DISTRIBUTORS             ~30 authorised distributor records
    MAGIC_SKUS               CUSTOM PRODUCT / SOWDUMMY / EXPORTDUMMY

The output is deterministic (seeded RNG) so repeat runs produce identical files,
making diffs reviewable.
"""
from __future__ import annotations

import pprint
import random
from datetime import date, timedelta
from typing import Any

# Deterministic seed so the generated file is reproducible
random.seed(20260513)

# ----------------------------------------------------------------------
# Region pools: realistic-looking company prefixes/suffixes per region
# ----------------------------------------------------------------------

AMS_COMPANIES = [
    ("Northstar Aerospace", "aerospace_defense", "ITAR", "USD"),
    ("Cascade Microwave", "semiconductor", "ISO_9001", "USD"),
    ("Pacific Photonics", "research", "ISO_9001", "USD"),
    ("Atlantic Defense Systems", "aerospace_defense", "ITAR", "USD"),
    ("Voyager Wireless Labs", "wireless_5g6g", "FCC_Part_15", "USD"),
    ("Granite State Calibration", "industrial", "ISO_17025", "USD"),
    ("Beacon Hill Test Engineering", "industrial", "ISO_17025", "USD"),
    ("Sequoia Semiconductor", "semiconductor", "ISO_9001", "USD"),
    ("Lone Star Telecom", "wireless_5g6g", "FCC_Part_15", "USD"),
    ("Cascadia Power Systems", "industrial", "UL_508A", "USD"),
    ("Pinnacle Avionics", "aerospace_defense", "DO-160", "USD"),
    ("Coastal Calibration Services", "industrial", "ISO_17025", "USD"),
    ("Mesa Microelectronics", "semiconductor", "ISO_9001", "USD"),
    ("Crestline EV Systems", "automotive", "IATF_16949", "USD"),
    ("Frontier Test Labs", "industrial", "ISO_17025", "USD"),
    ("Maple Leaf Aerospace", "aerospace_defense", "AS9100", "CAD"),
    ("Quebec Photonics Labs", "research", "ISO_9001", "CAD"),
    ("Toronto RF Engineering", "wireless_5g6g", "ISED_RSS", "CAD"),
    ("Vancouver Quantum Computing", "research", "ISO_9001", "CAD"),
    ("Calgary Energy Test Labs", "industrial", "CSA", "CAD"),
    ("Halcyon Defense Electronics", "aerospace_defense", "ITAR", "USD"),
    ("Cobalt Semiconductor", "semiconductor", "ISO_9001", "USD"),
    ("Redstone Wireless Test", "wireless_5g6g", "FCC_Part_15", "USD"),
    ("Riverbend Calibration", "industrial", "ISO_17025", "USD"),
    ("Summit Avionics Systems", "aerospace_defense", "DO-178C", "USD"),
    ("Trillium EV Labs", "automotive", "ISO_26262", "CAD"),
    ("Ironwood Telecom", "wireless_5g6g", "FCC_Part_15", "USD"),
    ("Bluestone Semiconductor", "semiconductor", "ISO_9001", "USD"),
    ("Highland Defense Systems", "aerospace_defense", "ITAR", "USD"),
    ("Glacier Photonics", "research", "ISO_9001", "USD"),
    ("Sierra Wireless Engineering", "wireless_5g6g", "FCC_Part_15", "USD"),
    ("Catalyst EV Test Labs", "automotive", "IATF_16949", "USD"),
    ("Yukon Energy Calibration", "industrial", "CSA", "CAD"),
    ("Anchor Defense Avionics", "aerospace_defense", "AS9100", "USD"),
    ("Brightstar Microwave", "wireless_5g6g", "FCC_Part_15", "USD"),
    ("Cinnabar Semiconductor", "semiconductor", "ISO_9001", "USD"),
    ("Driftwood Research Labs", "research", "ISO_9001", "USD"),
    ("Evergreen Calibration", "industrial", "ISO_17025", "USD"),
    ("Falcon Aerospace Test", "aerospace_defense", "AS9100", "USD"),
    ("Granite Bay EV Systems", "automotive", "IATF_16949", "USD"),
]

EMEA_COMPANIES = [
    ("Britannia RF Labs", "wireless_5g6g", "ETSI_EN_301", "GBP", "GB", "London", "en"),
    ("Albion Defense Electronics", "aerospace_defense", "ITAR", "GBP", "GB", "Bristol", "en"),
    ("Pendragon Quantum Systems", "research", "ISO_9001", "GBP", "GB", "Cambridge", "en"),
    ("Wessex Semiconductor", "semiconductor", "ISO_9001", "GBP", "GB", "Manchester", "en"),
    ("Heimdall Telecom", "wireless_5g6g", "ETSI_EN_301", "NOK", "NO", "Oslo", "en"),
    ("Vega Industrial Test", "industrial", "ISO_17025", "SEK", "SE", "Stockholm", "en"),
    ("Polaris Photonics", "research", "ISO_9001", "FIN", "FI", "Helsinki", "en"),
    ("Bauer Mikrowellen GmbH", "wireless_5g6g", "ETSI_EN_301", "EUR", "DE", "München", "de"),
    ("Schwarzwald Elektronik AG", "industrial", "ISO_17025", "EUR", "DE", "Stuttgart", "de"),
    ("Rheinmetall Test Systems", "aerospace_defense", "ITAR", "EUR", "DE", "Düsseldorf", "de"),
    ("Mittelstand Halbleiter GmbH", "semiconductor", "ISO_9001", "EUR", "DE", "Dresden", "de"),
    ("Dolomiti Microonde Srl", "wireless_5g6g", "ETSI_EN_301", "EUR", "IT", "Milano", "it"),
    ("Veneto Strumenti SpA", "industrial", "ISO_17025", "EUR", "IT", "Padova", "it"),
    ("Lyonnaise Télécom SAS", "wireless_5g6g", "ETSI_EN_301", "EUR", "FR", "Lyon", "fr"),
    ("Provence Aérospatiale", "aerospace_defense", "ITAR", "EUR", "FR", "Toulouse", "fr"),
    ("Bretagne Semi-conducteurs", "semiconductor", "ISO_9001", "EUR", "FR", "Rennes", "fr"),
    ("Sevilla Electrónica SL", "wireless_5g6g", "ETSI_EN_301", "EUR", "ES", "Sevilla", "es"),
    ("Barcelona Test Labs SA", "industrial", "ISO_17025", "EUR", "ES", "Barcelona", "es"),
    ("Lusíada Telecomunicações", "wireless_5g6g", "ETSI_EN_301", "EUR", "PT", "Lisboa", "pt"),
    ("Tagus Photonics Lda", "research", "ISO_9001", "EUR", "PT", "Porto", "pt"),
    ("Polderland Microwave BV", "wireless_5g6g", "ETSI_EN_301", "EUR", "NL", "Eindhoven", "nl"),
    ("Amsterdam Calibration BV", "industrial", "ISO_17025", "EUR", "NL", "Amsterdam", "nl"),
    ("Carpathia Semiconductors", "semiconductor", "ISO_9001", "PLN", "PL", "Warszawa", "pl"),
    ("Visegrád Test Engineering", "industrial", "ISO_17025", "PLN", "PL", "Kraków", "pl"),
    ("Helvetia Precision Labs", "industrial", "ISO_17025", "CHF", "CH", "Zürich", "de"),
    ("Genève Photonique SA", "research", "ISO_9001", "CHF", "CH", "Genève", "fr"),
    ("Wiener Telekom GmbH", "wireless_5g6g", "ETSI_EN_301", "EUR", "AT", "Wien", "de"),
    ("Bohemia Test Systems", "industrial", "ISO_17025", "CZK", "CZ", "Praha", "cs"),
    ("Magyar Mikrohullám Kft", "wireless_5g6g", "ETSI_EN_301", "HUF", "HU", "Budapest", "hu"),
    ("Sava RF Laboratories", "wireless_5g6g", "ETSI_EN_301", "EUR", "SI", "Ljubljana", "sl"),
    ("Hellas Telekom AE", "wireless_5g6g", "ETSI_EN_301", "EUR", "GR", "Athens", "el"),
    ("Aegean Industrial Test", "industrial", "ISO_17025", "EUR", "GR", "Thessaloniki", "el"),
    ("Bosporus Microwave", "wireless_5g6g", "ETSI_EN_301", "TRY", "TR", "Istanbul", "tr"),
    ("Anatolian Defense Labs", "aerospace_defense", "ITAR", "TRY", "TR", "Ankara", "tr"),
    ("Sahara Solar Test Systems", "industrial", "IEC_61215", "EUR", "MA", "Casablanca", "fr"),
    ("Nilotic Telecom Egypt", "wireless_5g6g", "ETSI_EN_301", "USD", "EG", "Cairo", "ar"),
    ("Cape Photonics SA", "research", "ISO_9001", "ZAR", "ZA", "Cape Town", "en"),
    ("Sandton Telecom Test", "wireless_5g6g", "ICASA", "ZAR", "ZA", "Johannesburg", "en"),
    ("Negev Defense Electronics", "aerospace_defense", "ITAR", "ILS", "IL", "Beer Sheva", "he"),
    ("Galilee Microwave Labs", "wireless_5g6g", "ETSI_EN_301", "ILS", "IL", "Haifa", "he"),
    ("Emirates Test Systems", "industrial", "ISO_17025", "AED", "AE", "Dubai", "en"),
    ("Riyadh Defense Engineering", "aerospace_defense", "ITAR", "SAR", "SA", "Riyadh", "ar"),
]

APAC_COMPANIES = [
    ("Suzhou Semiconductor Foundry", "semiconductor", "ISO_9001", "CNY", "CN", "Suzhou", "zh"),
    ("Shenzhen Microwave Labs", "wireless_5g6g", "SRRC", "CNY", "CN", "Shenzhen", "zh"),
    ("Beijing Photonics Research", "research", "ISO_9001", "CNY", "CN", "Beijing", "zh"),
    ("Shanghai EV Test Center", "automotive", "GB_T_18488", "CNY", "CN", "Shanghai", "zh"),
    ("Chengdu Aerospace Labs", "aerospace_defense", "GJB", "CNY", "CN", "Chengdu", "zh"),
    ("Hangzhou Calibration Co", "industrial", "ISO_17025", "CNY", "CN", "Hangzhou", "zh"),
    ("Xi'an RF Engineering", "wireless_5g6g", "SRRC", "CNY", "CN", "Xi'an", "zh"),
    ("Daejeon Semiconductor Test", "semiconductor", "ISO_9001", "KRW", "KR", "Daejeon", "ko"),
    ("Suwon Wireless Labs", "wireless_5g6g", "RRA_KC", "KRW", "KR", "Suwon", "ko"),
    ("Seoul Calibration Engineering", "industrial", "ISO_17025", "KRW", "KR", "Seoul", "ko"),
    ("Busan Marine Electronics", "industrial", "ISO_9001", "KRW", "KR", "Busan", "ko"),
    ("Incheon EV Test Labs", "automotive", "ISO_26262", "KRW", "KR", "Incheon", "ko"),
    ("Bangalore Telecom Test", "wireless_5g6g", "WPC_ETA", "INR", "IN", "Bengaluru", "en"),
    ("Hyderabad Semiconductor", "semiconductor", "ISO_9001", "INR", "IN", "Hyderabad", "en"),
    ("Chennai Auto Electronics", "automotive", "AIS_004", "INR", "IN", "Chennai", "en"),
    ("Pune Quantum Research", "research", "ISO_9001", "INR", "IN", "Pune", "en"),
    ("Mumbai Calibration Labs", "industrial", "ISO_17025", "INR", "IN", "Mumbai", "en"),
    ("Singapore Photonics Pte", "research", "ISO_9001", "SGD", "SG", "Singapore", "en"),
    ("Jurong Microwave Labs", "wireless_5g6g", "IMDA_TR", "SGD", "SG", "Singapore", "en"),
    ("Taipei Semiconductor Test", "semiconductor", "ISO_9001", "TWD", "TW", "Taipei", "zh"),
    ("Hsinchu Photonics Inc", "research", "ISO_9001", "TWD", "TW", "Hsinchu", "zh"),
    ("Taichung Industrial Test", "industrial", "ISO_17025", "TWD", "TW", "Taichung", "zh"),
    ("Sydney Defense Electronics", "aerospace_defense", "AS9100", "AUD", "AU", "Sydney", "en"),
    ("Melbourne EV Test Labs", "automotive", "ADR", "AUD", "AU", "Melbourne", "en"),
    ("Adelaide Aerospace Systems", "aerospace_defense", "AS9100", "AUD", "AU", "Adelaide", "en"),
    ("Auckland Calibration NZ", "industrial", "ISO_17025", "NZD", "NZ", "Auckland", "en"),
    ("Bangkok Telecom Test", "wireless_5g6g", "NBTC", "THB", "TH", "Bangkok", "th"),
    ("Hanoi Semiconductor Labs", "semiconductor", "ISO_9001", "VND", "VN", "Hanoi", "vi"),
    ("Ho Chi Minh Electronics Test", "industrial", "ISO_17025", "VND", "VN", "Ho Chi Minh City", "vi"),
    ("Manila Telecom Labs", "wireless_5g6g", "NTC", "PHP", "PH", "Manila", "en"),
    ("Jakarta Microwave Engineering", "wireless_5g6g", "POSTEL", "IDR", "ID", "Jakarta", "id"),
    ("Kuala Lumpur Test Engineering", "industrial", "ISO_17025", "MYR", "MY", "Kuala Lumpur", "ms"),
    ("Penang Semiconductor Co", "semiconductor", "ISO_9001", "MYR", "MY", "Penang", "ms"),
]

JP_COMPANIES = [
    ("ヒロサキ電子計測", "Hirosaki Denshi Keisoku", "industrial", "ISO_17025", "Aomori"),
    ("仙台無線研究所", "Sendai Musen Kenkyusho", "wireless_5g6g", "MIC_TELEC", "Miyagi"),
    ("浦安半導体工業", "Urayasu Handoutai Kogyo", "semiconductor", "ISO_9001", "Chiba"),
    ("品川宇宙システム", "Shinagawa Uchu System", "aerospace_defense", "JAXA", "Tokyo"),
    ("横須賀防衛電子", "Yokosuka Boei Denshi", "aerospace_defense", "ITAR", "Kanagawa"),
    ("つくば光通信研究所", "Tsukuba Hikari Tsushin Kenkyusho", "research", "ISO_9001", "Ibaraki"),
    ("名古屋自動車電子", "Nagoya Jidousha Denshi", "automotive", "ISO_26262", "Aichi"),
    ("豊田EVテストセンター", "Toyota EV Test Center", "automotive", "IATF_16949", "Aichi"),
    ("京都計測技術", "Kyoto Keisoku Gijutsu", "industrial", "ISO_17025", "Kyoto"),
    ("大阪マイクロ波技術", "Osaka Maikuroha Gijutsu", "wireless_5g6g", "MIC_TELEC", "Osaka"),
    ("神戸半導体検査", "Kobe Handoutai Kensa", "semiconductor", "ISO_9001", "Hyogo"),
    ("広島電子計測センター", "Hiroshima Denshi Keisoku Center", "industrial", "ISO_17025", "Hiroshima"),
    ("福岡無線ラボ", "Fukuoka Musen Lab", "wireless_5g6g", "MIC_TELEC", "Fukuoka"),
    ("札幌量子コンピューティング", "Sapporo Ryoshi Computing", "research", "ISO_9001", "Hokkaido"),
    ("沖縄光ファイバ研究所", "Okinawa Hikari Fiber Kenkyusho", "research", "ISO_9001", "Okinawa"),
    ("浜松フォトニクス検査", "Hamamatsu Photonics Kensa", "research", "ISO_9001", "Shizuoka"),
    ("つくば宇宙電子", "Tsukuba Uchu Denshi", "aerospace_defense", "JAXA", "Ibaraki"),
    ("川崎航空電子", "Kawasaki Koku Denshi", "aerospace_defense", "AS9100", "Kanagawa"),
    ("千葉EVバッテリー試験", "Chiba EV Battery Shiken", "automotive", "ISO_26262", "Chiba"),
    ("仙台RF計測", "Sendai RF Keisoku", "wireless_5g6g", "MIC_TELEC", "Miyagi"),
    ("奈良半導体製造", "Nara Handoutai Seizo", "semiconductor", "ISO_9001", "Nara"),
    ("熊本マイクロエレクトロニクス", "Kumamoto Microelectronics", "semiconductor", "ISO_9001", "Kumamoto"),
    ("茨城産業計測", "Ibaraki Sangyo Keisoku", "industrial", "ISO_17025", "Ibaraki"),
    ("新潟電力試験所", "Niigata Denryoku Shikenjo", "industrial", "JEC", "Niigata"),
]

FIRST_NAMES_EN = ["James", "Sarah", "Michael", "Emily", "Robert", "Jessica", "David", "Jennifer", "John", "Lisa",
                   "William", "Karen", "Richard", "Nancy", "Joseph", "Margaret", "Thomas", "Patricia", "Charles", "Linda",
                   "Daniel", "Barbara", "Matthew", "Susan", "Anthony", "Helen", "Donald", "Sandra", "Mark", "Donna"]
LAST_NAMES_EN = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
                  "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
                  "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson"]

FIRST_NAMES_DE = ["Andreas", "Klaus", "Stefan", "Michael", "Thomas", "Markus", "Petra", "Sabine", "Brigitte", "Ute",
                   "Ingrid", "Helga", "Anna", "Maria", "Christian", "Werner", "Jürgen", "Heinz", "Walter", "Erika"]
LAST_NAMES_DE = ["Müller", "Schmidt", "Schneider", "Fischer", "Weber", "Meyer", "Wagner", "Becker", "Schulz", "Hoffmann",
                  "Schäfer", "Koch", "Bauer", "Richter", "Klein", "Wolf", "Schröder", "Neumann", "Schwarz", "Zimmermann"]

FIRST_NAMES_FR = ["Pierre", "Jean", "Michel", "André", "Philippe", "Alain", "Bernard", "Jacques", "Claude", "Patrick",
                   "Marie", "Sophie", "Catherine", "Isabelle", "Françoise", "Nathalie", "Anne", "Sylvie", "Brigitte", "Christine"]
LAST_NAMES_FR = ["Martin", "Bernard", "Thomas", "Petit", "Robert", "Richard", "Durand", "Dubois", "Moreau", "Laurent",
                  "Simon", "Michel", "Lefebvre", "Leroy", "Roux", "David", "Bertrand", "Morel", "Fournier", "Girard"]

FIRST_NAMES_ES = ["Antonio", "José", "Manuel", "Francisco", "Juan", "David", "Javier", "Daniel", "Carlos", "Miguel",
                   "Carmen", "María", "Ana", "Isabel", "Laura", "Elena", "Pilar", "Rosa", "Marta", "Mercedes"]
LAST_NAMES_ES = ["García", "Rodríguez", "González", "Fernández", "López", "Martínez", "Sánchez", "Pérez", "Gómez", "Martín",
                  "Jiménez", "Ruiz", "Hernández", "Díaz", "Moreno", "Muñoz", "Álvarez", "Romero", "Alonso", "Gutiérrez"]

FIRST_NAMES_JA = ["太郎", "次郎", "三郎", "健", "誠", "明", "博", "和夫", "正夫", "孝",
                   "美咲", "由美", "恵子", "幸子", "美香", "陽子", "京子", "智子", "裕子", "麻衣"]
LAST_NAMES_JA = ["佐藤", "鈴木", "高橋", "田中", "渡辺", "伊藤", "山本", "中村", "小林", "加藤",
                  "吉田", "山田", "佐々木", "山口", "松本", "井上", "木村", "林", "斎藤", "清水"]

FIRST_NAMES_ZH = ["伟", "强", "磊", "勇", "杰", "军", "明", "超", "刚", "平",
                   "丽", "敏", "静", "娟", "艳", "霞", "燕", "玲", "桂英", "秀英"]
LAST_NAMES_ZH = ["王", "李", "张", "刘", "陈", "杨", "黄", "赵", "周", "吴",
                  "徐", "孙", "胡", "朱", "高", "林", "何", "郭", "马", "罗"]

FIRST_NAMES_KO = ["민준", "서준", "도윤", "예준", "시우", "주원", "하준", "지호", "지후", "준서",
                   "서연", "서윤", "지우", "서현", "민서", "수아", "하은", "지유", "윤서", "지민"]
LAST_NAMES_KO = ["김", "이", "박", "최", "정", "강", "조", "윤", "장", "임",
                  "한", "오", "서", "신", "권", "황", "안", "송", "전", "홍"]


def _first(language: str) -> str:
    return random.choice({
        "en": FIRST_NAMES_EN, "de": FIRST_NAMES_DE, "fr": FIRST_NAMES_FR, "es": FIRST_NAMES_ES,
        "it": FIRST_NAMES_EN, "pt": FIRST_NAMES_ES, "nl": FIRST_NAMES_DE,
        "pl": FIRST_NAMES_EN, "cs": FIRST_NAMES_EN, "hu": FIRST_NAMES_EN, "sl": FIRST_NAMES_EN,
        "el": FIRST_NAMES_EN, "tr": FIRST_NAMES_EN, "ar": FIRST_NAMES_EN, "he": FIRST_NAMES_EN,
        "ja": FIRST_NAMES_JA, "zh": FIRST_NAMES_ZH, "ko": FIRST_NAMES_KO,
        "th": FIRST_NAMES_EN, "vi": FIRST_NAMES_EN, "id": FIRST_NAMES_EN, "ms": FIRST_NAMES_EN,
    }.get(language, FIRST_NAMES_EN))


def _last(language: str) -> str:
    return random.choice({
        "en": LAST_NAMES_EN, "de": LAST_NAMES_DE, "fr": LAST_NAMES_FR, "es": LAST_NAMES_ES,
        "it": LAST_NAMES_EN, "pt": LAST_NAMES_ES, "nl": LAST_NAMES_DE,
        "pl": LAST_NAMES_EN, "cs": LAST_NAMES_EN, "hu": LAST_NAMES_EN, "sl": LAST_NAMES_EN,
        "el": LAST_NAMES_EN, "tr": LAST_NAMES_EN, "ar": LAST_NAMES_EN, "he": LAST_NAMES_EN,
        "ja": LAST_NAMES_JA, "zh": LAST_NAMES_ZH, "ko": LAST_NAMES_KO,
        "th": LAST_NAMES_EN, "vi": LAST_NAMES_EN, "id": LAST_NAMES_EN, "ms": LAST_NAMES_EN,
    }.get(language, LAST_NAMES_EN))


VERTICAL_TITLES = {
    "procurement": ["Procurement Manager", "Senior Buyer", "Strategic Sourcing Lead", "Category Manager"],
    "lab_ops": ["Calibration Lab Lead", "Test Engineering Manager", "Lab Operations Supervisor", "Senior Test Engineer"],
    "trade_compliance": ["Trade Compliance Analyst", "Export Control Lead", "Customs Specialist"],
    "ap": ["Accounts Payable Lead", "AP Specialist", "Finance Operations Manager"],
    "field_service": ["Field Service Manager", "Customer Service Engineer", "On-site Calibration Tech"],
}


def _contact(language: str, role: str, code_slug: str, domain: str, is_primary: bool = False) -> dict[str, Any]:
    first = _first(language)
    last = _last(language)
    if language in ("ja", "zh", "ko"):
        full = f"{last}{first}"
        if language == "ja":
            ascii_first = "".join(c for c in first if ord(c) < 128) or "Yuki"
            ascii_last = "".join(c for c in last if ord(c) < 128) or "Sato"
            full = f"{last}{first} ({ascii_first} {ascii_last})"
    else:
        full = f"{first} {last}"
    ascii_name = (
        full.split("(")[-1].rstrip(")")
        if "(" in full
        else f"{first}.{last}".lower()
    )
    handle_first = first.lower().replace(" ", ".") if language == "en" else "contact"
    handle_last = last.lower().replace(" ", "") if language == "en" else code_slug.lower()
    handle = (handle_first + "." + handle_last)[:40]
    return {
        "name": full,
        "title": random.choice(VERTICAL_TITLES[role]),
        "role": role,
        "email": f"{handle}@{domain}",
        "phone": _phone(language),
        **({"is_primary": True} if is_primary else {}),
        **({"language": language} if language != "en" else {}),
    }


def _phone(language: str) -> str:
    prefix = {
        "en": "+1", "fr": "+33", "es": "+34", "de": "+49", "it": "+39", "pt": "+351", "nl": "+31",
        "pl": "+48", "cs": "+420", "hu": "+36", "sl": "+386", "el": "+30", "tr": "+90",
        "ar": "+971", "he": "+972",
        "ja": "+81", "zh": "+86", "ko": "+82", "th": "+66", "vi": "+84", "id": "+62", "ms": "+60",
    }.get(language, "+1")
    return f"{prefix} {random.randint(100, 999)} 555 {random.randint(1000, 9999)}"


def _addr_for_country(country: str, region: str, city: str) -> list[dict[str, Any]]:
    streets_by_country = {
        "US": [("Innovation Way", "Lab Building 2"), ("Technology Parkway", "Receiving"), ("Industrial Blvd", None)],
        "CA": [("Avenue du Parc", None), ("King Street West", "Suite 400")],
        "GB": [("Innovation Park", "Calibration Bay 3"), ("Cambridge Science Park", None)],
        "DE": [("Industriestraße 22", "Halle 4"), ("Forschungspark 8", "Gebäude C")],
        "FR": [("Rue de l'Innovation 14", "Bâtiment Lab"), ("Parc Technologique", None)],
        "ES": [("Calle de Serrano 47", "Planta 5"), ("Parque Tecnológico Norte", "Nave 6")],
        "IT": [("Via Roma 88", "Edificio Lab"), ("Parco Scientifico", None)],
        "PT": [("Avenida da Liberdade 220", None), ("Parque Industrial", "Pavilhão 2")],
        "NL": [("Innovatiestraat 14", "Lab Gebouw"), ("Science Park 110", None)],
        "PL": [("Aleja Innowacji 22", None), ("Park Technologiczny", "Hala 4")],
        "CN": [("科技园路 88 号", "B 座 4 楼"), ("自由贸易区 12 号", "测试中心")],
        "JP": [("3-2-12", "Akasaka Bldg 6F"), ("1-1-1", "Innovation Tower 4F")],
        "KR": [("Pangyo Techno Valley", "Bldg 3"), ("Gangnam-daero 415", "Suite 22")],
        "IN": [("Electronic City Phase 2", "Tower B, Floor 8"), ("HITEC City Road 4", "Bldg 5")],
        "SG": [("1 Fusionopolis Way", "South Tower 10F"), ("Jurong Innovation District", "Block 22")],
        "TW": [("Li-Hsin Road 6", None), ("Hsin Chu Science Park", "Bldg E2")],
        "AU": [("47 George Street", "Level 8"), ("Innovation Drive 22", None)],
        "NZ": [("Albert Street 188", "Level 4"), (None, None)],
        "TH": [("Sukhumvit Road 222", "Level 5"), (None, None)],
        "VN": [("Quận 1 Lê Lợi 88", None), ("Khu Công Nghệ Cao", "Block 3")],
        "PH": [("Ayala Avenue 6788", "Tower 2 22F"), (None, None)],
        "ID": [("Jl. M.H. Thamrin 28", "Wisma 22F"), (None, None)],
        "MY": [("Persiaran KLCC 1", "Tower 2 18F"), ("Bayan Lepas Free Zone", "Lot 22")],
        "NO": [("Vingsvegen 14", None), (None, None)],
        "SE": [("Drottninggatan 71", "Plan 6"), (None, None)],
        "FI": [("Mikonkatu 22", "Floor 4"), (None, None)],
        "CH": [("Bahnhofstrasse 100", "5. Stock"), ("Rue du Rhône 14", None)],
        "AT": [("Mariahilfer Straße 88", "Stiege 2"), (None, None)],
        "CZ": [("Národní třída 22", "Patro 4"), (None, None)],
        "HU": [("Andrássy út 47", "II. emelet"), (None, None)],
        "SI": [("Slovenska cesta 14", None), (None, None)],
        "GR": [("Πανεπιστημίου 22", "5ος όροφος"), (None, None)],
        "TR": [("Bağdat Caddesi 188", "Daire 12"), (None, None)],
        "MA": [("Boulevard Mohammed V", "5e étage"), (None, None)],
        "EG": [("Tahrir Square", "Bldg 22"), (None, None)],
        "ZA": [("Rivonia Road 180", "Suite 4"), (None, None)],
        "IL": [("Rothschild Boulevard 22", "Floor 6"), (None, None)],
        "AE": [("Sheikh Zayed Road", "Tower 22, 18F"), (None, None)],
        "SA": [("King Fahd Road 88", "Bldg 4"), (None, None)],
    }
    streets = streets_by_country.get(country, [("Innovation Way", None)])
    chosen = random.choice(streets)
    return [
        {"type": "headquarters", "line1": chosen[0], **({"line2": chosen[1]} if chosen[1] else {}),
         "city": city, "region": region, "country": country, "postal": _postal(country)},
        {"type": "ship_to", "line1": f"{chosen[0]} - Receiving Dock",
         "city": city, "region": region, "country": country, "postal": _postal(country)},
    ]


def _postal(country: str) -> str:
    if country in ("US", "CA"):
        return f"{random.randint(10000, 99999)}"
    if country == "GB":
        return f"W{random.randint(1,9)}E {random.randint(1,9)}AA"
    if country in ("DE", "ES", "FR", "IT"):
        return f"{random.randint(10000, 99999)}"
    if country == "JP":
        return f"{random.randint(100, 999)}-{random.randint(1000, 9999)}"
    if country == "CN":
        return f"{random.randint(100000, 999999)}"
    if country == "KR":
        return f"{random.randint(10000, 99999)}"
    if country == "IN":
        return f"{random.randint(100000, 999999)}"
    return f"{random.randint(1000, 99999)}"


def _build_ams_customer(seq: int, spec: tuple) -> dict[str, Any]:
    name, vertical, comp_root, currency = spec
    code = f"GEN-AMS-{seq:03d}"
    domain_root = name.lower().replace(" ", "").replace(".", "").replace("&", "and")[:18]
    domain = f"{domain_root}.com"
    country = "CA" if currency == "CAD" else "US"
    region = random.choice(["CA", "TX", "MA", "WA", "CO", "VA", "NY", "MI", "IL"]) if country == "US" else random.choice(["ON", "QC", "BC", "AB"])
    cities = {
        "CA": ["Toronto", "Montreal", "Vancouver", "Calgary", "Ottawa"],
        "US": ["Boston", "Austin", "Boulder", "Denver", "Phoenix", "Atlanta", "Raleigh", "Portland"],
    }
    city = random.choice(cities[country])
    return {
        "code": code,
        "name": name,
        "legal_entity": f"{name}, Inc." if country == "US" else f"{name} Inc.",
        "region": "AMS",
        "language": "en",
        "email": f"procurement@{domain}",
        "vertical": vertical,
        "compliance": [comp_root, "ISO_9001"] if comp_root != "ISO_9001" else [comp_root],
        "industry": _industry_label(vertical),
        "naics": _naics_for(vertical),
        "annual_revenue_usd": float(random.choice([42_000_000, 96_000_000, 184_000_000, 312_000_000, 520_000_000, 1_240_000_000])),
        "employees": random.choice([180, 380, 620, 1_100, 1_800, 3_200, 5_500]),
        "account_manager": f"{_first('en')} {_last('en')}",
        "sales_engineer": f"{_first('en')} {_last('en')}",
        "customer_since": _customer_since(),
        "status": "active",
        "sla_tier": random.choice(["Gold", "Silver", "Platinum"]),
        "duns": f"{random.randint(10,99)}-{random.randint(100,999)}-{random.randint(1000,9999)}",
        "tax_id": f"{random.randint(10,99)}-{random.randint(1000000,9999999)}",
        "payment_terms": random.choice(["Net 30", "Net 45", "Net 60"]),
        "credit_limit": float(random.choice([350_000, 750_000, 1_500_000, 2_500_000, 5_000_000])),
        "default_currency": currency,
        "default_incoterms": random.choice(["FOB Origin", "FOB Destination", "DDP"]),
        "addresses": _addr_for_country(country, region, city),
        "contacts": [
            _contact("en", "procurement", code, domain, is_primary=True),
            _contact("en", "lab_ops", code, domain),
            _contact("en", "ap", code, domain),
        ],
    }


def _build_emea_customer(seq: int, spec: tuple) -> dict[str, Any]:
    name, vertical, comp_root, currency, country, city, language = spec
    code = f"GEN-EMEA-{seq:03d}"
    domain_root = name.lower().replace(" ", "").replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    domain_root = "".join(c for c in domain_root if c.isalnum())[:18]
    tld = {"GB": "co.uk", "DE": "de", "FR": "fr", "ES": "es", "IT": "it", "PT": "pt", "NL": "nl",
           "PL": "pl", "CZ": "cz", "HU": "hu", "SI": "si", "GR": "gr", "TR": "com.tr",
           "MA": "ma", "EG": "com.eg", "ZA": "co.za", "IL": "co.il", "AE": "ae", "SA": "com.sa",
           "CH": "ch", "AT": "at", "NO": "no", "SE": "se", "FI": "fi"}.get(country, "com")
    domain = f"{domain_root}.{tld}"
    region_for_addr = {"GB": city, "DE": "BE", "FR": "IDF", "ES": "MD", "IT": "MI",
                       "PT": "Lisboa", "NL": "NH", "PL": "MA", "CZ": "PR", "HU": "BP",
                       "SI": "LJ", "GR": "AT", "TR": "IS"}.get(country, city)
    return {
        "code": code,
        "name": name,
        "legal_entity": _legal_entity_for(name, country),
        "region": "EMEA",
        "language": language,
        "email": f"compras@{domain}" if language == "es" else f"einkauf@{domain}" if language == "de" else f"orders@{domain}",
        "vertical": vertical,
        "compliance": [comp_root, "ISO_9001"] if comp_root != "ISO_9001" else [comp_root],
        "industry": _industry_label(vertical),
        "naics": _naics_for(vertical),
        "annual_revenue_usd": float(random.choice([42_000_000, 96_000_000, 184_000_000, 312_000_000, 520_000_000])),
        "employees": random.choice([180, 380, 620, 1_100, 1_800, 3_200]),
        "account_manager": f"{_first(language)} {_last(language)}",
        "sales_engineer": f"{_first(language)} {_last(language)}",
        "customer_since": _customer_since(),
        "status": "active",
        "sla_tier": random.choice(["Gold", "Silver", "Platinum"]),
        "duns": f"{country}-{random.randint(1000,9999)}-{random.randint(1000,9999)}",
        "tax_id": _tax_id(country),
        "payment_terms": random.choice(["Net 30", "Net 45", "Net 60"]),
        "credit_limit": float(random.choice([350_000, 750_000, 1_500_000, 2_500_000])),
        "default_currency": currency,
        "default_incoterms": random.choice(["DDP", "EXW", "FCA", "DAP"]),
        "addresses": _addr_for_country(country, region_for_addr, city),
        "contacts": [
            _contact(language, "procurement", code, domain, is_primary=True),
            _contact(language, "lab_ops", code, domain),
        ],
    }


def _build_apac_customer(seq: int, spec: tuple) -> dict[str, Any]:
    name, vertical, comp_root, currency, country, city, language = spec
    code = f"GEN-APAC-{seq:03d}"
    domain_root = name.lower().replace(" ", "").replace("'", "")
    domain_root = "".join(c for c in domain_root if c.isalnum())[:18]
    tld = {"CN": "com.cn", "KR": "co.kr", "IN": "in", "SG": "com.sg", "TW": "com.tw",
           "AU": "com.au", "NZ": "co.nz", "TH": "co.th", "VN": "com.vn",
           "PH": "com.ph", "ID": "co.id", "MY": "com.my"}.get(country, "com")
    domain = f"{domain_root}.{tld}"
    return {
        "code": code,
        "name": name,
        "legal_entity": _legal_entity_for(name, country),
        "region": "APAC",
        "language": language,
        "email": f"procurement@{domain}",
        "vertical": vertical,
        "compliance": [comp_root, "ISO_9001"] if comp_root != "ISO_9001" else [comp_root],
        "industry": _industry_label(vertical),
        "naics": _naics_for(vertical),
        "annual_revenue_usd": float(random.choice([96_000_000, 184_000_000, 312_000_000, 520_000_000, 1_240_000_000, 4_900_000_000])),
        "employees": random.choice([380, 620, 1_100, 3_200, 5_500, 14_500]),
        "account_manager": f"{_first(language)} {_last(language)}",
        "sales_engineer": f"{_first(language)} {_last(language)}",
        "customer_since": _customer_since(),
        "status": "active",
        "sla_tier": random.choice(["Gold", "Silver", "Platinum"]),
        "duns": f"{country}-{random.randint(1000,9999)}-{random.randint(1000,9999)}",
        "tax_id": _tax_id(country),
        "payment_terms": random.choice(["Net 30", "Net 45", "Net 60"]),
        "credit_limit": float(random.choice([350_000, 750_000, 1_500_000, 2_500_000, 5_000_000])),
        "default_currency": currency,
        "default_incoterms": random.choice(["DDP", "FCA", "DAP", "FOB Origin"]),
        "addresses": _addr_for_country(country, city, city),
        "contacts": [
            _contact(language, "procurement", code, domain, is_primary=True),
            _contact(language, "lab_ops", code, domain),
        ],
    }


def _build_jp_customer(seq: int, spec: tuple) -> dict[str, Any]:
    jp_name, romaji, vertical, comp_root, prefecture = spec
    code = f"GEN-JP-{seq:03d}"
    domain_root = "".join(c for c in romaji.lower().replace(" ", "") if c.isalnum())[:18]
    domain = f"{domain_root}.co.jp"
    city_map = {"Aomori": "Aomori", "Miyagi": "Sendai", "Chiba": "Chiba", "Tokyo": "Tokyo",
                "Kanagawa": "Yokohama", "Ibaraki": "Tsukuba", "Aichi": "Nagoya", "Kyoto": "Kyoto",
                "Osaka": "Osaka", "Hyogo": "Kobe", "Hiroshima": "Hiroshima", "Fukuoka": "Fukuoka",
                "Hokkaido": "Sapporo", "Okinawa": "Naha", "Shizuoka": "Hamamatsu", "Nara": "Nara",
                "Kumamoto": "Kumamoto", "Niigata": "Niigata"}
    city = city_map.get(prefecture, "Tokyo")
    return {
        "code": code,
        "name": jp_name,
        "legal_entity": f"{jp_name}株式会社 / {romaji} K.K.",
        "region": "JP",
        "language": "ja",
        "email": f"chumon@{domain}",
        "vertical": vertical,
        "compliance": [comp_root, "ISO_9001"] if comp_root != "ISO_9001" else [comp_root],
        "industry": _industry_label(vertical),
        "naics": _naics_for(vertical),
        "annual_revenue_usd": float(random.choice([96_000_000, 312_000_000, 520_000_000, 1_240_000_000, 4_900_000_000])),
        "employees": random.choice([380, 1_100, 3_200, 5_500, 14_500]),
        "account_manager": f"{_first('ja')} {_last('ja')}",
        "sales_engineer": f"{_first('ja')} {_last('ja')}",
        "customer_since": _customer_since(),
        "status": "active",
        "sla_tier": random.choice(["Gold", "Silver", "Platinum"]),
        "duns": f"JP-{random.randint(1000,9999)}-{random.randint(1000,9999)}",
        "tax_id": _tax_id("JP"),
        "payment_terms": random.choice(["Net 30", "Net 45"]),
        "credit_limit": float(random.choice([500_000, 1_500_000, 3_000_000, 8_000_000])),
        "default_currency": "JPY",
        "default_incoterms": random.choice(["DDP", "FCA Tokyo"]),
        "addresses": _addr_for_country("JP", prefecture, city),
        "contacts": [
            _contact("ja", "procurement", code, domain, is_primary=True),
            _contact("ja", "lab_ops", code, domain),
        ],
    }


def _legal_entity_for(name: str, country: str) -> str:
    suffix = {"DE": "GmbH & Co. KG", "FR": "SAS", "ES": "SL", "IT": "Srl", "PT": "Lda",
              "NL": "BV", "PL": "Sp. z o.o.", "CZ": "s.r.o.", "HU": "Kft",
              "AT": "GmbH", "CH": "AG", "GB": "Ltd", "IE": "Ltd",
              "CN": "Co., Ltd.", "TW": "Co., Ltd.", "KR": "Co., Ltd.", "JP": "K.K.",
              "IN": "Pvt. Ltd.", "SG": "Pte. Ltd.", "AU": "Pty Ltd", "NZ": "Limited"}.get(country, "S.A.")
    if suffix in name:
        return name
    return f"{name} {suffix}"


def _tax_id(country: str) -> str:
    if country == "GB":
        return f"GB-{random.randint(100,999)}{random.randint(1000,9999)}"
    if country == "DE":
        return f"DE-{random.randint(100000000, 999999999)}"
    if country == "FR":
        return f"FR-{random.randint(10,99)}{random.randint(100000000, 999999999)}"
    if country == "ES":
        return f"ES-{chr(random.randint(65, 90))}{random.randint(10000000, 99999999)}"
    if country == "JP":
        return f"JP-{random.randint(1000000000000, 9999999999999)}"
    if country in ("CN", "TW"):
        return f"{country}-{random.randint(10000000, 99999999)}"
    return f"{country}-{random.randint(100000000, 999999999)}"


def _industry_label(vertical: str) -> str:
    return {
        "aerospace_defense": "Defense Electronics",
        "semiconductor": "Semiconductor Manufacturing",
        "wireless_5g6g": "Wireless / 5G/6G Test",
        "automotive": "Automotive Electronics",
        "research": "Research and Development",
        "industrial": "Industrial Test and Calibration",
        "test_systems_integrator": "Test Systems Integration",
    }.get(vertical, "Electronics")


def _naics_for(vertical: str) -> str:
    return {
        "aerospace_defense": "334511",
        "semiconductor": "334413",
        "wireless_5g6g": "541380",
        "automotive": "336320",
        "research": "541715",
        "industrial": "541380",
        "test_systems_integrator": "541330",
    }.get(vertical, "334290")


def _customer_since() -> str:
    d = date(2026, 5, 13) - timedelta(days=random.randint(365, 365 * 18))
    return d.isoformat()


# ----------------------------------------------------------------------
# Products
# ----------------------------------------------------------------------

NEW_PRODUCTS = [
    # Vector Network Analyzers
    {"sku": "N5227B-460", "description": "PNA Microwave Network Analyzer, 67 GHz, 2-port", "list_price": 198000.0, "family": "VNA", "category": "RF/Microwave", "lifecycle_status": "active", "lead_time_weeks": 14, "country_of_origin": "US", "eccn": "3A002.f", "warranty_months": 12},
    {"sku": "E5063A-285", "description": "ENA Network Analyzer, 8.5 GHz, 2-port (Mainstream)", "list_price": 18500.0, "family": "VNA", "category": "RF/Microwave", "lifecycle_status": "active", "lead_time_weeks": 6, "country_of_origin": "MY", "eccn": "EAR99", "warranty_months": 12},
    {"sku": "P5028B", "description": "Streamline USB VNA, 53 GHz, 2-port", "list_price": 48500.0, "family": "VNA", "category": "RF/Microwave", "lifecycle_status": "active", "lead_time_weeks": 8, "country_of_origin": "MY", "eccn": "EAR99", "warranty_months": 12},
    {"sku": "N5247B-485", "description": "PNA-X 67 GHz, 4-port + Pulse Option H85", "list_price": 245000.0, "family": "VNA", "category": "RF/Microwave", "lifecycle_status": "active", "lead_time_weeks": 18, "country_of_origin": "US", "eccn": "3A002.f", "warranty_months": 12},
    # Signal Generators
    {"sku": "N5172B-506", "description": "EXG Vector Signal Generator, 6 GHz, 160 MHz BW", "list_price": 42500.0, "family": "SG", "category": "RF/Microwave", "lifecycle_status": "active", "lead_time_weeks": 8, "country_of_origin": "US", "eccn": "EAR99", "warranty_months": 12},
    {"sku": "N5193A-540", "description": "UXG Agile Vector Adapter, 40 GHz", "list_price": 89500.0, "family": "SG", "category": "RF/Microwave", "lifecycle_status": "active", "lead_time_weeks": 12, "country_of_origin": "US", "eccn": "3A002.f", "warranty_months": 12},
    {"sku": "M9415A", "description": "VXT Vector Transceiver, 7.5 GHz, dual-channel", "list_price": 76500.0, "family": "SG", "category": "RF/Microwave", "lifecycle_status": "active", "lead_time_weeks": 10, "country_of_origin": "US", "eccn": "EAR99", "warranty_months": 12},
    {"sku": "E8257D-567", "description": "PSG Analog Signal Generator, 67 GHz", "list_price": 138000.0, "family": "SG", "category": "RF/Microwave", "lifecycle_status": "mature", "lead_time_weeks": 14, "country_of_origin": "US", "eccn": "3A002.f", "warranty_months": 12},
    # Spectrum / Signal Analyzers
    {"sku": "N9030B-526", "description": "PXA Signal Analyzer, 26.5 GHz, 1 GHz analysis BW", "list_price": 132000.0, "family": "SA", "category": "RF/Microwave", "lifecycle_status": "active", "lead_time_weeks": 12, "country_of_origin": "US", "eccn": "EAR99", "warranty_months": 12},
    {"sku": "N9000B-203", "description": "CXA Signal Analyzer, 3 GHz", "list_price": 12800.0, "family": "SA", "category": "RF/Microwave", "lifecycle_status": "active", "lead_time_weeks": 4, "country_of_origin": "MY", "eccn": "EAR99", "warranty_months": 12},
    {"sku": "N9010B-544", "description": "EXA Signal Analyzer, 44 GHz", "list_price": 58500.0, "family": "SA", "category": "RF/Microwave", "lifecycle_status": "active", "lead_time_weeks": 8, "country_of_origin": "US", "eccn": "EAR99", "warranty_months": 12},
    # Oscilloscopes
    {"sku": "DSOX1204A", "description": "InfiniiVision 1000X Oscilloscope, 200 MHz, 4-Ch", "list_price": 1995.0, "family": "OSC", "category": "Digital", "lifecycle_status": "active", "lead_time_weeks": 4, "country_of_origin": "MY", "eccn": "EAR99", "warranty_months": 36},
    {"sku": "DSOX3104T", "description": "InfiniiVision 3000T Oscilloscope, 1 GHz, 4-Ch", "list_price": 9800.0, "family": "OSC", "category": "Digital", "lifecycle_status": "active", "lead_time_weeks": 4, "country_of_origin": "MY", "eccn": "EAR99", "warranty_months": 36},
    {"sku": "DSOX4154A", "description": "InfiniiVision 4000 X-Series, 1.5 GHz, 4-Ch", "list_price": 22500.0, "family": "OSC", "category": "Digital", "lifecycle_status": "active", "lead_time_weeks": 6, "country_of_origin": "MY", "eccn": "EAR99", "warranty_months": 36},
    {"sku": "MXR208A", "description": "Infiniium MXR-Series, 2 GHz, 8-Ch", "list_price": 38500.0, "family": "OSC", "category": "Digital", "lifecycle_status": "active", "lead_time_weeks": 8, "country_of_origin": "US", "eccn": "EAR99", "warranty_months": 12},
    {"sku": "EXR404A", "description": "Infiniium EXR-Series, 4 GHz, 4-Ch", "list_price": 47500.0, "family": "OSC", "category": "Digital", "lifecycle_status": "active", "lead_time_weeks": 8, "country_of_origin": "US", "eccn": "EAR99", "warranty_months": 12},
    {"sku": "UXR1004A", "description": "Infiniium UXR Real-Time Oscilloscope, 100 GHz, 4-Ch, 256 GS/s", "list_price": 685000.0, "family": "OSC", "category": "Digital", "lifecycle_status": "active", "lead_time_weeks": 22, "country_of_origin": "US", "eccn": "3A002.a.5", "warranty_months": 12},
    # FieldFox
    {"sku": "N9913A-201", "description": "FieldFox Handheld RF Analyzer, 4 GHz, CAT only", "list_price": 8800.0, "family": "FieldFox", "category": "RF/Microwave", "lifecycle_status": "active", "lead_time_weeks": 4, "country_of_origin": "US", "eccn": "EAR99", "warranty_months": 12},
    {"sku": "N9914A-345", "description": "FieldFox Handheld, 6.5 GHz, Combo NA/SA", "list_price": 21500.0, "family": "FieldFox", "category": "RF/Microwave", "lifecycle_status": "active", "lead_time_weeks": 6, "country_of_origin": "US", "eccn": "EAR99", "warranty_months": 12},
    {"sku": "N9938A-345", "description": "FieldFox Handheld, 26.5 GHz, Combo NA/SA/SG", "list_price": 56500.0, "family": "FieldFox", "category": "RF/Microwave", "lifecycle_status": "active", "lead_time_weeks": 8, "country_of_origin": "US", "eccn": "3A002.f", "warranty_months": 12},
    # DC Power and Loads
    {"sku": "N6700C", "description": "Modular DC Power Mainframe, 4-slot", "list_price": 7100.0, "family": "DC", "category": "DC Power", "lifecycle_status": "active", "lead_time_weeks": 4, "country_of_origin": "MY", "eccn": "EAR99", "warranty_months": 36},
    {"sku": "EL34243A", "description": "Electronic Load, 200 W, dual input", "list_price": 4200.0, "family": "DC", "category": "DC Power", "lifecycle_status": "active", "lead_time_weeks": 4, "country_of_origin": "MY", "eccn": "EAR99", "warranty_months": 36},
    {"sku": "RP7900-1", "description": "Regenerative Power System, 5 kW", "list_price": 38500.0, "family": "DC", "category": "DC Power", "lifecycle_status": "active", "lead_time_weeks": 10, "country_of_origin": "MY", "eccn": "EAR99", "warranty_months": 36},
    {"sku": "B2961B", "description": "Precision Source/Measure Unit, 1-Ch, low-noise", "list_price": 11500.0, "family": "SMU", "category": "DC Power", "lifecycle_status": "active", "lead_time_weeks": 6, "country_of_origin": "MY", "eccn": "EAR99", "warranty_months": 36},
    # Logic Analyzers
    {"sku": "U4164A", "description": "AXIe Logic Analyzer, 136 channels, 12.5 Gb/s", "list_price": 245000.0, "family": "LA", "category": "Digital", "lifecycle_status": "active", "lead_time_weeks": 16, "country_of_origin": "US", "eccn": "3A002.a.5", "warranty_months": 12},
    # BERT and High-Speed Digital
    {"sku": "M8050A", "description": "High-Performance BERT, 120 GBaud", "list_price": 685000.0, "family": "BERT", "category": "Digital", "lifecycle_status": "active", "lead_time_weeks": 26, "country_of_origin": "US", "eccn": "3A002.a.5", "warranty_months": 12},
    {"sku": "M8195A", "description": "Arbitrary Waveform Generator, 65 GSa/s, 4-Ch", "list_price": 215000.0, "family": "AWG", "category": "RF/Microwave", "lifecycle_status": "active", "lead_time_weeks": 16, "country_of_origin": "US", "eccn": "3A002.a.5", "warranty_months": 12},
    # Optical / Photonics
    {"sku": "8163B-101", "description": "Lightwave Multimeter Mainframe", "list_price": 16500.0, "family": "OPT", "category": "Optical", "lifecycle_status": "active", "lead_time_weeks": 6, "country_of_origin": "DE", "eccn": "EAR99", "warranty_months": 12},
    {"sku": "N7714A", "description": "Tunable Laser Source, 4-Ch, 1527-1620 nm", "list_price": 78500.0, "family": "OPT", "category": "Optical", "lifecycle_status": "active", "lead_time_weeks": 12, "country_of_origin": "DE", "eccn": "EAR99", "warranty_months": 12},
    {"sku": "N7752A", "description": "Optical Switch / Attenuator, 2x2", "list_price": 24500.0, "family": "OPT", "category": "Optical", "lifecycle_status": "active", "lead_time_weeks": 8, "country_of_origin": "DE", "eccn": "EAR99", "warranty_months": 12},
    # Multimeters and Sensors
    {"sku": "34465A", "description": "Truevolt 6.5-Digit Digital Multimeter", "list_price": 1450.0, "family": "DMM", "category": "Digital", "lifecycle_status": "active", "lead_time_weeks": 4, "country_of_origin": "MY", "eccn": "EAR99", "warranty_months": 36},
    {"sku": "34470A", "description": "Truevolt 7.5-Digit DMM", "list_price": 2850.0, "family": "DMM", "category": "Digital", "lifecycle_status": "active", "lead_time_weeks": 4, "country_of_origin": "MY", "eccn": "EAR99", "warranty_months": 36},
    {"sku": "U2042XA", "description": "USB Power Sensor, 50 MHz to 26.5 GHz", "list_price": 4250.0, "family": "PWR", "category": "RF/Microwave", "lifecycle_status": "active", "lead_time_weeks": 4, "country_of_origin": "US", "eccn": "EAR99", "warranty_months": 12},
    # Accessories
    {"sku": "85052B", "description": "3.5 mm Standard Calibration Kit, DC to 26.5 GHz", "list_price": 8400.0, "family": "ACC", "category": "Accessory", "lifecycle_status": "active", "lead_time_weeks": 6, "country_of_origin": "US", "eccn": "EAR99", "warranty_months": 12},
    {"sku": "85058B", "description": "1.85 mm Precision Calibration Kit, DC to 67 GHz", "list_price": 18500.0, "family": "ACC", "category": "Accessory", "lifecycle_status": "active", "lead_time_weeks": 8, "country_of_origin": "US", "eccn": "3A002.f", "warranty_months": 12},
    {"sku": "85093C", "description": "ECal Module 2-port 50 GHz, 2.4 mm", "list_price": 22500.0, "family": "ACC", "category": "Accessory", "lifecycle_status": "active", "lead_time_weeks": 8, "country_of_origin": "US", "eccn": "3A002.f", "warranty_months": 12},
    {"sku": "N1021B", "description": "TDR Probe, 26 GHz, 50 ohm", "list_price": 4850.0, "family": "ACC", "category": "Accessory", "lifecycle_status": "active", "lead_time_weeks": 4, "country_of_origin": "US", "eccn": "EAR99", "warranty_months": 12},
    {"sku": "N5450B", "description": "InfiniiMax II Differential Probe, 13 GHz", "list_price": 9450.0, "family": "ACC", "category": "Accessory", "lifecycle_status": "active", "lead_time_weeks": 6, "country_of_origin": "US", "eccn": "EAR99", "warranty_months": 12},
    {"sku": "11878B", "description": "RF Cable, 18 GHz, 1 m, NMD-3.5 mm", "list_price": 850.0, "family": "ACC", "category": "Accessory", "lifecycle_status": "active", "lead_time_weeks": 2, "country_of_origin": "MY", "eccn": "EAR99", "warranty_months": 12},
    # Software / Options
    {"sku": "N7625C-1FP", "description": "Signal Studio for 5G NR, perpetual license", "list_price": 12500.0, "family": "SW", "category": "Software", "lifecycle_status": "active", "lead_time_weeks": 1, "country_of_origin": "US", "eccn": "EAR99", "warranty_months": 12},
    {"sku": "N9077EM0E", "description": "5G NR FR2 Measurement Application, transportable", "list_price": 8500.0, "family": "SW", "category": "Software", "lifecycle_status": "active", "lead_time_weeks": 1, "country_of_origin": "US", "eccn": "EAR99", "warranty_months": 12},
    {"sku": "N9085EM0E", "description": "LTE FDD/TDD Measurement Application", "list_price": 4200.0, "family": "SW", "category": "Software", "lifecycle_status": "active", "lead_time_weeks": 1, "country_of_origin": "US", "eccn": "EAR99", "warranty_months": 12},
    {"sku": "U9020XA", "description": "Wi-Fi 7 Test Application", "list_price": 9800.0, "family": "SW", "category": "Software", "lifecycle_status": "active", "lead_time_weeks": 1, "country_of_origin": "US", "eccn": "EAR99", "warranty_months": 12},
    # Service / Support
    {"sku": "CAL-17025-1Y", "description": "Calibration Service - ISO 17025 accredited, 1-year", "list_price": 1850.0, "family": "SVC", "category": "Service", "lifecycle_status": "active", "lead_time_weeks": 2, "country_of_origin": "US", "eccn": "EAR99", "warranty_months": 0},
    {"sku": "CAL-A2LA-3Y", "description": "Calibration Service - A2LA accredited, 3-year contract", "list_price": 3900.0, "family": "SVC", "category": "Service", "lifecycle_status": "active", "lead_time_weeks": 2, "country_of_origin": "US", "eccn": "EAR99", "warranty_months": 0},
    {"sku": "WARR-EXT-5Y", "description": "Extended Warranty, additional 5-year coverage", "list_price": 5800.0, "family": "SVC", "category": "Service", "lifecycle_status": "active", "lead_time_weeks": 0, "country_of_origin": "US", "eccn": "EAR99", "warranty_months": 0},
    {"sku": "REPAIR-RTRN", "description": "Return-to-factory repair service, fixed-fee", "list_price": 2850.0, "family": "SVC", "category": "Service", "lifecycle_status": "active", "lead_time_weeks": 3, "country_of_origin": "US", "eccn": "EAR99", "warranty_months": 0},
    {"sku": "TRAIN-RF-5D", "description": "RF Test Engineering Training, 5-day on-site", "list_price": 12500.0, "family": "SVC", "category": "Service", "lifecycle_status": "active", "lead_time_weeks": 4, "country_of_origin": "US", "eccn": "EAR99", "warranty_months": 0},
    {"sku": "FSE-DAY", "description": "Field Service Engineer Visit, per-day rate", "list_price": 2200.0, "family": "SVC", "category": "Service", "lifecycle_status": "active", "lead_time_weeks": 1, "country_of_origin": "US", "eccn": "EAR99", "warranty_months": 0},
    {"sku": "CONS-INSTALL", "description": "Installation and Commissioning Service", "list_price": 4800.0, "family": "SVC", "category": "Service", "lifecycle_status": "active", "lead_time_weeks": 2, "country_of_origin": "US", "eccn": "EAR99", "warranty_months": 0},
    # Education
    {"sku": "EDU-LIC-10S", "description": "University Educational License, 10 seats", "list_price": 3850.0, "family": "EDU", "category": "Education", "lifecycle_status": "active", "lead_time_weeks": 1, "country_of_origin": "US", "eccn": "EAR99", "warranty_months": 0},
    # Magic SKUs - operational routing markers (routing semantics live in MAGIC_SKUS below)
    {"sku": "CUSTOM-PRODUCT", "description": "Magic SKU: customer-specific custom product, requires manual review and engineering quote", "list_price": 0.0, "family": "MAGIC", "category": "Operational", "lifecycle_status": "active", "lead_time_weeks": 0, "country_of_origin": "N/A", "eccn": "N/A", "warranty_months": 0, "moq": 1},
    {"sku": "SOWDUMMY", "description": "Magic SKU: Statement-of-Work routing placeholder, routes the case to the SOW team", "list_price": 0.0, "family": "MAGIC", "category": "Operational", "lifecycle_status": "active", "lead_time_weeks": 0, "country_of_origin": "N/A", "eccn": "N/A", "warranty_months": 0, "moq": 1},
    {"sku": "EXPORTDUMMY", "description": "Magic SKU: Non-US destination flag, routes through Export Control review", "list_price": 0.0, "family": "MAGIC", "category": "Operational", "lifecycle_status": "active", "lead_time_weeks": 0, "country_of_origin": "N/A", "eccn": "N/A", "warranty_months": 0, "moq": 1},
]


# ----------------------------------------------------------------------
# Distributors (authorised channel partners)
# ----------------------------------------------------------------------

DISTRIBUTORS = [
    # Americas
    {"code": "DIST-NW-USA-001", "name": "Northwest T&M Solutions", "region": "AMS", "country": "US", "city": "Portland, OR", "tier": "Premier", "currency": "USD", "specialty": "RF and Microwave", "contact_email": "orders@northwesttm.com", "phone": "+1 503 555 0144"},
    {"code": "DIST-NE-USA-002", "name": "Atlantic Instrumentation Group", "region": "AMS", "country": "US", "city": "Boston, MA", "tier": "Premier", "currency": "USD", "specialty": "Aerospace and Defense", "contact_email": "po@atlanticinstr.com", "phone": "+1 617 555 0177"},
    {"code": "DIST-SW-USA-003", "name": "SunValley Test Equipment", "region": "AMS", "country": "US", "city": "Phoenix, AZ", "tier": "Authorised", "currency": "USD", "specialty": "Semiconductor", "contact_email": "sales@sunvalleyte.com", "phone": "+1 480 555 0188"},
    {"code": "DIST-CA-CAN-004", "name": "Maple Test Systems Ltd", "region": "AMS", "country": "CA", "city": "Toronto, ON", "tier": "Authorised", "currency": "CAD", "specialty": "General Purpose", "contact_email": "info@mapletest.ca", "phone": "+1 416 555 0188"},
    {"code": "DIST-MX-LAT-005", "name": "Equipos de Prueba MX", "region": "AMS", "country": "MX", "city": "Monterrey", "tier": "Authorised", "currency": "USD", "specialty": "Automotive", "contact_email": "ventas@equiposmx.mx", "phone": "+52 81 5555 0144"},
    # EMEA
    {"code": "DIST-UK-EMEA-006", "name": "Britannia Test Solutions", "region": "EMEA", "country": "GB", "city": "Reading, Berks", "tier": "Premier", "currency": "GBP", "specialty": "Wireless and 5G", "contact_email": "sales@britanniatest.co.uk", "phone": "+44 118 555 0144"},
    {"code": "DIST-DE-EMEA-007", "name": "Mitteleuropa Messtechnik GmbH", "region": "EMEA", "country": "DE", "city": "München", "tier": "Premier", "currency": "EUR", "specialty": "Industrial and Automotive", "contact_email": "bestellung@mitteleuropa-mess.de", "phone": "+49 89 555 0144"},
    {"code": "DIST-FR-EMEA-008", "name": "Mesure Technologies SAS", "region": "EMEA", "country": "FR", "city": "Paris", "tier": "Authorised", "currency": "EUR", "specialty": "Aerospace", "contact_email": "commandes@mesuretech.fr", "phone": "+33 1 5555 0144"},
    {"code": "DIST-ES-EMEA-009", "name": "Ibérica Instrumentación SL", "region": "EMEA", "country": "ES", "city": "Madrid", "tier": "Authorised", "currency": "EUR", "specialty": "General Purpose", "contact_email": "pedidos@ibericainstr.es", "phone": "+34 91 555 0144"},
    {"code": "DIST-IT-EMEA-010", "name": "Italiana Strumenti Srl", "region": "EMEA", "country": "IT", "city": "Milano", "tier": "Authorised", "currency": "EUR", "specialty": "Industrial", "contact_email": "ordini@italianastrumenti.it", "phone": "+39 02 5555 0144"},
    {"code": "DIST-NL-EMEA-011", "name": "Holland Test BV", "region": "EMEA", "country": "NL", "city": "Eindhoven", "tier": "Authorised", "currency": "EUR", "specialty": "Semiconductor", "contact_email": "bestellingen@hollandtest.nl", "phone": "+31 40 555 0144"},
    {"code": "DIST-CH-EMEA-012", "name": "Helvetia Precision AG", "region": "EMEA", "country": "CH", "city": "Zürich", "tier": "Premier", "currency": "CHF", "specialty": "Precision Instrumentation", "contact_email": "bestellung@helvetiaprecision.ch", "phone": "+41 44 555 0144"},
    {"code": "DIST-SE-EMEA-013", "name": "Nordic Test Solutions AB", "region": "EMEA", "country": "SE", "city": "Stockholm", "tier": "Authorised", "currency": "SEK", "specialty": "Wireless and 5G", "contact_email": "orders@nordictest.se", "phone": "+46 8 5555 0144"},
    {"code": "DIST-IL-EMEA-014", "name": "Holyland Instrumentation Ltd", "region": "EMEA", "country": "IL", "city": "Tel Aviv", "tier": "Authorised", "currency": "ILS", "specialty": "Defense Electronics", "contact_email": "orders@holyland-instr.co.il", "phone": "+972 3 5555 0144"},
    {"code": "DIST-AE-EMEA-015", "name": "Gulf Test Equipment LLC", "region": "EMEA", "country": "AE", "city": "Dubai", "tier": "Authorised", "currency": "AED", "specialty": "General Purpose", "contact_email": "orders@gulftest.ae", "phone": "+971 4 555 0144"},
    # APAC
    {"code": "DIST-CN-APAC-016", "name": "华东测试设备有限公司", "region": "APAC", "country": "CN", "city": "Shanghai", "tier": "Premier", "currency": "CNY", "specialty": "Semiconductor", "contact_email": "orders@huadong-test.com.cn", "phone": "+86 21 5555 0144"},
    {"code": "DIST-CN-APAC-017", "name": "Pearl River Microwave Co Ltd", "region": "APAC", "country": "CN", "city": "Shenzhen", "tier": "Premier", "currency": "CNY", "specialty": "Wireless and 5G", "contact_email": "sales@pearlrivermicrowave.com.cn", "phone": "+86 755 5555 0144"},
    {"code": "DIST-KR-APAC-018", "name": "Korea Instrumentation Co Ltd", "region": "APAC", "country": "KR", "city": "Seoul", "tier": "Premier", "currency": "KRW", "specialty": "Semiconductor and Display", "contact_email": "orders@koreainstr.co.kr", "phone": "+82 2 5555 0144"},
    {"code": "DIST-IN-APAC-019", "name": "Bharat Test Engineering Pvt Ltd", "region": "APAC", "country": "IN", "city": "Bengaluru", "tier": "Authorised", "currency": "INR", "specialty": "Aerospace and Defense", "contact_email": "orders@bharattest.in", "phone": "+91 80 5555 0144"},
    {"code": "DIST-SG-APAC-020", "name": "Lion City T&M Pte Ltd", "region": "APAC", "country": "SG", "city": "Singapore", "tier": "Authorised", "currency": "SGD", "specialty": "Wireless and 5G", "contact_email": "orders@lioncitytm.com.sg", "phone": "+65 6555 0144"},
    {"code": "DIST-TW-APAC-021", "name": "Formosa Test Systems Co", "region": "APAC", "country": "TW", "city": "Taipei", "tier": "Premier", "currency": "TWD", "specialty": "Semiconductor", "contact_email": "orders@formosatestsys.com.tw", "phone": "+886 2 5555 0144"},
    {"code": "DIST-AU-APAC-022", "name": "Southern Cross Test Solutions Pty", "region": "APAC", "country": "AU", "city": "Sydney", "tier": "Authorised", "currency": "AUD", "specialty": "General Purpose", "contact_email": "orders@southerncrosstest.com.au", "phone": "+61 2 5555 0144"},
    {"code": "DIST-TH-APAC-023", "name": "Bangkok Instrument Co Ltd", "region": "APAC", "country": "TH", "city": "Bangkok", "tier": "Authorised", "currency": "THB", "specialty": "General Purpose", "contact_email": "orders@bangkokinstr.co.th", "phone": "+66 2 5555 0144"},
    {"code": "DIST-VN-APAC-024", "name": "Saigon Test Equipment JSC", "region": "APAC", "country": "VN", "city": "Ho Chi Minh City", "tier": "Authorised", "currency": "VND", "specialty": "Semiconductor", "contact_email": "orders@saigontest.com.vn", "phone": "+84 28 5555 0144"},
    {"code": "DIST-MY-APAC-025", "name": "Penang Test Solutions Sdn Bhd", "region": "APAC", "country": "MY", "city": "Penang", "tier": "Authorised", "currency": "MYR", "specialty": "Semiconductor", "contact_email": "orders@penangtest.com.my", "phone": "+60 4 5555 0144"},
    # Japan
    {"code": "DIST-JP-JPN-026", "name": "東京計測器販売", "region": "JP", "country": "JP", "city": "Tokyo", "tier": "Premier", "currency": "JPY", "specialty": "General Purpose", "contact_email": "chumon@tokyokeisokuki.co.jp", "phone": "+81 3 5555 0144"},
    {"code": "DIST-JP-JPN-027", "name": "大阪測定機器", "region": "JP", "country": "JP", "city": "Osaka", "tier": "Premier", "currency": "JPY", "specialty": "Industrial", "contact_email": "chumon@osaka-sokutei.co.jp", "phone": "+81 6 5555 0144"},
    {"code": "DIST-JP-JPN-028", "name": "名古屋自動車テスト機材", "region": "JP", "country": "JP", "city": "Nagoya", "tier": "Authorised", "currency": "JPY", "specialty": "Automotive", "contact_email": "chumon@nagoyajidousha.co.jp", "phone": "+81 52 5555 0144"},
    {"code": "DIST-JP-JPN-029", "name": "横浜マイクロ波販売", "region": "JP", "country": "JP", "city": "Yokohama", "tier": "Authorised", "currency": "JPY", "specialty": "Wireless and 5G", "contact_email": "chumon@yokohama-microwave.co.jp", "phone": "+81 45 5555 0144"},
    {"code": "DIST-JP-JPN-030", "name": "福岡電子計測", "region": "JP", "country": "JP", "city": "Fukuoka", "tier": "Authorised", "currency": "JPY", "specialty": "General Purpose", "contact_email": "chumon@fukuokadenshi.co.jp", "phone": "+81 92 5555 0144"},
]


# ----------------------------------------------------------------------
# Magic SKUs lookup (referenced in routing rules)
# ----------------------------------------------------------------------

MAGIC_SKUS = {
    "CUSTOM-PRODUCT": {"description": "Customer-specific custom product, requires engineering quote", "routing": "engineering_quote"},
    "SOWDUMMY": {"description": "Statement-of-Work routing placeholder", "routing": "sow_team"},
    "EXPORTDUMMY": {"description": "Non-US destination, routes through Export Control review", "routing": "export_control"},
}


# ----------------------------------------------------------------------
# Main: emit module content as Python source
# ----------------------------------------------------------------------

def main():
    out: list[str] = []
    out.append('"""Generated catalog extras: customers, products, distributors, magic SKUs.')
    out.append('')
    out.append('Source of truth: app/synthetic/_build_catalog_extra.py (deterministic generator).')
    out.append('Regenerate with:  python -m app.synthetic._build_catalog_extra > app/synthetic/catalog_extra.py')
    out.append('"""')
    out.append('')

    customers: list[dict[str, Any]] = []
    for i, spec in enumerate(AMS_COMPANIES, start=1):
        customers.append(_build_ams_customer(i, spec))
    for i, spec in enumerate(EMEA_COMPANIES, start=1):
        customers.append(_build_emea_customer(i, spec))
    for i, spec in enumerate(APAC_COMPANIES, start=1):
        customers.append(_build_apac_customer(i, spec))
    for i, spec in enumerate(JP_COMPANIES, start=1):
        customers.append(_build_jp_customer(i, spec))

    pp = pprint.PrettyPrinter(indent=2, width=200, sort_dicts=False)
    out.append(f"CUSTOMERS_EXTRA = {pp.pformat(customers)}")
    out.append('')
    out.append(f"PRODUCTS_EXTRA = {pp.pformat(NEW_PRODUCTS)}")
    out.append('')
    out.append(f"DISTRIBUTORS = {pp.pformat(DISTRIBUTORS)}")
    out.append('')
    out.append(f"MAGIC_SKUS = {pp.pformat(MAGIC_SKUS)}")
    out.append('')
    print('\n'.join(out))


if __name__ == "__main__":
    main()
